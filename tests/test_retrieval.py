"""Tests for the pure Python BM25 implementation."""

from __future__ import annotations

import pytest

from groundwork.servers.ke_compliance.corpus import DOCUMENTS
from groundwork.servers.ke_compliance.retrieval import Bm25Index, IndexedDocument, tokenize


def build(texts: dict[str, str]) -> Bm25Index:
    return Bm25Index([IndexedDocument(key=key, text=text) for key, text in texts.items()])


class TestTokenize:
    def test_lowercases_and_splits_on_punctuation(self) -> None:
        assert tokenize("PAYE, VAT; turnover-tax") == ["paye", "vat", "turnover", "tax"]

    def test_drops_stopwords(self) -> None:
        assert "the" not in tokenize("the register of the controller")

    def test_empty_input(self) -> None:
        assert tokenize("   ") == []


class TestBm25:
    def test_ranks_the_on_topic_document_first(self) -> None:
        index = build(
            {
                "a": "data protection registration for data controllers",
                "b": "value added tax returns and filing deadlines",
                "c": "food hygiene licence for premises",
            }
        )
        hits = index.search("data controller registration", top_k=3)
        assert hits[0].key == "a"

    def test_term_frequency_saturates(self) -> None:
        """A document repeating a term twenty times should not beat a focused one by 20x."""
        index = build({"spam": "tax " * 20 + "unrelated words here", "real": "tax filing deadline"})
        scores = {hit.key: hit.score for hit in index.search("tax", top_k=2)}
        assert scores["spam"] < scores["real"] * 3

    def test_rare_terms_outweigh_common_ones(self) -> None:
        index = build(
            {
                "a": "tax filing housing levy",
                "b": "tax filing",
                "c": "tax filing",
                "d": "tax filing",
            }
        )
        hits = index.search("tax housing", top_k=4)
        assert hits[0].key == "a"

    def test_off_topic_query_returns_nothing(self) -> None:
        index = build({"a": "tax filing", "b": "payroll"})
        assert index.search("submarine propulsion", top_k=5) == []

    def test_top_k_is_respected(self) -> None:
        index = build({"a": "tax", "b": "tax", "c": "tax"})
        assert len(index.search("tax", top_k=2)) == 2

    def test_empty_query_returns_nothing(self) -> None:
        assert build({"a": "tax"}).search("the and of", top_k=5) == []

    def test_index_reports_its_size(self) -> None:
        index = build({"a": "tax", "b": "payroll"})
        assert len(index) == 2
        assert set(index.keys) == {"a", "b"}

    def test_empty_index_is_safe(self) -> None:
        assert Bm25Index([]).search("anything", top_k=3) == []


class TestAgainstTheRealCorpus:
    @pytest.mark.parametrize(
        ("query", "expected_doc"),
        [
            ("register as a data controller", "DOC-DPA-01"),
            ("value added tax threshold", "DOC-TAX-01"),
            ("remit PAYE deductions", "DOC-PAY-01"),
            ("single business permit renewal", "DOC-PERMIT-01"),
            ("written employment contract", "DOC-EMP-01"),
        ],
    )
    def test_each_topic_finds_its_document(self, query: str, expected_doc: str) -> None:
        index = Bm25Index(
            [
                IndexedDocument(
                    key=f"{doc.doc_id}#{section.section_id}",
                    text=f"{section.heading} {section.text}",
                )
                for doc in DOCUMENTS
                for section in doc.sections
            ]
        )
        hits = index.search(query, top_k=3)
        assert hits, f"no hits for {query!r}"
        assert hits[0].key.startswith(expected_doc)
