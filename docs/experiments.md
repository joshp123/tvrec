# Ranking experiments on other people's ratings

Which level of model dependence the ranker needs, tested on strangers in the
rating data sets. Scripts are in `experiments/`; they read a snapshot of the
soup copied to `data/work/exp/` by `extract.py` and `extract_text.py`.
Every number below is from the soup built at 05:13 on 18 Nov 2026.

Levels:

1. No AI model: other people's likes, who made what, public scores, plain
   word search over plot text.
2. Level 1 plus a frozen open embedding model over the same plot text
   (Qwen3-Embedding-0.6B, run locally).
3. Level 1 plus a frontier model (Claude Opus 5.5 through the local `claude`
   command) reordering the top of the list.

## Set-up (`split.py`)

- A like is a rating in the top quarter of the source's scale and at or above
  that person's own average. 76 million likes from 5.7 million people over
  114,317 titles with three or more likers.
- 7,700 test people held out: up to 1,500 per data set with 30 or more likes
  (Netflix 1,500, MovieLens 1,500, Letterboxd 800, Trakt 800, Amazon 800,
  MovieTweetings 300) plus 2,000 with ten or more liked series. Their ratings
  are not used to learn anything.
- "Little-rated" means fewer than 500 likers across all data sets.
  "Long-tail people" have a quarter or more of their likes on little-rated
  titles: 1,638 of the 7,660 used.
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

All 7,660 people:

| segment | k | popularity | sum | max | max+ | people |
|---|---|---|---|---|---|---|
| films | 10 | 0.248 | 0.350 | 0.305 | 0.333 | 7,515 |
| films | 50 | 0.310 | 0.430 | 0.385 | 0.428 | 4,678 |
| films, little-rated | 10 | 0.013 | 0.105 | 0.096 | 0.098 | 5,208 |
| series | 5 | 0.243 | 0.345 | 0.342 | 0.342 | 5,316 |
| series | 10 | 0.243 | 0.390 | 0.384 | 0.385 | 5,150 |
| series | 20 | 0.247 | 0.449 | 0.434 | 0.438 | 4,752 |
| series | 50 | 0.275 | 0.596 | 0.583 | 0.587 | 3,151 |
| series, little-rated | 10 | 0.030 | 0.192 | 0.186 | 0.187 | 2,746 |

The 1,638 long-tail people:

| segment | k | popularity | sum | max | max+ | people |
|---|---|---|---|---|---|---|
| films | 5 | 0.057 | 0.148 | 0.129 | 0.133 | 1,596 |
| films | 10 | 0.058 | 0.162 | 0.138 | 0.146 | 1,559 |
| films | 20 | 0.062 | 0.174 | 0.145 | 0.159 | 1,410 |
| films | 50 | 0.129 | 0.311 | 0.259 | 0.298 | 539 |
| films, little-rated | 10 | 0.010 | 0.117 | 0.098 | 0.103 | 1,487 |
| series | 5 | 0.068 | 0.174 | 0.167 | 0.169 | 1,501 |
| series | 10 | 0.067 | 0.211 | 0.198 | 0.200 | 1,440 |
| series | 20 | 0.063 | 0.248 | 0.217 | 0.225 | 1,237 |
| series | 50 | 0.030 | 0.369 | 0.347 | 0.351 | 448 |
| series, little-rated | 5 | 0.017 | 0.146 | 0.142 | 0.143 | 1,391 |
| series, little-rated | 10 | 0.019 | 0.201 | 0.191 | 0.193 | 1,314 |
| series, little-rated | 20 | 0.016 | 0.246 | 0.222 | 0.227 | 1,092 |

- Level 1 beats popularity everywhere, by most for long-tail people and
  little-rated titles: for little-rated series, 0.201 against 0.019 at k=10.
- More revealed likes help steadily: series recall rises from 0.345 at 5
  to 0.596 at 50.
- Summing beats the strongest link in every cell, by up to 5 points. The
  sum's earlier failure (one heavily credited show drowning the rest) was in
  the maker graph, not here.
- By data set (k=10, series, max+): Netflix 0.519, MovieLens 0.485,
  Letterboxd 0.397, Amazon 0.204, Trakt 0.170, against popularity 0.404,
  0.172, 0.012, 0.165, 0.079.

## 2. Film likes predict series likes (`eval_warm.py`)

2,783 people with 20 or more liked films and 6 or more liked series (655 of
them long-tail). Five of their liked series are held as seeds in one arm;
the measure is recall@50 over their other liked series.

| seeds | series, all people | series, little-rated, all | series, long-tail | series, little-rated, long-tail |
|---|---|---|---|---|
| popularity | 0.244 | 0.025 | 0.052 | 0.016 |
| 10 films | 0.328 | 0.096 | 0.130 | 0.086 |
| 20 films | 0.355 | 0.133 | 0.155 | 0.115 |
| 5 series | 0.517 | 0.322 | 0.263 | 0.265 |
| 20 films + 5 series | 0.527 | 0.334 | 0.249 | 0.268 |

Film likes carry real signal for series (20 films reach 60 to 70% of what 5
series do, well above popularity), but a few stated series favourites matter
more than many films.

## 3. Does anything help on rated titles? (`eval_warm_content.py`)

A random 2,000 of the test people (1,900 usable, 368 long-tail), recall@50,
k=10. Fusion is reciprocal-rank fusion; "1/.5/.25" weights the parts.

