
import pandas as pd
import yfinance as yf
import pandas_ta as ta
import numpy as np
import itertools
import warnings
import time
import math
warnings.filterwarnings('ignore')

SYMBOLS = ["ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "ICP-USD", "TON-USD", "SSV-USD", "BICO-USD"]
PERIOD = "3mo" # 3 months backtest

def clean_yf_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.ffill().bfill().dropna()
    df.columns = [c.lower() for c in df.columns]
    return df

def run_grid_search():
    print(f"--- BEAR HUNTER YENI NESIL GRID SEARCH BASLIYOR ({PERIOD}) ---")
    start_time = time.time()
    
    # 1. Fetch BTC data
    btc_raw = yf.download("BTC-USD", period=PERIOD, interval="1h", progress=False)
    btc_1h = clean_yf_df(btc_raw)
    if btc_1h.empty:
        print("BTC verisi alinamadi!")
        return
    
    btc_4h = btc_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
    btc_4h.ta.rsi(length=14, append=True)
    
    # 2. Fetch all symbol data and calculate indicators
    symbol_data = {}
    for sym in SYMBOLS:
        raw = yf.download(sym, period=PERIOD, interval="1h", progress=False)
        df_1h = clean_yf_df(raw)
        if df_1h.empty: continue
        df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        df_4h.ta.atr(length=14, append=True)
        df_4h.ta.rsi(length=14, append=True)
        df_4h.ta.ema(length=50, append=True)
        
        # align btc RSI
        df_4h['btc_rsi'] = btc_4h['RSI_14'].reindex(df_4h.index, method='ffill')
        
        symbol_data[sym] = df_4h
        
    print(f"Veriler indirildi ve indikatorler hesaplandi. Test basliyor...")
    
    # 3. Define Grid
    tol_list = [0.002, 0.005, 0.01]
    wick_list = [0.8, 1.2, 1.5]
    rsi_list = [0, 50, 55, 60] # 0 means no filter
    trend_list = [False, True] # True means price must be > EMA50
    btc_list = [100, 70, 65] # BTC RSI must be < this. 100 = no filter
    rr_list = [1.5, 2.0, 3.0]
    
    combinations = list(itertools.product(tol_list, wick_list, rsi_list, trend_list, btc_list, rr_list))
    total_combs = len(combinations)
    print(f"Toplam kombinasyon sayisi: {total_combs}")
    
    # Evaluate SFP logic once per symbol to save time.
    def get_sfp_signals(df, tol, wick):
        highs = df['high'].values
        closes = df['close'].values
        opens = df['open'].values
        
        signals = np.zeros(len(df), dtype=bool)
        
        for i in range(4, len(df)):
            # Find the last swing high before i
            swing_high = 0
            for j in range(i-2, 1, -1):
                if highs[j] > highs[j-1] and highs[j] > highs[j-2] and highs[j] > highs[j+1] and highs[j] > highs[j+2]:
                    swing_high = highs[j]
                    break
            
            if swing_high == 0: continue
            
            c = closes[i]
            o = opens[i]
            h = highs[i]
            
            if h > swing_high:
                body = abs(c - o)
                upper_wick = h - max(c, o)
                tol_zone = swing_high * (1 + tol)
                
                if c <= tol_zone and upper_wick > (body * wick):
                    signals[i] = True
                    
        return signals

    # Precalculate signals
    precalc_signals = {}
    for sym, df in symbol_data.items():
        precalc_signals[sym] = {}
        for tol in tol_list:
            for wick in wick_list:
                precalc_signals[sym][(tol, wick)] = get_sfp_signals(df, tol, wick)
                
    results_list = []
    
    for idx, (tol, wick, rsi_f, trnd, btc_f, rr) in enumerate(combinations):
        
        tot_wins = 0
        tot_losses = 0
        
        for sym, df in symbol_data.items():
            base_signals = precalc_signals[sym][(tol, wick)]
            
            rsi_cond = df['RSI_14'].values >= rsi_f
            if trnd:
                trend_cond = df['close'].values > df['EMA_50'].values
            else:
                trend_cond = np.ones(len(df), dtype=bool)
                
            btc_cond = df['btc_rsi'].values < btc_f
            
            valid_start = np.zeros(len(df), dtype=bool)
            valid_start[50:] = True
            
            final_signals = base_signals & rsi_cond & trend_cond & btc_cond & valid_start
            signal_indices = np.where(final_signals)[0]
            
            highs = df['high'].values
            lows = df['low'].values
            closes = df['close'].values
            atrs = df['ATRr_14'].values
            
            for i in signal_indices:
                atr_val = atrs[i] if not math.isnan(atrs[i]) else (closes[i] * 0.02)
                sl = closes[i] + (atr_val * 1.5)
                tp = closes[i] - (atr_val * 1.5 * rr)
                
                res = 0
                for j in range(i+1, len(df)):
                    if lows[j] <= tp:
                        res = 1
                        break
                    elif highs[j] >= sl:
                        res = -1
                        break
                        
                if res == 1:
                    tot_wins += 1
                elif res == -1:
                    tot_losses += 1
                    
        trades = tot_wins + tot_losses
        if trades > 0:
            win_rate = tot_wins / trades
            pnl = (tot_wins * rr) - (tot_losses * 1.0) # Assuming 1 unit risk per trade
            results_list.append({
                "Tol": tol,
                "Wick": wick,
                "RSI": rsi_f,
                "TrendUP": trnd,
                "BTC_RSI_<": btc_f,
                "RR": rr,
                "Trades": trades,
                "WinRate": round(win_rate * 100, 2),
                "PnL_Units": round(pnl, 2)
            })
            
    df_res = pd.DataFrame(results_list)
    
    if df_res.empty:
        print("Hiçbir kombinasyonda sinyal bulunamadı.")
        return
        
    df_res = df_res.sort_values(by="PnL_Units", ascending=False)
    
    print("\n[A] OPTIMUM (MAX PNL) - En yüksek kâr getiren strateji (Önerilen)")
    print(df_res.head(1).to_string(index=False))
    
    print("\n[B] SNIPER (MAX WIN RATE > 15 Trades) - Az islem ama en yuksek kazanma orani")
    sniper = df_res[df_res['Trades'] >= 15].sort_values(by="WinRate", ascending=False)
    if not sniper.empty:
        print(sniper.head(1).to_string(index=False))
    else:
        print("Yeterli islem sayisina ulasan Sniper strateji bulunamadi.")
        
    print("\n[C] AKTIF (MAX TRADES > 0 PnL) - Piyasada en cok firsat arayan, karda strateji")
    active = df_res[df_res['PnL_Units'] > 0].sort_values(by="Trades", ascending=False)
    if not active.empty:
        print(active.head(1).to_string(index=False))
    else:
        print("Karda olan aktif strateji bulunamadi.")
        
    print(f"\nGrid Search {time.time() - start_time:.1f} saniyede tamamlandi.")

if __name__ == '__main__':
    run_grid_search()
