"""Public-market context ingestion for the research replay."""

from .context import attach_market_context
from .gaps import audit_time_grid, build_gap_rows
from .normalize import normalize_funding, normalize_instrument, normalize_trade_bars, resample_trade_bars
from .archive import aggregate_trade_rows, archive_trade_url, download_archive_trade_bars
from .okx_public import (
    OKX_CANDLE_LIMIT,
    OKX_FUNDING_LIMIT,
    OKX_MARK_INDEX_LIMIT,
    OKX_PUBLIC_API_ROOT,
    OkxPublicClient,
    OkxPublicError,
    attach_okx_context,
    audit_okx_grid,
    build_causal_indicator_rows,
    fetch_funding_history,
    fetch_history_candles,
    infer_index_id,
)

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
    "resample_trade_bars",
    "OKX_CANDLE_LIMIT",
    "OKX_FUNDING_LIMIT",
    "OKX_MARK_INDEX_LIMIT",
    "OKX_PUBLIC_API_ROOT",
    "OkxPublicClient",
    "OkxPublicError",
    "attach_okx_context",
    "audit_okx_grid",
    "build_causal_indicator_rows",
    "fetch_funding_history",
    "fetch_history_candles",
    "infer_index_id",
]
