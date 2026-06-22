import abc
import json
import logging
import math
import os
import csv
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from core.defensive_engine import DefensiveStateGuard, DefensiveExceptionManager

import config

TRACKER_FILE = config.ACTIVE_TRADES_FILE
HISTORY_FILE = config.TRADE_HISTORY_FILE
TRADE_JOURNAL_CSV = config.TRADE_JOURNAL_CSV
_trade_file_lock = threading.Lock()

# ==========================================
# Abstract Repository Interface
# ==========================================
class BaseTradeRepository(abc.ABC):
    @abc.abstractmethod
    def load_active_trades(self) -> List[Dict[str, Any]]:
        pass

    @abc.abstractmethod
    def save_active_trades(self, trades: List[Dict[str, Any]]) -> None:
        pass

    @abc.abstractmethod
    def archive_closed_trades(self, closed_trades: List[Dict[str, Any]]) -> None:
        pass

# ==========================================
# In-Memory Repository for Testing
# ==========================================
class InMemoryTradeRepository(BaseTradeRepository):
    def __init__(self):
        self._active_trades = []
        self._history = []

    def load_active_trades(self) -> List[Dict[str, Any]]:
        return list(self._active_trades)

    def save_active_trades(self, trades: List[Dict[str, Any]]) -> None:
        self._active_trades = list(trades)

    def archive_closed_trades(self, closed_trades: List[Dict[str, Any]]) -> None:
        self._history.extend(closed_trades)

