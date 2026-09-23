import itertools

import pytest

from documind.core.errors import InvalidDocumentError
from documind.domain import Page
from documind.ingestion.chunking import chunk_pages, split_text
from documind.ingestion.pdf import parse_pdf
from tests.pdf_factory import make_pdf

PARAGRAPHS = "\n\n".join(
    f"Paragraph {i}. " + " ".join(f"word{i}_{j}" for j in range(40)) for i in range(6)
)


class TestSplitText:
    def test_chunks_respect_size(self) -> None:
        chunks = split_text(PARAGRAPHS, chunk_size=200, overlap=30)
        assert len(chunks) > 1
        assert all(len(c) <= 200 for c in chunks)

    def test_consecutive_chunks_overlap(self) -> None:
        chunks = split_text(PARAGRAPHS, chunk_size=200, overlap=40)
        overlapping = sum(1 for a, b in itertools.pairwise(chunks) if a[-15:] in b)
        assert overlapping >= len(chunks) // 2

    def test_no_text_is_lost(self) -> None:
        chunks = split_text(PARAGRAPHS, chunk_size=200, overlap=0)
        assert set(" ".join(chunks).split()) == set(PARAGRAPHS.split())

    def test_hard_splits_a_single_long_token(self) -> None:
        chunks = split_text("x" * 450, chunk_size=200, overlap=0)
        assert [len(c) for c in chunks] == [200, 200, 50]

    def test_short_and_empty_text(self) -> None:
        assert split_text("hello", chunk_size=200, overlap=30) == ["hello"]
        assert split_text("", chunk_size=200, overlap=30) == []


def test_chunk_pages_tracks_page_numbers_and_indices() -> None:
    pages = [Page(1, "alpha " * 60), Page(2, ""), Page(3, "gamma " * 10)]
    chunks = chunk_pages(pages, document_id="d1", chunk_size=100, overlap=10)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert {c.page for c in chunks} == {1, 3}  # the empty page produces no chunks
    assert chunks[-1].page == 3


class TestParsePdf:
    def test_extracts_text_per_page(self) -> None:
        pages = parse_pdf(make_pdf(["First page", "Second page"]), max_pages=10)
        assert [(p.number, p.text) for p in pages] == [(1, "First page"), (2, "Second page")]

    def test_rejects_non_pdf(self) -> None:
        with pytest.raises(InvalidDocumentError, match="not a PDF"):
            parse_pdf(b"hello world", max_pages=10)

    def test_rejects_corrupt_pdf(self) -> None:
        with pytest.raises(InvalidDocumentError):
            parse_pdf(b"%PDF-1.4\ngarbage", max_pages=10)

    def test_enforces_page_limit(self) -> None:
        with pytest.raises(InvalidDocumentError, match="more than 2 pages"):
            parse_pdf(make_pdf(["a", "b", "c"]), max_pages=2)

    def test_rejects_pdf_without_text(self) -> None:
        with pytest.raises(InvalidDocumentError, match="No text"):
            parse_pdf(make_pdf([""]), max_pages=10)
