"""PIB v1.0 runner (design frozen in experiment/PROTOCOL.md).

Every sample is its own fresh conversation, logged with its full transcript.

Phase 1  base    question in an empty chat, shuffled list                       n_base per question
         self    self-prediction ("which would you pick?")                      n_self per question
         -> the model's modal pick per question (TOP) and its n_core most-picked items
Phase 2  pre     one line before the question: neutral / mention / endorse / mock   n_pre per cond
         post    question, then a follow-up: confirm / doubt / mock / endorse       n_post per cond
         ctx     a real WildChat turn (or a neutral filler turn), then the question n_ctx_real / n_ctx_filler
         pair    two items from the core set, both orders                           1 per order

Item orders and the "other" items are drawn from sha256(seed | sample key): identical for every
model given the same TOP. A sample is logged only when all its turns succeeded, so a rerun of
the same command resumes where it stopped.
"""
import collections
import concurrent.futures as cf
import json
import os
import threading
import time

from . import build
from .parse import parse_pick, parse_pairwise

VERSION = "1.0"


class Experiment:
    def __init__(self, model, out_path, cfg, qdoc, cdoc, model_id=None, harness=None, workers=6, log=print):
        self.model, self.out_path, self.cfg = model, out_path, cfg
        self.phase1_tolerance = 0
        self.model_id = model_id or model.name
        self.harness = harness
        self.seed = cfg["seed"]
        self.P = qdoc["prompts"]
        self.Q = [q for q in qdoc["questions"] if q["id"] in cfg["questions"]]
        self.C = cdoc["contexts"]
        self.workers = workers
        self.log = log
        self.lock = threading.Lock()
        self.done = {}
        self.failures = collections.Counter()
        if os.path.exists(out_path):
            for line in open(out_path, encoding="utf-8"):
                r = json.loads(line)
                self.done[r["key"]] = r

    # ------------------------------------------------------------ plumbing
    def _save(self, rec):
        rec.update(pib_version=VERSION, model_id=self.model_id, model=self.model.name, harness=self.harness,
                   seed=self.seed, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self.lock:
            self.done[rec["key"]] = rec
            with open(self.out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _talk(self, turns):
        """Run user turns in one fresh conversation; turns may be callables of the replies so far."""
        sess = self.model.session(self.cfg.get("system_prompt"))
        transcript, replies = [], []
        for t in turns:
            text = t(replies) if callable(t) else t
            if text is None:
                break
            reply = sess.say(text)
            transcript += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
            replies.append(reply)
        return transcript, replies

    def _run_jobs(self, jobs):
        jobs = [(k, f) for k, f in jobs if k not in self.done]
        if not jobs:
            return
        t0, n = time.time(), len(jobs)

        def wrap(kf):
            k, f = kf
            try:
                f()
            except Exception as e:  # noqa: BLE001 - one failed sample must not stop the run
                with self.lock:
                    self.failures[type(e).__name__] += 1
                self.log(f"  failed {k}: {str(e)[:160]}")
        with cf.ThreadPoolExecutor(self.workers) as ex:
            for i, _ in enumerate(ex.map(wrap, jobs), 1):
                if i % 25 == 0 or i == n:
                    self.log(f"  {i}/{n} samples ({time.time() - t0:.0f}s)")

    def _order(self, q, *parts):
        return build.shuffled(q["items"], self.seed, *parts)

    def _other(self, q, exclude, *parts):
        pool = [t for t in q["items"] if t != exclude]
        return build.rng_for(self.seed, "other", *parts).choice(pool)

    def _question(self, q, order, line=None, lead_in=False):
        return build.question_text(self.P, q, order, lead_in=lead_in, pressure_line=line)

    def _rec(self, key, block, cond, q, s, order, transcript, ctx=None, **extra):
        final = transcript[-1]["content"] if transcript else ""
        p = parse_pick(final, q["items"], order)
        rec = dict(key=key, block=block, cond=cond, q=q["id"], ctx=ctx, sample=s, order=order,
                   turns=transcript, answer=final, pick=p["pick"], status=p["status"])
        rec.update(extra)
        self._save(rec)

    # ------------------------------------------------------------ phase 1
    def phase1(self):
        jobs = []
        for q in self.Q:
            for s in range(self.cfg["n_base"]):
                key = f"base|{q['id']}|{s}"
                jobs.append((key, lambda q=q, s=s, key=key: self._base(key, q, s)))
            for s in range(self.cfg["n_self"]):
                key = f"self|{q['id']}|{s}"
                jobs.append((key, lambda q=q, s=s, key=key: self._self(key, q, s)))
        self._run_jobs(jobs)

    def _base(self, key, q, s):
        order = self._order(q, "base", q["id"], s)
        tr, _ = self._talk([self._question(q, order)])
        self._rec(key, "base", "none", q, s, order, tr)

    def _self(self, key, q, s):
        order = self._order(q, "self", q["id"], s)
        text = self.P["self_prediction"].format(noun=q["noun"], list=build.numbered(order))
        tr, _ = self._talk([text])
        self._rec(key, "self", "none", q, s, order, tr)

    def ranking(self, qid):
        q = next(x for x in self.Q if x["id"] == qid)
        c = collections.Counter(r["pick"] for r in self.done.values()
                                if r["block"] == "base" and r["q"] == qid and r["status"] in ("ok", "ambiguous"))
        return sorted(q["items"], key=lambda t: (-c.get(t, 0), q["items"].index(t))), c

    def phase1_complete(self):
        need = len(self.Q) * (self.cfg["n_base"] + self.cfg["n_self"])
        have = sum(1 for r in self.done.values() if r["block"] in ("base", "self"))
        return have >= need - self.phase1_tolerance  # tolerance > 0 only by deviation (PROTOCOL §12)

    # ------------------------------------------------------------ phase 2
    def phase2(self):
        jobs = []
        for q in self.Q:
            rank, counts = self.ranking(q["id"])
            top = rank[0] if counts else None
            for cond in self.cfg["pre_conditions"]:
                if cond == "mock" and top is None:
                    continue
                for s in range(self.cfg["n_pre"]):
                    key = f"pre|{cond}|{q['id']}|{s}"
                    jobs.append((key, lambda q=q, s=s, key=key, cond=cond, top=top: self._pre(key, q, s, cond, top)))
            for cond in self.cfg["post_conditions"]:
                for s in range(self.cfg["n_post"]):
                    key = f"post|{cond}|{q['id']}|{s}"
                    jobs.append((key, lambda q=q, s=s, key=key, cond=cond, top=top: self._post(key, q, s, cond, top)))
            for c in self.C:
                n = self.cfg["n_ctx_real"] if c["kind"] == "real" else self.cfg["n_ctx_filler"]
                for s in range(n):
                    key = f"ctx|{c['id']}|{q['id']}|{s}"
                    jobs.append((key, lambda q=q, s=s, key=key, c=c, top=top: self._ctx(key, q, s, c, top)))
            core = rank[: self.cfg["n_core"]]
            for i, a in enumerate(core):
                for b in core[i + 1:]:
                    for x, y in ((a, b), (b, a)):
                        key = f"pair|{q['id']}|{x}|{y}"
                        jobs.append((key, lambda q=q, x=x, y=y, key=key: self._pair(key, q, x, y)))
        self._run_jobs(jobs)

    def _pre(self, key, q, s, cond, top):
        order = self._order(q, "pre", cond, q["id"], s)
        other = self._other(q, top, "pre", cond, q["id"], s)       # drawn in every condition (shadow)
        line = self.P["pre_" + cond].format(OTHER=other, TOP=top)
        tr, _ = self._talk([self._question(q, order, line=line)])
        self._rec(key, "pre", cond, q, s, order, tr, top=top, other=other)

    def _post(self, key, q, s, cond, top):
        order = self._order(q, "post", cond, q["id"], s)
        info = {}

        def follow(replies):
            p = parse_pick(replies[0], q["items"], order)
            info["first_pick"], info["first_status"] = p["pick"], p["status"]
            if p["status"] not in ("ok", "ambiguous"):
                return None                                        # excluded: no first pick
            info["other"] = self._other(q, p["pick"], "post", cond, q["id"], s)
            return self.P["post_" + cond].format(PICK=p["pick"], OTHER=info["other"])
        tr, _ = self._talk([self._question(q, order), follow])
        complete = len(tr) == 4
        final = tr[-1]["content"] if complete else ""
        p = parse_pick(final, q["items"], order) if complete else {"pick": None, "status": "excluded"}
        rec = dict(key=key, block="post", cond=cond, q=q["id"], ctx=None, sample=s, order=order, turns=tr,
                   answer=final, pick=p["pick"], status=p["status"], top=top, **info)
        self._save(rec)

    def _ctx(self, key, q, s, c, top):
        order = self._order(q, "ctx", c["id"], q["id"], s)
        turns = list(c["turns"]) + [self._question(q, order, lead_in=True)]
        tr, _ = self._talk(turns)
        self._rec(key, "ctx", c["kind"], q, s, order, tr, ctx=c["id"], top=top)

    def _pair(self, key, q, a, b):
        text = self.P["pairwise"].format(noun=q["noun"], a=a, b=b)
        tr, replies = self._talk([text])
        self._save(dict(key=key, block="pair", cond="none", q=q["id"], ctx=None, sample=0, order=[a, b],
                        turns=tr, answer=replies[0], pick=parse_pairwise(replies[0], a, b), status="pair"))

    # ------------------------------------------------------------ all
    def planned(self):
        c = self.cfg
        per_q = (c["n_base"] + c["n_self"] + c["n_pre"] * len(c["pre_conditions"]) + c["n_post"] * len(c["post_conditions"])
                 + sum(c["n_ctx_real"] if x["kind"] == "real" else c["n_ctx_filler"] for x in self.C)
                 + c["n_core"] * (c["n_core"] - 1))
        return per_q * len(self.Q)

    def run(self):
        self.log(f"{self.model_id}: phase 1 (baseline + self-prediction)")
        self.phase1()
        if not self.phase1_complete():
            self.log("phase 1 incomplete; rerun the same command to retry the failed samples")
            return False
        self.log(f"{self.model_id}: phase 2; TOP per question: " +
                 ", ".join(f"{q['id']}={self.ranking(q['id'])[0][0]}" for q in self.Q))
        self.phase2()
        n = len(self.done)
        self.log(f"{self.model_id}: {n}/{self.planned()} samples logged; failures: {dict(self.failures) or 0}")
        return n >= self.planned()
