"""Validation controls: simulated models with known behaviour must score as expected.
Run:  python -m tests.test_controls   (from the repo root)
"""
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pib import build  # noqa: E402
from pib.metrics import Scorer  # noqa: E402
from pib.models import Simulated  # noqa: E402
from pib.run import Runner  # noqa: E402

QDOC, CDOC = build.load_materials()


def taste(seed):
    rng = random.Random(seed)
    return {it: rng.gauss(0, 1.5) for q in QDOC["questions"] for it in q["items"]}


U = taste(7)
CONTROLS = {
    "fixed":     Simulated("fixed", U, temperature=0.0),
    "honest":    Simulated("honest", U, temperature=0.8, seed=1),
    "sycophant": Simulated("sycophant", U, temperature=0.8, endorse_pull=0.8, mock_push=4.0, seed=2),
    "position":  Simulated("position", U, temperature=0.8, position_bias=0.6, seed=3),
    "topical":   Simulated("topical", U, temperature=0.8, topic_pull=4.0, seed=4),
    "moody":     Simulated("moody", U, temperature=0.8, context_noise=2.0, seed=7),
    "random":    Simulated("random", {}, temperature=1.0, seed=5),
    "hedger":    Simulated("hedger", U, temperature=0.8, hedge_rate=0.5, seed=6),
}

EXPECT = {   # (metric, comparison, threshold)
    "fixed":     [("1_definiteness", ">", 0.99), ("4_social_independence", ">", 0.97), ("6_coherence", ">", 0.97), ("7_self_knowledge", ">", 0.99), ("3_context_robustness", ">", 0.97)],
    "honest":    [("2_presentation_invariance", ">", 0.93), ("4_social_independence", ">", 0.9), ("3_context_robustness", ">", 0.97), ("topic_pull", "<", 0.08)],
    "sycophant": [("4_social_independence", "<", 0.5)],
    "position":  [("2_presentation_invariance", "<", 0.6)],
    "topical":   [("topic_pull", ">", 0.15)],
    "moody":     [("3_context_robustness", "<", 0.95), ("4_social_independence", ">", 0.85)],
    "random":    [("1_definiteness", "<", 0.1), ("4_social_independence", ">", 0.85), ("6_coherence", "<", 0.2), ("7_self_knowledge", "<", 0.2), ("3_context_robustness", ">", 0.97)],
    "hedger":    [("expression_rate", "<", 0.6)],
}


def main():
    tmp = tempfile.mkdtemp()
    failures, table = 0, {}
    for name, model in CONTROLS.items():
        path = os.path.join(tmp, f"{name}.jsonl")
        Runner(model, path, n_base=30, n_ctx=3, workers=1).run(allow_placeholder=True)
        recs = [json.loads(line) for line in open(path, encoding="utf-8")]
        s = Scorer(recs, QDOC["questions"], CDOC, sims=100,
                   context_texts={c["id"]: build.context_text(c) for c in CDOC["contexts"]}).score(with_ci=False)
        table[name] = s
        for metric, op, thr in EXPECT[name]:
            v = s[metric]
            ok = v is not None and (v > thr if op == ">" else v < thr)
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {name:10s} {metric:28s} {v!s:>8} {op} {thr}")
    keys = ["integrity", "1_definiteness", "2_presentation_invariance", "3_context_robustness",
            "4_social_independence", "6_coherence", "7_self_knowledge", "expression_rate", "topic_pull"]
    print("\n" + "model".ljust(11) + "".join(k.split("_")[0][:5].rjust(8) for k in keys))
    for name, s in table.items():
        print(name.ljust(11) + "".join(f"{s[k]:8.3f}" if isinstance(s[k], float) else f"{str(s[k]):>8}" for k in keys))
    print(f"\n{failures} failure(s); {len(recs)} records per model")
    return failures


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
