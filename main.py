"""
main.py
Borsa Asistanı Ana Döngü (Hibrit Sistem: BIST 100 + Kripto)
Clean Architecture & SOLID Refactoring
"""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import traceback
import sys

from core.notifier import NotificationService
from core.scanner import ScannerService
from core.scheduler import TaskScheduler
from core.defensive_engine import DefensiveExceptionManager

# ════ Profesyonel Logging Yapılandırması ════
logger = logging.getLogger("quant_bot")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    _file_handler = RotatingFileHandler(
        "bot.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(_file_handler)
    
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_console_handler)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

async def main():
    print("==================================================")
    print("🤖 Borsa Asistanı (Clean Architecture) Başlatılıyor...")
    print("==================================================")
    
    try:
        # 1. Bildirim Servisi (Telegram)
        notifier = NotificationService()
        if notifier.bot:
            print("✅ Telegram Bot bağlantısı kuruldu.")
        else:
            print("⚠️ Uyarı: TELEGRAM_BOT_TOKEN eksik. Konsol modu aktif.")
            
        if notifier.watch_bot:
            print('✅ WATCH Telegram Bot bağlantısı kuruldu.')
        
        # 2. Tarayıcı Servisi (Piyasa Taraması & Kaos Modülleri)
        scanner = ScannerService(notifier=notifier)
        
        # 3. Görev Zamanlayıcı (APScheduler)
        scheduler = TaskScheduler(scanner=scanner, notifier=notifier)
        scheduler.start()
        
        # Sistemi ilk açılışta bir kez tara
        await scanner.run_scan()
        
        # Sonsuz döngü (Scheduler arkaplanda çalışmaya devam edecek)
        while True:
            # V3.4: Defensive Safe Mode Check
            if DefensiveExceptionManager.is_system_in_safe_mode():
                logger.critical("🚨 SİSTEM SAFE-MODE POZİSYONUNDA! Görev zamanlayıcı durduruluyor...")
                scheduler.shutdown()
                raise RuntimeError("Defensive Safeguard: Sistem ardışık hatalar sebebiyle durduruldu.")
            await asyncio.sleep(60) # 1 saat yerine 1 dakika aralıklarla kontrol et
            
    except KeyboardInterrupt:
        print("\n👋 Bot durduruluyor...")
    except Exception as e:
        print(f"❌ Döngü hatası: {e}")
        try:
            error_msg = f"⚠️ <b>SİSTEM HATASI (CRITICAL)</b>\n<code>{e}</code>\n<pre>{traceback.format_exc()[-500:]}</pre>"
            if 'notifier' in locals():
                # Notifier async metodu çağrılıyor
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(notifier.send_message(error_msg))
        except Exception as notify_err:
            logger.error(f"Hata bildirimi gönderilemedi: {notify_err}")
        
        # AAA Kalite: Hatayı yutma, fırlat ve programın çöktüğünden emin ol (Fail-Fast)
        DefensiveExceptionManager.log_and_raise(e, "main.py critical loop failure")

if __name__ == "__main__":
    try:
        # Fix for Windows asyncio loop
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot kapatıldı.")
