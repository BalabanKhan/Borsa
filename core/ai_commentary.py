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
            reason = s.get("reason", "")
            strategy = s.get("strategy", "")
            entry = s.get("entry_price", 0.0)
            sl = s.get("sl", 0.0)
            tp = s.get("tp", 0.0)
            
            # Combine indicators and raw_indicators
            inds = s.get("indicators", {}) or {}
            raw_inds = s.get("raw_indicators", {}) or {}
            
            all_inds = {}
            if isinstance(inds, dict):
                all_inds.update(inds)
            if isinstance(raw_inds, dict):
                all_inds.update(raw_inds)
                
            ind_strings = []
            for k, v in all_inds.items():
                if isinstance(v, float):
                    ind_strings.append(f"{k}: {v:.2f}")
                else:
                    ind_strings.append(f"{k}: {v}")
            inds_formatted = ", ".join(ind_strings) if ind_strings else "Veri bulunmuyor"
            
            signal_details.append(
                f"- Varlık: {ticker}\n"
                f"  Yön: {direction}\n"
                f"  Seviyeler: Giriş={entry:.4f} | SL={sl:.4f} | TP={tp:.4f}\n"
                f"  Strateji: {strategy}\n"
                f"  Sistem Gerekçesi: {reason}\n"
                f"  Teknik İndikatörler: {inds_formatted}"
            )
            
        prompt = (
            "Sen benim kişisel algoritmik trade asistanımsın. Aşağıda sistemimin ürettiği "
            "işlem sinyalleri ve bunlara ait teknik indikatör verileri bulunuyor.\n\n"
            "Sinyaller:\n" + "\n\n".join(signal_details) + "\n\n"
            "Görev: Sistem puanından bağımsız olarak, sadece verilen teknik indikatörleri (RSI, ADX, Trend yönü, Hacim vb.), "
            "işlem yönünü (LONG/SHORT) ve giriş/SL/TP seviyelerini objektif olarak analiz et. "
            "Bu işleme girip girmemem gerektiği konusunda bana doğrudan, veri odaklı ve net bir tavsiye ver.\n\n"
            "Kurallar:\n"
            "- Sistem gerekçelerini ve indikatör değerlerini karşılaştırarak uyuşmazlık olup olmadığını denetle (örneğin aşırı alım bölgesinde LONG girmek riskli mi, trend yönüyle sinyal yönü uyumlu mu vb.).\n"
            "- Sadece bana özel, doğrudan, profesyonel ve net bir dille konuş.\n"
            "- Kendi bağımsız değerlendirmene göre 0 ile 100 arasında bir 'Yapay Zeka Güven Skoru' ver.\n"
            "- Değerlendirmende net ol ve mesajın en sonunda büyük harflerle 'KARAR: İŞLEME GİR' veya 'KARAR: BEKLE' şeklinde tavsiyeni belirt.\n"
            "- 'Kripto piyasası risklidir, kendi araştırmanızı yapın' gibi genel geçer uyarıları KESİNLİKLE KULLANMA. Sadece veriye dayalı, eyleme dönüştürülebilir net bir yorum yap."
        )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Sen benim özel algoritmik kripto asistanımsın. Gereksiz laf kalabalığı yapmadan, teknik verilere dayalı net kararlar ve tavsiyeler verirsin."},
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
