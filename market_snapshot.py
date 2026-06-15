import os
import pandas as pd
from datetime import datetime, timezone
import requests
import asyncio
from dotenv import load_dotenv

load_dotenv()

WATCH_BOT_TOKEN = os.getenv("TELEGRAM_WATCH_BOT_TOKEN")
WATCH_CHAT_IDS_ENV = os.getenv("TELEGRAM_WATCH_CHAT_ID", "")
WATCH_CHAT_IDS = [cid.strip() for cid in WATCH_CHAT_IDS_ENV.split(",") if cid.strip()]

def _send_telegram_document_sync(file_path, caption=""):
    """Senkron belge gönderme fonksiyonu."""
    if not WATCH_BOT_TOKEN or not WATCH_CHAT_IDS:
        print("[Snapshot] Watch Bot token or chat ID is missing. Document not sent.")
        return False
        
    url = f"https://api.telegram.org/bot{WATCH_BOT_TOKEN}/sendDocument"
    success = False
    for cid in WATCH_CHAT_IDS:
        try:
            with open(file_path, "rb") as f:
                payload = {"chat_id": cid, "caption": caption, "parse_mode": "HTML"}
                files = {"document": f}
                r = requests.post(url, data=payload, files=files, timeout=30)
                r.raise_for_status()
            print(f"[Snapshot] Document {file_path} sent via Watch Bot to {cid}")
            success = True
        except Exception as e:
            print(f"[Snapshot] Failed to send document to {cid}: {e}")
    return success

async def send_snapshot_excel(metrics_list):
    """
    Toplanan piyasa metriklerini Excel formatına dönüştürür ve WATCH botuna iletir.
    metrics_list: [{"Symbol": "THYAO", "Market": "BIST", ...}, ...]
    """
    if not metrics_list:
        print("[Snapshot] No metrics collected, skipping snapshot generation.")
        return

    if isinstance(metrics_list, dict):
        metrics_list = list(metrics_list.values())

    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime('%Y%m%d_%H%M')
    file_path = f"market_snapshot_{timestamp_str}.xlsx"

    try:
        # DataFrame oluştur ve Excel'e kaydet
        df = pd.DataFrame(metrics_list)
        df.to_excel(file_path, index=False)

        
        caption = f"📊 <b>Anlık Piyasa Taraması (Market Snapshot)</b>\n📅 {now.strftime('%Y-%m-%d %H:%M')} (UTC)"
        
        # Asenkron içinde senkron istek yapmak için asyncio.to_thread kullanılır
        await asyncio.to_thread(_send_telegram_document_sync, file_path, caption)
        
    except Exception as e:
        print(f"[Snapshot] Failed to generate or send Excel snapshot: {e}")
    finally:
        # Geçici dosyayı temizle
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as cleanup_error:
                print(f"[Snapshot] Cleanup error: {cleanup_error}")
