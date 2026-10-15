#!/usr/bin/env python3
"""Score every completed run and apply the confirmatory analysis (PROTOCOL.md §7).

  python experiment/analyze.py            # -> results/scores/<id>.json, results/summary.json, results/leaderboard.md
  python experiment/analyze.py --B 200    # faster bootstrap while checking

Every run is re-read with the current parser. Only runs with >= 95% of planned samples are scored.
Primary tests T1-T8 of all `main` models form one Holm family.
"""
import argparse
import json
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pib"))
from pib.score_v1 import ScoreV1, reparse  # noqa: E402
from pib.stats import holm  # noqa: E402
from pib.v1 import Experiment  # noqa: E402

RUNS = os.environ.get("PIB_RUNS", os.path.join(HERE, "runs"))   # override only for tests
RES = os.environ.get("PIB_RESULTS", os.path.join(HERE, "results"))
CFG = json.load(open(os.path.join(HERE, "config.json")))
QDOC = json.load(open(os.path.join(HERE, "materials", "questions.json")))
CDOC = json.load(open(os.path.join(HERE, "materials", "contexts.json")))
QS = [q for q in QDOC["questions"] if q["id"] in CFG["questions"]]
ROSTER = json.load(open(os.path.join(HERE, "models.json")))["models"]
COMPONENTS = ["presentation_invariance", "conformity_resistance", "pushback_resistance", "context_stability", "coherence"]


def load(mid):
    p = os.path.join(RUNS, mid + ".jsonl")
    if not os.path.exists(p):
        return None, None
    recs = [json.loads(l) for l in open(p, encoding="utf-8")]
    meta_p = p[:-6] + ".meta.json"
    planned = json.load(open(meta_p))["sessions"][-1].get("planned") if os.path.exists(meta_p) else None
    # a run that was killed or is still running has no meta file yet: use the design's count
    return recs, planned or Experiment.planned(SimpleNamespace(cfg=CFG, C=CDOC["contexts"], Q=QS))


def fmt(v, ci=None):
    if v is None:
        return "n/a"
    s = f"{v:.2f}"
    if ci and ci[0] is not None:
        s += f" [{ci[0]:.2f}, {ci[1]:.2f}]"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--B", type=int, default=CFG["bootstrap_B"])
    a = ap.parse_args()
    os.makedirs(os.path.join(RES, "scores"), exist_ok=True)
    scores = {}
    for m in ROSTER:
        recs, planned = load(m["id"])
        if not recs:
            continue
        if planned and len(recs) < 0.95 * planned:
            print(f"skip {m['id']}: {len(recs)}/{planned} samples")
            continue
        s = ScoreV1(reparse(recs, QS), QS).score(B=a.B)
        s["model"] = m
        scores[m["id"]] = s
        json.dump(s, open(os.path.join(RES, "scores", m["id"] + ".json"), "w"), indent=1, ensure_ascii=False, default=str)
        print(f"scored {m['id']}: integrity {fmt(s['components']['integrity'])}")

    # ---- confirmatory family: T1-T8 across main models, Holm
    family = [(mid, t, p) for mid, s in scores.items() if s["model"]["role"] == "main" for t, p in s["tests"].items()]
    adj = holm([p for _, _, p in family])
    for (mid, t, p), q in zip(family, adj):
        scores[mid].setdefault("tests_holm", {})[t] = q

    # ---- controls: harness (A2) and retest (C5)
    controls = []
    for mid, s in scores.items():
        ref = s["model"].get("control_of")
        if ref and ref in scores:
            d = {c: (None if s["components"][c] is None or scores[ref]["components"][c] is None
                     else round(s["components"][c] - scores[ref]["components"][c], 3)) for c in COMPONENTS + ["integrity"]}
            controls.append({"run": mid, "reference": ref, "role": s["model"]["role"], "difference": d,
                             "pass_integrity_within_0.05": d["integrity"] is not None and abs(d["integrity"]) <= 0.05})

    summary = {"version": CFG["version"], "models": {mid: {"label": s["model"]["label"], "role": s["model"]["role"],
               "components": s["components"], "ci95": s["ci95"], "tests_holm": s.get("tests_holm"),
               "descriptive": s["descriptive"]} for mid, s in scores.items()}, "controls": controls}
    json.dump(summary, open(os.path.join(RES, "summary.json"), "w"), indent=1, ensure_ascii=False, default=str)

    # ---- leaderboard
    main_ids = sorted((mid for mid, s in scores.items() if s["model"]["role"] == "main"),
                      key=lambda mid: -(scores[mid]["components"]["integrity"] or -1))
    L = ["| Model | Integrity | " + " | ".join(c.replace("_", " ").capitalize() for c in COMPONENTS) + " | Names a pick |",
         "|---" * (len(COMPONENTS) + 3) + "|"]
    for mid in main_ids:
        s = scores[mid]
        ci = s["ci95"] or {}
        L.append(f"| {s['model']['label']} | {fmt(s['components']['integrity'], ci.get('integrity'))} | " +
                 " | ".join(fmt(s["components"][c], ci.get(c)) for c in COMPONENTS) +
                 f" | {fmt(s['descriptive']['expression_rate'])} |")
    L += ["", "Significant after Holm correction (p_adj < 0.05):", ""]
    for mid in main_ids:
        sig = [t.split("_", 1)[0] for t, q in (scores[mid].get("tests_holm") or {}).items() if q is not None and q < CFG["alpha"]]
        L.append(f"- {scores[mid]['model']['label']}: {', '.join(sig) or 'none'}")
    if controls:
        L += ["", "Controls (difference vs reference run):", ""]
        L += [f"- {c['run']} vs {c['reference']}: integrity {c['difference']['integrity']:+.3f} "
              f"({'pass' if c['pass_integrity_within_0.05'] else 'FAIL'})" for c in controls if c['difference']['integrity'] is not None]
    open(os.path.join(RES, "leaderboard.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
