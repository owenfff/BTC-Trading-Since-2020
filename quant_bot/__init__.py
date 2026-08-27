"""Exchange-neutral strategy core for the BTC-first research program."""

# The repository keeps research-only Python packages under ``quant/src``.
# Make the checkout runnable with ``python -m quant_bot`` from its root while
# preserving normal installed-package behavior when that path is unavailable.
from pathlib import Path
import sys

_RESEARCH_SRC = Path(__file__).resolve().parents[1] / "quant" / "src"
if _RESEARCH_SRC.is_dir() and str(_RESEARCH_SRC) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_SRC))

from .strategy.base import StrategyInput, StrategySignal

__all__ = ["StrategyInput", "StrategySignal"]
