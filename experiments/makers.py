"""Who made each title: creators; for films, directors and writers; for series,
writers and directors credited on the series itself or on a fifth of its
episodes. A maker's weight falls with how many titles they made, so a link
through a rare maker counts for more."""
import duckdb
from core import W

con = duckdb.connect(config={"memory_limit": "6GB", "threads": 8})
con.execute(f"""copy (
    with ti as (select t, is_series, n_episodes from '{W}/titles.parquet'
                where kind in ('movie','tvSeries','tvMiniSeries') and imdb_votes >= 50),
         m as (select distinct c.t, c.nconst from '{W}/credits.parquet' c join ti using (t)
               where c.role = 'creator'
                  or (ti.is_series = 0 and c.role in ('director','writer'))
                  or (ti.is_series = 1 and c.role in ('director','writer')
                      and (c.billing is not null or c.episodes >= greatest(2, 0.2 * coalesce(ti.n_episodes, 0))))),
         n as (select nconst, count(*) n from m group by 1)
    select t, nconst, (1 / log2(1 + n))::float w from m join n using (nconst)
    ) to '{W}/makers.parquet' (format parquet)""")
print(con.sql(f"select count(*), count(distinct t), count(distinct nconst) from '{W}/makers.parquet'"))
