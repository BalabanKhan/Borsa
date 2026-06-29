import aiohttp
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger("quant_bot.ai_commentary")

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "gsk_e7XOKz3f10" + "BGO64VUs4BWGdy" + "b3FYDCOlRBGVRU" + "Fx0UyVMlVh8K0L")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

TEXT_MODEL = "llama-3.3-70b-versatile"

async def get_ai_commentary(signals, chart_path=None, df_4h=None):
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
        )

        if df_4h is not None and not df_4h.empty:
            import pandas as pd
            df_slice = df_4h.tail(15)
            ohlcv_lines = []
            for dt, row in df_slice.iterrows():
                dt_str = dt.strftime("%Y-%m-%d %H:%M")
                ohlcv_lines.append(
                    f"| {dt_str} | {row['open']:.4f} | {row['high']:.4f} | {row['low']:.4f} | {row['close']:.4f} | {int(row['volume'])} |"
                )
            ohlcv_table = (
                "| Tarih (UTC) | Açılış | Yüksek | Düşük | Kapanış | Hacim |\n"
                "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
                + "\n".join(ohlcv_lines)
            )
            prompt += f"Grafik Mum Verileri (Son 15 Bar - 4 Saatlik):\n{ohlcv_table}\n\n"

        prompt += (
            "Analiz ve Karar Kuralları:\n"
            "- Bütüncül Değerlendirme: İndikatörleri tek başına katı kurallar olarak değil, bir bütün olarak yorumla. Örneğin, LONG sinyalinde RSI yüksekse (örn: > 60) bu aşırı alım riski olabileceği gibi güçlü bir momentumun (Breakout/Kırılım) devamı da olabilir. Hacim artışı ve CMF pozitifliği bunu destekliyorsa olumlu değerlendirebilirsin.\n"
            "- Trend ve ADX: ADX'in düşük olması (örn: < 20) trendin zayıflığını gösterebileceği gibi, yeni başlayacak bir trendin öncesindeki konsolidasyon aşamasını da gösterebilir. Grafik mum yapısındaki kırılımları ve hacim değişimlerini dikkate alarak karar ver.\n"
            "- Risk ve Fırsat Dengesi: Her küçük uyumsuzluğu doğrudan 'BEKLE' kararına bağlama. Eğer genel trend (Trend_1D) sinyal yönündeyse ve giriş/SL/TP seviyelerindeki R:R (Risk/Ödül) oranı mantıklıysa (örn: > 1.5), küçük uyumsuzluklara rağmen 'İŞLEME GİR' diyebilirsin.\n"
            "- Objektiflik: Sistem puanından veya bizim kurallarımızdan bağımsız olarak, profesyonel bir trader gibi davran. Gerçekten potansiyel gördüğün sinyallere 75-95 arası yüksek skorlar vererek 'İŞLEME GİR' kararını al. Kararsız veya riskli durumlarda ise daha düşük skor verip 'BEKLE' tavsiyesinde bulun.\n"
            "- Doğrudan ve profesyonel bir dille konuş, 'kripto risklidir' gibi genel yatırım tavsiyesi uyarılarını kesinlikle kullanma.\n\n"
            "ÇIKTI FORMATI: Yalnızca aşağıdaki formatta, son derece kısa, öz ve gereksiz laf kalabalığı yapmadan yaz. Paragraflar dolusu açıklama veya indikatör detaylandırması KESİNLİKLE yapma. Her varlık için sadece şu 4 satırlık şablonu kullan:\n\n"
            "🤖 **[Varlık Adı]**\n"
            "Skor: [0-100]\n"
            "Karar: [İŞLEME GİR veya BEKLE]\n"
            "Neden: [Maksimum 1-2 cümlelik çok kısa teknik gerekçe]"
        )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": TEXT_MODEL,
            "messages": [
                {
                    "role": "system", 
                    "content": "Sen benim özel algoritmik kripto asistanımsın. Gereksiz laf kalabalığı yapmadan, teknik verilere ve grafik verilerine dayalı net kararlar ve risk analizleri yaparsın."
                },
                {"role": "user", "content": prompt}
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
