from typing import List, Optional
from .base import TradeRule, RuleResult
from ..trailing import _update_trailing_stop
from ..calculations import (
    _check_scale_out, _check_funding_shield, _check_danger_zone,
    _check_sfp_mfe_time_filter, _check_time_stop, _check_black_swan
)

class BlackSwanRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        updated_trade, notifications, is_black_swan = _check_black_swan(trade, current_price, signal)
        return RuleResult(
            updated_trade=updated_trade,
            notifications=[] if is_watch else notifications,
            should_close=is_black_swan,
            exit_price=current_price if is_black_swan else None,
            close_reason="BLACK_SWAN",
            status_override="CLOSED_SL"  # Black swan treated similarly to emergency SL in calculations/engine logic
        )

class ScaleOutRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        if is_watch:
            return RuleResult(updated_trade=trade, notifications=[])
        updated_trade, notifications = _check_scale_out(trade, profit_pct_wick, signal, strategy_name, current_price)
        return RuleResult(
            updated_trade=updated_trade,
            notifications=notifications,
            should_close=False
        )

class TrailingStopRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        if is_watch:
            return RuleResult(updated_trade=trade, notifications=[])
        updated_trade, notifications = _update_trailing_stop(trade, check_price, profit_pct_body, signal, strategy_name)
        return RuleResult(
            updated_trade=updated_trade,
            notifications=notifications,
            should_close=False
        )

class FundingShieldRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        if is_watch:
            return RuleResult(updated_trade=trade, notifications=[])
        updated_trade, notifications, funding_close = _check_funding_shield(trade, current_price, profit_pct_wick, signal)
        return RuleResult(
            updated_trade=updated_trade,
            notifications=notifications,
            should_close=funding_close,
            exit_price=current_price if funding_close else None,
            close_reason="FUNDING"
        )

class DangerZoneRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        if is_watch:
            return RuleResult(updated_trade=trade, notifications=[])
        updated_trade, notifications = _check_danger_zone(trade, check_price, signal)
        return RuleResult(
            updated_trade=updated_trade,
            notifications=notifications,
            should_close=False
        )

class SfpTimeFilterRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        if is_watch:
            return RuleResult(updated_trade=trade, notifications=[])
        updated_trade, notifications, sfp_close = _check_sfp_mfe_time_filter(trade, check_price, profit_pct_body)
        return RuleResult(
            updated_trade=updated_trade,
            notifications=notifications,
            should_close=sfp_close,
            exit_price=check_price if sfp_close else None,
            close_reason="SL"  # SFP close triggers SL exit accounting
        )

class TimeStopRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        if is_watch:
            return RuleResult(updated_trade=trade, notifications=[])
        updated_trade, notifications, time_stop_close = _check_time_stop(trade, check_price, profit_pct_body)
        return RuleResult(
            updated_trade=updated_trade,
            notifications=notifications,
            should_close=time_stop_close,
            exit_price=check_price if time_stop_close else None,
            close_reason="SL"  # Time stop close triggers SL exit accounting
        )

class TakeProfitRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        should_close = False
        if signal == "AL" and current_price >= tp and tp > 0:
            should_close = True
        elif signal == "SAT" and current_price <= tp and tp > 0:
            should_close = True

        return RuleResult(
            updated_trade=trade,
            notifications=[],
            should_close=should_close,
            exit_price=current_price if should_close else None,
            close_reason="TP",
            status_override="CLOSED_TP"
        )

class StopLossRule(TradeRule):
    def evaluate(
        self, trade: dict, current_price: float, check_price: float,
        profit_pct_wick: float, profit_pct_body: float, signal: str,
        tp: float, sl: float, strategy_name: str, is_watch: bool
    ) -> RuleResult:
        # Dynamically fetch updated sl since previous rules might have updated sl
        current_sl = float(trade.get("sl", sl))
        should_close = False
        if signal == "AL" and check_price <= current_sl:
            should_close = True
        elif signal == "SAT" and check_price >= current_sl:
            should_close = True

        return RuleResult(
            updated_trade=trade,
            notifications=[],
            should_close=should_close,
            exit_price=check_price if should_close else None,
            close_reason="SL",
            status_override="CLOSED_SL"
        )
