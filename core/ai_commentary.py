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
            "Sen benim kişisel algoritmik trade asistanımsın. Aşağıda sistemimin ürettiği "
            "işlem sinyali (veya sinyalleri) bulunuyor.\n\n"
            "Sinyaller:\n" + "\n".join(signal_details) + "\n\n"
            "Görev: Bu işleme girip girmemem gerektiği konusunda bana doğrudan ve net bir tavsiye ver.\n"
            "Kurallar:\n"
            "- Sadece bana özel, doğrudan ve net bir dille konuş.\n"
            "- İşlem yönünü (LONG veya SHORT) ve sistem gerekçelerini analiz ederek bana 0 ile 100 arasında kendi 'Yapay Zeka Güven Skorunu' ver.\n"
            "- Değerlendirmende net ol ve mesajın en sonunda büyük harflerle 'KARAR: İŞLEME GİR' veya 'KARAR: BEKLE' şeklinde tavsiyeni belirt.\n"
            "- Genel piyasa hikayeleri yerine spesifik olarak bu sinyale ve başarı ihtimaline odaklan.\n"
            "- 'Kripto piyasası risklidir, kendi araştırmanızı yapın' gibi genel geçer uyarıları KESİNLİKLE KULLANMA. Sadece veriye dayalı, eyleme dönüştürülebilir net bir yorum yap."
        )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Sen benim özel algoritmik kripto asistanımsın. Gereksiz laf kalabalığı yapmadan, net kararlar ve tavsiyeler verirsin."},
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
