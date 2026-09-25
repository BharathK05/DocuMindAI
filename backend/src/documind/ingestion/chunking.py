"""Recursive chunking, applied page by page so every chunk has a page for citations.

Same algorithm as LangChain's RecursiveCharacterTextSplitter (the original pipeline): split on
the coarsest separator present (paragraph → line → sentence → word → character) until pieces fit,
then greedily merge pieces into chunks of at most ``chunk_size`` units, carrying roughly
``overlap`` units of trailing context into the next chunk. Units are characters by default, or
tokens when a token-counting ``length`` function is passed (used by structured chunking).
"""

from collections.abc import Callable, Sequence

from documind.domain import Chunk, Page

DEFAULT_SEPARATORS = ("\n\n", "\n", ". ", " ", "")

Length = Callable[[str], int]


def split_text(
    text: str,
    chunk_size: int,
    overlap: int,
    separators: Sequence[str] = DEFAULT_SEPARATORS,
    length: Length = len,
) -> list[str]:
    return _merge(_split(text, chunk_size, separators, length), chunk_size, overlap, length)


def _hard_split(text: str, chunk_size: int, length: Length) -> list[str]:
    # Last resort for a single unbreakable run: cut by characters, scaled so each piece is
    # roughly chunk_size units long even when units are tokens.
    chars_per_unit = max(1, len(text) // max(1, length(text)))
    step = max(1, chunk_size * chars_per_unit)
    return [text[j : j + step] for j in range(0, len(text), step)]


def _split(text: str, chunk_size: int, separators: Sequence[str], length: Length) -> list[str]:
    if length(text) <= chunk_size:
        return [text] if text else []
    for i, sep in enumerate(separators):
        if sep == "":
            return _hard_split(text, chunk_size, length)
        if sep in text:
            parts = text.split(sep)
            # Keep the separator attached so merged chunks read naturally.
            parts = [p + sep for p in parts[:-1]] + [parts[-1]]
            pieces: list[str] = []
            for part in parts:
                pieces.extend(_split(part, chunk_size, separators[i + 1 :], length))
            return pieces
    return [text]  # unreachable while "" is the last separator


def _merge(pieces: list[str], chunk_size: int, overlap: int, length: Length) -> list[str]:
    chunks: list[str] = []
    window: list[tuple[str, int]] = []
    total = 0
    for piece in pieces:
        size = length(piece)
        if window and total + size > chunk_size:
            chunks.append("".join(p for p, _ in window))
            # Slide: drop pieces from the front until what remains fits as overlap.
            while window and (total > overlap or total + size > chunk_size):
                total -= window.pop(0)[1]
        window.append((piece, size))
        total += size
    if window:
        chunks.append("".join(p for p, _ in window))
    return [c.strip() for c in chunks if c.strip()]


def chunk_pages(
    pages: Sequence[Page], *, document_id: str, chunk_size: int, overlap: int
) -> list[Chunk]:
    """Baseline strategy: fixed-size character chunks, no structure awareness."""
    chunks: list[Chunk] = []
    for page in pages:
        for text in split_text(page.text, chunk_size, overlap):
            chunks.append(Chunk(document_id, index=len(chunks), page=page.number, text=text))
    return chunks
