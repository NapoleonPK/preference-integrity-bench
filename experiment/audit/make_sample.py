#!/usr/bin/env python3
"""Parser audit (criterion B1): draw a stratified random sample of answers for hand-labelling.

  python experiment/audit/make_sample.py [--n 150]
  -> audit/sample.csv   (fill in human_pick and human_status; do NOT look at sample_key.json first)
  -> audit/sample_key.json   (parser output, hidden from the labeller)

Stratified so that every main model and every answer type (paragraph answers, name-only
follow-ups, pairwise) is represented. human_status: ok | hedge (declines / no favourite) | none.
"""
import argparse, csv, json, os, random, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pib"))
from pib.score_v1 import reparse

ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=150); a = ap.parse_args()
cfg = json.load(open(os.path.join(HERE, "config.json")))
QS = [q for q in json.load(open(os.path.join(HERE, "materials", "questions.json")))["questions"] if q["id"] in cfg["questions"]]
items = {q["id"]: q["items"] for q in QS}
roster = [m for m in json.load(open(os.path.join(HERE, "models.json")))["models"] if m["role"] == "main"]
pool = []
for m in roster:
    p = os.path.join(os.environ.get("PIB_RUNS", os.path.join(HERE, "runs")), m["id"] + ".jsonl")
    if not os.path.exists(p):
        continue
    for r in reparse([json.loads(l) for l in open(p)], QS):
        if r["block"] in ("base", "pre", "ctx"):
            pool.append((m["id"], "paragraph", r, r["answer"], items[r["q"]], r["pick"], r["status"]))
        elif r["block"] == "post" and len(r["turns"]) == 4:
            pool.append((m["id"], "follow-up", r, r["turns"][3]["content"], items[r["q"]], r["pick"], r["status"]))
        elif r["block"] == "pair":
            pool.append((m["id"], "pairwise", r, r["answer"], r["order"], r["pick"], "ok" if r["pick"] else "none"))
rng = random.Random("pib-v1.0-audit")
strata = {}
for x in pool:
    strata.setdefault((x[0], x[1]), []).append(x)
per = max(1, a.n // max(1, len(strata)))
sample = []
for k in sorted(strata):
    sample += rng.sample(strata[k], min(per, len(strata[k])))
rest = [x for x in pool if x not in sample]
sample += rng.sample(rest, max(0, min(len(rest), a.n - len(sample))))
rng.shuffle(sample)
with open(os.path.join(HERE, "audit", "sample.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["audit_id", "answer_type", "options", "answer", "human_pick", "human_status"])
    for i, (mid, kind, r, ans, opts, _, _) in enumerate(sample):
        w.writerow([i, kind, " | ".join(opts), ans, "", ""])
json.dump([{"audit_id": i, "model_id": mid, "key": r["key"], "parser_pick": pk, "parser_status": st}
           for i, (mid, kind, r, ans, opts, pk, st) in enumerate(sample)],
          open(os.path.join(HERE, "audit", "sample_key.json"), "w"), indent=1, ensure_ascii=False)
print(len(sample), "answers from", len(pool), "->", "audit/sample.csv")
