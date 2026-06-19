import json
import pandas as pd
from datetime import datetime, timedelta
from data_sources import fetch_data_yahoo_hourly
import indicators.core as ind_core
import config
from strategies.bist import _check_bist_7_vwap

def test_vwap():
    tickers = ["ISCTR.IS", "YKBNK.IS", "THYAO.IS", "TUPRS.IS", "KCHOL.IS", "AKBNK.IS", "SAHOL.IS", "ASELS.IS", "BIMAS.IS", "SISE.IS"]
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    signals = []
    
    for ticker in tickers:
        df_1h = fetch_data_yahoo_hourly(ticker, start_date=start_date, end_date=end_date)
        df_1d = fetch_data_yahoo_hourly(ticker, start_date=start_date - timedelta(days=100), end_date=end_date, interval="1d")
        
        if df_1h is None or len(df_1h) < 50 or df_1d is None or len(df_1d) < 50:
            continue
            
        df_1h = ind_core.inject_smart_indicators(df_1h)
        df_1d = ind_core.inject_smart_indicators(df_1d)
        
        df_1h['vol_sma_20'] = df_1h['volume'].rolling(20).mean()
        
        for i in range(50, len(df_1h)):
            ctx = {
                "symbol": ticker,
                "df_1h": df_1h.iloc[:i+1],
                "df_1d": df_1d,
                "last_1h": df_1h.iloc[i],
                "prev_1h": df_1h.iloc[i-1],
                "last_1d": df_1d.iloc[-1],
                "current_price": df_1h['close'].iloc[i],
                "bist_regime": "BULL",
                "xu100_down": False,
                "dynamic_sl_dist": df_1h['ATRr_14'].iloc[i] * 2.0 if 'ATRr_14' in df_1h.columns else df_1h['close'].iloc[i] * 0.02
            }
            
            # Sadece haftaici kontrolu bist.py icinde yapiliyor
            res = _check_bist_7_vwap(ctx)
            if res:
                for r in res:
                    signals.append(r)
                    print(f"SIGNAL FOUND: {ticker} at {df_1h.index[i]} - Reason: {r.get('reason')}")
                    
    print(f"\nTotal VWAP signals found in 30 days: {len(signals)}")
    
if __name__ == '__main__':
    test_vwap()
