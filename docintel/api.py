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
from .config import Settings
from .models import ParseResult, VisualItem
from .vlm import Describer

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
    }


def _weave_descriptions(result: ParseResult) -> str:
    """Append visual descriptions after the text so downstream RAG sees them.

    Phase 1 keeps this simple: a labelled block per described visual, appended to
    the document text. Positional in-line weaving (right after each image anchor)
    is a Phase 2 refinement once we track anchor offsets.
    """
    described = [v for v in result.visuals if v.description]
    if not described:
        return result.text
    lines = [result.text.rstrip(), "", "<!-- image descriptions -->"]
    for v in described:
        loc = f"page {v.page}" if v.page is not None else "document"
        lines.append(f"![{v.kind.value} — {loc}] {v.description}")
    return "\n".join(lines)


def _serialize(result: ParseResult, woven_text: str, stats) -> dict:
    return {
        "engine": result.engine,
        "extraction_method": result.extraction_method,
        "mime_type": result.mime_type,
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
        "vlm_enabled": _settings.vlm_enabled,
        "vlm_model": _settings.vlm_model if _settings.vlm_enabled else None,
    }


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    describe: bool | None = Form(None),  # override VLM per request (default: server setting)
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    mime = file.content_type or "application/octet-stream"

    try:
        result = await _adapter.parse(data, mime, file.filename)
    except ParseError as exc:
        raise HTTPException(422, str(exc)) from exc

    # Async VLM lane — parallel, cached, non-blocking to the parse itself.
    from .vlm.describer import DescribeStats

    stats = DescribeStats()
    if describe is not False:
        stats = await _describer.run(result.visuals)

    woven = _weave_descriptions(result)
    return _serialize(result, woven, stats)
