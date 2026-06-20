import pandas as pd
import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text
from crypto_grid_search import fetch_data

def get_variant_d_trades(symbol_data):
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
            
            is_long_setup = (emas20[i] > emas50[i]) and (lows[i] <= emas20[i]) and (closes[i] > opens[i])
            is_short_setup = (emas20[i] < emas50[i]) and (highs[i] >= emas20[i]) and (closes[i] < opens[i])
            
            ema_diff_pct = abs(emas20[i] - emas50[i]) / closes[i]
            
            if is_whipsaw or adxs[i] > 45 or ema_diff_pct > 0.015: 
                continue 
            
            signal = None
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
                    trade_date = df.index[i]
                    trades.append({
                        'Symbol': sym,
                        'Signal': signal,
                        'Result': result,
                        'Date': trade_date,
                        'Hour': trade_date.hour,
                        'DayOfWeek': trade_date.dayofweek,
                        'RSI': rsis[i],
                        'ADX': adxs[i],
                        'Relative_Volume': rel_vols[i],
                        'ATR_Pct': (atrs[i] / closes[i]) * 100,
                        'EMA_Diff_Pct': ema_diff_pct * 100,
                        'Distance_To_EMA20_Pct': abs(closes[i] - emas20[i]) / closes[i] * 100,
                        'Candle_Body_Pct': (body / closes[i]) * 100,
                    })
                    
    return pd.DataFrame(trades)

def deep_research_losses():
    symbol_data = fetch_data()
    if not symbol_data: return
    
    df = get_variant_d_trades(symbol_data)
    if df.empty: return
    
    wins = df[df['Result'] == 'WIN']
    losses = df[df['Result'] == 'LOSS']
    
    print("=== DEEP RESEARCH: VARIANT D (WINS VS LOSSES) ===")
    print(f"Total Wins: {len(wins)}, Total Losses: {len(losses)}")
    
    features = ['RSI', 'ADX', 'Relative_Volume', 'ATR_Pct', 'EMA_Diff_Pct', 'Distance_To_EMA20_Pct', 'Candle_Body_Pct', 'Hour']
    
    print("\n--- STATISTICAL COMPARISON (AVERAGE) ---")
    for f in features:
        w_avg = wins[f].mean()
        l_avg = losses[f].mean()
        diff = ((l_avg - w_avg) / w_avg * 100) if w_avg != 0 else 0
        print(f"{f:22s} | WINS: {w_avg:6.2f} | LOSSES: {l_avg:6.2f} | DIFF: {diff:+6.2f}%")

    # Decision Tree to find the best rules separating WIN and LOSS
    df['Is_Loss'] = (df['Result'] == 'LOSS').astype(int)
    X = df[features]
    y = df['Is_Loss']
    
    dt = DecisionTreeClassifier(max_depth=3, min_samples_leaf=10, random_state=42)
    dt.fit(X, y)
    
    print("\n--- DECISION TREE RULE EXTRACTION (What causes LOSS?) ---")
    tree_rules = export_text(dt, feature_names=features)
    print(tree_rules)
    
    # Feature importance
    print("\n--- FEATURE IMPORTANCE FOR PREDICTING LOSS ---")
    importances = pd.Series(dt.feature_importances_, index=features).sort_values(ascending=False)
    for feat, imp in importances.items():
        if imp > 0:
            print(f"{feat:22s}: {imp:.4f}")

if __name__ == '__main__':
    deep_research_losses()
