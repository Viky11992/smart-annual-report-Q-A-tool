"""
index.py
BM25-based search index over ingested PDF pages.
Returns the top-k page chunks most relevant to a query,
boosting pages that contain tables for numeric questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rank_bm25 import BM25Okapi

from ingest import PageData
from metrics import expand_query


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    chunk_id: int
    pdf_index: int
    page_number: int
    text: str
    has_table: bool


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenise(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

class AnnualReportIndex:
    """
    Builds a BM25 index over chunks derived from ingested pages.
    Each page is treated as one chunk (optionally split for very long pages).
    """

    MAX_CHUNK_CHARS = 3000  # characters per chunk before splitting

    def __init__(self, pages: list[PageData]) -> None:
        self.chunks: list[Chunk] = []
        self._build_chunks(pages)
        tokenised = [_tokenise(c.text) for c in self.chunks]
        self.bm25 = BM25Okapi(tokenised)

    def _build_chunks(self, pages: list[PageData]) -> None:
        chunk_id = 0
        for page in pages:
            full = page.full_text
            if len(full) <= self.MAX_CHUNK_CHARS:
                self.chunks.append(Chunk(
                    chunk_id=chunk_id,
                    pdf_index=page.pdf_index,
                    page_number=page.page_number,
                    text=full,
                    has_table=page.has_table,
                ))
                chunk_id += 1
            else:
                # Split into overlapping sub-chunks of MAX_CHUNK_CHARS with 200-char overlap
                overlap = 200
                step = self.MAX_CHUNK_CHARS - overlap
                for start in range(0, len(full), step):
                    sub = full[start: start + self.MAX_CHUNK_CHARS]
                    if not sub.strip():
                        continue
                    self.chunks.append(Chunk(
                        chunk_id=chunk_id,
                        pdf_index=page.pdf_index,
                        page_number=page.page_number,
                        text=sub,
                        has_table=page.has_table,
                    ))
                    chunk_id += 1

    def search(
        self,
        query: str,
        top_k: int = 8,
        boost_tables: bool = False,
    ) -> list[Chunk]:
        """
        Return top_k chunks for the query.
        If boost_tables is True, pages containing tables get a score bonus.
        """
        expanded = expand_query(query)
        tokens = _tokenise(expanded)
        scores = self.bm25.get_scores(tokens)

        if boost_tables:
            TABLE_BOOST = 2.0
            for i, chunk in enumerate(self.chunks):
                if chunk.has_table:
                    scores[i] += TABLE_BOOST

        # Rank by score descending; deduplicate by page_number (keep highest score)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        seen_pages: set[int] = set()
        results: list[Chunk] = []
        for idx, score in ranked:
            if score <= 0:
                break
            chunk = self.chunks[idx]
            if chunk.page_number not in seen_pages:
                seen_pages.add(chunk.page_number)
                results.append(chunk)
            if len(results) >= top_k:
                break

        return results
