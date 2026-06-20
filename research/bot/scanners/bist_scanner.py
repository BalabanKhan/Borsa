import asyncio
import datetime
import pytz
import logging
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from config import TOP_BIST_50, TOP_BIST
import data_sources
from research.market_predictor import predict_future, evaluate_model_accuracy

logger = logging.getLogger("research.bot.scanners.bist")

def run_intraday_scan():
    """BIST 50 seans sonu için trend/momentum taraması yapar."""
    tickers_str = " ".join(TOP_BIST_50)
    data = yf.download(tickers_str, period="60d", interval="1h", group_by="ticker", progress=False)
    
    results = []
    for ticker in TOP_BIST_50:
        if len(TOP_BIST_50) == 1:
            df = data.copy()
        else:
            if ticker not in data.columns.get_level_values(0):
                continue
            df = data[ticker].copy()
        
        df = df.dropna()
        if df.empty: continue
        
        # İndikatörler
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI_14'] = 100 - (100 / (1 + rs))
        
        df['EMA_5'] = df['Close'].ewm(span=5, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['Volume_SMA'] = df['Volume'].rolling(window=20).mean()
        
        # ATR (Average True Range) Hesaplama (Volatilite)
        tr1 = df['High'] - df['Low']
        tr2 = (df['High'] - df['Close'].shift(1)).abs()
        tr3 = (df['Low'] - df['Close'].shift(1)).abs()
        df['TR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_14'] = df['TR'].rolling(window=14).mean()
        
        df['Trend'] = (df['Close'] > df['EMA_5']) & (df['EMA_5'] > df['EMA_20'])
        df['Vol_Surge'] = df['Volume'] > df['Volume_SMA'] * 1.5
        
        df['MACD'] = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        df['MACD_Pos'] = df['MACD_Hist'] > 0
        
        df = df.dropna()
        if df.empty: continue
        
        last_bar = df.iloc[-1]
        
        # Algoritma: (A + C birleşimi + RSI < 75) -> Trend + MACD Momentum + Hacim + RSI
        if last_bar['Trend'] and last_bar['MACD_Pos'] and last_bar['Vol_Surge'] and last_bar['RSI_14'] < 75:
            price = last_bar['Close']
            atr = last_bar['ATR_14']
            
            # Dinamik Hedefler: Fiyat hareketinin 2 katı kazanç, 1.5 katı stop
            tp = price + (atr * 2.0)
            sl = price - (atr * 1.5)
            
            tp_pct = ((tp - price) / price) * 100
            sl_pct = ((price - sl) / price) * 100
            
            results.append({
                'Ticker': ticker,
                'RSI': last_bar['RSI_14'],
                'Price': price,
                'TP': tp,
                'SL': sl,
                'TP_Pct': tp_pct,
                'SL_Pct': sl_pct
            })
            
    if not results:
        # Esnek Kriter: Trend + RSI < 75 (Hacim veya MACD filtresine takılanları kurtar)
        for ticker in TOP_BIST_50:
            if len(TOP_BIST_50) == 1:
                df = data.copy()
            else:
                if ticker not in data.columns.get_level_values(0): continue
                df = data[ticker].copy()
            df = df.dropna()
            if df.empty: continue
            
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi_val = 100 - (100 / (1 + rs)).iloc[-1]
            
            ema_5 = df['Close'].ewm(span=5, adjust=False).mean()
            ema_20 = df['Close'].ewm(span=20, adjust=False).mean()
            trend = (df['Close'] > ema_5) & (ema_5 > ema_20)
            
            if trend.iloc[-1] and rsi_val < 75:
                price = df['Close'].iloc[-1]
                results.append({
                    'Ticker': ticker,
                    'RSI': rsi_val,
                    'Price': price,
                    'TP': price * 1.05,
                    'SL': price * 0.97,
                    'TP_Pct': 5.0,
                    'SL_Pct': 3.0
                })
    
    res_df = pd.DataFrame(results)
    if res_df.empty:
        return []
    
    return res_df.to_dict('records')


def run_hourly_scan():
    """BIST 50 için TimesFM MAPE optimizasyonlu saatlik tarama yapar."""
    results = []
    candidates = [32, 64, 96, 128]
    for ticker in TOP_BIST_50:
        best_mape = float('inf')
        best_c = 60
        for c in candidates:
            mape = evaluate_model_accuracy(ticker, asset_type='bist', interval='1h', context_len=c, horizon_len=7)
            if mape is not None and mape < best_mape:
                best_mape = mape
                best_c = c
        
        if best_mape != float('inf'):
            results.append({'symbol': ticker, 'mape': best_mape, 'best_context': best_c})
    
    results.sort(key=lambda x: x['mape'])
    top_3 = results[:3]
    
    final_results = []
    for item in top_3:
        sym = item['symbol']
        c_len = item['best_context']
        res = predict_future(symbol=sym, asset_type='bist', interval='1h', context_len=c_len, horizon_len=7, show_plot=False, save_plot=True)
        if res and res[0]:
            image_path, final_pred, pct_change, rsi = res
            
            _, _, df_1h = data_sources.get_bist_data(sym)
            if df_1h is not None and not df_1h.empty:
                last_close = df_1h['close'].iloc[-1]
                tr1 = df_1h['high'] - df_1h['low']
                tr2 = (df_1h['high'] - df_1h['close'].shift(1)).abs()
                tr3 = (df_1h['low'] - df_1h['close'].shift(1)).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr = tr.rolling(window=14).mean().iloc[-1]
                
                tp = last_close + (atr * 2.0)
                sl = last_close - (atr * 1.5)
                tp_pct = ((tp - last_close) / last_close) * 100
                sl_pct = ((last_close - sl) / last_close) * 100
            else:
                tp = sl = tp_pct = sl_pct = 0
                last_close = final_pred / (1 + (pct_change/100))
            
            final_results.append({
                'symbol': sym,
                'mape': item['mape'],
                'pct_change': pct_change,
                'final_pred': final_pred,
                'image_path': image_path,
                'tp': tp,
                'sl': sl,
                'tp_pct': tp_pct,
                'sl_pct': sl_pct,
                'price': last_close,
                'best_context': c_len
            })
    return final_results


def scan_all_bist100():
    """BIST 100 hisselerini çeker, seviye 1 ve seviye 2 filtrelerini uygular."""
    bist_targets = TOP_BIST
    logger.info(f"BIST 100 toplu veri indiriliyor (toplam {len(bist_targets)} hisse)...")
    batch_data = data_sources.get_bist_data_batch(bist_targets, batch_size=35)
    
    def apply_filter(vol_mult, rsi_limit, ema_check):
        scanned_candidates = []
        for symbol in bist_targets:
            try:
                dfs = batch_data.get(symbol)
                if not dfs or dfs[0] is None or dfs[2] is None:
                    continue
                    
                df_1d, df_4h, df_1h = dfs
                
                # Filtre A: Saatlik Hacim Kontrolü
                if len(df_1h) >= 20:
                    last_vol = df_1h['volume'].iloc[-1]
                    avg_vol_20 = df_1h['volume'].rolling(20).mean().iloc[-1]
                    if pd.isna(avg_vol_20) or avg_vol_20 == 0:
                        avg_vol_20 = 1.0
                    if last_vol <= avg_vol_20 * vol_mult:
                        continue
                else:
                    continue

                # Filtre B: Saatlik (1h) RSI Kontrolü (RSI < rsi_limit)
                if len(df_1h) >= 15:
                    df_1h_copy = df_1h.copy()
                    df_1h_copy.ta.rsi(length=14, append=True)
                    rsi_col = 'rsi_14' if 'rsi_14' in df_1h_copy.columns else 'RSI_14'
                    if rsi_col in df_1h_copy.columns:
                        rsi_1h = df_1h_copy[rsi_col].iloc[-1]
                        if pd.isna(rsi_1h) or rsi_1h > rsi_limit:
                            continue
                    else:
                        continue
                else:
                    continue

                # Günlük Tahmin
                res_1d = predict_future(
                    symbol=symbol, 
                    asset_type='bist', 
                    context_len=90,
                    horizon_len=7, 
                    show_plot=False,
                    save_plot=False,
                    interval='1d',
                    preloaded_dfs=dfs
                )
                
                if res_1d:
                    _, final_pred_1d, pct_change_1d, rsi_1d = res_1d
                    
                    # Filtre C: Günlük trend negatifse ele
                    if pct_change_1d <= 0:
                        continue
                    
                    # Vur-kaç seans içi işlem odaklı sabit 64 saatlik lookback
                    best_c = 64
                    best_mape_val = evaluate_model_accuracy(symbol, 'bist', '1h', best_c, 8, preloaded_dfs=dfs)
                    if best_mape_val is None:
                        best_mape_val = 0.0

                    # Saatlik Tahmin
                    res_1h = predict_future(
                        symbol=symbol,
                        asset_type='bist',
                        context_len=best_c,
                        horizon_len=8,
                        show_plot=False,
                        save_plot=False,
                        interval='1h',
                        preloaded_dfs=dfs
                    )
                    
                    if res_1h:
                        _, final_pred_1h, pct_change_1h, _ = res_1h
                        
                        # Filtre D: Saatlik trend negatifse ele
                        if pct_change_1h <= 0:
                            continue
                            
                        last_close = df_1h['close'].iloc[-1]
                        
                        # Filtre E: EMA 5 Kontrolü
                        if ema_check:
                            ema5 = df_1h['close'].ewm(span=5, adjust=False).mean()
                            last_ema5 = ema5.iloc[-1]
                            if last_close <= last_ema5:
                                continue
                            
                        # ATR ve TP/SL
                        tr1 = df_1h['high'] - df_1h['low']
                        tr2 = (df_1h['high'] - df_1h['close'].shift(1)).abs()
                        tr3 = (df_1h['low'] - df_1h['close'].shift(1)).abs()
                        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                        atr = tr.rolling(window=14).mean().iloc[-1]
                        
                        tp = last_close + (atr * 2.0)
                        sl = last_close - (atr * 1.5)
                        tp_pct = ((tp - last_close) / last_close) * 100
                        sl_pct = ((last_close - sl) / last_close) * 100
                            
                        scanned_candidates.append({
                            'symbol': symbol,
                            'pct_change_1d': pct_change_1d,
                            'pct_change_1h': pct_change_1h,
                            'rsi': rsi_1h,
                            'tp': tp,
                            'sl': sl,
                            'tp_pct': tp_pct,
                            'sl_pct': sl_pct,
                            'price': last_close,
                            'best_context_1h': best_c,
                            'mape_1h': best_mape_val
                        })
            except Exception as e:
                logger.error(f"Scan error for {symbol}: {e}")
        return scanned_candidates

    # Level 1 (Standart/Sabah Taraması): Hacim > 1.0, RSI < 70, EMA5 aktif
    level = 1
    results = apply_filter(vol_mult=1.0, rsi_limit=70.0, ema_check=True)
    
    # Level 2 (Esnek/Fallback): Hacim > 0.8, RSI < 75, EMA5 pasif
    if not results:
        logger.info("Level 1 (Standart) filtrelerinden geçen hisse bulunamadı. Level 2 (Esnek/Fallback) deneniyor...")
        level = 2
        results = apply_filter(vol_mult=0.8, rsi_limit=75.0, ema_check=False)
        
    return results, level, batch_data
