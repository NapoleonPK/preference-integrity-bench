"""Small, dependency-free statistics for PIB v1.0 (frozen with the protocol).

wilson(k, n)                 95% Wilson interval for a proportion
strat_exact(strata, side)    exact stratified test of two proportions (conditional on each
                             stratum's margins, like an exact Cochran-Mantel-Haenszel test).
                             strata = [(k_a, n_a, k_b, n_b), ...]; side 'greater' tests
                             P(success | a) > P(success | b). The statistic is the total number
                             of successes in group a; its null distribution is the convolution
                             of one hypergeometric per stratum.
binom_greater(k, n, p0)      exact one-sided binomial p-value P(X >= k)
holm(pvals)                  Holm-Bonferroni adjusted p-values (same order as given)
"""
import math


def wilson(k, n, z=1.959964):
    if not n:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _hypergeom(k_tot, n_a, n_b):
    """P(X = x) for x successes in group a, when k_tot successes are spread over n_a + n_b."""
    n = n_a + n_b
    lo, hi = max(0, k_tot - n_b), min(k_tot, n_a)
    den = math.comb(n, k_tot)
    return {x: math.comb(n_a, x) * math.comb(n_b, k_tot - x) / den for x in range(lo, hi + 1)}


def strat_exact(strata, side="greater"):
    strata = [s for s in strata if s[1] and s[3]]
    if not strata:
        return None
    dist = {0: 1.0}
    obs = 0
    for k_a, n_a, k_b, n_b in strata:
        obs += k_a
        h = _hypergeom(k_a + k_b, n_a, n_b)
        new = {}
        for x, px in dist.items():
            for y, py in h.items():
                new[x + y] = new.get(x + y, 0.0) + px * py
        dist = new
    eps = 1e-12
    if side == "greater":
        p = sum(v for x, v in dist.items() if x >= obs - eps)
    else:
        p = sum(v for x, v in dist.items() if x <= obs + eps)
    return min(1.0, p)


def binom_greater(k, n, p0=0.5):
    if not n:
        return None
    return min(1.0, sum(math.comb(n, i) * p0 ** i * (1 - p0) ** (n - i) for i in range(k, n + 1)))


def holm(pvals):
    idx = [i for i, p in enumerate(pvals) if p is not None]
    order = sorted(idx, key=lambda i: pvals[i])
    m = len(order)
    adj = [None] * len(pvals)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def percentile(vals, q):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    pos = q * (len(vals) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)
