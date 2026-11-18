"""Would the backlog find a person's own new favourites? Treat each as unseen
and unrated in turn, and report where it ranks in "New and good".
Usage: python check_new.py PERSON LEVEL TCONST..."""
import sys

import backlog

person, level = sys.argv[1], int(sys.argv[2])
for tc in sys.argv[3:]:
    t = int(tc[2:])
    cand, kinds, why, *_ = backlog.evidence(person, level, holdout=(t,))
    df = backlog.lanes_of(cand)["New and good"].copy()
    df["score"], df["why"] = backlog.fuse(df, kinds)
    df = df[df.is_series == df.is_series.get(t, 1)].sort_values("score", ascending=False)
    if t not in df.index:
        print(f"{tc}: not in the lane (filtered out)")
        continue
    r = df.loc[t]
    found = r.score > 0
    print(f"{r.title}: rank {list(df.index).index(t) + 1} of {len(df)}"
          + (f"; evidence: {why[r.why][t][1]}" if found else "; no evidence"),
          {k: round(float(r[k]), 4) for k in kinds})
