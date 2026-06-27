import yf_cache
import pandas as pd
import yfinance as yf
import ta
import numpy as np

def analyze_actual_signals():
    # Read the trades
    df_trades = pd.read_csv('universal_backtest_results.csv')
    if df_trades.empty:
        print("No trades to analyze")
        return
        
    print(f"Total trades: {len(df_trades)}")
    
    # Load daily / hourly data for symbols
    symbols = df_trades['Symbol'].unique()
    data = {}
    for sym in symbols:
        df = yf.download(sym, period="3mo", interval="1h", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df.ffill().bfill().dropna()
        df.columns = [c.lower() for c in df.columns]
        data[sym] = df
        
    results = []
    
    for _, row in df_trades.iterrows():
        sym = row['Symbol']
        date = pd.to_datetime(row['Date'])
        if sym not in data: continue
        df = data[sym]
        
        future_df = df[df.index > date].head(24) # Next 24 hours
        if future_df.empty: continue
        
        entry = row['Price']
        signal = row['Signal'] # We assumed LONG for VWAP and Mega trend but VWAP can be long. Let's assume all are LONG for now unless strategy says Short
        if "Short" in row['Strategy']:
            signal = "SHORT"
        else:
            signal = "LONG"
            
        if signal == "LONG":
            mfe = (future_df['high'].max() - entry) / entry * 100
            mae = (entry - future_df['low'].min()) / entry * 100
        else:
            mfe = (entry - future_df['low'].min()) / entry * 100
            mae = (future_df['high'].max() - entry) / entry * 100
            
        results.append({
            "Strategy": row['Strategy'],
            "Symbol": sym,
            "Signal": signal,
            "Outcome": row['Outcome'],
            "MFE_Pct": mfe,
            "MAE_Pct": mae,
            "SL_Dist_Pct": abs(entry - row['SL']) / entry * 100,
            "TP_Dist_Pct": abs(row['TP'] - entry) / entry * 100
        })
        
    res_df = pd.DataFrame(results)
    
    print("\n--- Actual Signal MFE and MAE ---")
    print(res_df.groupby("Strategy")[['MFE_Pct', 'MAE_Pct', 'SL_Dist_Pct', 'TP_Dist_Pct']].mean())
    
    print("\nOutcome Breakdown by Strategy:")
    print(res_df.groupby(['Strategy', 'Outcome']).size())

analyze_actual_signals()
