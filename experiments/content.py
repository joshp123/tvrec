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
    """Plain word overlap (TF-IDF cosine) between plots."""

    def __init__(self):
        p = plots()
        self.ids = np.fromiter(p.keys(), np.int64)
        self.pos = {t: i for i, t in enumerate(self.ids)}
        self.X = TfidfVectorizer(stop_words="english", min_df=2, max_df=0.2, sublinear_tf=True,
                                 dtype=np.float32).fit_transform(p.values())

    def block(self, a, b):
        return (self.X[a] @ self.X[b].T).toarray()

    def sims(self, seeds):
        """(every title x seeds); a title is not similar to itself."""
        S = (self.X @ self.X[[self.pos[s] for s in seeds]].T).toarray()
        S[[self.pos[s] for s in seeds], np.arange(len(seeds))] = 0
        return S


class Embeddings(Text):
    """Cosine between plot embeddings from a frozen open model (embed.py)."""

    def __init__(self):
        self.ids, self.X = load_embeddings()
        self.pos = {t: i for i, t in enumerate(self.ids)}

    def block(self, a, b):
        return self.X[a] @ self.X[b].T

    def sims(self, seeds):
        S = self.X @ self.X[[self.pos[s] for s in seeds]].T
        S[[self.pos[s] for s in seeds], np.arange(len(seeds))] = 0
        return S


def load_embeddings():
    """Title ids and their embeddings, memory-mapped (embed.py)."""
    return np.load(W / "emb_ids.npy"), np.load(W / "emb.npy", mmap_mode="r")
