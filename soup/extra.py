"""Public sources that describe titles rather than rate them."""

import zipfile

from .db import RAW, WORK


def tvtropes(con):
    """TV Tropes trope-to-work links already matched to IMDb by Gala et al."""
    d = WORK / "tvtropes" / "TVTropesData"
    if not (d / "tv_imdb_match.csv").exists():
        with zipfile.ZipFile(RAW / "tvtropes" / "TVTropesData.zip") as z:
            for name in ("TVTropesData/tv_imdb_match.csv", "TVTropesData/film_imdb_match.csv", "TVTropesData/tropes.csv"):
                z.extract(name, WORK / "tvtropes")
    con.execute(f"""
    create or replace table title_trope as
    select distinct tconst, Trope as trope
    from read_csv(['{d}/tv_imdb_match.csv', '{d}/film_imdb_match.csv'], header=true,
                  columns={{'idx':'varchar','Title':'varchar','Trope':'varchar','Example':'varchar',
                            'CleanTitle':'varchar','tconst':'varchar','trope_id':'varchar','title_id':'varchar'}},
                  max_line_size=10000000, parallel=false)
    where tconst in (select tconst from title)
    """)
    con.execute(f"""
    create or replace table trope as
    select Trope as trope, trim(Description) as description
    from read_csv('{d}/tropes.csv', header=true, max_line_size=10000000, parallel=false,
                  columns={{'idx':'varchar','TropeID':'varchar','Trope':'varchar','Description':'varchar'}})
    where Trope in (select trope from title_trope)
    """)


WIKIDATA_FACTS = ["country", "language", "broadcaster", "genre", "main_subject", "based_on",
                  "award", "nomination", "creator", "showrunner", "production_company"]


def wikidata(con):
    """Wikidata's links to other sites and its facts per title (fetch_wikidata.py)."""
    d = RAW / "wikidata"
    # TSV values are quoted literals ("x", "x"@en) or IRIs (<.../Q42>).
    clean = lambda c: f"nullif(regexp_replace(regexp_replace({c}, '^\"|\"(@\\w+)?$', '', 'g'), '^<.*/([^/>]+)>$', '\\1'), '')"
    con.execute(f"""
    create or replace table title_link as
    select {clean('"?imdb"')} as tconst,
           min({clean('"?item"')}) as wikidata,
           min(replace(regexp_extract("?enwiki", '^<(.*)>$', 1), 'https://en.wikipedia.org/wiki/', '')) filter (where "?enwiki" is not null) as enwiki,
           min({clean('"?tmdb_movie"')}) filter (where "?tmdb_movie" is not null) as tmdb_movie,
           min({clean('"?tmdb_tv"')}) filter (where "?tmdb_tv" is not null) as tmdb_tv,
           min({clean('"?rt"')}) filter (where "?rt" is not null) as rotten_tomatoes,
           min({clean('"?metacritic"')}) filter (where "?metacritic" is not null) as metacritic,
           min({clean('"?tvdb"')}) filter (where "?tvdb" is not null) as tvdb
    from read_csv('{d}/ids.tsv', delim='\t', header=true, quote='', all_varchar=true)
    group by 1 having tconst in (select tconst from title)
    """)
    parts = []
    for name in WIKIDATA_FACTS:
        nm = f"{clean('\"?nm\"')}" if name in ("creator", "showrunner") else "null"
        parts.append(f"""
        select {clean('"?imdb"')} as tconst, '{name}' as fact, {clean('"?label"')} as value,
               coalesce({nm}, {clean('"?v"')}) as value_id
        from read_csv('{d}/{name}.tsv', delim='\t', header=true, quote='', all_varchar=true)""")
    con.execute(f"""
    create or replace table title_fact as
    select distinct * from ({' union all '.join(parts)})
    where tconst in (select tconst from title)
    """)
