"""docintel — document intelligence service.

Phase 0: adapter contract + XBERG fast-extraction + API. VLM is not wired yet.
"""

from .models import BBox, ParseResult, VisualItem, VisualKind

__all__ = ["ParseResult", "VisualItem", "VisualKind", "BBox"]
__version__ = "0.0.1"
