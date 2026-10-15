#!/usr/bin/env python3
"""Preference Integrity Benchmark v1 - command line.

  # full run on one model (needs real contexts from the selector, and a key):
  export PIB_API_KEY=...            # OpenRouter key (or ANTHROPIC_API_KEY with --provider anthropic)
  python run_pib.py run  --model anthropic/claude-haiku-5-5 --out results/haiku.jsonl
  python run_pib.py score --log results/haiku.jsonl

  # validation controls (no key needed):
  python -m tests.test_controls
"""
import argparse
import json

from pib import build
from pib.metrics import Scorer
from pib.models import Anthropic, OpenAICompatible
from pib.run import Runner


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--provider", choices=["openai-compatible", "anthropic"], default="openai-compatible")
    r.add_argument("--out", required=True)
    r.add_argument("--questions", nargs="*")
    r.add_argument("--contexts", nargs="*")
    r.add_argument("--n-base", type=int, default=30)
    r.add_argument("--n-ctx", type=int, default=3)
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--allow-placeholder", action="store_true", help="dry runs only")
    s = sub.add_parser("score")
    s.add_argument("--log", required=True)
    args = ap.parse_args()

    qdoc, cdoc = build.load_materials()
    if args.cmd == "run":
        model = Anthropic(args.model) if args.provider == "anthropic" else OpenAICompatible(args.model)
        Runner(model, args.out, questions=args.questions, contexts=args.contexts, n_base=args.n_base,
               n_ctx=args.n_ctx, workers=args.workers).run(allow_placeholder=args.allow_placeholder)
        args.log = args.out
    recs = [json.loads(line) for line in open(args.log, encoding="utf-8")]
    texts = {c["id"]: build.context_text(c) for c in cdoc["contexts"]}
    print(json.dumps(Scorer(recs, qdoc["questions"], cdoc, context_texts=texts).score(), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
