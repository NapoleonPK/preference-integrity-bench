"""Power by simulation: share of simulated runs in which each primary test fires (p < 0.05/8,
a conservative stand-in for Holm), at several effect sizes. Usage (from pib/): python ../experiment/power/power.py"""
import json, os, sys, tempfile
sys.path.insert(0, ".")
from tests.test_v1 import CFG, QDOC, CDOC, taste, TopicalSim
T_LLM = 0.5   # deliberately less decisive than the pilot models (definiteness ~0.40): conservative power
from pib.v1 import Experiment
from pib.score_v1 import ScoreV1, reparse
from pib.sim_v1 import SimV1
ALPHA, SEEDS = 0.05 / 8, 20
GRID = {
 "T1_endorse_pre_adoption_gt_mention": ("endorse_pull", [0.1, 0.2, 0.3]),
 "T3_doubt_switch_gt_confirm": ("cave", [0.1, 0.2, 0.3]),
 "T5_endorse_post_adoption_gt_confirm": ("post_endorse_pull", [0.1, 0.2, 0.3]),
 "T6_real_contexts_differ_from_filler": ("context_noise", [0.5, 1.0, 1.5]),
 "T7_position_bias": ("position_bias", [0.05, 0.1, 0.2]),
}
out = {}
for test, (param, levels) in GRID.items():
    for lv in levels:
        hits, effects = 0, []
        for seed in range(SEEDS):
            U = taste(100 + seed)
            cls = TopicalSim if param == "context_noise" else SimV1
            m = cls("p", U, temperature=T_LLM, seed=seed, **{param: lv})
            path = tempfile.mktemp()
            Experiment(m, path, CFG, QDOC, CDOC, workers=1, log=lambda *a: None).run()
            s = ScoreV1(reparse([json.loads(l) for l in open(path)], QDOC["questions"]), QDOC["questions"]).score(B=0)
            os.remove(path)
            hits += (s["tests"][test] or 1) < ALPHA
            r = s["rates"]
            effects.append({"T1": lambda: r["pre_adopt"]["endorse"]["rate"] - r["pre_adopt"]["mention"]["rate"],
                            "T3": lambda: r["post_switch"]["doubt"]["rate"] - r["post_switch"]["confirm"]["rate"],
                            "T5": lambda: r["post_adopt"]["endorse"]["rate"] - r["post_adopt"]["confirm"]["rate"],
                            "T6": lambda: r["ctx_keep"]["filler"]["rate"] - r["ctx_keep"]["real"]["rate"],
                            "T7": lambda: None}[test[:2]]())
        e = [x for x in effects if x is not None]
        out[f"{test} | {param}={lv}"] = {"power": hits / SEEDS, "mean_effect_rate_diff": round(sum(e) / len(e), 3) if e else None}
        print(f"{test:40s} {param}={lv:<5} power={hits/SEEDS:.2f} effect={out[f'{test} | {param}={lv}']['mean_effect_rate_diff']}", flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "power_results.json"), "w"), indent=1)
