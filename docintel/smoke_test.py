"""Phase 1 smoke test — fast parse lane + async VLM lane, against the mock.

Runs the whole pipeline directly (no HTTP server), pointing the VLM lane at the
mock endpoint. Verifies: text extracted, image bytes present, description filled
by the VLM, and that a second identical image is served from cache (one call for
two identical images).

    # mock running on the host (docker compose up -d mock-vlm) -> localhost:9090
    VLM_BASE_URL=http://localhost:9090/v1 VLM_API_KEY=mock \
        python -m docintel.smoke_test testdata/sample_with_image.docx
"""

from __future__ import annotations

import asyncio
import sys

from .adapters import build_adapter
from .config import Settings
from .models import VisualItem, VisualKind
from .vlm import Describer


async def main(path: str) -> int:
    with open(path, "rb") as fh:
        data = fh.read()

    settings = Settings.from_env()
    adapter = build_adapter(settings)
    print(f"parser_backend={settings.parser_backend}  adapter={adapter.name}")

    result = await adapter.parse(data, mime="application/octet-stream", filename=path)
    print(f"engine={result.engine}  text={len(result.text)} chars  images={len(result.images)}")
    assert result.text.strip(), "expected non-empty text"
    assert result.images, "expected at least one embedded image"

    if not settings.vlm_enabled:
        print("\nVLM disabled (no VLM_BASE_URL/VLM_API_KEY set) — set them to test the VLM lane.")
        print("PASS (parse-only path).")
        return 0

    describer = Describer(settings)

    # Add a deliberate duplicate of the first image to prove dedup/caching:
    first = result.images[0]
    dup = VisualItem(data=first.data, mime=first.mime, kind=VisualKind.EMBEDDED,
                     width=first.width, height=first.height)
    visuals = [*result.images, dup]

    stats = await describer.run(visuals)
    print(f"\nVLM lane: candidates={stats.candidates} calls={stats.calls} "
          f"cache_hits={stats.cache_hits} skipped={stats.skipped} failed={stats.failed}")
    for v in result.images:
        print(f"  p{v.page} #{v.index} {len(v.data)}B -> caption: {(v.description or '')[:70]!r}")

    assert stats.failed == 0, f"VLM calls failed: {stats.errors}"
    assert any(v.description for v in result.images), "expected at least one description filled"
    assert stats.cache_hits >= 1, "duplicate image should have been served from cache (dedup)"
    assert dup.description == first.description, "duplicate must get the same description"
    print("\nPASS — parse + parallel VLM descriptions + dedup/caching all working.")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "testdata/sample_with_image.docx"
    raise SystemExit(asyncio.run(main(target)))
