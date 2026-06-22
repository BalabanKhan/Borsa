import pandas as pd
import yfinance as yf
import ta
import numpy as np
from datetime import timedelta

def analyze_mfe_mae(symbols=["BTC-USD", "ETH-USD"], period="3mo", interval="1h"):
    print("Fetching data...")
    data = {}
    for sym in symbols:
        df = yf.download(sym, period=period, interval=interval, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df.ffill().bfill().dropna()
        df.columns = [c.lower() for c in df.columns]
        
        # calculate some basics
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        df['ema_20'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        
        data[sym] = df.dropna()
        
    trades = []
    
    # Very basic breakout logic to generate lots of signals and test MFE/MAE
    for sym, df in data.items():
        for i in range(50, len(df)-24): # Ensure 24 hours of future data
            row = df.iloc[i]
            prev = df.iloc[i-1]
            
            # Condition: Simple EMA cross or RSI breakout just to have events
            signal = None
            if row['close'] > row['ema_20'] and prev['close'] <= prev['ema_20']:
                signal = "LONG"
            elif row['close'] < row['ema_20'] and prev['close'] >= prev['ema_20']:
                signal = "SHORT"
                
            if signal:
                entry_price = row['close']
                future_24 = df.iloc[i+1:i+25]
                
                if signal == "LONG":
                    mfe = (future_24['high'].max() - entry_price) / entry_price * 100
                    mae = (entry_price - future_24['low'].min()) / entry_price * 100
                else:
                    mfe = (entry_price - future_24['low'].min()) / entry_price * 100
                    mae = (future_24['high'].max() - entry_price) / entry_price * 100
                    
                trades.append({
                    "Symbol": sym,
                    "Signal": signal,
                    "Entry": entry_price,
                    "MFE_Pct": mfe,
                    "MAE_Pct": mae,
                    "ATR_Pct": row['atr'] / entry_price * 100
                })
                
    tdf = pd.DataFrame(trades)
    print(f"\nTotal signals analyzed: {len(tdf)}")
    print("\n--- Descriptive Statistics for MFE and MAE ---")
    print(tdf[['MFE_Pct', 'MAE_Pct', 'ATR_Pct']].describe())
    
    print("\nIf we set TP at 1% and SL at 1%, how many hit TP first?")
    # We can't know 'first' exactly from max/min, but we can assume if MAE < SL, MFE > TP -> WIN
    # Actually, we need step-by-step for exact 'first'. Let's do exact forward check:
    
    results = []
    for sl_mult in [1.0, 1.5, 2.0]:
        for tp_mult in [1.0, 2.0, 3.0]:
            wins = 0
            losses = 0
            for sym, df in data.items():
                for i in range(50, len(df)-24):
                    row = df.iloc[i]
                    prev = df.iloc[i-1]
                    signal = None
                    if row['close'] > row['ema_20'] and prev['close'] <= prev['ema_20']:
                        signal = "LONG"
                    elif row['close'] < row['ema_20'] and prev['close'] >= prev['ema_20']:
                        signal = "SHORT"
                    
                    if not signal: continue
                    
                    entry = row['close']
                    atr = row['atr']
                    sl_dist = atr * sl_mult
                    tp_dist = atr * tp_mult
                    
                    if signal == "LONG":
                        sl_price = entry - sl_dist
                        tp_price = entry + tp_dist
                    else:
                        sl_price = entry + sl_dist
                        tp_price = entry - tp_dist
                        
                    future_24 = df.iloc[i+1:i+25]
                    outcome = "TIMEOUT"
                    for _, f_row in future_24.iterrows():
                        if signal == "LONG":
                            if f_row['low'] <= sl_price:
                                outcome = "LOSS"
                                break
                            if f_row['high'] >= tp_price:
                                outcome = "WIN"
                                break
                        else:
                            if f_row['high'] >= sl_price:
                                outcome = "LOSS"
                                break
                            if f_row['low'] <= tp_price:
                                outcome = "WIN"
                                break
                    if outcome == "WIN": wins+=1
                    elif outcome == "LOSS": losses+=1
            total = wins+losses
            if total > 0:
                print(f"SL={sl_mult}xATR, TP={tp_mult}xATR -> WinRate: {wins/total*100:.1f}% ({wins}W / {losses}L)")

analyze_mfe_mae()
