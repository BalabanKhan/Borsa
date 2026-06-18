import json
import logging
import math
import os
import csv
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from core.defensive_engine import DefensiveStateGuard, DefensiveExceptionManager

TRACKER_FILE = "active_trades.json"
HISTORY_FILE = "trade_history.json"
_trade_file_lock = threading.Lock()

def _load_trades_unlocked() -> List[Dict[str, Any]]:
    """Lock TUTULMADAN çağrılır — caller'ın _trade_file_lock tutması gerekir."""
    def _default_trades() -> List[Dict[str, Any]]:
        return []
    return DefensiveStateGuard.load_state_safe(TRACKER_FILE, _default_trades)

def _sanitize_for_json(obj: Any) -> Any:
    """Recursively converts numpy and pandas types to standard Python types."""
    try:
        import numpy as np
        if isinstance(obj, (np.int64, np.int32, np.int16, np.int8, np.integer)):
            return int(obj)
        if isinstance(obj, (np.float64, np.float32, np.float16, np.floating)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return [_sanitize_for_json(x) for x in obj.tolist()]
    except ImportError:
        pass

    try:
        import pandas as pd
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except ImportError:
        pass

    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(x) for x in obj]
    elif isinstance(obj, tuple):
        return tuple(_sanitize_for_json(x) for x in obj)
    return obj

def _save_trades_unlocked(trades: List[Dict[str, Any]]) -> None:
    """Lock TUTULMADAN çağrılır — caller'ın _trade_file_lock tutması gerekir."""
    sanitized = _sanitize_for_json(trades)
    success = DefensiveStateGuard.save_state_atomic(TRACKER_FILE, sanitized)
    if not success:
        logging.error("[trade_tracker] Aktif işlemler kaydedilemedi (DefensiveStateGuard başarısız).")

def load_trades():
    """Thread-safe: Aktif işlemleri JSON dosyasından yükle."""
    _trade_file_lock.acquire()
    try:
        return _load_trades_unlocked()
    finally:
        _trade_file_lock.release()

def save_trades(trades):
    """Crash-safe atomic write: önce temp dosyaya yaz, sonra atomik replace."""
    _trade_file_lock.acquire()
    try:
        _save_trades_unlocked(trades)
    finally:
        _trade_file_lock.release()

def _archive_closed_trades(closed_trades: List[Dict[str, Any]]) -> None:
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
        _write_trade_journal_csv(t)

TRADE_JOURNAL_CSV = "trade_journal.csv"
_CSV_HEADERS = [
    "tarih", "sembol", "market", "strateji", "sinyal", "giris_fiyat",
    "cikis_fiyat", "sl", "tp", "net_pnl_pct", "rr_ratio", "rr_achieved",
    "sure", "sonuc", "entry_time", "exit_time", "is_watch", "indicators",
    "conviction_score", "conviction_grade", "position_size_pct",
    "c_adx", "c_ema_alignment", "c_rsi", "c_rsi_direction", "c_volume_ratio",
    "c_dollar_volume", "c_rr_ratio", "c_engulfing", "c_regime", "c_macro", "c_penalty"
]

