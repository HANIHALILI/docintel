"""XBERG / Kreuzberg adapter — the ONLY file that knows about xberg.

Everything xberg-specific lives here: the config shape, the result field names,
the quirks. If xberg renames a field or a future engine replaces it, this is the
single file that changes. The rest of the system depends on `ParseResult` only.

Phase 0 scope: fast extraction only — text + embedded image bytes + bboxes.
VLM is OFF here by construction (the async VLM lane owns all model calls).
"""

from __future__ import annotations

import xberg

from ..models import BBox, ParseResult, VisualItem
from ._xberg_common import map_image_kind
from .base import ParseError


def _fast_parse_config() -> dict:
    """Config for pure extraction: pull text + images, run NO VLM and NO page OCR.

    Kept as a dict on purpose. Across xberg release-candidates field names have
    churned; a dict degrades gracefully (unknown keys are ignored) where typed
    config objects would break the build.
    """
    return {
        "use_cache": False,
        "images": {
            "extract_images": True,
            "run_ocr_on_images": False,   # no per-image OCR — the VLM lane owns visuals
            "inject_placeholders": True,  # keep image anchors in the markdown for later weaving
        },
        "pdf_options": {"extract_images": True},
        # OCR disabled entirely in Phase 0: no page-level OCR, no VLM.
        "ocr": {"enabled": False},
    }


def _to_bytes(img) -> bytes:
    """Get raw image bytes from an xberg ExtractedImage, however it exposes them."""
    data = getattr(img, "data", None)
    if data:
        return bytes(data)
    b64 = getattr(img, "data_base64", None)
    if b64:
        import base64

        return base64.b64decode(b64)
    return b""


def _to_bbox(img) -> BBox | None:
    raw = getattr(img, "bounding_box", None)
    if raw is None:
        return None
    # Could be an object with x0/y0/x1/y1 or a 4-tuple — handle both.
    try:
        if all(hasattr(raw, a) for a in ("x0", "y0", "x1", "y1")):
            return BBox(float(raw.x0), float(raw.y0), float(raw.x1), float(raw.y1))
        x0, y0, x1, y1 = raw
        return BBox(float(x0), float(y0), float(x1), float(y1))
    except (TypeError, ValueError):
        return None


def _to_visual(img) -> VisualItem | None:
    if getattr(img, "is_mask", False):
        return None
    data = _to_bytes(img)
    if not data:
        return None
    fmt = (getattr(img, "format", None) or "png").lower()
    kind = map_image_kind(getattr(img, "image_kind", None))
    return VisualItem(
        data=data,
        mime=f"image/{'jpeg' if fmt in ('jpg', 'jpeg') else fmt}",
        kind=kind,
        page=getattr(img, "page_number", None),
        index=getattr(img, "image_index", None),
        width=getattr(img, "width", None),
        height=getattr(img, "height", None),
        bbox=_to_bbox(img),
        cluster_id=getattr(img, "cluster_id", None),
    )


class XbergAdapter:
    """Fast, broad-format extraction via the xberg Rust engine."""

    name = "xberg"

    def supports(self, mime: str, filename: str | None) -> bool:
        # Default engine — claims everything. The dispatcher (Phase 3) will
        # route specific mimes/languages elsewhere before falling back to here.
        return True

    async def parse(self, data: bytes, mime: str, filename: str | None = None) -> ParseResult:
        # Feed the bytes straight into xberg — no temp file. A weak/oct-stream
        # mime is dropped so xberg falls back to filename-based detection.
        mime_hint = mime if mime and mime != "application/octet-stream" else None
        inp = xberg.ExtractInput(
            kind="bytes",
            bytes=data,
            mime_type=mime_hint,
            filename=filename,
        )
        try:
            result = await xberg.extract(inp, _fast_parse_config())
        except Exception as exc:  # normalize engine errors to our type
            raise ParseError(f"xberg extraction failed: {exc}") from exc

        docs = list(getattr(result, "results", None) or [])
        if not docs:
            errors = "; ".join(str(e) for e in (getattr(result, "errors", None) or []))
            raise ParseError(errors or "xberg returned no documents")

        doc = docs[0]
        images: list[VisualItem] = []
        for img in getattr(doc, "images", None) or []:
            v = _to_visual(img)
            if v is not None:
                images.append(v)

        return ParseResult(
            text=getattr(doc, "content", "") or "",
            images=images,
            regions=[],  # figure-region detection arrives in Phase 3 (layout)
            mime_type=getattr(doc, "mime_type", "text/plain") or "text/plain",
            engine=self.name,
            extraction_method=str(getattr(doc, "extraction_method", "") or "") or None,
            warnings=[str(w) for w in (getattr(doc, "processing_warnings", None) or [])],
            metadata={"xberg_image_count": len(images)},
        )
