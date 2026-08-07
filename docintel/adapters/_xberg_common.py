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


def apply_ocr_to_config(cfg: dict, options) -> None:
    """Toggle image-OCR in an xberg extraction config dict, in place.

    ON  → xberg OCRs each extracted image and attaches `ocr_result`.
    OFF → images are extracted only; the VLM lane will describe them.
    """
    on = bool(options and options.ocr_images)
    cfg["images"]["run_ocr_on_images"] = on
    if on:
        langs = [part for part in (options.ocr_language or "eng").split("+") if part] or ["eng"]
        cfg["ocr"] = {
            "enabled": True,
            "backend": options.ocr_backend or "tesseract",
            "language": langs,   # xberg joins these with "+" for Tesseract
        }
    else:
        cfg["ocr"] = {"enabled": False}


def extract_ocr_text(raw) -> str | None:
    """Pull recognized text from an xberg `ocr_result`, object or JSON dict."""
    if raw is None:
        return None
    if isinstance(raw, str):
        content = raw
    elif isinstance(raw, dict):
        content = raw.get("content") or raw.get("text")
    else:
        content = getattr(raw, "content", None)
    content = (content or "").strip()
    return content or None
