from typing import List
from .base import TradeRule, RuleResult
from .concrete_rules import (
    BlackSwanRule,
    ScaleOutRule,
    TrailingStopRule,
    FundingShieldRule,
    DangerZoneRule,
    SfpTimeFilterRule,
    TimeStopRule,
    TakeProfitRule,
    StopLossRule
)

def get_default_rules() -> List[TradeRule]:
    """
    TradeEngine için varsayılan sıralamada kuralları döner.
    """
    return [
        BlackSwanRule(),
        ScaleOutRule(),
        TrailingStopRule(),
        FundingShieldRule(),
        DangerZoneRule(),
        SfpTimeFilterRule(),
        TimeStopRule(),
        TakeProfitRule(),
        StopLossRule()
    ]
