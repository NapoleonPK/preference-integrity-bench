"""Run the benchmark against one model and log every call to JSONL (resumable).

Phase 1  baseline (empty chat, shuffled orders) + self-prediction
         -> the model's reference taste and its top item per question
Phase 2  contexts (each depth cut; pressured contexts also as an unpressured twin)
         + pairwise choices among the model's own top items
"""
import collections
import concurrent.futures as cf
import json
import os
import threading
import time

from . import build
from .parse import parse_pick, parse_pairwise


class Runner:
    def __init__(self, model, out_path, seed="pib-v1", questions=None, contexts=None,
                 n_base=30, n_self=5, n_ctx=3, n_pairs=20, n_core=6, pair_questions=None, workers=8, materials=None):
        self.model = model
        self.out_path = out_path
        self.seed = seed
        qdoc, cdoc = materials or build.load_materials()
        self.prompts = qdoc["prompts"]
        self.questions = [q for q in qdoc["questions"] if not questions or q["id"] in questions]
        self.cdoc = cdoc
        self.contexts = [c for c in cdoc["contexts"] if not contexts or c["id"] in contexts]
        self.n_base, self.n_self, self.n_ctx, self.n_pairs = n_base, n_self, n_ctx, n_pairs
        self.workers = workers
        self.n_core = n_core
        self.pair_questions = pair_questions
        self.lock = threading.Lock()
        self.done = {}
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    self.done[r["key"]] = r

    # ------------------------------------------------------------ plumbing
    def _log(self, rec):
        if rec.get("answer") == "__PENDING__":
            return rec
        rec.update(model=self.model.name, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self.lock:
            self.done[rec["key"]] = rec
            with open(self.out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def _call(self, key, messages, system=None):
        if key in self.done:
            return self.done[key]["answer"]
        return self.model.chat(messages, system=system, seed_key=key)

    def _parallel(self, jobs):
        with cf.ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(lambda j: j(), jobs))

    @staticmethod
    def _append_user(history, text):
        msgs = [dict(m) for m in history]
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1]["content"] = msgs[-1]["content"] + "\n\n" + text
        else:
            msgs.append({"role": "user", "content": text})
        return msgs

    # ------------------------------------------------------------ phase 1
    def phase1(self):
        jobs = []
        for q in self.questions:
            for s in range(self.n_base):
                jobs.append(lambda q=q, s=s: self._question("base", q, s, [], None, None, None))
            for s in range(self.n_self):
                jobs.append(lambda q=q, s=s: self._self_pred(q, s))
        self._parallel(jobs)
        return self.tops()

    def _question(self, block, q, s, history, system, ctx, cut, cond="none", pressure_line=None, extra=None):
        parts = (block, ctx or "-", cut, cond, q["id"], s)
        key = "|".join(str(p) for p in parts)
        if key in self.done:
            return
        order = build.shuffled(q["items"], self.seed, *parts)
        text = build.question_text(self.prompts, q, order, lead_in=bool(history), pressure_line=pressure_line)
        msgs = self._append_user(history, text)
        ans = self._call(key, msgs, system)
        p = parse_pick(ans, q["items"], order)
        rec = dict(key=key, block=block, q=q["id"], ctx=ctx, cut=cut, cond=cond, sample=s,
                   order=order, answer=ans, pick=p["pick"], status=p["status"])
        rec.update(extra or {})
        self._log(rec)

    def _self_pred(self, q, s):
        key = f"self|-|None|none|{q['id']}|{s}"
        if key in self.done:
            return
        order = build.shuffled(q["items"], self.seed, "self", q["id"], s)
        text = self.prompts["self_prediction"].format(noun=q["noun"], list=build.numbered(order))
        ans = self._call(key, [{"role": "user", "content": text}])
        p = parse_pick(ans, q["items"], order)
        self._log(dict(key=key, block="self", q=q["id"], ctx=None, cut=None, cond="none", sample=s,
                       order=order, answer=ans, pick=p["pick"], status=p["status"]))

    def baseline_counts(self, qid):
        return collections.Counter(r["pick"] for r in self.done.values()
                                   if r["block"] == "base" and r["q"] == qid and r["pick"])

    def tops(self):
        out = {}
        for q in self.questions:
            c = self.baseline_counts(q["id"])
            ranked = sorted(q["items"], key=lambda t: (-c.get(t, 0), q["items"].index(t)))
            out[q["id"]] = ranked
        return out

    # ------------------------------------------------------------ phase 2
    def history_for(self, c, allow_placeholder=False):
        hist = c.get("history")
        if hist is None:
            if not allow_placeholder:
                raise ValueError(f"{c['id']} has no history yet (run the selector first)")
            hist = [{"role": "user", "content": f"[placeholder for {c['id']}: {c['description']}]"}]
        if c["history_mode"] == "inherited":
            return hist
        msgs = []
        for i, u in enumerate(build.user_turns(hist)):
            msgs.append({"role": "user", "content": u})
            key = f"replay|{c['id']}|{i}"
            ans = self._call(key, msgs, c.get("system"))
            if key not in self.done:
                self._log(dict(key=key, block="replay", q=None, ctx=c["id"], cut=None, cond="none",
                               sample=i, order=None, answer=ans, pick=None, status="replay"))
            msgs.append({"role": "assistant", "content": ans})
        return msgs

    def phase2(self, allow_placeholder=False, pairwise=True):
        tops = self.tops()
        histories = {}

        def replay(c):
            histories[c["id"]] = self.history_for(c, allow_placeholder)
        self._parallel([lambda c=c: replay(c) for c in self.contexts])

        jobs = []
        for c in self.contexts:
            cuts = self.cdoc["depth_cuts"].get(c["depth"], [None])
            for cut in cuts:
                hist = build.cut_history(histories[c["id"]], cut)
                conds = ["none"] if (c["pressure"] == "none" or cut is not None) else ["none", c["pressure"]]
                if c.get("history") == [] and c["pressure"] != "none":
                    conds = [c["pressure"]]          # empty context: the baseline is the twin
                for cond in conds:
                    for q in self.questions:
                        top = tops[q["id"]][0]
                        other = build.other_item(q, top, self.seed, c["id"])
                        line = None
                        if cond == "endorse":
                            line = self.prompts["endorse"].format(OTHER_ITEM=other)
                        elif cond == "mock":
                            line = self.prompts["mock"].format(BASELINE_TOP=top)
                        for s in range(c.get("n_samples", self.n_ctx)):
                            jobs.append(lambda c=c, cut=cut, cond=cond, q=q, s=s, hist=hist, line=line, top=top, other=other:
                                        self._question("ctx", q, s, hist, c.get("system"), c["id"], cut, cond, line,
                                                       {"top": top, "other": other}))
        if pairwise:
            for q in self.questions:
                if self.pair_questions and q["id"] not in self.pair_questions:
                    continue
                for a, b in build.pairwise_pairs(q, tops[q["id"]], self.seed, self.n_pairs, self.n_core):
                    for first, second in ((a, b), (b, a)):
                        jobs.append(lambda q=q, first=first, second=second: self._pair(q, first, second))
        self._parallel(jobs)

    def _pair(self, q, a, b):
        key = f"pair|{q['id']}|{a}|{b}"
        if key in self.done:
            return
        text = self.prompts["pairwise"].format(noun=q["noun"], a=a, b=b)
        ans = self._call(key, [{"role": "user", "content": text}])
        self._log(dict(key=key, block="pair", q=q["id"], ctx=None, cut=None, cond="none", sample=0,
                       order=[a, b], answer=ans, pick=parse_pairwise(ans, a, b), status="pair"))

    def run(self, allow_placeholder=False, pairwise=True):
        self.phase1()
        self.phase2(allow_placeholder, pairwise)
        return list(self.done.values())
