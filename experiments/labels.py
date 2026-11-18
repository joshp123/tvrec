"""A person's labels for the personal ranker: their own verdicts and answers,
plus household viewing as weak evidence.

Levels (higher is better): loved 4; liked or seen and fine 3; a show the
household watched to the end 3, but as weak evidence; wanted 2; not for me 1;
disliked, slop, or a show dropped after one episode 0. Titles the other person
was judged to watch alone never count as this person's."""
import pandas as pd

LEVEL = {"loved": 4, "seen_loved": 4, "liked": 3, "seen_fine": 3, "want": 2, "wants to watch": 2,
         "not_for_me": 1, "disliked": 0, "slop": 0, "seen_disliked": 0}


def labels(p):
    rows = []
    for t, (w, why) in p.evidence.items():
        if why.startswith("said: "):
            v = why[6:].split(" (")[0]
            if v in LEVEL:
                rows.append((t, LEVEL[v], 1.0, v))
        elif "dropped after one episode" in why:
            rows.append((t, 0, 1.0, "dropped after one episode"))
        elif "episodes played" in why and w > 0 and "other person" not in why:
            rows.append((t, 3, 0.3, "watched to the end"))
    return pd.DataFrame(rows, columns=["t", "level", "weight", "label"]).drop_duplicates("t").set_index("t")
