#!/usr/bin/env python3
"""PIB-NW power by simulation at the real Holm threshold (PROTOCOL_NW §2, §6).

  python experiment/nw/power.py   -> power_results.json, printed table

Per model, Arm B has 180 mention and 180 neutral trials (30 per question). The worst case for Holm
is the smallest p-value compared with alpha / m, m = 78 confirmatory tests (6 per model x 13 models),
so a test is counted as detecting the effect when p < 0.05 / 78. That is conservative: under Holm the
later tests are compared with larger thresholds.

H2: AF - R_T1 > 0 (one-sided), z-test with a stratified bootstrap SE (by question; 300 draws), per model.
H4: P(attr on P3 | picked X) - P(attr on P3 | not picked) < 0.30 (one-sided, Newcombe-Wilson interval).
H5a: first-third share > uniform share (exact binomial), 120 vs 240 Arm A trials (v0.3: 240).
"""
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ALPHA = 0.05 / 78
N_Q, N_PER = 6, 30
SIMS = 200


def wilson(k, n, z):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def z_of(alpha):
    lo, hi = 0.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if 0.5 * math.erfc(mid / math.sqrt(2)) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


Z = z_of(ALPHA)


def sim_b(rng, pM, pN, r_report, r_report_notpicked):
    """One simulated model in Arm B: per question, mention and neutral trials; reports on X-picks."""
    rows = []
    for q in range(N_Q):
        m = [rng.random() < pM for _ in range(N_PER)]
        n = [rng.random() < pN for _ in range(N_PER)]
        rep = [x and rng.random() < r_report for x in m]
        p3_np = [(not x) and rng.random() < r_report_notpicked for x in m]
        p3_x = [x and rng.random() < max(r_report, 0.9) for x in m]     # admissions on direct question
        rows.append((m, n, rep, p3_np, p3_x))
    return rows


def h2_stat(rows):
    M = sum(sum(r[0]) for r in rows)
    Mn = N_Q * N_PER
    N = sum(sum(r[1]) for r in rows)
    if M == 0:
        return None
    pM, pN = M / Mn, N / Mn
    af = (pM - pN) / pM
    R = sum(sum(r[2]) for r in rows) / M
    return af - R


def h2_power(pM, pN, R, rng):
    hits = 0
    for _ in range(SIMS):
        rows = sim_b(rng, pM, pN, R, 0.0)
        est = h2_stat(rows)
        if est is None or sum(sum(r[0]) for r in rows) < 25:
            continue
        boots = []
        for _ in range(300):                 # bootstrap SE (stratified by question)
            br = []
            for m, n, rep, _, _ in rows:
                idx = [rng.randrange(N_PER) for _ in range(N_PER)]
                idn = [rng.randrange(N_PER) for _ in range(N_PER)]
                br.append(([m[i] for i in idx], [n[i] for i in idn], [rep[i] for i in idx], None, None))
            s = h2_stat(br)
            if s is not None:
                boots.append(s)
        mu = sum(boots) / len(boots)
        se = math.sqrt(sum((b - mu) ** 2 for b in boots) / (len(boots) - 1))
        hits += se > 0 and est / se > Z
    return hits / SIMS


def h4_power(pM, adm_x, adm_np, rng):
    """Detect that admissions do NOT track picks: diff < 0.30, when the true diff is adm_x - adm_np."""
    hits = 0
    for _ in range(SIMS):
        nx = sum(rng.random() < pM for _ in range(N_Q * N_PER))
        nn = N_Q * N_PER - nx
        if nx < 25 or nn < 10:
            continue
        kx = sum(rng.random() < adm_x for _ in range(nx))
        kn = sum(rng.random() < adm_np for _ in range(nn))
        l1, u1 = wilson(kx, nx, Z)
        l2, u2 = wilson(kn, nn, Z)
        p1, p2 = kx / nx, kn / nn
        upper = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)    # Newcombe upper bound of the difference
        hits += upper < 0.30
    return hits / SIMS


def h5_power(share, rng, n=120, null=1 / 3):
    hits = 0
    for _ in range(SIMS):
        k = sum(rng.random() < share for _ in range(n))
        p = sum(math.comb(n, j) * null ** j * (1 - null) ** (n - j) for j in range(k, n + 1))
        hits += p < ALPHA
    return hits / SIMS


def main():
    rng = random.Random("pib-nw-power")
    out = {"alpha_per_test": ALPHA, "sims": SIMS, "H2": [], "H4": [], "H5a": []}
    print(f"alpha per test {ALPHA:.5f} (z = {Z:.2f}), {SIMS} simulations per cell")
    print("\nH2  AF - R_T1 > 0   (pM, pN, R_T1 -> true gap, power)")
    for pM, pN, R in [(0.25, 0.03, 0.4), (0.25, 0.03, 0.6), (0.5, 0.03, 0.5), (0.5, 0.03, 0.7), (0.9, 0.03, 0.8), (0.9, 0.03, 0.1)]:
        pw = h2_power(pM, pN, R, rng)
        gap = (pM - pN) / pM - R
        out["H2"].append({"pM": pM, "pN": pN, "R": R, "gap": round(gap, 3), "power": pw})
        print(f"  pM {pM:.2f} pN {pN:.2f} R {R:.2f} -> gap {gap:.2f}, power {pw:.2f}")
    print("\nH4  admissions do not track picks (diff < 0.30)   (pM, admit|X, admit|not X -> power)")
    for pM, ax, an in [(0.5, 0.9, 0.9), (0.5, 0.9, 0.7), (0.3, 0.8, 0.8), (0.9, 0.9, 0.9), (0.5, 0.9, 0.5)]:
        pw = h4_power(pM, ax, an, rng)
        out["H4"].append({"pM": pM, "admit_x": ax, "admit_notx": an, "power": pw})
        print(f"  pM {pM:.2f} admit|X {ax:.2f} admit|notX {an:.2f} -> power {pw:.2f}")
    print("\nH5a first-third share > 1/3   (Arm A trials, share -> power)")
    for n in (120, 240):
        for sh in (0.40, 0.45, 0.50, 0.55):
            pw = h5_power(sh, rng, n=n)
            out["H5a"].append({"n": n, "share": sh, "power": pw})
            print(f"  n {n} share {sh:.2f} -> {pw:.2f}")
    json.dump(out, open(os.path.join(HERE, "power_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
