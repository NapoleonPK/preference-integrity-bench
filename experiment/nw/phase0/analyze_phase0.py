#!/usr/bin/env python3
"""PIB-NW Phase 0 analysis (exploratory: this v1 data has been seen).

  python experiment/nw/phase0/analyze_phase0.py   -> phase0/results.json, printed tables

Codes: first judge (codes/j1_*.json) for every judged answer; answers outside the prescreen are `none`.
Second judge (codes/j2_*.json) on a random 25% gives agreement and Cohen's kappa.
"""
import collections
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(EXP), "pib"))
from pib.stats import wilson  # noqa: E402

rows = json.load(open(os.path.join(HERE, "key.json")))
SUMMARY = json.load(open(os.path.join(EXP, "results", "summary.json")))
LABEL = {m: s["label"] for m, s in SUMMARY["models"].items()}
j1, j2 = {}, {}
for f in glob.glob(os.path.join(HERE, "codes", "j1_*.json")):
    j1.update(json.load(open(f)))
for f in glob.glob(os.path.join(HERE, "codes", "j2_*.json")):
    j2.update(json.load(open(f)))
judged = [r for r in rows if r["judged"]]
missing = [r["id"] for r in judged if r["id"] not in j1]
assert not missing, f"{len(missing)} judged answers have no code"
for r in rows:
    r["code"] = j1[r["id"]] if r["judged"] else "none"
OK = ("ok", "ambiguous")


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": [round(x, 3) for x in wilson(k, n)] if n else None}


def kappa(a, b, cats):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else None


out = {"note": "Exploratory. v1 data, already analysed; first judge = Claude subagents (inherited model), second judge = Claude Sonnet subagent.",
       "models": {}, "pooled": {}, "position": {}, "checks": {}}

# ---------------- mention arm
M = [r for r in rows if r["task"] == "mention"]
models = list(dict.fromkeys(r["model"] for r in M))
pool = collections.Counter()
for m in models:
    mm = [r for r in M if r["model"] == m and r["cond"] == "mention" and r["status"] in OK]
    nn = [r for r in M if r["model"] == m and r["cond"] == "neutral" and r["status"] in OK]
    xp = [r for r in mm if r["picked_x"]]
    ox = [r for r in mm if not r["picked_x"]]
    pM = len(xp) / len(mm)
    pN = sum(r["picked_x"] for r in nn) / len(nn)
    af = (pM - pN) / pM if pM else None
    c = lambda rs, code: sum(r["code"] == code for r in rs)
    d = {"label": LABEL[m], "pM": rate(len(xp), len(mm)), "pN": rate(sum(r["picked_x"] for r in nn), len(nn)),
         "AF": round(af, 3) if af is not None else None,
         "xpick_attr": rate(c(xp, "attr"), len(xp)), "xpick_ack": rate(c(xp, "ack"), len(xp)),
         "xpick_any": rate(c(xp, "attr") + c(xp, "ack"), len(xp)),
         "other_attr": rate(c(ox, "attr"), len(ox)), "other_ack": rate(c(ox, "ack"), len(ox)),
         "neutral_any": rate(sum(r["code"] != "none" for r in nn), len(nn))}
    d["gap_AF_minus_attr"] = round(af - d["xpick_attr"]["rate"], 3) if af is not None and xp else None
    out["models"][m] = d
    for k, v in (("mm", len(mm)), ("xp", len(xp)), ("nn", len(nn)), ("nx", sum(r["picked_x"] for r in nn)),
                 ("xa", c(xp, "attr")), ("xk", c(xp, "ack")), ("oa", c(ox, "attr")), ("ok_", c(ox, "ack")), ("ox", len(ox)),
                 ("na", sum(r["code"] != "none" for r in nn))):
        pool[k] += v
pM, pN = pool["xp"] / pool["mm"], pool["nx"] / pool["nn"]
out["pooled"] = {"pM": rate(pool["xp"], pool["mm"]), "pN": rate(pool["nx"], pool["nn"]), "AF": round((pM - pN) / pM, 3),
                 "xpick_attr": rate(pool["xa"], pool["xp"]), "xpick_ack": rate(pool["xk"], pool["xp"]),
                 "other_attr": rate(pool["oa"], pool["ox"]), "other_ack": rate(pool["ok_"], pool["ox"]),
                 "neutral_any": rate(pool["na"], pool["nn"])}

# does reporting track influence across models? (Spearman, models with >= 10 X-picks)
def ranks(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]:
            j += 1
        for t in range(i, j + 1):
            r[o[t]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return cov / math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))


