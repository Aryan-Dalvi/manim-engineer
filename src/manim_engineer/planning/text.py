"""Lightweight lexical tools: tokens, TF-IDF-ish vectors, cosine. No ML dependency."""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_\-]+|\d+(?:\.\d+)?")
STOPWORDS = set(
    """a an the and or but if then else so of to in on at by for with from as is are was were be been being
    it its this that these those there here we you they he she i me my our your their them his her us
    do does did doing have has had having not no yes can could would should will shall may might must
    just really very also too more most much many some any all each every both few little lot lots kind
    sort like about into over under again further once because while where when why how what which who whom
    thing things way get got go going gonna wanna okay ok right um uh yeah know think mean say said
    one two three first second next now than up down out off only own same such let make made see
    actually basically literally sort kind bit""".split()
)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text) if len(t) > 2 and t.lower() not in STOPWORDS]


class Vectorizer:
    """Incremental TF-IDF: document frequencies grow as units are added."""

    def __init__(self) -> None:
        self.df: Counter[str] = Counter()
        self.n_docs = 0

    def fit_one(self, text: str) -> None:
        self.n_docs += 1
        self.df.update(set(tokens(text)))

    def vector(self, text: str) -> dict[str, float]:
        tf = Counter(tokens(text))
        if not tf:
            return {}
        out: dict[str, float] = {}
        for term, c in tf.items():
            idf = math.log((1 + self.n_docs) / (1 + self.df.get(term, 0))) + 1.0
            out[term] = (1 + math.log(c)) * idf
        norm = math.sqrt(sum(v * v for v in out.values())) or 1.0
        return {k: v / norm for k, v in out.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def add_to_centroid(centroid: dict[str, float], vec: dict[str, float], n: int) -> dict[str, float]:
    """Running mean of unit vectors, renormalized."""
    out = {k: v * n for k, v in centroid.items()}
    for k, v in vec.items():
        out[k] = out.get(k, 0.0) + v
    total = n + 1
    out = {k: v / total for k, v in out.items()}
    norm = math.sqrt(sum(v * v for v in out.values())) or 1.0
    return {k: v / norm for k, v in out.items()}


def top_terms(vec: dict[str, float], k: int = 12) -> list[str]:
    return [t for t, _ in sorted(vec.items(), key=lambda kv: -kv[1])[:k]]


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


CONCRETE_CUES = re.compile(
    r"\b(equation|formula|derive|derivation|proof|theorem|lemma|gradient|matrix|vector|softmax|attention|"
    r"architecture|encoder|decoder|layer|pipeline|loop|algorithm|step|iteration|rollout|trajectory|"
    r"probability|distribution|sample|expectation|variance|plot|curve|graph|axis|converge|"
    r"key idea|intuition|intuitively|think of it as|picture|imagine|the trick|geometrically)\b",
    re.I,
)


def concreteness(text: str) -> float:
    """0..1 score: math symbols, numbers, and explanatory cue phrases."""
    n = max(len(text), 1)
    cues = len(CONCRETE_CUES.findall(text))
    symbols = len(re.findall(r"[=+\-*/^_\\{}()<>]|\d", text))
    score = min(1.0, cues / 6.0) * 0.6 + min(1.0, symbols / (n / 40)) * 0.4
    return round(score, 3)
