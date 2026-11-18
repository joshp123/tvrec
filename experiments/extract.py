"""Copy what the experiments need from the soup into data/work/exp/ as Parquet,
so a rebuild of the soup cannot change a run halfway."""
import duckdb, pathlib

OUT = pathlib.Path("data/work/exp")
OUT.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(config={"memory_limit": "6GB", "threads": 6})
con.execute("install sqlite; load sqlite; attach 'data/soup.sqlite' as soup (type sqlite, read_only)")

def dump(name, sql):
    con.execute(f"copy ({sql}) to '{OUT}/{name}.parquet' (format parquet)")
    print(name, con.execute(f"select count(*) from '{OUT}/{name}.parquet'").fetchone()[0])

# One row per person and title: editions and season discs of one title collapse to the best rating.
dump("ratings", """
    select r.user_key::int as u, cast(substr(r.tconst, 3) as int) as t, x.source,
           max((r.rating - s.scale_min::double) / (s.scale_max::double - s.scale_min::double))::float as r,
           max(r.ts) as ts
    from soup.rating r join soup.rater x using (user_key) join soup.source s on s.name = x.source
    where r.tconst is not null
    group by all""")
dump("watch", "select user_key::int as u, cast(substr(tconst, 3) as int) as t, plays, last_ts from soup.watch")
dump("titles", """
    select cast(substr(tconst, 3) as int) as t, tconst, kind, is_series, primary_title as title, start_year, end_year,
           genres, imdb_rating, imdb_votes, n_episodes
    from soup.title where kind in ('movie','tvSeries','tvMiniSeries','tvMovie','tvSpecial','video')""")
dump("credits", """
    select cast(substr(tconst, 3) as int) as t, nconst, role, billing, episodes
    from soup.credit where role in ('creator','writer','director','producer','actor','composer','cinematographer','editor')""")
dump("people", "select nconst, name from soup.person")
dump("scores", "select cast(substr(tconst, 3) as int) as t, scorer, score, votes from soup.public_score")
dump("facts", "select cast(substr(tconst, 3) as int) as t, fact, value, value_id from soup.title_fact where fact in ('country','creator','showrunner','genre','award','nomination','based_on','broadcaster')")
