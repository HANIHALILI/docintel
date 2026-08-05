"""XBERG captioning service — one call: text via native/Tesseract, VLM only for image descriptions.

Built on the xberg 1.0.0rc29 Linux wheel, which (unlike the published Docker
images) is compiled WITH the `captioning` feature. Exposes a single
/extract endpoint compatible in spirit with the official API:

  POST /extract   multipart:  file=<document> [, config=<ExtractionConfig JSON>]

Behavior with the default config:
  * document text        -> native extraction
  * scanned pages        -> Tesseract OCR (no VLM, no cost)
  * embedded images      -> sent to the VLM once each, caption returned in
                            images[i].caption

Environment variables:
  VLM_MODEL       liter-llm model string (default: openai/gpt-4o-mini)
  VLM_BASE_URL    optional endpoint override (e.g. the mock, or a vLLM server)
  VLM_API_KEY     optional; when unset the provider's standard env var is used
                  (e.g. OPENAI_API_KEY), which xberg reads natively
  CAPTION_PROMPT  optional custom captioning prompt
  MIN_IMAGE_AREA  skip images smaller than this many pixels (default 1000)
  OCR_LANGUAGE    Tesseract language(s), comma separated (default eng)
"""

import json
import os
import tempfile

import xberg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

app = FastAPI(title="xberg-captioning-service")


def default_config() -> dict:
    llm = {
        "model": os.environ.get("VLM_MODEL", "openai/gpt-4o-mini"),
        "timeout_secs": 60,
        "max_retries": 3,
    }
    if os.environ.get("VLM_BASE_URL"):
        llm["base_url"] = os.environ["VLM_BASE_URL"]
    if os.environ.get("VLM_API_KEY"):
        llm["api_key"] = os.environ["VLM_API_KEY"]

    captioning = {
        "min_image_area": int(os.environ.get("MIN_IMAGE_AREA", "1000")),
        "llm": llm,
    }
    if os.environ.get("CAPTION_PROMPT"):
        captioning["prompt"] = os.environ["CAPTION_PROMPT"]

    return {
        "use_cache": False,
        # extract embedded images, but do NOT run OCR per image — captioning
        # is the only VLM consumer, so pages/scans never reach the VLM
        "images": {"extract_images": True, "run_ocr_on_images": False},
        "pdf_options": {"extract_images": True},
        # scanned pages fall back to Tesseract (local, free)
        "ocr": {
            "enabled": True,
            "backend": "tesseract",
            "language": os.environ.get("OCR_LANGUAGE", "eng").split(","),
        },
        "captioning": captioning,
    }


def _serialize_image(img) -> dict:
    ocr_text = None
    if getattr(img, "ocr_result", None) is not None:
        ocr_text = getattr(img.ocr_result, "content", None) or str(img.ocr_result)
    return {
        "page_number": img.page_number,
        "image_index": img.image_index,
        "format": img.format,
        "width": img.width,
        "height": img.height,
        "caption": img.caption,
        "ocr_result": ocr_text,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "xberg-captioning", "xberg": getattr(xberg, "__version__", "?")}


@app.post("/extract")
async def extract(file: UploadFile = File(...), config: str | None = Form(None)):
    cfg = default_config()
    if config:
        try:
            override = json.loads(config)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"config field is not valid JSON: {exc}") from exc
        cfg.update(override)  # shallow merge: client sections replace defaults

    suffix = os.path.splitext(file.filename or "upload.bin")[1] or ".bin"
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        result = await xberg.extract(tmp_path, cfg)
    except Exception as exc:  # surface extraction errors as HTTP 500 with detail
        raise HTTPException(500, f"extraction failed: {exc}") from exc
    finally:
        os.unlink(tmp_path)

    docs = []
    for doc in result.results or []:
        docs.append(
            {
                "content": doc.content,
                "mime_type": doc.mime_type,
                "extraction_method": str(doc.extraction_method) if doc.extraction_method else None,
                "images": [_serialize_image(i) for i in (doc.images or [])],
                "warnings": [str(w) for w in (doc.processing_warnings or [])],
                "llm_usage": [str(u) for u in (doc.llm_usage or [])],
            }
        )
    errors = [str(e) for e in (result.errors or [])]
    return {"documents": docs, "errors": errors}
