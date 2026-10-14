"""The `ke_compliance` MCP server.

Answers questions about business obligations for small businesses in Kenya, over a
corpus that is entirely synthetic. Every tool description repeats that, and every
result carries a disclaimer, because the failure mode this domain is designed around
is an agent that sounds authoritative about something it made up.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .applicability import BusinessProfile, ComplianceError, check_applicability
from .corpus import (
    CATEGORIES,
    DISCLAIMER,
    DOCUMENTS,
    DOCUMENTS_BY_ID,
    OBLIGATIONS,
    SECTORS,
    all_sections,
)
from .retrieval import Bm25Index, IndexedDocument

mcp = MCPServer(
    name="ke_compliance",
    version="0.1.0",
    instructions=(
        "Question answering over a SYNTHETIC corpus of small business obligations in "
        "Kenya. The corpus was written for a software demonstration. It is not law and "
        "not legal advice. Always cite the section you used, in the form DOC-ID#SECTION. "
        "If search returns nothing relevant, say so rather than answering from memory."
    ),
    log_level="CRITICAL",
)

_SECTION_TEXT: dict[str, dict[str, Any]] = {}
for _doc_id, _section in all_sections():
    _SECTION_TEXT[f"{_doc_id}#{_section.section_id}"] = {
        "doc_id": _doc_id,
        "section": _section,
    }

_INDEX = Bm25Index(
    IndexedDocument(
        key=key,
        text=f"{DOCUMENTS_BY_ID[entry['doc_id']].title} {entry['section'].heading} "
        f"{entry['section'].text}",
    )
    for key, entry in _SECTION_TEXT.items()
)


@mcp.tool()
def search_corpus(query: str, top_k: int = 5) -> dict[str, Any]:
    """Search the synthetic corpus and return matching sections, best first.

    Retrieval is BM25 over section text. Results are sections, not whole documents, so
    the `citation` field on each hit is directly quotable. A query that matches nothing
    returns an empty list, which means the corpus does not cover it: say that rather
    than answering from general knowledge.

    The corpus is synthetic, written for this demo, and is not legal advice.

    Args:
        query: Natural language question or keywords.
        top_k: How many sections to return. 3 to 8 is usually right.
    """
    if not query.strip():
        raise ToolError("query cannot be empty")
    hits = _INDEX.search(query, top_k=top_k)
    results = []
    for hit in hits:
        entry = _SECTION_TEXT[hit.key]
        payload = entry["section"].to_api(entry["doc_id"])
        payload["score"] = hit.score
        payload["title"] = DOCUMENTS_BY_ID[entry["doc_id"]].title
        results.append(payload)
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "corpus": "synthetic",
        "note": (
            "No results means the corpus does not cover this question."
            if not results
            else "Cite sections using the 'citation' field, for example DOC-TAX-01#S2."
        ),
    }


@mcp.tool()
def list_documents() -> dict[str, Any]:
    """List every document in the synthetic corpus with its sections and categories."""
    return {
        "count": len(DOCUMENTS),
        "disclaimer": DISCLAIMER,
        "documents": [doc.to_api(include_text=False) for doc in DOCUMENTS],
    }


@mcp.tool()
def get_document(doc_id: str) -> dict[str, Any]:
    """Get one whole document, all sections, from the synthetic corpus.

    Prefer get_section when you already know which section you need: whole documents
    are long and most questions turn on one or two sections.

    Args:
        doc_id: Document id such as 'DOC-TAX-01'.
    """
    document = DOCUMENTS_BY_ID.get(doc_id.upper())
    if document is None:
        available = ", ".join(sorted(DOCUMENTS_BY_ID))
        raise ToolError(f"document '{doc_id}' not found. Available documents: {available}.")
    return document.to_api()


@mcp.tool()
def get_section(doc_id: str, section_id: str) -> dict[str, Any]:
    """Get one section of one document, for quoting and citing.

    Args:
        doc_id: Document id such as 'DOC-PAY-01'.
        section_id: Section id such as 'S5'.
    """
    key = f"{doc_id.upper()}#{section_id.upper()}"
    entry = _SECTION_TEXT.get(key)
    if entry is None:
        document = DOCUMENTS_BY_ID.get(doc_id.upper())
        if document is None:
            available = ", ".join(sorted(DOCUMENTS_BY_ID))
            raise ToolError(f"document '{doc_id}' not found. Available documents: {available}.")
        sections = ", ".join(section.section_id for section in document.sections)
        raise ToolError(f"section '{section_id}' not found in {doc_id}. Sections: {sections}.")
    return entry["section"].to_api(entry["doc_id"])


@mcp.tool()
def list_obligations(category: str | None = None) -> dict[str, Any]:
    """List structured obligations: agency, filing frequency, deadline, and citations.

    This is the structured view of the same synthetic corpus that search_corpus reads.
    Use it when the question is about deadlines or who to file with. Use
    check_applicability when the question is whether a specific business is in scope.

    These obligations are synthetic and are not legal advice.

    Args:
        category: Optional filter. One of: tax, payroll, data_protection, permits,
            employment, sector.
    """
    selected = list(OBLIGATIONS)
    if category:
        key = category.lower().strip()
        if key not in CATEGORIES:
            raise ToolError(f"unknown category '{category}'. Categories: {', '.join(CATEGORIES)}.")
        selected = [item for item in selected if item.category == key]
    return {
        "count": len(selected),
        "category": category,
        "categories": list(CATEGORIES),
        "obligations": [item.to_api() for item in selected],
    }


@mcp.tool()
def check_applicability_for_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Decide which synthetic obligations apply to a specific business, and why.

    Each result carries the reasoning that produced it and the sections it came from,
    so the answer can be checked rather than trusted. Anything the profile does not
    state is treated as absent, so a missing field makes the answer narrower, not wider.

    The rules are synthetic and are not legal advice.

    Args:
        profile: Object with these fields: employees (int), annual_turnover_kes (int),
            sector (one of retail, food, services, fintech, health, manufacturing),
            handles_personal_data (bool), has_physical_premises (bool).
    """
    try:
        parsed = BusinessProfile.from_dict(profile)
    except ComplianceError as exc:
        raise ToolError(str(exc)) from exc
    result = check_applicability(parsed)
    result["known_sectors"] = list(SECTORS)
    result["disclaimer"] = DISCLAIMER
    return result


def main() -> None:
    """Run the server over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
