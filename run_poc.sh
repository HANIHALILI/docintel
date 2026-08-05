#!/usr/bin/env bash
# XBERG embedded-image -> VLM proof-of-concept (Linux, Docker).
# Brings up the XBERG API server + a mock VLM, sends test documents through
# /extract, then inspects the mock's logs to prove (or disprove) that the
# images embedded in the documents were transmitted to the VLM endpoint.
set -euo pipefail
cd "$(dirname "$0")"

XBERG_URL=${XBERG_URL:-http://localhost:8000}
MOCK_URL=${MOCK_URL:-http://localhost:9090}
CAPTION_URL=${CAPTION_URL:-http://localhost:8080}

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

say "0. Regenerating test documents (stdlib-only, deterministic)"
if command -v python3 >/dev/null; then
  python3 testdata/make_test_files.py
else
  echo "python3 not found on host - using the pre-generated files shipped in testdata/"
fi

say "1. Starting containers (xberg API + mock VLM)"
mkdir -p logs/images
docker compose up -d --build

say "2. Waiting for both services to be healthy"
for url in "$MOCK_URL/health" "$XBERG_URL/health" "$CAPTION_URL/health"; do
  for i in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then echo "OK: $url"; break; fi
    if [ "$i" = 60 ]; then echo "FATAL: $url never became healthy"; docker compose logs; exit 1; fi
    sleep 2
  done
done

# Snapshot the mock request count so this run's traffic is measured cleanly.
BASELINE=$(cat logs/requests.jsonl 2>/dev/null | wc -l)

say "3. Test A: DOCX with embedded PNG -> per-image VLM OCR (images.run_ocr_on_images + ocr.backend=vlm)"
curl -fsS "$XBERG_URL/extract" \
  -F "file=@testdata/sample_with_image.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -F "config=$(cat config/config_image_ocr_vlm.json)" \
  -o logs/response_A_docx_image_ocr.json \
  && echo "response saved to logs/response_A_docx_image_ocr.json"

say "4. Test B: DOCX with embedded PNG -> VLM captioning post-processor (captioning config)"
curl -fsS "$XBERG_URL/extract" \
  -F "file=@testdata/sample_with_image.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -F "config=$(cat config/config_captioning.json)" \
  -o logs/response_B_docx_captioning.json \
  && echo "response saved to logs/response_B_docx_captioning.json"

say "5. Test C: image-only (scanned) PDF -> VLM OCR"
curl -fsS "$XBERG_URL/extract" \
  -F "file=@testdata/sample_scanned.pdf;type=application/pdf" \
  -F "config=$(cat config/config_image_ocr_vlm.json)" \
  -o logs/response_C_pdf_scanned.json \
  && echo "response saved to logs/response_C_pdf_scanned.json"

say "5b. Test D: captioning service (single image, single call) - DOCX: text native, image -> VLM caption"
curl -fsS "$CAPTION_URL/extract" \
  -F "file=@testdata/sample_with_image.docx" \
  -o logs/response_D_docx_captioning_service.json \
  && echo "response saved to logs/response_D_docx_captioning_service.json"

say "5c. Test E: captioning service - scanned PDF: pages -> Tesseract (NOT VLM), embedded image -> VLM caption"
curl -fsS "$CAPTION_URL/extract" \
  -F "file=@testdata/sample_scanned.pdf" \
  -o logs/response_E_pdf_captioning_service.json \
  && echo "response saved to logs/response_E_pdf_captioning_service.json"

sleep 2

say "6. VERDICT - what did the mock VLM actually receive?"
TOTAL=$(cat logs/requests.jsonl 2>/dev/null | wc -l)
NEW=$((TOTAL - BASELINE))
IMAGES_RECEIVED=$(ls logs/images 2>/dev/null | wc -l)
echo "VLM requests during this run : $NEW"
echo "Images captured (all runs)   : $IMAGES_RECEIVED  (decoded copies in logs/images/)"
echo
echo "--- mock VLM summary log (this is the evidence) ---"
cat logs/summary.log 2>/dev/null || echo "(no summary log - no VLM call ever arrived)"
echo
echo "--- fixed mock response visible in extraction output? ---"
for f in logs/response_A_docx_image_ocr.json logs/response_B_docx_captioning.json logs/response_C_pdf_scanned.json \
         logs/response_D_docx_captioning_service.json logs/response_E_pdf_captioning_service.json; do
  n=$(grep -o "MOCK-VLM-FIXED-RESPONSE" "$f" 2>/dev/null | wc -l)
  echo "$f: $n occurrence(s) of the mock response text"
done
echo
echo "--- captioning service: caption fields (should equal the mock text; prompt in summary.log"
echo "    should be the caption prompt 'Write a concise, factual caption...', NOT 'Extract all visible text') ---"
for f in logs/response_D_docx_captioning_service.json logs/response_E_pdf_captioning_service.json; do
  if command -v python3 >/dev/null && [ -f "$f" ]; then
    python3 -c "
import json,sys
d=json.load(open('$f'))
for doc in d.get('documents',[]):
    print('$f'.split('/')[-1], 'method:', doc.get('extraction_method'))
    for im in doc.get('images',[]):
        print('   image p%s#%s %sx%s caption: %r' % (im['page_number'], im['image_index'], im['width'], im['height'], (im['caption'] or '')[:80]))
"
  fi
done
echo
if [ "$NEW" -gt 0 ] && [ "$IMAGES_RECEIVED" -gt 0 ]; then
  echo "RESULT: CONFIRMED - XBERG transmitted embedded image(s) to the VLM endpoint."
  echo "        Compare logs/images/* against testdata/embedded_image.png (same pixels,"
  echo "        possibly re-encoded; check dimensions 400x300)."
else
  echo "RESULT: NOT CONFIRMED - no image reached the mock VLM. See README notes on"
  echo "        feature gates (captioning may be absent from this build) and check"
  echo "        'docker compose logs xberg' for warnings."
fi
echo
echo "Full raw evidence: logs/requests.jsonl (headers + complete bodies, one JSON per line)"
