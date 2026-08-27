"""Shared strategy interfaces and interpretable behavioral approximations."""

from .base import StrategyInput, StrategySignal
from .distilled_rules import DistilledRuleStrategy
from .imitation_model import HistoricalBehaviorBaseline
from .strategy_state import StrategyState
from .supervised_models import CrossAssetNumpyLogisticStrategy, NumpyDecisionTreeStrategy, NumpyLogisticStrategy, TwoStageCrossAssetStrategy
from .unified_distillation import UNIFIED_MODEL_VERSION, UnifiedDistilledStrategy

__all__ = [
    "StrategyInput",
    "StrategySignal",
    "DistilledRuleStrategy",
    "HistoricalBehaviorBaseline",
    "StrategyState",
    "NumpyDecisionTreeStrategy",
    "NumpyLogisticStrategy",
    "CrossAssetNumpyLogisticStrategy",
    "TwoStageCrossAssetStrategy",
    "UNIFIED_MODEL_VERSION",
    "UnifiedDistilledStrategy",
]
