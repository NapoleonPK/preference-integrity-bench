#!/usr/bin/env python3
"""Run PIB v1.0 on one model from models.json (resumable: rerun the same command after a stop).

  python experiment/run.py claude-haiku-5-5            # full run -> experiment/runs/<id>.jsonl
  python experiment/run.py claude-haiku-5-5 --smoke    # 1 sample per cell, 1 question -> runs/smoke/<id>.jsonl
  python experiment/run.py --list                      # roster and progress
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pib"))
from pib.models import PiCLI, ClaudeCLI, CodexCLI, OpenCodeCLI, OpenAICompatible, Anthropic, PI_SYSTEM  # noqa: E402
from pib.v1 import Experiment  # noqa: E402

KEYS = os.path.expanduser("~/.config/pib/keys.env")      # API keys live outside the repo
if os.path.exists(KEYS):
    for line in open(KEYS):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)
CFG = json.load(open(os.path.join(HERE, "config.json")))
QDOC = json.load(open(os.path.join(HERE, "materials", "questions.json")))
CDOC = json.load(open(os.path.join(HERE, "materials", "contexts.json")))
ROSTER = {m["id"]: m for m in json.load(open(os.path.join(HERE, "models.json")))["models"]}
assert PI_SYSTEM == CFG["system_prompt"], "harness system prompt and config.json disagree"


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def clean_codex_home():
    home = os.path.join(HERE, ".codex-home")
    os.makedirs(home, exist_ok=True)
    link = os.path.join(home, "auth.json")
    if not os.path.exists(link):
        os.symlink(os.path.expanduser("~/.codex/auth.json"), link)
    return home


def backend(m):
    h = m["harness"]
    if h == "pi":
        return PiCLI(m["model"], thinking=m.get("effort"))
    if h == "claude-cli":
        return ClaudeCLI(m["model"], effort=m.get("effort"))
    if h == "codex":
        return CodexCLI(m["model"], codex_home=clean_codex_home(), effort=m.get("effort"))
    if h == "opencode":
        return OpenCodeCLI(m["model"])
    if h == "openai-compatible":
        return OpenAICompatible(m["model"], base_url=m.get("base_url"), api_key=os.environ.get(m.get("key_env", "PIB_API_KEY")))
    if h == "anthropic-api":
        return Anthropic(m["model"])
    raise SystemExit(f"unknown harness {h}")


def version(h):
    cmd = {"pi": ["pi", "--version"], "claude-cli": ["claude", "--version"], "codex": ["codex", "--version"],
           "opencode": ["opencode", "--version"]}.get(h)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip() if cmd else None
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id", nargs="?")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.model_id:
        for mid, m in ROSTER.items():
            p = os.path.join(HERE, "runs", mid + ".jsonl")
            n = sum(1 for _ in open(p)) if os.path.exists(p) else 0
            print(f"{mid:28s} {m['role']:16s} {m['harness']:11s} {m['model']:40s} {n} samples")
        return
    m = ROSTER[a.model_id]
    if "FILL-IN" in m["model"]:
        raise SystemExit(f"{a.model_id}: fill in the model id in models.json first")
    cfg = dict(CFG, seed=m.get("seed", CFG["seed"]))
    out_dir = os.path.join(HERE, "runs", "smoke") if a.smoke else os.path.join(HERE, "runs")
    if a.smoke:
        cfg.update(questions=cfg["questions"][:1], n_base=2, n_self=1, n_pre=1, n_post=1, n_ctx_real=1, n_ctx_filler=1, n_core=2)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, a.model_id + ".jsonl")
    meta_path = out[:-6] + ".meta.json"
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {"sessions": []}
    meta.update(model=m, config=cfg, harness_version=version(m["harness"]),
                hashes={f: sha(os.path.join(HERE, p)) for f, p in
                        [("config", "config.json"), ("questions", "materials/questions.json"), ("contexts", "materials/contexts.json")]})
    meta["sessions"].append({"start": time.strftime("%Y-%m-%dT%H:%M:%S")})
    ex = Experiment(backend(m), out, cfg, QDOC, CDOC, model_id=a.model_id, harness=m["harness"], workers=a.workers,
                    log=lambda *x: print(*x, flush=True))
    ex.phase1_tolerance = m.get("phase1_tolerance", 0)   # set per model only by deviation (PROTOCOL §12)
    done = ex.run()
    meta["sessions"][-1].update(end=time.strftime("%Y-%m-%dT%H:%M:%S"), complete=done, samples=len(ex.done),
                                planned=ex.planned(), failures=dict(ex.failures))
    json.dump(meta, open(meta_path, "w"), indent=1, ensure_ascii=False)
    print("COMPLETE" if done else "INCOMPLETE - rerun the same command to resume")


if __name__ == "__main__":
    main()
