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

    con.execute("""
    create or replace macro id_num(s) as try_cast(s[3:] as bigint);
    create or replace macro id_text(p, n) as p || case when n < 10000000 then lpad(n::varchar, 7, '0') else n::varchar end;
    drop type if exists credit_role;
    create type credit_role as enum ('actor', 'self', 'writer', 'creator', 'director', 'producer', 'editor',
        'cinematographer', 'composer', 'archive_footage', 'production_designer', 'casting_director', 'archive_sound');
    """)
    # Job texts as integers, so the aggregations below hold only fixed-size
    # values and DuckDB can spill them to disk.
    con.execute(f"""
    create or replace table _job as
    select row_number() over (order by job) as job_id, job
    from (select distinct job from read_csv('{d}/title.principals.tsv.gz', {TSV}) where job is not null)
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
    select id_num(coalesce(e.series, l.tconst)) as t,
           id_num(e.episode) as ep,
           id_num(l.nconst) as n,
           (case when l.category in ('actor', 'actress') then 'actor'
                 when l.category = 'writer' and regexp_matches(lower(coalesce(l.job, '')), '{CREATOR_JOB}') then 'creator'
                 else l.category end)::credit_role as role,
           j.job_id,
           case when e.episode is null then l.ordering end as billing
    from lines l left join _episode e on e.episode = l.tconst
    left join _job j on j.job = l.job
    where e.series is not null or l.tconst in (select tconst from title)
    """)

    # Aggregated in two materialised steps over integer IDs: text IDs and
    # count(distinct) make hash tables DuckDB cannot keep within its limit.
    con.execute("""
    create or replace table _per_episode as
    select t, n, role, ep, min(billing) as billing, min(job_id) as job_id
    from _raw_credit group by all
    """)
    con.execute("drop table _raw_credit")
    con.execute("""
    create or replace table _per_title as
    select t, n, role, min(billing) as billing, count(ep) as episodes, min(job_id) as job_id
    from _per_episode group by all
    """)
    con.execute("drop table _per_episode")
    con.execute("""
    create or replace table credit as
    select id_text('tt', c.t) as tconst, id_text('nm', c.n) as nconst, c.role::varchar as role,
           c.billing, c.episodes, j.job
    from _per_title c left join _job j using (job_id)
    """)
    con.execute("drop table _per_title")
    con.execute("update credit set episodes = null where tconst in (select tconst from title where not is_series)")
    con.execute("drop table _job")

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
    select tconst, key, min(rank) as rank from (
        select tconst, norm(primary_title) as key, 0 as rank from title
        union all select tconst, norm(original_title), 0 from title
        union all
        select titleId, norm(title), 1
        from read_csv('{d}/title.akas.tsv.gz', {TSV})
        where (region in ('GB','US','CA','AU','IE','NZ','XWW') or language = 'en')
          and titleId in (select tconst from title))
    where key is not null
    group by all
    """)
    con.execute("""
    create or replace table _person_key as
    select nconst, norm_name(name) as key from person where norm_name(name) is not null
    """)
