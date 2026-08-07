"""HTTP surface for the document-intelligence service.

Phase 1: fast parse lane + async VLM lane. `POST /extract` parses (fast), then
fills each visual's description in parallel via the VLM lane, weaves the
descriptions into the text, and returns. The VLM never blocks the parse; when
`VLM_ENABLED` is off the endpoint behaves exactly like Phase 0.
"""

from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from . import __version__
from .adapters import ParseError, build_adapter
from .adapters.base import ParseOptions
from .config import Settings
from .models import ParseResult, VisualItem
from .vlm import Describer
from .vlm.describer import DescribeStats
from .weave import weave_descriptions

app = FastAPI(title="docintel", version=__version__)

_settings = Settings.from_env()
_adapter = build_adapter(_settings)  # inprocess (wheel) or http (container), per env
_describer = Describer(_settings)     # holds the cross-request VLM cache


def _serialize_visual(v: VisualItem) -> dict:
    return {
        "kind": v.kind.value,
        "page": v.page,
        "index": v.index,
        "mime": v.mime,
        "width": v.width,
        "height": v.height,
        "pixel_area": v.pixel_area,
        "bbox": None if v.bbox is None else [v.bbox.x0, v.bbox.y0, v.bbox.x1, v.bbox.y1],
        "size_bytes": len(v.data),
        "sha256": v.sha256,
        "cluster_id": v.cluster_id,
        "description": v.description,
        "ocr_text": v.ocr_text,
    }


def _serialize(result: ParseResult, woven_text: str, stats, image_mode: str) -> dict:
    return {
        "engine": result.engine,
        "extraction_method": result.extraction_method,
        "mime_type": result.mime_type,
        "image_mode": image_mode,
        "text": woven_text,
        "images": [_serialize_visual(v) for v in result.images],
        "regions": [_serialize_visual(v) for v in result.regions],
        "counts": {"images": len(result.images), "regions": len(result.regions)},
        "vlm": {
            "enabled": _settings.vlm_enabled,
            "candidates": stats.candidates,
            "calls": stats.calls,
            "cache_hits": stats.cache_hits,
            "skipped": stats.skipped,
            "failed": stats.failed,
            "errors": stats.errors,
        },
        "warnings": result.warnings,
        "metadata": result.metadata,
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "docintel",
        "version": __version__,
        "parser_backend": _settings.parser_backend,
        "adapter": _adapter.name,
        "image_mode": _settings.image_mode,
        "ocr_backend": _settings.ocr_backend if _settings.image_mode == "ocr" else None,
        "ocr_language": _settings.ocr_language if _settings.image_mode == "ocr" else None,
        "vlm_enabled": _settings.vlm_enabled,
        "vlm_model": _settings.vlm_model if _settings.vlm_enabled and _settings.image_mode == "vlm" else None,
    }


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    image_mode: str | None = Form(None),  # per-request override: "vlm" | "ocr" (default: server setting)
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    mime = file.content_type or "application/octet-stream"

    mode = (image_mode or _settings.image_mode).lower()
    if mode not in ("vlm", "ocr"):
        raise HTTPException(400, f"image_mode must be 'vlm' or 'ocr', got {mode!r}")

    # In OCR mode the engine reads the text in each image during extraction; in
    # VLM mode images come back plain and our async lane describes them.
    options = ParseOptions(
        ocr_images=(mode == "ocr"),
        ocr_backend=_settings.ocr_backend,
        ocr_language=_settings.ocr_language,
    )
    try:
        result = await _adapter.parse(data, mime, file.filename, options)
    except ParseError as exc:
        raise HTTPException(422, str(exc)) from exc

    stats = DescribeStats()
    if mode == "vlm":
        # Async VLM lane — parallel, cached, non-blocking to the parse itself.
        stats = await _describer.run(result.visuals)

    woven = weave_descriptions(result.text, result.visuals)
    return _serialize(result, woven, stats, mode)
