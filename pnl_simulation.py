import pandas as pd
import pandas_ta as ta
import yfinance as yf
import ccxt
from datetime import datetime, timedelta
import logging
import warnings
import sys

sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')



from data_fetcher import TOP_BIST, TOP_CRYPTO

# Simulation parameters
start_sim = pd.to_datetime("2026-06-08 00:00:00")
end_sim = pd.to_datetime("2026-06-12 23:59:59")

exchange = ccxt.binance({'enableRateLimit': True})

completed_trades = []

def simulate_bist():
    print("BIST PnL Simülasyonu Başlatılıyor...")
    for sym in TOP_BIST:
        df_1h = yf.download(sym, start=start_sim - timedelta(days=60), end=end_sim + timedelta(days=1), interval="1h", progress=False)
        df_1d = yf.download(sym, start=start_sim - timedelta(days=180), end=end_sim + timedelta(days=1), interval="1d", progress=False)
        
        if df_1h.empty or df_1d.empty:
            continue
            
        if isinstance(df_1h.columns, pd.MultiIndex):
            df_1h.columns = df_1h.columns.droplevel(1)
        if isinstance(df_1d.columns, pd.MultiIndex):
            df_1d.columns = df_1d.columns.droplevel(1)
            
        df_1h.columns = [c.lower() for c in df_1h.columns]
        df_1d.columns = [c.lower() for c in df_1d.columns]
        df_1h = df_1h.dropna()
        df_1d = df_1d.dropna()
        
        df_1h.index = df_1h.index.tz_localize(None)
        df_1d.index = df_1d.index.tz_localize(None)
        
        # === ÖN HESAPLAMA: İndikatörleri döngü dışında tek seferlik hesapla (O(N²) → O(N)) ===
        df_1h['vol_sma_20'] = ta.sma(df_1h['volume'], length=20)
        df_1h.ta.rsi(length=14, append=True)
        df_1h.ta.ema(length=8, append=True)
        df_1h.ta.ema(length=13, append=True)
        
        df_1d.ta.rsi(length=14, append=True)
        df_1d.ta.ema(length=8, append=True)
        df_1d.ta.ema(length=21, append=True)
        df_1d.ta.bbands(length=20, std=2, append=True)
        df_1d.ta.atr(length=14, append=True)
        
        df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        if len(df_4h) < 20: continue
        df_4h.ta.adx(length=14, append=True)
        df_4h.ta.ema(length=5, append=True)
        df_4h.ta.ema(length=13, append=True)
        
        sim_bars = df_1h[(df_1h.index >= start_sim) & (df_1h.index <= end_sim)]
        open_trade = None
        
        for idx, row in sim_bars.iterrows():
            curr_time = idx
            
            if open_trade is not None:
                profit_pct = ((row['high'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                
                if profit_pct >= 5.0 and not open_trade.get("partial_tp_hit", False):
                    open_trade["partial_tp_hit"] = True
                    if open_trade['sl'] < open_trade['entry_price']:
                        open_trade['sl'] = open_trade['entry_price']

                if profit_pct >= 15.0:
                    current_trailing_dist = row['high'] * 0.025
                elif profit_pct >= 10.0:
                    current_trailing_dist = row['high'] * 0.040
                else:
                    current_trailing_dist = open_trade['trailing_dist']

                # TRAILING STOP GÜNCELLEMESİ
                if row['high'] > open_trade['highest_high']:
                    open_trade['highest_high'] = row['high']
                    new_sl = open_trade['highest_high'] - current_trailing_dist
                    if new_sl > open_trade['sl']:
                        open_trade['sl'] = new_sl

                # SADECE STOP-LOSS (TRAILING) İLE ÇIKIŞ (Take Profit iptal, trend sonuna kadar sürülür)
                if row['low'] <= open_trade['sl']:
                    # KARA KUĞU (BLACK SWAN) ŞALTERİ
                    if row['low'] <= open_trade['sl'] * 0.97:
                        open_trade['exit_time'] = curr_time
                        open_trade['exit_price'] = min(open_trade['sl'] * 0.97, row['low'])
                        open_trade['status'] = 'KARA KUĞU (ACİL SAT)'
                        if open_trade.get("partial_tp_hit", False):
                            pnl_2 = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                            open_trade['pnl_pct'] = (5.0 + pnl_2) / 2.0
                        else:
                            open_trade['pnl_pct'] = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                        completed_trades.append(open_trade)
                        open_trade = None
                        print(f"\n🚨 KIRMIZI ALARM: {sym} ({curr_time}) - Fiyat aniden %3'ten fazla çakıldı. Savaş Masası İPTAL, ACİL SATILDI!")
                        continue
                        
                    # SAVAŞ MASASI KONTROL LİSTESİ (Mum kapanışında)
                    if row['close'] > open_trade['sl']:
                        # Sadece iğne (fitil) atmış, stop seviyesi üstünde kapatmış. Tuzağa düşme.
                        continue
                        
                    score = 0
                    report = []
                    
                    # 1. Mum Anatomisi Testi (Doji korumalı)
                    body = abs(row['open'] - row['close'])
                    candle_range = row['high'] - row['low']
                    lower_wick = min(row['close'], row['open']) - row['low']
                    if candle_range > 0 and body < candle_range * 0.05:
                        report.append("🕯️ Mum Testi: Doji Mum (Kararsızlık) (0 Puan)")
                    elif body > 0 and lower_wick >= (body * 1.5):
                        score += 1
                        report.append("🕯️ Mum Testi: Alt İğne >= Gövde x1.5 (+1 Puan)")
                    else:
                        report.append("🕯️ Mum Testi: Tok Gövde (0 Puan)")
                        
                    # 2. Hacim Emilim Testi (önceden hesaplanmış değerler)
                    last_vol_sma = row.get('vol_sma_20')
                    current_vol = row['volume']
                    
                    if pd.isna(last_vol_sma) or current_vol < last_vol_sma:
                        score += 1
                        report.append("📊 Hacim Testi: Cılız Hacim (+1 Puan)")
                    elif current_vol > (2.0 * last_vol_sma) and lower_wick >= body:
                        score += 1
                        report.append("📊 Hacim Testi: Devasa Hacim Emilimi (+1 Puan)")
                    else:
                        report.append("📊 Hacim Testi: Satış Baskısı (0 Puan)")
                        
                    # 3. RSI Röntgeni Testi (önceden hesaplanmış değerler)
                    current_rsi = row.get('RSI_14')
                    
                    curr_pos = df_1h.index.get_loc(curr_time)
                    lookback_start = max(0, curr_pos - 20)
                    lookback_window = df_1h.iloc[lookback_start:curr_pos]
                    if not lookback_window.empty and not pd.isna(current_rsi):
                        prev_low_idx = lookback_window['low'].idxmin()
                        prev_low_price = lookback_window.loc[prev_low_idx, 'low']
                        prev_rsi = lookback_window.loc[prev_low_idx, 'RSI_14']
                        
                        if not pd.isna(prev_rsi) and row['low'] < prev_low_price and current_rsi > prev_rsi:
                            score += 1
                            report.append("🔬 RSI Testi: Pozitif Uyumsuzluk Var (+1 Puan)")
                        else:
                            report.append("🔬 RSI Testi: Uyumsuzluk Yok (0 Puan)")
                    else:
                        report.append("🔬 RSI Testi: Yetersiz Veri (0 Puan)")
                        
                    print(f"\n⚠️ STOP İHLALİ TESPİT EDİLDİ: {sym} ({curr_time})")
                    print(f"Fiyat dinamik stopun ({open_trade['sl']:.2f}) altına indi. Savaş Masası Testleri Başladı:")
                    for r in report:
                        print(r)
                    print(f"🧮 TOPLAM SKOR: {score} / 3")
                    
                    if score >= 2:
                        print("🤖 ASİSTAN KARARI: İŞLEMDE KAL! (SATMA). Tahtacı stop patlatıyor olabilir.")
                        continue
                    else:
                        print("🤖 ASİSTAN KARARI: GERÇEK ÇÖKÜŞ (SAT).")
                        open_trade['exit_time'] = curr_time
                        open_trade['exit_price'] = row['close'] # Mum kapandığı anki fiyat
                        open_trade['status'] = 'GERÇEK ÇÖKÜŞ (SAT)'
                        if open_trade.get("partial_tp_hit", False):
                            pnl_2 = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                            open_trade['pnl_pct'] = (5.0 + pnl_2) / 2.0
                        else:
                            open_trade['pnl_pct'] = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                        completed_trades.append(open_trade)
                        open_trade = None
                        continue

            if open_trade is None:
                # İndikatörler döngü öncesinde hesaplandı, sadece ilgili satırları oku
                curr_day = curr_time.normalize()
                avail_1d = df_1d[df_1d.index <= curr_day]
                avail_4h = df_4h[df_4h.index <= curr_time]
                
                if len(avail_1d) < 30 or len(avail_4h) < 20: continue
                
                last_1d = avail_1d.iloc[-1]
                last_4h = avail_4h.iloc[-1]
                last_1h = row  # Mevcut mum (önceden hesaplanmış indikatörlerle)
                curr_pos = df_1h.index.get_loc(curr_time)
                if curr_pos < 1: continue
                prev_1h = df_1h.iloc[curr_pos - 1]
                current_price = last_1h['close']
                
                atr_val = last_1d.get('ATRr_14', last_1d.get('ATR_14'))
                if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
                dynamic_sl_dist = max(2.0 * atr_val, current_price * 0.03)
                
                # BIST 1: Dip Avcılığı (Eski güvenli hal: RSI 35)
                if last_1d.get('RSI_14', 100) < 35 and current_price > last_1d.get('EMA_8', current_price*2):
                    if last_1h['close'] > last_1h.get('EMA_8', current_price*2) and last_1h['close'] > last_1h['open']:
                        if last_1h.get('RSI_14', 0) > prev_1h.get('RSI_14', 100):
                            sl = current_price - dynamic_sl_dist
                            open_trade = {
                                'symbol': sym, 'market': 'BIST', 'strategy': 'Dip Avcılığı', 'entry_time': curr_time,
                                'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
                            }
                            continue

                # BIST 2: Trend Takibi (Eski güvenli hal: ADX 25)
                if last_4h.get('ADX_14', 0) > 25 and last_4h.get('EMA_5', 0) > last_4h.get('EMA_13', current_price*2):
                    if last_1h['low'] <= last_1h.get('EMA_13', 0) and last_1h['close'] > last_1h.get('EMA_13', current_price*2) and last_1h['close'] > last_1h['open']:
                        sl = current_price - dynamic_sl_dist
                        open_trade = {
                            'symbol': sym, 'market': 'BIST', 'strategy': 'Trend Takibi', 'entry_time': curr_time,
                            'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
                        }
                        continue
                        
                # BIST 3: Breakout (Eski güvenli hal: BB width 0.15)
                bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
                bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
                bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]
                if bb_upper_col and bb_lower_col and bb_mid_col:
                    bbu = last_1d[bb_upper_col[0]]
                    bbl = last_1d[bb_lower_col[0]]
                    bbm = last_1d[bb_mid_col[0]]
                    bb_width = (bbu - bbl) / bbm if bbm != 0 else 1
                    avail_1d_for_high = df_1d[df_1d.index <= curr_day]
                    if bb_width < 0.15:
                        month_high = avail_1d_for_high['high'].tail(30).max() if len(avail_1d_for_high) >= 30 else avail_1d_for_high['high'].max()
                        if current_price > month_high:
                            if not pd.isna(last_1h.get('vol_sma_20')):
                                if last_1h['volume'] > (1.3 * last_1h['vol_sma_20']):
                                    sl = current_price - dynamic_sl_dist
                                    open_trade = {
                                        'symbol': sym, 'market': 'BIST', 'strategy': 'Breakout', 'entry_time': curr_time,
                                        'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
                                    }
                                    continue
        
        if open_trade is not None:
            last_bar = sim_bars.iloc[-1]
            open_trade['exit_time'] = sim_bars.index[-1]
            open_trade['exit_price'] = last_bar['close']
            open_trade['status'] = 'OPEN_AT_END'
            end_pnl = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
            if open_trade.get("partial_tp_hit", False):
                open_trade['pnl_pct'] = (5.0 + end_pnl) / 2.0
            else:
                open_trade['pnl_pct'] = end_pnl
            completed_trades.append(open_trade)

def simulate_crypto():
    print("Kripto PnL Simülasyonu Başlatılıyor...")
    
    start_ts = int(start_sim.timestamp() * 1000) - (60 * 24 * 60 * 60 * 1000)
    end_ts = int(end_sim.timestamp() * 1000)
    
    df_btc = None
    try:
        btc_ohlcv = exchange.fetch_ohlcv("BTC/USDT", '1d', since=start_ts, limit=1000)
        if btc_ohlcv:
            df_btc = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_btc['timestamp'] = pd.to_datetime(df_btc['timestamp'], unit='ms')
            df_btc.set_index('timestamp', inplace=True)
    except Exception as e:
        logging.warning(f"[simulate_crypto] BTC veri çekme hatası: {e}")
    
    for sym in TOP_CRYPTO:
        try:
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', since=start_ts, limit=1000)
            if not ohlcv_4h: continue
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['timestamp'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            df_4h.set_index('timestamp', inplace=True)
            
            df_1d = df_4h.resample('1d').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            
            # === ÖN HESAPLAMA: İndikatörleri döngü dışında tek seferlik hesapla ===
            df_4h['vol_sma_20'] = ta.sma(df_4h['volume'], length=20)
            df_4h.ta.rsi(length=14, append=True)
            df_4h.ta.ema(length=20, append=True)
            df_4h.ta.ema(length=50, append=True)
            df_4h.ta.adx(length=14, append=True)
            df_4h.ta.atr(length=14, append=True)
            
            df_1d.ta.ema(length=20, append=True)
            df_1d.ta.ema(length=50, append=True)
            df_1d.ta.bbands(length=20, std=2, append=True)
            
            sim_bars = df_4h[(df_4h.index >= start_sim) & (df_4h.index <= end_sim)]
            
            open_trade = None
            
            for idx, row in sim_bars.iterrows():
                curr_time = idx
                
                if open_trade is not None:
                    is_short = open_trade.get('signal') == 'SAT'
                    
                    if not is_short:
                        profit_pct = ((row['high'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                        
                        if profit_pct >= 5.0 and not open_trade.get("partial_tp_hit", False):
                            open_trade["partial_tp_hit"] = True
                            if open_trade['sl'] < open_trade['entry_price']:
                                open_trade['sl'] = open_trade['entry_price']
                                
                        if profit_pct >= 15.0:
                            current_trailing_dist = row['high'] * 0.005
                        elif profit_pct >= 10.0:
                            current_trailing_dist = row['high'] * 0.015
                        else:
                            current_trailing_dist = open_trade['trailing_dist']

                        # TRAILING STOP GÜNCELLEMESİ
                        if row['high'] > open_trade['highest_high']:
                            open_trade['highest_high'] = row['high']
                            new_sl = open_trade['highest_high'] - current_trailing_dist
                            if new_sl > open_trade['sl']:
                                open_trade['sl'] = new_sl

                        if row['low'] <= open_trade['sl']:
                            # KARA KUĞU (BLACK SWAN) ŞALTERİ
                            if row['low'] <= open_trade['sl'] * 0.97:
                                open_trade['exit_time'] = curr_time
                                open_trade['exit_price'] = min(open_trade['sl'] * 0.97, row['low'])
                                open_trade['status'] = 'KARA KUĞU (ACİL SAT)'
                                if open_trade.get("partial_tp_hit", False):
                                    pnl_2 = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                                    open_trade['pnl_pct'] = (5.0 + pnl_2) / 2.0
                                else:
                                    open_trade['pnl_pct'] = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                                completed_trades.append(open_trade)
                                open_trade = None
                                print(f"\n🚨 KIRMIZI ALARM: {sym} ({curr_time}) - Fiyat aniden %3'ten fazla çakıldı. Savaş Masası İPTAL, ACİL SATILDI!")
                                continue
                                
                            if row['close'] > open_trade['sl']:
                                continue
                                
                            score = 0
                            report = []
                            body = abs(row['open'] - row['close'])
                            candle_range = row['high'] - row['low']
                            lower_wick = min(row['close'], row['open']) - row['low']
                            if candle_range > 0 and body < candle_range * 0.05:
                                report.append("🕯️ Mum Testi: Doji Mum (Kararsızlık) (0 Puan)")
                            elif body > 0 and lower_wick >= (body * 1.5):
                                score += 1
                                report.append("🕯️ Mum Testi: Alt İğne >= Gövde x1.5 (+1 Puan)")
                            else:
                                report.append("🕯️ Mum Testi: Tok Gövde (0 Puan)")
                                
                            last_vol_sma = row.get('vol_sma_20')
                            current_vol = row['volume']
                            
                            if pd.isna(last_vol_sma) or current_vol < last_vol_sma:
                                score += 1
                                report.append("📊 Hacim Testi: Cılız Hacim (+1 Puan)")
                            elif current_vol > (2.0 * last_vol_sma) and lower_wick >= body:
                                score += 1
                                report.append("📊 Hacim Testi: Devasa Hacim Emilimi (+1 Puan)")
                            else:
                                report.append("📊 Hacim Testi: Satış Baskısı (0 Puan)")
                                
                            current_rsi = row.get('RSI_14')
                            curr_pos = df_4h.index.get_loc(curr_time)
                            lb_start = max(0, curr_pos - 20)
                            lookback_window = df_4h.iloc[lb_start:curr_pos]
                            if not lookback_window.empty and not pd.isna(current_rsi):
                                prev_low_idx = lookback_window['low'].idxmin()
                                prev_low_price = lookback_window.loc[prev_low_idx, 'low']
                                prev_rsi = lookback_window.loc[prev_low_idx, 'RSI_14']
                                if not pd.isna(prev_rsi) and row['low'] < prev_low_price and current_rsi > prev_rsi:
                                    score += 1
                                    report.append("🔬 RSI Testi: Pozitif Uyumsuzluk Var (+1 Puan)")
                                else:
                                    report.append("🔬 RSI Testi: Uyumsuzluk Yok (0 Puan)")
                            else:
                                report.append("🔬 RSI Testi: Yetersiz Veri (0 Puan)")
                                
                            print(f"\n⚠️ STOP İHLALİ TESPİT EDİLDİ: {sym} ({curr_time})")
                            print(f"Fiyat dinamik stopun ({open_trade['sl']:.2f}) altına indi. Savaş Masası Testleri Başladı:")
                            for r in report: print(r)
                            print(f"🧮 TOPLAM SKOR: {score} / 3")
                            
                            if score >= 2:
                                print("🤖 ASİSTAN KARARI: İŞLEMDE KAL! (SATMA). Tahtacı stop patlatıyor olabilir.")
                                continue
                            else:
                                print("🤖 ASİSTAN KARARI: GERÇEK ÇÖKÜŞ (SAT).")
                                open_trade['exit_time'] = curr_time
                                open_trade['exit_price'] = row['close']
                                open_trade['status'] = 'GERÇEK ÇÖKÜŞ (SAT)'
                                if open_trade.get("partial_tp_hit", False):
                                    pnl_2 = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                                    open_trade['pnl_pct'] = (5.0 + pnl_2) / 2.0
                                else:
                                    open_trade['pnl_pct'] = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                                completed_trades.append(open_trade)
                                open_trade = None
                                continue
                            
                    else: # SHORT TRADE
                        profit_pct = ((open_trade['entry_price'] - row['low']) / open_trade['entry_price']) * 100
                        strategy_name = open_trade['strategy']
                        scale_out_target = 10.0 if "FOMO İNFAZI" in strategy_name else 5.0
                        
                        if profit_pct >= scale_out_target and not open_trade.get("partial_tp_hit", False):
                            open_trade["partial_tp_hit"] = True
                            if open_trade['sl'] > open_trade['entry_price']:
                                open_trade['sl'] = open_trade['entry_price']
                                
                        current_trailing_dist = open_trade['trailing_dist']
                        if "ŞELALE SÖRFÜ" in strategy_name:
                            pass
                        elif "UÇURUM ÇÖKÜŞÜ" in strategy_name:
                            if profit_pct >= 15.0:
                                current_trailing_dist = open_trade['trailing_dist'] * 0.4
                        else:
                            if profit_pct >= 15.0:
                                current_trailing_dist = row['low'] * 0.005
                            elif profit_pct >= 10.0:
                                current_trailing_dist = row['low'] * 0.015

                        if row['low'] < open_trade['lowest_low']:
                            open_trade['lowest_low'] = row['low']
                            new_sl = open_trade['lowest_low'] + current_trailing_dist
                            if new_sl < open_trade['sl']:
                                open_trade['sl'] = new_sl

                        if row['high'] >= open_trade['sl']:
                            # KARA KUĞU (BLACK SWAN) ŞALTERİ (SHORT İÇİN YUKARI PATLAMA)
                            if row['high'] >= open_trade['sl'] * 1.03:
                                open_trade['exit_time'] = curr_time
                                open_trade['exit_price'] = max(open_trade['sl'] * 1.03, row['high'])
                                open_trade['status'] = 'KARA KUĞU (ACİL ÇIK)'
                                if open_trade.get("partial_tp_hit", False):
                                    pnl_2 = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
                                    open_trade['pnl_pct'] = (scale_out_target + pnl_2) / 2.0
                                else:
                                    open_trade['pnl_pct'] = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
                                completed_trades.append(open_trade)
                                open_trade = None
                                print(f"\n🚨 KIRMIZI ALARM: {sym} ({curr_time}) - Fiyat aniden %3'ten fazla fırladı. Savaş Masası İPTAL, ACİL ÇIKILDI!")
                                continue
                                
                            if row['close'] < open_trade['sl']:
                                continue
                                
                            score = 0
                            report = []
                            body = abs(row['open'] - row['close'])
                            candle_range = row['high'] - row['low']
                            upper_wick = row['high'] - max(row['close'], row['open'])
                            if candle_range > 0 and body < candle_range * 0.05:
                                report.append("🕯️ Mum Testi: Doji Mum (Kararsızlık) (0 Puan)")
                            elif body > 0 and upper_wick >= (body * 1.5):
                                score += 1
                                report.append("🕯️ Mum Testi: Üst İğne >= Gövde x1.5 (+1 Puan)")
                            else:
                                report.append("🕯️ Mum Testi: Tok Gövde (0 Puan)")
                                
                            last_vol_sma = row.get('vol_sma_20')
                            current_vol = row['volume']
                            
                            if pd.isna(last_vol_sma) or current_vol < last_vol_sma:
                                score += 1
                                report.append("📊 Hacim Testi: Cılız Hacim (+1 Puan)")
                            elif current_vol > (2.0 * last_vol_sma) and upper_wick >= body:
                                score += 1
                                report.append("📊 Hacim Testi: Devasa Hacim Emilimi (+1 Puan)")
                            else:
                                report.append("📊 Hacim Testi: Alım Baskısı (0 Puan)")
                                
                            current_rsi = row.get('RSI_14')
                            curr_pos_s = df_4h.index.get_loc(curr_time)
                            lb_start_s = max(0, curr_pos_s - 20)
                            lookback_window = df_4h.iloc[lb_start_s:curr_pos_s]
                            if not lookback_window.empty and not pd.isna(current_rsi):
                                prev_high_idx = lookback_window['high'].idxmax()
                                prev_high_price = lookback_window.loc[prev_high_idx, 'high']
                                prev_rsi = lookback_window.loc[prev_high_idx, 'RSI_14']
                                if not pd.isna(prev_rsi) and row['high'] > prev_high_price and current_rsi < prev_rsi:
                                    score += 1
                                    report.append("🔬 RSI Testi: Negatif Uyumsuzluk Var (+1 Puan)")
                                else:
                                    report.append("🔬 RSI Testi: Uyumsuzluk Yok (0 Puan)")
                            else:
                                report.append("🔬 RSI Testi: Yetersiz Veri (0 Puan)")
                                
                            print(f"\n⚠️ STOP İHLALİ TESPİT EDİLDİ (SHORT): {sym} ({curr_time})")
                            print(f"Fiyat dinamik stopun ({open_trade['sl']:.2f}) üstüne çıktı. Savaş Masası Testleri Başladı:")
                            for r in report: print(r)
                            print(f"🧮 TOPLAM SKOR: {score} / 3")
                            
                            if score >= 2:
                                print("🤖 ASİSTAN KARARI: İŞLEMDE KAL! (ÇIKMA). Tahtacı stop patlatıyor olabilir.")
                                continue
                            else:
                                print("🤖 ASİSTAN KARARI: GERÇEK YÜKSELİŞ (ÇIK).")
                                open_trade['exit_time'] = curr_time
                                open_trade['exit_price'] = row['close']
                                open_trade['status'] = 'GERÇEK YÜKSELİŞ (ÇIK)'
                                if open_trade.get("partial_tp_hit", False):
                                    pnl_2 = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
                                    open_trade['pnl_pct'] = (scale_out_target + pnl_2) / 2.0
                                else:
                                    open_trade['pnl_pct'] = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
                                completed_trades.append(open_trade)
                                open_trade = None
                                continue
                        
                if open_trade is None:
                    # İndikatörler döngü öncesinde hesaplandı, sadece ilgili satırları oku
                    avail_1d = df_1d[df_1d.index <= curr_time.floor('d')]
                    
                    if len(df_4h[df_4h.index <= curr_time]) < 20 or len(avail_1d) < 30: continue
                    
                    last_1d = avail_1d.iloc[-1]
                    last_4h = row  # Mevcut 4h mum (önceden hesaplanmış indikatörlerle)
                    current_price = last_4h['close']
                    
                    atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
                    if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
                    dynamic_sl_dist = 1.5 * atr_val
                    
                    # Hafta sonu sahteliği filtresi (Tarihsel zamana göre)
                    is_weekend = False
                    if curr_time.weekday() == 4 and curr_time.hour >= 23: is_weekend = True
                    elif curr_time.weekday() == 5: is_weekend = True
                    elif curr_time.weekday() == 6 and curr_time.hour < 23: is_weekend = True
                    
                    # Crypto 1: Dip Avcılığı (Esnek ayar: RSI 28, Vol 2.0x, OI Crash)
                    if not is_weekend:
                        if last_4h.get('RSI_14', 100) < 28 and last_4h.get('volume', 0) > (2.0 * last_4h.get('vol_sma_20', 99999999)):
                            if current_price > last_4h.get('EMA_20', current_price*2) and current_price > last_4h['open']:
                                oi_crash_mock = True # Simülasyon için mock
                                if oi_crash_mock:
                                    sl = last_4h['low'] * 0.99
                                    open_trade = {
                                        'symbol': sym, 'market': 'KRIPTO', 'strategy': 'Kripto 1: Dip Avcılığı', 'entry_time': curr_time,
                                        'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': (current_price - sl)
                                    }
                                    continue
                            
                    # Crypto 2: Mega Trend Takibi (BTC Dominans Kalkanı)
                    if last_1d.get('EMA_20', 0) > last_1d.get('EMA_50', current_price*2) and last_1d['close'] > last_1d.get('EMA_20', current_price*2):
                        if last_4h.get('ADX_14', 0) > 25:
                            if last_4h['low'] <= last_4h.get('EMA_20', 0) and current_price > last_4h.get('EMA_20', current_price*2) and current_price > last_4h['open']:
                                btcdom_trend_mock = "DOWN" # Simülasyon mock
                                if btcdom_trend_mock != "UP":
                                    sl_atr = current_price - (1.5 * atr_val)
                                    sl_ema = last_4h.get('EMA_50', current_price) * 0.98
                                    sl = max(sl_atr, sl_ema)
                                    open_trade = {
                                        'symbol': sym, 'market': 'KRIPTO', 'strategy': 'Kripto 2: Trend Takibi', 'entry_time': curr_time,
                                        'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
                                    }
                                    continue

                    # Crypto 3: Retest (Funding Rate ve Token Unlocks)
                    if not is_weekend:
                        bb_upper_col = [c for c in sliced_1d.columns if 'BBU' in c]
                        bb_lower_col = [c for c in sliced_1d.columns if 'BBL' in c]
                        bb_mid_col = [c for c in sliced_1d.columns if 'BBM' in c]
                        if bb_upper_col and bb_lower_col and bb_mid_col:
                            bb_width_series = (sliced_1d[bb_upper_col[0]] - sliced_1d[bb_lower_col[0]]) / sliced_1d[bb_mid_col[0]]
                            min_width_30d = bb_width_series.tail(30).min()
                            last_width = bb_width_series.iloc[-1]
                            
                            if last_width <= min_width_30d * 1.20:
                                if last_4h['volume'] > (2.0 * last_4h.get('vol_sma_20', 99999999)):
                                    local_high = sliced_4h['high'].tail(15).max()
                                    if last_4h['low'] <= local_high * 0.99 and current_price > last_4h['open']:
                                        has_unlocks_mock = False
                                        funding_rate_mock = -0.01
                                        if not has_unlocks_mock and funding_rate_mock <= 0.0:
                                            sl = current_price * 0.95
                                            open_trade = {
                                                'symbol': sym, 'market': 'KRIPTO', 'strategy': 'Kripto 3: Retest', 'entry_time': curr_time,
                                                'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': (current_price - sl)
                                            }
                                            continue
                                            
                    # YENİ KRİPTO SHORT STRATEJİLERİ
                    btc_not_pumping = True
                    if df_btc is not None:
                        sliced_btc = df_btc[df_btc.index <= curr_time.floor('d')].copy()
                        if len(sliced_btc) >= 20:
                            sliced_btc.ta.ema(length=20, append=True)
                            btc_last = sliced_btc.iloc[-1]
                            btc_prev = sliced_btc.iloc[-2]
                            btc_ema20 = btc_last.get('EMA_20', 999999)
                            if (btc_last['close'] > btc_ema20) and (btc_last['close'] > btc_prev['high']):
                                btc_not_pumping = False
                                
                    if btc_not_pumping and not is_weekend:
                        # SHORT 1: FOMO İNFAZI
                        if last_4h.get('RSI_14', 0) > 85:
                            body = abs(current_price - last_4h['open'])
                            upper_wick = last_4h['high'] - max(current_price, last_4h['open'])
                            if current_price < last_4h['open'] and upper_wick > (2 * body):
                                recent_high = sliced_4h['high'].tail(5).max()
                                sl_structural = recent_high * 1.01
                                sl_atr = current_price + (2.0 * atr_val)
                                sl = max(sl_structural, sl_atr)
                                open_trade = {
                                    'symbol': sym, 'market': 'KRIPTO', 'strategy': 'SHORT 1: FOMO İNFAZI', 'signal': 'SAT',
                                    'entry_time': curr_time, 'entry_price': current_price, 'sl': sl,
                                    'lowest_low': current_price, 'trailing_dist': (sl - current_price)
                                }
                                continue

                        # SHORT 2: KANLI ŞELALE SÖRFÜ
                        if last_1d.get('EMA_20', 0) < last_1d.get('EMA_50', 0) and current_price < last_1d.get('EMA_20', 0):
                            if last_4h.get('ADX_14', 0) > 30:
                                if last_4h['high'] >= last_4h.get('EMA_20', 999999) and current_price < last_4h.get('EMA_20', 0) and current_price < last_4h['open']:
                                    btcdom_trend_mock = "UP"
                                    if btcdom_trend_mock == "UP":
                                        recent_high = sliced_4h['high'].tail(5).max()
                                        sl_structural = recent_high * 1.01
                                        sl_atr = current_price + (1.5 * atr_val)
                                        sl = max(sl_structural, sl_atr)
                                        open_trade = {
                                            'symbol': sym, 'market': 'KRIPTO', 'strategy': 'SHORT 2: KANLI ŞELALE SÖRFÜ', 'signal': 'SAT',
                                            'entry_time': curr_time, 'entry_price': current_price, 'sl': sl,
                                            'lowest_low': current_price, 'trailing_dist': (sl - current_price)
                                        }
                                        continue

                        # SHORT 3: UÇURUM ÇÖKÜŞÜ
                        if len(sliced_4h) >= 90:
                            support_lookback = sliced_4h['low'].iloc[-75:-15].min()
                            breakout_zone = sliced_4h.iloc[-15:-1]
                            if breakout_zone['low'].min() < support_lookback:
                                if current_price < support_lookback:
                                    recent_high = max(last_4h['high'], sliced_4h.iloc[-2]['high'])
                                    proximity = (support_lookback - recent_high) / support_lookback
                                    if 0 <= proximity <= 0.015 and current_price < last_4h['open']:
                                        sl = support_lookback * 1.02
                                        open_trade = {
                                            'symbol': sym, 'market': 'KRIPTO', 'strategy': 'SHORT 3: UÇURUM ÇÖKÜŞÜ', 'signal': 'SAT',
                                            'entry_time': curr_time, 'entry_price': current_price, 'sl': sl,
                                            'lowest_low': current_price, 'trailing_dist': (sl - current_price)
                                        }
                                        continue
                                    
            if open_trade is not None:
                last_bar = sim_bars.iloc[-1]
                open_trade['exit_time'] = sim_bars.index[-1]
                open_trade['exit_price'] = last_bar['close']
                open_trade['status'] = 'OPEN_AT_END'
                end_pnl = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
                if open_trade.get('signal') == 'SAT':
                    end_pnl = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
                    
                if open_trade.get("partial_tp_hit", False):
                    scale_out_target = 10.0 if "FOMO İNFAZI" in open_trade['strategy'] else 5.0
                    open_trade['pnl_pct'] = (scale_out_target + end_pnl) / 2.0
                else:
                    open_trade['pnl_pct'] = end_pnl
                completed_trades.append(open_trade)
        except Exception as e:
            logging.warning(f"[simulate_crypto] {sym}: {e}")

def simulate_pnl():
    completed_trades.clear()
    simulate_bist()
    simulate_crypto()
    
    df_trades = pd.DataFrame(completed_trades)
    if not df_trades.empty:
        df_trades['entry_time'] = df_trades['entry_time'].dt.strftime('%Y-%m-%d %H:%M')
        df_trades['exit_time'] = df_trades['exit_time'].dt.strftime('%Y-%m-%d %H:%M')
        print(df_trades[['market', 'symbol', 'strategy', 'entry_time', 'exit_time', 'pnl_pct', 'status']].to_string())
        
        total_trades = len(df_trades)
        wins = len(df_trades[df_trades['pnl_pct'] > 0])
        losses = len(df_trades[df_trades['pnl_pct'] <= 0])
        total_pnl = df_trades['pnl_pct'].sum()
        
        bist_trades = df_trades[df_trades['market'] == 'BIST']
        crypto_trades = df_trades[df_trades['market'] == 'KRIPTO']
        
        print("\n=== ÖZET ===")
        print(f"Toplam İşlem: {total_trades}")
        print(f"Karlı İşlem: {wins}")
        print(f"Zararlı İşlem: {losses}")
        print(f"Toplam Net Getiri Yüzdesi: %{total_pnl:.2f}")
        
        print("\n=== BIST ÖZETİ ===")
        print(f"Toplam İşlem: {len(bist_trades)}")
        print(f"BIST Net Getiri: %{bist_trades['pnl_pct'].sum():.2f}")
        
        print("\n=== KRIPTO ÖZETİ ===")
        print(f"Toplam İşlem: {len(crypto_trades)}")
        print(f"Kripto Net Getiri: %{crypto_trades['pnl_pct'].sum():.2f}")
        
        df_trades.to_csv("simulation_results.csv", index=False)
    else:
        print("Hiç işlem gerçekleşmedi.")

if __name__ == "__main__":
    simulate_pnl()
