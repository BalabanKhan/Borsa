import json
import logging
import asyncio
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from trade_tracker import load_trades, save_trades, _archive_closed_trades
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
    def __init__(self, scanner, notifier, trade_engine):
        self.scanner = scanner
        self.notifier = notifier
        self.trade_engine = trade_engine
        self.scheduler = AsyncIOScheduler(
            timezone=ZoneInfo("Europe/Istanbul"),
            job_defaults={'misfire_grace_time': 15}
        )
        self._price_fail_count = 0
        self.setup_jobs()

    def setup_jobs(self):
        # Piyasa Taraması (Her 5 Dakikanın Katında: :00, :05, :10 vb.)
        self.scheduler.add_job(self.scanner.run_scan, 'cron', minute='*/5', id='market_scan')
        
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
        
        # Günlük AI Otopsi Raporu (Her gün 23:30)
        self.scheduler.add_job(self.send_ai_postmortem_report, 'cron', hour=23, minute=30, id='ai_postmortem_report')
        
        # Haftalık Darwinizm (Her Pazar 00:00)
        self.scheduler.add_job(self.run_weekly_tasks, 'cron', day_of_week='sun', hour=0, minute=0, id='weekly_tasks')

    def start(self):
        self.scheduler.start()
        logger.info("APScheduler görev yöneticisi başlatıldı.")

    async def check_prices(self):
        trades = await asyncio.to_thread(load_trades)
        active_trades = [t for t in trades if t["status"] == "ACTIVE"]
        active_tickers = list(set([t["ticker"] for t in active_trades]))
        
        if not active_tickers:
            return

        current_prices = await asyncio.to_thread(get_current_prices, active_tickers)
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
        notifications = await loop.run_in_executor(None, self.trade_engine.check_active_trades, current_prices)
        for msg in notifications:
            await self.notifier.send_message(msg, is_system=True)

    async def close_day_trades(self):
        trades = await asyncio.to_thread(load_trades)
        day_trades = [t for t in trades if t.get("is_day_trade") and t["status"] == "ACTIVE"]
        if not day_trades:
            return

        tickers = [t["ticker"] for t in day_trades]
        current_prices = await asyncio.to_thread(get_current_prices, tickers)
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

        def save_and_archive():
            closed_day = [t for t in trades if t["status"] != "ACTIVE"]
            if closed_day:
                _archive_closed_trades(closed_day)
            remaining = [t for t in trades if t["status"] == "ACTIVE"]
            save_trades(remaining)
        await asyncio.to_thread(save_and_archive)

    async def send_daily_snapshot(self):
        try:
            def read_metrics():
                with open('last_scan_metrics.json', 'r', encoding='utf-8') as f:
                    return json.load(f)
            metrics = await asyncio.to_thread(read_metrics)
            asyncio.create_task(send_snapshot_excel(metrics))
        except Exception as e:
            logger.warning(f"Gün sonu Excel gönderilemedi: {e}")

    async def send_ai_postmortem_report(self):
        try:
            from trade_tracker.reporter import generate_ai_daily_report
            report_msg = generate_ai_daily_report()
            # Send to WATCH channel as requested
            await self.notifier.send_message(report_msg, is_watch=True)
        except Exception as e:
            logger.error(f"Günlük AI Raporu gönderilemedi: {e}")

    async def send_heartbeat(self):
        def build_heartbeat():
            trades = load_trades()
            active_count = sum(1 for t in trades if t["status"] == "ACTIVE")
            return (
                f"💚 <b>Bot Aktif (Clean Arch)</b>\n"
                f"Aktif Pozisyon: {active_count}\n"
                f"{cb_status()}\n"
                f"━━━ Kaos Modülleri ━━━\n"
                f"{get_penalty_status()}\n"
                f"{get_scorecard_status()}\n"
                f"{get_filter_health_summary()}"
            )
        hb_msg = await asyncio.to_thread(build_heartbeat)
        await self.notifier.send_message(hb_msg, is_system=True)

    async def run_weekly_tasks(self):
        try:
            def do_weekly_sync():
                changes_res = run_darwinism(
                    min_trades=config.SCORECARD_MIN_TRADES,
                    window_days=config.SCORECARD_AUTO_DISABLE_DAYS
                )
                report_res = generate_weekly_report()
                cleanup_expired_quarantines()
                
                pruned_res = 0
                try:
                    from penalty_box import prune_old_assets
                    pruned_res = prune_old_assets(90)
                except Exception as e:
                    logger.warning(f"Penalty pruning hatası: {e}")
                    
                paralysis_res = check_analysis_paralysis()
                return changes_res, report_res, pruned_res, paralysis_res

            changes, report, pruned, paralysis = await asyncio.to_thread(do_weekly_sync)

            if changes:
                darwin_msg = "🦕 <b>DARWİNİZM RAPORU</b>\n━━━━━━━━━━━━━━━━━━\n"
                for c in changes:
                    icon = "🔴" if c["action"] == "DISABLED" else "⚠️"
                    darwin_msg += f"{icon} {c['strategy']}: {c['reason']}\n"
                await self.notifier.send_message(darwin_msg, is_system=True)
            
            await self.notifier.send_message(report, is_system=True)
            if pruned > 0:
                await self.notifier.send_message(f"🧹 Penalty Box temizliği: {pruned} eski varlık silindi.", is_system=True)
            if paralysis:
                await self.notifier.send_message(paralysis, is_system=True)
        except Exception as e:
            logger.error(f"Haftalık görev hatası: {e}")
