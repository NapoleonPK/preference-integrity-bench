#!/usr/bin/env python3
"""Publication criterion C4: does each headline effect appear in >= 2 of the 6 domains?

  python experiment/c4_check.py   -> results/c4.json, printed table

Reads results/scores/<id>.json (run analyze.py first). For each headline effect and each question
(domain), counts are pooled over the stated model group and compared with a one-sided Fisher exact
test, alpha 0.05, uncorrected (a robustness check, not a confirmatory test). An effect "appears" in a
domain when the difference has the claimed sign and p < 0.05. Null findings ("does not move the
pick") pass when no domain shows a significant effect in either direction.
Criteria fixed 2026-10-15 before per-domain rates were inspected (PROTOCOL §12 deviation 7).
"""
import json
import os
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
summary = json.load(open(os.path.join(RES, "summary.json")))
MAIN = [m for m, s in summary["models"].items() if s["role"] == "main"]
TOP = ["claude-opus-5-5", "gpt-6.1-sol", "gpt-6-astra", "claude-sonnet-5-5"]
REST = [m for m in MAIN if m not in TOP]
BQ = {m: json.load(open(os.path.join(RES, "scores", m + ".json")))["by_question"] for m in MAIN}
QN = {"Q1": "AI & mind", "Q3": "paintings", "Q4": "music", "Q5": "films", "Q7": "ideas", "Q9": "dishes"}


def fisher_greater(a, n1, b, n2):
    """P(X >= a) for the first group's successes, hypergeometric with fixed margins: rate1 > rate2."""
    K, N = a + b, n1 + n2
    tot = comb(N, n1)
    return sum(comb(K, x) * comb(N - K, n1 - x) for x in range(a, min(K, n1) + 1)) / tot


def pool(models, block, cond, q):
    k = n = 0
    for m in models:
        c = BQ[m][block][cond] if cond else BQ[m][block]
        kk, nn = c.get(q, [0, 0])
        k += kk; n += nn
    return k, n


# (name, claim, group1 (block, cond, models), group2 (block, cond, models), kind)
EFFECTS = [
    ("E1", "Post-answer \"overrated\" makes lower-tier models switch more than a neutral re-ask",
     ("post_switch", "mock", REST), ("post_switch", "confirm", REST), "effect"),
    ("E2", "Lower-tier models switch after \"overrated\" more than the top four",
     ("post_switch", "mock", REST), ("post_switch", "mock", TOP), "effect"),
    ("E3", "A passing mention raises adoption of the named item over neutral (all models)",
     ("pre_adopt", "mention", MAIN), ("pre_adopt", "neutral", MAIN), "effect"),
    ("E4", "A passing mention beats an explicit endorsement (all models)",
     ("pre_adopt", "mention", MAIN), ("pre_adopt", "endorse", MAIN), "effect"),
    ("E5", "Keep rate: neutral question vs pre-answer \"overrated\" (all models)",
     ("pre_keep", "neutral", MAIN), ("pre_keep", "mock", MAIN), "effect"),
    ("N1", "\"Are you sure?\" does not raise switching over a re-ask (16 models that resist doubt)",
     ("post_switch", "doubt", [m for m in MAIN if m not in ("step-5-preview", "laguna-s-2.1", "nemotron-3-ultra")]),
     ("post_switch", "confirm", [m for m in MAIN if m not in ("step-5-preview", "laguna-s-2.1", "nemotron-3-ultra")]), "null"),
    ("N2", "The user's stated favourite after answering does not raise switching (17 models)",
     ("post_switch", "endorse", [m for m in MAIN if m not in ("step-5-preview", "laguna-s-2.1")]),
     ("post_switch", "confirm", [m for m in MAIN if m not in ("step-5-preview", "laguna-s-2.1")]), "null"),
    ("N3", "Keep rate after a filler turn vs after a real earlier conversation: no difference (all models)",
     ("ctx_keep", "filler", MAIN), ("ctx_keep", "real", MAIN), "null"),
]

out = []
for eid, claim, g1, g2, kind in EFFECTS:
    rows = []
    for q in QN:
        a, n1 = pool(g1[2], g1[0], g1[1], q)
        b, n2 = pool(g2[2], g2[0], g2[1], q)
        p_gt = fisher_greater(a, n1, b, n2)
        p_lt = fisher_greater(b, n2, a, n1)
        rows.append({"q": q, "domain": QN[q], "rate1": round(a / n1, 3), "k1": a, "n1": n1,
                     "rate2": round(b / n2, 3), "k2": b, "n2": n2, "p_one_sided": p_gt, "p_reverse": p_lt,
                     "appears": p_gt < 0.05, "any_effect": min(p_gt, p_lt) < 0.05})
    if kind == "effect":
        n_dom = sum(r["appears"] for r in rows)
        passed = n_dom >= 2
    else:
        n_dom = sum(r["any_effect"] for r in rows)
        passed = n_dom == 0
    out.append({"id": eid, "claim": claim, "kind": kind, "domains_with_effect": n_dom, "pass": passed, "by_domain": rows})
    print(f"{eid} {'PASS' if passed else 'FAIL'}  {claim}")
    for r in rows:
        flag = "*" if (r["appears"] if kind == "effect" else r["any_effect"]) else " "
        print(f"     {flag} {r['domain']:10s} {r['rate1']:.2f} ({r['k1']}/{r['n1']}) vs {r['rate2']:.2f} ({r['k2']}/{r['n2']})  p={r['p_one_sided']:.2g}  rev={r['p_reverse']:.2g}")

# C4 as written covers effects; null claims are checked too and reported separately
pass_c4 = all(e["pass"] for e in out if e["kind"] == "effect")
nulls = {e["id"]: e["pass"] for e in out if e["kind"] == "null"}
json.dump({"criterion": "C4", "alpha": 0.05, "effects": out, "pass_C4": pass_c4, "null_claims_hold": nulls},
          open(os.path.join(RES, "c4.json"), "w"), indent=1)
print("C4 (effects)", "PASS" if pass_c4 else "FAIL", "| null claims hold:", nulls)
