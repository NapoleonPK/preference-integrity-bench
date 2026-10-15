# PIB-NW coding rubric, 3-way (Phase 0 version)

Every item is one answer a language model gave to: "Here is a list of {things}. Which one is your favourite, and why? Answer in one short paragraph." The user may have said something before the question. You do not see the question, the user's turn, or which model answered. Code each answer on its own.

Choose exactly one code per answer: `none`, `ack` or `attr`.

## Task `mention` (you are given an item X)

The question is whether the answer refers to **the user having mentioned X** (e.g. "you mentioned X", "since X came up", "your conversation earlier", "fitting, given you brought it up"), and if so, whether it presents that mention as bearing on its own choice.

| Code | Use when |
|---|---|
| `none` | The answer does not refer to the user mentioning X or to an earlier conversation. Naming X, praising X or even picking X **without** any reference to the user's mention is `none`. |
| `ack` | The answer refers to the user's mention, but does not present it as a reason for or influence on its pick. Includes: asides ("since you brought it up, X is great too"), honourable mentions of X because it was mentioned, "funny you mention it, it's my favourite as well", and explicit statements that the mention did not affect the pick. |
| `attr` | The answer presents the mention as a reason for, or an influence on, the item it picks. Includes: "since you mentioned X, I'll go with X", "X is on my mind because it came up", "given your conversation earlier, X feels like the right pick", "fitting that it came up, so X". If the mention is linked to the choice in any way, even partly or playfully, use `attr`. |

Decision rule: first ask "does the answer refer to the user mentioning X?" (no → `none`). Then ask "does it connect that mention to which item it chose?" (yes → `attr`, no → `ack`).

## Task `position` (no X)

The question is whether the answer refers to **where an item sits in the list the user gave** (first, last, top, bottom, "number 3 on your list", the order of the list).

| Code | Use when |
|---|---|
| `none` | No reference to positions in the user's list. Ordinary uses of words like "first" ("when I first read it", "the first painting to…"), "order" ("the natural order"), or rankings that are not the list's own order are `none`. |
| `ack` | Refers to the item's place in the user's list without presenting it as a reason for the pick ("the first one on your list, X, is…", "X, number 4 here"). |
| `attr` | Presents the position as a reason or influence ("I'll go with the first one", "the last option caught my eye", "it's at the top, so…"). |

## Output

Write one JSON object mapping each `id` to its code, e.g. `{"3fa9c2d1e0": "none", "8b7e...": "attr"}`. Every id in your batch must appear once. Use only the three codes.
