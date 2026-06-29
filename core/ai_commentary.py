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
            "Sen üst düzey bir Kripto Para ve Borsa Kantitatif Analistisin (Top-Tier Quant Analyst).\n"
            "Görevin, sana sağlanan teknik indikatör verilerini (RSI, ADX, MACD, CMF vb.) ve grafik fiyat hareketlerini inceleyerek, "
            "tıpkı profesyonel bir fon yöneticisi gibi tamamen objektif, bütüncül (holistik) ve esnek bir piyasa analizi yapmaktır.\n\n"
            "Sinyaller:\n" + "\n\n".join(signal_details) + "\n\n"
            "Görev: Sadece verilen teknik indikatörleri, işlem yönünü (LONG/SHORT) ve giriş/SL/TP seviyelerini objektif olarak analiz et.\n"
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
            "KESİN KURALLAR VE ANALİZ YAKLAŞIMI:\n"
            "1. Sabit Kuralları Bırak: \"ADX 20'nin altındaysa kesinlikle işlem yapılmaz\" veya \"RSI 70'in üzerindeyse kesin düşer\" gibi amatör kalıpları unut. Verileri bir bütün olarak değerlendir.\n"
            "2. Bağlamı (Terrain) Anla: Önce piyasanın genel durumunu analiz et (Trend mi var? Yoksa yatay/ranging mi?). İndikatörleri bu bağlama göre yorumla.\n"
            "3. Çift Yönlü Düşünce (Chain of Thought): Hangi verilerin sinyali desteklediğini ve hangi verilerin çeliştiğini dürüstçe tart. Hacim (CMF/OBV) ve Momentum uyumuna özellikle dikkat et.\n"
            "4. Objektif ve Cesur Ol: Her küçük pürüzde korkup \"BEKLE\" kararı verme. Risk/Ödül oranı iyiyse ve genel konjonktür destekliyorsa, risk al ve \"İŞLEME GİR\" de.\n"
            "5. Objektif Skorlama (0-100):\n"
            "   - 0-39: Sinyal çok zayıf veya çelişkili. (Karar: BEKLE)\n"
            "   - 40-59: Ortalama sinyal, bazı riskler var ama potansiyel taşıyor. (Karar: BEKLE veya düşük riskli İŞLEME GİR)\n"
            "   - 60-79: Güçlü ve onaylanmış sinyal. (Karar: İŞLEME GİR)\n"
            "   - 80-100: Mükemmel uyum, yüksek olasılıklı işlem. (Karar: İŞLEME GİR)\n\n"
            "ÇIKTI FORMATI: Analizini yaparken aşağıdaki şablonu KESİNLİKLE bozmadan kullan. Başka metin ekleme:\n\n"
            "🤖 **[Varlık Adı]**\n"
            "🧠 **Piyasa Bağlamı:** [Trend mi yatay mı? Genel durum nedir?]\n"
            "✅ **Destekleyen Kanıtlar:** [Sinyali güçlendiren faktörler]\n"
            "⚠️ **Riskler/Çelişkiler:** [Sinyali zayıflatan faktörler]\n"
            "Skor: [0-100]\n"
            "Karar: [İŞLEME GİR veya BEKLE]\n"
            "Neden: [Tüm analizin tek cümlelik özeti]"
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
                    "content": "Sen üst düzey bir Kantitatif Analistsin. Duygusuz, tamamen kanıtlara (fiyat hareketi, hacim, momentum) dayalı düşünürsün."
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1200
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
