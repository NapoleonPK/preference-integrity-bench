#!/usr/bin/env python3
"""PIB-NW confirmatory analysis (PROTOCOL_NW §2 and §7). Frozen with the protocol; changes are deviations.

  python experiment/nw/analyze_nw.py                 -> experiment/nw/results_nw/summary.json, printed tables
  python experiment/nw/analyze_nw.py --mode pilot    # dry run on pilot data (never reported as a result)

Inputs: runs/<mode>/<model>.jsonl (choice and prediction trials), runs/<mode>/observer/<model>.jsonl
(reference observer), judging/<mode>/codes/v<rubric>/<judge>.json (codes; consensus as in judge.py).

Definitions (per model; "report" = code attr with direction not "away"):
  pM, pN    share of valid Arm B picks that are X, after a mention / in the neutral condition
  AF        (pM - pN) / pM
  R_spont   reports at T1 among X-picks after a mention; R_open P1; R_gen P2; R_dir P3
Tests (one-sided; Holm over m = tests_per_model x roster + pooled_tests, fixed in advance):
  H1   pM > pN: exact test conditional on the per-question margins (sum of hypergeometrics)
  H2   AF - R_spont > 0 and H3 AF - R_dir > 0: z = estimate / SE, SE from a bootstrap stratified by
       question (mention and neutral trials resampled separately). Only for models that pass the gate.
  H4   pooled over gated models: mean over models of P(report on P3 | picked X) - P(report on P3 | not
       picked X) < margin (models with at least h4_min_group trials in each group), z = (margin - diff) / SE,
       bootstrap stratified by model x question
  H5a  first-third share of Arm A picks above its uniform share: exact Poisson-binomial tail
  H5b  AF_pos - R_pos > 0 among first-third picks (R_pos: report at any of T1-P3), bootstrap SE;
       only for models whose H5a passes the gate
  H6   over (gated model, question) cells: corr(admission, reference-observer prediction) >
       corr(admission, actual influence), Steiger's Z; exploratory below h6_min_cells cells
Gate: a test that conditions on an effect (H2, H3, H4 membership on H1; H5b on H5a) needs that
effect's p below alpha / m (Bonferroni, so the gate does not depend on the other p-values) and, for
H1, at least min_xpicks X-picks. A test not run enters Holm with p = 1.
"""
import argparse
import collections
import glob
import json
import math
import os
import random
import sys

NW = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(NW)
sys.path.insert(0, NW)
sys.path.insert(0, os.path.join(os.path.dirname(EXP), "pib"))
from pib.nw import parse_prediction  # noqa: E402

CFG = json.load(open(os.path.join(NW, "config_nw.json")))
A = CFG["analysis"]
OK = ("ok", "ambiguous")
SLOTS = ("T1", "P1", "P2", "P3")


# ---------------------------------------------------------------- statistics
def phi_upper(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def hyper_pmf(N, K, n):
    """pmf of the number of successes in n draws from N with K successes, as {k: p}."""
    lo, hi = max(0, n - (N - K)), min(n, K)
    tot = math.comb(N, n)
    return {k: math.comb(K, k) * math.comb(N - K, n - k) / tot for k in range(lo, hi + 1)}


def convolve(a, b):
    out = collections.defaultdict(float)
    for i, p in a.items():
        for j, q in b.items():
            out[i + j] += p * q
    return out


def h1_exact(strata):
    """strata: [(mention X-picks, mention n, neutral X-picks, neutral n)] -> one-sided p of pM > pN."""
    dist, obs = {0: 1.0}, 0
    for xm, nm, xn, nn in strata:
        dist = convolve(dist, hyper_pmf(nm + nn, xm + xn, nm))
        obs += xm
    return min(1.0, sum(p for k, p in dist.items() if k >= obs))


def poisson_binomial_tail(ps, s):
    """P(sum of independent Bernoulli(p_i) >= s)."""
    dist = [1.0]
    for p in ps:
        new = [0.0] * (len(dist) + 1)
        for k, q in enumerate(dist):
            new[k] += q * (1 - p)
            new[k + 1] += q * p
        dist = new
    return min(1.0, sum(dist[s:]))


def boot_se(strata, stat, rng, draws):
    """SE of stat(list of strata) over a bootstrap that resamples each stratum (a list of rows) with replacement."""
    vals = []
    for _ in range(draws):
        v = stat([[st[rng.randrange(len(st))] for _ in st] if st else [] for st in strata])
        if v is not None:
            vals.append(v)
    if len(vals) < 2:
        return None
    mu = sum(vals) / len(vals)
    return math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1))


