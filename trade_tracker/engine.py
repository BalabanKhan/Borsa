import logging
import math
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .repository import (
    load_trades, save_trades, _load_trades_unlocked, _save_trades_unlocked,
    _archive_closed_trades, _trade_file_lock, TRACKER_FILE
)
from .trailing import _update_trailing_stop
from .calculations import (
    _check_scale_out, _check_funding_shield, _check_danger_zone,
    _check_sfp_mfe_time_filter, _check_time_stop, _check_black_swan,
    _get_last_completed_candle_close
)

import config
from data_guard import validate_signal_output
from circuit_breaker import cb_observer
from penalty_box import record_asset_sl, record_asset_tp
from strategy_scorecard import record_trade_result
from core.defensive_engine import DefensiveExceptionManager

def add_trade(ticker, signal, entry_price, sl, tp, reason, provider, strategy="", indicators=None, is_watch=False,
              market=None, conviction_score=None, conviction_grade=None, position_size_pct=None, raw_indicators=None, conviction_details=None):
    check_dict = {"ticker": ticker, "signal": signal, "entry_price": entry_price,
                  "sl": sl, "tp": tp, "market": market or ("KRIPTO" if "/" in ticker else "BIST")}
    ok, reason_dg = validate_signal_output(check_dict)
    if not ok:
        logging.warning(f"[add_trade] DG-06 VETO: {reason_dg}")
        return None

    with _trade_file_lock:
        trades = _load_trades_unlocked()
        trade_id = f"{ticker}_{int(os.path.getmtime(TRACKER_FILE) if os.path.exists(TRACKER_FILE) else 0)}_{len(trades)}"

        trailing_dist = entry_price - sl if signal == "AL" else sl - entry_price
        highest_high = entry_price
        lowest_low = entry_price

        new_trade = {
            "id": trade_id,
            "ticker": ticker,
            "signal": signal,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "reason": reason,
            "provider": provider,
            "strategy": strategy,
            "indicators": indicators or {},
            "status": "ACTIVE",
            "trailing_dist": trailing_dist,
            "highest_high": highest_high,
            "lowest_low": lowest_low,
            "entry_time": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00'),
            "is_watch": is_watch,
            "market": market or ("KRİPTO" if "/" in ticker else "BIST"),
            "conviction_score": conviction_score,
            "conviction_grade": conviction_grade,
            "position_size_pct": position_size_pct,
            "raw_indicators": raw_indicators or {},
            "conviction_details": conviction_details or {}
        }
        trades.append(new_trade)
        _save_trades_unlocked(trades)
    return new_trade

