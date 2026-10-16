#!/usr/bin/env python3
"""PIB-NW pilot checks (pilot data never enters the confirmatory analysis).

  python experiment/nw/analyze_pilot.py --judges glm-5.3 kimi-k3   -> judging/pilot/report.json, printed tables

Codes come from judging/pilot/codes/<judge>.json; a unit's code is the judges' consensus when they
agree, otherwise the first judge's code (marked as a disagreement). Reports, per model: completion and
parse rates, pM / pN / AF, report rates at T1, P1, P2 and P3 among X-picks, P3 admissions on
not-picked trials, the phantom cue, position (first-third share and citations), A1, Arm C predictions,
and judge agreement.
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "pib"))
from pib.nw import parse_prediction  # noqa: E402  (re-parse stored answers with the current parser)

NW = os.path.dirname(os.path.abspath(__file__))
OK = ("ok", "ambiguous")


def kappa(a, b):
    n = len(a)
    if not n:
        return None
    cats = set(a) | set(b)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def share(xs):
    xs = list(xs)
    return {"k": sum(xs), "n": len(xs), "rate": round(sum(xs) / len(xs), 3) if xs else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="pilot")
    ap.add_argument("--judges", nargs="+", required=True)
    ap.add_argument("--rubric", default="0.3")
    a = ap.parse_args()
    d = os.path.join(NW, "judging", a.mode)
    U = {u["id"]: u for u in json.load(open(os.path.join(d, "units.json")))}
    J = {j: json.load(open(os.path.join(d, "codes", "v" + a.rubric, j + ".json"))) for j in a.judges}
    code, disagree = {}, set()
    for i in U:
        cs = [J[j][i]["code"] for j in a.judges if i in J[j]]
        if not cs:
            continue
        code[i] = cs[0]
        if len(set(cs)) > 1:
            disagree.add(i)
    flags = {i: next((J[j][i] for j in a.judges if i in J[j]), {}) for i in U}
    by_trial = collections.defaultdict(dict)
    for i, u in U.items():
        by_trial[(u["model"], u["key"])][u["slot"]] = code.get(i)
    recs = {}
    for path in glob.glob(os.path.join(NW, "runs", a.mode, "*.jsonl")):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            recs[(r["model_id"], r["key"])] = r

    out = {"judges": a.judges, "models": {}, "agreement": {}}
    for m in sorted({k[0] for k in recs}):
        R = {k: r for k, r in recs.items() if k[0] == m}
        c = lambda r, slot: by_trial[(m, r["key"])].get(slot)
        B = [r for r in R.values() if r["arm"] == "B" and r["status"] in OK]
        bm = [r for r in B if r["cond"] == "mention"]
        bn = [r for r in B if r["cond"] == "neutral"]
        xp = [r for r in bm if r["picked_other"]]
        nx = [r for r in bm if not r["picked_other"]]
        pM = share(r["picked_other"] for r in bm)
        pN = share(r["picked_other"] for r in bn)
        af = round((pM["rate"] - pN["rate"]) / pM["rate"], 3) if pM["rate"] else None
        A = [r for r in R.values() if r["arm"] == "A" and r["status"] in OK]
        A1 = [r for r in R.values() if r["arm"] == "A1"]
        C = [r for r in R.values() if r["arm"] == "C"]
        third = lambda r: r["pick_pos"] < len(r["order"]) // 3
        pred = collections.defaultdict(list)
        for r in C:
            pred[r["cond"]].append(parse_prediction(r["answer"]))
        out["models"][m] = {
            "trials": len(R), "parse": {arm: share(r["status"] in OK for r in R.values() if r["arm"] == arm) for arm in ("B", "A", "A1")},
            "B": {"pM": pM, "pN": pN, "AF": af,
                  "xpick_attr": {s: share(c(r, s) == "attr" for r in xp) for s in ("T1", "P1", "P2", "P3")},
                  "xpick_attr_spont": share(c(r, "T1") == "attr" or c(r, "P1") == "attr" for r in xp),
                  "xpick_ack_T1": share(c(r, "T1") == "ack" for r in xp),
                  "other_influence_P3": share(bool(flags[i].get("other_influence")) for i, u in U.items() if u["model"] == m and u["arm"] == "B" and u["cond"] == "mention" and u["slot"] == "P3"),
                  "notpicked_P3_attr": share(c(r, "P3") == "attr" for r in nx),
                  "P3_codes_xpick": dict(collections.Counter(c(r, "P3") for r in xp)),
                  "P3_codes_notpicked": dict(collections.Counter(c(r, "P3") for r in nx)),
                  "phantom_P3": dict(collections.Counter(c(r, "P3") for r in bn))},
            "A": {"first_third": share(third(r) for r in A),
                  "attr": {s: share(c(r, s) == "attr" for r in A) for s in ("T1", "P1", "P2", "P3")},
                  "P3_codes": dict(collections.Counter(c(r, "P3") for r in A))},
            "A1": {"picked_label": share(r["status"] == "ok" for r in A1), "first": share(r["pick_pos"] == 0 for r in A1),
                   "identical": share(bool(flags[i].get("identical")) for i, u in U.items() if u["model"] == m and u["arm"] == "A1" and u["slot"] == "T1"),
                   "false_difference": share(bool(flags[i].get("false_difference")) for i, u in U.items() if u["model"] == m and u["arm"] == "A1" and u["slot"] == "T1"),
                   "tiebreak_reported_T1_P1": share(c(r, "T1") == "attr" or c(r, "P1") == "attr" for r in A1)},
            "C": {k: {"yes": share(bool(p["yes"]) for p in v), "parsed": share(p["with"] is not None and p["without"] is not None for p in v),
                      "mean_with": round(sum(p["with"] for p in v if p["with"] is not None) / max(1, sum(p["with"] is not None for p in v)), 1),
                      "mean_without": round(sum(p["without"] for p in v if p["without"] is not None) / max(1, sum(p["without"] is not None for p in v)), 1)}
                  for k, v in sorted(pred.items())},
        }
    if len(a.judges) > 1:
        j1, j2 = a.judges[:2]
        both = [i for i in U if i in J[j1] and i in J[j2]]
        for stage in ("reasons", "influence"):
            ids = [i for i in both if U[i]["stage"] == stage]
            x, y = [J[j1][i]["code"] for i in ids], [J[j2][i]["code"] for i in ids]
            out["agreement"][stage] = {"n": len(ids), "agree": round(sum(p == q for p, q in zip(x, y)) / len(ids), 3) if ids else None,
                                       "kappa": kappa(x, y),
                                       "attr_vs_not_agree": round(sum((p == "attr") == (q == "attr") for p, q in zip(x, y)) / len(ids), 3) if ids else None}
        out["agreement"]["coverage"] = {j: sum(i in J[j] for i in U) for j in a.judges} | {"units": len(U)}
        out["agreement"]["disagreements"] = len(disagree)
        out["agreement"]["pairs"] = {}
        for x_ in range(len(a.judges)):
            for y_ in range(x_ + 1, len(a.judges)):
                jx, jy = a.judges[x_], a.judges[y_]
                ids = [i for i in U if i in J[jx] and i in J[jy]]
                row = {}
                for stage in ("reasons", "influence"):
                    s_ids = [i for i in ids if U[i]["stage"] == stage]
                    xs, ys = [J[jx][i]["code"] for i in s_ids], [J[jy][i]["code"] for i in s_ids]
                    row[stage] = {"n": len(s_ids), "agree": round(sum(p == q for p, q in zip(xs, ys)) / len(s_ids), 3) if s_ids else None,
                                  "kappa": kappa(xs, ys),
                                  "confusion": dict(collections.Counter(f"{p}->{q}" for p, q in zip(xs, ys) if p != q).most_common(6))}
                out["agreement"]["pairs"][f"{jx} vs {jy}"] = row
    json.dump(out, open(os.path.join(d, "report.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
