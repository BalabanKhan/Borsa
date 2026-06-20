import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any

from core.defensive_engine import DefensiveStateGuard

POSTMORTEM_FILE = "trade_postmortems.json"

def generate_postmortem(trade: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generates a postmortem analysis for a closed trade.
    It captures PnL, RR, trade classification, and basic insights.
    """
    try:
        ticker = trade.get("ticker", "UNKNOWN")
        status = trade.get("status", "")
        entry_price = float(trade.get("entry_price", 0))
        exit_price = float(trade.get("exit_price", entry_price))
        sl = float(trade.get("sl", 0))
        tp = float(trade.get("tp", 0))
        signal = trade.get("signal", "AL")
        
        # Determine PnL
        if entry_price > 0 and exit_price > 0:
            if signal == "AL":
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            else:
                pnl_pct = ((entry_price - exit_price) / entry_price) * 100
        else:
            pnl_pct = 0.0

        # Risk / Reward Analysis
        risk = abs(entry_price - sl) if abs(entry_price - sl) > 0 else 1e-8
        reward = abs(tp - entry_price)
        planned_rr = round(reward / risk, 2)
        
        actual_reward = abs(exit_price - entry_price)
        achieved_rr = round(actual_reward / risk, 2)
        if pnl_pct < 0:
            achieved_rr = -achieved_rr

        # Classify the trade
        classification = "Unknown"
        if "TP" in status or pnl_pct > 1.0:
            classification = "Successful Trade"
        elif "SL" in status and pnl_pct > 0:
            classification = "Trailing Stop Win"
        elif "SL" in status and pnl_pct <= 0:
            classification = "Stopped Out"
        elif "BLACK_SWAN" in status:
            classification = "Black Swan Event"
        elif "FUNDING" in status:
            classification = "Funding Shield Exit"

        # Generate Insights
        insights = []
        if achieved_rr < planned_rr and pnl_pct > 0:
            insights.append("Exited before target TP. Verify if trailing stop was too tight or market reversed.")
        if achieved_rr >= planned_rr:
            insights.append("Excellent execution. Target RR achieved or exceeded.")
        if pnl_pct < -2.0:
            insights.append("Significant loss. Review entry conditions, SL placement, and market regime.")
        if trade.get("conviction_score", 0) > 0 and trade.get("conviction_score", 0) < 50 and pnl_pct < 0:
            insights.append("Low conviction entry resulted in a loss. Consider filtering low conviction setups.")
        if "BLACK_SWAN" in status:
            insights.append("Black swan event detected. Ensure risk per trade is strictly capped.")

        # Highest/Lowest metrics
        highest = trade.get("highest_high", entry_price)
        lowest = trade.get("lowest_low", entry_price)
        if signal == "AL":
            max_favorable_excursion = ((highest - entry_price) / entry_price) * 100
            max_adverse_excursion = ((entry_price - lowest) / entry_price) * 100
        else:
            max_favorable_excursion = ((entry_price - lowest) / entry_price) * 100
            max_adverse_excursion = ((highest - entry_price) / entry_price) * 100

        postmortem_data = {
            "trade_id": trade.get("id", f"{ticker}_{datetime.now().timestamp()}"),
            "ticker": ticker,
            "strategy": trade.get("strategy", "Unknown"),
            "entry_time": trade.get("entry_time", ""),
            "exit_time": trade.get("exit_time", datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')),
            "duration": _calculate_duration(trade.get("entry_time"), trade.get("exit_time")),
            "pnl_pct": round(pnl_pct, 2),
            "planned_rr": planned_rr,
            "achieved_rr": achieved_rr,
            "max_favorable_excursion": round(max_favorable_excursion, 2),
            "max_adverse_excursion": round(max_adverse_excursion, 2),
            "classification": classification,
            "insights": insights,
            "market": trade.get("market", "")
        }

        # Save postmortem
        _save_postmortem(postmortem_data)
        
        logging.info(f"[Postmortem] Generated for {ticker} ({classification}). PnL: {pnl_pct:.2f}%")
        return postmortem_data
    except Exception as e:
        logging.error(f"[Postmortem] Error generating postmortem: {e}")
        return {}

def _calculate_duration(entry_time_str: str, exit_time_str: str) -> str:
    try:
        if not entry_time_str: return "?"
        exit_time_str = exit_time_str or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')
        
        fmt_entry = '%Y-%m-%d %H:%M:%S+00:00' if '+' in entry_time_str else '%Y-%m-%d %H:%M'
        entry_dt = datetime.strptime(entry_time_str, fmt_entry).replace(tzinfo=timezone.utc)
        
        fmt_exit = '%Y-%m-%d %H:%M:%S+00:00' if '+' in exit_time_str else '%Y-%m-%d %H:%M'
        exit_dt = datetime.strptime(exit_time_str, fmt_exit).replace(tzinfo=timezone.utc)
        
        delta = exit_dt - entry_dt
        hours = int(delta.total_seconds()) // 3600
        mins = (int(delta.total_seconds()) % 3600) // 60
        return f"{hours}h {mins}m"
    except Exception:
        return "?"

def _save_postmortem(data: Dict[str, Any]):
    def _default_postmortems() -> list:
        return []
    postmortems = DefensiveStateGuard.load_state_safe(POSTMORTEM_FILE, _default_postmortems)
    postmortems.append(data)
    DefensiveStateGuard.save_state_atomic(POSTMORTEM_FILE, postmortems)

def get_postmortems(limit: int = 50) -> list:
    """Returns the most recent postmortems."""
    def _default() -> list:
        return []
    postmortems = DefensiveStateGuard.load_state_safe(POSTMORTEM_FILE, _default)
    return postmortems[-limit:]
