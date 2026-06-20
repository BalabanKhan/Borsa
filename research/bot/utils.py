import os
import logging
from telegram import Update

# Loglama ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("research.bot")

ALLOWED_USER_IDS = [5892379162]

async def check_auth(update: Update) -> bool:
    """Kullanıcının yetkili olup olmadığını kontrol eder."""
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Bu botu kullanma yetkiniz bulunmamaktadır.")
        logger.warning(f"Yetkisiz erişim denemesi! User ID: {user_id}, Name: {update.effective_user.first_name}")
        return False
    return True
