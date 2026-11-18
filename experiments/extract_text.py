"""Plot text and Plex scores straight from the fetch files, which run ahead of
the soup while fetching continues. Rerun to pick up more text."""
import duckdb
from core import W

RAW = W.parent.parent / "raw"
con = duckdb.connect(config={"memory_limit": "6GB", "threads": 6})
con.execute(f"install sqlite; load sqlite; attach '{W.parent.parent}/soup.sqlite' as soup (type sqlite, read_only)")
con.execute(f"""create table plex as
    select tconst, metadata as m
    from read_json('{RAW}/plex_metadata/metadata.jsonl', format='newline_delimited', ignore_errors=true,
                   columns={{'tconst':'varchar','metadata':'json'}})
    where metadata is not null qualify row_number() over (partition by tconst) = 1""")
con.execute(f"""copy (
    with p as (select tconst, 'plex' src, m->>'$.summary' txt from plex),
         w as (select l.tconst, 'wikipedia' src, any_value(w.text) txt
               from read_json('{RAW}/wikipedia/intros.jsonl', format='newline_delimited', ignore_errors=true,
                              columns={{'enwiki':'varchar','text':'varchar'}}) w
               join soup.title_link l on url_decode(l.enwiki) = w.enwiki group by 1),
         a as (select tconst, 'amazon' src, text txt from soup.plot where source = 'amazon')
    select cast(substr(tconst, 3) as int) t, src, txt from (from p union all from w union all from a)
    where length(trim(txt)) > 20) to '{W}/plot.parquet' (format parquet)""")
con.execute(f"""copy (
    with r as (select tconst, unnest(json_extract(m, '$.Rating[*]')) r from plex)
    select cast(substr(tconst, 3) as int) t,
           case when r->>'$.image' like 'rottentomatoes://%' and r->>'$.type' = 'critic' then 'rt_critics'
                when r->>'$.image' like 'rottentomatoes://%' then 'rt_audience'
                when r->>'$.image' like 'imdb://%' then 'imdb' else 'tmdb' end scorer,
           max((r->>'$.value')::double) score
    from r group by all) to '{W}/plex_scores.parquet' (format parquet)""")
print(con.sql(f"select src, count(*) from '{W}/plot.parquet' group by 1"))
print(con.sql(f"select scorer, count(*) from '{W}/plex_scores.parquet' group by 1"))
