"""Phase 2 retrieval components: structured chunking, hybrid search, reranking, budgets."""

from collections.abc import AsyncIterator, Sequence

import numpy as np
import pytest

from documind.core.config import RerankerName, RetrievalMode, Settings
from documind.core.container import build_container
from documind.core.errors import ProviderError
from documind.domain import Chunk, Message, Page, ScoredChunk, TokenUsage
from documind.ingestion.structure import is_heading, remove_boilerplate, structured_chunks
from documind.providers.base import Completion, StreamEvent, l2_normalize
from documind.repositories.search import (
    bm25_scores,
    rank,
    reciprocal_rank_fusion,
    term_counts,
    tokenize,
)
from documind.services.prompts import SYSTEM_PROMPT_V1, SYSTEM_PROMPT_V2, build_messages
from documind.services.query import Retrieval
from documind.services.rerank import LLMReranker, parse_ranking

HEADER = "ACME Report 2025 | Confidential"


def page(n: int, body: str) -> Page:
    return Page(n, f"{HEADER}\n{body}\n{n}")


class TestStructuredChunking:
    def test_removes_running_headers_page_numbers_and_toc_lines(self) -> None:
        words = ["alpha", "bravo", "charlie", "delta", "echo"]
        body = [
            "\n".join([*(f"{w} line {j}" for j in range(4)), "See Appendix A.", "x", "y", "z"])
            for w in words
        ]
        pages = [page(i, b) for i, b in enumerate(body, start=1)]
        pages.append(Page(6, "Contents\n1. Overview ........ 3\n2. Details ....... 9"))
        cleaned = remove_boilerplate(pages)
        assert all(HEADER not in p.text for p in cleaned)  # header at the page edge: removed
        assert cleaned[0].text.startswith("alpha line 0")
        assert not cleaned[0].text.endswith("1")  # bare page number removed
        assert all("See Appendix A." in p.text for p in cleaned[:5])  # repeated mid-page: kept
        assert "...." not in cleaned[5].text

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("3.2. CSF Tiers", True),
            ("5.1.1.2 Memorized Secret Verifiers", True),
            ("Appendix A. CSF Core", True),
            ("4. Introduction to Online Resources That Supplement the CSF", True),
            ("2. A Target Profile specifies the desired outcomes that an organization has", False),
            ("1. Scope the Organizational Profile. Document the facts.", False),
            ("Plain sentence without a number", False),
        ],
    )
    def test_heading_detection(self, line: str, expected: bool) -> None:
        assert is_heading(line) is expected

    def test_chunks_carry_title_and_section_and_never_cross_pages(self) -> None:
        pages = [
            page(1, "1. Introduction\n" + "Intro sentence. " * 60),
            page(2, "More intro text without a heading. " * 5),
            page(3, "2. Access Control Rules\nPasswords must be long. " * 3),
            page(4, "Closing remarks for the report."),
        ]
        chunks = structured_chunks(
            pages,
            document_id="d",
            title="ACME Report",
            chunk_tokens=120,
            overlap_tokens=10,
            tokenizer="cl100k_base",
        )
        assert chunks[0].context == "ACME Report > 1. Introduction"
        page2 = [c for c in chunks if c.page == 2]
        assert page2 and page2[0].context.endswith("1. Introduction")  # carried over
        page3 = [c for c in chunks if c.page == 3]
        assert page3[0].context.endswith("2. Access Control Rules")
        assert page3[0].search_text.startswith("ACME Report > 2. Access Control Rules")
        assert [c.index for c in chunks] == list(range(len(chunks)))


