"""Public-market context ingestion for the research replay."""

from .context import attach_market_context
from .gaps import audit_time_grid, build_gap_rows
from .normalize import normalize_funding, normalize_instrument, normalize_trade_bars
from .archive import aggregate_trade_rows, archive_trade_url, download_archive_trade_bars

__all__ = [
    "attach_market_context",
    "aggregate_trade_rows",
    "archive_trade_url",
    "audit_time_grid",
    "build_gap_rows",
    "download_archive_trade_bars",
    "normalize_funding",
    "normalize_instrument",
    "normalize_trade_bars",
]
