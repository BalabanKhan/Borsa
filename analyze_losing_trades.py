import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
from scipy.signal import find_peaks
import warnings

warnings.filterwarnings('ignore')

SYMBOLS = ["ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "ICP-USD", "TON-USD", "SSV-USD", "BICO-USD"]
PERIOD = "3mo"

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
    if btc_1h.empty: return
    
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

    TOLERANCE, WICK_RATIO, RSI_LIMIT, TREND_UP, BTC_RSI_LIMIT, RR = 0.01, 0.8, 50, True, 100, 2.0
    trades = []
    
    print("Finding signals and running trades...")
    for sym, df in symbol_data.items():
        highs, lows, closes, opens = df['high'].values, df['low'].values, df['close'].values, df['open'].values
        rsis, emas, atrs, btc_rsis = df['RSI_14'].values, df['EMA_50'].values, df['ATRr_14'].values, df['btc_rsi'].values
        
        # ponytail: vectorized peak finding replacing manual nested loop
        peaks, _ = find_peaks(highs, distance=3)
        
        for i in range(50, len(df)-1):
            if rsis[i] < RSI_LIMIT or (TREND_UP and closes[i] <= emas[i]) or (pd.notnull(btc_rsis[i]) and btc_rsis[i] > BTC_RSI_LIMIT):
                continue
            
            valid_peaks = peaks[peaks < i]
            if len(valid_peaks) == 0: continue
            swing_high = highs[valid_peaks[-1]]
            
            if highs[i] > swing_high:
                body = abs(closes[i] - opens[i])
                upper_wick = highs[i] - max(closes[i], opens[i])
                
                if closes[i] <= swing_high * (1 + TOLERANCE) and upper_wick > (body * WICK_RATIO):
                    atr_val = atrs[i] if not np.isnan(atrs[i]) else (closes[i] * 0.02)
                    sl = closes[i] + (atr_val * 1.5)
                    tp = closes[i] - (atr_val * 1.5 * RR)
                    
                    # ponytail: argmax instead of inner loop for exit check
                    fwd_highs = highs[i+1:]
                    fwd_lows = lows[i+1:]
                    hit_sl = np.argmax(fwd_highs >= sl)
                    hit_tp = np.argmax(fwd_lows <= tp)
                    
                    sl_idx = hit_sl if fwd_highs[hit_sl] >= sl else len(fwd_highs)
                    tp_idx = hit_tp if fwd_lows[hit_tp] <= tp else len(fwd_lows)
                    
                    if tp_idx < sl_idx: result = "WIN"
                    elif sl_idx < tp_idx: result = "LOSS"
                    else: result = None
                            
                    if result:
                        trades.append({
                            'Symbol': sym, 'Result': result, 'RSI': rsis[i],
                            'Rel_Volume': df['Relative_Volume'].iloc[i],
                            'Wick_Pct': (upper_wick / body) if body>0 else 0,
                            'Dist_EMA50': ((closes[i] - emas[i]) / emas[i]) * 100,
                            'Hour': df.index[i].hour, 'BTC_24h_Ret': df['BTC_24h_Return'].iloc[i] * 100
                        })

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        print("No trades found.")
        return
        
    wins, losses = trades_df[trades_df['Result'] == 'WIN'], trades_df[trades_df['Result'] == 'LOSS']
    
    print(f"\nTotal Trades: {len(trades_df)}\nWins: {len(wins)} | Losses: {len(losses)}\n" + "-" * 50)
    print(f"{'Metric':<15} | {'WIN Mean':<12} | {'LOSS Mean':<12} | {'Diff'}\n" + "-" * 50)
    
    for m in ['RSI', 'Rel_Volume', 'Wick_Pct', 'Dist_EMA50', 'BTC_24h_Ret']:
        w, l = wins[m].mean(), losses[m].mean()
        print(f"{m:<15} | {w:>12.2f} | {l:>12.2f} | {l - w:>+8.2f}")
        
    print("\nLosses by Hour (UTC):"); print(losses['Hour'].value_counts().sort_index())
    print("\nWins by Hour (UTC):"); print(wins['Hour'].value_counts().sort_index())

if __name__ == "__main__":
    run_analysis()
