"""The parser adapter contract.

Every engine (XBERG, Docling, Tika, OCR) is wrapped in a class implementing
`ParserAdapter`. The dispatcher (Phase 3) picks an adapter per file; the rest
of the system only ever sees `ParseResult`. This is the seam that makes the
choice of parser reversible — swap an implementation, not the system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..models import ParseResult


@dataclass(slots=True)
class ParseOptions:
    """Per-call knobs for a parse.

    When `ocr_images` is set, the adapter asks the engine to OCR each extracted
    image (via `ocr_backend`/`ocr_language`) and populate `VisualItem.ocr_text`.
    The VLM lane is then skipped by the caller — images go to OCR, not the VLM.
    """

    ocr_images: bool = False
    ocr_backend: str = "tesseract"   # "tesseract" | "paddle-ocr"
    ocr_language: str = "eng"        # e.g. "eng", "heb+eng" (Tesseract "+"-joined)


@runtime_checkable
class ParserAdapter(Protocol):
    """Turn raw file bytes into a `ParseResult`.

    Implementations must be safe to call concurrently (the service may parse
    several documents at once). They should raise `ParseError` on failure so the
    API layer can translate it into a clean HTTP error.
    """

    name: str

    def supports(self, mime: str, filename: str | None) -> bool:
        """Whether this adapter can handle the given input. Used by the dispatcher."""
        ...

    async def parse(
        self, data: bytes, mime: str, filename: str | None = None, options: ParseOptions | None = None
    ) -> ParseResult:
        """Extract text + visual items. Must not perform any VLM calls."""
        ...


class ParseError(RuntimeError):
    """Raised by an adapter when extraction fails."""
