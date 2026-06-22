import logging
import math
import os
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .rules import get_default_rules, TradeRule
from .calculations import _get_last_completed_candle_close

import config
from core.defensive_engine import DefensiveExceptionManager

class TradeEngine:
    def __init__(self, data_guard=None, cb_observer=None, penalty_box=None, strategy_scorecard=None, postmortem=None, repository=None, rules: Optional[List[TradeRule]] = None):
        self.data_guard = data_guard
        self.cb_observer = cb_observer
        self.penalty_box = penalty_box
        self.strategy_scorecard = strategy_scorecard
        self.postmortem = postmortem
        self.rules = rules if rules is not None else get_default_rules()
        
        if repository is None:
            from .repository import JsonTradeRepository
            self.repository = JsonTradeRepository()
        else:
            self.repository = repository

        self._engine_lock = threading.Lock()

    def add_trade(self, ticker, signal, entry_price, sl, tp, reason, provider, strategy="", indicators=None, is_watch=False,
                  market=None, conviction_score=None, conviction_grade=None, position_size_pct=None, raw_indicators=None, conviction_details=None):
        check_dict = {"ticker": ticker, "signal": signal, "entry_price": entry_price,
                      "sl": sl, "tp": tp, "market": market or ("KRIPTO" if "/" in ticker else "BIST")}
        
        if self.data_guard:
            ok, reason_dg = self.data_guard.validate_signal_output(check_dict)
        else:
            ok, reason_dg = True, ""
            
        if not ok:
            logging.warning(f"[add_trade] DG-06 VETO: {reason_dg}")
            return None

        from .models import Trade
        from pydantic import ValidationError
        
        with self._engine_lock:
            trades = self.repository.load_active_trades()
            trades_len = len(trades)
            
            try:
                trade_obj = Trade(
                    ticker=ticker, signal=signal, entry_price=entry_price, sl=sl, tp=tp,
                    reason=reason, provider=provider, strategy=strategy if strategy else "Unknown",
                    indicators=indicators or {}, is_watch=is_watch, 
                    market=market or ("KRİPTO" if "/" in ticker else "BIST"),
                    conviction_score=conviction_score, conviction_grade=conviction_grade,
                    position_size_pct=position_size_pct, raw_indicators=raw_indicators or {},
                    conviction_details=conviction_details or {},
                    existing_trades_count=trades_len
                )
            except ValidationError as e:
                logging.warning(f"[add_trade] Pydantic VETO: {e}")
                return None

            new_trade = trade_obj.model_dump(exclude_none=False)
            trades.append(new_trade)
            self.repository.save_active_trades(trades)
            
        return new_trade

    def _format_close_message(self, t, current_price, signal, close_type):
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

    def _stamp_exit_data(self, trade, current_price):
        trade["exit_price"] = current_price
        trade["exit_time"] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')
        return trade

    def _process_active_trade_checks(self, t, current_price, check_price, profit_pct_wick, profit_pct_body, signal, tp, sl, strategy_name, is_watch, notifications):
        for rule in self.rules:
            result = rule.evaluate(
                t, current_price, check_price, profit_pct_wick, profit_pct_body,
                signal, tp, sl, strategy_name, is_watch
            )
            t = result.updated_trade
            if result.notifications:
                notifications.extend(result.notifications)

            if result.should_close:
                exit_price = result.exit_price if result.exit_price is not None else current_price
                self._stamp_exit_data(t, exit_price)
                reason = result.close_reason or "SL"
                t["status"] = result.status_override or f"CLOSED_{reason}"
                
                if not is_watch and reason in ["TP", "SL"]:
                    close_msg = self._format_close_message(t, exit_price, signal, reason)
                    notifications.append(close_msg)
                return True
        return False

    def _cb_on_trade_closed_helper(self, status, ticker_ct, strategy_ct, pnl_pct, hold_hours, entry_time_ct, ct, rr_achieved, cb_notifications):
        is_win = pnl_pct > 0.05
        is_be = -0.05 <= pnl_pct <= 0.05
        is_loss = pnl_pct < -0.05

        if ("SL" in status and is_loss) or "BLACK_SWAN" in status:
            if self.cb_observer:
                self.cb_observer.on_trade_closed({
                    "ticker": ticker_ct,
                    "strategy": strategy_ct,
                    "pnl_percent": pnl_pct if pnl_pct != 0 else -0.01
                })
            
            if self.penalty_box:
                penalty_msg = self.penalty_box.record_asset_sl(ticker_ct)
                if penalty_msg:
                    cb_notifications.append(penalty_msg)
            
            if strategy_ct and self.strategy_scorecard:
                self.strategy_scorecard.record_trade_result(strategy_ct, {
                    "ticker": ticker_ct,
                    "outcome": "SL",
                    "pnl_pct": pnl_pct,
                    "hold_hours": hold_hours,
                    "entry_time": entry_time_ct,
                    "exit_time": ct.get("exit_time", ""),
                    "rr_achieved": round(rr_achieved, 2),
                })
                
        elif "SL" in status and is_be:
            if self.cb_observer:
                self.cb_observer.on_trade_closed({
                    "ticker": ticker_ct,
                    "strategy": strategy_ct,
                    "pnl_percent": 0.0
                })
            
            if strategy_ct and self.strategy_scorecard:
                self.strategy_scorecard.record_trade_result(strategy_ct, {
                    "ticker": ticker_ct,
                    "outcome": "MANUAL",
                    "pnl_pct": pnl_pct,
                    "hold_hours": hold_hours,
                    "entry_time": entry_time_ct,
                    "exit_time": ct.get("exit_time", ""),
                    "rr_achieved": round(rr_achieved, 2),
                })
            
        elif "TP" in status or ("SL" in status and is_win):
            if self.cb_observer:
                self.cb_observer.on_trade_closed({
                    "ticker": ticker_ct,
                    "strategy": strategy_ct,
                    "pnl_percent": pnl_pct if pnl_pct != 0 else 0.01
                })
            
            if self.penalty_box:
                penalty_msg = self.penalty_box.record_asset_tp(ticker_ct)
                if penalty_msg:
                    cb_notifications.append(penalty_msg)
                
            if strategy_ct and self.strategy_scorecard:
                self.strategy_scorecard.record_trade_result(strategy_ct, {
                    "ticker": ticker_ct,
                    "outcome": "TP",
                    "pnl_pct": pnl_pct,
                    "hold_hours": hold_hours,
                    "entry_time": entry_time_ct,
                    "exit_time": ct.get("exit_time", ""),
                    "rr_achieved": round(rr_achieved, 2),
                })
        else:
            if strategy_ct and self.strategy_scorecard:
                self.strategy_scorecard.record_trade_result(strategy_ct, {
                    "ticker": ticker_ct,
                    "outcome": "MANUAL",
                    "pnl_pct": pnl_pct,
                    "hold_hours": hold_hours,
                    "entry_time": entry_time_ct,
                    "exit_time": ct.get("exit_time", ""),
                    "rr_achieved": round(rr_achieved, 2),
                })

    def _handle_closed_trade_accounting(self, closed_trades, notifications):
        self.repository.archive_closed_trades(closed_trades)
        
        try:
            for ct in closed_trades:
                if self.postmortem:
                    self.postmortem.generate_postmortem(ct)
        except Exception as e:
            import logging
            logging.error(f"[_handle_closed_trade_accounting] Postmortem generation failed: {e}")

        cb_notifications = []
        
        def _cb_listener(msg):
            if msg:
                cb_notifications.append(msg)
                
        if self.cb_observer:
            self.cb_observer.subscribe(_cb_listener)
            
        try:
            for ct in closed_trades:
                status = ct.get("status", "")
                ticker_ct = ct.get("ticker", "?")
                strategy_ct = ct.get("strategy", "")
                entry_price_ct = float(ct.get("entry_price") or 0)
                exit_price_ct = float(ct.get("exit_price") or ct.get("entry_price") or 0)
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
                
                self._cb_on_trade_closed_helper(status, ticker_ct, strategy_ct, pnl_pct, hold_hours, entry_time_ct, ct, rr_achieved, cb_notifications)
        finally:
            if self.cb_observer:
                self.cb_observer.unsubscribe(_cb_listener)
            
        if cb_notifications:
            notifications.extend(cb_notifications)

    def check_active_trades(self, current_prices_dict):
        """
        current_prices_dict: {"BTC/USDT": 65000.5, "ETH/USDT": 3000.2}
        """
        with self._engine_lock:
            trades = self.repository.load_active_trades()
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

                closed = self._process_active_trade_checks(t, current_price, check_price, profit_pct_wick, profit_pct_body, signal, tp, sl, strategy_name, is_watch, notifications)
                if closed:
                    closed_trades.append(t)
                else:
                    active_trades.append(t)

            missing_tickers = [t.get("ticker") for t in trades
                               if isinstance(t, dict) and t.get("status") == "ACTIVE" and t.get("ticker") not in current_prices_dict and t.get("ticker")]
            if missing_tickers:
                notifications.append(
                    f"⚠️ <b>FİYAT EKSİK — İZLENEMEYEN POZİSYONLAR</b>\n"
                    f"Şu varlıkların fiyatı çekilemedi:\n"
                    f"<code>{', '.join(missing_tickers)}</code>\n"
                    f"Bu pozisyonlar ŞU AN kontrol edilemiyor!"
                )

            if closed_trades:
                self._handle_closed_trade_accounting(closed_trades, notifications)

            self.repository.save_active_trades(active_trades)
            return notifications
