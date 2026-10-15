"""Build every prompt of a run, deterministically.

Every model sees exactly the same item orders, because each order is derived from
sha256(seed | call key), never from a global RNG.
"""
import hashlib
import json
import os
import random

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_materials(root=None):
    root = root or os.path.join(HERE, "materials")
    with open(os.path.join(root, "questions.json"), encoding="utf-8") as f:
        q = json.load(f)
    with open(os.path.join(root, "contexts.json"), encoding="utf-8") as f:
        c = json.load(f)
    return q, c


def rng_for(seed, *parts):
    h = hashlib.sha256("|".join([str(seed)] + [str(p) for p in parts]).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def shuffled(items, seed, *parts):
    order = list(items)
    rng_for(seed, "order", *parts).shuffle(order)
    return order


def numbered(order):
    return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(order))


def question_text(prompts, q, order, lead_in=False, pressure_line=None):
    body = prompts["question"].format(noun=q["noun"], list=numbered(order))
    if pressure_line:
        body = pressure_line + "\n\n" + body
    if lead_in:
        body = prompts["lead_in"] + body
    return body


def other_item(q, top, seed, ctx_id):
    """The item a user 'endorses': fixed per (context, question), never the model's own top."""
    pool = [t for t in q["items"] if t != top]
    return rng_for(seed, "other", ctx_id, q["id"]).choice(pool)


def cut_history(history, n_user_turns):
    """Keep the first n user turns and every message that follows them up to the next user turn."""
    if n_user_turns is None:
        return list(history)
    out, seen = [], 0
    for m in history:
        if m["role"] == "user":
            if seen == n_user_turns:
                break
            seen += 1
        out.append(m)
    return out


def user_turns(history):
    return [m["content"] for m in history if m["role"] == "user"]


def pairwise_pairs(q, top_items, seed, n_pairs=20, n_core=6):
    """Round-robin among the n_core most-picked baseline items (15 pairs for 6), plus random extra pairs."""
    core = list(top_items[:n_core])
    for t in q["items"]:
        if len(core) >= n_core:
            break
        if t not in core:
            core.append(t)
    pairs = [(a, b) for i, a in enumerate(core) for b in core[i + 1:]]
    rest = [(a, b) for i, a in enumerate(q["items"]) for b in q["items"][i + 1:]
            if (a, b) not in pairs and (b, a) not in pairs]
    rng_for(seed, "pairs", q["id"]).shuffle(rest)
    return pairs + rest[: max(0, n_pairs - len(pairs))]


def context_text(c):
    """The user-side text of a context (what topic pull is measured against)."""
    hist = c.get("history")
    if hist is None:
        return f"[placeholder for {c['id']}: {c['description']}]"
    return " ".join(m["content"] for m in hist if m["role"] == "user")
