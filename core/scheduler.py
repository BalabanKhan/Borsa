import json
import logging
import asyncio
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from trade_tracker import load_trades, check_active_trades, save_trades, _archive_closed_trades
from data_fetcher import get_current_prices
from market_snapshot import send_snapshot_excel
from quarantine import check_staleness, generate_quarantine_alert, is_quarantined, remove_from_quarantine, cleanup_expired_quarantines
from filter_health import check_analysis_paralysis, get_filter_health_summary
from circuit_breaker import get_status_message as cb_status
from penalty_box import get_penalty_status
from strategy_scorecard import get_scorecard_status, run_darwinism, generate_weekly_report
import config

logger = logging.getLogger("quant_bot.scheduler")

class TaskScheduler:
    def __init__(self, scanner, notifier):
        self.scanner = scanner
        self.notifier = notifier
        self.scheduler = AsyncIOScheduler(
            timezone=ZoneInfo("Europe/Istanbul"),
            job_defaults={'misfire_grace_time': 15}
        )
        self._price_fail_count = 0
        self.setup_jobs()

    def setup_jobs(self):
        # Piyasa Taraması (Her 15 Dakika)
        self.scheduler.add_job(self.scanner.run_scan, 'interval', minutes=15, id='market_scan')
        
        # Aktif Pozisyon Fiyat Kontrolü (Her 1 Dakika)
        self.scheduler.add_job(self.check_prices, 'interval', minutes=1, id='check_prices', max_instances=2)
        
        # Başarısız Mesajları Yeniden Gönderme (Her 1 Dakika)
        self.scheduler.add_job(self.notifier.retry_failed_messages, 'interval', minutes=1, id='retry_messages')
        
        # Heartbeat (Her 6 Saat)
        self.scheduler.add_job(self.send_heartbeat, 'interval', hours=6, id='heartbeat')
        
        # Day Trade Otomatik Kapanış (Her gün 17:55)
        self.scheduler.add_job(self.close_day_trades, 'cron', hour=17, minute=55, id='close_day_trades')
        
        # Gün Sonu Excel Snapshot Gönderimi (Her gün 23:00)
        self.scheduler.add_job(self.send_daily_snapshot, 'cron', hour=23, minute=0, id='daily_snapshot')
        
        # Haftalık Darwinizm (Her Pazar 00:00)
        self.scheduler.add_job(self.run_weekly_tasks, 'cron', day_of_week='sun', hour=0, minute=0, id='weekly_tasks')

    def start(self):
        self.scheduler.start()
        logger.info("APScheduler görev yöneticisi başlatıldı.")

    async def check_prices(self):
        trades = load_trades()
        active_trades = [t for t in trades if t["status"] == "ACTIVE"]
        active_tickers = list(set([t["ticker"] for t in active_trades]))
        
        if not active_tickers:
            return

        current_prices = get_current_prices(active_tickers)
        if current_prices:
            self._price_fail_count = 0
            await self._process_active_prices(active_trades, current_prices)
        else:
            self._price_fail_count += 1
            if self._price_fail_count >= 3:
                await self.notifier.send_message(
                    f"🔴 <b>FİYAT ÇEKİLEMİYOR</b>\nSon {self._price_fail_count} denemede veri alınamadı.",
                    is_system=True
                )
                self._price_fail_count = -15 # Cooldown

    async def _process_active_prices(self, active_trades, current_prices):
        for t in active_trades:
            ticker = t["ticker"]
            if ticker in current_prices:
                if is_quarantined(ticker):
                    remove_from_quarantine(ticker)
            else:
                q_report = check_staleness(t)
                if q_report:
                    await self.notifier.send_message(generate_quarantine_alert(q_report), is_system=True)

        loop = asyncio.get_event_loop()
        notifications = await loop.run_in_executor(None, check_active_trades, current_prices)
        for msg in notifications:
            await self.notifier.send_message(msg, is_system=True)

    async def close_day_trades(self):
        trades = load_trades()
        day_trades = [t for t in trades if t.get("is_day_trade") and t["status"] == "ACTIVE"]
        if not day_trades:
            return

        current_prices = get_current_prices([t["ticker"] for t in day_trades])
        for t in day_trades:
            ticker = t["ticker"]
            cp = current_prices.get(ticker)
            if not cp: continue
            
            entry = float(t["entry_price"])
            pnl = ((cp - entry) / entry * 100) if t["signal"] == "AL" else ((entry - cp) / entry * 100)
            t["status"] = "CLOSED_TP" if pnl > 0 else "CLOSED_SL"
            
            await self.notifier.send_message(
                f"⏱️ <b>DAY TRADE KAPANDI (17:55)</b>\n"
                f"Varlık: <code>{ticker}</code>\nNet: %{pnl:.2f} {'✅' if pnl > 0 else '❌'}",
                is_system=True
            )

        closed_day = [t for t in trades if t["status"] != "ACTIVE"]
        if closed_day:
            _archive_closed_trades(closed_day)
        
        remaining = [t for t in trades if t["status"] == "ACTIVE"]
        save_trades(remaining)

    async def send_daily_snapshot(self):
        try:
            with open('last_scan_metrics.json', 'r', encoding='utf-8') as f:
                metrics = json.load(f)
                asyncio.create_task(send_snapshot_excel(metrics))
        except Exception as e:
            logger.warning(f"Gün sonu Excel gönderilemedi: {e}")

    async def send_heartbeat(self):
        trades = load_trades()
        active_count = sum(1 for t in trades if t["status"] == "ACTIVE")
        hb_msg = (
            f"💚 <b>Bot Aktif (Clean Arch)</b>\n"
            f"Aktif Pozisyon: {active_count}\n"
            f"{cb_status()}\n"
            f"━━━ Kaos Modülleri ━━━\n"
            f"{get_penalty_status()}\n"
            f"{get_scorecard_status()}\n"
            f"{get_filter_health_summary()}"
        )
        await self.notifier.send_message(hb_msg, is_system=True)

    async def run_weekly_tasks(self):
        try:
            changes = run_darwinism(
                min_trades=config.SCORECARD_MIN_TRADES,
                window_days=config.SCORECARD_AUTO_DISABLE_DAYS
            )
            if changes:
                darwin_msg = "🦕 <b>DARWİNİZM RAPORU</b>\n━━━━━━━━━━━━━━━━━━\n"
                for c in changes:
                    icon = "🔴" if c["action"] == "DISABLED" else "⚠️"
                    darwin_msg += f"{icon} {c['strategy']}: {c['reason']}\n"
                await self.notifier.send_message(darwin_msg, is_system=True)
            
            await self.notifier.send_message(generate_weekly_report(), is_system=True)
            cleanup_expired_quarantines()
            
            try:
                from penalty_box import prune_old_assets
                pruned = prune_old_assets(90)
                if pruned > 0:
                    await self.notifier.send_message(f"🧹 Penalty Box temizliği: {pruned} eski varlık silindi.", is_system=True)
            except Exception as e:
                logger.warning(f"Penalty pruning hatası: {e}")
                
            paralysis = check_analysis_paralysis()
            if paralysis:
                await self.notifier.send_message(paralysis, is_system=True)
        except Exception as e:
            logger.error(f"Haftalık görev hatası: {e}")
