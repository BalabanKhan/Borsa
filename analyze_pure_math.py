import pandas as pd
import numpy as np
from crypto_grid_search import fetch_data

def get_variant_d_trades(symbol_data):
    trades = []
    RR = 2.0
    
    for sym, df in symbol_data.items():
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        opens = df['open'].values
        volumes = df['volume'].values
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
            is_long_setup = (emas20[i] > emas50[i]) and (lows[i] <= emas20[i]) and (closes[i] > opens[i])
            is_short_setup = (emas20[i] < emas50[i]) and (highs[i] >= emas20[i]) and (closes[i] < opens[i])
            
            ema_diff_pct = abs(emas20[i] - emas50[i]) / closes[i]
            
            if is_whipsaw or adxs[i] > 45 or ema_diff_pct > 0.015: 
                continue 
            
            signal = None
            if is_long_setup and btc_trends[i] == 'UP': signal = "LONG"
            elif is_short_setup and btc_trends[i] == 'DOWN': signal = "SHORT"

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
                        if lows[j] <= sl: result = "LOSS"; break
                        elif highs[j] >= tp: result = "WIN"; break
                    else:
                        if highs[j] >= sl: result = 'LOSS'; break
                        elif lows[j] <= tp: result = 'WIN'; break
                            
                if result:
                    trade_date = df.index[i]
                    trades.append({
                        'Symbol': sym,
                        'Signal': signal,
                        'Result': result,
                        'Hour': trade_date.hour,
                        'DayOfWeek': trade_date.dayofweek,
                        'RSI': rsis[i],
                        'ADX': adxs[i],
                        'Relative_Volume': rel_vols[i],
                        'Volume': volumes[i],
                        'ATR_Pct': (atrs[i] / closes[i]) * 100,
                        'EMA_Diff_Pct': ema_diff_pct * 100,
                        'Distance_To_EMA20_Pct': abs(closes[i] - emas20[i]) / closes[i] * 100,
                        'Candle_Body_Pct': (body / closes[i]) * 100,
                        'Upper_Wick_Pct': (upper_wick / closes[i]) * 100,
                        'Lower_Wick_Pct': (lower_wick / closes[i]) * 100
                    })
                    
    return pd.DataFrame(trades)

def exhaustive_search():
    symbol_data = fetch_data()
    if not symbol_data: return
    
    df = get_variant_d_trades(symbol_data)
    if df.empty: return
    
    features = ['RSI', 'ADX', 'Relative_Volume', 'Volume', 'ATR_Pct', 'EMA_Diff_Pct', 'Distance_To_EMA20_Pct', 'Candle_Body_Pct', 'Upper_Wick_Pct', 'Lower_Wick_Pct', 'Hour', 'DayOfWeek']
    
    results = []
    
    for f in features:
        min_val = df[f].min()
        max_val = df[f].max()
        step = (max_val - min_val) / 50.0
        if step == 0: continue
        
        thresholds = np.arange(min_val, max_val, step)
        
        for t in thresholds:
            # Rule type 1: Skip if feature > threshold
            skipped_wins_gt = len(df[(df['Result'] == 'WIN') & (df[f] > t)])
            skipped_losses_gt = len(df[(df['Result'] == 'LOSS') & (df[f] > t)])
            
            if skipped_losses_gt > 10:
                ratio_gt = skipped_losses_gt / max(1, skipped_wins_gt)
                results.append({
                    'Rule': f"{f} > {t:.4f}",
                    'Wins_Sacrificed': skipped_wins_gt,
                    'Losses_Prevented': skipped_losses_gt,
                    'Ratio (Loss/Win)': ratio_gt,
                    'Net_R_Saved': (skipped_losses_gt * 1) - (skipped_wins_gt * 2)
                })
                
            # Rule type 2: Skip if feature < threshold
            skipped_wins_lt = len(df[(df['Result'] == 'WIN') & (df[f] < t)])
            skipped_losses_lt = len(df[(df['Result'] == 'LOSS') & (df[f] < t)])
            
            if skipped_losses_lt > 10:
                ratio_lt = skipped_losses_lt / max(1, skipped_wins_lt)
                results.append({
                    'Rule': f"{f} < {t:.4f}",
                    'Wins_Sacrificed': skipped_wins_lt,
                    'Losses_Prevented': skipped_losses_lt,
                    'Ratio (Loss/Win)': ratio_lt,
                    'Net_R_Saved': (skipped_losses_lt * 1) - (skipped_wins_lt * 2)
                })

    res_df = pd.DataFrame(results)
    
    # Sort by pure mathematical net R saved
    res_df = res_df.sort_values(by='Net_R_Saved', ascending=False)
    res_df = res_df.drop_duplicates(subset=['Wins_Sacrificed', 'Losses_Prevented'])
    
    print("\n" + "="*80)
    print("PURE MATH: BEST FILTERS TO ELIMINATE LOSSES WITHOUT SACRIFICING WINS")
    print("="*80)
    print(res_df.head(20).to_string(index=False))

if __name__ == '__main__':
    exhaustive_search()
