"""Structure-aware chunking.

Three things the baseline gets wrong on real reports, measured by the eval harness:

1. Running headers/footers ("NIST CSWP 29 ... February 26, 2024", page numbers) repeat on every
   page, so every chunk shares boilerplate that dilutes its embedding.
2. Table-of-contents lines ("3. Introduction ......... 6") mention every topic, so TOC chunks
   match almost any question while answering none.
3. Small character chunks cut lists and table rows apart, and a chunk loses track of which
   section it belongs to.

So: strip repeated lines and TOC leaders, chunk by tokens (bigger, list-friendly chunks), and
prefix each chunk's *embedded* text with "document title > section heading" (a contextual chunk
header). Chunks still never cross page boundaries, so citations stay exact.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace

import tiktoken

from documind.domain import Chunk, Page
from documind.ingestion.chunking import split_text

_DIGITS = re.compile(r"\d+")
_TOC_LINE = re.compile(r"\.{4,}\s*[ivxlc\d]+\s*$", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?(?:\d{1,4}|[ivxlc]{1,6})$", re.IGNORECASE)
# "3.2. CSF Tiers", "5.1.1.2 Memorized Secret Verifiers", "Appendix A. CSF Core".
# Headings are short and don't end in a period; numbered list items usually do.
_HEADING = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?|Appendix [A-Z]\.?)\s+([A-Z][^.]{2,90})$",
)
# Words allowed to stay lowercase in a Title Case heading.
_MINOR_WORD_TEXT = "a an and as at by for from in of on or the to via vs with"
_MINOR_WORDS = frozenset(_MINOR_WORD_TEXT.split())
_MAX_HEADING_WORDS = 12
_MIN_CHUNK_TOKENS = 40  # smaller page leftovers are merged into the previous chunk
_EDGE_TOP_LINES = 5  # running headers live in the first/last few lines of a page
_EDGE_BOTTOM_LINES = 3
_MIN_PAGES_FOR_BOILERPLATE = 4
_BOILERPLATE_PAGE_SHARE = 0.5


def _line_key(line: str) -> str:
    # Page numbers inside headers differ per page; normalise digits so they still match.
    return _DIGITS.sub("#", line.strip().lower())


def _is_edge(i: int, n: int) -> bool:
    return i < _EDGE_TOP_LINES or i >= n - _EDGE_BOTTOM_LINES


def remove_boilerplate(pages: Sequence[Page]) -> list[Page]:
    """Drop running headers/footers (edge lines repeated on at least half the pages), TOC
    leader lines and bare page numbers. Only page edges are considered, so a genuine sentence
    that happens to recur mid-page is never removed."""
    repeated: set[str] = set()
    if len(pages) >= _MIN_PAGES_FOR_BOILERPLATE:
        counts: Counter[str] = Counter()
        for p in pages:
            lines = p.text.splitlines()
            counts.update(
                {_line_key(line) for i, line in enumerate(lines) if _is_edge(i, len(lines))} - {""}
            )
        threshold = max(3, int(len(pages) * _BOILERPLATE_PAGE_SHARE))
        repeated = {key for key, n in counts.items() if n >= threshold}

    cleaned = []
    for page in pages:
        lines = page.text.splitlines()
        kept = [
            line
            for i, line in enumerate(lines)
            if not (_is_edge(i, len(lines)) and _line_key(line) in repeated)
            and not _TOC_LINE.search(line)
            and not _PAGE_NUMBER.match(line.strip())
        ]
        cleaned.append(Page(page.number, "\n".join(kept).strip()))
    return cleaned


def is_heading(line: str) -> bool:
    """Numbered, short and Title Case. Wrapped numbered list items ("2. A Target Profile
    specifies the desired...") match the numbering pattern but fail the Title Case test."""
    match = _HEADING.match(line)
    if not match:
        return False
    words = match.group(1).split()
    if len(words) > _MAX_HEADING_WORDS:
        return False
    significant = [w for w in words if w.lower() not in _MINOR_WORDS]
    capitalised = [w for w in significant if w[0].isupper() or not w[0].isalpha()]
    return len(capitalised) >= 0.8 * len(significant)


def find_headings(text: str) -> list[tuple[int, str]]:
    """(character offset, heading text) for each heading-like line."""
    headings = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if is_heading(stripped):
            headings.append((offset, stripped))
        offset += len(line)
    return headings


def structured_chunks(
    pages: Sequence[Page],
    *,
    document_id: str,
    title: str,
    chunk_tokens: int,
    overlap_tokens: int,
    tokenizer: str,
) -> list[Chunk]:
    encoding = tiktoken.get_encoding(tokenizer)

    def count(text: str) -> int:
        return len(encoding.encode(text, disallowed_special=()))

    chunks: list[Chunk] = []
    section = ""  # carried across pages until a new heading appears
    for page in remove_boilerplate(pages):
        if not page.text:
            continue
        headings = find_headings(page.text)
        cursor = 0
        for text in split_text(page.text, chunk_tokens, overlap_tokens, length=count):
            start = page.text.find(text[:50], cursor)
            if start >= 0:
                cursor = start
            # The chunk belongs to the last heading that starts before its end.
            end = cursor + len(text)
            for position, heading in headings:
                if position < end:
                    section = heading
            context = f"{title} > {section}" if section else title
            previous = chunks[-1] if chunks else None
            if previous and previous.page == page.number and count(text) < _MIN_CHUNK_TOKENS:
                # A few leftover lines make a poor standalone chunk; attach them instead.
                chunks[-1] = replace(previous, text="\n".join((previous.text, text)))
                continue
            chunks.append(
                Chunk(document_id, index=len(chunks), page=page.number, text=text, context=context)
            )
    return chunks
