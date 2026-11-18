"""What a title is about, from its plot text: plain word overlap (level 1) and a
frozen open embedding model (level 2)."""
import duckdb
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from core import W

_PRIORITY = "case src when 'plex' then 0 when 'wikipedia' then 1 else 2 end"


def plots():
    """All plot text per title, Plex first, then Wikipedia, then Amazon."""
    return dict(duckdb.sql(f"select t, string_agg(txt, ' ' order by {_PRIORITY}) from '{W}/plot.parquet' group by t").fetchall())


def display_plots(limit=230):
    out = {}
    for t, txt in duckdb.sql(f"select t, first(txt order by {_PRIORITY}) from '{W}/plot.parquet' group by t").fetchall():
        txt = " ".join(txt.split())
        cut = txt[:limit]
        if len(txt) > limit:
            end = cut.rfind(". ")
            cut = cut[:end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "…"
        out[t] = cut
    return out


class Text:
    def __init__(self):
        p = plots()
        self.ids = np.fromiter(p.keys(), np.int64)
        self.pos = {t: i for i, t in enumerate(self.ids)}
        self.X = TfidfVectorizer(stop_words="english", min_df=2, max_df=0.2, sublinear_tf=True,
                                 dtype=np.float32).fit_transform(p.values())

    def sims(self, seeds):
        """(titles x seeds) cosine of plot words."""
        rows = [self.pos[s] for s in seeds]
        return (self.X @ self.X[rows].T).toarray()


def _best(ids, S, seeds, weights):
    S = S * np.array([weights[s] for s in seeds])[None, :]
    best = S.argmax(1)
    v = S[np.arange(len(ids)), best]
    keep = v > 0
    return dict(zip(ids[keep], v[keep])), dict(zip(ids[keep], np.array(seeds)[best[keep]]))


def text_scores(seeds, weights):
    tx = Text()
    seeds = [s for s in seeds if s in tx.pos]
    S = tx.sims(seeds)
    S[[tx.pos[s] for s in seeds], :] = 0
    return _best(tx.ids, S, seeds, weights)


def embedding_scores(seeds, weights):
    ids, E = load_embeddings()
    pos = {t: i for i, t in enumerate(ids)}
    seeds = [s for s in seeds if s in pos]
    S = E @ E[[pos[s] for s in seeds]].T
    S[[pos[s] for s in seeds], :] = 0
    return _best(ids, S, seeds, weights)


def load_embeddings():
    d = np.load(W / "emb.npz")
    return d["ids"], d["E"]
