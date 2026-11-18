"""One drop of picks for a person: mostly the model picker's (picker.py), with
one of the ranker's best (picks.py) in each kind, so their answers show which
source earns its place. Each card carries its source in the data, not on the
card. Nothing they have seen, answered or been shown before; every pick shown
is recorded in private/shown.jsonl.

Usage: python drop.py PERSON [OTHER_PERSON]"""
import json
import sys
import time

import cards
import household
import picker
import picks as P

MODEL = {"new": 3, "decent": 2, "niche": 2}
RANKER = {"new": 1, "decent": 1, "niche": 1}
MIN_RATING = 6.8


def main(person, other=None):
    p = household.load(person)
    ti = picker.titles()
    exclude = picker.shown(person) | p.answered
    props = picker.resolve_all(picker.propose(p, ti), p, ti, exclude)
    chosen, used = [], set()
    for kind, n in MODEL.items():
        for x in props:
            t = x["t"]
            if (x["status"] == "ok" and x["pick"] == kind and t not in used and sum(c["kind"] == kind for c in chosen) < n
                    and not (ti.imdb_rating.get(t) == ti.imdb_rating.get(t) and ti.imdb_rating[t] < MIN_RATING)):
                chosen.append({"t": t, "kind": kind, "source": "model", "why": x["why"]})
                used.add(t)
    q = household.load(person)
    q.known |= exclude | used
    ranked, *_ = P.choose(q)
    for kind, n in RANKER.items():
        for t, k, stretch in sorted(ranked, key=lambda x: x[2]):
            if k == kind and t not in used and sum(c["kind"] == kind and c["source"] == "ranker" for c in chosen) < n:
                chosen.append({"t": t, "kind": kind, "source": "ranker", "why": None})
                used.add(t)
    order = {"new": 0, "decent": 1, "niche": 2}
    chosen.sort(key=lambda c: order[c["kind"]])
    cards.main(person, other, given=chosen, shown=exclude)
    with open(picker.SHOWN, "a") as f:
        for c in chosen:
            f.write(json.dumps({"person": person, "imdb_id": f"tt{c['t']:07d}", "source": c["source"],
                                "kind": c["kind"], "round": time.strftime("%Y-%m-%d %H:%M")}) + "\n")
    for c in chosen:
        print(c["source"], c["kind"], ti.title[c["t"]], int(ti.start_year[c["t"]]))
    print("model proposals:", len(props), "usable:", sum(x["status"] == "ok" for x in props),
          "unresolved:", sum(x["status"] == "unresolved" for x in props), "already known or shown:",
          sum(x["status"] == "known" for x in props))


if __name__ == "__main__":
    main(*sys.argv[1:3])
