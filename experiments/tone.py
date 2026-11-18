"""Tone scores, offline and cached: the frontier model rates each title once on
ten axes of tone and execution, so a ranker can use them as numbers with no
model at run time. Titles: the person's labelled titles, the ranker's top 150
by features alone (ranker_test.py), and 100 random series, for contrast.

Usage: python tone.py PERSON   writes data/work/exp/tone-<person>.parquet"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import duckdb
import numpy as np
import pandas as pd

import content
import household
import labels as LB
import ranker_test as RT
from core import W
from eval_verdicts import claude

AXES = ["formulaic", "deadpan", "cruel_or_bleak", "sentimental", "about_institutions", "formally_odd",
        "absurd", "satirical", "broad_mainstream_appeal", "topical_dated"]
CACHE = W / "tone_cache.json"


def pool(person):
    p = household.load(person)
    lab = LB.labels(p)
    d = np.load(W / f"features-{person}.npz", allow_pickle=True)
    X = RT.design(d, lab, None)
    beta, _ = RT.fit(X, lab, None)
    score = pd.Series(X.values @ beta, index=X.index).drop(lab.index, errors="ignore")
    F = pd.DataFrame(d["F"], index=d["cols"], columns=d["names"])
    series = F.index[F.is_series == 1].difference(lab.index)
    rng = np.random.default_rng(3)
    return list(lab.index) + list(score.sort_values(ascending=False).index[:150]) + list(rng.choice(series, 100, replace=False))


def main(person):
    ts = list(dict.fromkeys(pool(person)))
    ti = dict(((t, (n, y)) for t, n, y in duckdb.sql(f"select t, title, start_year from '{W}/titles.parquet'").fetchall()))
    plots = content.display_plots(300)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [t for t in ts if str(t) not in cache]

    def ask(batch):
        items = [{"id": int(t), "title": ti[t][0], "year": ti[t][1], "plot": plots.get(t, "")} for t in batch]
        prompt = ("Rate each film or series below from 0 to 10 on each of these axes of tone and execution: "
                  + ", ".join(AXES) + ". Judge the work itself as you know it, not its popularity. "
                  "Reply with only JSON: [{\"id\": 123, " + ", ".join(f'"{a}": 0' for a in AXES) + "}]\n\n"
                  + "\n".join(json.dumps(x, ensure_ascii=False) for x in items))
        return claude(prompt) or []

    batches = [todo[i:i + 25] for i in range(0, len(todo), 25)]
    with ThreadPoolExecutor(3) as ex:
        for res in ex.map(ask, batches):
            for r in res:
                if all(a in r for a in AXES):
                    cache[str(r["id"])] = {a: float(r[a]) for a in AXES}
    CACHE.write_text(json.dumps(cache))
    df = pd.DataFrame([{"t": t, **{f"tone_{a}": cache[str(t)][a] for a in AXES}} for t in ts if str(t) in cache]).set_index("t")
    df.to_parquet(W / f"tone-{person}.parquet")
    print("scored", len(df), "of", len(ts))


if __name__ == "__main__":
    main(sys.argv[1])
