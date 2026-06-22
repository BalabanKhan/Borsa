from abc import ABC, abstractmethod
from typing import List, Optional

class RuleResult:
    def __init__(
        self,
        updated_trade: dict,
        notifications: List[str],
        should_close: bool = False,
        exit_price: Optional[float] = None,
        close_reason: str = "",
        status_override: Optional[str] = None
    ):
        self.updated_trade = updated_trade
        self.notifications = notifications
        self.should_close = should_close
        self.exit_price = exit_price
        self.close_reason = close_reason
        self.status_override = status_override

class TradeRule(ABC):
    @abstractmethod
    def evaluate(
        self,
        trade: dict,
        current_price: float,
        check_price: float,
        profit_pct_wick: float,
        profit_pct_body: float,
        signal: str,
        tp: float,
        sl: float,
        strategy_name: str,
        is_watch: bool
    ) -> RuleResult:
        """
        Kuralı değerlendirir ve bir RuleResult döner.
        """
        pass
