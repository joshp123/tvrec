"""Picks for one person, chosen on the taste map.

1. Where the person sits: each cluster's strength is the sum of their evidence
   there (household.py), scaled so their strongest cluster is 1.
2. Stretch: a cluster they have not touched is reachable in proportion to its
   closeness to the clusters they are strong in.
3. Clusters are chosen first, then the best title in each: good (IMDb rating
   and critics), not too well known (fewer votes than the cluster's popular
   members), and linked to the person where possible (fans of their titles
   liked it more than its popularity predicts; it shares a maker with one of
   their titles). At most one pick per cluster and PER_SHELF per shelf, so
   the set is varied.
4. Three kinds of pick: new and good (out since 2024 or still running with a
   recent season), decent (widely watched, but not a streaming homepage
   staple), weird niche (little known).

No AI model is involved in choosing."""
import duckdb
import numpy as np
import pandas as pd

import household
from core import SHRINK, W, score

PER_KIND, SERIES_SHARE = 10, 0.7
OWN_SHARE = 0.6               # the rest are stretch picks from neighbouring clusters
HOMEPAGE = {1: 200_000, 0: 150_000}  # IMDb votes above which a title is too well known (series, films)
NICHE = 20_000
PROBABLY_SEEN = 40_000        # on the person's own shelves, a title this well known is a question, not a pick
MIN_RATING, MIN_VOTES = 7.2, 500
OBVIOUS = 0.15
STRETCH_LIKES = 0.008         # a stretch pick needs at least this pull from the person's titles, or a shared maker
TASTE_MIN = 0.15              # evidence this weak (library titles) marks a title as known, not as taste
PER_SHELF = 3                 # at most this many picks from one shelf (shelves.py), for variety


def load_map():
    m = duckdb.sql(f"select t, cluster from '{W}/map.parquet'").df()
    return dict(zip(m.t, m.cluster)), np.load(W / "closeness.npy")


def profile(person, cl, S):
    k = S.shape[0]
    strength = np.zeros(k)
    against = np.zeros(k)
    for t, (w, _) in person.evidence.items():
        if abs(w) < TASTE_MIN:
            continue
        c = cl.get(t)
        if c is None:
            continue
        if w > 0:
            strength[c] += w
        else:
            against[c] += -w
    own = np.clip(strength - 0.5 * against, 0, None)
    own = own / own.max() if own.max() > 0 else own
    reach = S @ own
    reach[own > 0.05] = 0
    reach[against > strength] = 0
    reach = reach / reach.max() if reach.max() > 0 else reach
    return own, reach, against


def candidates(person, cl):
    ti = duckdb.sql(f"""select ti.t, ti.tconst, ti.title, ti.start_year, ti.end_year, ti.is_series, ti.imdb_rating,
               ti.imdb_votes, ti.genres
        from '{W}/titles.parquet' ti where kind in ('movie','tvSeries','tvMiniSeries')""").df().set_index("t")
    rt = duckdb.sql(f"select t, scorer, score from '{W}/plex_scores.parquet' where scorer like 'rt%'").df()
    rt = rt.pivot_table(index="t", columns="scorer", values="score")
    ti = ti.join(rt)
    ti["cluster"] = ti.index.map(cl)
    ok = (ti.cluster.notna() & ~ti.index.isin(person.known) & (ti.imdb_votes >= MIN_VOTES)
          & ((ti.imdb_rating >= MIN_RATING) | ((ti.rt_critics >= 9.0) & (ti.imdb_rating >= 6.9))))
    ok &= ti.imdb_votes < np.where(ti.is_series == 1, HOMEPAGE[1], HOMEPAGE[0])
    return ti[ok].copy()


def links(person, cand):
    """For each candidate: the person's titles it is linked to, and how strongly,
    by other people's likes (popularity-corrected) and by shared makers."""
    d = np.load(W / "nb_full.npz")
    items, idx, cnt, n = d["items"], d["idx"], d["cnt"], d["n"]
    pos = {t: i for i, t in enumerate(items)}
    val = cnt / (np.sqrt(n)[:, None] * n[idx]) * (cnt / (cnt + SHRINK))
    val[cnt < 2] = 0
    pos_ev = [(t, w) for t, (w, why) in person.evidence.items() if w >= TASTE_MIN and t in pos]
    neg_ev = [t for t, (w, _) in person.evidence.items() if w < 0 and t in pos]
    cf, seed = score([pos[t] for t, _ in pos_ev], idx, val, len(items), "sum", [w for _, w in pos_ev])
    dis, _ = score([pos[t] for t in neg_ev], idx, val, len(items), "max") if neg_ev else (np.zeros(len(items)), None)
    obvious = set()
    for t, w in pos_ev:
        j = pos[t]
        if n[j] >= 200 and w >= 0.6:
            obvious |= set(items[idx[j][cnt[j] > OBVIOUS * n[j]]])
    out = {}
    for t in cand.index:
        if t in pos and cf[pos[t]] > 0:
            out[t] = {"likes": float(cf[pos[t]]), "likes_from": int(pos_ev[seed[pos[t]]][0]),
                      "dislike": float(dis[pos[t]])}
    mk = duckdb.sql(f"select t, nconst, share, w from '{W}/makers.parquet'").df()
    mine = {t: w for t, (w, _) in person.evidence.items() if w >= TASTE_MIN}
    fav = mk[mk.t.isin(mine.keys())]
    j = mk[mk.t.isin(cand.index)].merge(fav, on="nconst", suffixes=("", "_fav"))
    j = j[j.t != j.t_fav]
    j["link"] = j.w * j.w_fav * j.t_fav.map(mine)
    for t, g in j.groupby("t"):
        best = g.sort_values("link").iloc[-1]
        if best.link >= 0.1:
            out.setdefault(t, {}).update({"maker": float(best.link), "maker_from": int(best.t_fav), "maker_who": best.nconst})
    return out, obvious


