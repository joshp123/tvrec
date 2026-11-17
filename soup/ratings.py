"""Rating data sets, each with its items matched to IMDb IDs.

Each loader stages three tables and calls `add`:
  _item(item_id, title, year, kind, people)  the source's catalogue
  _match(item_id, tconst, method)            items matched to IMDb (match.run)
  _r(user, item_id, rating, ts)              its ratings (ts in Unix seconds)
"""

from . import match
from .db import RAW, WORK

SCHEMA = """
create table if not exists rater (user_key bigint, source varchar, source_user varchar);
create table if not exists source_item (
    item_key bigint, source varchar, item_id varchar, title varchar, year int,
    kind varchar, tconst varchar, match_method varchar, n_ratings bigint);
create table if not exists rating (user_key bigint, item_key bigint, tconst varchar, rating float, ts bigint);
"""


def add(con, source):
    """Replace the source's rows with the staged tables."""
    con.execute(SCHEMA)
    for t in ("rater", "source_item", "rating"):
        con.execute(f"delete from {t} where {'source' if t != 'rating' else 'user_key'} "
                    + (f"= '{source}'" if t != "rating" else
                       f"in (select user_key from rater where source = '{source}')"))
    item_base = con.execute("select coalesce(max(item_key), 0) from source_item").fetchall()[0][0]
    user_base = con.execute("select coalesce(max(user_key), 0) from rater").fetchall()[0][0]
    con.execute(f"""
    insert into source_item
    select {item_base} + row_number() over (order by i.item_id), '{source}', i.item_id, i.title, i.year,
           i.kind, m.tconst, m.method, coalesce(n.n, 0)
    from _item i left join _match m using (item_id)
    left join (select item_id, count(*) as n from _r group by 1) n using (item_id)
    """)
    con.execute(f"""
    insert into rater
    select {user_base} + row_number() over (order by u), '{source}', u
    from (select distinct user::varchar as u from _r)
    """)
    con.execute(f"""
    insert into rating
    select u.user_key, s.item_key, s.tconst, r.rating, r.ts
    from _r r
    join rater u on u.source = '{source}' and u.source_user = r.user::varchar
    join source_item s on s.source = '{source}' and s.item_id = r.item_id
    """)


def movielens(con):
    z = RAW / "movielens" / "ml-32m.zip"
    d = WORK / "ml-32m"
    if not (d / "ratings.csv").exists():
        import zipfile
        zipfile.ZipFile(z).extractall(WORK)
    con.execute(f"""
    create or replace table _item as
    select m.movieId::varchar as item_id,
           regexp_replace(m.title, '\\s*\\(\\d{{4}}\\)\\s*$', '') as title,
           try_cast(regexp_extract(m.title, '\\((\\d{{4}})\\)\\s*$', 1) as int) as year,
           'film' as kind, []::varchar[] as people,
           'tt' || lpad(l.imdbId::varchar, greatest(7, length(l.imdbId))::int, '0') as tconst
    from read_csv('{d}/movies.csv', header=true, all_varchar=true) m
    left join read_csv('{d}/links.csv', header=true, all_varchar=true) l using (movieId)
    """)
    con.execute(f"""
    create or replace table _r as
    select userId as user, movieId::varchar as item_id, rating::float as rating, timestamp::bigint as ts
    from read_csv('{d}/ratings.csv', header=true, columns={{'userId':'bigint','movieId':'bigint','rating':'float','timestamp':'bigint'}})
    """)
    con.execute("create or replace table _match as select item_id, tconst, 'imdb_id' as method from _item where tconst in (select tconst from title)")
    add(con, "movielens")
    con.execute(f"""
    create or replace table movielens_tag as
    select s.tconst, t.userId as user, t.tag, t.timestamp::bigint as ts
    from read_csv('{d}/tags.csv', header=true, all_varchar=true) t
    join source_item s on s.source = 'movielens' and s.item_id = t.movieId
    """)


