"""PIB-NW runner (design in experiment/nw/PROTOCOL_NW.md; frozen after the pilot).

Every trial is its own fresh conversation, logged with its full transcript.

Arm B   v1 passing mention vs neutral line, then probes P1 (open), P2 (general), P3 (direct;
        phantom cue in neutral trials)                                     n_B per (question, cond)
Arm A   v1 favourite question, no line before it, shuffled list, then P1, P2, P3 about position
                                                                           n_A per question
Arm A1  four identical listings, two label schemes, then P1-P3 (descriptive) n_A1 per (set, scheme)
Arm C   self-prediction and same-model observer, fresh chats, one turn     n_C per (question, cue, version)

Pilot finding (v0.2): near-identical paraphrases (the old A2) are recognised as one product and
position is used as an open tie-breaker, so the position arm uses v1's lists of different items,
where v1 shows an unreported primacy bias.

TOP per question is the model's v1 TOP (read from its v1 run), so no new baseline phase is needed.
Orders and the "other" items are drawn from sha256(seed | trial key), as in v1.
"""
import json
import os
import re
import time

from . import build
from .parse import parse_pick
from .v1 import Experiment

VERSION = "nw-0.2"


def v1_tops(v1_run_path):
    """{question id: TOP} as stored by the v1 runner in every phase-2 record."""
    tops = {}
    for line in open(v1_run_path, encoding="utf-8"):
        r = json.loads(line)
        if r["block"] in ("pre", "post", "ctx") and r.get("top") and r["q"] not in tops:
            tops[r["q"]] = r["top"]
    return tops


def parse_option(answer, labels):
    """The option label an answer picks ('B'), or None. Arm A answers name options by label."""
    if not answer:
        return None
    alt = "|".join(re.escape(l) for l in labels)
    pats = [rf"\boption\s*\**\s*({alt})\b",                       # "Option B", "option **B"
            rf"^\W*({alt})\W",                                    # starts with "B." / "**B**"
            rf"\b(?:pick|choose|go with|recommend|choice is)\W+(?:option\s*)?\**\(?({alt})\b"]
    for p in pats:
        found = {m.group(1).upper() for m in re.finditer(p, answer, re.I | re.M)}
        found &= set(labels)
        if len(found) == 1:
            return found.pop()
    return None


