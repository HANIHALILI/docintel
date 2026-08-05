#!/usr/bin/env python3
"""Mock VLM server for the XBERG embedded-image POC.

A minimal OpenAI-compatible endpoint (POST /v1/chat/completions) built on the
Python standard library only. It is NOT a real model:

  * Every incoming request is logged in full (headers + body) to
    LOG_DIR/requests.jsonl (one JSON record per line).
  * Every image found in the request (data: URL or http URL inside an
    `image_url` content part) is decoded, hashed, measured, and the decoded
    bytes are saved to LOG_DIR/images/reqNNN_imgM.<ext> so you can open the
    exact picture XBERG transmitted.
  * A human-readable summary is appended to LOG_DIR/summary.log and stdout.
  * The response is ALWAYS the same fixed OpenAI-style chat completion,
    regardless of input.

Environment variables:
  PORT     - listen port (default 9090)
  LOG_DIR  - directory for logs and captured images (default /logs)
"""

import base64
import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "9090"))
LOG_DIR = os.environ.get("LOG_DIR", "/logs")
IMAGES_DIR = os.path.join(LOG_DIR, "images")
REQUESTS_LOG = os.path.join(LOG_DIR, "requests.jsonl")
SUMMARY_LOG = os.path.join(LOG_DIR, "summary.log")

FIXED_RESPONSE_TEXT = (
    "MOCK-VLM-FIXED-RESPONSE: a placeholder description returned for every "
    "request; no real model was involved."
)

_lock = threading.Lock()
_request_counter = 0

MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}

DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<b64>.*)$", re.DOTALL)


def _sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    return "application/octet-stream"


def _analyze_images(body_json, req_num):
    """Walk an OpenAI chat request; decode, save, and describe every image part."""
    findings = []
    if not isinstance(body_json, dict):
        return findings
    img_idx = 0
    for m_idx, message in enumerate(body_json.get("messages", [])):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for p_idx, part in enumerate(content):
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            url = (part.get("image_url") or {}).get("url", "")
            record = {
                "message_index": m_idx,
                "part_index": p_idx,
                "transport": None,
                "declared_mime": None,
                "sniffed_mime": None,
                "decoded_bytes": None,
                "sha256": None,
                "saved_as": None,
            }
            match = DATA_URL_RE.match(url)
            if match:
                record["transport"] = "base64 data URL"
                record["declared_mime"] = match.group("mime")
                try:
                    raw = base64.b64decode(match.group("b64"))
                    record["decoded_bytes"] = len(raw)
                    record["sha256"] = hashlib.sha256(raw).hexdigest()
                    record["sniffed_mime"] = _sniff_mime(raw)
                    ext = MIME_TO_EXT.get(record["sniffed_mime"], "bin")
                    fname = f"req{req_num:03d}_img{img_idx}.{ext}"
                    with open(os.path.join(IMAGES_DIR, fname), "wb") as fh:
                        fh.write(raw)
                    record["saved_as"] = f"images/{fname}"
                except Exception as exc:  # noqa: BLE001 - log, never fail the mock
                    record["decode_error"] = str(exc)
            else:
                record["transport"] = "URL reference (not inline)"
                record["url_prefix"] = url[:120]
            findings.append(record)
            img_idx += 1
    return findings


class MockVlmHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MockVLM/1.0"

    def log_message(self, fmt, *args):  # silence default per-line access log
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/", "/v1/health"):
            self._send_json(200, {"status": "ok", "service": "mock-vlm"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        global _request_counter
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b""

        with _lock:
            _request_counter += 1
            req_num = _request_counter

        try:
            body_json = json.loads(raw_body)
            body_parse_error = None
        except Exception as exc:  # noqa: BLE001
            body_json = None
            body_parse_error = str(exc)

        images = _analyze_images(body_json, req_num)

        # Extract the text part(s) of the prompt for the summary.
        prompt_texts = []
        if isinstance(body_json, dict):
            for message in body_json.get("messages", []):
                content = message.get("content")
                if isinstance(content, str):
                    prompt_texts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            prompt_texts.append(part.get("text", ""))

        record = {
            "request_number": req_num,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "method": "POST",
            "path": self.path,
            "headers": dict(self.headers.items()),
            "body": body_json if body_json is not None else base64.b64encode(raw_body).decode(),
            "body_parse_error": body_parse_error,
            "image_analysis": images,
        }
        with _lock:
            with open(REQUESTS_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")

            lines = [
                f"--- request #{req_num}  POST {self.path}  "
                f"({len(raw_body)} bytes, model={body_json.get('model') if isinstance(body_json, dict) else '?'})"
            ]
            for text in prompt_texts:
                lines.append(f"    text part: {text[:100]!r}")
            if images:
                for img in images:
                    if img.get("decoded_bytes") is not None:
                        lines.append(
                            f"    IMAGE RECEIVED: {img['transport']}, "
                            f"declared={img['declared_mime']}, sniffed={img['sniffed_mime']}, "
                            f"{img['decoded_bytes']} bytes, sha256={img['sha256'][:16]}..., "
                            f"saved as {img['saved_as']}"
                        )
                    else:
                        lines.append(f"    IMAGE PART (undecodable): {img}")
            else:
                lines.append("    no image parts in this request")
            summary = "\n".join(lines)
            with open(SUMMARY_LOG, "a", encoding="utf-8") as fh:
                fh.write(summary + "\n")
        print(summary, flush=True)

        self._send_json(
            200,
            {
                "id": f"chatcmpl-mock-{req_num}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body_json.get("model", "mock") if isinstance(body_json, dict) else "mock",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": FIXED_RESPONSE_TEXT},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), MockVlmHandler)
    print(f"mock-vlm listening on :{PORT}, logging to {LOG_DIR}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
