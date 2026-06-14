import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id_env = os.getenv("TELEGRAM_CHAT_ID", "")
CHAT_IDS = [cid.strip() for cid in chat_id_env.split(",") if cid.strip()]

async def main():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is missing in .env")
        return
        
    bot = Bot(token=BOT_TOKEN)
    msg = "🤖 <b>Test Mesajı</b>\nKripto AI Bot kurulumu başarıyla tamamlandı. Telegram entegrasyonu test ediliyor... Sistem aktif ve piyasa analizi için hazır!"
    
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
            print(f"Mesaj başarıyla gönderildi: chat_id={chat_id}")
        except Exception as e:
            print(f"Hata oluştu (chat_id={chat_id}): {e}")

if __name__ == "__main__":
    asyncio.run(main())