def kind_of(r):
    if pd.isna(r.start_year):
        return "niche" if r.imdb_votes < NICHE else "decent"
    new = r.start_year >= 2024 or (r.is_series == 1 and r.start_year >= 2021 and (pd.isna(r.end_year) or r.end_year >= 2025))
    if new:
        return "new"
    return "niche" if r.imdb_votes < NICHE else "decent"


def choose(person):
    cl, S = load_map()
    own, reach, against = profile(person, cl, S)
    cand = candidates(person, cl)
    lk, obvious = links(person, cand)
    cand = cand[~cand.index.isin(obvious)]
    cand = cand[[lk.get(t, {}).get("dislike", 0) <= lk.get(t, {}).get("likes", 0) for t in cand.index]]
    c = cand.cluster.astype(int).values
    cand["own"] = own[c]
    cand["reach"] = reach[c]
    shelf = np.load(W / "shelves.npy")
    s_own = np.bincount(shelf, weights=own, minlength=shelf.max() + 1)
    cand["own_shelf"] = s_own[shelf[c]] > 0.2 * s_own.max()
    cand = cand[(cand.own > 0) | (cand.reach > 0)]
    cand = cand[~(cand.own_shelf & (cand.imdb_votes >= PROBABLY_SEEN))]
    # Quality: IMDb rating shrunk towards 7 when few people voted, plus critics where known.
    v = cand.imdb_votes.values
    cand["quality"] = (cand.imdb_rating * v + 7.0 * 2000) / (v + 2000) + 0.5 * cand.rt_critics.fillna(cand.imdb_rating).values / 10
    # Less obvious: votes relative to the cluster's most-voted title.
    top = cand.groupby("cluster").imdb_votes.transform("max")
    cand["obscurity"] = 1 - np.log1p(cand.imdb_votes) / np.log1p(np.maximum(top, 1000))
    likes = np.array([lk.get(t, {}).get("likes", 0) for t in cand.index])
    maker = np.array([lk.get(t, {}).get("maker", 0) for t in cand.index])
    cand["strong_link"] = (likes >= STRETCH_LIKES) | (maker >= 0.1)
    cand["link"] = (likes > 0) * 0.5 + (likes / (likes.max() or 1)) + np.minimum(maker, 1)
    cand["value"] = cand.quality + 0.5 * cand.obscurity + cand.link
    cand["kind"] = [kind_of(r) for r in cand.itertuples()]

    picks, used, per_shelf = [], set(), {}
    for kind in ("new", "decent", "niche"):
        pool = cand[cand.kind == kind]
        for want_series, n_want in ((1, round(PER_KIND * SERIES_SHARE)), (0, PER_KIND - round(PER_KIND * SERIES_SHARE))):
            part = pool[pool.is_series == want_series]
            for stretch, share in ((False, OWN_SHARE), (True, 1 - OWN_SHARE)):
                k = round(n_want * share) if not stretch else n_want - round(n_want * OWN_SHARE)
                sub = part[(part.reach > 0) & part.strong_link] if stretch else part[part.own > 0]
                # Best title per cluster, then clusters in order of how much they matter to the person.
                sub = sub.sort_values("value", ascending=False).drop_duplicates("cluster")
                weight = sub.reach if stretch else sub.own
                sub = sub.assign(order=weight * sub.value).sort_values("order", ascending=False)
                got = 0
                for t, r in sub.iterrows():
                    sh = int(shelf[int(r.cluster)])
                    if r.cluster in used or per_shelf.get(sh, 0) >= PER_SHELF:
                        continue
                    used.add(r.cluster)
                    per_shelf[sh] = per_shelf.get(sh, 0) + 1
                    picks.append((t, kind, stretch))
                    got += 1
                    if got == k:
                        break
    return picks, cand, lk, own, reach, against, cl, S