class TestHybridSearch:
    def test_tokenize_keeps_identifiers_and_their_parts(self) -> None:
        assert tokenize("What does GV.SC-04 say?") == ["gv.sc-04", "gv", "sc", "04", "say"]

    def test_bm25_prefers_rare_exact_terms(self) -> None:
        docs = [
            term_counts("GV.SC-04: Suppliers are known and prioritized by criticality"),
            term_counts("Suppliers and partners are managed in the supply chain program"),
            term_counts("Backups of data are created and tested"),
        ]
        scores = bm25_scores("What does GV.SC-04 state?", docs)
        assert int(np.argmax(scores)) == 0
        assert scores[2] == 0

    def test_reciprocal_rank_fusion_rewards_agreement(self) -> None:
        fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]])
        assert [item for item, _ in fused][:2] == [1, 3]

    def test_hybrid_rescues_an_identifier_query_that_dense_misses(self) -> None:
        texts = ["GV.SC-04: Suppliers are known", "general supplier guidance", "unrelated"]
        # Dense vectors deliberately rank the identifier chunk last.
        matrix = l2_normalize(np.array([[0.1, 1.0], [1.0, 0.1], [0.9, 0.3]], dtype=np.float32))
        query = l2_normalize(np.array([[1.0, 0.0]], dtype=np.float32))[0]
        dense = rank(
            texts, matrix, query, "GV.SC-04", top_k=3, mode=RetrievalMode.DENSE, candidates=3
        )
        hybrid = rank(
            texts, matrix, query, "GV.SC-04", top_k=3, mode=RetrievalMode.HYBRID, candidates=3
        )
        assert dense[-1][0] == 0
        assert hybrid[0][0] == 0


def scored(texts: Sequence[str]) -> list[ScoredChunk]:
    return [ScoredChunk(Chunk("d", i, 1, t), 1.0) for i, t in enumerate(texts)]


class StubLLM:
    def __init__(self, reply: str = "", fail: bool = False) -> None:
        self.reply, self.fail = reply, fail

    async def complete(self, messages: Sequence[Message], *, max_output_tokens: int) -> Completion:
        if self.fail:
            raise ProviderError("down")
        return Completion(self.reply, TokenUsage(100, 5))

    async def stream(
        self, messages: Sequence[Message], *, max_output_tokens: int
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError
        yield  # pragma: no cover


class TestReranker:
    def test_parse_ranking_tolerates_prose_duplicates_and_omissions(self) -> None:
        assert parse_ranking("Sure! [3, 1, 3, 9]", 4) == [2, 0, 1, 3]
        assert parse_ranking("no idea", 3) == [0, 1, 2]

    async def test_reorders_and_reports_usage(self) -> None:
        result = await LLMReranker(StubLLM("[2, 1]")).rerank("q", scored(["a", "b"]))
        assert [s.chunk.text for s in result.chunks] == ["b", "a"]
        assert result.usage.input_tokens == 100

    async def test_falls_back_to_retrieval_order_on_provider_error(self) -> None:
        result = await LLMReranker(StubLLM(fail=True)).rerank("q", scored(["a", "b"]))
        assert [s.chunk.text for s in result.chunks] == ["a", "b"]
        assert result.usage == TokenUsage()


def test_context_budget_keeps_best_chunks_that_fit(settings: Settings) -> None:
    service = build_container(
        settings.model_copy(update={"context_token_budget": 25})
    ).query_service
    retrieval = Retrieval(scored(["word " * 20, "word " * 10, "tiny"]), {"d": "a.pdf"})
    fitted = service._fit_budget(retrieval)
    assert [len(s.chunk.text.split()) for s in fitted.chunks] == [20]
    huge = Retrieval(scored(["word " * 500]), {"d": "a.pdf"})
    assert len(service._fit_budget(huge).chunks) == 1


def test_prompt_versions() -> None:
    v1 = build_messages("q", [], [], {}, version=1)[0].content
    v2 = build_messages("q", [], [], {}, version=2)[0].content
    assert v1 == SYSTEM_PROMPT_V1 and v2 == SYSTEM_PROMPT_V2
    assert "only part of the question" in v2


async def test_retrieve_uses_reranker_and_counts_its_tokens(settings: Settings) -> None:
    configured = settings.model_copy(update={"reranker": RerankerName.LLM, "retrieval_top_k": 2})
    container = build_container(configured)
    from tests.pdf_factory import make_pdf

    await container.ingestion_service.ingest_bytes(
        "u", "r.pdf", make_pdf(["alpha facts here", "beta facts here", "gamma facts here"])
    )
    retrieval = await container.query_service.retrieve("u", "which page mentions beta?")
    assert len(retrieval.chunks) == 2
    assert retrieval.usage.input_tokens > 0  # the fake LLM's reranking call was counted
