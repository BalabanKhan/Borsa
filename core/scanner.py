import time
import json
import logging
import asyncio
from datetime import datetime, timezone
import tempfile
import os

from data_fetcher import scan_all_markets
from trade_tracker import load_trades, add_trade
from circuit_breaker import is_circuit_open
from penalty_box import is_asset_penalized, is_daily_commission_exceeded, record_trade_commission
from strategy_scorecard import is_strategy_disabled
from quarantine import is_quarantined
from signal_decay import should_block_entry

logger = logging.getLogger("quant_bot.scanner")

class ScannerService:
    COOLDOWN_FILE = "signal_cooldown.json"
    COOLDOWN_SECONDS = 3600

    def __init__(self, notifier):
        self.notifier = notifier
        self.signal_cooldown = self._load_cooldown()

    def _load_cooldown(self):
        if os.path.exists(self.COOLDOWN_FILE):
            try:
                with open(self.COOLDOWN_FILE, 'r') as f:
                    data = json.load(f)
                    return {tuple(k.split("|")): v for k, v in data.items()}
            except Exception as e:
                logger.warning(f"Cooldown yüklenemedi: {e}")
        return {}

    def _save_cooldown(self):
        try:
            data = {f"{k[0]}|{k[1]}": v for k, v in self.signal_cooldown.items()}
            tmp_fd, tmp_path = tempfile.mkstemp(dir='.', suffix='.tmp')
            with os.fdopen(tmp_fd, 'w') as f:
                json.dump(data, f)
            os.replace(tmp_path, self.COOLDOWN_FILE)
        except Exception as e:
            logger.error(f"Cooldown kaydedilemedi: {e}")

    def _cleanup_cooldown(self):
        now = time.time()
        self.signal_cooldown = {k: v for k, v in self.signal_cooldown.items() if now - v < self.COOLDOWN_SECONDS}

    def _save_scan_metrics(self, metrics):
        if not metrics:
            return
        def convert_numpy(obj):
            import numpy as np
            import pandas as pd
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, (np.ndarray, pd.Series)):
                return obj.tolist()
            elif isinstance(obj, pd.DataFrame):
                return obj.to_dict()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        try:
            with open('last_scan_metrics.json', 'w', encoding='utf-8') as f:
                json.dump(metrics, f, ensure_ascii=False, indent=2, default=convert_numpy)
        except Exception as e:
            logger.warning(f"Metrics kaydedilemedi: {e}")

    async def run_scan(self):
        logger.info("Hibrit piyasa taraması başlatılıyor (BIST & Kripto)...")
        self._cleanup_cooldown()

        loop = asyncio.get_event_loop()
        scan_start = time.time()
        signals, scan_metrics = await loop.run_in_executor(None, scan_all_markets)
        logger.info(f"Tarama süresi: {time.time() - scan_start:.1f}s")

        self._save_scan_metrics(scan_metrics)
        import gc
        gc.collect()

        if not signals:
            return

        logger.info(f"Sistem toplam {len(signals)} adet işlem kararı üretti!")

        if is_daily_commission_exceeded():
            logger.warning("Günlük komisyon limiti aşıldı.")
            await self.notifier.send_message("🥊 <b>GÜNLÜK KOMİSYON LİMİTİ AŞILDI</b>\nBugün için tüm yeni sinyal üretimi durduruldu.")
            return

        await self._process_signals(signals)

    async def _process_signals(self, signals):
        for decision in signals:
            ticker = decision.get("ticker", "Bilinmiyor")
            strategy = decision.get("strategy", "")
            
            if self._is_on_cooldown(ticker, strategy): continue
            if self._is_already_active(ticker): continue
            
            if is_circuit_open(ticker, strategy): continue
            if is_asset_penalized(ticker): continue
            if is_strategy_disabled(strategy): continue
            if is_quarantined(ticker): continue

            entry_price, sl_price, tp_price = decision.get("entry_price", 0), decision.get("sl", 0), decision.get("tp", 0)
            
            if entry_price > 0 and sl_price > 0 and tp_price > 0:
                should_block, _ = should_block_entry({
                    "ticker": ticker, "entry_price": entry_price, "sl": sl_price, "tp": tp_price,
                    "signal": decision.get("signal", "AL"), "signal_time": datetime.now(timezone.utc).isoformat(),
                    "market": decision.get("market", "KRİPTO")
                }, entry_price)
                if should_block: continue

            conv_grade = decision.get("conviction_grade", "N/A")
            is_watch = (conv_grade == 'WATCH')

            trade = add_trade(
                ticker=ticker,
                signal=decision.get("signal", "AL"),
                entry_price=entry_price,
                sl=sl_price,
                tp=tp_price,
                reason=decision.get("reason", "Neden belirtilmedi"),
                provider="Algorithm",
                strategy=strategy,
                indicators=decision.get("indicators", {}),
                is_watch=is_watch,
                market=decision.get("market", "KRİPTO"),
                conviction_score=decision.get("conviction_score"),
                conviction_grade=conv_grade,
                position_size_pct=decision.get("position_size_pct", 100),
                raw_indicators=decision.get("raw_indicators", {}),
                conviction_details=decision.get("conviction_details", {})
            )

            if trade is None: continue

            if not is_watch:
                record_trade_commission(ticker)

            if decision.get("is_day_trade"):
                self._mark_as_day_trade(trade["id"])

            msg = self.notifier.format_signal_message(trade)
            
            if is_watch:
                watch_header = '👁️ <b>WATCH LIST</b> — Sadece İzle\n━━━━━━━━━━━━━━━━━━\n'
                await self.notifier.send_message(watch_header + msg, is_watch=True)
            else:
                await self.notifier.send_message(msg)
                self._set_cooldown(ticker, strategy)

    def _is_on_cooldown(self, ticker, strategy):
        key = (ticker, strategy)
        if key in self.signal_cooldown and (time.time() - self.signal_cooldown[key]) < self.COOLDOWN_SECONDS:
            return True
        return False

    def _set_cooldown(self, ticker, strategy):
        self.signal_cooldown[(ticker, strategy)] = time.time()
        self._save_cooldown()

    def _is_already_active(self, ticker):
        trades = load_trades()
        return any(t["ticker"] == ticker and t["status"] == "ACTIVE" for t in trades)

    def _mark_as_day_trade(self, trade_id):
        from trade_tracker import save_trades
        trades = load_trades()
        for t in trades:
            if t.get("id") == trade_id:
                t["is_day_trade"] = True
        save_trades(trades)
