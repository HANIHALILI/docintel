"""Adapter registry.

Concrete adapters are imported lazily so a deployment only pulls in what it
uses: the http backend needs only httpx; the in-process backend needs the xberg
wheel. `build_adapter(settings)` picks one from configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ParseError, ParserAdapter

if TYPE_CHECKING:  # for type checkers only — no runtime import
    from .xberg_adapter import XbergAdapter
    from .xberg_http_adapter import XbergHttpAdapter

__all__ = ["ParserAdapter", "ParseError", "XbergAdapter", "XbergHttpAdapter", "build_adapter"]


def __getattr__(name: str):
    # Lazy attribute access: `from docintel.adapters import XbergAdapter` works
    # but only imports xberg when actually referenced.
    if name == "XbergAdapter":
        from .xberg_adapter import XbergAdapter

        return XbergAdapter
    if name == "XbergHttpAdapter":
        from .xberg_http_adapter import XbergHttpAdapter

        return XbergHttpAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_adapter(settings) -> ParserAdapter:
    """Construct the parser adapter named by `settings.parser_backend`."""
    backend = getattr(settings, "parser_backend", "inprocess")
    if backend == "http":
        if not settings.xberg_url:
            raise RuntimeError("PARSER_BACKEND=http requires XBERG_URL to be set")
        from .xberg_http_adapter import XbergHttpAdapter

        return XbergHttpAdapter(settings.xberg_url)
    if backend == "inprocess":
        from .xberg_adapter import XbergAdapter

        return XbergAdapter()
    raise RuntimeError(f"unknown PARSER_BACKEND: {backend!r} (use 'inprocess' or 'http')")
