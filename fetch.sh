#!/usr/bin/env bash
# Download the static public data sets into data/raw/. Files already present
# are skipped. Sources and licences: docs/data-sources.md. The API sources are
# fetched by soup/fetch_*.py after a first build.
set -euo pipefail
cd "$(dirname "$0")/data/raw"

get() { # dir file url
  mkdir -p "$1"
  if [ ! -s "$1/$2" ]; then
    /usr/bin/curl -fL --retry 3 -o "$1/$2.part" "$3"
    mv "$1/$2.part" "$1/$2"
  fi
}

for f in title.basics title.akas title.crew title.episode title.principals title.ratings name.basics; do
  get imdb "$f.tsv.gz" "https://datasets.imdbws.com/$f.tsv.gz"
done
get movielens ml-32m.zip https://files.grouplens.org/datasets/movielens/ml-32m.zip
get genome genome_2021.zip https://files.grouplens.org/datasets/tag-genome-2021/genome_2021.zip
get letterboxd train.parquet https://huggingface.co/datasets/titouann/letterboxd-10m-movies-ratings-2025/resolve/main/train.parquet
get amazon Movies_and_TV.ratings.csv.gz https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/benchmark/0core/rating_only/Movies_and_TV.csv.gz
get amazon meta_Movies_and_TV.jsonl.gz https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/meta_categories/meta_Movies_and_TV.jsonl.gz
get amazon Movies_and_TV.reviews.jsonl.gz https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/review_categories/Movies_and_TV.jsonl.gz
get netflix nf_prize_dataset.tar.gz https://archive.org/download/nf_prize_dataset.tar/nf_prize_dataset.tar.gz
get movietweetings ratings.dat https://raw.githubusercontent.com/sidooms/MovieTweetings/master/latest/ratings.dat
get movietweetings movies.dat https://raw.githubusercontent.com/sidooms/MovieTweetings/master/latest/movies.dat
get trakt train-00000-of-00002.parquet https://huggingface.co/datasets/jahb57/trakt_users_12k/resolve/main/data/train-00000-of-00002.parquet
get trakt train-00001-of-00002.parquet https://huggingface.co/datasets/jahb57/trakt_users_12k/resolve/main/data/train-00001-of-00002.parquet
get tvtropes TVTropesData.zip 'https://drive.usercontent.google.com/download?id=1Duyz5ATlLHzwMidj15bWVnWHpdE4aRXn&export=download&confirm=t'
