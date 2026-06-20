import asyncio
from config import TOP_CRYPTO
from data_sources import get_crypto_data, get_btc_status, get_btc_dominance_trend
from strategies import analyze_strategies_crypto, analyze_bear_hunter

async def main():
    print("Kripto piyasası SHORT (Satış) sinyalleri taranıyor...\n")
    btc_ok = get_btc_status()
    # Pumping check is usually inside strategies, but let's just pass context
    
    short_signals = []
    
    for symbol in TOP_CRYPTO:
        # 1D ve 4H verilerini çek
        df_1d, df_4h = get_crypto_data(symbol)
        
        if df_1d is None or df_1d.empty or df_4h is None or df_4h.empty:
            continue
            
        last_1d = df_1d.iloc[-1]
        last_4h = df_4h.iloc[-1]
        current_price = last_4h['close']
        
        ctx = {
            "symbol": symbol,
            "last_1d": last_1d,
            "last_4h": last_4h,
            "current_price": current_price,
            "df_1d": df_1d,
            "df_4h": df_4h,
            "btc_ok": btc_ok,
            "btcdom_trend": "UP" # Mock or real, doesn't matter, we just run the strategy.
        }
        
        # Crypto normal strats
        signals = analyze_strategies_crypto(symbol, df_1d, df_4h, btc_ok)
        # Filter for shorts (SAT)
        for s in signals:
            if s.get("signal") == "SAT":
                short_signals.append(s)
                
        # Ayı avcısı strats (Short specifik)
        bear_signals = analyze_bear_hunter(symbol, df_1d, df_4h, btc_ok)
        for s in bear_signals:
            if s.get("signal") == "SAT":
                short_signals.append(s)

    if short_signals:
        print(f"Toplam {len(short_signals)} SHORT sinyali bulundu:\n")
        for s in short_signals:
            print(f"-> Ticker: {s['ticker']}")
            print(f"   Strateji: {s['strategy']}")
            print(f"   Güven Skoru: {s['conviction_score']} ({s['conviction_grade']})")
            print(f"   Giriş: {s['entry_price']} | SL: {s['sl']} | TP: {s['tp']}")
            reason_text = s['reason'].encode('cp1254', 'ignore').decode('cp1254')
            print(f"   Neden: {reason_text}")
            print("-" * 40)
    else:
        print("Şu anda uygun bir kripto SHORT (Satış) sinyali bulunamadı.")

if __name__ == "__main__":
    asyncio.run(main())
