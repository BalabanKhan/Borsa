import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

SYMBOLS = ["ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD"]
PERIOD = "3mo" 

def clean_yf_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.ffill().bfill().dropna()
    df.columns = [c.lower() for c in df.columns]
    return df

def fetch_data():
    print(f"Fetching data for {PERIOD}...")
    btc_raw = yf.download("BTC-USD", period=PERIOD, interval="1h", progress=False)
    btc_1h = clean_yf_df(btc_raw)
    
    btc_4h = btc_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
    btc_4h.ta.rsi(length=14, append=True)
    btc_4h['EMA_50'] = ta.ema(btc_4h['close'], length=50)
    btc_4h['BTC_Trend'] = np.where(btc_4h['close'] > btc_4h['EMA_50'], 'UP', 'DOWN')
    
    symbol_data = {}
    for sym in SYMBOLS:
        raw = yf.download(sym, period=PERIOD, interval="1h", progress=False)
        df_1h = clean_yf_df(raw)
        if df_1h.empty: continue
        df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        df_4h.ta.atr(length=14, append=True)
        df_4h.ta.rsi(length=14, append=True)
        df_4h.ta.ema(length=20, append=True)
        df_4h.ta.ema(length=50, append=True)
        df_4h.ta.adx(length=14, append=True)
        
        df_4h['SMA_Volume_20'] = df_4h['volume'].rolling(window=20).mean()
        df_4h['Relative_Volume'] = df_4h['volume'] / df_4h['SMA_Volume_20']
        
        # Align BTC data
        df_4h['btc_trend'] = btc_4h['BTC_Trend'].reindex(df_4h.index, method='ffill')
        
        symbol_data[sym] = df_4h.dropna()
        
    return symbol_data

def run_strategy_variant(symbol_data, variant_name, conditions):
    trades = []
    RR = 2.0
    
    for sym, df in symbol_data.items():
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        opens = df['open'].values
        rsis = df['RSI_14'].values
        emas20 = df['EMA_20'].values
        emas50 = df['EMA_50'].values
        atrs = df['ATRr_14'].values
        rel_vols = df['Relative_Volume'].values
        btc_trends = df['btc_trend'].values
        
        if 'ADX_14' in df.columns:
            adxs = df['ADX_14'].values
        else:
            adxs = np.zeros(len(df))

        for i in range(50, len(df)-1):
            body = abs(closes[i] - opens[i])
            upper_wick = highs[i] - max(closes[i], opens[i])
            lower_wick = min(closes[i], opens[i]) - lows[i]
            
            is_whipsaw = (upper_wick > body * 2) or (lower_wick > body * 2)
            
            # Base Trend Long Setup (EMA 20 > EMA 50 & Pullback)
            is_long_setup = (emas20[i] > emas50[i]) and (lows[i] <= emas20[i]) and (closes[i] > opens[i])
            # Base Trend Short Setup (EMA 20 < EMA 50 & Pullback)
            is_short_setup = (emas20[i] < emas50[i]) and (highs[i] >= emas20[i]) and (closes[i] < opens[i])
            
            signal = None
            
            if variant_name == "A_BASELINE":
                if is_long_setup and rel_vols[i] > 1.0 and rsis[i] > 50:
                    signal = "LONG"
                elif is_short_setup and rel_vols[i] > 1.0 and rsis[i] < 50:
                    signal = "SHORT"
                    
            elif variant_name == "B_STRICT":
                if is_long_setup and rel_vols[i] > 1.5 and btc_trends[i] == 'UP':
                    signal = "LONG"
                elif is_short_setup and rsis[i] > 70 and btc_trends[i] == 'DOWN': # High RSI for short (overbought)
                    signal = "SHORT"
                    
            elif variant_name == "C_DYNAMIC":
                if is_whipsaw or adxs[i] > 45: 
                    continue # Ignore whipsaw or exhaustion
                
                if is_long_setup and btc_trends[i] == 'UP':
                    signal = "LONG"
                elif is_short_setup and btc_trends[i] == 'DOWN':
                    signal = "SHORT"
                    
            elif variant_name == "F_PURE_MATH":
                ema_diff_pct = abs(emas20[i] - emas50[i]) / closes[i]
                candle_body_pct = body / closes[i]
                
                # Base C rules
                if is_whipsaw or adxs[i] > 45 or ema_diff_pct > 0.015:
                    continue
                
                # Pure Math F rules
                if adxs[i] < 14.2 or rsis[i] > 57.82 or candle_body_pct > 0.0257:
                    continue
                    
                if is_long_setup and btc_trends[i] == 'UP':
                    signal = "LONG"
                elif is_short_setup and btc_trends[i] == 'DOWN':
                    signal = "SHORT"

            if signal:
                atr_val = atrs[i] if not np.isnan(atrs[i]) else (closes[i] * 0.02)
                
                # Dynamic Stop for C and F
                if variant_name in ["C_DYNAMIC", "F_PURE_MATH"]:
                    atr_mult = 2.0 if adxs[i] > 25 else 1.2
                else:
                    atr_mult = 1.5
                    
                if signal == "LONG":
                    sl = closes[i] - (atr_val * atr_mult)
                    tp = closes[i] + (atr_val * atr_mult * RR)
                else:
                    sl = closes[i] + (atr_val * atr_mult)
                    tp = closes[i] - (atr_val * atr_mult * RR)
                    
                result = None
                for j in range(i+1, len(df)):
                    if signal == "LONG":
                        if lows[j] <= sl:
                            result = "LOSS"
                            break
                        elif highs[j] >= tp:
                            result = "WIN"
                            break
                    else:
                        if highs[j] >= sl:
                            result = "LOSS"
                            break
                        elif lows[j] <= tp:
                            result = "WIN"
                            break
                            
                if result:
                    trades.append({
                        'Symbol': sym,
                        'Variant': variant_name,
                        'Signal': signal,
                        'Result': result,
                        'Date': df.index[i]
                    })
                    
    return pd.DataFrame(trades)

def print_report(df, name):
    print(f"\n{'='*40}")
    print(f"VARIANT {name} REPORT")
    print(f"{'='*40}")
    if df.empty:
        print("No trades executed.")
        return
        
    wins = len(df[df['Result'] == 'WIN'])
    losses = len(df[df['Result'] == 'LOSS'])
    total = wins + losses
    winrate = wins / total * 100
    pnl = (wins * 2.0) - losses
    
    print(f"Total Trades : {total}")
    print(f"Wins         : {wins}")
    print(f"Losses       : {losses}")
    print(f"Win Rate     : {winrate:.2f}%")
    print(f"Net PnL      : +{pnl:.2f} R")
    
def main():
    symbol_data = fetch_data()
    if not symbol_data: return
    
    df_a = run_strategy_variant(symbol_data, "A_BASELINE", {})
    df_b = run_strategy_variant(symbol_data, "B_STRICT", {})
    df_c = run_strategy_variant(symbol_data, "C_DYNAMIC", {})
    df_f = run_strategy_variant(symbol_data, "F_PURE_MATH", {})
    
    print_report(df_a, "A (Mevcut Durum / Baseline)")
    print_report(df_b, "B (Kati Filtre / Strict W/R)")
    print_report(df_c, "C (Dinamik Hacim & Volatilite)")
    print_report(df_f, "F (Saf Matematik / Pure Math) - FINAL YAPI")

if __name__ == "__main__":
    main()
