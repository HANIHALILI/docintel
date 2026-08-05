"""XBERG-over-HTTP adapter — talks to an `xberg serve` container.

Same contract as the in-process `XbergAdapter`, but instead of importing the
xberg wheel it POSTs the file to the xberg REST API (`/extract`) and maps the
JSON back into a `ParseResult`. This keeps the docintel service thin and lets
xberg run, scale, and version as its own container.

We ask xberg for fast extraction only (text + images), VLM OFF — our own async
lane owns the descriptions. `include_data_base64` makes the REST response carry
each image's bytes as a base64 string (otherwise `data` comes back as a giant
integer array).
"""

from __future__ import annotations

import base64
import json

import httpx

from ..models import BBox, ParseResult, VisualItem, VisualKind
from .base import ParseError

# xberg ImageKind values (lowercased) we treat as figures rather than plain images.
_FIGURE_KINDS = {"chart", "diagram", "drawing"}


def _http_parse_config() -> dict:
    return {
        "use_cache": False,
        "images": {
            "extract_images": True,
            "run_ocr_on_images": False,
            "inject_placeholders": True,
            "include_data_base64": True,   # <-- image bytes returned as base64 over HTTP
        },
        "pdf_options": {"extract_images": True},
        "ocr": {"enabled": False},
    }


def _to_visual(img: dict) -> VisualItem | None:
    if img.get("is_mask"):
        return None
    b64 = img.get("data_base64")
    if not b64:
        return None
    try:
        data = base64.b64decode(b64)
    except (ValueError, TypeError):
        return None
    if not data:
        return None

    fmt = (img.get("format") or "png").lower()
    kind_raw = (img.get("image_kind") or "").lower()
    kind = VisualKind.FIGURE if kind_raw in _FIGURE_KINDS else VisualKind.EMBEDDED

    bb = img.get("bounding_box")
    bbox = None
    if isinstance(bb, dict) and all(k in bb for k in ("x0", "y0", "x1", "y1")):
        bbox = BBox(float(bb["x0"]), float(bb["y0"]), float(bb["x1"]), float(bb["y1"]))

    return VisualItem(
        data=data,
        mime=f"image/{'jpeg' if fmt in ('jpg', 'jpeg') else fmt}",
        kind=kind,
        page=img.get("page_number"),
        index=img.get("image_index"),
        width=img.get("width"),
        height=img.get("height"),
        bbox=bbox,
        cluster_id=str(img["cluster_id"]) if img.get("cluster_id") is not None else None,
    )


class XbergHttpAdapter:
    """Fast extraction via an xberg REST container."""

    name = "xberg-http"

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._url = f"{base_url.rstrip('/')}/extract"
        self._timeout = timeout

    def supports(self, mime: str, filename: str | None) -> bool:
        return True

    async def parse(self, data: bytes, mime: str, filename: str | None = None) -> ParseResult:
        files = {"file": (filename or "upload.bin", data, mime or "application/octet-stream")}
        form = {"config": json.dumps(_http_parse_config())}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(self._url, files=files, data=form)
                resp.raise_for_status()
                body = resp.json()
            except httpx.HTTPError as exc:
                raise ParseError(f"xberg HTTP request failed ({self._url}): {exc}") from exc
            except ValueError as exc:  # non-JSON body
                raise ParseError(f"xberg returned a non-JSON response: {exc}") from exc

        docs = body.get("results") or []
        if not docs:
            errs = "; ".join(str(e) for e in (body.get("errors") or []))
            raise ParseError(errs or "xberg returned no documents")

        doc = docs[0]
        images = [v for img in (doc.get("images") or []) if (v := _to_visual(img)) is not None]

        return ParseResult(
            text=doc.get("content", "") or "",
            images=images,
            regions=[],  # figure-region detection arrives in Phase 3 (layout)
            mime_type=doc.get("mime_type", "text/plain") or "text/plain",
            engine=self.name,
            extraction_method=doc.get("extraction_method"),
            warnings=[str(w) for w in (doc.get("processing_warnings") or [])],
            metadata={"xberg_image_count": len(images), "xberg_url": self._url},
        )
