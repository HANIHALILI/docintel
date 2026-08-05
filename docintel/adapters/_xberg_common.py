"""Shared xberg mapping helpers used by both the in-process and HTTP adapters.

Kept in one place so the two adapters can't drift (they previously held separate,
inconsistent copies of the image-kind mapping).
"""

from __future__ import annotations

from ..models import VisualKind

# xberg's ImageKind values (lowercased) we treat as figures rather than plain
# embedded images. xberg's full set: photograph, diagram, chart, drawing,
# textblock, decoration, logo. Only populated when image classification is
# enabled in the extraction config (off by default → everything maps to EMBEDDED).
_FIGURE_KINDS = {"chart", "diagram", "drawing"}


def map_image_kind(raw: str | None) -> VisualKind:
    """Map an xberg `image_kind` string onto our `VisualKind`."""
    return VisualKind.FIGURE if (raw or "").lower() in _FIGURE_KINDS else VisualKind.EMBEDDED
