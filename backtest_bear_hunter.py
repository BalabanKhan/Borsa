import yf_cache
import pandas as pd
import yfinance as yf
import pandas_ta as ta
import time
import math
import warnings
warnings.filterwarnings('ignore')

SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "MATIC-USD", "ICP-USD", "TON-USD", "SSV-USD", "BICO-USD"]
PERIOD = "1mo"
SFP_TOLERANCE_PCT = 0.005 # %0.5 tolerans (esnetilmiş SFP)

def clean_yf_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.ffill().bfill().dropna()
    df.columns = [c.lower() for c in df.columns]
    return df

def detect_sfp_relaxed(df):
    """Esnetilmiş SFP tespiti."""
    if len(df) < 10:
        return False, 0
    
    # 2 mum sağı solu düşük pivot high
    highs = df['high'].values
    pivots = []
    for i in range(2, len(df)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            pivots.append((i, highs[i]))
            
    if not pivots:
        return False, 0
        
    last_pivot_idx, swing_high = pivots[-1]
    
    current = df.iloc[-1]
    if float(current['high']) > swing_high:
        close_price = float(current['close'])
        open_price = float(current['open'])
        
        candle_body = abs(close_price - open_price)
        upper_wick = float(current['high']) - max(close_price, open_price)
        
        tolerance_zone = swing_high * (1 + SFP_TOLERANCE_PCT)
        
        # Eğer kapanış tolerans altındaysa VE üst fitil gövdeden büyükse (tuzak onayı)
        if close_price <= tolerance_zone and upper_wick > (candle_body * 1.5):
            return True, swing_high
            
    return False, 0

def check_relative_weakness(symbol_df, btc_df):
    """Göreli Zayıflık Kontrolü: BTC son 6 mumda (24 saat) ralli yaparken, altcoin eziliyorsa True."""
    if len(symbol_df) < 6 or len(btc_df) < 6:
        return False
        
    sym_ret = symbol_df['close'].iloc[-1] / symbol_df['close'].iloc[-6] - 1
    btc_ret = btc_df['close'].iloc[-1] / btc_df['close'].iloc[-6] - 1
    
    # BTC %1.5'den fazla çıkmışken, coin BTC'nin %30'undan az prim yapmışsa zayıftır.
    if btc_ret > 0.015 and sym_ret < (btc_ret * 0.3):
        return True
    return False

def run_backtest():
    print(f"--- BEAR HUNTER YENI NESIL BACKTEST BASLIYOR ({PERIOD}) ---")
    
    btc_raw = yf.download("BTC-USD", period=PERIOD, interval="1h", progress=False)
    btc_1h = clean_yf_df(btc_raw)
    if btc_1h.empty:
        print("BTC verisi alinamadi!")
        return
        
    btc_4h = btc_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
    btc_4h.ta.rsi(length=14, append=True)
    
    results = []
    all_trades = []
    
    for symbol in SYMBOLS:
        if symbol == "BTC-USD":
            continue
        try:
            raw = yf.download(symbol, period=PERIOD, interval="1h", progress=False)
            df_1h = clean_yf_df(raw)
            if df_1h.empty: continue
            
            df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            df_4h.ta.atr(length=14, append=True)
            df_4h.ta.rsi(length=14, append=True)
            df_4h.ta.ema(length=50, append=True)
            
            in_position = False
            sl = 0
            tp = 0
            current_trade = None
            
            total_trades = 0
            wins = 0
            losses = 0
            sfp_triggers = 0
            rw_triggers = 0
            
            for i in range(50, len(df_4h)): # Start at 50 for EMA
                current_candle = df_4h.iloc[i]
                current_idx = df_4h.index[i]
                current_price = float(current_candle['close'])
                
                if in_position:
                    if float(current_candle['low']) <= tp:
                        wins += 1
                        in_position = False
                        current_trade['Result'] = 'WIN'
                        all_trades.append(current_trade)
                    elif float(current_candle['high']) >= sl:
                        losses += 1
                        in_position = False
                        current_trade['Result'] = 'LOSS'
                        all_trades.append(current_trade)
                    continue
                
                slice_df = df_4h.iloc[:i+1]
                
                # Timestamp matching for BTC
                try:
                    btc_idx = btc_4h.index.get_loc(current_idx)
                    slice_btc = btc_4h.iloc[:btc_idx+1]
                    btc_rsi = btc_4h.iloc[btc_idx].get('RSI_14', 50)
                except KeyError:
                    slice_btc = btc_4h.iloc[:i+1]
                    btc_rsi = 50
                
                sfp_found, sfp_level = detect_sfp_relaxed(slice_df)
                is_weak = check_relative_weakness(slice_df, slice_btc)
                
                if sfp_found or is_weak:
                    rsi_val = current_candle.get('RSI_14', 50)
                    ema_val = current_candle.get('EMA_50', current_price)
                    trend = "UP" if current_price > ema_val else "DOWN"
                    
                    # YENI FILTRELER: RSI >= 55, Trend == UP, ve BTC RSI < 65 degilse girme
                    if rsi_val < 55 or trend == "DOWN" or btc_rsi >= 65:
                        continue
                        
                    total_trades += 1
                    if sfp_found: sfp_triggers += 1
                    if is_weak: rw_triggers += 1
                    
                    atr_val = current_candle.get('ATRr_14', current_price * 0.02)
                    if math.isnan(atr_val): atr_val = current_price * 0.02

                    
                    sl = current_price + (atr_val * 1.5) # ATR bazli Stop Loss
                    tp = current_price - (atr_val * 3.0) # 1:2 Risk/Reward
                    in_position = True
                    
                    current_trade = {
                        "Symbol": symbol.replace("-USD", ""),
                        "Type": "SFP" if sfp_found else "RW",
                        "EntryPrice": round(current_price, 4),
                        "RSI": round(rsi_val, 2),
                        "Trend": trend,
                        "Result": "PENDING"
                    }
                    
            if total_trades > 0:
                win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
                results.append({
                    "Symbol": symbol.replace("-USD", ""),
                    "Trades": total_trades,
                    "SFP": sfp_triggers,
                    "RW": rw_triggers,
                    "Wins": wins,
                    "Losses": losses,
                    "WinRate%": round(win_rate, 2)
                })
                
        except Exception as e:
            print(f"Hata {symbol}: {e}")
            
    print("\n--- SONUCLAR (Son 1 Ay) ---")
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        print(df_res.to_string(index=False))
        total_tr = df_res['Trades'].sum()
        tot_wins = df_res['Wins'].sum()
        tot_loss = df_res['Losses'].sum()
        tot_winrate = (tot_wins / (tot_wins + tot_loss)) * 100 if (tot_wins + tot_loss) > 0 else 0
        print(f"\nTOPLAM ISLEM: {total_tr}")
        print(f"KAZANC (TP): {tot_wins} | KAYIP (SL): {tot_loss}")
        print(f"ORTALAMA WIN RATE: %{tot_winrate:.2f}")
    else:
        print("Sinyal bulunamadi.")
        
    print("\n--- ZARAR EDEN (STOP) ISLEMLERIN ANALIZI ---")
    df_trades = pd.DataFrame(all_trades)
    if not df_trades.empty:
        loss_trades = df_trades[df_trades['Result'] == 'LOSS']
        win_trades = df_trades[df_trades['Result'] == 'WIN']
        
        print("\n[LOSS İşlemleri Ortalama Karakteristiği]")
        print(f"Ortalama RSI: {loss_trades['RSI'].mean():.2f}")
        print(f"Trend Durumu: \n{loss_trades['Trend'].value_counts().to_string()}")
        print(f"Sinyal Tipi: \n{loss_trades['Type'].value_counts().to_string()}")
        
        print("\n[WIN İşlemleri Ortalama Karakteristiği]")
        print(f"Ortalama RSI: {win_trades['RSI'].mean():.2f}")
        print(f"Trend Durumu: \n{win_trades['Trend'].value_counts().to_string()}")
        print(f"Sinyal Tipi: \n{win_trades['Type'].value_counts().to_string()}")
        
        print("\n--- TÜM KAYBEDEN (LOSS) İŞLEMLER ---")
        print(loss_trades.to_string(index=False))
        
        print("\n--- TÜM KAZANAN (WIN) İŞLEMLER ---")
        print(win_trades.to_string(index=False))

if __name__ == '__main__':
    run_backtest()
