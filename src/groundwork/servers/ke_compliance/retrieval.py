"""A small BM25 index, written out in full rather than pulled in as a dependency.

BM25 is about forty lines. On an engagement, a forty line retriever that the customer
can read, reason about and tune beats a vector database they cannot operate, at least
until you have evidence that you need more. It is also trivially deterministic, which
matters because retrieval quality is one of the things the eval suite measures.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

K1 = 1.5
B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORD_TEXT = """
a an the and or but if then than that this these those is are was were be been
being do does did doing have has had having i you he she it we they them his her
its our your their to of in on at by for with about against between into through
during before after above below from up down out off over under again further
once here there when where why how all any both each few more most other some
such no nor not only own same so too very can will just should now what which
who whom
"""

STOPWORDS: frozenset[str] = frozenset(_STOPWORD_TEXT.split())


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non alphanumerics, drop stopwords and single characters."""
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in STOPWORDS and len(token) > 1
    ]


@dataclass(frozen=True)
class IndexedDocument:
    """One unit of retrieval. In this server that is a document section."""

    key: str
    text: str


@dataclass(frozen=True)
class SearchHit:
    """A scored result."""

    key: str
    score: float


class Bm25Index:
    """Okapi BM25 over a fixed collection.

    Args:
        documents: The units of retrieval. The `key` is what search returns.
        k1: Term frequency saturation. Higher means repeated terms keep adding weight.
        b: Length normalisation. 0 ignores document length, 1 fully normalises by it.
    """

    def __init__(
        self,
        documents: Iterable[IndexedDocument],
        *,
        k1: float = K1,
        b: float = B,
    ) -> None:
        self.k1 = k1
        self.b = b
        self._keys: list[str] = []
        self._term_counts: list[Counter[str]] = []
        self._lengths: list[int] = []
        document_frequency: Counter[str] = Counter()

        for document in documents:
            tokens = tokenize(document.text)
            counts = Counter(tokens)
            self._keys.append(document.key)
            self._term_counts.append(counts)
            self._lengths.append(len(tokens))
            document_frequency.update(counts.keys())

        self._count = len(self._keys)
        self._average_length = (sum(self._lengths) / self._count) if self._count else 0.0
        self._idf = {
            term: math.log(1 + (self._count - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    def __len__(self) -> int:
        return self._count

    @property
    def keys(self) -> Sequence[str]:
        """Every indexed key, in insertion order."""
        return tuple(self._keys)

    def score(self, query_tokens: Sequence[str], index: int) -> float:
        """BM25 score of one document against already tokenized query terms."""
        length = self._lengths[index] or 1
        counts = self._term_counts[index]
        norm = self.k1 * (1 - self.b + self.b * length / (self._average_length or 1))
        total = 0.0
        for term in query_tokens:
            frequency = counts.get(term)
            if not frequency:
                continue
            total += self._idf.get(term, 0.0) * (frequency * (self.k1 + 1)) / (frequency + norm)
        return total

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        """Return the `top_k` highest scoring documents, best first.

        Documents scoring zero are dropped rather than padded in, so an off topic query
        returns nothing and the agent has to say so instead of citing the least bad hit.
        """
        tokens = tokenize(query)
        if not tokens or not self._count:
            return []
        scored = [
            SearchHit(key=self._keys[index], score=round(self.score(tokens, index), 4))
            for index in range(self._count)
        ]
        hits = [hit for hit in scored if hit.score > 0]
        hits.sort(key=lambda hit: (-hit.score, hit.key))
        return hits[: max(0, top_k)]
