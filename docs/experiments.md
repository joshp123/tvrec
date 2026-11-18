# Ranking experiments on other people's ratings

Which level of model dependence the ranker needs, tested on strangers in the
rating data sets. Scripts are in `experiments/`; they read a snapshot of the
soup copied to `data/work/exp/` by `extract.py` and `extract_text.py`.

Levels:

1. No AI model: other people's likes, who made what, public scores, plain
   word search over plot text.
2. Level 1 plus a frozen open embedding model over the same plot text
   (Qwen3-Embedding-0.6B, run locally).
3. Level 2 plus a frontier model (Claude Opus 5.5 through the local `claude`
   command) reordering the top of the list.

## Set-up (`split.py`)

- A like is a rating in the top quarter of the source's scale and at or above
  that person's own average. 77 million likes from 5.8 million people over
  119,620 titles with three or more likers.
- 7,700 test people held out: up to 1,500 per data set with 30 or more likes
  (Netflix 1,500, MovieLens 1,500, Letterboxd 800, Trakt 800, Amazon 800,
  MovieTweetings 300) plus 2,000 with ten or more liked series. Their ratings
  are not used to learn anything.
- "Little-rated" means fewer than 500 likers across all data sets.
  "Long-tail people" have a quarter or more of their likes on little-rated
  titles: 1,687 of the 7,669 used.
- 800 series and 800 films that test people liked were made "new": every
  rating of them, by anyone, was removed before learning.
- Level 1's model: for every pair of titles, the number of people who liked
  both, divided by the square root of each title's number of likers, shrunk
  when few people support it; 400 neighbours kept per title.

The measure: reveal k of a test person's likes, rank every other title, and
count the share of their hidden likes in the top 50 (recall@50). Series are
ranked among series, films among films, and little-rated titles among
little-rated titles, as the niche lane would rank them.

## 1. Rated titles: other people's likes against popularity (`eval_warm.py`)

Recall@50; "sum" adds a candidate's links to every revealed like, "max" takes
the strongest single link, "max+" adds a tenth of the rest to the strongest.

All 7,669 people:

| segment | k | popularity | sum | max | max+ | people |
|---|---|---|---|---|---|---|
| films | 10 | 0.247 | 0.349 | 0.302 | 0.332 | 7,519 |
| films | 50 | 0.306 | 0.426 | 0.381 | 0.423 | 4,718 |
| films, little-rated | 10 | 0.012 | 0.103 | 0.095 | 0.098 | 5,290 |
| series | 5 | 0.237 | 0.338 | 0.335 | 0.336 | 5,386 |
| series | 10 | 0.233 | 0.378 | 0.371 | 0.373 | 5,219 |
| series | 20 | 0.236 | 0.442 | 0.430 | 0.433 | 4,839 |
| series | 50 | 0.267 | 0.580 | 0.570 | 0.573 | 3,210 |
| series, little-rated | 10 | 0.029 | 0.193 | 0.184 | 0.186 | 2,834 |

The 1,687 long-tail people:

| segment | k | popularity | sum | max | max+ | people |
|---|---|---|---|---|---|---|
| films | 5 | 0.056 | 0.147 | 0.128 | 0.132 | 1,649 |
| films | 10 | 0.057 | 0.161 | 0.136 | 0.144 | 1,601 |
| films | 20 | 0.061 | 0.174 | 0.145 | 0.159 | 1,471 |
| films | 50 | 0.122 | 0.299 | 0.249 | 0.285 | 582 |
| films, little-rated | 10 | 0.010 | 0.113 | 0.097 | 0.102 | 1,541 |
| series | 5 | 0.065 | 0.171 | 0.166 | 0.166 | 1,568 |
| series | 10 | 0.062 | 0.205 | 0.193 | 0.195 | 1,501 |
| series | 20 | 0.060 | 0.248 | 0.220 | 0.225 | 1,328 |
| series | 50 | 0.047 | 0.360 | 0.343 | 0.348 | 498 |
| series, little-rated | 5 | 0.021 | 0.144 | 0.140 | 0.141 | 1,470 |
| series, little-rated | 10 | 0.017 | 0.189 | 0.177 | 0.179 | 1,387 |
| series, little-rated | 20 | 0.017 | 0.263 | 0.233 | 0.239 | 1,182 |

- Level 1 beats popularity everywhere, by most for long-tail people and
  little-rated titles: for little-rated series, 0.189 against 0.017 at k=10.
- More revealed likes help steadily: series recall rises from 0.338 at 5
  to 0.580 at 50.
- Summing beats the strongest link in every cell, by 1 to 5 points. The sum's
  earlier failure (one heavily credited show drowning the rest) was in the
  maker graph, not here.
- By data set (k=10, series): Netflix 0.507, Letterboxd 0.399, MovieLens
  0.404, Amazon 0.185, Trakt 0.171, against popularity 0.392, 0.011, 0.154,
  0.151, 0.077.

## 2. Film likes predict series likes (`eval_warm.py`)

2,882 people with 20 or more liked films and 6 or more liked series (725 of
them long-tail). Five of their liked series are held as seeds in one arm;
the measure is recall@50 over their other liked series.

