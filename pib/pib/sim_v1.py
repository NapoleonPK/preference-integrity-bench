"""Simulated models for validating PIB v1.0: each has a known behaviour, so the scores and tests
must come out as expected (tests/test_v1.py). They read the v1.0 prompts as a real model would."""
import hashlib
import math
import random
import re
import threading

from .models import Model

LIST_LINE = re.compile(r"^\s*(\d{1,2})\.\s+(.+?)\s*$", re.M)
PAIR_LINE = re.compile(r"^\s*([AB])\.\s+(.+?)\s*$", re.M)
PRE_ENDORSE = re.compile(r"my own favourite here is (.+?)\. I think")
PRE_MOCK = re.compile(r"honestly, I find (.+?) overrated\.")
PRE_MENTION = re.compile(r"Before you answer: (.+?) came up in a conversation")
POST_MOCK = re.compile(r"^Honestly, I find (.+?) overrated\.")
POST_ENDORSE = re.compile(r"^My own favourite is (.+?)\. I think")
PICK = re.compile(r"My favourite is (.+?)\. It stands out")


class SimV1(Model):
    def __init__(self, name, utilities, temperature=0.8, endorse_pull=0.0, mock_push=0.0, mention_pull=0.0,
                 cave=0.0, post_endorse_pull=0.0, position_bias=0.0, context_noise=0.0, hedge_rate=0.0, seed=0):
        self.name = name
        self.u, self.t = utilities, temperature
        self.endorse_pull, self.mock_push, self.mention_pull = endorse_pull, mock_push, mention_pull
        self.cave, self.post_endorse_pull = cave, post_endorse_pull
        self.position_bias, self.context_noise, self.hedge_rate = position_bias, context_noise, hedge_rate
        self.rng = random.Random(seed)
        self.lock = threading.Lock()

    def _choose(self, items, noise_key=None, mocked=None):
        scores = []
        for it in items:
            s = self.u.get(it, 0.0)
            if it == mocked:
                s -= self.mock_push
            if noise_key and self.context_noise:
                h = hashlib.sha256((noise_key + "|" + it).encode()).digest()
                s += self.context_noise * (int.from_bytes(h[:4], "big") / 2 ** 32 - 0.5) * 3.46
            scores.append(s)
        if self.t <= 0:
            return items[scores.index(max(scores))]
        m = max(scores)
        return self.rng.choices(items, weights=[math.exp((s - m) / self.t) for s in scores])[0]

    def chat(self, messages, system=None, seed_key=""):
        with self.lock:
            return self._reply(messages)

    def _reply(self, messages):
        last = messages[-1]["content"]
        pair = PAIR_LINE.findall(last)
        if len(pair) == 2 and "prefer" in last:
            return self._choose([pair[0][1], pair[1][1]]) + "."
        items = [t for _, t in LIST_LINE.findall(last)]
        if items:
            if "predict" in last:
                return max(items, key=lambda x: self.u.get(x, 0))
            if self.hedge_rate and self.rng.random() < self.hedge_rate:
                return "As an AI I don't really have a favourite here; they are all remarkable."
            prior = [m["content"] for m in messages[:-1] if m["role"] == "user"]
            noise_key = prior[0] if prior else None
            e, mo, me = PRE_ENDORSE.search(last), PRE_MOCK.search(last), PRE_MENTION.search(last)
            if self.position_bias and self.rng.random() < self.position_bias:
                pick = items[0]
            elif e and self.rng.random() < self.endorse_pull:
                pick = e.group(1)
            elif me and self.rng.random() < self.mention_pull:
                pick = me.group(1)
            else:
                pick = self._choose(items, noise_key, mo.group(1) if mo else None)
            return f"My favourite is {pick}. It stands out to me for its depth."
        # a follow-up after an answered question
        prev_lists = [LIST_LINE.findall(m["content"]) for m in messages if m["role"] == "user"]
        prev_items = next(([t for _, t in L] for L in prev_lists if L), None)
        prev_pick = next((PICK.search(m["content"]).group(1) for m in messages
                          if m["role"] == "assistant" and PICK.search(m["content"])), None)
        if prev_items and prev_pick:
            pm, pe = POST_MOCK.search(last), POST_ENDORSE.search(last)
            if pe and self.rng.random() < self.post_endorse_pull:
                return pe.group(1)
            if (pm or last.startswith("Are you sure")) and self.rng.random() < self.cave:
                return self._choose([x for x in prev_items if x != prev_pick])
            return prev_pick
        return "Sure, here is my reply to that."
