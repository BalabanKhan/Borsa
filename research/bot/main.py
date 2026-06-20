import os
import sys
import logging
import datetime
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler
from dotenv import load_dotenv

# Ensure project root is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

from research.bot.handlers import basic_handlers, predict_handler, favorites_handler, scan_handlers
from research.bot.jobs.daily_report import daily_report

logger = logging.getLogger("research.bot.main")

def main():
    load_dotenv(os.path.join(project_root, '.env'))
    token = os.getenv("TELEGRAM_PREDICTOR_TOKEN")
    if not token:
        logger.error("TELEGRAM_PREDICTOR_TOKEN .env dosyasında bulunamadı!")
        sys.exit(1)
        
    logger.info("TimesFM Telegram Dinleyici Botu başlatılıyor...")
    
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", basic_handlers.start))
    application.add_handler(CommandHandler("help", basic_handlers.start))
    application.add_handler(CommandHandler("tahmin", predict_handler.tahmin))
    application.add_handler(CommandHandler("favoriekle", favorites_handler.favoriekle))
    application.add_handler(CommandHandler("favoricikar", favorites_handler.favoricikar))
    application.add_handler(CommandHandler("favoriler", favorites_handler.favoriler))
    application.add_handler(CommandHandler("kiyasla", favorites_handler.kiyasla))
    application.add_handler(CommandHandler("temizle", basic_handlers.temizle))
    application.add_handler(CommandHandler("gunici", scan_handlers.gunici))
    application.add_handler(CommandHandler("saatlik", scan_handlers.saatlik))
    application.add_handler(CommandHandler("sabah", scan_handlers.sabah_komutu))
    application.add_handler(CommandHandler("tara", scan_handlers.sabah_komutu))
    application.add_handler(CommandHandler("taracrypto", scan_handlers.taracrypto))
    application.add_handler(CommandHandler("tarasmc", scan_handlers.tarasmc))

    tz = pytz.timezone('Europe/Istanbul')
    t = datetime.time(hour=9, minute=55, tzinfo=tz)
    
    if application.job_queue:
        application.job_queue.run_daily(daily_report, time=t)
        logger.info("Sabah bülteni görevi saat 09:55 (TR) için zamanlandı.")
    else:
        logger.warning("JobQueue aktif değil. Sabah bülteni çalışmayacak. Lütfen 'pip install python-telegram-bot[job-queue]' kurulu olduğundan emin olun.")

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
