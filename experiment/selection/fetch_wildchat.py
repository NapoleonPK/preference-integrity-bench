"""Fetch candidate first turns from WildChat-1M (allenai, ODC-BY) at seeded random offsets.
Usage: python fetch_wildchat.py  -> candidates_raw.jsonl"""
import json, random, time, urllib.request
SEED, N_PAGES, PAGE, TOTAL = "pib-v1.0-contexts", 40, 100, 837989
rng = random.Random(SEED)
offsets = sorted(rng.randrange(0, TOTAL - PAGE) for _ in range(N_PAGES))
out = open("candidates_raw.jsonl", "w")
for off in offsets:
    url = f"https://datasets-server.huggingface.co/rows?dataset=allenai/WildChat-1M&config=default&split=train&offset={off}&length={PAGE}"
    for attempt in range(5):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=60)); break
        except Exception as e:
            time.sleep(3 * 2 ** attempt)
    for row in d["rows"]:
        r = row["row"]
        conv = r["conversation"]
        out.write(json.dumps({"row_idx": row["row_idx"], "hash": r["conversation_hash"], "turn": r["turn"],
                              "language": r["language"], "toxic": r.get("toxic"), "redacted": r.get("redacted"),
                              "flagged": any(m.get("flagged") for m in (r.get("openai_moderation") or [])),
                              "user": conv[0]["content"] if conv and conv[0]["role"] == "user" else None}, ensure_ascii=False) + "\n")
    print(off, len(d["rows"]), flush=True)
