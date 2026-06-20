import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')

SYMBOLS = ["ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "ICP-USD", "TON-USD", "SSV-USD", "BICO-USD"]
PERIOD = "3mo" # 3 months backtest

def clean_yf_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.ffill().bfill().dropna()
    df.columns = [c.lower() for c in df.columns]
    return df

def run_analysis():
    print("Fetching data for 3 months...")
    btc_raw = yf.download("BTC-USD", period=PERIOD, interval="1h", progress=False)
    btc_1h = clean_yf_df(btc_raw)
    if btc_1h.empty:
        print("BTC verisi alinamadi!")
        return
    
    btc_4h = btc_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
    btc_4h.ta.rsi(length=14, append=True)
    btc_4h['BTC_24h_Return'] = btc_4h['close'].pct_change(periods=6)
    
    symbol_data = {}
    for sym in SYMBOLS:
        raw = yf.download(sym, period=PERIOD, interval="1h", progress=False)
        df_1h = clean_yf_df(raw)
        if df_1h.empty: continue
        df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        df_4h.ta.atr(length=14, append=True)
        df_4h.ta.rsi(length=14, append=True)
        df_4h.ta.ema(length=50, append=True)
        df_4h['SMA_Volume_20'] = df_4h['volume'].rolling(window=20).mean()
        df_4h['Relative_Volume'] = df_4h['volume'] / df_4h['SMA_Volume_20']
        
        df_4h['btc_rsi'] = btc_4h['RSI_14'].reindex(df_4h.index, method='ffill')
        df_4h['BTC_24h_Return'] = btc_4h['BTC_24h_Return'].reindex(df_4h.index, method='ffill')
        
        symbol_data[sym] = df_4h

    # Option A parameters
    TOLERANCE = 0.01
    WICK_RATIO = 0.8
    RSI_LIMIT = 50
    TREND_UP = True
    BTC_RSI_LIMIT = 100
    RR = 2.0
    
    trades = []
    
    print("Finding signals and running trades...")
    for sym, df in symbol_data.items():
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        opens = df['open'].values
        rsis = df['RSI_14'].values
        emas = df['EMA_50'].values
        atrs = df['ATRr_14'].values
        btc_rsis = df['btc_rsi'].values
        
        for i in range(50, len(df)-1):
            if rsis[i] < RSI_LIMIT: continue
            if TREND_UP and closes[i] <= emas[i]: continue
            if pd.notnull(btc_rsis[i]) and btc_rsis[i] > BTC_RSI_LIMIT: continue
            
            # Find swing high
            swing_high = 0
            for j in range(i-2, 1, -1):
                if highs[j] > highs[j-1] and highs[j] > highs[j-2] and highs[j] > highs[j+1] and highs[j] > highs[j+2]:
                    swing_high = highs[j]
                    break
            
            if swing_high == 0: continue
            
            if highs[i] > swing_high:
                body = abs(closes[i] - opens[i])
                upper_wick = highs[i] - max(closes[i], opens[i])
                tol_zone = swing_high * (1 + TOLERANCE)
                
                if closes[i] <= tol_zone and upper_wick > (body * WICK_RATIO):
                    # Signal!
                    atr_val = atrs[i] if not np.isnan(atrs[i]) else (closes[i] * 0.02)
                    sl = closes[i] + (atr_val * 1.5)
                    tp = closes[i] - (atr_val * 1.5 * RR)
                    
                    result = None
                    for j in range(i+1, len(df)):
                        if lows[j] <= tp:
                            result = "WIN"
                            break
                        elif highs[j] >= sl:
                            result = "LOSS"
                            break
                            
                    if result:
                        trades.append({
                            'Symbol': sym,
                            'Result': result,
                            'RSI': rsis[i],
                            'Rel_Volume': df['Relative_Volume'].iloc[i],
                            'Wick_Pct': (upper_wick / body) if body>0 else 0,
                            'Dist_EMA50': ((closes[i] - emas[i]) / emas[i]) * 100,
                            'Hour': df.index[i].hour,
                            'BTC_24h_Ret': df['BTC_24h_Return'].iloc[i] * 100
                        })

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        print("No trades found.")
        return
        
    wins = trades_df[trades_df['Result'] == 'WIN']
    losses = trades_df[trades_df['Result'] == 'LOSS']
    
    print(f"\nTotal Trades: {len(trades_df)}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print("-" * 50)
    
    metrics = ['RSI', 'Rel_Volume', 'Wick_Pct', 'Dist_EMA50', 'BTC_24h_Ret']
    
    print(f"{'Metric':<15} | {'WIN Mean':<12} | {'LOSS Mean':<12} | {'Diff'}")
    print("-" * 50)
    for m in metrics:
        w_mean = wins[m].mean()
        l_mean = losses[m].mean()
        diff = l_mean - w_mean
        print(f"{m:<15} | {w_mean:>12.2f} | {l_mean:>12.2f} | {diff:>+8.2f}")
        
    print("\nLosses by Hour (UTC):")
    print(losses['Hour'].value_counts().sort_index())
    print("\nWins by Hour (UTC):")
    print(wins['Hour'].value_counts().sort_index())
    
    # Simulate Filtered Results
    print("\n" + "="*50)
    print("FILTER SIMULATION: Rel_Volume > 1.5 AND Hour != 20")
    filtered = trades_df[(trades_df['Rel_Volume'] > 1.5) & (trades_df['Hour'] != 20)]
    f_wins = len(filtered[filtered['Result'] == 'WIN'])
    f_losses = len(filtered[filtered['Result'] == 'LOSS'])
    f_trades = len(filtered)
    if f_trades > 0:
        f_winrate = f_wins / f_trades * 100
        f_pnl = (f_wins * 2.0) - f_losses
        print(f"Trades: {f_trades} | Wins: {f_wins} | Losses: {f_losses}")
        print(f"Win Rate: {f_winrate:.2f}% | Net PnL: +{f_pnl:.2f} Units")
    else:
        print("No trades left after filter.")
    print("="*50)

if __name__ == "__main__":
    run_analysis()
