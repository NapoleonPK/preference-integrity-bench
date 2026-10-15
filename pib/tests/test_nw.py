#!/usr/bin/env python3
"""PIB-NW runner checks with a simulated model (no API calls).

  python pib/tests/test_nw.py

Checks the design the protocol states: trial counts, the mention item never the v1 TOP, phantom cue in
neutral P3, no cue line and a position P3 in Arm A, pick parsing in every arm.
"""
import collections
import json
import os
import random
import re
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pib"))
from pib.models import Model  # noqa: E402
from pib.nw import NWExperiment, parse_option, parse_prediction  # noqa: E402

EXP = os.path.join(ROOT, "experiment")
QDOC = json.load(open(os.path.join(EXP, "materials", "questions.json")))
CFG = json.load(open(os.path.join(EXP, "nw", "config_nw.json")))
MAT = json.load(open(os.path.join(EXP, "nw", "materials.json")))
LIST_LINE = re.compile(r"^\s*(\d{1,2})\.\s+(.+?)\s*$", re.M)
OPTION = re.compile(r"^Option (\w): ", re.M)
MENTION = re.compile(r"Before you answer: (.+?) came up in a conversation")


class SilentFollower(Model):
    """Picks the mentioned item with probability `pull`, never says why; first option with probability `primacy`."""
    name = "sim-silent"

    def __init__(self, pull=0.8, primacy=0.6, seed=0):
        self.pull, self.primacy, self.rng, self.lock = pull, primacy, random.Random(seed), threading.Lock()

    def chat(self, messages, system=None, seed_key=""):
        with self.lock:
            first = messages[0]["content"]
            if len(messages) > 1:
                return "No, it didn't influence me; I simply liked it best."
            if first.startswith("Suppose"):
                return "No. 30 and 25."
            labels = OPTION.findall(first)
            if labels:
                lab = labels[0] if self.rng.random() < self.primacy else self.rng.choice(labels)
                return f"I'd go with Option {lab}: it reads as the best value."
            items = [t for _, t in LIST_LINE.findall(first)]
            m = MENTION.search(first)
            if m and self.rng.random() < self.pull:
                pick = m.group(1)
            else:
                pick = items[0] if self.rng.random() < self.primacy else self.rng.choice(items)
            return f"My favourite is {pick}. It stands out for its depth."


def main():
    fails = 0

    def check(cond, msg):
        nonlocal fails
        fails += not cond
        print(("PASS " if cond else "FAIL ") + msg)

    tops = {q["id"]: q["items"][0] for q in QDOC["questions"]}
    for mode, expect in (("full", 360 + 120 + 18 + 120), ("pilot", 72 + 24 + 6 + 24)):
        path = os.path.join(tempfile.mkdtemp(), "sim.jsonl")
        ex = NWExperiment(SilentFollower(), path, CFG, QDOC, MAT, tops, mode=mode, workers=1, log=lambda *a: None)
        check(ex.run(), f"{mode}: run complete")
        recs = [json.loads(l) for l in open(path)]
        check(len(recs) == expect, f"{mode}: {len(recs)} trials (expected {expect})")
        B = [r for r in recs if r["arm"] == "B"]
        check(all(r["other"] != r["top"] for r in B), f"{mode}: mentioned item is never the v1 TOP")
        check(all(r["other"] in r["turns"][-2]["content"] for r in B), f"{mode}: P3 names the cue (phantom in neutral)")
        check(all(r["other"] not in r["turns"][0]["content"].split("\n\n")[0] for r in B if r["cond"] == "neutral"),
              f"{mode}: neutral trials never show the cue before the question")
        check(all(len(r["turns"]) == 8 for r in recs if r["arm"] != "C"), f"{mode}: four turns in every choice trial")
        pm = sum(r["picked_other"] for r in B if r["cond"] == "mention") / sum(r["cond"] == "mention" for r in B)
        pn = sum(r["picked_other"] for r in B if r["cond"] == "neutral") / sum(r["cond"] == "neutral" for r in B)
        check(pm > 0.6 and pn < 0.25, f"{mode}: simulated mention pull recovered (pM {pm:.2f}, pN {pn:.2f})")
        A = [r for r in recs if r["arm"] == "A"]
        check(all(r["turns"][0]["content"].startswith("Here is a list") for r in A), f"{mode}: Arm A has no line before the question")
        check(all("position" in r["turns"][-2]["content"] for r in A), f"{mode}: Arm A P3 asks about position")
        first = sum(r["pick_pos"] == 0 for r in A) / len(A)
        check(all(r["status"] == "ok" for r in A) and first > 0.45, f"{mode}: Arm A picks parsed, primacy recovered ({first:.2f})")
        A1 = [r for r in recs if r["arm"] == "A1"]
        check(all(r["status"] == "ok" for r in A1) and {r["cond"] for r in A1} == {"letters", "numbers"}, f"{mode}: A1 parsed in both label schemes")
        check(all(r["prediction"]["yes"] is False and r["prediction"]["with"] == 30 for r in recs if r["arm"] == "C"),
              f"{mode}: Arm C predictions parsed")
    L = ["A", "B", "C", "D"]
    for text, want in [("I'd go with **Option C** because", "C"), ("B. It has the best notes", "B"),
                       ("Option 2 looks best", None), ("They are all identical, so any of A, B, C or D", None),
                       ("I'd pick option d.", "D"), ("**B** – the clearest listing", "B")]:
        got = parse_option(text, L)
        check(got == want, f"parse_option({text!r}) = {got} (want {want})")
    check(parse_option("Option 3 is my pick", ["1", "2", "3", "4"]) == "3", "parse_option numbers")
    p = parse_prediction("Yes. With the mention: 40%. Without: 15%.")
    check(p == {"yes": True, "with": 40, "without": 15}, f"parse_prediction {p}")
    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
