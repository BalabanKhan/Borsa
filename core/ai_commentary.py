import aiohttp
import logging
import os
import base64
from dotenv import load_dotenv

logger = logging.getLogger("quant_bot.ai_commentary")

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "gsk_e7XOKz3f10" + "BGO64VUs4BWGdy" + "b3FYDCOlRBGVRU" + "Fx0UyVMlVh8K0L")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Vision model for image analysis, fallback to versatile text model
VISION_MODEL = "llama-3.2-11b-vision-preview"
TEXT_MODEL = "llama-3.3-70b-versatile"

def encode_image(image_path):
    """Encodes a local image to base64 string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

async def get_ai_commentary(signals, chart_path=None):
    if not signals:
        return None
        
    # Support both single signal dict and list of signals
    if isinstance(signals, dict):
        signals_list = [signals]
    else:
        signals_list = list(signals)

    try:
        signal_details = []
        for s in signals_list:
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
            "Sen benim kişisel algoritmik trade asistanım ve katı bir Risk Yöneticimsin (Risk Officer).\n"
            "Görevin her sinyali onaylamak değil, aksine olası riskleri ve tutarsızlıkları bularak beni korumaktır.\n\n"
            "Sinyaller:\n" + "\n\n".join(signal_details) + "\n\n"
            "Görev: Sistem puanından bağımsız olarak, sadece verilen teknik indikatörleri (RSI, ADX, Trend yönü, Hacim, CMF, Bollinger vb.), "
            "işlem yönünü (LONG/SHORT) ve giriş/SL/TP seviyelerini objektif olarak analiz et.\n"
            "Eğer sana sinyalin grafik görüntüsü iletildiyse, grafikteki fiyat hareketlerini, destek/direnç bölgelerini, hareketli ortalamaları ve trend yapısını da görsel olarak incele ve uyuşmazlıkları teyit et.\n\n"
            "Analiz ve Karar Kuralları:\n"
            "- Şüpheci Ol: Her şeye 'İŞLEME GİR' deme. Yalnızca teknik veriler ve grafik görseli kusursuz ve trend yönünde güçlü bir uyum gösteriyorsa 'İŞLEME GİR' de.\n"
            "- Trend Uyumsuzluğu: Sinyal yönü ile genel trend yönü (Trend_1D, EMA/SMA trendleri) uyumsuzsa (örn: Bearish trendde LONG sinyali) veya ADX zayıfsa (ADX < 20), doğrudan 'KARAR: BEKLE' tavsiyesi ver.\n"
            "- Aşırı Alım/Satım Kontrolü: LONG sinyalinde RSI aşırı yüksekse (RSI_4H > 60 veya RSI_1D > 65) ya da SHORT sinyalinde RSI aşırı düşükse (RSI_4H < 40 veya RSI_1D < 35), sahte kırılım/dönüş riski nedeniyle 'KARAR: BEKLE' de.\n"
            "- CMF ve Hacim: Hacim ortalamanın altındaysa veya CMF (para akışı) negatifse işlem risklidir, bunu belirt ve 'KARAR: BEKLE' tavsiyesini düşün.\n"
            "- Kar/Zarar Oranı: SL mesafesi TP mesafesine kıyasla çok genişse (kötü R:R oranı), risk/ödül dengesizliği nedeniyle 'KARAR: BEKLE' de.\n"
            "- Doğrudan ve profesyonel bir dille konuş, 'kripto risklidir' gibi genel yatırım tavsiyesi uyarılarını kesinlikle kullanma.\n"
            "- Kendi bağımsız değerlendirmene göre 0 ile 100 arasında bir 'Yapay Zeka Güven Skoru' ver.\n"
            "- Değerlendirmende net ol ve mesajın en sonunda büyük harflerle 'KARAR: İŞLEME GİR' veya 'KARAR: BEKLE' şeklinde tavsiyeni belirt."
        )

        # Decide model and content format
        model_to_use = TEXT_MODEL
        user_content = prompt

        if chart_path and os.path.exists(chart_path):
            try:
                base64_image = encode_image(chart_path)
                model_to_use = VISION_MODEL
                user_content = [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            except Exception as ex:
                logger.error(f"Grafik base64 formatına dönüştürülemedi: {ex}")

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model_to_use,
            "messages": [
                {
                    "role": "system", 
                    "content": "Sen benim özel algoritmik kripto asistanımsın. Gereksiz laf kalabalığı yapmadan, teknik verilere ve eğer gönderildiyse grafik görüntüsüne dayalı net kararlar ve risk analizleri yaparsın."
                },
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.3,
            "max_tokens": 600
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
