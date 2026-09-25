"""PDF → per-page text. CPU-bound: call from a worker thread in async code."""

import io
import logging
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from documind.core.errors import InvalidDocumentError
from documind.domain import Page

logger = logging.getLogger(__name__)

_SPACES = re.compile(r"[ \t\xa0]+")  # xa0 = non-breaking space, common in PDFs
_BLANK_LINES = re.compile(r"\n{3,}")


def _normalize(text: str) -> str:
    text = _SPACES.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


@dataclass(frozen=True, slots=True)
class ParsedPdf:
    title: str | None
    pages: list[Page]


def _title(reader: PdfReader) -> str | None:
    try:
        title = reader.metadata.title if reader.metadata else None
    except PdfReadError:
        return None
    return title.strip()[:200] if isinstance(title, str) and title.strip() else None


def parse_pdf(data: bytes, *, max_pages: int) -> ParsedPdf:
    # The PDF spec allows junk before the header, but it must appear within the first 1 KB.
    if b"%PDF-" not in data[:1024]:
        raise InvalidDocumentError("The file is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise InvalidDocumentError("Password-protected PDFs are not supported.")
        if len(reader.pages) > max_pages:
            raise InvalidDocumentError(f"The PDF has more than {max_pages} pages.")
        pages = [
            Page(number=i, text=_normalize(page.extract_text() or ""))
            for i, page in enumerate(reader.pages, start=1)
        ]
        title = _title(reader)
    except PdfReadError as exc:
        logger.info("pdf parse failed", extra={"error": str(exc)})
        raise InvalidDocumentError("The PDF is corrupt or unreadable.") from exc
    if not any(p.text for p in pages):
        raise InvalidDocumentError(
            "No text could be extracted. Scanned (image-only) PDFs are not supported yet."
        )
    return ParsedPdf(title, pages)
