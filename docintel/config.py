"""Runtime configuration, read from environment variables.

Keeping all env access in one place makes the service easy to configure via
docker-compose and easy to test (construct `Settings` directly).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_PROMPT = (
    "Describe this image concisely in one or two sentences: the subject, any "
    "visible text, and key details. If it is a chart or diagram, state what it "
    "shows and the main values. Do not add commentary."
)


@dataclass(slots=True)
class Settings:
    # --- parser backend ---
    parser_backend: str = "inprocess"        # "inprocess" (xberg wheel) | "http" (xberg container)
    xberg_url: str | None = None             # required for http backend, e.g. http://xberg:8000
    # --- VLM endpoint (OpenAI-compatible) ---
    vlm_model: str = "openai/gpt-4o-mini"
    vlm_base_url: str | None = None          # e.g. http://mock-vlm:9090/v1
    vlm_api_key: str | None = None           # falls back to provider env var when None
    # --- async lane behaviour ---
    vlm_enabled: bool = True                 # master switch; auto-off if no base_url and no key
    concurrency: int = 8                     # max parallel VLM calls (semaphore size)
    min_pixel_area: int = 1_000              # skip icons/decorations below this area
    request_timeout: float = 60.0            # seconds per VLM call
    max_retries: int = 3
    prompt: str = _DEFAULT_PROMPT

    @classmethod
    def from_env(cls) -> "Settings":
        # NB: with slots=True, class-level `cls.field` is a slot descriptor, not
        # the default value — so read defaults from a fresh instance instead.
        d = cls()
        base_url = os.environ.get("VLM_BASE_URL") or None
        api_key = os.environ.get("VLM_API_KEY") or None
        enabled = _env_bool("VLM_ENABLED", default=bool(base_url or api_key))
        return cls(
            parser_backend=os.environ.get("PARSER_BACKEND", d.parser_backend),
            xberg_url=os.environ.get("XBERG_URL") or None,
            vlm_model=os.environ.get("VLM_MODEL", d.vlm_model),
            vlm_base_url=base_url,
            vlm_api_key=api_key,
            vlm_enabled=enabled,
            concurrency=int(os.environ.get("VLM_CONCURRENCY", d.concurrency)),
            min_pixel_area=int(os.environ.get("VLM_MIN_PIXEL_AREA", d.min_pixel_area)),
            request_timeout=float(os.environ.get("VLM_TIMEOUT", d.request_timeout)),
            max_retries=int(os.environ.get("VLM_MAX_RETRIES", d.max_retries)),
            prompt=os.environ.get("VLM_PROMPT", d.prompt),
        )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
