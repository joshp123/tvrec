"""Test a personal pairwise ranker against the old ranker and the model picker.

PASS MARK, fixed before the first run (18 Nov 2026):
  (a) leave-one-out AUC, his stated loves and likes against his stated dislikes,
      slop and one-episode drops: at least 0.10 above the old ranker's;
  (b) with each of his less famous loves hidden, its median rank among all
      candidate series he does not already know: better than the old ranker's;
  (c) of those hidden titles, the number ranked in the top 40 series: no fewer
      than the model picker's exam count (proposed among its 40) minus 2.
If it fails, it fails: no tuning to pass.

The ranker: logistic regression on feature differences between pairs of his
labelled titles (labels.py), L2-regularised with C fixed at 0.1, no intercept.
Features (features.py): what each title is, plus its links to his loved and
liked titles and to his disliked ones, by makers, repeat cast, tropes and tags,
and EASE crowd links. Pairs from household viewing count at their weight
(0.3). Uncertainty per title by a Laplace approximation.

The old ranker: the sum of popularity-corrected likes links from his loved and
liked titles (picks.py's pull). The model picker: its exam (exam.py).

Usage: python ranker_test.py PERSON [--tone]   (--tone adds cached tone scores)"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

import household
import labels as LB
from core import SHRINK, W

C_REG = 0.1
NICHE_VOTES = 100_000  # his loved and liked titles below this many IMDb votes are the "less famous" ones
LINKS = ("makers", "cast", "tropes", "crowd")


def link_features(d, lab, hide):
    """Links of every candidate to the labelled titles, without the hidden one."""
    rows = list(d["rows"])
    lev = np.array([lab.level[t] for t in rows], float)
    wt = np.array([lab.weight[t] for t in rows], float)
    mask = np.array([t != hide for t in rows])
    pos = np.where(mask & (lev >= 3), (lev - 2) / 2 * wt, 0)
    neg = np.where(mask & (lev <= 1), wt, 0)
    out = {}
    for k in LINKS:
        L = d[f"L_{k}"]
        if k == "tropes":
            out[f"{k}_to_liked"] = (L * (pos > 0)[:, None]).max(0)
            out[f"{k}_to_disliked"] = (L * (neg > 0)[:, None]).max(0)
        else:
            out[f"{k}_to_liked"] = pos @ L
            out[f"{k}_to_disliked"] = neg @ L
    return pd.DataFrame(out, index=d["cols"])


def design(d, lab, hide, tone=None):
    F = pd.DataFrame(d["F"], index=d["cols"], columns=d["names"])
    nets = pd.Series(d["nets"], index=d["cols"])
    common = [n for n, k in nets[nets.index.isin(lab.index)].value_counts().items() if k >= 2 and n]
    for n in common:
        F[f"net_{n}"] = (nets == n).astype(float)
    X = pd.concat([F, link_features(d, lab, hide)], axis=1)
    if tone is not None:
        X = X.join(tone, how="inner")
    return (X - X.mean()) / (X.std() + 1e-6)


def fit(X, lab, hide):
    tr = [t for t in lab.index if t != hide and t in X.index]
    rows, ws = [], []
    for i in tr:
        for j in tr:
            if lab.level[i] > lab.level[j]:
                rows.append(X.loc[i].values - X.loc[j].values)
                ws.append(lab.weight[i] * lab.weight[j])
    D = np.array(rows)
    y = np.r_[np.ones(len(D)), np.zeros(len(D))]
    D2 = np.vstack([D, -D])
    w2 = np.r_[ws, ws]
    m = LogisticRegression(C=C_REG, fit_intercept=False, max_iter=2000).fit(D2, y, sample_weight=w2)
    beta = m.coef_.ravel()
    p = 1 / (1 + np.exp(-D2 @ beta))
    H = (D2 * (w2 * p * (1 - p))[:, None]).T @ D2 + np.eye(len(beta)) / C_REG
    return beta, np.linalg.inv(H)


def old_scores(lab, hide, cols):
    d = np.load(W / "nb_people.npz")
    items, idx, cnt, n = d["items"], d["idx"], d["cnt"], d["n"]
    pos = {t: i for i, t in enumerate(items)}
    val = d["val"] / np.sqrt(d["n_weighted"][idx])
    val[cnt < 5] = 0
    s = np.zeros(len(items))
    for t in lab.index:
        if t != hide and lab.level[t] >= 3 and t in pos:
            np.add.at(s, idx[pos[t]], val[pos[t]] * (lab.level[t] - 2) / 2 * lab.weight[t])
    return pd.Series([s[pos[t]] if t in pos else 0.0 for t in cols], index=cols)


def main(person, use_tone):
    p = household.load(person)
    lab = LB.labels(p)
    d = np.load(W / f"features-{person}.npz", allow_pickle=True)
    cols = d["cols"]
    tone = pd.read_parquet(W / f"tone-{person}.parquet") if use_tone else None
    ti = pd.DataFrame(d["F"], index=cols, columns=d["names"])
    titles = dict(__import__("duckdb").sql(f"select t, title from '{W}/titles.parquet'").fetchall())
    series = set(ti.index[ti.is_series == 1])
    known = set(p.known) | set(lab.index)
    said = [t for t in lab.index if lab.weight[t] == 1.0 and lab.level[t] != 2]
    rows = []
    for h in said:
        X = design(d, lab, h, tone)
        if h not in X.index:
            continue
        beta, cov = fit(X, lab, h)
        new = pd.Series(X.values @ beta, index=X.index)
        old = old_scores(lab, h, list(X.index))
        pool = [t for t in X.index if t in series and (t not in known or t == h)]
        r_new = int((new[pool] > new[h]).sum()) + 1
        r_old = int((old[pool] > old[h]).sum()) + 1
        rows.append({"t": h, "title": titles.get(h, h), "label": lab.label[h], "level": lab.level[h],
                     "new": new[h], "old": old[h], "rank_new": r_new, "rank_old": r_old, "pool": len(pool)})
    res = pd.DataFrame(rows)
    good = res.level >= 3
    bad = res.level <= 1
    sub = res[good | bad]
    auc_new = roc_auc_score(good[good | bad], sub.new)
    auc_old = roc_auc_score(good[good | bad], sub.old)
    votes = dict(__import__("duckdb").sql(f"select t, imdb_votes from '{W}/titles.parquet'").fetchall())
    niche = res[(res.level >= 3) & res.t.map(lambda t: (votes.get(t) or 0) < NICHE_VOTES)]
    exam = {r["imdb_id"]: r for r in json.loads((household.PRIVATE / f"exam-{person}.json").read_text())}
    model_hits = sum(exam.get(f"tt{t:07d}", {}).get("proposed", False) for t in niche.t)
    model_n = sum(f"tt{t:07d}" in exam for t in niche.t)
    top40_new, top40_old = int((niche.rank_new <= 40).sum()), int((niche.rank_old <= 40).sum())
    passed = (auc_new >= auc_old + 0.10, niche.rank_new.median() < niche.rank_old.median(), top40_new >= model_hits - 2)
    print(f"AUC, loves and likes against dislikes and slop (leave one out): new {auc_new:.2f}, old {auc_old:.2f}")
    print(f"hidden less famous loves ({len(niche)}): median rank among {int(niche['pool'].median())} series, "
          f"new {niche.rank_new.median():.0f}, old {niche.rank_old.median():.0f}; in top 40: new {top40_new}, "
          f"old {top40_old}, model picker {model_hits} of the {model_n} it was examined on")
    print("pass marks (a, b, c):", passed, "->", "PASS" if all(passed) else "FAIL")
    print("\nordering by the new ranker's leave-one-out score:")
    for r in res.sort_values("new", ascending=False).itertuples():
        e = exam.get(f"tt{r.t:07d}", {})
        print(f"  {r.new:+7.2f} {r.label:26} {r.title[:34]:34} rank new {r.rank_new:>5} old {r.rank_old:>5}"
              f"  model picker {'back' if e.get('proposed') else '-' if e else 'n/a'}")
    res.to_parquet(W / f"ranker_test-{person}{'-tone' if use_tone else ''}.parquet")

    if all(passed):
        X = design(d, lab, None, tone)
        beta, cov = fit(X, lab, None)
        score = pd.Series(X.values @ beta, index=X.index)
        sd = pd.Series(np.sqrt(np.einsum("ij,jk,ik->i", X.values, cov, X.values)), index=X.index)
        import picker
        fresh = [t for t in X.index if t not in known and t not in picker.shown(person) and t not in p.answered]
        top = score[fresh].sort_values(ascending=False).head(12)
        print("\ntop picks not seen, answered or shown (score, uncertainty, what drove it):")
        for t in top.index:
            contrib = pd.Series(X.loc[t].values * beta, index=X.columns).sort_values(ascending=False)
            drivers = ", ".join(f"{k} {v:+.2f}" for k, v in contrib.head(4).items())
            print(f"  {score[t]:+.2f} ±{sd[t]:.2f} {titles.get(t, t)[:40]:40} {drivers}")
        print("\nweights:", ", ".join(f"{k} {v:+.2f}" for k, v in sorted(zip(X.columns, beta), key=lambda x: -abs(x[1]))[:12]))


if __name__ == "__main__":
    main(sys.argv[1], "--tone" in sys.argv)