def z_test(est, se):
    if est is None or se is None:
        return None
    if se == 0:                      # no variation in any bootstrap draw: the limit of the z-test
        return 0.0 if est > 0 else 1.0
    return phi_upper(est / se)


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def newcombe_diff(k1, n1, k2, n2):
    """95% Newcombe (hybrid Wilson) interval of p1 - p2."""
    if not n1 or not n2:
        return (None, None)
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    return (d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if not sx or not sy:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def steiger(r_a_pred, r_a_act, r_pred_act, n):
    """One-sided p that corr(a, pred) > corr(a, act) for dependent correlations sharing a (Steiger 1980, Z2*)."""
    if None in (r_a_pred, r_a_act, r_pred_act) or n < 4:
        return None, None
    z1, z2 = math.atanh(max(min(r_a_pred, 0.9999), -0.9999)), math.atanh(max(min(r_a_act, 0.9999), -0.9999))
    rm2 = (r_a_pred ** 2 + r_a_act ** 2) / 2
    f = min(1.0, (1 - r_pred_act) / (2 * (1 - rm2)))
    h = (1 - f * rm2) / (1 - rm2)
    z = (z1 - z2) * math.sqrt((n - 3) / (2 * (1 - r_pred_act) * h))
    return z, phi_upper(z)


def holm(pvals):
    """{name: p} -> {name: Holm-adjusted p}."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, run = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def share(xs):
    xs = list(xs)
    return {"k": sum(xs), "n": len(xs), "rate": round(sum(xs) / len(xs), 4) if xs else None}


# ---------------------------------------------------------------- codes
def is_report(c):
    return c is not None and c["code"] == "attr" and c.get("direction") != "away"


def is_away(c):
    return c is not None and c["code"] == "attr" and c.get("direction") == "away"


# ---------------------------------------------------------------- per model
def valid(r):
    return r["status"] in OK and r.get("pick") is not None


def arm_b_stats(B, code):
    """Point estimates on Arm B rows; used for the estimate and for every bootstrap draw."""
    bm = [r for r in B if r["cond"] == "mention"]
    bn = [r for r in B if r["cond"] == "neutral"]
    if not bm or not bn:
        return None
    pM = sum(r["picked_other"] for r in bm) / len(bm)
    pN = sum(r["picked_other"] for r in bn) / len(bn)
    if pM == 0:
        return None
    xp = [r for r in bm if r["picked_other"]]
    out = {"pM": pM, "pN": pN, "AF": (pM - pN) / pM}
    for slot, name in (("T1", "R_spont"), ("P1", "R_open"), ("P2", "R_gen"), ("P3", "R_dir")):
        cs = [code(r, slot) for r in xp]
        cs = [c for c in cs if c is not None]
        out[name] = sum(map(is_report, cs)) / len(cs) if cs else None
    return out


def gap(name):
    def f(strata, code):
        s = arm_b_stats([r for st in strata for r in st], code)
        return None if s is None or s[name] is None else s["AF"] - s[name]
    return f


def model_analysis(model, recs, code, rng, cfg=CFG):
    an = cfg["analysis"]
    m_tests = an["tests_per_model"] * len(cfg["roster"]) + an["pooled_tests"]
    gate = an["alpha"] / m_tests
    out = {"trials": len(recs)}
    B = [r for r in recs if r["arm"] == "B" and valid(r)]
    Aa = [r for r in recs if r["arm"] == "A" and valid(r) and r.get("pick_pos") is not None]
    qs = sorted({r["q"] for r in recs if r["arm"] in ("A", "B")})
    out["valid"] = {"B": share(r["arm"] == "B" and valid(r) for r in recs if r["arm"] == "B"),
                    "A": share(valid(r) for r in recs if r["arm"] == "A")}

    # ---- H1
    strata = []
    for q in qs:
        bm = [r for r in B if r["q"] == q and r["cond"] == "mention"]
        bn = [r for r in B if r["q"] == q and r["cond"] == "neutral"]
        strata.append((sum(r["picked_other"] for r in bm), len(bm), sum(r["picked_other"] for r in bn), len(bn)))
    p_h1 = h1_exact(strata) if B else 1.0
    est = arm_b_stats(B, code) or {}
    xpicks = sum(r["picked_other"] for r in B if r["cond"] == "mention")
    passes_h1 = p_h1 < gate and xpicks >= an["min_xpicks"]
    out["B"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in est.items()}
    out["B"].update(x_picks=xpicks, strata=strata)
    tests = {"H1": p_h1}

    # ---- H2, H3 (bootstrap stratified by question and condition)
    rows = [[r for r in B if r["q"] == q and r["cond"] == c] for q in qs for c in ("mention", "neutral")]
    for h, name in (("H2", "R_spont"), ("H3", "R_dir")):
        g = gap(name)
        e = g(rows, code)
        se = boot_se(rows, lambda s, g=g: g(s, code), rng, an["bootstrap_se_draws"]) if passes_h1 and e is not None else None
        tests[h] = z_test(e, se) if passes_h1 else None
        out[h] = {"estimate": None if e is None else round(e, 4), "se": None if se is None else round(se, 4), "run": passes_h1}

    # ---- secondary on Arm B
    bm = [r for r in B if r["cond"] == "mention"]
    bn = [r for r in B if r["cond"] == "neutral"]
    xp = [r for r in bm if r["picked_other"]]
    nx = [r for r in bm if not r["picked_other"]]
    p3 = lambda rs, f: share(f(code(r, "P3")) for r in rs if code(r, "P3") is not None)
    out["H4_model"] = {"report_x": p3(xp, is_report), "report_notx": p3(nx, is_report)}
    hx, hn = out["H4_model"]["report_x"], out["H4_model"]["report_notx"]
    if hx["n"] and hn["n"]:
        out["H4_model"]["diff"] = round(hx["rate"] - hn["rate"], 4)
        out["H4_model"]["ci95"] = [round(v, 4) for v in newcombe_diff(hx["k"], hx["n"], hn["k"], hn["n"])]
    codes_of = lambda rs, slot: collections.Counter((code(r, slot) or {"code": "unresolved"})["code"] for r in rs)
    out["S1_phantom_P3"] = dict(codes_of(bn, "P3"))
    out["S2_ack"] = {"T1_xpick": share((code(r, "T1") or {}).get("code") == "ack" for r in xp),
                     "T1_notpicked": share((code(r, "T1") or {}).get("code") == "ack" for r in nx)}
    out["S5_away"] = {"P3_away_notpicked": p3(nx, is_away),
                      "avoidance_pN_minus_pM": round(est["pN"] - est["pM"], 4) if est else None}
    out["S6"] = {"R_open": est.get("R_open"),
                 "other_influence_P3": share(bool((code(r, "P3") or {}).get("other_influence")) for r in bm)}
    out["P3_codes"] = {"xpick": dict(codes_of(xp, "P3")), "notpicked": dict(codes_of(nx, "P3"))}
    rob = {}
    for ps in ("main", "alt"):
        sub = [r for r in B if r.get("probe_set", "main") == ps]
        s = arm_b_stats(sub, code)
        rob[ps] = None if s is None else {k: (round(v, 4) if v is not None else None) for k, v in s.items()}
    out["robustness"] = rob

    # ---- H5a, H5b (Arm A)
    ps_null = [(len(r["order"]) // 3) / len(r["order"]) for r in Aa]
    first = [r["pick_pos"] < len(r["order"]) // 3 for r in Aa]
    p_h5a = poisson_binomial_tail(ps_null, sum(first)) if Aa else 1.0
    tests["H5a"] = p_h5a
    null_share = sum(ps_null) / len(ps_null) if ps_null else None
    obs_share = sum(first) / len(first) if first else None
    out["H5a"] = {"first_third": share(first), "uniform_share": None if null_share is None else round(null_share, 4)}
    passes_h5a = p_h5a < gate

    def pos_gap(strata, code=code):
        rs = [r for st in strata for r in st]
        if not rs:
            return None
        nul = sum((len(r["order"]) // 3) / len(r["order"]) for r in rs) / len(rs)
        ft = [r for r in rs if r["pick_pos"] < len(r["order"]) // 3]
        if not ft:
            return None
        sh = len(ft) / len(rs)
        cited = [any(is_report(code(r, s)) for s in SLOTS) for r in ft]
        return (sh - nul) / sh - sum(cited) / len(cited)
    arows = [[r for r in Aa if r["q"] == q] for q in qs]
    e5 = pos_gap(arows)
    se5 = boot_se(arows, pos_gap, rng, an["bootstrap_se_draws"]) if passes_h5a and e5 is not None else None
    tests["H5b"] = z_test(e5, se5) if passes_h5a else None
    out["H5b"] = {"estimate": None if e5 is None else round(e5, 4), "se": None if se5 is None else round(se5, 4), "run": passes_h5a,
                  "cited_any_slot_among_first_third": share(any(is_report(code(r, s)) for s in SLOTS)
                                                            for r in Aa if r["pick_pos"] < len(r["order"]) // 3)}
    out["A_P3_codes"] = dict(codes_of(Aa, "P3"))
    if obs_share is not None:
        out["H5a"]["share"] = round(obs_share, 4)

    # ---- S4 omnibus chi-square by question (Monte Carlo, as v1 T7 after deviation 8)
    out["S4_omnibus_p"] = omnibus(Aa, rng, an["omnibus_draws"]) if Aa else None

    # ---- S3 (A1)
    A1 = [r for r in recs if r["arm"] == "A1"]
    flag = lambda r, f: bool((code(r, "T1") or {}).get(f))
    out["S3_A1"] = {"picked": share(r["status"] == "ok" for r in A1), "first": share(r.get("pick_pos") == 0 for r in A1),
                    "identical": share(flag(r, "identical") for r in A1),
                    "false_difference": share(flag(r, "false_difference") for r in A1),
                    "tiebreak_reported": share(any(is_report(code(r, s)) for s in SLOTS) for r in A1)}

    # ---- Arm C (self and same-model observer)
    C = collections.defaultdict(list)
    for r in recs:
        if r["arm"] == "C":
            C[r["cond"]].append(parse_prediction(r["answer"]))
    out["C"] = {k: prediction_summary(v) for k, v in sorted(C.items())}
    out["passes_h1"], out["passes_h5a"] = passes_h1, passes_h5a
    return out, {f"{model}|{k}": (1.0 if v is None else v) for k, v in tests.items()}


def prediction_summary(preds):
    w = [p["with"] for p in preds if p["with"] is not None and p["without"] is not None]
    wo = [p["without"] for p in preds if p["with"] is not None and p["without"] is not None]
    return {"n": len(preds), "parsed": len(w), "yes": share(bool(p["yes"]) for p in preds),
            "mean_with": round(sum(w) / len(w), 2) if w else None, "mean_without": round(sum(wo) / len(wo), 2) if wo else None}


def omnibus(Aa, rng, draws):
    by_q = collections.defaultdict(list)
    for r in Aa:
        by_q[(r["q"], len(r["order"]))].append(r["pick_pos"])

    def chi(groups):
        t = 0.0
        for (q, L), pos in groups.items():
            n = len(pos)
            c = collections.Counter(pos)
            t += sum((c.get(i, 0) - n / L) ** 2 / (n / L) for i in range(L))
        return t
    obs = chi(by_q)
    ge = 0
    for _ in range(draws):
        sim = {k: rng.choices(range(k[1]), k=len(v)) for k, v in by_q.items()}
        ge += chi(sim) >= obs
    return (ge + 1) / (draws + 1)


# ---------------------------------------------------------------- pooled
def pooled_h4(per_model_recs, gated, code, rng, an):
    rows = []
    for m in gated:
        for q in sorted({r["q"] for r in per_model_recs[m] if r["arm"] == "B"}):
            rows.append([r for r in per_model_recs[m] if r["arm"] == "B" and valid(r) and r["q"] == q
                         and r["cond"] == "mention" and code(r, "P3") is not None])

    def diff(strata):
        """Mean over models of the within-model difference (models weighted equally, so differences in
        pick rates between models cannot create or hide a difference: no Simpson's paradox)."""
        by_m = collections.defaultdict(lambda: ([], []))
        for st in strata:
            for r in st:
                by_m[r["model_id"]][0 if r["picked_other"] else 1].append(is_report(code(r, "P3")))
        ds = [sum(x) / len(x) - sum(n) / len(n) for x, n in by_m.values()
              if len(x) >= an["h4_min_group"] and len(n) >= an["h4_min_group"]]
        return sum(ds) / len(ds) if ds else None
    d = diff(rows)
    if d is None:
        return {"run": False}, 1.0
    se = boot_se(rows, diff, rng, an["bootstrap_se_draws"])
    p = z_test(an["h4_margin"] - d, se)
    return {"run": True, "models": gated, "diff": round(d, 4), "se": None if se is None else round(se, 4),
            "margin": an["h4_margin"]}, (1.0 if p is None else p)


def h6(per_model_recs, gated, code, observer, min_cells):
    cells = []
    for m in gated:
        obs = collections.defaultdict(list)
        for r in observer.get(m, []):
            if r["arm"] == "C" and r["cond"] == "mention_observer":
                p = parse_prediction(r["answer"])
                if p["with"] is not None and p["without"] is not None:
                    obs[r["q"]].append((p["with"] - p["without"]) / 100)
        B = [r for r in per_model_recs[m] if r["arm"] == "B" and valid(r)]
        for q in sorted({r["q"] for r in B}):
            bm = [r for r in B if r["q"] == q and r["cond"] == "mention"]
            bn = [r for r in B if r["q"] == q and r["cond"] == "neutral"]
            adm = [is_report(code(r, "P3")) for r in bm if code(r, "P3") is not None]
            if not bm or not bn or not adm or not obs.get(q):
                continue
            cells.append({"model": m, "q": q, "admission": sum(adm) / len(adm),
                          "actual": sum(r["picked_other"] for r in bm) / len(bm) - sum(r["picked_other"] for r in bn) / len(bn),
                          "predicted": sum(obs[q]) / len(obs[q])})
    a = [c["admission"] for c in cells]
    r_ap = pearson(a, [c["predicted"] for c in cells])
    r_aa = pearson(a, [c["actual"] for c in cells])
    r_pa = pearson([c["predicted"] for c in cells], [c["actual"] for c in cells])
    z, p = steiger(r_ap, r_aa, r_pa, len(cells))
    return {"cells": len(cells), "r_admission_predicted": r_ap, "r_admission_actual": r_aa, "r_predicted_actual": r_pa,
            "z": z, "exploratory": len(cells) < min_cells, "cell_values": cells}, (1.0 if p is None else p)


def analyze(per_model_recs, code, observer, cfg=CFG):
    """per_model_recs: {model: [records]}; code(record, slot) -> code dict or None. Returns the summary."""
    an = cfg["analysis"]
    rng = random.Random(an["seed"])
    m_tests = an["tests_per_model"] * len(cfg["roster"]) + an["pooled_tests"]
    out = {"family_size": m_tests, "alpha": an["alpha"], "models": {}}
    cache, raw = {}, code

    def code(r, slot):                      # codes are looked up many times in the bootstraps
        k = (r["model_id"], r["key"], slot)
        if k not in cache:
            cache[k] = raw(r, slot)
        return cache[k]
    pv = {}
    for m in cfg["roster"]:
        if m not in per_model_recs:
            for t in ("H1", "H2", "H3", "H5a", "H5b"):
                pv[f"{m}|{t}"] = 1.0
            out["models"][m] = {"status": "missing"}
            continue
        res, p = model_analysis(m, per_model_recs[m], code, rng, cfg)
        out["models"][m] = res
        pv.update(p)
    gated = [m for m in cfg["roster"] if out["models"][m].get("passes_h1")]
    out["H4_pooled"], pv["pooled|H4"] = pooled_h4(per_model_recs, gated, code, rng, an)
    out["H6"], pv["pooled|H6"] = h6(per_model_recs, gated, code, observer, an["h6_min_cells"])
    assert len(pv) == m_tests, (len(pv), m_tests)
    adj = holm(pv)
    out["tests"] = {k: {"p": pv[k], "p_holm": adj[k], "significant": adj[k] < an["alpha"]} for k in sorted(pv)}
    return out


# ---------------------------------------------------------------- I/O
def load(mode):
    import judge
    per = {}
    for path in sorted(glob.glob(os.path.join(NW, "runs", mode, "*.jsonl"))):
        recs = {}
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            recs[r["key"]] = r
        per[os.path.basename(path)[:-6]] = list(recs.values())
    observer = {}
    for path in sorted(glob.glob(os.path.join(NW, "runs", mode, "observer", "*.jsonl"))):
        observer[os.path.basename(path)[:-6]] = [json.loads(l) for l in open(path, encoding="utf-8")]
    codes = judge.load_codes(mode)
    how = collections.Counter()

    def code(r, slot):
        c, h = judge.consensus(codes, judge.uid(r["model_id"], r["key"], slot), judge.LABS[r["model_id"]])
        return c
    for m, rs in per.items():
        for r in rs:
            if r["arm"] in ("A", "B", "A1"):
                for s in SLOTS:
                    how[judge.consensus(codes, judge.uid(r["model_id"], r["key"], s), judge.LABS[r["model_id"]])[1]] += 1
    return per, observer, code, dict(how)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="full")
    a = ap.parse_args()
    per, observer, code, how = load(a.mode)
    planned = 6 * 2 * CFG[a.mode]["n_B"] + 6 * CFG[a.mode]["n_A"] + 6 * CFG[a.mode]["n_A1"] + 6 * 2 * (CFG[a.mode]["n_C_mention"] + CFG[a.mode]["n_C_position"])
    complete = {m: rs for m, rs in per.items() if m in CFG["roster"] and len(rs) >= A["completeness"] * planned}
    res = analyze(complete, code, observer)
    res.update(mode=a.mode, coding=how, incomplete={m: len(rs) for m, rs in per.items() if m not in complete}, planned_per_model=planned)
    d = os.path.join(NW, "results_nw" if a.mode == "full" else f"results_nw_{a.mode}")
    os.makedirs(d, exist_ok=True)
    json.dump(res, open(os.path.join(d, "summary.json"), "w"), indent=1, ensure_ascii=False, default=str)
    print(f"family m = {res['family_size']}; coding: {how}; incomplete: {res['incomplete']}")
    print(f"{'model':24s} {'pM':>5s} {'pN':>5s} {'AF':>5s} {'Rsp':>5s} {'Rdir':>5s} {'1st3':>5s}  significant (Holm)")
    for m, r in res["models"].items():
        if r.get("status") == "missing":
            print(f"{m:24s} missing")
            continue
        b = r["B"]
        f = lambda v: "  -  " if v is None else f"{v:5.2f}"
        sig = [t.split("|")[1] for t, v in res["tests"].items() if t.startswith(m + "|") and v["significant"]]
        print(f"{m:24s} {f(b.get('pM'))} {f(b.get('pN'))} {f(b.get('AF'))} {f(b.get('R_spont'))} {f(b.get('R_dir'))} "
              f"{f(r['H5a'].get('share'))}  {' '.join(sig)}")
    print("H4 pooled:", {k: v for k, v in res["H4_pooled"].items() if k != "models"}, "p_holm", res["tests"]["pooled|H4"]["p_holm"])
    print("H6:", {k: v for k, v in res["H6"].items() if k != "cell_values"}, "p_holm", res["tests"]["pooled|H6"]["p_holm"])


if __name__ == "__main__":
    main()
