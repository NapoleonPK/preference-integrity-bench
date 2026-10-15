"""Turn a free-text answer into a pick (or a hedge/refusal).

Rules (frozen for v1):
1. Items are matched on a normalised form (case, accents, punctuation, a leading 'The'
   ignored); 'Composer, Work' items also match on the work alone.
2. A reference to the list number ("number 3", "#3", "option 3") counts as that item.
3. One item mentioned -> that item.
4. Several mentioned -> the item named in an explicit choice phrase ("my favourite is X",
   "I'd pick X", "X is my favourite"); otherwise the first item named in the first sentence
   that names any item; if that sentence names more than one, the answer is 'ambiguous'.
5. No item and a hedge phrase -> 'hedge'; no item at all -> 'none'.
"""
import re
import unicodedata

CHOICE_BEFORE = r"(?:favou?rite(?: one)?(?: here| (?:on|from|in) (?:this|the) list)?(?: though| however)? (?:is|would be|has to be)|i(?:'d| would)? (?:pick|choose|go with|have to go with|select)|i(?:'m| am) (?:drawn|going) (?:to|with)|my (?:pick|choice|answer) (?:is|would be))"
CHOICE_AFTER = r"(?:is|would be|has to be) my (?:favou?rite|pick|choice)"
HEDGE = re.compile(r"(?:don't|do not|can't|cannot) (?:really )?(?:have|experience|taste|eat|hear|see)|as an ai|no personal (?:preference|favou?rite)|not able to have|i don't have (?:a )?favou?rite", re.I)


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def aliases(item):
    a = {norm(item)}
    n = norm(item)
    if n.startswith("the "):
        a.add(n[4:])
    if ", " in item:                       # "Bach, Goldberg Variations" -> "goldberg variations"
        work = item.split(", ", 1)[1]
        a.add(norm(work))
        if norm(work).startswith("the "):
            a.add(norm(work)[4:])
    return {x for x in a if len(x) >= 2}


# Items that are also everyday words: matched only capitalised, in the original text.
COMMON_WORD_ITEMS = {"Go": r"(?<![A-Za-z])Go(?![A-Za-z])(?! (?:with|for|to|ahead|back|on)\b)",
                     "Bridge": r"(?<![A-Za-z])Bridge(?![A-Za-z])"}


def _positions(text_n, item, original=None):
    if item in COMMON_WORD_ITEMS:
        if original is None:
            return []
        return [m.start() for m in re.finditer(COMMON_WORD_ITEMS[item], original)]
    pos = []
    for al in aliases(item):
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(al) + r"(?![a-z0-9])", text_n):
            pos.append(m.start())
    return sorted(pos)


def parse_pick(answer, items, presented_order=None):
    """Return dict(pick, status) with status in {ok, ambiguous, hedge, none}."""
    if not answer or not answer.strip():
        return {"pick": None, "status": "none"}
    text_n = norm(answer)
    found = {it: _positions(text_n, it, answer) for it in items}
    # numeric references to the presented list
    if presented_order:
        for m in re.finditer(r"(?:number|no|option|item|#)\s*(\d{1,2})\b", answer.lower()):
            k = int(m.group(1))
            if 1 <= k <= len(presented_order):
                found[presented_order[k - 1]] = found.get(presented_order[k - 1], []) + [10 ** 6]
    mentioned = [it for it, p in found.items() if p]
    if not mentioned:
        return {"pick": None, "status": "hedge" if HEDGE.search(answer) else "none"}
    if len(mentioned) == 1:
        return {"pick": mentioned[0], "status": "ok"}
    # explicit choice phrase: first an exact "favourite is X" anywhere, then (within one sentence)
    # allow up to three words in between ("my favourite is Ted Chiang's Exhalation")
    sentences = [norm(x) for x in re.split(r"(?<=[.!?])\s+|\n+", answer)]
    for gap, texts in ((r"", [text_n]), (r"(?:[a-z']+ ){0,3}?", sentences)):
        for t in texts:
            for it in mentioned:
                for al in aliases(it):
                    e = re.escape(al)
                    if re.search(CHOICE_BEFORE + r"\s+(?:probably |definitely |easily |clearly )?(?:the )?" + gap + e + r"(?![a-z0-9])", t) or \
                       re.search(e + r"(?:\s+\S+){0,6}?\s+" + CHOICE_AFTER, t):
                        return {"pick": it, "status": "ok"}
    # no choice phrase: an answer that opens with an item name ("Xiaolongbao: ...", "**Las Meninas** - ...")
    head = norm(answer[:120])
    for it in mentioned:
        for al in aliases(it):
            if re.match(re.escape(al) + r"(?![a-z0-9])", head):
                return {"pick": it, "status": "ok"}
    # first sentence that names an item
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    for s in sentences:
        sn = norm(s)
        here = [it for it in items if _positions(sn, it, s)]
        if len(here) == 1:
            return {"pick": here[0], "status": "ok"}
        if len(here) > 1:
            return {"pick": min(here, key=lambda it: _positions(sn, it, s)[0]), "status": "ambiguous"}
    return {"pick": None, "status": "ambiguous"}


def parse_pairwise(answer, a, b):
    m = re.fullmatch(r"\W*(?:option\s+)?([AB])\W*", (answer or "").strip(), re.I)
    if m:
        return a if m.group(1).upper() == "A" else b
    r = parse_pick(answer, [a, b])
    return r["pick"] if r["status"] == "ok" else None
