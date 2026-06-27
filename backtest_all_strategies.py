import yf_cache
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import warnings

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
        
        # Approximate 1D EMAs
        df_4h['1D_EMA_20'] = df_4h['close'].ewm(span=20*6, adjust=False).mean()
        df_4h['1D_EMA_50'] = df_4h['close'].ewm(span=50*6, adjust=False).mean()
        
        symbol_data[sym] = df_4h.dropna()
        
    return symbol_data

def run_strategies(symbol_data):
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
        emas1d20 = df['1D_EMA_20'].values
        emas1d50 = df['1D_EMA_50'].values
        atrs = df['ATRr_14'].values
        rel_vols = df['Relative_Volume'].values
        adxs = df['ADX_14'].values if 'ADX_14' in df.columns else np.zeros(len(df))

        for i in range(50, len(df)-1):
            body = abs(closes[i] - opens[i])
            upper_wick = highs[i] - max(closes[i], opens[i])
            lower_wick = min(closes[i], opens[i]) - lows[i]
            
            signals = []
            
            # STRATEGY: Crypto 2 Mega Trend (Long)
            # 1D EMA20 > 1D EMA50, 4H Pullback to 4H EMA50
            if emas1d20[i] > emas1d50[i]:
                if lows[i] <= emas50[i] and closes[i] > emas50[i] and closes[i] > opens[i]:
                    signals.append(("Mega Trend", "LONG"))
                    
            # STRATEGY: Crypto Short 2 Waterfall (Short)
            # 1D EMA20 < 1D EMA50, 4H pullback to 4H EMA20 and reject
            if emas1d20[i] < emas1d50[i]:
                if highs[i] >= emas20[i] and closes[i] < emas20[i] and closes[i] < opens[i]:
                    signals.append(("Waterfall", "SHORT"))
                    
            # STRATEGY: Crypto Short 1 FOMO
            # RSI > 70 and bearish candle
            if rsis[i] > 70 and closes[i] < opens[i]:
                signals.append(("FOMO Short", "SHORT"))
                
            # STRATEGY: Liquidation Dip (Long)
            # RSI < 30 and bullish candle
            if rsis[i] < 30 and closes[i] > opens[i]:
                signals.append(("Liquidation", "LONG"))

            for strat_name, sig_dir in signals:
                atr_val = atrs[i] if not np.isnan(atrs[i]) else (closes[i] * 0.02)
                atr_mult = 1.5
                
                if sig_dir == "LONG":
                    sl = closes[i] - (atr_val * atr_mult)
                    tp = closes[i] + (atr_val * atr_mult * RR)
                else:
                    sl = closes[i] + (atr_val * atr_mult)
                    tp = closes[i] - (atr_val * atr_mult * RR)
                    
                result = None
                for j in range(i+1, len(df)):
                    if sig_dir == "LONG":
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
                        'Strategy': strat_name,
                        'Signal': sig_dir,
                        'Result': result,
                        'Date': df.index[i],
                        'RSI': rsis[i],
                        'ADX': adxs[i],
                        'Relative_Volume': rel_vols[i],
                        'ATR_Pct': (atrs[i] / closes[i]) * 100,
                        'EMA_Diff_Pct': abs(emas20[i] - emas50[i]) / closes[i] * 100,
                        'Candle_Body_Pct': (body / closes[i]) * 100
                    })
                    
    return pd.DataFrame(trades)

def main():
    symbol_data = fetch_data()
    if not symbol_data: return
        
    trades_df = run_strategies(symbol_data)
    trades_df.to_csv("backtest_all_strategies_results.csv", index=False)
    
    strategies = trades_df['Strategy'].unique()
    print("\n" + "="*50)
    print("ALL STRATEGIES BACKTEST REPORT")
    print("="*50)
    
    for s in strategies:
        s_df = trades_df[trades_df['Strategy'] == s]
        wins = len(s_df[s_df['Result'] == 'WIN'])
        losses = len(s_df[s_df['Result'] == 'LOSS'])
        total = wins + losses
        winrate = wins / total * 100 if total > 0 else 0
        pnl = (wins * 2.0) - losses
        
        print(f"\n{s}")
        print(f"Total Signals : {total}")
        print(f"Wins / Losses : {wins} / {losses}")
        print(f"Win Rate      : {winrate:.2f}%")
        print(f"Net PnL       : {pnl:.2f} R")

if __name__ == "__main__":
    main()