# ==========================================
# JSON/CSV File Repository (Production)
# ==========================================
class JsonTradeRepository(BaseTradeRepository):
    def __init__(self):
        self._lock = threading.Lock()

    def _sanitize_for_json(self, obj: Any) -> Any:
        try:
            import numpy as np
            if isinstance(obj, (np.int64, np.int32, np.int16, np.int8, np.integer)):
                return int(obj)
            if isinstance(obj, (np.float64, np.float32, np.float16, np.floating)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return [self._sanitize_for_json(x) for x in obj.tolist()]
        except ImportError:
            pass

        try:
            import pandas as pd
            if isinstance(obj, pd.Timestamp):
                return obj.isoformat()
        except ImportError:
            pass

        if isinstance(obj, dict):
            return {str(k): self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(x) for x in obj]
        elif isinstance(obj, tuple):
            return tuple(self._sanitize_for_json(x) for x in obj)
        return obj

    def load_active_trades(self) -> List[Dict[str, Any]]:
        self._lock.acquire()
        try:
            def _default_trades(): return []
            return DefensiveStateGuard.load_state_safe(TRACKER_FILE, _default_trades)
        finally:
            self._lock.release()

    def save_active_trades(self, trades: List[Dict[str, Any]]) -> None:
        self._lock.acquire()
        try:
            sanitized = self._sanitize_for_json(trades)
            success = DefensiveStateGuard.save_state_atomic(TRACKER_FILE, sanitized)
            if not success:
                logging.error("[trade_tracker] Aktif işlemler kaydedilemedi.")
        finally:
            self._lock.release()

    def archive_closed_trades(self, closed_trades: List[Dict[str, Any]]) -> None:
        month_tag = datetime.now(timezone.utc).strftime('%Y_%m')
        history_file = f"trade_history_{month_tag}.json"
        
        def _default_history() -> List[Dict[str, Any]]:
            return []
            
        history = DefensiveStateGuard.load_state_safe(history_file, _default_history)
        history.extend(closed_trades)
        
        success = DefensiveStateGuard.save_state_atomic(history_file, history)
        if not success:
            logging.error(f"[_archive_closed_trades] Geçmiş işlemler arşivi kaydedilemedi: {history_file}")

        for t in closed_trades:
            self._write_trade_journal_csv(t)

    # ... CSV helpers inside JSON Repo ...
    _CSV_HEADERS = [
        "tarih", "sembol", "market", "strateji", "sinyal", "giris_fiyat",
        "cikis_fiyat", "sl", "tp", "net_pnl_pct", "rr_ratio", "rr_achieved",
        "sure", "sonuc", "entry_time", "exit_time", "is_watch", "indicators",
        "conviction_score", "conviction_grade", "position_size_pct",
        "c_adx", "c_ema_alignment", "c_rsi", "c_rsi_direction", "c_volume_ratio",
        "c_dollar_volume", "c_rr_ratio", "c_engulfing", "c_regime", "c_macro", "c_penalty"
    ]

    def _align_and_migrate_journal_csv(self):
        target_csv = TRADE_JOURNAL_CSV
        if not os.path.exists(target_csv):
            return

        try:
            rows = []
            needs_migration = False
            with open(target_csv, 'r', newline='', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                if headers:
                    if len(headers) < len(self._CSV_HEADERS):
                        needs_migration = True
                        for row in reader:
                            migrated_row = row + [""] * (len(self._CSV_HEADERS) - len(row))
                            rows.append(migrated_row)
            
            if needs_migration:
                with open(target_csv, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(self._CSV_HEADERS)
                    writer.writerows(rows)
        except Exception as e:
            logging.error(f"Journal migrasyonu sırasında hata: {e}")

    def _write_trade_journal_csv(self, trade):
        try:
            self._align_and_migrate_journal_csv()
            target_csv = TRADE_JOURNAL_CSV
            file_exists = os.path.exists(target_csv)

            entry_price = float(trade.get("entry_price", 0))
            exit_price = float(trade.get("exit_price", 0))
            sl = float(trade.get("sl", 0))
            tp = float(trade.get("tp", 0))
            signal = trade.get("signal", "AL")
            status = trade.get("status", "")

            if entry_price > 0 and exit_price > 0:
                if signal == "AL":
                    net_pnl = ((exit_price - entry_price) / entry_price) * 100
                else:
                    net_pnl = ((entry_price - exit_price) / entry_price) * 100
            else:
                net_pnl = 0.0

            risk = abs(entry_price - sl) if abs(entry_price - sl) > 0 else 1e-8
            reward = abs(tp - entry_price)
            rr_planned = round(reward / risk, 2)

            actual_reward = abs(exit_price - entry_price)
            rr_achieved = round(actual_reward / risk, 2) if risk > 0 else 0.0
            if net_pnl < 0:
                rr_achieved = -rr_achieved

            entry_time_str = trade.get("entry_time", "")
            exit_time_str = trade.get("exit_time", datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00'))
            duration_str = "?"
            try:
                if '+' in entry_time_str:
                    entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
                else:
                    entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                if '+' in exit_time_str:
                    exit_dt = datetime.strptime(exit_time_str, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
                else:
                    exit_dt = datetime.now(timezone.utc)
                delta = exit_dt - entry_dt
                hours = int(delta.total_seconds()) // 3600
                mins = (int(delta.total_seconds()) % 3600) // 60
                duration_str = f"{hours}s {mins}dk"
            except Exception as e:
                DefensiveExceptionManager.swallow_safely(e, "trade_tracker duration parsing", threshold=100)

            if "TP" in status: sonuc = "KAZANC"
            elif "SL" in status: sonuc = "KAYIP"
            elif "BLACK_SWAN" in status: sonuc = "KARA_KUGU"
            else: sonuc = status

            # Prepare row
            conv_details = trade.get("conviction_details", {}) or {}
            row = [
                datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                trade.get("ticker", ""),
                trade.get("market", ""),
                trade.get("strategy", ""),
                signal,
                f"{entry_price:.6f}", f"{exit_price:.6f}", f"{sl:.6f}", f"{tp:.6f}",
                f"{net_pnl:.2f}", f"{rr_planned:.2f}", f"{rr_achieved:.2f}",
                duration_str, sonuc, entry_time_str, exit_time_str,
                "TRUE" if trade.get("is_watch", False) else "FALSE",
                str(trade.get("indicators", {})),
                f"{trade.get('conviction_score', '')}",
                str(trade.get('conviction_grade', '')),
                f"{trade.get('position_size_pct', '')}",
                f"{conv_details.get('adx', '')}",
                f"{conv_details.get('ema_alignment', '')}",
                f"{conv_details.get('rsi', '')}",
                f"{conv_details.get('rsi_direction', '')}",
                f"{conv_details.get('volume_ratio', '')}",
                f"{conv_details.get('dollar_volume', '')}",
                f"{conv_details.get('rr_ratio', '')}",
                f"{conv_details.get('engulfing', '')}",
                f"{conv_details.get('regime', '')}",
                f"{conv_details.get('macro', '')}",
                f"{conv_details.get('penalty', '')}",
            ]
            row.extend([""] * (len(self._CSV_HEADERS) - len(row)))

            with open(target_csv, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(self._CSV_HEADERS)
                writer.writerow(row)
        except Exception:
            pass

# Legacy shims (For backward compatibility with parts of code we didn't touch yet)
_global_repo = JsonTradeRepository()

def load_trades():
    return _global_repo.load_active_trades()

def save_trades(trades):
    _global_repo.save_active_trades(trades)

def _archive_closed_trades(closed_trades):
    _global_repo.archive_closed_trades(closed_trades)

def _load_trades_unlocked():
    # Only for backward compat if anyone calls directly
    return _global_repo.load_active_trades()

def _save_trades_unlocked(trades):
    _global_repo.save_active_trades(trades)
