import asyncio
import sys
import pytest
from core.notifier import NotificationService

@pytest.mark.anyio
async def test_telegram():
    print("Test başlatılıyor...")
    notifier = NotificationService()
    
    if not notifier.bot:
        print("HATA: TELEGRAM_BOT_TOKEN bulunamadı.")
        return
        
    print("Test mesajı gönderiliyor...")
    msg = (
        "🟢 <b>TEST MESAJI</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Bu mesaj sistemin yeni Clean Architecture üzerinden başarıyla Telegram bildirimleri gönderebildiğini doğrulamak için atılmıştır.\n\n"
        "<i>Sistem çalışır durumda.</i>"
    )
    
    await notifier.send_message(msg)
    print("Test mesajı gönderim işlemi tamamlandı. Lütfen Telegram kanalınızı kontrol edin.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_telegram())