class NWExperiment(Experiment):
    def __init__(self, model, out_path, cfg, qdoc, materials, tops, mode="full", **kw):
        super().__init__(model, out_path, cfg, qdoc, {"contexts": []}, **kw)
        self.M, self.tops, self.mode = materials, tops, mode
        self.n = cfg[mode]
        if mode == "pilot":
            self.seed = cfg["pilot_seed"]

    def _save(self, rec):
        rec.update(nw_version=VERSION, model_id=self.model_id, model=self.model.name, harness=self.harness,
                   seed=self.seed, mode=self.mode, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self.lock:
            self.done[rec["key"]] = rec
            with open(self.out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _probes(self, p3):
        P = self.M["probes"]
        return [P["P1"], P["P2"], p3]

    # ------------------------------------------------------------ jobs
    def jobs(self):
        jobs = []
        for q in self.Q:
            for cond in ("mention", "neutral"):
                for s in range(self.n["n_B"]):
                    key = f"B|{cond}|{q['id']}|{s}"
                    jobs.append((key, lambda q=q, s=s, key=key, cond=cond: self._arm_b(key, q, s, cond)))
        for q in self.Q:
            for s in range(self.n["n_A"]):
                key = f"A|{q['id']}|{s}"
                jobs.append((key, lambda q=q, s=s, key=key: self._arm_a(key, q, s)))
        for st in self.M["arm_a1"]["sets"]:
            for scheme in self.M["arm_a1"]["label_schemes"]:
                for s in range(self.n["n_A1"]):
                    key = f"A1|{st['id']}|{scheme}|{s}"
                    jobs.append((key, lambda st=st, s=s, scheme=scheme, key=key: self._arm_a1(key, st, s, scheme)))
        for version in ("self", "observer"):
            for q in self.Q:
                for s in range(self.n["n_C_mention"]):
                    key = f"C|mention|{version}|{q['id']}|{s}"
                    jobs.append((key, lambda q=q, s=s, v=version, key=key: self._arm_c(key, q, s, v, "mention")))
                for s in range(self.n["n_C_position"]):
                    key = f"C|position|{version}|{q['id']}|{s}"
                    jobs.append((key, lambda q=q, s=s, v=version, key=key: self._arm_c(key, q, s, v, "position")))
        return jobs

    def planned(self):
        return len(self.jobs())

    def run(self):
        missing = [q["id"] for q in self.Q if q["id"] not in self.tops]
        if missing:
            raise SystemExit(f"{self.model_id}: no v1 TOP for {missing}")
        jobs = self.jobs()
        self.log(f"{self.model_id}: PIB-NW {self.mode}, {len(jobs)} trials")
        self._run_jobs(jobs)
        n = sum(1 for k in self.done if k in {k for k, _ in jobs})
        self.log(f"{self.model_id}: {n}/{len(jobs)} trials logged; failures: {dict(self.failures) or 0}")
        return n >= len(jobs)

    # ------------------------------------------------------------ arms
    def _arm_b(self, key, q, s, cond):
        top = self.tops[q["id"]]
        order = self._order(q, "B", cond, q["id"], s)
        other = self._other(q, top, "B", cond, q["id"], s)          # drawn in both conditions; phantom in neutral
        line = self.M["arm_b"][cond].format(OTHER=other)
        p3 = self.M["probes"]["P3_mention" if cond == "mention" else "P3_phantom"].format(OTHER=other)
        tr, replies = self._talk([self._question(q, order, line=line)] + self._probes(p3))
        p = parse_pick(replies[0], q["items"], order)
        self._save(dict(key=key, arm="B", cond=cond, q=q["id"], sample=s, order=order, top=top, other=other,
                        turns=tr, answer=replies[0], pick=p["pick"], status=p["status"],
                        picked_other=p["pick"] == other, probes=dict(zip(("P1", "P2", "P3"), replies[1:]))))

    def _arm_a(self, key, q, s):
        order = self._order(q, "A", q["id"], s)
        tr, replies = self._talk([self._question(q, order)] + self._probes(self.M["probes"]["P3_position"]))
        p = parse_pick(replies[0], q["items"], order)
        self._save(dict(key=key, arm="A", cond="none", q=q["id"], sample=s, order=order, top=self.tops[q["id"]],
                        turns=tr, answer=replies[0], pick=p["pick"], status=p["status"],
                        pick_pos=order.index(p["pick"]) if p["pick"] in order else None,
                        probes=dict(zip(("P1", "P2", "P3"), replies[1:]))))

    def _arm_a1(self, key, st, s, scheme):
        A = self.M["arm_a1"]
        labels = A["label_schemes"][scheme]
        body = "\n".join(A["option_line"].format(label=l, text=st["listing"]) for l in labels)
        tr, replies = self._talk([st["request"] + "\n\n" + body] + self._probes(self.M["probes"]["P3_position"]))
        lab = parse_option(replies[0], labels)
        self._save(dict(key=key, arm="A1", cond=scheme, q=st["id"], sample=s, labels=labels, turns=tr, answer=replies[0],
                        pick_pos=labels.index(lab) if lab else None, status="ok" if lab else "none",
                        probes=dict(zip(("P1", "P2", "P3"), replies[1:]))))

    def _arm_c(self, key, q, s, version, cue):
        order = self._order(q, "C", cue, version, q["id"], s)
        x = self._other(q, self.tops[q["id"]], "C", cue, q["id"], s)      # same X for self and observer
        text = self.M["arm_c"][f"{cue}_{version}"].format(noun=q["noun"], X=x, list=build.numbered(order))
        tr, replies = self._talk([text])
        self._save(dict(key=key, arm="C", cond=f"{cue}_{version}", q=q["id"], sample=s, order=order, other=x,
                        turns=tr, answer=replies[0], prediction=parse_prediction(replies[0])))


def parse_prediction(answer):
    """yes/no and the first two numbers 0-100 in an Arm C answer."""
    a = answer or ""
    yn = re.search(r"\b(yes|no)\b", a, re.I)
    nums = [int(x) for x in re.findall(r"(?<![\d.])(\d{1,3})(?:\s*%)?(?![\d.])", a) if int(x) <= 100]
    return {"yes": (yn.group(1).lower() == "yes") if yn else None,
            "with": nums[0] if len(nums) > 0 else None, "without": nums[1] if len(nums) > 1 else None}