def _format_close_message(t, current_price, signal, close_type):
    """
    Kapanış mesajı üretir.
    close_type: 'TP', 'SL', 'BLACK_SWAN', 'FUNDING'
    """
    ticker = t["ticker"]
    entry_price = float(t["entry_price"])
    strategy_name = t.get("strategy", "Bilinmiyor")
    entry_time_str = t.get("entry_time", "Bilinmiyor")

    duration_str = "Bilinmiyor"
    if entry_time_str != "Bilinmiyor":
        try:
            if '+' in entry_time_str:
                entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
            else:
                entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
            duration = datetime.now(timezone.utc) - entry_dt
            hours, remainder = divmod(int(duration.total_seconds()), 3600)
            minutes = remainder // 60
            if hours >= 24:
                days = hours // 24
                hours = hours % 24
                duration_str = f"{days}g {hours}s {minutes}dk"
            else:
                duration_str = f"{hours}s {minutes}dk"
        except Exception as e:
            DefensiveExceptionManager.swallow_safely(e, "trade_tracker duration_str format parsing", threshold=100)
            duration_str = "Hesaplanamadı"

    if signal == "AL":
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        max_profit_price = float(t.get("highest_high", entry_price))
        max_profit_pct = ((max_profit_price - entry_price) / entry_price) * 100
    else:
        profit_pct = ((entry_price - current_price) / entry_price) * 100
        max_profit_price = float(t.get("lowest_low", entry_price))
        max_profit_pct = ((entry_price - max_profit_price) / entry_price) * 100

    type_map = {
        "TP": ("🎉", "KAR ALINDI (TP)"),
        "SL": ("🛑", "ZARAR KESİLDİ (SL)"),
        "BLACK_SWAN": ("🦢", "KARA KUĞU ÇIKIŞI"),
        "FUNDING": ("🛡️", "FONLAMA KALKANI ÇIKIŞI"),
    }

    if close_type == "SL" and profit_pct > 0:
        icon = "🟢"
        title = "KÂR ALINDI (Trailing)"
    else:
        icon, title = type_map.get(close_type, ("❓", "BİLİNMEYEN ÇIKIŞ"))

    short_tag = " [SHORT]" if signal == "SAT" else ""

    if close_type == "BLACK_SWAN":
        gap_pct = abs((current_price - float(t["sl"])) / max(abs(float(t["sl"])), 1e-8)) * 100
        return (
            f"🚨🚨🚨 <b>KARA KUĞU — ACİL TASFİYE GEREKLİ</b>{short_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Strateji: <i>{strategy_name}</i>\n"
            f"Varlık: <code>{ticker}</code>\n"
            f"Giriş: ${entry_price:.4f}\n"
            f"Anlık Fiyat: ${current_price:.4f}\n"
            f"Stop Seviyesi: ${float(t['sl']):.4f}\n"
            f"⚠️ Stop'un <b>%{gap_pct:.1f}</b> ÖTESİNDE!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>ACİL AKSİYON:</b>\n"
            f"1. Derhal borsayı aç ve bu pozisyonu kapat\n"
            f"2. Diğer açık pozisyonları kontrol et\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Net Zarar: %{profit_pct:.2f} | Süre: {duration_str}"
        )

    return (
        f"{icon} <b>{title}{short_tag}</b>\n"
        f"Strateji: <i>{strategy_name}</i>\n"
        f"Varlık: <code>{ticker}</code>\n"
        f"Giriş: ${entry_price:.4f}\n"
        f"Çıkış: ${current_price:.4f}\n"
        f"Net Kâr: %{profit_pct:.2f}\n"
        f"Maks. Kâr: %{max_profit_pct:.2f}\n"
        f"Süre: {duration_str}\n"
        f"Durum: İşlem kapandı."
    )

def _stamp_exit_data(trade, current_price):
    trade["exit_price"] = current_price
    trade["exit_time"] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')
    return trade

def _process_active_trade_checks(t, current_price, check_price, profit_pct_wick, profit_pct_body, signal, tp, sl, strategy_name, is_watch, notifications):
    t, bs_notifs, is_black_swan = _check_black_swan(t, current_price, signal)
    if not is_watch:
        notifications.extend(bs_notifs)
    if is_black_swan:
        return True

    if not is_watch:
        t, so_notifs = _check_scale_out(t, profit_pct_wick, signal, strategy_name, current_price)
        notifications.extend(so_notifs)

        t, ts_notifs = _update_trailing_stop(t, check_price, profit_pct_body, signal, strategy_name)
        notifications.extend(ts_notifs)

        t, fs_notifs, funding_close = _check_funding_shield(t, current_price, profit_pct_wick, signal)
        notifications.extend(fs_notifs)
        if funding_close:
            _stamp_exit_data(t, current_price)
            return True

        t, dz_notifs = _check_danger_zone(t, check_price, signal)
        notifications.extend(dz_notifs)

        t, sfp_notifs, sfp_close = _check_sfp_mfe_time_filter(t, check_price, profit_pct_body)
        if sfp_close:
            notifications.extend(sfp_notifs)
            _stamp_exit_data(t, check_price)
            return True

        t, time_stop_notifs, time_stop_close = _check_time_stop(t, check_price, profit_pct_body)
        if time_stop_close:
            notifications.extend(time_stop_notifs)
            _stamp_exit_data(t, check_price)
            return True

    sl = float(t["sl"])

    if signal == "AL":
        if current_price >= tp and tp > 0:
            close_msg = _format_close_message(t, current_price, signal, "TP")
            if not is_watch:
                notifications.append(close_msg)
            _stamp_exit_data(t, current_price)
            t["status"] = "CLOSED_TP"
            return True
        elif check_price <= sl:
            close_msg = _format_close_message(t, check_price, signal, "SL")
            if not is_watch:
                notifications.append(close_msg)
            _stamp_exit_data(t, check_price)
            t["status"] = "CLOSED_SL"
            return True

    elif signal == "SAT":
        if current_price <= tp and tp > 0:
            close_msg = _format_close_message(t, current_price, signal, "TP")
            if not is_watch:
                notifications.append(close_msg)
            _stamp_exit_data(t, current_price)
            t["status"] = "CLOSED_TP"
            return True
        elif check_price >= sl:
            close_msg = _format_close_message(t, check_price, signal, "SL")
            if not is_watch:
                notifications.append(close_msg)
            _stamp_exit_data(t, check_price)
            t["status"] = "CLOSED_SL"
            return True

    return False

