import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

logger = logging.getLogger("quant_bot.notifier")
FAILED_MSG_FILE = "failed_messages.json"

class NotificationService:
    def __init__(self):
        load_dotenv()
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.watch_bot_token = os.getenv("TELEGRAM_WATCH_BOT_TOKEN")
        
        chat_id_env = os.getenv("TELEGRAM_CHAT_ID", "")
        self.chat_ids = [cid.strip() for cid in chat_id_env.split(",") if cid.strip()]
        
        watch_chat_id_env = os.getenv("TELEGRAM_WATCH_CHAT_ID", "")
        self.watch_chat_ids = [cid.strip() for cid in watch_chat_id_env.split(",") if cid.strip()]
        
        self.bot = Bot(token=self.bot_token) if self.bot_token else None
        self.watch_bot = Bot(token=self.watch_bot_token) if self.watch_bot_token else None

    async def send_message(self, message, is_watch=False, max_retries=3):
        target_bot = self.watch_bot if is_watch else self.bot
        target_chat_ids = self.watch_chat_ids if is_watch else self.chat_ids

        if not target_bot or not target_chat_ids:
            clean_msg = message.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", "")
            logger.info(f"[Console Fallback] {clean_msg}")
            return

        for chat_id in target_chat_ids:
            sent = False
            for attempt in range(max_retries):
                try:
                    await target_bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
                    logger.info(f"[Telegram] Mesaj gönderildi: chat_id={chat_id}")
                    sent = True
                    break
                except Exception as e:
                    logger.error(f"[Telegram] Deneme {attempt+1}/{max_retries} başarısız (chat_id={chat_id}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5 * (attempt + 1))
            
            if not sent:
                self._save_failed_message(chat_id, message)

    def _save_failed_message(self, chat_id, message):
        failed = []
        if os.path.exists(FAILED_MSG_FILE):
            try:
                with open(FAILED_MSG_FILE, 'r', encoding='utf-8') as f:
                    failed = json.load(f)
            except Exception as e:
                logger.warning(f"Yedek dosya okunamadı: {e}")
        
        failed.append({
            "chat_id": chat_id,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        try:
            with open(FAILED_MSG_FILE, 'w', encoding='utf-8') as f:
                json.dump(failed, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Yedekleme hatası: {e}")

    async def retry_failed_messages(self):
        if not os.path.exists(FAILED_MSG_FILE):
            return
            
        try:
            with open(FAILED_MSG_FILE, 'r', encoding='utf-8') as f:
                failed = json.load(f)
        except Exception as e:
            logger.error(f"Failed messages dosya hatası: {e}")
            return

        if not failed or not self.bot:
            return

        remaining = []
        for item in failed:
            try:
                await self.bot.send_message(
                    chat_id=item["chat_id"],
                    text=f"⏰ <i>Gecikmeli mesaj ({item['timestamp'][:16]}):</i>\n\n{item['message']}",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Retry başarısız chat_id={item.get('chat_id')}: {e}")
                remaining.append(item)

        with open(FAILED_MSG_FILE, 'w', encoding='utf-8') as f:
            json.dump(remaining, f, indent=2, ensure_ascii=False)

    @staticmethod
    def format_signal_message(trade_data):
        market = trade_data.get("market", "KRİPTO")
        strategy = trade_data.get("strategy", "BİLİNMİYOR")
        
        headers = {
            "BIST": "📈 [BIST 100 SİNYALİ]",
            "EMTİA": "⛏️ [EMTİA SİNYALİ]",
            "AYI_AVCISI": "🐻 [AYI AVCISI SHORT]"
        }
        header = headers.get(market, "🚀 [KRİPTO SİNYALİ]")
        
        entry_price = trade_data.get('entry_price', 0)
        sl_price = trade_data.get('sl', 0)
        tp_price = trade_data.get('tp', 0)
        signal_dir = trade_data.get('signal', 'AL')

        rr_ratio = trade_data.get('rr_ratio')
        rr_line = f"<b>R:R Oranı:</b> <code>{rr_ratio:.1f}:1</code>\n" if rr_ratio else ""

        conv_score = trade_data.get('conviction_score')
        conv_line = ""
        if conv_score is not None:
            conv_grade = trade_data.get('conviction_grade', 'N/A')
            conv_pos = trade_data.get('position_size_pct', 100)
            conv_emoji = {"STRONG": "🟢", "MEDIUM": "🟡", "WATCH": "🟠"}.get(conv_grade, "⚪")
            conv_line = f"{conv_emoji} <b>Conviction:</b> <code>{conv_score:.0f}/100 ({conv_grade})</code> | Poz: %{conv_pos}\n"

        conv_details = trade_data.get('conviction_details')
        details_str = ""
        if conv_details and isinstance(conv_details, dict):
            details_str = "<b>Puanlama Detayları:</b>\n"
            for k, v in conv_details.items():
                if v > 0:
                    details_str += f" ├ {k}: <code>+{v:.1f}</code>\n"
            details_str += " └────────────────\n"

        raw_inds = trade_data.get('raw_indicators')
        if raw_inds and isinstance(raw_inds, dict):
            details_str += "<b>Giriş Metrikleri:</b>\n"
            for k, v in raw_inds.items():
                details_str += f" ├ {k}: <code>{v}</code>\n"
            details_str += " └────────────────\n"

        ttl_pct = 0.015
        if signal_dir == "AL":
            ttl_ceiling = entry_price * (1 + ttl_pct)
            ttl_floor = entry_price * (1 - ttl_pct)
            ttl_line = (f"\n⏰ <b>SİNYAL ÖMRÜ (TTL):</b>\n"
                       f"❗ Fiyat <code>{ttl_ceiling:.4f}</code> üstüne çıkmışsa → SİNYAL ÖLDÜ, İŞLEME GİRME!\n"
                       f"❗ Fiyat <code>{ttl_floor:.4f}</code> altına düşmüşse → SL YAKINLAŞMIŞ, DİKKATLİ OL!")
        else:
            ttl_floor = entry_price * (1 - ttl_pct)
            ttl_ceiling = entry_price * (1 + ttl_pct)
            ttl_line = (f"\n⏰ <b>SİNYAL ÖMRÜ (TTL):</b>\n"
                       f"❗ Fiyat <code>{ttl_floor:.4f}</code> altına düşmüşse → SİNYAL ÖLDÜ, İŞLEME GİRME!\n"
                       f"❗ Fiyat <code>{ttl_ceiling:.4f}</code> üstüne çıkmışsa → SL YAKINLAŞMIŞ, DİKKATLİ OL!")

        return (
            f"<b>{header}</b>\n"
            f"<b>{strategy}</b>\n"
            f"-------------------------------------\n"
            f"<b>Varlık:</b> <code>{trade_data.get('ticker', 'Bilinmiyor')}</code>\n"
            f"<b>Giriş Fiyatı:</b> <code>{entry_price:.4f}</code>\n"
            f"<b>Zarar Kes (SL):</b> <code>{sl_price:.4f}</code>\n"
            f"<b>Kar Al (TP):</b> <code>{tp_price:.4f}</code>\n"
            f"{rr_line}{conv_line}{details_str}"
            f"-------------------------------------\n"
            f"<b>Sistem Gerekçesi:</b>\n<i>{trade_data.get('reason', 'Sebep belirtilmemiş.')}</i>\n{ttl_line}"
        )
