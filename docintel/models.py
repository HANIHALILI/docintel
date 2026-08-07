"""Core data model — the contract every parser adapter returns.

This module is deliberately parser-agnostic: it knows nothing about XBERG,
Docling, Tika or any other engine. All adapters (see `adapters/`) map their
engine-specific output into these types, so the rest of the system depends on
this contract alone.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class VisualKind(str, Enum):
    """What a visual item is, as far as the pipeline cares."""

    EMBEDDED = "embedded"      # a raster image embedded in the document
    FIGURE = "figure"          # a detected figure/chart region (may be vector-origin)
    PAGE = "page"              # a full-page raster (e.g. a scanned page)
    UNKNOWN = "unknown"


@dataclass(slots=True)
class BBox:
    """Bounding box on a page, in the source engine's coordinate space."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def area(self) -> float:
        return abs((self.x1 - self.x0) * (self.y1 - self.y0))


@dataclass(slots=True)
class VisualItem:
    """One image / figure / region extracted from a document.

    `data` holds the raw encoded bytes (PNG/JPEG/…). `description` starts as
    None and is filled in later by the async VLM lane (Phase 1). Keeping the
    bytes on the item lets the VLM lane run entirely off this model without
    re-parsing the source document.
    """

    data: bytes
    mime: str = "image/png"
    kind: VisualKind = VisualKind.EMBEDDED
    page: int | None = None
    index: int | None = None
    width: int | None = None
    height: int | None = None
    bbox: BBox | None = None
    cluster_id: str | None = None   # groups tiles that form one logical figure
    # Text derived from the image. Exactly one is filled, depending on image mode:
    #   description — from the VLM lane (what the image shows)
    #   ocr_text    — from the OCR backend (the literal text in the image)
    description: str | None = None
    ocr_text: str | None = None

    @property
    def derived_text(self) -> str | None:
        """The text produced for this image, whichever mode ran (OCR or VLM)."""
        return self.ocr_text or self.description

    @property
    def sha256(self) -> str:
        """Content hash — the cache key for the VLM lane (dedup identical images)."""
        return hashlib.sha256(self.data).hexdigest()

    @property
    def pixel_area(self) -> int | None:
        if self.width is None or self.height is None:
            return None
        return self.width * self.height


@dataclass(slots=True)
class ParseResult:
    """The unified output of any parser adapter.

    `images` and `regions` are separated because they come from different
    mechanisms: `images` are rasters actually embedded in the file, while
    `regions` are figure/chart areas found by layout detection (the path that
    covers vector drawings, which have no embedded raster). The VLM lane treats
    both the same way.
    """

    text: str
    images: list[VisualItem] = field(default_factory=list)
    regions: list[VisualItem] = field(default_factory=list)
    mime_type: str = "text/plain"
    engine: str = ""                       # which adapter produced this
    extraction_method: str | None = None   # engine's own label (native/ocr/…)
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def visuals(self) -> list[VisualItem]:
        """All visual items the VLM lane should consider, images + regions."""
        return [*self.images, *self.regions]