def letterboxd(con):
    f = RAW / "letterboxd" / "train.parquet"
    # The data set gives only Letterboxd's URL slug, which is the title
    # lower-cased and hyphenated, with "-YYYY" added when the title is taken.
    con.execute(f"""
    create or replace table _item as
    with s as (select distinct movie_id::varchar as item_id, title as slug from '{f}')
    select item_id, replace(slug, '-', ' ') as title, null::int as year, 'film' as kind, []::varchar[] as people from s
    union all
    select item_id, regexp_replace(replace(slug, '-', ' '), ' \\d{{4}}$', ''),
           try_cast(regexp_extract(slug, '-(\\d{{4}})$', 1) as int), 'film', []::varchar[]
    from s where regexp_matches(slug, '-(19|20)\\d\\d$')
    """)
    # Two readings of a slug ending in a year: a disambiguating suffix (tried
    # first, year required) or part of the title ("blade-runner-2049").
    con.execute("create or replace table _lb_item as select * from _item")
    con.execute("create or replace table _item as select * from _lb_item qualify row_number() over (partition by item_id order by year nulls last) = 1")
    match.run(con)
    con.execute("create or replace table _lb_match as select * from _match")
    con.execute("create or replace table _item as select * from _lb_item where year is null and item_id not in (select item_id from _lb_match)")
    match.run(con)
    con.execute("create or replace table _match as select * from _lb_match union all select * from _match")
    con.execute("create or replace table _item as select * from _lb_item qualify row_number() over (partition by item_id order by year nulls last) = 1")
    con.execute(f"""
    create or replace table _r as
    select "user" as user, movie_id::varchar as item_id, rating, null::bigint as ts from '{f}'
    """)
    add(con, "letterboxd")


AMAZON_PEOPLE = ["Directors", "Director", "Starring", "Actors"]


def amazon(con):
    d = RAW / "amazon"
    people = " || ".join(
        f"""coalesce(case when json_type(json_extract(details, '$."{k}"')) = 'ARRAY'
                     then json_extract_string(details, '$."{k}"[*]')
                     else string_split(json_extract_string(details, '$."{k}"'), ', ') end, [])"""
        for k in AMAZON_PEOPLE)
    con.execute(f"""
    create or replace table _amz_meta as
    select parent_asin as item_id, main_category, title,
           list_filter(features, lambda x: regexp_matches(x, '^(19|20)\\d\\d$'))[1]::int as feat_year,
           try_cast(regexp_extract(json_extract_string(details, '$."Release date"'), '(\\d{{4}})', 1) as int) as release_year,
           list_filter(features, lambda x: x like '%episode%')[1] is not null as has_episodes,
           list_filter(features, lambda x: regexp_matches(x, '^\\d+ h|^\\d+ min'))[1] is not null as has_runtime,
           try_cast(list_filter(features, lambda x: x like 'IMDb %')[1][6:] as double) as amazon_imdb_rating,
           {people} as people,
           array_to_string(description, ' ') as description,
           average_rating, rating_number
    from read_json('{d}/meta_Movies_and_TV.jsonl.gz', format='newline_delimited', maximum_object_size=50000000, sample_size=-1,
                   columns={{'parent_asin':'varchar','main_category':'varchar','title':'varchar','features':'varchar[]',
                             'details':'json','description':'varchar[]','average_rating':'double','rating_number':'bigint'}})
    """)
    # Strip packaging and season wording from DVD titles; season wording
    # marks the item as a series.
    season = match.SEASON
    con.execute(f"""
    create or replace table _item as
    with t as (
        select *, regexp_replace(regexp_replace(coalesce(title, ''), '\\s*[\\[\\(][^\\]\\)]*[\\]\\)]', '', 'g'),
                                 '(?i)^masterpiece( classic| mystery| theatre)?\\s*!?:\\s*', '') as t0
        from _amz_meta)
    select item_id,
           nullif(trim(regexp_replace(t0, '{season}', '')), '') as title,
           coalesce(feat_year, release_year) as year,
           case when has_episodes or regexp_matches(t0, '{season}') then 'series'
                when has_runtime then 'film' end as kind,
           list_distinct(list_filter(people, lambda x: length(x) > 2)) as people
    from t
    """)
    con.execute(f"""
    create or replace table _r as
    select user_id as user, parent_asin as item_id, rating::float as rating, (timestamp::bigint // 1000) as ts
    from read_csv('{d}/Movies_and_TV.ratings.csv.gz', header=true,
                  columns={{'user_id':'varchar','parent_asin':'varchar','rating':'float','timestamp':'bigint'}})
    """)
    match.run(con, year_fallback=True)
    add(con, "amazon")


