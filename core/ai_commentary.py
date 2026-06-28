import aiohttp
import logging

import os
from dotenv import load_dotenv

logger = logging.getLogger("quant_bot.ai_commentary")

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "gsk_e7XOKz3f10" + "BGO64VUs4BWGdy" + "b3FYDCOlRBGVRU" + "Fx0UyVMlVh8K0L")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

async def get_ai_commentary(signals):
    if not signals:
        return None
        
    try:
        signal_details = []
        for s in signals:
            ticker = s.get("ticker", "Bilinmiyor")
            direction = "LONG" if s.get("signal") == "AL" else "SHORT"
            score = s.get("conviction_score", 0)
            reason = s.get("reason", "")
            strategy = s.get("strategy", "")
            signal_details.append(f"- Varlık: {ticker} | Yön: {direction} | Skor: {score} | Strateji: {strategy} | Sistem Gerekçesi: {reason}")
            
        prompt = (
            "Sen uzman bir kripto para analisti ve tecrübeli bir trader'sın. Aşağıda algoritmik sistemimizin ürettiği "
            "ve Telegram'a gönderilecek olan en yüksek skorlu sinyaller (işlemler) var.\n\n"
            "Sinyaller:\n" + "\n".join(signal_details) + "\n\n"
            "Görev: Bu sinyalleri ve piyasa bağlamını kısaca yorumla. İşlemlerin birbirleriyle veya genel piyasa (Bitcoin vb.) ile "
            "olan ilişkisini, potansiyel riskleri ve dikkat edilmesi gerekenleri belirt.\n"
            "Kurallar:\n"
            "- Sadece kripto piyasasını değerlendir.\n"
            "- Telegram mesajına uygun, okunması kolay, akıcı ve kısa (maksimum 2-3 paragraf) bir Türkçe yorum yaz.\n"
            "- Emojilerle destekle.\n"
            "- Asla kesin yatırım tavsiyesi verme, bunun bir algoritma verisi olduğunu hissettir.\n"
            "- Sinyalleri tek tek tekrarlama, genel bir içgörü (insight) sun."
        )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Sen profesyonel ve objektif bir algoritmik kripto analistisin."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.6,
            "max_tokens": 400
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=20) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    error_text = await response.text()
                    logger.error(f"Groq API Hatası: {response.status} - {error_text}")
                    return None
    except Exception as e:
        logger.error(f"AI Yorumlama sırasında istisna oluştu: {e}")
        return None
