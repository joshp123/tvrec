"""Plot text, public scores and similar-title links fetched per title."""

import zipfile

from .db import RAW, WORK

PLEX = RAW / "plex_metadata" / "metadata.jsonl"
WIKIPEDIA = RAW / "wikipedia" / "intros.jsonl"


def plex(con):
    """Plex's public metadata (fetch_plex.py): summary, scores, similar titles."""
    if not PLEX.exists():
        return
    con.execute(f"""
    create or replace table _plex as
    select tconst, metadata as m
    from read_json('{PLEX}', format='newline_delimited', ignore_errors=true, columns={{'tconst':'varchar','metadata':'json'}})
    where metadata is not null and tconst in (select tconst from title)
    qualify row_number() over (partition by tconst) = 1
    """)
    con.execute("""
    create or replace table plex_title as
    select tconst,
           m->>'$.guid' as plex_guid,
           m->>'$.studio' as studio,
           m->>'$.contentRating' as content_rating,
           m->>'$.originallyAvailableAt' as first_aired,
           m->>'$.tagline' as tagline,
           array_to_string(json_extract_string(m, '$.Country[*].tag'), ', ') as countries,
           array_to_string(json_extract_string(m, '$.Genre[*].tag'), ', ') as genres
    from _plex
    """)
    con.execute("""
    create or replace table _plex_plot as
    select tconst, 'plex' as source, m->>'$.summary' as text from _plex where nullif(trim(m->>'$.summary'), '') is not null
    """)
    # Scores Plex shows: IMDb, TMDB, and Rotten Tomatoes critics' and audience
    # scores, all on a 0-10 scale.
    con.execute("""
    create or replace table _plex_score as
    with r as (select tconst, unnest(json_extract(m, '$.Rating[*]')) as r, (m->>'$.imdbRatingCount')::bigint as imdb_n from _plex)
    select tconst,
           case when r->>'$.image' like 'rottentomatoes://%' and r->>'$.type' = 'critic' then 'rotten_tomatoes_critics'
                when r->>'$.image' like 'rottentomatoes://%' then 'rotten_tomatoes_audience'
                when r->>'$.image' like 'imdb://%' then 'imdb'
                when r->>'$.image' like 'themoviedb://%' then 'tmdb'
                else r->>'$.image' end as scorer,
           (r->>'$.value')::double as score,
           case when r->>'$.image' like 'imdb://%' then imdb_n end as votes
    from r
    """)
    con.execute("""
    create or replace table title_similar as
    with s as (
        select tconst, unnest(json_extract_string(m, '$.Similar[*].guid')) as guid,
               generate_subscripts(json_extract_string(m, '$.Similar[*].guid'), 1) as rank
        from _plex)
    select s.tconst, p.tconst as similar, 'plex' as source, s.rank
    from s join plex_title p on p.plex_guid = s.guid
    """)


def wikipedia(con):
    """Lead sections of English Wikipedia articles (fetch_wikipedia.py)."""
    if not WIKIPEDIA.exists():
        return
    con.execute(f"""
    create or replace table _wiki_plot as
    select l.tconst, 'wikipedia' as source, any_value(w.text) as text
    from read_json('{WIKIPEDIA}', format='newline_delimited', ignore_errors=true, columns={{'enwiki':'varchar','text':'varchar'}}) w
    join title_link l on url_decode(l.enwiki) = w.enwiki
    where nullif(trim(w.text), '') is not null
    group by l.tconst
    """)


def amazon(con):
    """Amazon's product descriptions; for each title, the longest among its matched items."""
    con.execute("""
    create or replace table _amz_plot as
    select s.tconst, 'amazon' as source, arg_max(m.description, length(m.description)) as text
    from source_item s join _amz_meta m on m.item_id = s.item_id
    where s.source = 'amazon' and s.tconst is not null and length(m.description) >= 40
    group by s.tconst
    """)


def assemble(con):
    """One `plot` table and one `public_score` table from whichever sources loaded."""
    parts = [t for t in ("_plex_plot", "_wiki_plot", "_amz_plot") if _exists(con, t)]
    con.execute("create or replace table plot as " + " union all ".join(
        f"select tconst, source, text from {t}" for t in parts))
    scores = ["select tconst, 'imdb' as scorer, imdb_rating as score, imdb_votes::bigint as votes from title where imdb_rating is not null"]
    if _exists(con, "_plex_score"):
        scores.append("select tconst, scorer, score, votes from _plex_score where scorer <> 'imdb'")
    scores.append("""select tconst, source || '_average' as scorer, avg(rating) as score, count(*) as votes
                     from rating join rater using (user_key) where tconst is not null group by all""")
    con.execute("create or replace table public_score as " + " union all ".join(scores))


def genome(con):
    """MovieLens Tag Genome 2021: relevance (0-1) of 1,084 tags to 9,734 films."""
    z = RAW / "genome" / "genome_2021.zip"
    if not z.exists():
        return
    d = WORK / "genome"
    base = "movie_dataset_public_final"
    if not (d / base / "scores" / "tagdl.csv").exists():
        with zipfile.ZipFile(z) as f:
            for n in (f"{base}/scores/tagdl.csv", f"{base}/raw/metadata.json"):
                f.extract(n, d)
    con.execute(f"""
    create or replace table tag_genome as
    with meta as (
        select item_id, 'tt' || lpad(imdbId::varchar, greatest(7, length(imdbId::varchar))::int, '0') as tconst
        from read_json('{d}/{base}/raw/metadata.json', format='newline_delimited'))
    select m.tconst, s.tag, s.score::float as relevance
    from read_csv('{d}/{base}/scores/tagdl.csv', header=true) s join meta m using (item_id)
    where m.tconst in (select tconst from title)
    """)


def _exists(con, name):
    return con.execute("select count(*) from information_schema.tables where table_name = ?", [name]).fetchall()[0][0] > 0
