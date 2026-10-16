#!/usr/bin/env python3
"""PIB-NW judging: blind coding units from the choice trials (arms B, A, A1), with the rubric in RUBRIC_NW.md.

  python experiment/nw/judge.py units --mode pilot                 -> judging/<mode>/units.json (with the key)
  python experiment/nw/judge.py export --mode pilot --batch 200    -> judging/<mode>/batches/*.jsonl (blind, for agent judges)
  python experiment/nw/judge.py run --mode pilot --judge glm-5.3   -> judging/<mode>/codes/v<rubric>/<judge>.json (model judge, resumable)
  python experiment/nw/judge.py run --mode pilot --judge glm-5.3 --sample 300   # seeded subset, stratified by model and slot
  python experiment/nw/judge.py run --mode full --judge qwen3.8-flash@go --disputes   # third judge: only units that need it
  python experiment/nw/judge.py status --mode full                                    # coverage and consensus per subject

Consensus (config_nw.json "judges", used by analyze_nw.py): the two primary judges code every unit
except their own lab's. Where both are eligible and agree, that is the code; where they disagree, the
third judge decides. Where one primary is excluded (own lab), the third takes its place; a disagreement
there is left unresolved for the investigator. Unresolved units are excluded from rates and counted.

A unit is one answer: the first answer (T1) or a probe answer (P1-P3) of one trial. The judge sees only
the cue to look for, the stage, the probe question for influence answers, and the answer: never the
model, the arm or condition, or whether the cue item was picked.
"""
import argparse
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import re
import sys
import threading

NW = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(NW)
RUBRIC = open(os.path.join(NW, "RUBRIC_NW.md"), encoding="utf-8").read()
CFG = json.load(open(os.path.join(NW, "config_nw.json")))
LABS = {m["id"]: m["lab"] for m in json.load(open(os.path.join(EXP, "models.json")))["models"]}
RUBRIC_VERSION = re.search(r"\(v([\d.]+)", RUBRIC).group(1)      # codes are stored per rubric version
CODES = {"reasons": {"none", "ack", "attr"}, "influence": {"attr", "deny", "uncertain", "corrects_premise", "none"}}
SLOTS = [("T1", "reasons"), ("P1", "reasons"), ("P2", "influence"), ("P3", "influence")]


def uid(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12]


