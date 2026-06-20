import logging
import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
from config import TOP_CRYPTO_SCAN, TOP_BIST_50
import data_sources

logger = logging.getLogger("research.bot.scanners.smc")

import pandas_ta as ta

def calculate_atr(df, window=14):
    df.ta.atr(length=window, append=True)
    return df[f'ATRr_{window}']

def calculate_zscore(df, window=20):
    sma = df.ta.sma(length=window)
    std = df.ta.stdev(length=window)
    z_score = (df['close'] - sma) / std
    return z_score, sma


def get_swing_points(df, order=5):
    """Finds local peaks and valleys."""
    highs = argrelextrema(df['high'].values, np.greater_equal, order=order)[0]
    lows = argrelextrema(df['low'].values, np.less_equal, order=order)[0]
    return highs, lows

def calculate_volume_profile(df, bins=20):
    """Calculates Volume Profile and finds Point of Control (POC)."""
    min_price = df['low'].min()
    max_price = df['high'].max()
    if pd.isna(min_price) or pd.isna(max_price) or min_price == max_price:
        return min_price
        
    price_bins = np.linspace(min_price, max_price, bins)
    
    volume_profile = np.zeros(bins-1)
    for i in range(len(df)):
        price = df['close'].iloc[i]
        vol = df['volume'].iloc[i]
        for j in range(bins-1):
            if price_bins[j] <= price <= price_bins[j+1]:
                volume_profile[j] += vol
                break
                
    poc_idx = np.argmax(volume_profile)
    poc_price = (price_bins[poc_idx] + price_bins[poc_idx+1]) / 2
    return poc_price

def run_smc_scan(asset_type='crypto'):
    """Runs a purely mathematical/deterministic SMC scan."""
    results = []
    symbols = TOP_CRYPTO_SCAN if asset_type == 'crypto' else TOP_BIST_50
    for symbol in symbols:
        try:
            if asset_type == 'crypto':
                df = data_sources.get_crypto_1h_data(symbol)
            else:
                _, _, df = data_sources.get_bist_data(symbol)
                
            if df is None or df.empty or len(df) < 100:
                continue
            
            close = df['close'].iloc[-1]
            atr = calculate_atr(df).iloc[-1]
            z_score, sma = calculate_zscore(df)
            current_z = z_score.iloc[-1]
            
            # POC Calculation (Last 100 hours)
            df_recent = df.tail(100)
            poc = calculate_volume_profile(df_recent)
            
            # Swings (Local extrema)
            highs, lows = get_swing_points(df_recent, order=5)
            last_swing_low = df_recent['low'].iloc[lows[-1]] if len(lows) > 0 else close - atr*2
            last_swing_high = df_recent['high'].iloc[highs[-1]] if len(highs) > 0 else close + atr*2
            
            # VWAP Calculation (for BIST/Crypto volume confirmation)
            df.ta.vwap(append=True)
            vwap = df[f'VWAP_D'].iloc[-1] if f'VWAP_D' in df.columns else (df['VWAP'] if 'VWAP' in df.columns else df.ta.vwap().iloc[-1])

            # 1D Trend onaylama (MTF Teyit)
            if asset_type == 'crypto':
                df_1d, _ = data_sources.get_crypto_data_cached(symbol)
            else:
                df_1d, _, _ = data_sources.get_bist_data(symbol)
                
            if df_1d is not None and len(df_1d) >= 50:
                ema_50_1d = df_1d.ta.ema(length=50).iloc[-1]
            else:
                ema_50_1d = None

            # Deterministic conditions
            # Long condition: Oversold, price > POC, price > last swing low (uptrend structure forming)
            is_oversold = current_z < -1.0
            is_overbought = current_z > 1.0
            
            # Ekstra Kantitatif Filtreler (CCXT & VWAP)
            ob_imbalance = 0.0
            if asset_type == 'crypto':
                ob_imbalance = data_sources.get_order_book_imbalance(symbol)
            
            long_score = 0
            if is_oversold: long_score += 2
            if close > poc: long_score += 1
            if close > last_swing_low: long_score += 1
            if close > vwap: long_score += 1 # Fiyat VWAP üzerinde mi?
            if ob_imbalance > 0.15: long_score += 1 # %15+ alıcı baskısı
            
            # Trend Uyum Filtresi: 1D EMA 50 altında LONG işlemler engellenir
            if ema_50_1d is not None and close < ema_50_1d:
                long_score = 0
            
            short_score = 0
            if is_overbought: short_score += 2
            if close < poc: short_score += 1
            if close < last_swing_high: short_score += 1
            if close < vwap: short_score += 1
            if ob_imbalance < -0.15: short_score += 1
            
            # Trend Uyum Filtresi: 1D EMA 50 üstünde SHORT işlemler engellenir
            if ema_50_1d is not None and close > ema_50_1d:
                short_score = 0

            
            results.append({
                'symbol': symbol,
                'price': close,
                'poc': poc,
                'z_score': current_z,
                'atr': atr,
                'vwap': vwap,
                'ob_imbalance': ob_imbalance,
                'last_swing_low': last_swing_low,
                'last_swing_high': last_swing_high,
                'long_score': long_score,
                'short_score': short_score
            })
            
        except Exception as e:
            logger.error(f"SMC Scan error for {symbol}: {e}")
            
    # Sort and filter
    longs = sorted([r for r in results if r['long_score'] >= 2], key=lambda x: (x['long_score'], -x['z_score']), reverse=True)
    shorts = sorted([r for r in results if r['short_score'] >= 2], key=lambda x: (x['short_score'], x['z_score']), reverse=True)
    
    return longs[:3], shorts[:3]
