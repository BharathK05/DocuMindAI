"""Recursive character chunking, applied page by page so every chunk has a page for citations.

Same algorithm as LangChain's RecursiveCharacterTextSplitter (the original pipeline): split on
the coarsest separator present (paragraph → line → sentence → word → character) until pieces fit,
then greedily merge pieces into chunks of at most ``chunk_size`` characters, carrying roughly
``overlap`` characters of trailing context into the next chunk. Structure-aware chunking comes in
Phase 2; this is the baseline it will be measured against.
"""

from collections.abc import Sequence

from documind.domain import Chunk, Page

DEFAULT_SEPARATORS = ("\n\n", "\n", ". ", " ", "")


def split_text(
    text: str, chunk_size: int, overlap: int, separators: Sequence[str] = DEFAULT_SEPARATORS
) -> list[str]:
    return _merge(_split(text, chunk_size, separators), chunk_size, overlap)


def _split(text: str, chunk_size: int, separators: Sequence[str]) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text else []
    for i, sep in enumerate(separators):
        if sep == "":
            return [text[j : j + chunk_size] for j in range(0, len(text), chunk_size)]
        if sep in text:
            parts = text.split(sep)
            # Keep the separator attached so merged chunks read naturally.
            parts = [p + sep for p in parts[:-1]] + [parts[-1]]
            pieces: list[str] = []
            for part in parts:
                pieces.extend(_split(part, chunk_size, separators[i + 1 :]))
            return pieces
    return [text]  # unreachable while "" is the last separator


def _merge(pieces: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    window: list[str] = []
    length = 0
    for piece in pieces:
        if window and length + len(piece) > chunk_size:
            chunks.append("".join(window))
            # Slide: drop pieces from the front until what remains fits as overlap.
            while window and (length > overlap or length + len(piece) > chunk_size):
                length -= len(window.pop(0))
        window.append(piece)
        length += len(piece)
    if window:
        chunks.append("".join(window))
    return [c.strip() for c in chunks if c.strip()]


def chunk_pages(
    pages: Sequence[Page], *, document_id: str, chunk_size: int, overlap: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        for text in split_text(page.text, chunk_size, overlap):
            chunks.append(Chunk(document_id, index=len(chunks), page=page.number, text=text))
    return chunks