eligible = [m for m, d in out["models"].items() if d["pM"]["k"] >= 10]
out["pooled"]["spearman_pM_vs_attr"] = {"n_models": len(eligible), "rho": round(spearman(
    [out["models"][m]["pM"]["rate"] for m in eligible], [out["models"][m]["xpick_attr"]["rate"] for m in eligible]), 3)}

# ---------------- position arm
P = [r for r in rows if r["task"] == "position"]
for m in dict.fromkeys(r["model"] for r in P):
    pp = [r for r in P if r["model"] == m and r["status"] in OK and r["pick_pos"] is not None]
    third = lambda r: r["n_items"] // 3            # positions 1..floor(K/3)
    first = sum(r["pick_pos"] < third(r) for r in pp)
    last = sum(r["pick_pos"] >= r["n_items"] - third(r) for r in pp)
    exp_edge = sum(third(r) / r["n_items"] for r in pp)
    holm = (SUMMARY["models"][m]["tests_holm"] or {}).get("T7_position_bias")
    out["position"][m] = {"label": LABEL[m], "n": len(pp), "first_third": rate(first, len(pp)), "last_third": rate(last, len(pp)),
                          "expected_each": round(exp_edge / len(pp), 3), "T7_holm": holm,
                          "T7_significant": holm is not None and holm < 0.05,
                          "ack": sum(r["code"] == "ack" for r in pp), "attr": sum(r["code"] == "attr" for r in pp)}

# ---------------- checks
mc = [r for r in rows if r.get("miss_check")]
out["checks"]["prescreen_misses"] = {"judged": len(mc), "non_none": sum(j1[r["id"]] != "none" for r in mc),
                                     "ids": [r["id"] for r in mc if j1[r["id"]] != "none"]}
both = [r["id"] for r in judged if r["id"] in j2]
a, b = [j1[i] for i in both], [j2[i] for i in both]
ab, bb = [x == "attr" for x in a], [x == "attr" for x in b]
out["checks"]["second_judge"] = {
    "n": len(both), "agreement": round(sum(x == y for x, y in zip(a, b)) / len(both), 3),
    "kappa_3way": round(kappa(a, b, ["none", "ack", "attr"]), 3),
    "agreement_attr_vs_not": round(sum(x == y for x, y in zip(ab, bb)) / len(both), 3),
    "kappa_attr_vs_not": round(kappa(ab, bb, [True, False]), 3),
    "confusion": dict(collections.Counter(f"{x}->{y}" for x, y in zip(a, b) if x != y))}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, ensure_ascii=False)

# ---------------- print
p = lambda d: f"{d['rate'] * 100:3.0f}%" if d["rate"] is not None else "  - "
print(f"{'model':24s} {'pM':>5s} {'pN':>5s} {'AF':>5s} | X-picks: {'attr':>5s} {'ack':>5s} | other: {'attr':>5s} {'ack':>5s} | neutral any")
for m, d in sorted(out["models"].items(), key=lambda kv: -kv[1]["pM"]["rate"]):
    print(f"{d['label'][:24]:24s} {p(d['pM'])} {p(d['pN'])} {d['AF'] if d['AF'] is not None else '-':>5} | {d['pM']['k']:3d}  {p(d['xpick_attr'])} {p(d['xpick_ack'])} | {p(d['other_attr'])} {p(d['other_ack'])} | {p(d['neutral_any'])}")
P_ = out["pooled"]
print(f"{'POOLED':24s} {p(P_['pM'])} {p(P_['pN'])} {P_['AF']:>5} | {pool['xp']:3d}  {p(P_['xpick_attr'])} {p(P_['xpick_ack'])} | {p(P_['other_attr'])} {p(P_['other_ack'])} | {p(P_['neutral_any'])}")
print("spearman pM vs attr:", P_["spearman_pM_vs_attr"])
print("\nposition (base answers): model, n, first third, last third, expected each, T7 holm, ack, attr")
for m, d in sorted(out["position"].items(), key=lambda kv: kv[1]["T7_holm"] or 1):
    print(f"  {d['label'][:24]:24s} {d['n']:4d} {p(d['first_third'])} {p(d['last_third'])} {d['expected_each']:.2f} {d['T7_holm'] if d['T7_holm'] is None else round(d['T7_holm'], 4)!s:>8} {d['ack']:3d} {d['attr']:3d}")
print("\nchecks:", json.dumps(out["checks"], indent=1))