def _cb_on_trade_closed_helper(status, ticker_ct, strategy_ct, pnl_pct, hold_hours, entry_time_ct, ct, rr_achieved, cb_notifications):
    is_win = pnl_pct > 0.05
    is_be = -0.05 <= pnl_pct <= 0.05
    is_loss = pnl_pct < -0.05

    if ("SL" in status and is_loss) or "BLACK_SWAN" in status:
        cb_observer.on_trade_closed({
            "ticker": ticker_ct,
            "strategy": strategy_ct,
            "pnl_percent": pnl_pct if pnl_pct != 0 else -0.01
        })
        
        penalty_msg = record_asset_sl(ticker_ct)
        if penalty_msg:
            cb_notifications.append(penalty_msg)
        
        if strategy_ct:
            record_trade_result(strategy_ct, {
                "ticker": ticker_ct,
                "outcome": "SL",
                "pnl_pct": pnl_pct,
                "hold_hours": hold_hours,
                "entry_time": entry_time_ct,
                "exit_time": ct.get("exit_time", ""),
                "rr_achieved": round(rr_achieved, 2),
            })
            
    elif "SL" in status and is_be:
        cb_observer.on_trade_closed({
            "ticker": ticker_ct,
            "strategy": strategy_ct,
            "pnl_percent": 0.0
        })
        
        if strategy_ct:
            record_trade_result(strategy_ct, {
                "ticker": ticker_ct,
                "outcome": "MANUAL",
                "pnl_pct": pnl_pct,
                "hold_hours": hold_hours,
                "entry_time": entry_time_ct,
                "exit_time": ct.get("exit_time", ""),
                "rr_achieved": round(rr_achieved, 2),
            })
        
    elif "TP" in status or ("SL" in status and is_win):
        cb_observer.on_trade_closed({
            "ticker": ticker_ct,
            "strategy": strategy_ct,
            "pnl_percent": pnl_pct if pnl_pct != 0 else 0.01
        })
        
        penalty_msg = record_asset_tp(ticker_ct)
        if penalty_msg:
            cb_notifications.append(penalty_msg)
            
        if strategy_ct:
            record_trade_result(strategy_ct, {
                "ticker": ticker_ct,
                "outcome": "TP",
                "pnl_pct": pnl_pct,
                "hold_hours": hold_hours,
                "entry_time": entry_time_ct,
                "exit_time": ct.get("exit_time", ""),
                "rr_achieved": round(rr_achieved, 2),
            })
    else:
        if strategy_ct:
            record_trade_result(strategy_ct, {
                "ticker": ticker_ct,
                "outcome": "MANUAL",
                "pnl_pct": pnl_pct,
                "hold_hours": hold_hours,
                "entry_time": entry_time_ct,
                "exit_time": ct.get("exit_time", ""),
                "rr_achieved": round(rr_achieved, 2),
            })

