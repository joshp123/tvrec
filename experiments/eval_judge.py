"""Level 3 on a small sample: a frontier model, run through the local `claude`
command under the subscription, reorders the top 30 that a lower level found.
Only people with at least one hidden like in that 30 are used, since only
for them can reordering change the result; we count hidden likes in the top 10
before and after.

  new:   titles nobody has rated (pool from level 2, else level 1)
  rated: series with ratings, for long-tail people (pool from level 1)"""
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import duckdb
import numpy as np
import pandas as pd

from content import display_plots
from core import W

POOL, TOP, PER_CASE = 30, 10, 40
MODEL = "opus"
rng = np.random.default_rng(3)
ti = duckdb.sql(f"select t, title, start_year, is_series from '{W}/titles.parquet'").df().set_index("t")
plot = display_plots(300)

SYSTEM = "You are a film and television expert helping rank recommendations."


def label(t):
    r = ti.loc[t]
    return f"{r.title} ({r.start_year})"


def ask(seeds, cands):
    seeds = [t for t in seeds if t in ti.index]
    lines = [f"[{i}] {label(t)}, {'series' if ti.loc[t].is_series else 'film'}: {plot.get(t, '(no plot text)')}"
             for i, t in enumerate(cands)]
    prompt = ("A viewer rated these titles highly:\n" + "\n".join(label(t) for t in seeds) +
              f"\n\nRank all {len(cands)} candidates below from most to least likely to be rated highly by this viewer. "
              "Reply with only the candidate numbers in order, comma-separated.\n\n" + "\n".join(lines))
    out = subprocess.run(["claude", "-p", "--model", MODEL, "--tools", "", "--strict-mcp-config", "--safe-mode",
                          "--setting-sources", "", "--system-prompt", SYSTEM, "--no-session-persistence"],
                         input=prompt, capture_output=True, text=True, timeout=600, cwd="/tmp").stdout
    order = []
    for x in re.findall(r"\d+", out):
        if int(x) < len(cands) and int(x) not in order:
            order.append(int(x))
    return order + [i for i in range(len(cands)) if i not in order], len(order)


def new_cases():
    import eval_new as E
    sig_name = "level 1: makers + words"
    out = []
    for u, liked_new, seeds in E.people():
        sig = E.signals(seeds)[sig_name]
        for kind, m in (("series", E.new_ser), ("films", ~E.new_ser)):
            pool = np.flatnonzero(m)[np.argsort(-sig[m])][:POOL]
            hit = np.isin(pool, liked_new)
            if hit.any():
                out.append(("new " + kind, u, [E.items[s] for s in seeds], [E.new[p] for p in pool], hit))
    out = [c for c in out if all(t in ti.index for t in c[3])]
    return out, sig_name


def rated_cases():
    import eval_warm as R
    out = []
    tl = duckdb.sql(f"select u, t from '{W}/test_likes.parquet'").df()
    for u, g in tl.groupby("u"):
        warm = np.array([R.pos[t] for t in g.t if t in R.pos])
        if len(warm) < 30 or R.little[warm].mean() < 0.25:
            continue
        seeds = rng.choice(warm, 20, replace=False)
        sc = R.agg(seeds, "sum") + R.tie
        sc[seeds] = -np.inf
        sc[~R.ser] = -np.inf
        pool = np.argsort(-sc)[:POOL]
        hit = np.isin(pool, np.setdiff1d(warm, seeds))
        if hit.any():
            out.append(("rated series, long-tail people", u, [R.items[s] for s in seeds], [R.items[p] for p in pool], hit))
    out = [c for c in out if all(t in ti.index for t in c[3])]
    return out


def main(which):
    sample, sig_name = [], "level 1 (sum)"
    if which == "new":
        cases, sig_name = new_cases()
        by = {}
        for c in cases:
            by.setdefault(c[0], []).append(c)
        for k, v in by.items():
            sample += [v[i] for i in rng.choice(len(v), min(PER_CASE // 2, len(v)), replace=False)]
        print({k: len(v) for k, v in by.items()}, flush=True)
    else:
        rated = rated_cases()
        sample += [rated[i] for i in rng.choice(len(rated), min(PER_CASE, len(rated)), replace=False)]
        print("rated", len(rated), flush=True)

    def run(c):
        order, parsed = ask(c[2], c[3])
        return c[0], c[1], c[4][:TOP].sum(), c[4][order][:TOP].sum(), c[4].sum(), parsed

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(run, sample))
    df = pd.DataFrame(res, columns=["case", "u", "lower_hits", "judge_hits", "in_pool", "parsed"])
    df.to_parquet(W / f"eval_judge_{which}.parquet")
    print(f"pool from: {sig_name}; model: {MODEL}")
    print(df.groupby("case").agg(people=("u", "count"), hidden_likes_in_pool=("in_pool", "sum"),
                                 top10_lower=("lower_hits", "sum"), top10_judge=("judge_hits", "sum"),
                                 judge_better=("judge_hits", lambda s: (s > df.loc[s.index, "lower_hits"]).sum()),
                                 judge_worse=("judge_hits", lambda s: (s < df.loc[s.index, "lower_hits"]).sum()),
                                 fully_parsed=("parsed", lambda s: (s == POOL).sum())))


if __name__ == "__main__":
    main(sys.argv[1])
