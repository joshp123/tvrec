"""Who made each title, and how much of it.

share: a creator (IMDb's creator credit, Wikidata's creator, or Wikidata's
showrunner who also wrote a fifth or more of it, since Wikidata lists many
executive producers as showrunners) made all of it, 1. A film's director, 1; its writer, 0.7. A series' writer or
director made the share of episodes they are credited on, halved. Someone
also credited as cast is not a maker unless they are a creator or one of at
most two writers (a double act writing its own show). A maker's
rarity falls with how many titles they made a fifth or more of.

w = share * sqrt(rarity), so the link between two titles, the sum over shared
makers of w(a) * w(b), is share(a) * share(b) * rarity."""
import duckdb

from core import W

con = duckdb.connect(config={"memory_limit": "6GB", "threads": 8})
con.execute(f"""create table m as
    with ti as (select t, is_series, n_episodes from '{W}/titles.parquet'
                where kind in ('movie','tvSeries','tvMiniSeries') and imdb_votes >= 50),
         c as (select * from '{W}/credits.parquet' where t in (select t from ti)),
         cast_ as (select distinct t, nconst from c where role = 'actor'),
         creators as (select t, nconst from c where role = 'creator'
                      union select t, value_id from '{W}/facts.parquet'
                      where fact = 'creator' and value_id like 'nm%' and t in (select t from ti)
                      union select f.t, f.value_id from '{W}/facts.parquet' f
                      join c on c.t = f.t and c.nconst = f.value_id and c.role = 'writer'
                      join ti on ti.t = f.t
                      where f.fact = 'showrunner' and (ti.is_series = 0 or c.episodes >= 0.2 * ti.n_episodes)),
         crew as (select c.t, c.nconst,
                         case when ti.is_series = 0 then (case when c.role = 'director' then 1.0 else 0.7 end)
                              when c.episodes is not null and ti.n_episodes > 0 then 0.5 * least(1.0, c.episodes / ti.n_episodes)
                              when c.billing is not null then 0.5 else 0 end as share
                  from c join ti using (t)
                  where c.role in ('writer','director')
                    and ((c.t, c.nconst) not in (select t, nconst from cast_)
                         or c.t in (select t from c where role = 'writer' group by t having count(*) <= 2))),
         s as (select t, nconst, 1.0 share from creators
               union all select t, nconst, share from crew)
    select t, nconst, max(share) share from s group by all having max(share) > 0""")
con.execute(f"""copy (
    with n as (select nconst, count(*) n from m where share >= 0.2 group by 1)
    select t, nconst, share::float share, (share * sqrt(1 / log2(1 + greatest(coalesce(n.n, 1), 1))))::float w
    from m left join n using (nconst)) to '{W}/makers.parquet' (format parquet)""")
print(con.sql(f"select count(*), count(distinct t), count(distinct nconst) from '{W}/makers.parquet'"))
