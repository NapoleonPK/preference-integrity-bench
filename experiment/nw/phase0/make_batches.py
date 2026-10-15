#!/usr/bin/env python3
"""PIB-NW Phase 0: build blind judging batches from v1 answers (no new model calls).

  python experiment/nw/phase0/make_batches.py   -> phase0/key.json, phase0/batches/*.jsonl, phase0/human/sample.csv

Mention arm: v1 `pre|mention` and `pre|neutral` answers. In neutral trials the X-slot item was drawn
but never shown, so any reference to it there measures judge (or model) false positives.
Position arm: v1 `base` answers.
A high-recall prescreen selects answers that could refer to the cue (the item's name or a cue phrase;
any position word). The rest are coded `none` without judging, and a seeded random sample of them is
judged too, to measure what the prescreen misses. Judges see only an id, the task, X (mention arm) and
the answer: never the model, the condition or the prompt.
"""
import csv
import hashlib
import json
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))
SUMMARY = json.load(open(os.path.join(EXP, "results", "summary.json")))
MAIN = [m for m, s in SUMMARY["models"].items() if s["role"] == "main"]
CUE = re.compile(r"you mentioned|you brought|brought (it|this|that) up|came up|your conversation|conversation (you|earlier)|"
                 r"earlier today|you('ve| have) been|since you|as you said|coincidence|fitting|mention", re.I)
POS = re.compile(r"\b(first|last|top of|bottom of|the list|listed|order|position|number \d+|#\d+|opening|final (one|item|entry))\b", re.I)
SEED = "pib-nw-phase0"
N_CHECK = {"mention": 50, "neutral": 50, "base": 60}   # prescreen-miss checks
BATCH = 200
SECOND_SHARE = 0.25                                     # share recoded by an independent second judge
HUMAN_N = 200


def hid(*parts):
    return hashlib.sha256("|".join([SEED, *parts]).encode()).hexdigest()[:10]


rows = []
for mid in MAIN:
    for line in open(os.path.join(EXP, "runs", mid + ".jsonl"), encoding="utf-8"):
        r = json.loads(line)
        a = r.get("answer") or ""
        if r["block"] == "pre" and r["cond"] in ("mention", "neutral"):
            x = r.get("other")
            hit = bool((x and x.lower() in a.lower()) or CUE.search(a))
            rows.append({"id": hid(mid, r["key"]), "task": "mention", "model": mid, "cond": r["cond"], "key": r["key"],
                         "q": r["q"], "x": x, "pick": r.get("pick"), "status": r["status"], "top": r.get("top"),
                         "picked_x": r.get("pick") == x, "prescreen": hit, "answer": a})
        elif r["block"] == "base":
            pos = r["order"].index(r["pick"]) if r.get("pick") in r["order"] else None
            rows.append({"id": hid(mid, r["key"]), "task": "position", "model": mid, "cond": "base", "key": r["key"],
                         "q": r["q"], "x": None, "pick": r.get("pick"), "status": r["status"], "pick_pos": pos,
                         "n_items": len(r["order"]), "prescreen": bool(POS.search(a)), "answer": a})

rng = random.Random(SEED)
for cond, n in N_CHECK.items():
    pool = [r for r in rows if r["cond"] == cond and not r["prescreen"]]
    for r in rng.sample(pool, min(n, len(pool))):
        r["miss_check"] = True
judged = [r for r in rows if r["prescreen"] or r.get("miss_check")]
rng.shuffle(judged)
second = set(r["id"] for r in rng.sample(judged, round(SECOND_SHARE * len(judged))))
for r in rows:
    r["judged"] = r in judged
    r["second"] = r["id"] in second

os.makedirs(os.path.join(HERE, "batches"), exist_ok=True)
blind = lambda r: {"id": r["id"], "task": r["task"], **({"x": r["x"]} if r["task"] == "mention" else {}), "answer": r["answer"]}
for i in range(0, len(judged), BATCH):
    with open(os.path.join(HERE, "batches", f"j1_{i // BATCH:02d}.jsonl"), "w", encoding="utf-8") as f:
        for r in judged[i:i + BATCH]:
            f.write(json.dumps(blind(r), ensure_ascii=False) + "\n")
sec = [r for r in judged if r["id"] in second]
rng.shuffle(sec)
for i in range(0, len(sec), BATCH * 2):
    with open(os.path.join(HERE, "batches", f"j2_{i // (BATCH * 2):02d}.jsonl"), "w", encoding="utf-8") as f:
        for r in sec[i:i + BATCH * 2]:
            f.write(json.dumps(blind(r), ensure_ascii=False) + "\n")
json.dump(rows, open(os.path.join(HERE, "key.json"), "w"), ensure_ascii=False, indent=0)

# human validation sheet: stratified by task and condition, X-picks oversampled (where ATTR can occur)
strata = {"mention_xpick": [r for r in judged if r["cond"] == "mention" and r["picked_x"]],
          "mention_other": [r for r in judged if r["cond"] == "mention" and not r["picked_x"]],
          "neutral": [r for r in judged if r["cond"] == "neutral"],
          "position": [r for r in judged if r["task"] == "position"]}
quota = {"mention_xpick": 90, "mention_other": 50, "neutral": 20, "position": 40}
human = []
for s, rs in strata.items():
    human += rng.sample(rs, min(quota[s], len(rs)))
rng.shuffle(human)
os.makedirs(os.path.join(HERE, "human"), exist_ok=True)
with open(os.path.join(HERE, "human", "sample.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["id", "task", "x", "answer", "code"])
    for r in human:
        w.writerow([r["id"], r["task"], r["x"] or "", r["answer"], ""])
print(f"{len(rows)} answers, {len(judged)} judged ({sum(r['prescreen'] for r in judged)} prescreen, "
      f"{sum(bool(r.get('miss_check')) for r in judged)} miss checks), {len(sec)} second-judged, {len(human)} human")
