"""Automatic eligibility filter (frozen). Usage: python filter_wildchat.py -> eligible.jsonl (seeded order)"""
import json, random, re, sys
sys.path.insert(0, "../../pib")
from pib.parse import norm
Q = json.load(open("../materials/questions.json"))
ITEM_WORDS = {w for q in Q["questions"] for it in q["items"] for w in re.findall(r"[a-z]{5,}", norm(it))}
DOMAIN = re.compile(r"\b(book|novel|essay|read(ing)?|author|paint|art|artist|museum|music|song|album|band|film|movie|cinema|"
                    r"food|dish|recipe|cook|restaurant|eat|science|scientific|theorem|physics|math|equation|"
                    r"favou?rite|prefer|best|opinion|ai|chatgpt|gpt|assistant|language model)\w*", re.I)
BAD = re.compile(r"\b(pretend|act as|roleplay|role-play|jailbreak|dan|ignore (all|previous)|sex|nsfw|kill|suicide)\b", re.I)
rows = [json.loads(l) for l in open("candidates_raw.jsonl")]
seen, ok = set(), []
for r in rows:
    u = (r["user"] or "").strip()
    why = None
    if r["language"] != "English": why = "language"
    elif r["turn"] != 1: why = "multi-turn"
    elif r["toxic"] or r["redacted"] or r["flagged"]: why = "toxic/redacted/flagged"
    elif not 60 <= len(u) <= 600: why = "length"
    elif u in seen: why = "duplicate"
    elif DOMAIN.search(u): why = "domain/preference word"
    elif ITEM_WORDS & set(re.findall(r"[a-z]{5,}", norm(u))): why = "mentions an item"
    elif BAD.search(u): why = "role-play/unsafe"
    elif len(re.findall(r"[{};=<>]", u)) > 15: why = "mostly code"
    seen.add(u)
    if why is None:
        ok.append(r)
random.Random("pib-v1.0-order").shuffle(ok)
with open("eligible.jsonl", "w") as f:
    for r in ok: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(rows), "candidates ->", len(ok), "eligible")
