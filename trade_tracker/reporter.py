import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from .postmortem import get_postmortems

def generate_ai_daily_report() -> str:
    """
    Generates a structured daily report of postmortems from the last 24 hours.
    Designed to be easily readable by an AI/LLM for analysis.
    """
    try:
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        
        all_postmortems = get_postmortems(limit=100) # Fetch enough to cover the last day
        daily_pm = []
        
        for pm in all_postmortems:
            exit_time_str = pm.get("exit_time", "")
            if exit_time_str:
                fmt = '%Y-%m-%d %H:%M:%S+00:00' if '+' in exit_time_str else '%Y-%m-%d %H:%M'
                try:
                    exit_dt = datetime.strptime(exit_time_str, fmt).replace(tzinfo=timezone.utc)
                    if exit_dt >= yesterday:
                        daily_pm.append(pm)
                except Exception:
                    pass
                    
        if not daily_pm:
            return '{"report_type": "daily_postmortem", "date": "' + now.strftime('%Y-%m-%d') + '", "status": "no_trades_closed"}'

        total_trades = len(daily_pm)
        winning_trades = sum(1 for pm in daily_pm if pm.get("pnl_pct", 0) > 0)
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        total_pnl = sum(pm.get("pnl_pct", 0) for pm in daily_pm)
        
        report_data = {
            "report_type": "daily_postmortem",
            "date": now.strftime('%Y-%m-%d'),
            "summary": {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate_pct": round(win_rate, 2),
                "total_pnl_pct": round(total_pnl, 2)
            },
            "trades": daily_pm
        }
        
        # We format as a tight JSON string, so the AI can parse it cleanly.
        # But we also add a human/AI-readable header for context in Telegram.
        
        header = f"🤖 [AI DAILY REPORT] {now.strftime('%Y-%m-%d')}\n"
        header += f"Parse the following JSON to evaluate today's trading performance:\n\n"
        
        # Compact JSON to save space in Telegram message
        json_str = json.dumps(report_data, ensure_ascii=False, separators=(',', ':'))
        
        # If the JSON is too long for a single Telegram message (limit ~4096 chars), we might need to truncate
        # but for daily trades, it should usually be fine. We'll truncate if it exceeds 3800.
        if len(json_str) > 3800:
            report_data["trades"] = report_data["trades"][-10:] # Keep only the last 10 to save space
            report_data["note"] = "TRUNCATED: Showing only last 10 trades due to length limits."
            json_str = json.dumps(report_data, ensure_ascii=False, separators=(',', ':'))
            
        return header + f"<code>{json_str}</code>"
        
    except Exception as e:
        logging.error(f"[Reporter] Failed to generate AI daily report: {e}")
        return '{"error": "Failed to generate report"}'