def _handle_closed_trade_accounting(closed_trades, notifications):
    _archive_closed_trades(closed_trades)
    
    # Generate postmortem for each closed trade
    try:
        from .postmortem import generate_postmortem
        for ct in closed_trades:
            generate_postmortem(ct)
    except Exception as e:
        import logging
        logging.error(f"[_handle_closed_trade_accounting] Postmortem generation failed: {e}")

    cb_notifications = []
    
    def _cb_listener(msg):
        if msg:
            cb_notifications.append(msg)
            
    cb_observer.subscribe(_cb_listener)
    try:
        for ct in closed_trades:
            status = ct.get("status", "")
            ticker_ct = ct.get("ticker", "?")
            strategy_ct = ct.get("strategy", "")
            entry_price_ct = float(ct.get("entry_price", 0))
            exit_price_ct = float(ct.get("exit_price", ct.get("entry_price", 0)))
            signal_ct = ct.get("signal", "AL")
            
            if entry_price_ct > 0 and exit_price_ct > 0:
                pnl_pct = ((exit_price_ct - entry_price_ct) / entry_price_ct) * 100 if signal_ct == "AL" else ((entry_price_ct - exit_price_ct) / entry_price_ct) * 100
            else:
                pnl_pct = 0.0
            
            hold_hours = 0.0
            entry_time_ct = ct.get("entry_time", "")
            if entry_time_ct:
                try:
                    if '+' in entry_time_ct:
                        entry_dt_ct = datetime.strptime(entry_time_ct, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
                    else:
                        entry_dt_ct = datetime.strptime(entry_time_ct, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                    hold_hours = (datetime.now(timezone.utc) - entry_dt_ct).total_seconds() / 3600
                except Exception as e:
                    DefensiveExceptionManager.swallow_safely(e, "trade_tracker hold_hours calculation", threshold=100)
            
            sl_ct = float(ct.get("sl", 0))
            risk_ct = abs(entry_price_ct - sl_ct) if abs(entry_price_ct - sl_ct) > 0 else 1e-8
            rr_achieved = abs(exit_price_ct - entry_price_ct) / risk_ct
            if pnl_pct < 0:
                rr_achieved = -rr_achieved
            
            _cb_on_trade_closed_helper(status, ticker_ct, strategy_ct, pnl_pct, hold_hours, entry_time_ct, ct, rr_achieved, cb_notifications)
    finally:
        cb_observer.unsubscribe(_cb_listener)
        
    if cb_notifications:
        notifications.extend(cb_notifications)

def check_active_trades(current_prices_dict):
    """
    current_prices_dict: {"BTC/USDT": 65000.5, "ETH/USDT": 3000.2} şeklinde güncel fiyat sözlüğü.
    Aktif işlemleri kontrol eder.
    """
    trades = load_trades()
    notifications = []
    active_trades = []
    closed_trades = []

    for t in trades:
        if not isinstance(t, dict):
            logging.error(f"[trade_tracker] Geçersiz trade objesi tipi: {type(t)}")
            continue

        status = t.get("status", "ACTIVE")
        if status != "ACTIVE":
            closed_trades.append(t)
            continue

        ticker = t.get("ticker")
        if not ticker:
            logging.error("[trade_tracker] Ticker bulunamadı, işlem atlanıyor.")
            continue

        if ticker not in current_prices_dict:
            active_trades.append(t)
            continue

        current_price = current_prices_dict[ticker]
        
        t["signal"] = t.get("signal", "AL")
        t["sl"] = float(t.get("sl", 0.0))
        t["tp"] = float(t.get("tp", 0.0))
        
        entry_price = float(t.get("entry_price", 0.0))
        if entry_price <= 0:
            logging.error(f"[trade_tracker] Geçersiz entry_price ({entry_price}) ticker: {ticker}. Güvenlik için 1e-8 olarak atandı.")
            entry_price = 1e-8
        t["entry_price"] = entry_price

        signal = t["signal"]
        tp = t["tp"]
        sl = t["sl"]

        if "trailing_dist" not in t:
            t["trailing_dist"] = entry_price - sl if signal == "AL" else sl - entry_price

        body_close_stop_required = t.get("body_close_stop_required", False)
        timeframe = t.get("timeframe", "4h")

        check_price = current_price
        if body_close_stop_required or getattr(config, "HYBRID_STOP_ENABLED", False):
            completed_close = _get_last_completed_candle_close(ticker, timeframe)
            if completed_close is not None:
                check_price = completed_close

        if signal == "AL":
            profit_pct_wick = ((current_price - entry_price) / entry_price) * 100
            profit_pct_body = ((check_price - entry_price) / entry_price) * 100
        else:
            profit_pct_wick = ((entry_price - current_price) / entry_price) * 100
            profit_pct_body = ((entry_price - check_price) / entry_price) * 100

        is_watch = t.get("is_watch", False)
        strategy_name = t.get("strategy", "")

        closed = _process_active_trade_checks(t, current_price, check_price, profit_pct_wick, profit_pct_body, signal, tp, sl, strategy_name, is_watch, notifications)
        if closed:
            closed_trades.append(t)
        else:
            active_trades.append(t)

    missing_tickers = [t["ticker"] for t in trades
                       if t["status"] == "ACTIVE" and t["ticker"] not in current_prices_dict]
    if missing_tickers:
        notifications.append(
            f"⚠️ <b>FİYAT EKSİK — İZLENEMEYEN POZİSYONLAR</b>\n"
            f"Şu varlıkların fiyatı çekilemedi:\n"
            f"<code>{', '.join(missing_tickers)}</code>\n"
            f"Bu pozisyonlar ŞU AN kontrol edilemiyor!"
        )

    if closed_trades:
        _handle_closed_trade_accounting(closed_trades, notifications)

    save_trades(active_trades)
    return notifications
