"""The exam: does the picker bring back what a person loved, and keep out what
they called slop? Run without them whenever the picker changes; it grows with
every answer they give.

For each of the person's own verdicts and answers, hide it (the title, its
words, and any other words that name it) and ask the picker for a drop of
proposals, as the person would. A title they loved or liked should come back;
a title they disliked or called slop should not.

What it can show: whether the picker reaches the person's known goods and
avoids their known bads from the rest of what they said. What it cannot:
whether they would want anything new (only they can say), and for famous
titles a hit may come from the model knowing the title rather than reading
the person; titles with few IMDb votes are reported apart for that reason.

Usage: python exam.py PERSON   writes private/exam-<person>.json and prints a table"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import household
import picker

PRIVATE = household.PRIVATE
FAMOUS = 100_000
GOOD = ("loved", "liked", "seen_loved", "seen_fine")
BAD = ("disliked", "slop", "not_for_me", "seen_disliked")


def hidden_copy(p, t, title):
    q = household.Person(p.name, dict(p.evidence), set(p.known), dict(p.words), set(p.answered), set(p.in_library))
    q.evidence.pop(t, None)
    q.known.discard(t)
    own = q.words.pop(t, "")
    key = re.sub(r"^the ", "", household.norm(title)).replace(" ", "")
    for u, w in list(q.words.items()):
        if w == own or key in household.norm(w).replace(" ", ""):
            q.words.pop(u)
    return q


def main(person):
    p = household.load(person)
    ti = picker.titles()
    cases = [(t, why[6:]) for t, (w, why) in p.evidence.items()
             if why.startswith("said") and why[6:] in GOOD + BAD and t in ti.index]

    def run(case):
        t, verdict = case
        q = hidden_copy(p, t, ti.title[t])
        props = picker.resolve_all(picker.propose(q, ti, hide={t}), q, ti, set())
        got = [x["t"] for x in props if x["t"]]
        return {"imdb_id": f"tt{t:07d}", "title": ti.title[t], "votes": int(ti.imdb_votes[t] or 0), "verdict": verdict,
                "words": p.words.get(t, ""), "proposed": t in got,
                "rank": got.index(t) + 1 if t in got else None, "n_proposed": len(got),
                "proposed_bad": [ti.title[u] for u in got if u != t and p.evidence.get(u, (0, ""))[0] < 0]}

    picker.recent_all(ti)
    picker.resolver(ti)
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(run, cases))
    (PRIVATE / f"exam-{person}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))

    def line(rs, kind):
        hits = sum(r["proposed"] for r in rs)
        return f"{kind}: {hits} of {len(rs)} came back" if rs else f"{kind}: none"
    good = [r for r in res if r["verdict"] in GOOD]
    bad = [r for r in res if r["verdict"] in BAD]
    print(line([r for r in good if r["votes"] < FAMOUS], "loved or liked, less famous"))
    print(line([r for r in good if r["votes"] >= FAMOUS], "loved or liked, famous"))
    print(line(bad, "disliked or slop (should not come back)"))
    print("runs that proposed something else they had called bad:", sum(bool(r["proposed_bad"]) for r in res), "of", len(res))
    for r in sorted(res, key=lambda r: (r["verdict"] in BAD, r["votes"])):
        print(f"{r['title'][:34]:34} {r['votes']:>9,} {r['verdict']:12} {'BACK' if r['proposed'] else '-':5} "
              f"{r['rank'] or '':3} {', '.join(r['proposed_bad'])}")


if __name__ == "__main__":
    main(sys.argv[1])
