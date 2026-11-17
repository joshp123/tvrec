<!-- Written by AI on 2026.11.17 by model claude opus 5.5. -->

# Data sources

Every source below is free to download with no account, sign-up, API key or
payment, except Plex's metadata service, which takes the household's own Plex
token. None of the data is committed; `fetch.sh` and the `soup/fetch_*.py`
scripts download it into `data/raw/`. Most licences allow personal,
non-commercial use only.

| Source | Where | Retrieved | Licence | In the soup |
|---|---|---|---|---|
| IMDb non-commercial datasets (7 files) | https://datasets.imdbws.com/ (`title.basics`, `title.akas`, `title.crew`, `title.episode`, `title.principals`, `title.ratings`, `name.basics`) | 2026-11-17 | IMDb [non-commercial licence](https://developer.imdb.com/non-commercial-datasets/): personal and non-commercial use | `title`, `person`, `credit`, IMDb rows of `public_score` |
| MovieLens 32M | https://files.grouplens.org/datasets/movielens/ml-32m.zip | 2026-11-17 | GroupLens usage licence: research, non-commercial, cite Harper and Konstan 2015 | `rating` (source `movielens`), `movielens_tag` |
| Letterboxd Movie Ratings 10M (Dec 2025, Titouan Mokrani) | https://huggingface.co/datasets/titouann/letterboxd-10m-movies-ratings-2025/resolve/main/train.parquet | 2026-11-17 | CC BY-NC-SA 4.0 | `rating` (source `letterboxd`) |
| Amazon Reviews 2023 (McAuley Lab, UCSD), Movies_and_TV ratings and item metadata | https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/benchmark/0core/rating_only/Movies_and_TV.csv.gz and https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/meta_categories/meta_Movies_and_TV.jsonl.gz | 2026-11-17 | None stated; academic research data set | `rating` (source `amazon`), Amazon rows of `plot` |
| Amazon Reviews 2023, Movies_and_TV review text | https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/review_categories/Movies_and_TV.jsonl.gz | 2026-11-17 | None stated | Downloaded, not loaded (see below) |
| Netflix Prize | https://archive.org/download/nf_prize_dataset.tar/nf_prize_dataset.tar.gz | 2026-11-17 | Netflix's README grants no reuse terms; distributed for the 2006 to 2009 competition | `rating` (source `netflix`) |
| MovieTweetings | https://github.com/sidooms/MovieTweetings (`latest/`) | 2026-11-17 | MIT | `rating` (source `movietweetings`) |
| Trakt users 12k (Hugging Face `jahb57/trakt_users_12k`) | https://huggingface.co/datasets/jahb57/trakt_users_12k | 2026-11-17 | None stated; scraped from public Trakt profiles, Trakt's terms may apply | `rating` (source `trakt`), `watch` |
| MovieLens Tag Genome 2021 | https://files.grouplens.org/datasets/tag-genome-2021/genome_2021.zip | 2026-11-17 | CC BY-NC 3.0 | `tag_genome` |
| TV Tropes data set (Gala et al. 2020, `dhruvilgala/tvtropes`) | Google Drive file `1Duyz5ATlLHzwMidj15bWVnWHpdE4aRXn` (link in `fetch.sh`) | 2026-11-17 | None stated; scraped from tvtropes.org (CC BY-NC-SA) | `title_trope`, `trope` |
| Wikidata, through QLever | https://qlever.dev/api/wikidata (`soup/fetch_wikidata.py`) | 2026-11-17 | CC0 | `title_link`, `title_fact` |
| English Wikipedia lead sections | https://en.wikipedia.org/w/api.php (`soup/fetch_wikipedia.py`) | 2026-11-17 | CC BY-SA 4.0 | Wikipedia rows of `plot` |
| Plex metadata service | https://metadata.provider.plex.tv (`soup/fetch_plex.py`, household token) | 2026-11-17 | Plex terms of service; text and scores originate from TMDB, TVDB, IMDb and Rotten Tomatoes | `plex_title`, `title_similar`, Plex rows of `plot` and `public_score` |

## Downloaded but not loaded

- Amazon review text (2.4 GB compressed): free-text reviews for the same
  items as the Amazon ratings. Left out to keep the soup small; a text
  experiment can read it from `data/raw/amazon/` and join on `source_item`.
- Tag Genome 2021 also holds 2.6 million IMDb user reviews of films
  (`raw/reviews.json`, 3.9 GB); films only, left in the zip.

## Considered and not used

- TMDB through Seerr (a self-hosted app that proxies TMDB): works, but needs TMDB IDs, which only
  60,058 titles have through Wikidata. Plex's metadata service takes IMDb IDs
  directly and returns the same TMDB plot text, so it was used instead.
- Kaggle sets (IMDb reviews, Rotten Tomatoes reviews), IEEE DataPort "IMDb
  Users' Ratings Dataset" (4.7 million ratings keyed by IMDb ID): need an
  account.
- Trakt API, Letterboxd API: need an account or an API key; Letterboxd refuses
  personal projects.
- Reddit recommendation threads (Arctic Shift API): free text with no IDs,
  and Reddit's terms bar AI use.
- CMU Movie Summary Corpus, MPST: films only, already covered by Plex and
  Wikipedia text.