| seeds | series, all people | series, little-rated, all | series, long-tail | series, little-rated, long-tail |
|---|---|---|---|---|
| popularity | 0.242 | 0.027 | 0.058 | 0.012 |
| 10 films | 0.320 | 0.103 | 0.133 | 0.092 |
| 20 films | 0.351 | 0.147 | 0.151 | 0.130 |
| 5 series | 0.504 | 0.310 | 0.253 | 0.258 |
| 20 films + 5 series | 0.516 | 0.327 | 0.242 | 0.267 |

Film likes carry real signal for series (20 films reach about 60% of what 5
series do, well above popularity), but a few stated series favourites matter
more than many films.

## 3. Does anything help on rated titles? (`eval_warm_content.py`)

2,000 of the test people (1,916 usable, 403 long-tail), recall@50, k=10.
Fusion is reciprocal-rank fusion; "1/.5/.25" weights the parts.

| method | films | films, little | series | series, little | long-tail series | long-tail series, little |
|---|---|---|---|---|---|---|
| likes only (sum) | 0.350 | 0.097 | 0.383 | 0.199 | 0.199 | 0.198 |
| likes, popularity-corrected | 0.182 | 0.076 | 0.350 | 0.175 | 0.166 | 0.175 |
| likes + makers | 0.278 | 0.028 | 0.113 | 0.095 | 0.102 | 0.116 |
| likes + makers + words, 1/.5/.25 | 0.349 | 0.044 | 0.184 | 0.099 | 0.122 | 0.128 |
| likes + makers + embedding, 1/.5/.25 | 0.350 | 0.040 | 0.174 | 0.095 | 0.118 | 0.123 |
| likes + makers + words + embedding | 0.191 | 0.037 | 0.094 | 0.078 | 0.085 | 0.101 |

Where a title has ratings, other people's likes alone are best; every mix
with makers, plot words or embeddings is worse. "Popularity-corrected"
(co-likes divided by the candidate's own likers rather than its square root)
costs 3 points on series and half the film recall: the hits it loses are the
popular titles a person has most likely already seen, which this measure
counts as hits.

## 4. Titles nobody has rated (`eval_new.py`)

1,600 held-out titles; for each person, 20 revealed likes among rated
titles; recall@20 among the 800 new titles of each kind. 4,039 people liked
a new series, 6,277 a new film.

| signal | level | series | films |
|---|---|---|---|
| random | | 0.025 | 0.025 |
| makers (creator-weighted) | 1 | 0.108 | 0.147 |
| plot words, closest revealed like | 1 | 0.161 | 0.303 |
| plot words via rated neighbours | 1 | 0.131 | 0.382 |
| makers + words (fused) | 1 | 0.191 | 0.411 |
| embedding, closest revealed like | 2 | 0.117 | 0.131 |
| embedding via rated neighbours | 2 | 0.082 | 0.228 |
| makers + embedding | 2 | 0.143 | 0.211 |
| level 1 + embedding | 2 | 0.175 | 0.381 |
| IMDb votes (uses future votes; not available on release day) | | 0.141 | 0.395 |

"Via rated neighbours" scores a new title by the likes of the 20 rated
titles whose text is closest to it. The embedding model (Qwen3-Embedding-
0.6B over the same text, 1,599 of the 1,600 embedded) is worse than plain
word overlap on every line and lowers the level-1 fusion. Word overlap wins
partly because Wikipedia leads name creators, cast, broadcaster and country,
which TF-IDF matches exactly and the embedding blurs.

The held-out titles were chosen among titles that two or more test people
liked, so they lean popular; IMDb votes look strong for that reason.

## 5. Level 3: a frontier model reorders the top 30 (`eval_judge.py`)

Claude Opus 5.5 through the local `claude` command, no tools, minimal
system prompt, given the person's 20 revealed likes (title and year) and,
for each candidate, title, year and plot text. Only people with at least
one hidden like in the 30 are used. Hidden likes in the top 10, before and
after:

| case | people | hidden likes in the 30 | lower level | frontier model | better / worse | sign test p |
|---|---|---|---|---|---|---|
| rated series, long-tail people (pool: level 1 likes) | 40 | 99 | 48 | 58 | 17 / 7 | 0.064 |
| new series (pool: level 1 makers + words) | 20 | 28 | 13 | 24 | 11 / 1 | 0.006 |
| new films (pool: level 1 makers + words) | 20 | 80 | 37 | 54 | 11 / 1 | 0.006 |

The model knows these titles: they are "new" only in the data, and all
predate its training. It also knows their audiences. For a truly new release
it knows nothing but the plot text it is handed, so these gains are an upper
bound for the "new and good" case, and this data cannot say how much of them
survives.

## What this says

- Level 1 is a real ranker for rated titles and the long tail, and level 2
  (embeddings) added nothing in any test.
- For titles with no ratings, level 1 reaches about 7 times random for series
  and 16 times for films; makers alone are weaker than plot words on
  average.
- Level 3 improves the order of a short list in every case tried, strongly
  for unrated titles, with the caveat above.