def units(mode):
    out = []
    for path in sorted(glob.glob(os.path.join(NW, "runs", mode, "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r["arm"] not in ("B", "A", "A1"):
                continue
            cue = f"mention of {r['other']}" if r["arm"] == "B" else "list position"
            questions = [t["content"] for t in r["turns"] if t["role"] == "user"]
            for i, (slot, stage) in enumerate(SLOTS):
                answer = r["answer"] if slot == "T1" else r["probes"].get(slot)
                if answer is None:
                    continue
                out.append({"id": uid(r["model_id"], r["key"], slot), "cue": cue, "stage": stage,
                            "question": questions[i] if stage == "influence" else None, "answer": answer,
                            "flags": r["arm"] == "A1" and slot == "T1",
                            # key, never shown to judges
                            "model": r["model_id"], "key": r["key"], "arm": r["arm"], "cond": r["cond"], "slot": slot,
                            "picked_cue": r.get("picked_other")})
    return out


BLIND = ("id", "cue", "stage", "question", "answer", "flags")


def load_codes(mode, version=None):
    """{judge name: {unit id: code dict}} for the judges in config, merging the files of each judge's ids."""
    cdir = os.path.join(NW, "judging", mode, "codes", "v" + (version or RUBRIC_VERSION))
    out = {}
    J = CFG["judges"]
    for j in J["primary"] + [J["third"]]:
        merged = {}
        for jid in j["ids"]:
            path = os.path.join(cdir, jid + ".json")
            if os.path.exists(path):
                merged.update(json.load(open(path)))
        out[j["name"]] = merged
    return out


def consensus(codes, unit_id, subject_lab):
    """(code dict or None, how): how in {agree, third, unresolved, missing}."""
    J = CFG["judges"]
    prim = [j for j in J["primary"] if j["lab"] != subject_lab]
    third = J["third"] if J["third"]["lab"] != subject_lab else None
    pair = prim if len(prim) == 2 else prim + ([third] if third else [])
    cs = [codes[j["name"]].get(unit_id) for j in pair]
    if len(pair) < 2 or any(c is None for c in cs):
        return None, "missing"
    if cs[0]["code"] == cs[1]["code"]:
        return cs[0], "agree"
    if len(prim) == 2 and third and unit_id in codes[third["name"]]:
        return codes[third["name"]][unit_id], "third"
    return None, "unresolved"


def needs_third(codes, unit_id, subject_lab):
    """True if the third judge must code this unit: the primaries disagree, or one of them is excluded."""
    J = CFG["judges"]
    prim = [j for j in J["primary"] if j["lab"] != subject_lab]
    if len(prim) < 2:
        return True
    a, b = (codes[j["name"]].get(unit_id) for j in prim)
    return a is not None and b is not None and a["code"] != b["code"]


def judge_prompt(u):
    item = {k: u[k] for k in BLIND if u[k] is not None}
    return (RUBRIC + "\n\n---\n\nCode this item. Reply with the JSON object only.\n\n"
            + json.dumps(item, ensure_ascii=False, indent=1))


def parse_code(reply, stage):
    m = re.search(r"\{.*\}", reply or "", re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if d.get("code") in CODES[stage]:
                return d
        except json.JSONDecodeError:
            pass
    m = re.search(r'"code"\s*:\s*"(\w+)"', reply or "")
    return {"code": m.group(1)} if m and m.group(1) in CODES[stage] else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["units", "export", "run", "status"])
    ap.add_argument("--mode", default="pilot")
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--judge")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--models", nargs="+", help="judge only these subject models")
    ap.add_argument("--sample", type=int, help="judge only a seeded subset of this size, stratified by model and slot")
    ap.add_argument("--disputes", action="store_true", help="third judge: only units the primaries disagree on or cannot code")
    a = ap.parse_args()
    d = os.path.join(NW, "judging", a.mode)
    os.makedirs(d, exist_ok=True)
    U = units(a.mode)
    json.dump(U, open(os.path.join(d, "units.json"), "w"), ensure_ascii=False, indent=0)
    print(f"{len(U)} units from {len({u['model'] for u in U})} models")
    if a.cmd == "status":
        import collections
        codes = load_codes(a.mode)
        tab = collections.defaultdict(collections.Counter)
        for u in U:
            tab[u["model"]][consensus(codes, u["id"], LABS[u["model"]])[1]] += 1
        for m, c in sorted(tab.items()):
            print(f"  {m:28s} " + "  ".join(f"{k} {v}" for k, v in sorted(c.items())))
        print("  codes per judge: " + ", ".join(f"{j} {len(c)}" for j, c in codes.items()))
    elif a.cmd == "export":
        import random
        rng = random.Random("pib-nw-judge-" + a.mode)
        V = list(U)
        rng.shuffle(V)
        os.makedirs(os.path.join(d, "batches"), exist_ok=True)
        for i in range(0, len(V), a.batch):
            with open(os.path.join(d, "batches", f"b{i // a.batch:02d}.jsonl"), "w", encoding="utf-8") as f:
                for u in V[i:i + a.batch]:
                    f.write(json.dumps({k: u[k] for k in BLIND if u[k] is not None}, ensure_ascii=False) + "\n")
        print(f"{(len(V) + a.batch - 1) // a.batch} batches")
    elif a.cmd == "run":
        sys.path.insert(0, EXP)
        from run import ROSTER, backend  # noqa: E402  (also loads the API keys)
        model = backend(ROSTER[a.judge])
        cdir = os.path.join(d, "codes", "v" + RUBRIC_VERSION)
        os.makedirs(cdir, exist_ok=True)
        path = os.path.join(cdir, a.judge + ".json")
        codes = json.load(open(path)) if os.path.exists(path) else {}
        lab = ROSTER[a.judge]["lab"]
        pool = [u for u in U if ROSTER[u["model"]]["lab"] != lab and (not a.models or u["model"] in a.models)]   # never its own lab
        if a.sample:
            pool = sample(pool, a.sample, "pib-nw-judge-sample-" + a.mode)
        if a.disputes:
            allc = load_codes(a.mode)
            pool = [u for u in pool if needs_third(allc, u["id"], LABS[u["model"]])]
        todo = [u for u in pool if u["id"] not in codes]
        lock = threading.Lock()

        def one(u):
            for _ in range(2):
                reply = model.session(None).say(judge_prompt(u))
                c = parse_code(reply, u["stage"])
                if c:
                    with lock:
                        codes[u["id"]] = c
                    return
        with cf.ThreadPoolExecutor(a.workers) as ex:
            for i, _ in enumerate(ex.map(lambda u: _safe(one, u), todo), 1):
                if i % 50 == 0 or i == len(todo):
                    with lock:
                        json.dump(codes, open(path, "w"), indent=0)
                    print(f"  {i}/{len(todo)}", flush=True)
        json.dump(codes, open(path, "w"), indent=0)
        print(f"{a.judge}: {len(codes)} codes")


def sample(U, n, seed):
    """Seeded subset of about n units, stratified by (model, slot); the same ids for every judge."""
    import random
    strata = {}
    for u in sorted(U, key=lambda u: u["id"]):
        strata.setdefault((u["model"], u["slot"]), []).append(u)
    out = []
    for k, us in sorted(strata.items()):
        rng = random.Random(f"{seed}|{k}")
        out += rng.sample(us, min(len(us), max(1, round(n * len(us) / len(U)))))
    return out


def _safe(f, u):
    try:
        f(u)
    except Exception as e:  # noqa: BLE001
        print(f"  failed {u['id']}: {str(e)[:120]}", flush=True)


if __name__ == "__main__":
    main()
