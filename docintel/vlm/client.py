"""Minimal OpenAI-compatible vision client.

Sends one image + prompt as a chat-completions request and returns the model's
text. The image travels as a base64 data-URL image part — the standard
multimodal shape, and the single point where the VLM provider is pinned. Point
`base_url` at the mock, a self-hosted vLLM/Ollama, or a cloud endpoint; nothing
else changes.
"""

from __future__ import annotations

import base64

import httpx


class VlmError(RuntimeError):
    """A VLM call failed (network, HTTP status, or malformed response)."""


class VlmClient:
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        # normalize: allow base_url with or without trailing /v1 or /
        self._url = base_url.rstrip("/")
        if not self._url.endswith("/v1"):
            self._url = f"{self._url}/v1"
        self._url = f"{self._url}/chat/completions"
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._timeout = timeout

    async def describe(self, image: bytes, mime: str, prompt: str) -> str:
        b64 = base64.b64encode(image).decode("ascii")
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(self._url, json=payload, headers=self._headers)
                resp.raise_for_status()
                body = resp.json()
            except httpx.HTTPError as exc:
                raise VlmError(f"VLM request failed: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise VlmError(f"VLM returned an unexpected response shape: {body!r}") from exc
