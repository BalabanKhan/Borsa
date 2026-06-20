import pandas as pd
import numpy as np
from crypto_grid_search import fetch_data

def run_variant_c_analysis(symbol_data):
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
            
            # Base Trend Setup
            is_long_setup = (emas20[i] > emas50[i]) and (lows[i] <= emas20[i]) and (closes[i] > opens[i])
            is_short_setup = (emas20[i] < emas50[i]) and (highs[i] >= emas20[i]) and (closes[i] < opens[i])
            
            signal = None
            
            # Variant C Logic
            if is_whipsaw or adxs[i] > 45: 
                continue 
            
            if is_long_setup and btc_trends[i] == 'UP':
                signal = "LONG"
            elif is_short_setup and btc_trends[i] == 'DOWN':
                signal = "SHORT"

            if signal:
                atr_val = atrs[i] if not np.isnan(atrs[i]) else (closes[i] * 0.02)
                atr_mult = 2.0 if adxs[i] > 25 else 1.2
                    
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
                        'Signal': signal,
                        'Result': result,
                        'Date': df.index[i],
                        'RSI': rsis[i],
                        'ADX': adxs[i],
                        'Relative_Volume': rel_vols[i],
                        'ATR_Pct': atrs[i] / closes[i] * 100,
                        'EMA_Diff_Pct': abs(emas20[i] - emas50[i]) / closes[i] * 100
                    })
                    
    return pd.DataFrame(trades)

def main():
    symbol_data = fetch_data()
    if not symbol_data: 
        print("No data.")
        return
    
    df = run_variant_c_analysis(symbol_data)
    
    if df.empty:
        print("No trades found.")
        return
        
    wins = df[df['Result'] == 'WIN']
    losses = df[df['Result'] == 'LOSS']
    
    print("=== VARIANT C ANALYSIS: WINS VS LOSSES ===")
    print(f"Total Wins: {len(wins)}, Total Losses: {len(losses)}")
    
    features = ['RSI', 'ADX', 'Relative_Volume', 'ATR_Pct', 'EMA_Diff_Pct']
    
    print("\n--- AVERAGE VALUES ---")
    for f in features:
        win_avg = wins[f].mean()
        loss_avg = losses[f].mean()
        print(f"{f:15s} -> WINS: {win_avg:.2f} | LOSSES: {loss_avg:.2f}")

    print("\n--- MEDIAN VALUES ---")
    for f in features:
        win_med = wins[f].median()
        loss_med = losses[f].median()
        print(f"{f:15s} -> WINS: {win_med:.2f} | LOSSES: {loss_med:.2f}")

if __name__ == '__main__':
    main()
