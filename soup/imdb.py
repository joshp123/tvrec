"""IMDb's daily dumps: titles, people, credits and the title lookup the matchers use."""

from .db import RAW, TSV

KINDS = "('movie','tvMovie','tvSeries','tvMiniSeries','tvSpecial','video','short','tvShort')"

# Writer credits IMDb marks as creating the show, as against adapting a source.
CREATOR_JOB = r"^(series )?(creator|created by|created for television by|series creator|original creator|developed by|developed for television by)$"


def build(con):
    d = RAW / "imdb"
    con.execute(f"""
    create or replace table title as
    with b as (select * from read_csv('{d}/title.basics.tsv.gz', {TSV}) where titleType in {KINDS}),
    r as (select * from read_csv('{d}/title.ratings.tsv.gz', {TSV})),
    ep as (select * from read_csv('{d}/title.episode.tsv.gz', {TSV})),
    series_stats as (
        select parentTconst as tconst,
               count(*) as n_episodes,
               count(distinct seasonNumber) as n_seasons,
               sum(r.numVotes::int) as episode_votes
        from ep left join r using (tconst) group by 1)
    select b.tconst,
           b.titleType as kind,
           b.titleType in ('tvSeries', 'tvMiniSeries') as is_series,
           b.primaryTitle as primary_title,
           b.originalTitle as original_title,
           b.startYear::int as start_year,
           b.endYear::int as end_year,
           b.runtimeMinutes::int as runtime_min,
           b.genres,
           b.isAdult = '1' as is_adult,
           r.averageRating::double as imdb_rating,
           coalesce(r.numVotes::int, 0) as imdb_votes,
           s.n_seasons, s.n_episodes, s.episode_votes
    from b left join r using (tconst) left join series_stats s using (tconst)
    """)

    con.execute(f"""
    create or replace table _episode as
    select tconst as episode, parentTconst as series
    from read_csv('{d}/title.episode.tsv.gz', {TSV})
    where parentTconst in (select tconst from title where is_series)
    """)

    # Every credit on a title or one of its episodes, one row per source line.
    con.execute(f"""
    create or replace table _raw_credit as
    with p as (
        select tconst, nconst, ordering::int as ordering, category, job
        from read_csv('{d}/title.principals.tsv.gz', {TSV})),
    c as (select * from read_csv('{d}/title.crew.tsv.gz', {TSV})),
    crew as (
        select tconst, unnest(string_split(directors, ',')) as nconst, 'director' as category from c where directors is not null
        union all
        select tconst, unnest(string_split(writers, ',')) as nconst, 'writer' as category from c where writers is not null),
    lines as (
        select tconst, nconst, ordering, category, job from p
        union all
        select tconst, nconst, null, category, null from crew)
    select coalesce(e.series, l.tconst) as tconst,
           e.episode,
           l.nconst,
           case when l.category in ('actor', 'actress') then 'actor'
                when l.category = 'writer' and regexp_matches(lower(coalesce(l.job, '')), '{CREATOR_JOB}') then 'creator'
                else l.category end as role,
           l.job,
           case when e.episode is null then l.ordering end as billing
    from lines l left join _episode e on e.episode = l.tconst
    where e.series is not null or l.tconst in (select tconst from title)
    """)

    con.execute("""
    create or replace table credit as
    select tconst, nconst, role,
           min(billing) as billing,
           count(distinct episode) filter (where episode is not null) as episodes,
           any_value(job) filter (where job is not null) as job
    from _raw_credit group by all
    """)
    con.execute("update credit set episodes = null where tconst in (select tconst from title where not is_series)")
    con.execute("drop table _raw_credit")

    con.execute(f"""
    create or replace table person as
    select nconst, primaryName as name, birthYear::int as birth_year, deathYear::int as death_year,
           primaryProfession as professions
    from read_csv('{d}/name.basics.tsv.gz', {TSV})
    where nconst in (select distinct nconst from credit)
    """)

    # Lookup of normalised titles for the matchers: primary, original, and
    # English-language or English-speaking-region alternative titles.
    con.execute(f"""
    create or replace table _title_key as
    select distinct tconst, key, min(rank) over (partition by tconst, key) as rank from (
        select tconst, norm(primary_title) as key, 0 as rank from title
        union all select tconst, norm(original_title), 0 from title
        union all
        select titleId, norm(title), 1
        from read_csv('{d}/title.akas.tsv.gz', {TSV})
        where (region in ('GB','US','CA','AU','IE','NZ','XWW') or language = 'en')
          and titleId in (select tconst from title))
    where key is not null
    """)
    con.execute("create or replace table _title_key as select tconst, key, min(rank) as rank from _title_key group by all")
    con.execute("""
    create or replace table _person_key as
    select nconst, norm_name(name) as key from person where norm_name(name) is not null
    """)
