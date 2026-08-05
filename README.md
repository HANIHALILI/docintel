# POC: Does XBERG send images embedded inside files to a VLM?

**Answer: YES.** XBERG detects and extracts images embedded inside documents
(PDF, DOCX, PPTX, …) and can forward each extracted image to a Vision Language
Model as a **base64 `data:` URL inside an OpenAI-style `image_url` content
part**, via `POST {base_url}/v1/chat/completions`. This POC proves it against a
mock VLM server that logs every request — no real model is involved.

---

## 1. What XBERG is

[XBERG](https://github.com/xberg-io/xberg) (`ghcr.io/xberg-io/xberg`, PyPI
`xberg`) is a polyglot document-intelligence framework with a Rust core — the
rebranded continuation of **Kreuzberg** (PyPI `kreuzberg`; the `xberg` 0.1.0
PyPI package is a shim that just depends on `kreuzberg`). Latest stable release
at the time of writing: **kreuzberg 4.10.2**; the rename ships as
**xberg 1.0.0-rc.29** (prerelease wheels + Docker images). It extracts text,
metadata, images, and structure from 97+ formats and runs as a library, CLI,
REST API, or MCP server.

All source citations below are pinned to commit
[`22b5033`](https://github.com/xberg-io/xberg/tree/22b5033ad53389d29c5eb6afeb18ab35871cc162)
(= 1.0.0-rc.29).

## 2. How embedded images reach a VLM (from source)

XBERG has **two distinct pipelines** that send *embedded* images to a VLM,
plus two adjacent ones (listed for completeness):

### Path A — per-image VLM OCR (`images.run_ocr_on_images` + `ocr.backend: "vlm"`)

1. The extractor pulls embedded images out of the document when
   `images.extract_images` is on
   ([`ImageExtractionConfig`, types.rs#L379-L448](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/core/config/extraction/types.rs#L379-L448);
   PDFs additionally need `pdf_options.extract_images: true`).
2. The pipeline then runs OCR **on every extracted image** when
   `images.run_ocr_on_images` (default `true`) and an `ocr` config are set
   ([pipeline/mod.rs#L62-L76](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/core/pipeline/mod.rs#L62-L76)).
3. The OCR backend is looked up by name and called per image
   ([image_ocr.rs#L85-L102](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/extraction/image_ocr.rs#L85-L102)).
   With `backend: "vlm"`, that backend is `VlmOcrBackend`
   ([vlm_ocr.rs#L46-L80](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/llm/vlm_ocr.rs#L46-L80)).

### Path B — VLM captioning post-processor (`captioning` config)

When `captioning` is set, a Middle-stage post-processor walks
`ExtractedDocument.images` and calls the VLM once per image (pixel area ≥
`min_image_area`, default 1000), storing the result in each image's `caption`
field
([captioning.rs#L50-L127](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/plugins/processor/builtin/captioning.rs#L50-L127),
[config/captioning.rs#L14-L25](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/core/config/captioning.rs#L14-L25)).

### Adjacent paths (not exercised here)

* **Page-level VLM OCR**: scanned pages are rasterized and OCR'd through the
  same `VlmOcrBackend` when text extraction quality is poor (Test C touches
  this: an image-only PDF).
* **Region VLM extraction / structured vision**: layout-detected figure/table
  regions are cropped and sent to the VLM
  ([region_extractor.rs](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/llm/region_extractor.rs));
  structured extraction has `vision_only`/`text_plus_vision` call modes
  ([config/llm.rs#L120-L128](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/core/config/llm.rs#L120-L128)).

### Wire format (what actually goes over HTTP)

Both paths funnel into one function, `vlm_ocr()`
([vlm_ocr.rs#L105-L147](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/llm/vlm_ocr.rs#L105-L147)):

* image bytes → **base64** → `data:{mime};base64,{b64}` (L114-L115)
* one user message with two content parts: `{"type":"text", ...}` and
  `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}`
  (L121-L132) — i.e. the **OpenAI chat-completions multimodal schema**
* sent through the bundled `liter-llm` client; `LlmConfig.base_url` overrides
  the endpoint and the request lands on `POST {base}/v1/chat/completions`
  with `Authorization: Bearer {api_key}` — asserted by XBERG's own test
  ([client.rs#L49-L115](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/llm/client.rs#L49-L115)).
* Model routing uses liter-llm strings like `openai/gpt-4o-mini`,
  `anthropic/claude-…`
  ([config/llm.rs#L22-L53](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/core/config/llm.rs#L22-L53)).

So a plain **OpenAI-compatible mock server is exactly the right test double.**

## 3. Limitations & version gates (important)

| Concern | Detail |
|---|---|
| `vlm` OCR backend availability | Registered whenever the build has the `liter-llm` feature ([registry/ocr.rs#L110-L117](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/plugins/registry/ocr.rs#L110-L117)). Verified present in the Linux Docker image, and in Windows/Linux wheels of both kreuzberg 4.10.2 and xberg 1.0.0-rc.29 (`list_ocr_backends()` → `['tesseract', 'vlm']`). |
| `captioning` is a Cargo feature gate | The post-processor only exists when built with the `captioning` feature ([builtin/mod.rs#L17-L18, L46-L47](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/plugins/processor/builtin/mod.rs#L17)). The `full` feature set includes it ([Cargo.toml#L622-L656](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/Cargo.toml#L622)), but the `windows-target` wheel set does **not** ([Cargo.toml#L512-L570](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/Cargo.toml#L512)), and the CLI's `all` set (used by the Dockerfiles) does not name it either ([xberg-cli/Cargo.toml#L76-L88](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg-cli/Cargo.toml#L76)). A build without it **silently ignores** the `captioning` config (the field is plain data, always deserializable). Test B tells you empirically whether your image has it; Test A (Path A) does not depend on it. |
| Version gate | `run_ocr_on_images` and `captioning` exist in the 1.0.0-rc line (and captioning-as-config is absent in kreuzberg 4.10.2 — verified: `hasattr(kreuzberg, 'CaptioningConfig') == False`). Use `ghcr.io/xberg-io/xberg` / `pip install --pre xberg==1.0.0rc29`. |
| What happens *without* VLM config | Embedded images are still extracted (bytes/metadata in `ExtractedDocument.images`), OCR'd by Tesseract if OCR is on, or simply carried as data — they are **not** sent anywhere by default. Sending to a VLM is strictly opt-in via `ocr.backend: "vlm"`, `captioning`, or structured-extraction vision modes. |
| Small images are skipped by captioning | `min_image_area` (default 1000 px²) filters icons ([captioning.rs#L146-L154](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/plugins/processor/builtin/captioning.rs#L146)); masks are never sent. |

## 4. POC architecture

```
                 docker network
  ┌──────────────────┐  multipart /extract   ┌──────────────────────┐
  │  test documents  │ ────────────────────► │  xberg-api  :8000    │
  │  DOCX + PDF with │   file + config JSON  │  ghcr.io/xberg-io/…  │
  │  embedded PNG    │                       └─────────┬────────────┘
  └──────────────────┘                                 │ POST /v1/chat/completions
                                                       │ {text part + base64 image part}
                                             ┌─────────▼────────────┐
                                             │  mock-vlm  :9090     │
                                             │  logs EVERYTHING,    │
                                             │  fixed reply always  │
                                             └─────────┬────────────┘
                                                       ▼
                                    logs/requests.jsonl   (full headers+bodies)
                                    logs/summary.log      (human-readable evidence)
                                    logs/images/*.png     (decoded received images)
```

Files:

```
docker-compose.yml               xberg API + mock VLM services
mock-vlm/server.py               stdlib-only OpenAI-compatible mock (fixed response, full logging)
mock-vlm/Dockerfile
testdata/make_test_files.py      stdlib-only generator (deterministic)
testdata/sample_with_image.docx  text + embedded 400x300 PNG (pre-generated)
testdata/sample_scanned.pdf      image-only page, no text layer (pre-generated)
testdata/embedded_image.png      reference copy of the embedded image
config/config_image_ocr_vlm.json Path A config (per-image VLM OCR)
config/config_captioning.json    Path B config (VLM captioning)
run_poc.sh                       end-to-end runner + verdict
```

## 5. Running it (Linux with Docker + Docker Compose v2)

```bash
chmod +x run_poc.sh
./run_poc.sh
```

That's it. The script: regenerates test files (if `python3` exists; otherwise
uses the shipped ones), starts both containers, waits for `/health` on both,
POSTs three requests to `http://localhost:8000/extract`
(multipart `file` + `config` JSON fields, per
[handlers.rs#L198-L239](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg/src/api/handlers.rs#L198-L239)),
then prints the verdict from the mock's logs.

| Test | File | Config | Expectation |
|---|---|---|---|
| A | `sample_with_image.docx` | Path A (`ocr.backend: "vlm"` + `run_ocr_on_images`) | Mock receives the embedded PNG as a base64 data URL; extraction output contains `MOCK-VLM-FIXED-RESPONSE` as the image's OCR text |
| B | `sample_with_image.docx` | Path B (`captioning`) | Same image arrives with the captioning prompt; each image's `caption` = mock text. **If no request arrives, this build lacks the `captioning` feature** (see §3) — Path A is unaffected |
| C | `sample_scanned.pdf` | Path A | The PDF's embedded image (and/or the rasterized page) arrives for OCR |

Manual single command, if you prefer:

```bash
curl -s http://localhost:8000/extract \
  -F "file=@testdata/sample_with_image.docx" \
  -F "config=$(cat config/config_image_ocr_vlm.json)" | head -c 2000
```

Inspect evidence afterwards:

```bash
cat logs/summary.log            # per-request: transport, mime, bytes, sha256
ls  logs/images/                # the exact decoded images the "VLM" received
python3 -m json.tool <(head -1 logs/requests.jsonl) | less   # a full raw request
docker compose down             # cleanup
```

Expected `summary.log` shape for a successful Test A:

```
--- request #1  POST /v1/chat/completions  (nnnnn bytes, model=openai/gpt-4o-mini)
    text part: 'Extract all visible text from this image...'
    IMAGE RECEIVED: base64 data URL, declared=image/png, sniffed=image/png,
    nnnn bytes, sha256=..., saved as images/req001_img0.png
```

The received image should be 400x300 and visually identical to
`testdata/embedded_image.png` (XBERG may re-encode/normalize DPI, so compare
pixels/dimensions rather than the file hash).

## 6. Single-image captioning service (`xberg-service/`)

The published Docker images (official `ghcr.io/xberg-io/xberg` and
`salmastik/xberg:1.0.0-rc.29` — verified by downloading the layer holding the
binary and scanning it for feature-gated strings) are compiled **without** the
`captioning` Cargo feature, so they silently ignore captioning config. Two ways
to get "text via Tesseract, VLM only for image descriptions" in ONE image and
ONE call:

**Option 1 (shipped here, fast): `xberg-service/`** — the Linux Python wheel
of xberg 1.0.0rc29 IS built with `captioning`
([xberg-py/Cargo.toml#L39-L40](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/crates/xberg-py/Cargo.toml#L39)),
so this image wraps it with a thin FastAPI layer exposing `POST /extract`
(multipart `file` + optional `config`). Default behavior: native text,
Tesseract for scanned pages (local, free), one VLM call per embedded image →
`images[i].caption`. Configure via env: `VLM_MODEL`, `VLM_BASE_URL` (omit for
real OpenAI/Anthropic), `VLM_API_KEY` or provider-standard env var,
`CAPTION_PROMPT`, `MIN_IMAGE_AREA`, `OCR_LANGUAGE`. Tests D/E in `run_poc.sh`
verify it against the mock: captions filled, and the prompt seen by the mock is
the *caption* prompt, not the OCR prompt.

**Option 2 (full official REST API, slow build): build from source with the
feature added.** One-line patch to the official Dockerfile:

```bash
git clone --depth 1 --branch v1.0.0-rc.29 https://github.com/xberg-io/xberg
cd xberg
sed -i 's|--features all|--features all --features xberg/captioning|' docker/Dockerfile.full
docker build -f docker/Dockerfile.full -t xberg:full-captioning .
```

Then use `xberg:full-captioning` in place of the official image; the
`config_captioning.json` here works as-is against its `/extract` (set
`ocr.backend` to `tesseract` to keep scans off the VLM). Expect a long Rust
release build (tens of minutes) the first time.

## 7. Assumptions made

* The docs site (docs.xberg.io) blocks automated fetching, so all claims are
  cited from source at commit `22b5033` instead of doc pages.
* `ghcr.io/xberg-io/xberg:latest` serves the API on port 8000 (per
  [Dockerfile.full#L153-L159](https://github.com/xberg-io/xberg/blob/22b5033ad53389d29c5eb6afeb18ab35871cc162/docker/Dockerfile.full#L153))
  and its build includes `liter-llm` (hence the `vlm` OCR backend). Whether it
  includes `captioning` is not provable from the build files alone — Test B
  settles it empirically; the run script's verdict handles both outcomes.
* The mock accepts any POST path, so liter-llm base-URL path normalization
  quirks cannot break the capture.