def netflix(con):
    d = WORK / "netflix"
    if not (d / "training_set").exists():
        import tarfile
        d.mkdir(parents=True, exist_ok=True)
        with tarfile.open(RAW / "netflix" / "nf_prize_dataset.tar.gz") as t:
            t.extract("download/movie_titles.txt", d)
            t.extract("download/training_set.tar", d)
        with tarfile.open(d / "download" / "training_set.tar") as t:
            t.extractall(d)
        (d / "download" / "training_set.tar").unlink()
    # movie_titles.txt: id,year,title in Latin-1, titles may contain commas.
    rows = []
    with open(d / "download" / "movie_titles.txt", encoding="latin-1") as f:
        for line in f:
            i, y, t = line.rstrip("\n").split(",", 2)
            rows.append((i, int(y) if y.isdigit() else None, t))
    con.execute("create or replace table _nf_titles (item_id varchar, year int, title varchar)")
    con.executemany("insert into _nf_titles values (?, ?, ?)", rows)
    con.execute(f"""
    create or replace table _item as
    select item_id, nullif(trim(regexp_replace(title, '{match.SEASON}', '')), '') as title, year,
           case when regexp_matches(title, '{match.SEASON}') then 'series' end as kind,
           []::varchar[] as people
    from _nf_titles
    """)
    match.run(con, year_fallback=True)
    con.execute(f"""
    create or replace table _r as
    select customer as user, regexp_extract(filename, 'mv_0*(\\d+)\\.txt', 1) as item_id,
           rating::float as rating, epoch(date)::bigint as ts
    from read_csv('{d}/training_set/mv_*.txt', skip=1, header=false, filename=true,
                  columns={{'customer':'bigint','rating':'tinyint','date':'date'}})
    """)
    add(con, "netflix")


def movietweetings(con):
    d = RAW / "movietweetings"
    con.execute(f"""
    create or replace table _item as
    select column0 as item_id,
           regexp_replace(column1, '\\s*\\(\\d{{4}}\\)\\s*$', '') as title,
           try_cast(regexp_extract(column1, '\\((\\d{{4}})\\)\\s*$', 1) as int) as year,
           null::varchar as kind, []::varchar[] as people,
           'tt' || lpad(column0, greatest(7, length(column0))::int, '0') as tconst
    from read_csv('{d}/movies.dat', delim='::', header=false, all_varchar=true, quote='')
    """)
    con.execute("create or replace table _match as select item_id, tconst, 'imdb_id' as method from _item where tconst in (select tconst from title)")
    con.execute(f"""
    create or replace table _r as
    select column0 as user, column1 as item_id, column2::float as rating, column3::bigint as ts
    from read_csv('{d}/ratings.dat', delim='::', header=false, all_varchar=true, quote='')
    """)
    add(con, "movietweetings")


def trakt(con):
    """Trakt users' public ratings (1-10) and what they watched, IMDb IDs given.

    Each user's lists hold at most their latest 100 entries. Season and
    episode ratings count towards the show when the user did not rate the
    show itself."""
    f = RAW / "trakt" / "*.parquet"
    con.execute(f"""
    create or replace table _tr as
    select username, unnest(ratings_json) as r from '{f}'
    """)
    con.execute("""
    create or replace table _tr as
    select username as user,
           coalesce(r.movie.ids.imdb, r.show.ids.imdb) as tconst,
           coalesce(r.movie.title, r.show.title) as title,
           coalesce(r.movie.year, r.show.year) as year,
           r.type, r.rating, epoch(r.rated_at::timestamp)::bigint as ts
    from _tr where coalesce(r.movie.ids.imdb, r.show.ids.imdb) like 'tt%'
    """)
    con.execute("""
    create or replace table _r as
    with direct as (select user, tconst, rating::float as rating, ts from _tr where type in ('movie', 'show')),
    parts as (select user, tconst, avg(rating)::float as rating, max(ts) as ts from _tr
              where type in ('season', 'episode') group by all)
    select user, tconst as item_id, rating, ts from direct
    union all
    select p.user, p.tconst, p.rating, p.ts from parts p
    where not exists (select 1 from direct d where d.user = p.user and d.tconst = p.tconst)
    """)
    con.execute("""
    create or replace table _item as
    select tconst as item_id, any_value(title) as title, any_value(year) as year,
           null::varchar as kind, []::varchar[] as people, tconst
    from _tr group by tconst
    """)
    con.execute("create or replace table _match as select item_id, tconst, 'imdb_id' as method from _item where tconst in (select tconst from title)")
    add(con, "trakt")
    con.execute(f"""
    insert into rater
    select (select max(user_key) from rater) + row_number() over (order by username), 'trakt', username
    from (select distinct username from '{f}')
    where username not in (select source_user from rater where source = 'trakt')
    """)
    con.execute(f"""
    create or replace table watch as
    with w as (
        select username as user, unnest(watched_shows_json) as w, 'show' as type from '{f}'
        union all
        select username, unnest(watched_movies_json), 'movie' from '{f}')
    select u.user_key, coalesce(w.show.ids.imdb, w.movie.ids.imdb) as tconst, w.plays,
           epoch(w.last_watched_at::timestamp)::bigint as last_ts
    from w join rater u on u.source = 'trakt' and u.source_user = w.user
    where coalesce(w.show.ids.imdb, w.movie.ids.imdb) in (select tconst from title)
    """)
