"""Weave VLM descriptions into the extracted text at the image anchors.

xberg injects an image placeholder where each image sat, but the placeholder
format differs by extractor (``![Image 1](embedded:p1_i0)`` for the generic/PDF
path, ``[Image: alt text]`` for the DOCX path, …). Rather than parse a specific
key out of those anchors — brittle and format-dependent — we match anchors with
a tolerant pattern and map them to visuals *by order*: both the anchors and the
`visuals` list are in document order, so the k-th anchor is the k-th visual.

Precise when the counts line up (the common case); when they don't — e.g. an
extractor injected an anchor for an image we filtered out — we fall back to a
trailing description block so nothing is ever mis-attributed.
"""

from __future__ import annotations

import re

from .models import VisualItem

# Matches either the generic markdown anchor `![...](embedded:...)` or the
# office-style `[Image: ...]` placeholder. Kept deliberately narrow.
_ANCHOR_RE = re.compile(r"!\[[^\]]*\]\(embedded:[^)]*\)|\[Image:[^\]]*\]")


def weave_descriptions(text: str, visuals: list[VisualItem]) -> str:
    # `derived_text` is the OCR text or the VLM description, whichever mode ran.
    described = [v for v in visuals if v.derived_text and v.derived_text.strip()]
    if not described:
        return text

    anchors = list(_ANCHOR_RE.finditer(text))
    if len(anchors) == len(described):
        return _insert_at_anchors(text, anchors, described)
    return _append_block(text, described)


def _insert_at_anchors(text: str, anchors: list[re.Match], described: list[VisualItem]) -> str:
    """Insert each description immediately after its anchor, preserving the anchor."""
    out: list[str] = []
    last = 0
    for anchor, v in zip(anchors, described):
        out.append(text[last : anchor.end()])
        out.append(f"\n{v.derived_text.strip()}")
        last = anchor.end()
    out.append(text[last:])
    return "".join(out)


def _append_block(text: str, described: list[VisualItem]) -> str:
    """Fallback: a labelled block of descriptions appended to the document."""
    lines = [text.rstrip(), "", "<!-- image descriptions -->"]
    for v in described:
        loc = f"page {v.page}" if v.page is not None else "document"
        lines.append(f"![{v.kind.value} — {loc}] {v.derived_text.strip()}")
    return "\n".join(lines)
