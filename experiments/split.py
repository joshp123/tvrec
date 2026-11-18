"""Hold out test people and "new" titles, then learn level-1 neighbours from
everyone else's likes.

Test people: up to N per data set with at least 30 likes, plus people with at
least 10 liked series. New titles: a sample of series and films that test
people liked and that have plot text; every rating of them is removed, as if
they had just come out."""
import duckdb
import numpy as np

from core import W, like_matrix, neighbours

PER_SOURCE = {"netflix": 1500, "movielens": 1500, "letterboxd": 800, "trakt": 800, "amazon": 800, "movietweetings": 300}
SERIES_USERS = 2000
NEW_SERIES, NEW_FILMS = 800, 800
rng = np.random.default_rng(7)

con = duckdb.connect(config={"memory_limit": "6GB", "threads": 8})
con.execute(f"""create table likes as
    with m as (select u, t, source, r, avg(r) over (partition by u) um from '{W}/ratings.parquet')
    select m.u, m.t, m.source, coalesce(ti.is_series, 0)::int s from m left join '{W}/titles.parquet' ti using (t)
    where r >= 0.75 and r >= um""")
per_user = con.execute("select u, any_value(source) src, count(*) n, sum(s) ns from likes group by u").fetchnumpy()

test = []
for src, n in PER_SOURCE.items():
    pool = per_user["u"][(per_user["src"] == src) & (per_user["n"] >= 30)]
    test.append(rng.choice(pool, min(n, len(pool)), replace=False))
    print(src, "eligible", len(pool), "taken", len(test[-1]))
pool = np.setdiff1d(per_user["u"][per_user["ns"] >= 10], np.concatenate(test))
test.append(rng.choice(pool, min(SERIES_USERS, len(pool)), replace=False))
print("series-rich eligible", len(pool), "taken", len(test[-1]))
test = np.unique(np.concatenate(test))

con.execute("create table test as select unnest($1) u", [test.tolist()])
cands = con.execute(f"""
    select t, any_value(s) s, count(*) n from likes join test using (u)
    where t in (select t from '{W}/plot.parquet') group by t having count(*) >= 2""").fetchnumpy()
new = np.concatenate([
    rng.choice(cands["t"][cands["s"] == 1], min(NEW_SERIES, (cands["s"] == 1).sum()), replace=False),
    rng.choice(cands["t"][cands["s"] == 0], min(NEW_FILMS, (cands["s"] == 0).sum()), replace=False)])
print("test people", len(test), "new titles", len(new))

u, t = con.execute("select u, t from likes").fetchnumpy().values()
train = ~np.isin(u, test) & ~np.isin(t, new)
L, items = like_matrix(u[train], t[train])
print("train likes", L.nnz, "titles", L.shape[1], flush=True)
idx, val, cnt, n = neighbours(L)
np.savez(W / "nb_eval.npz", items=items, idx=idx, val=val, cnt=cnt, n=n, test=test, new=new)
con.execute(f"copy (select u, t, source, s from likes join test using (u)) to '{W}/test_likes.parquet' (format parquet)")
