#!/usr/bin/env python3
"""Run PIB-NW on one model from experiment/models.json (resumable: rerun the same command after a stop).

  python experiment/nw/run_nw.py claude-sonnet-5-5 --pilot     # pilot -> experiment/nw/runs/pilot/<id>.jsonl
  python experiment/nw/run_nw.py claude-sonnet-5-5             # full  -> experiment/nw/runs/<id>.jsonl (after the freeze)
  python experiment/nw/run_nw.py claude-sonnet-5-5 --smoke     # 1 trial per arm, no v1 TOP needed beyond the model's run
  python experiment/nw/run_nw.py deepseek-v4.1-flash@go --observe-for nemotron-3-super
        # reference observer (config "reference_observer"): the Arm C observer prompts of that subject,
        # word for word (same X and orders), answered by the reference model -> runs/<mode>/observer/<subject>.jsonl

Uses the v1 harness for each model (experiment/run.py: backend) and the model's v1 TOP per question.
Subscription-backed models are run one at a time, as in v1.
"""
import argparse
import json
import os
import sys
import time

NW = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(NW)
sys.path.insert(0, EXP)
sys.path.insert(0, os.path.join(os.path.dirname(EXP), "pib"))
from run import ROSTER, QDOC, backend, sha, version  # noqa: E402  (also loads the API keys)
from pib.nw import NWExperiment, v1_tops  # noqa: E402

CFG = json.load(open(os.path.join(NW, "config_nw.json")))
MAT = json.load(open(os.path.join(NW, "materials.json")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--observe-for", metavar="SUBJECT")
    a = ap.parse_args()
    m = ROSTER[a.model_id]
    mode = "pilot" if a.pilot or a.smoke else "full"
    cfg = json.loads(json.dumps(CFG))
    if a.smoke:
        cfg["questions"] = cfg["questions"][:1]
        cfg["pilot"] = {"n_B": 1, "n_A1": 1, "n_C_mention": 1, "n_C_position": 1}
    out_dir = os.path.join(NW, "runs", "smoke" if a.smoke else mode)
    subject = a.observe_for or a.model_id
    if a.observe_for:
        out_dir = os.path.join(out_dir, "observer")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, subject + ".jsonl")
    tops = v1_tops(os.path.join(EXP, "runs", subject + ".jsonl"))
    meta_path = out[:-6] + ".meta.json"
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {"sessions": []}
    meta.update(model=m, config=cfg, mode=mode, v1_tops=tops, harness_version=version(m["harness"]),
                hashes={f: sha(os.path.join(NW, f)) for f in ("config_nw.json", "materials.json", "PROTOCOL_NW.md")})
    meta["sessions"].append({"start": time.strftime("%Y-%m-%dT%H:%M:%S")})
    arms = ["C|mention|observer", "C|position|observer"] if a.observe_for else None
    ex = NWExperiment(backend(m), out, cfg, QDOC, MAT, tops, mode=mode, arms=arms, model_id=a.model_id,
                      harness=m["harness"], workers=a.workers, log=lambda *x: print(*x, flush=True))
    if a.observe_for:
        ex.extra = {"observed_for": a.observe_for}
        meta.update(observed_for=a.observe_for)
    if a.smoke:   # one trial per arm
        jobs = ex.jobs()
        keep = {}
        for k, f in jobs:
            keep.setdefault(k.split("|")[0] + k.split("|")[1], (k, f))
        ex.jobs = lambda: list(keep.values())
    done = ex.run()
    meta["sessions"][-1].update(end=time.strftime("%Y-%m-%dT%H:%M:%S"), complete=done, samples=len(ex.done),
                                planned=ex.planned(), failures=dict(ex.failures))
    json.dump(meta, open(meta_path, "w"), indent=1, ensure_ascii=False)
    print("COMPLETE" if done else "INCOMPLETE - rerun the same command to resume")


if __name__ == "__main__":
    main()
