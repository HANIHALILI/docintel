"""The async VLM lane.

Takes the visual items a parser produced and fills each one's `description`,
in parallel and cheaply. This is the component we own end to end — independent
of any parser's built-in (serial) VLM path.

Cost/latency controls, in order of effect:
  1. Candidate filter  — icons/decorations below `min_pixel_area` are skipped.
  2. Dedup by content  — identical images (same SHA-256) trigger ONE call; the
                          result fans out to every item that shares the hash.
  3. Process cache     — a hash described once is never described again, across
                          requests, for the lifetime of the process.
  4. Bounded fan-out   — a semaphore caps parallel calls so we never flood the
                          endpoint.

A single item's failure is recorded and skipped; it never fails the batch.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..config import Settings
from ..models import VisualItem
from .client import VlmClient, VlmError


@dataclass(slots=True)
class DescribeStats:
    candidates: int = 0      # items that passed the filter
    skipped: int = 0         # items below the area threshold
    calls: int = 0           # actual VLM requests made
    cache_hits: int = 0      # items served from the process cache / in-batch dedup
    failed: int = 0          # items whose VLM call errored
    errors: list[str] = field(default_factory=list)


class Describer:
    def __init__(self, settings: Settings, client: VlmClient | None = None) -> None:
        self._s = settings
        self._client = client
        self._sem = asyncio.Semaphore(settings.concurrency)
        # sha256 -> description, shared across requests for the process lifetime.
        self._cache: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_client(self) -> VlmClient:
        if self._client is not None:
            return self._client
        if not self._s.vlm_base_url:
            raise VlmError("VLM_BASE_URL is not set; cannot make VLM calls")
        self._client = VlmClient(
            model=self._s.vlm_model,
            base_url=self._s.vlm_base_url,
            api_key=self._s.vlm_api_key,
            timeout=self._s.request_timeout,
        )
        return self._client

    def _is_candidate(self, item: VisualItem) -> bool:
        area = item.pixel_area
        # Unknown dimensions pass through (don't silently drop) — matches the
        # spirit of the parser's own gate.
        if area is None:
            return True
        return area >= self._s.min_pixel_area

    async def run(self, items: list[VisualItem]) -> DescribeStats:
        """Fill `description` on every candidate in `items`, in place."""
        stats = DescribeStats()
        if not self._s.vlm_enabled:
            return stats

        candidates = [i for i in items if self._is_candidate(i)]
        stats.skipped = len(items) - len(candidates)
        stats.candidates = len(candidates)
        if not candidates:
            return stats

        await asyncio.gather(*(self._describe_one(item, stats) for item in candidates))
        return stats

    async def _describe_one(self, item: VisualItem, stats: DescribeStats) -> None:
        key = item.sha256

        # Fast path: already known.
        cached = self._cache.get(key)
        if cached is not None:
            item.description = cached
            stats.cache_hits += 1
            return

        # Per-hash lock so concurrent duplicates collapse into one call.
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            if cached is not None:
                item.description = cached
                stats.cache_hits += 1
                return

            try:
                text = await self._call_with_retry(item)
            except VlmError as exc:
                stats.failed += 1
                stats.errors.append(f"{key[:12]}: {exc}")
                return

            text = text.strip()
            self._cache[key] = text
            item.description = text
            stats.calls += 1

    async def _call_with_retry(self, item: VisualItem) -> str:
        client = self._get_client()
        last: Exception | None = None
        for attempt in range(self._s.max_retries):
            try:
                async with self._sem:
                    return await client.describe(item.data, item.mime, self._s.prompt)
            except VlmError as exc:
                last = exc
                if attempt < self._s.max_retries - 1:
                    await asyncio.sleep(0.4 * (2 ** attempt))  # 0.4s, 0.8s, 1.6s…
        raise last or VlmError("VLM call failed")
