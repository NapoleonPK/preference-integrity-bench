#!/usr/bin/env python3
"""Build the Hugging Face dataset folder from the runs and results.

  python experiment/export_hf.py            -> hf/  (then: huggingface-cli upload <user>/preference-integrity-bench hf/ --repo-type dataset)

Layout
  hf/README.md                         dataset card (from hf_card_template.md + results)
  hf/data/conversations/<model>.jsonl  one row per sample, with the full transcript
  hf/data/scores.jsonl                 one row per model: components, 95% CIs, Holm-adjusted tests
  hf/materials/                        questions, contexts (with WildChat provenance), config, protocol
  hf/checks/                           parser audit (sample, blind labels, parser key, report) and the C4 domain check
  hf/results/                          summary.json and leaderboard.md as written by analyze.py

Runs below the 95% completeness threshold are exported with run_role "incomplete" and scored = false;
they are never in scores.jsonl. Only roster runs are exported (runs/smoke is not).
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pib"))
from pib.score_v1 import reparse  # noqa: E402

OUT = os.environ.get("PIB_HF_OUT", os.path.join(ROOT, "hf"))
RUNS = os.environ.get("PIB_RUNS", os.path.join(HERE, "runs"))   # override only for tests
CFG = json.load(open(os.path.join(HERE, "config.json")))
QDOC = json.load(open(os.path.join(HERE, "materials", "questions.json")))
QS = [q for q in QDOC["questions"] if q["id"] in CFG["questions"]]
DOMAIN = {q["id"]: q["domain"] for q in QS}
ROSTER = {m["id"]: m for m in json.load(open(os.path.join(HERE, "models.json")))["models"]}
RES = os.environ.get("PIB_RESULTS", os.path.join(HERE, "results"))
SUMMARY = os.path.join(RES, "summary.json")


def row(r, m, scored):
    return {
        "model_id": m["id"], "model_label": m["label"], "lab": m["lab"], "harness": m["harness"],
        "open_weights": m["open_weights"], "run_role": m["role"] if scored else "incomplete", "scored": scored,
        "pib_version": r["pib_version"], "seed": r["seed"],
        "sample_key": r["key"], "block": r["block"], "condition": r["cond"], "question_id": r["q"],
        "question_domain": DOMAIN[r["q"]], "context_id": r.get("ctx"), "sample": r["sample"],
        "item_order": r["order"], "top_item": r.get("top"), "other_item": r.get("other"),
        "first_pick": r.get("first_pick"), "turns": r["turns"], "final_answer": r["answer"],
        "pick": r["pick"], "timestamp": r["ts"],
        # pairwise records keep the runner's placeholder status; derive it from the parsed pick (as audit/make_sample.py does)
        "pick_status": ("ok" if r["pick"] else "none") if r["block"] == "pair" else r["status"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", default="TODO-REPO-URL")
    ap.add_argument("--contact", default="TODO-CONTACT")
    ap.add_argument("--author", default="TODO-AUTHOR")
    a = ap.parse_args()
    summ = json.load(open(SUMMARY)) if os.path.exists(SUMMARY) else {"models": {}, "controls": []}
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "data", "conversations"))
    os.makedirs(os.path.join(OUT, "materials"))
    n_rows, models, incomplete = 0, [], []
    for mid, m in ROSTER.items():
        p = os.path.join(RUNS, mid + ".jsonl")
        if not os.path.exists(p):
            continue
        recs = reparse([json.loads(l) for l in open(p, encoding="utf-8")], QS)
        scored = mid in summ["models"]
        if not scored:
            incomplete.append(f"{m['label']} ({len(recs)}/930)")
        with open(os.path.join(OUT, "data", "conversations", mid.replace("@", "__") + ".jsonl"), "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(row(r, m, scored), ensure_ascii=False) + "\n")
        n_rows += len(recs)
        models.append(m)
    with open(os.path.join(OUT, "data", "scores.jsonl"), "w", encoding="utf-8") as f:
        for mid, s in summ["models"].items():
            f.write(json.dumps({"model_id": mid, **s}, ensure_ascii=False, default=str) + "\n")
    for name in ["config.json", "models.json", "PROTOCOL.md", "materials/questions.json", "materials/contexts.json",
                 "selection/manual_review.json"]:
        shutil.copy(os.path.join(HERE, name), os.path.join(OUT, "materials", os.path.basename(name)))
    os.makedirs(os.path.join(OUT, "checks"))
    os.makedirs(os.path.join(OUT, "results"))
    for name in ["audit/sample.csv", "audit/sample_key.json", "audit/report.json", "audit/make_sample.py", "audit/score_audit.py",
                 "c4_check.py", os.path.join(RES, "c4.json")]:
        shutil.copy(os.path.join(HERE, name), os.path.join(OUT, "checks", os.path.basename(name)))
    for name in ["summary.json", "leaderboard.md"]:
        shutil.copy(os.path.join(RES, name), os.path.join(OUT, "results", name))
    audit = json.load(open(os.path.join(HERE, "audit", "report.json")))
    c4 = json.load(open(os.path.join(RES, "c4.json")))
    ctl = {c["run"]: c["difference"]["integrity"] for c in summ.get("controls", [])}
    board = open(os.path.join(RES, "leaderboard.md")).read() if os.path.exists(os.path.join(RES, "leaderboard.md")) else "_Results pending._"
    card = open(os.path.join(HERE, "hf_card_template.md")).read()
    n_main = sum(1 for s in summ["models"].values() if s["role"] == "main")
    fill = {
        "N_ROWS": f"{n_rows:,}", "N_RUNS": str(len(models)), "N_MAIN": str(n_main), "LEADERBOARD": board,
        "INCOMPLETE": ", ".join(incomplete) or "none",
        "AUDIT_N": str(audit["labelled"]), "AUDIT_AGREE": f"{audit['agreement'] * 100:.1f}",
        "AUDIT_K": str(round(audit["agreement"] * audit["labelled"])), "AUDIT_HEDGES": str(audit["hedges"]),
        "C4_EFFECTS": str(sum(e["pass"] for e in c4["effects"] if e["kind"] == "effect")),
        "CTL_CODEX": f"{ctl.get('gpt-6-luna@codex', float('nan')):+.3f}", "CTL_OPENCODE": f"{ctl.get('nemotron-3-ultra@opencode', float('nan')):+.3f}",
        "CTL_RETEST": f"{ctl.get('claude-haiku-5-5@retest', float('nan')):+.3f}",
        "REPO_URL": a.repo_url, "CONTACT": a.contact, "AUTHOR": a.author,
    }
    for k, v in fill.items():
        card = card.replace("{{" + k + "}}", v)
    assert "{{" not in card, "unfilled placeholder in the card"
    open(os.path.join(OUT, "README.md"), "w").write(card)
    print(f"hf/: {n_rows} conversations from {len(models)} runs ({n_main} scored main models; incomplete: {fill['INCOMPLETE']})")
    if "TODO" in a.repo_url + a.contact + a.author:
        print("note: pass --repo-url, --contact and --author before uploading")


if __name__ == "__main__":
    main()