| method | films | films, little | series | series, little | long-tail series | long-tail series, little |
|---|---|---|---|---|---|---|
| likes only (sum) | 0.366 | 0.105 | 0.397 | 0.189 | 0.203 | 0.179 |
| likes, popularity-corrected | 0.194 | 0.085 | 0.362 | 0.168 | 0.167 | 0.163 |
| likes + makers | 0.288 | 0.033 | 0.134 | 0.093 | 0.115 | 0.108 |
| likes + makers + words, 1/.5/.25 | 0.363 | 0.043 | 0.195 | 0.108 | 0.136 | 0.135 |
| likes + makers + embedding, 1/.5/.25 | 0.364 | 0.040 | 0.182 | 0.096 | 0.134 | 0.114 |
| likes + makers + words + embedding | 0.196 | 0.035 | 0.110 | 0.081 | 0.105 | 0.106 |

Where a title has ratings, other people's likes alone are best; every mix
with makers, plot words or embeddings is worse. "Popularity-corrected"
(co-likes divided by the candidate's own likers rather than its square root)
costs 4 points on series and half the film recall: the hits it loses are the
popular titles a person has most likely already seen, which this measure
counts as hits.

## 4. Titles nobody has rated (`eval_new.py`)

1,600 held-out titles; for each person, 20 revealed likes among rated
titles; recall@20 among the 800 new titles of each kind. 3,948 people liked
a new series, 6,248 a new film.

| signal | level | series | films |
|---|---|---|---|
| random | | 0.028 | 0.025 |
| makers (creator-weighted) | 1 | 0.108 | 0.147 |
| plot words, closest revealed like | 1 | 0.154 | 0.290 |
| plot words via rated neighbours | 1 | 0.109 | 0.390 |
| makers + words (fused) | 1 | 0.190 | 0.397 |
| embedding, closest revealed like | 2 | 0.115 | 0.136 |
| embedding via rated neighbours | 2 | 0.074 | 0.236 |
| makers + embedding | 2 | 0.143 | 0.214 |
| level 1 + embedding | 2 | 0.169 | 0.373 |
| IMDb votes (uses future votes; not available on release day) | | 0.148 | 0.387 |

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
for each candidate, title, year and plot text. The 30 come from level 1.
Only people with at least one hidden like in the 30 are used, sampled at
random. Hidden likes in the top 10, before and after:

| case | people | hidden likes in the 30 | level 1 | frontier model | better / worse | sign test p |
|---|---|---|---|---|---|---|
| rated series, long-tail people (pool: likes) | 40 | 74 | 29 | 47 | 19 / 6 | 0.015 |
| new series (pool: makers + words) | 20 | 33 | 15 | 29 | 11 / 1 | 0.006 |
| new films (pool: makers + words) | 20 | 60 | 24 | 49 | 14 / 0 | < 0.001 |

The model knows these titles: they are "new" only in the data, and all
predate its training. It also knows their audiences. For a truly new release
it knows nothing but the plot text it is handed, so these gains are an upper
bound for the "new and good" case, and this data cannot say how much of them
survives. Its order also varies between runs, so a level-3 backlog changes a
little each time it is made.

## What this says

- Level 1 is a real ranker for rated titles and the long tail, and level 2
  (embeddings) added nothing in any test.
- For titles with no ratings, level 1 reaches about 7 times random for series
  and 16 times for films; makers alone are weaker than plot words on
  average.
- Level 3 improves the order of a short list in every case tried, strongly
  for unrated titles, with the caveat above.

## 6. The taste map (`map.py`, `shelves.py`, `name_clusters.py`)

One graph over the 129,245 films and series with 300 or more IMDb votes.
Titles with 30 or more likers (36,205) link to their 20 strongest neighbours
by other people's likes; every title also links to its 10 closest by shared
makers plus plot words, at a quarter weight for titles with likes of their own.
Leiden community detection, with clusters over 150 cut again, gives 4,002
clusters (median 19 titles). Those join into 132 shelves by Leiden over the
cluster-closeness graph. A frontier model names clusters and shelves from
their members, for the ones in use.

Likes alone grouped TV by data set and era (a 2000s DVD catalogue, one
service's hits); content links at full weight let plot words override
audiences (a shared word in two plots outweighed two quite different
audiences). The quarter weight is the compromise.

How well a title with no ratings can be placed: hiding the likes links of
3,000 well-rated titles, makers and plot words alone put 0.49 in their own
cluster and 0.54 in it or one of its 5 closest. A thinly rated title's shelf
is more reliable than its exact cluster.

## 7. Choosing stretch picks (`eval_stretch.py`)

For 1,765 held-out people (296 long-tail), 20 likes revealed; their usual
clusters are those 20 likes' clusters. Stretch likes are their other likes in
any other cluster. Recall@50 over titles outside the usual clusters, with how
well known the hits are:

| method | recall, all | median likers of hits | little-rated share of hits | recall, long-tail | median likers | little-rated share |
|---|---|---|---|---|---|---|
| popularity | 0.182 | 116,688 | 0.000 | 0.056 | 134,380 | 0.000 |
| map: closest clusters, best-rated first | 0.130 | 51,636 | 0.036 | 0.069 | 12,153 | 0.267 |
| likes | 0.283 | 67,024 | 0.004 | 0.141 | 22,477 | 0.042 |
| likes, popularity-corrected | 0.199 | 32,812 | 0.062 | 0.091 | 1,595 | 0.421 |
| map + likes | 0.254 | 64,498 | 0.018 | 0.126 | 17,782 | 0.147 |
| map + corrected likes | 0.206 | 41,666 | 0.046 | 0.095 | 6,899 | 0.351 |

Choosing stretch by map closeness alone finds fewer stretch likes than other
people's likes do, and adding it to likes lowers recall. So stretch picks are
chosen by the strength of their link to the person's titles; the map decides
what counts as outside their usual clusters, keeps the set varied and names
what each pick is. Correcting for popularity costs recall but its hits are far
less well known (for long-tail people, a median of 1,595 likers against
22,477), which is the trade the picks want. The map was built from everyone's
likes, test people included (7,700 of 5.7 million).