def _align_and_migrate_journal_csv():
    """
    Eğer trade_journal.csv zaten varsa ve eski sütun sayısına sahipse,
    verileri bozmamak için eski satırları yeni sütunlarla hizalar ve dosyayı günceller.
    """
    import trade_tracker
    target_csv = trade_tracker.TRADE_JOURNAL_CSV
    if not os.path.exists(target_csv):
        return

    try:
        rows = []
        needs_migration = False
        with open(target_csv, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if headers:
                if len(headers) < len(_CSV_HEADERS):
                    needs_migration = True
                    for row in reader:
                        migrated_row = row + [""] * (len(_CSV_HEADERS) - len(row))
                        rows.append(migrated_row)
        
        if needs_migration:
            with open(target_csv, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(_CSV_HEADERS)
                writer.writerows(rows)
            logging.info(f"[FM-05 Journal] {target_csv} yeni sütun yapısına başarıyla migrate edildi.")
    except Exception as e:
        logging.error(f"[FM-05 Journal] Journal migrasyonu sırasında hata: {e}")

def _write_trade_journal_csv(trade):
    """FM-05: Kapanan işlemi trade_journal.csv'ye satır olarak yaz."""
    try:
        import trade_tracker
        trade_tracker._align_and_migrate_journal_csv()

        target_csv = trade_tracker.TRADE_JOURNAL_CSV
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
            DefensiveExceptionManager.swallow_safely(e, "trade_tracker history exit duration parsing", threshold=100)

        if "TP" in status:
            sonuc = "KAZANC"
        elif "SL" in status:
            sonuc = "KAYIP"
        elif "BLACK_SWAN" in status:
            sonuc = "KARA_KUGU"
        else:
            sonuc = status

        indicators = trade.get("indicators", {})
        raw_inds = trade.get("raw_indicators", {})
        merged_inds = {}
        if isinstance(indicators, dict): merged_inds.update(indicators)
        if isinstance(raw_inds, dict): merged_inds.update(raw_inds)
        
        if merged_inds:
            ind_str = " | ".join(f"{k}:{v}" for k, v in merged_inds.items())
        elif isinstance(indicators, str):
            ind_str = indicators
        else:
            ind_str = "N/A"

        conv_score = trade.get("conviction_score")
        conv_grade = trade.get("conviction_grade", "")
        pos_size_pct = trade.get("position_size_pct")
        c_details = trade.get("conviction_details", {})
        if not isinstance(c_details, dict):
            c_details = {}

        row = [
            datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            trade.get("ticker", ""),
            trade.get("market", ""),
            trade.get("strategy", ""),
            signal,
            f"{entry_price:.6f}",
            f"{exit_price:.6f}",
            f"{sl:.6f}",
            f"{tp:.6f}",
            f"{net_pnl:.2f}",
            f"{rr_planned:.2f}",
            f"{rr_achieved:.2f}",
            duration_str,
            sonuc,
            entry_time_str,
            exit_time_str,
            "TRUE" if trade.get("is_watch", False) else "FALSE",
            ind_str,
            f"{conv_score:.1f}" if conv_score is not None else "",
            str(conv_grade),
            f"{pos_size_pct:.1f}" if pos_size_pct is not None else "",
            f"{c_details.get('adx', 0):.1f}",
            f"{c_details.get('ema_alignment', 0):.1f}",
            f"{c_details.get('rsi', 0):.1f}",
            f"{c_details.get('rsi_direction', 0):.1f}",
            f"{c_details.get('volume_ratio', 0):.1f}",
            f"{c_details.get('dollar_volume', 0):.1f}",
            f"{c_details.get('rr_ratio', 0):.1f}",
            f"{c_details.get('engulfing', 0):.1f}",
            f"{c_details.get('regime', 0):.1f}",
            f"{c_details.get('macro', 0):.1f}",
            f"{c_details.get('penalty', 0):.1f}"
        ]

        with open(target_csv, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(_CSV_HEADERS)
            writer.writerow(row)

        logging.info(f"[FM-05 Journal] {trade.get('ticker')} → {sonuc} ({net_pnl:+.2f}%) CSV'ye yazıldı.")
    except Exception as e:
        logging.warning(f"[FM-05 Journal] CSV yazma hatası: {e}")

def get_learning_context(limit=5):
    """
    Kapanan başarılı (PnL > 0) ve başarısız (PnL <= 0) işlemleri döndürür.
    """
    import glob
    history = []
    history_files = sorted(glob.glob("trade_history*.json"))
    for hf in history_files:
        try:
            with open(hf, 'r', encoding='utf-8') as f:
                history.extend(json.load(f))
        except Exception as e:
            logging.warning(f"[get_learning_context] {hf} okuma hatası: {e}")

    successful = []
    failed = []
    
    for t in history:
        entry_price = float(t.get("entry_price", 0))
        exit_price = float(t.get("exit_price", 0))
        signal = t.get("signal", "AL")
        
        if entry_price > 0 and exit_price > 0:
            if signal == "AL":
                pnl = ((exit_price - entry_price) / entry_price) * 100
            else:
                pnl = ((entry_price - exit_price) / entry_price) * 100
        else:
            pnl = 0.0
            
        if pnl > 0:
            successful.append(t)
        elif pnl < 0:
            failed.append(t)
        else:
            if "TP" in t.get("status", ""):
                successful.append(t)
            elif "SL" in t.get("status", "") or "BLACK_SWAN" in t.get("status", ""):
                failed.append(t)

    return {
        "successful_trades": successful[-limit:],
        "failed_trades": failed[-limit:]
    }
