import pandas as pd
import pandas_ta as ta
import yfinance as yf
import ccxt
from datetime import timedelta
import logging
import warnings
import sys

sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from data_fetcher import TOP_BIST, TOP_CRYPTO
import config
from indicators import (
    detect_squeeze,
    calculate_anchored_vwap,
    detect_vwap_bounce,
    detect_obv_accumulation,
    inject_smart_indicators,
)

# Simulation parameters
start_sim = pd.to_datetime("2026-06-08 00:00:00")
end_sim = pd.to_datetime("2026-06-17 23:59:59")

exchange = ccxt.binance({'enableRateLimit': True})
completed_trades = []

def _check_war_candle_anatomy(row, is_short, report):
    body = abs(row['open'] - row['close'])
    candle_range = row['high'] - row['low']
    if not is_short:
        lower_wick = min(row['close'], row['open']) - row['low']
        if candle_range > 0 and body < candle_range * 0.05:
            report.append("🕯️ Mum Testi: Doji Mum (Kararsızlık) (0 Puan)")
            return 0
        elif body > 0 and lower_wick >= (body * 1.5):
            report.append("🕯️ Mum Testi: Alt İğne >= Gövde x1.5 (+1 Puan)")
            return 1
    else:
        upper_wick = row['high'] - max(row['close'], row['open'])
        if candle_range > 0 and body < candle_range * 0.05:
            report.append("🕯️ Mum Testi: Doji Mum (Kararsızlık) (0 Puan)")
            return 0
        elif body > 0 and upper_wick >= (body * 1.5):
            report.append("🕯️ Mum Testi: Üst İğne >= Gövde x1.5 (+1 Puan)")
            return 1
    report.append("🕯️ Mum Testi: Tok Gövde (0 Puan)")
    return 0

def _check_war_volume_absorption(row, is_short, report):
    last_vol_sma = row.get('vol_sma_20')
    current_vol = row['volume']
    body = abs(row['open'] - row['close'])
    if not is_short:
        lower_wick = min(row['close'], row['open']) - row['low']
        if pd.isna(last_vol_sma) or current_vol < last_vol_sma:
            report.append("📊 Hacim Testi: Cılız Hacim (+1 Puan)")
            return 1
        elif current_vol > (2.0 * last_vol_sma) and lower_wick >= body:
            report.append("📊 Hacim Testi: Devasa Hacim Emilimi (+1 Puan)")
            return 1
        else:
            report.append("📊 Hacim Testi: Satış Baskısı (0 Puan)")
            return 0
    else:
        upper_wick = row['high'] - max(row['close'], row['open'])
        if pd.isna(last_vol_sma) or current_vol < last_vol_sma:
            report.append("📊 Hacim Testi: Cılız Hacim (+1 Puan)")
            return 1
        elif current_vol > (2.0 * last_vol_sma) and upper_wick >= body:
            report.append("📊 Hacim Testi: Devasa Hacim Emilimi (+1 Puan)")
            return 1
        else:
            report.append("📊 Hacim Testi: Alım Baskısı (0 Puan)")
            return 0

def _check_war_rsi_rontgen(row, df, curr_time, is_short, report):
    current_rsi = row.get('RSI_14')
    try:
        curr_pos = df.index.get_loc(curr_time)
        lookback_start = max(0, curr_pos - 20)
        lookback_window = df.iloc[lookback_start:curr_pos]
    except Exception:
        report.append("🔬 RSI Testi: Yetersiz Veri (0 Puan)")
        return 0
        
    if lookback_window.empty:
        report.append("🔬 RSI Testi: Yetersiz Veri (0 Puan)")
        return 0
    if pd.isna(current_rsi):
        report.append("🔬 RSI Testi: Yetersiz Veri (0 Puan)")
        return 0

    if not is_short:
        prev_low_idx = lookback_window['low'].idxmin()
        prev_low_price = lookback_window.loc[prev_low_idx, 'low']
        prev_rsi = lookback_window.loc[prev_low_idx, 'RSI_14']
        if pd.isna(prev_rsi):
            pass
        elif row['low'] < prev_low_price:
            if current_rsi > prev_rsi:
                report.append("🔬 RSI Testi: Pozitif Uyumsuzluk Var (+1 Puan)")
                return 1
        report.append("🔬 RSI Testi: Uyumsuzluk Yok (0 Puan)")
        return 0

    prev_high_idx = lookback_window['high'].idxmax()
    prev_high_price = lookback_window.loc[prev_high_idx, 'high']
    prev_rsi = lookback_window.loc[prev_high_idx, 'RSI_14']
    if pd.isna(prev_rsi):
        pass
    elif row['high'] > prev_high_price:
        if current_rsi < prev_rsi:
            report.append("🔬 RSI Testi: Negatif Uyumsuzluk Var (+1 Puan)")
            return 1
            
    report.append("🔬 RSI Testi: Uyumsuzluk Yok (0 Puan)")
    return 0

def _check_war_table(row, df, curr_time, is_short, sym, open_trade):
    if not is_short and row['close'] > open_trade['sl']:
        return None
    if is_short and row['close'] < open_trade['sl']:
        return None

    score = 0
    report = []
    
    score += _check_war_candle_anatomy(row, is_short, report)
    score += _check_war_volume_absorption(row, is_short, report)
    score += _check_war_rsi_rontgen(row, df, curr_time, is_short, report)
        
    label_str = " (SHORT)" if is_short else ""
    print(f"\n⚠️ STOP İHLALİ TESPİT EDİLDİ{label_str}: {sym} ({curr_time})")
    print(f"Fiyat dinamik stopun ({open_trade['sl']:.2f}) {'üstüne çıktı' if is_short else 'altına indi'}. Savaş Masası Testleri Başladı:")
    for r in report:
        print(r)
    print(f"🧮 TOPLAM SKOR: {score} / 3")
    return score

def _check_bist1_dip_hunter(row, last_1d, prev_1h, curr_time, sym, dynamic_sl_dist):
    current_price = row['close']
    if last_1d.get('RSI_14', 100) < 35 and current_price > last_1d.get('EMA_8', current_price*2):
        if row['close'] > row.get('EMA_8', current_price*2) and row['close'] > row['open']:
            if row.get('RSI_14', 0) > prev_1h.get('RSI_14', 100):
                sl = current_price - dynamic_sl_dist
                return {
                    'symbol': sym, 'market': 'BIST', 'strategy': 'Dip Avcılığı', 'entry_time': curr_time,
                    'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
                }
    return None

def _check_bist2_trend_following(row, last_4h, curr_time, sym, dynamic_sl_dist):
    current_price = row['close']
    if last_4h.get('ADX_14', 0) > 25 and last_4h.get('EMA_5', 0) > last_4h.get('EMA_13', current_price*2):
        if row['low'] <= row.get('EMA_13', 0) and row['close'] > row.get('EMA_13', current_price*2) and row['close'] > row['open']:
            sl = current_price - dynamic_sl_dist
            return {
                'symbol': sym, 'market': 'BIST', 'strategy': 'Trend Takibi', 'entry_time': curr_time,
                'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
            }
    return None

def _check_bist3_breakout(row, df_1d, last_1d, curr_time, sym, dynamic_sl_dist):
    current_price = row['close']
    curr_day = curr_time.normalize()
    cols = df_1d.columns
    bb_upper_col = [c for c in cols if 'BBU' in c]
    bb_lower_col = [c for c in cols if 'BBL' in c]
    bb_mid_col = [c for c in cols if 'BBM' in c]
    if len(bb_upper_col) == 0 or len(bb_lower_col) == 0 or len(bb_mid_col) == 0:
        return None
    bbu = last_1d[bb_upper_col[0]]
    bbl = last_1d[bb_lower_col[0]]
    bbm = last_1d[bb_mid_col[0]]
    
    bb_width = 1
    if bbm != 0:
        bb_width = (bbu - bbl) / bbm
        
    if bb_width >= 0.15:
        return None
        
    avail_1d_for_high = df_1d[df_1d.index <= curr_day]
    month_high = avail_1d_for_high['high'].max()
    if len(avail_1d_for_high) >= 30:
        month_high = avail_1d_for_high['high'].tail(30).max()
        
    if current_price <= month_high:
        return None
        
    vol_sma = row.get('vol_sma_20')
    if pd.isna(vol_sma):
        return None
    if row['volume'] <= (1.3 * vol_sma):
        return None
        
    sl = current_price - dynamic_sl_dist
    return {
        'symbol': sym, 'market': 'BIST', 'strategy': 'Breakout', 'entry_time': curr_time,
        'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
    }

def _check_bist_entry_triggers(row, curr_time, sym, df_1d, df_1h, prev_1h, last_1d, last_4h, curr_pos, atr_val, dynamic_sl_dist):
    res1 = _check_bist1_dip_hunter(row, last_1d, prev_1h, curr_time, sym, dynamic_sl_dist)
    if res1:
        return res1
    res2 = _check_bist2_trend_following(row, last_4h, curr_time, sym, dynamic_sl_dist)
    if res2:
        return res2
    res3 = _check_bist3_breakout(row, df_1d, last_1d, curr_time, sym, dynamic_sl_dist)
    if res3:
        return res3
    return None

def _handle_bist_stop_hit(row, open_trade, curr_time, df_1h, sym):
    if row['low'] <= open_trade['sl'] * 0.97:
        open_trade['exit_time'] = curr_time
        open_trade['exit_price'] = min(open_trade['sl'] * 0.97, row['low'])
        open_trade['status'] = 'KARA KUĞU (ACİL SAT)'
        pnl_val = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
        open_trade['pnl_pct'] = (5.0 + pnl_val) / 2.0 if open_trade.get("partial_tp_hit", False) else pnl_val
        completed_trades.append(open_trade)
        print(f"\n🚨 KIRMIZI ALARM: {sym} ({curr_time}) - Fiyat aniden %3'ten fazla çakıldı. Savaş Masası İPTAL, ACİL SATILDI!")
        return None

    score = _check_war_table(row, df_1h, curr_time, False, sym, open_trade)
    if score is not None:
        if score >= 2:
            print("🤖 ASİSTAN KARARI: İŞLEMDE KAL! (SATMA). Tahtacı stop patlatıyor olabilir.")
            return open_trade
        else:
            print("🤖 ASİSTAN KARARI: GERÇEK ÇÖKÜŞ (SAT).")
            open_trade['exit_time'] = curr_time
            open_trade['exit_price'] = row['close']
            open_trade['status'] = 'GERÇEK ÇÖKÜŞ (SAT)'
            pnl_val = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
            open_trade['pnl_pct'] = (5.0 + pnl_val) / 2.0 if open_trade.get("partial_tp_hit", False) else pnl_val
            completed_trades.append(open_trade)
            return None
    return open_trade

def _simulate_bist_trade(row, open_trade, curr_time, df_1h, sym):
    if 'tp' not in open_trade:
        atr = open_trade.get('entry_atr')
        if not atr: atr = open_trade['entry_price'] * 0.02
        open_trade['tp'] = open_trade['entry_price'] + (1.5 * atr)

    if row['high'] >= open_trade['tp']:
        open_trade['exit_time'] = curr_time
        open_trade['exit_price'] = open_trade['tp']
        open_trade['status'] = 'KAR AL (TP)'
        pnl_val = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
        open_trade['pnl_pct'] = pnl_val
        completed_trades.append(open_trade)
        return None

    profit_pct = ((row['high'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
    if profit_pct >= 1.5 and not open_trade.get("partial_tp_hit", False):
        open_trade["partial_tp_hit"] = True
        if open_trade['sl'] < open_trade['entry_price']:
            open_trade['sl'] = open_trade['entry_price']

    if profit_pct >= 15.0:
        current_trailing_dist = row['high'] * 0.025
    elif profit_pct >= 10.0:
        current_trailing_dist = row['high'] * 0.040
    else:
        current_trailing_dist = open_trade['trailing_dist']

    if row['high'] > open_trade['highest_high']:
        open_trade['highest_high'] = row['high']
        new_sl = open_trade['highest_high'] - current_trailing_dist
        if new_sl > open_trade['sl']:
            open_trade['sl'] = new_sl

    if row['low'] <= open_trade['sl']:
        return _handle_bist_stop_hit(row, open_trade, curr_time, df_1h, sym)
    return open_trade

def _is_crypto_weekend(curr_time):
    if curr_time.weekday() == 4 and curr_time.hour >= 23: 
        return True
    if curr_time.weekday() == 5: 
        return True
    if curr_time.weekday() == 6 and curr_time.hour < 23: 
        return True
    return False

def _check_crypto_dip_hunter(row, curr_time, sym, is_weekend):
    if is_weekend:
        return None
    current_price = row['close']
    if row.get('RSI_14', 100) < 28 and row.get('volume', 0) > (2.0 * row.get('vol_sma_20', 99999999)):
        if current_price > row.get('EMA_20', current_price*2) and current_price > row['open']:
            sl = row['low'] * 0.99
            return {
                'symbol': sym, 'market': 'KRIPTO', 'strategy': 'Kripto 1: Dip Avcılığı', 'entry_time': curr_time,
                'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': (current_price - sl)
            }
    return None

def _check_crypto_trend_following(row, curr_time, sym, last_1d, atr_val, dynamic_sl_dist):
    current_price = row['close']
    if last_1d.get('EMA_20', 0) > last_1d.get('EMA_50', current_price*2) and last_1d['close'] > last_1d.get('EMA_20', current_price*2):
        if row.get('ADX_14', 0) > 25:
            vol_sma = row.get('vol_sma_20', 0)
            if vol_sma > 0 and row.get('volume', 0) < vol_sma * config.CRYPTO_TREND_VOLUME_SMA_MULT:
                return None
            if row['low'] <= row.get('EMA_20', 0) and current_price > row.get('EMA_20', current_price*2) and current_price > row['open']:
                sl_atr = current_price - (1.5 * atr_val)
                sl_ema = row.get('EMA_50', current_price) * 0.98
                sl = max(sl_atr, sl_ema)
                return {
                    'symbol': sym, 'market': 'KRIPTO', 'strategy': 'Kripto 2: Trend Takibi', 'entry_time': curr_time,
                    'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': dynamic_sl_dist
                }
    return None

def _check_crypto_retest(row, curr_time, sym, avail_1d, df_4h, is_weekend):
    if is_weekend:
        return None
    if row.get('RSI_14', 0) >= config.CRYPTO_RETEST_RSI_MAX:
        return None
    if row.get('ADX_14', 0) < config.CRYPTO_RETEST_ADX_MIN:
        return None
    current_price = row['close']
    cols = avail_1d.columns
    bb_upper_col = [c for c in cols if 'BBU' in c]
    bb_lower_col = [c for c in cols if 'BBL' in c]
    bb_mid_col = [c for c in cols if 'BBM' in c]
    if len(bb_upper_col) == 0 or len(bb_lower_col) == 0 or len(bb_mid_col) == 0:
        return None
    bb_width_series = (avail_1d[bb_upper_col[0]] - avail_1d[bb_lower_col[0]]) / avail_1d[bb_mid_col[0]]
    min_width_30d = bb_width_series.tail(30).min()
    last_width = bb_width_series.iloc[-1]
    
    if last_width > min_width_30d * 1.20:
        return None
    vol_sma = row.get('vol_sma_20', 99999999)
    if row['volume'] <= (2.0 * vol_sma):
        return None
    avail_4h_for_high = df_4h[df_4h.index <= curr_time]
    local_high = avail_4h_for_high['high'].tail(15).max()
    if row['low'] > local_high * 0.99:
        return None
    if current_price <= row['open']:
        return None
    sl = current_price * 0.95
    return {
        'symbol': sym, 'market': 'KRIPTO', 'strategy': 'Kripto 3: Retest', 'entry_time': curr_time,
        'entry_price': current_price, 'sl': sl, 'highest_high': current_price, 'trailing_dist': (current_price - sl)
    }

def _is_btc_not_pumping(df_btc, curr_time):
    if df_btc is None:
        return True
    sliced_btc = df_btc[df_btc.index <= curr_time.floor('d')].copy()
    if len(sliced_btc) >= 20:
        sliced_btc.ta.ema(length=20, append=True)
        btc_last = sliced_btc.iloc[-1]
        btc_prev = sliced_btc.iloc[-2]
        btc_ema20 = btc_last.get('EMA_20', 999999)
        if (btc_last['close'] > btc_ema20) and (btc_last['close'] > btc_prev['high']):
            return False
    return True

def _check_crypto_short_fomo(row, curr_time, sym, avail_4h_for_high, atr_val):
    current_price = row['close']
    if row.get('RSI_14', 0) <= 85:
        return None
    body = abs(current_price - row['open'])
    upper_wick = row['high'] - max(current_price, row['open'])
    if current_price >= row['open'] or upper_wick <= (2 * body):
        return None
    recent_high = avail_4h_for_high['high'].tail(5).max()
    sl_structural = recent_high * 1.01
    sl_atr = current_price + (2.0 * atr_val)
    sl = max(sl_structural, sl_atr)
    return {
        'symbol': sym, 'market': 'KRIPTO', 'strategy': 'SHORT 1: FOMO İNFAZI', 'signal': 'SAT',
        'entry_time': curr_time, 'entry_price': current_price, 'sl': sl,
        'lowest_low': current_price, 'trailing_dist': (sl - current_price)
    }

def _check_crypto_short_waterfall(row, curr_time, sym, avail_4h_for_high, last_1d, atr_val):
    current_price = row['close']
    if last_1d.get('EMA_20', 0) >= last_1d.get('EMA_50', 0) or current_price >= last_1d.get('EMA_20', 0):
        return None
    if row.get('ADX_14', 0) <= config.CRYPTO_SHORT2_ADX_MIN:
        return None
    vol_sma = row.get('vol_sma_20', 0)
    if vol_sma > 0 and row.get('volume', 0) < vol_sma * config.CRYPTO_SHORT2_VOLUME_SMA_MULT:
        return None
    if row['high'] < row.get('EMA_20', 999999) or current_price >= row.get('EMA_20', 0) or current_price >= row['open']:
        return None
    sl_atr = current_price + (1.5 * atr_val)
    recent_high = avail_4h_for_high['high'].tail(5).max()
    sl_structural = recent_high * 1.01
    sl = max(sl_structural, sl_atr)
    return {
        'symbol': sym, 'market': 'KRIPTO', 'strategy': 'SHORT 2: KANLI ŞELALE SÖRFÜ', 'signal': 'SAT',
        'entry_time': curr_time, 'entry_price': current_price, 'sl': sl,
        'lowest_low': current_price, 'trailing_dist': (sl - current_price)
    }

def _check_crypto_short_cliff(row, curr_time, sym, avail_4h_for_high):
    current_price = row['close']
    if len(avail_4h_for_high) < 90:
        return None
    support_lookback = avail_4h_for_high['low'].iloc[-75:-15].min()
    breakout_zone = avail_4h_for_high.iloc[-15:-1]
    if breakout_zone['low'].min() >= support_lookback:
        return None
    if current_price >= support_lookback:
        return None
    recent_high = max(row['high'], avail_4h_for_high.iloc[-2]['high'])
    proximity = (support_lookback - recent_high) / support_lookback
    if not (0 <= proximity <= 0.015) or current_price >= row['open']:
        return None
    sl = support_lookback * 1.02
    return {
        'symbol': sym, 'market': 'KRIPTO', 'strategy': 'SHORT 3: UÇURUM ÇÖKÜŞÜ', 'signal': 'SAT',
        'entry_time': curr_time, 'entry_price': current_price, 'sl': sl,
        'lowest_low': current_price, 'trailing_dist': (sl - current_price)
    }

def _check_crypto_shorts(row, curr_time, sym, df_4h, last_1d, atr_val):
    avail_4h_for_high = df_4h[df_4h.index <= curr_time]
    res1 = _check_crypto_short_fomo(row, curr_time, sym, avail_4h_for_high, atr_val)
    if res1:
        return res1
    res2 = _check_crypto_short_waterfall(row, curr_time, sym, avail_4h_for_high, last_1d, atr_val)
    if res2:
        return res2
    res3 = _check_crypto_short_cliff(row, curr_time, sym, avail_4h_for_high)
    if res3:
        return res3
    return None
def _check_crypto_squeeze(row, curr_time, sym, df_4h, last_1d):
    avail_4h = df_4h[df_4h.index <= curr_time]
    if len(avail_4h) < 20:
        return None
    sq_fired, sq_dir, sq_candle = detect_squeeze(avail_4h)
    if sq_fired and sq_dir is not None:
        if row.get('ADX_14', 0) < config.CRYPTO_SQUEEZE_ADX_MIN:
            return None
        trend_up = (last_1d is not None and 
                    not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')) and
                    last_1d.get('EMA_20', 0) > last_1d.get('EMA_50', 0))
        valid_breakout = (sq_dir == "up" and trend_up) or (sq_dir == "down" and not trend_up)
        if valid_breakout:
            if sq_dir == "up" and row.get('ADX_14', 0) < config.CRYPTO_SQUEEZE_LONG_ADX_MIN:
                return None
            sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
            ema20_4h = row.get('EMA_20', row['close'])
            if sq_dir == "up":
                sl = min(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                sl_dist = abs(row['close'] - sl)
                tp = row['close'] + (sl_dist * config.BEAR_HUNTER_TP_RR)
                return {
                    'symbol': sym, 'market': 'KRIPTO', 'strategy': 'KRİPTO 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)', 'signal': 'AL',
                    'entry_time': curr_time, 'entry_price': row['close'], 'sl': sl, 'tp': tp,
                    'highest_high': row['close'], 'trailing_dist': sl_dist
                }
            else:
                sl = max(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                sl_dist = abs(sl - row['close'])
                tp = row['close'] - (sl_dist * config.BEAR_HUNTER_TP_RR)
                return {
                    'symbol': sym, 'market': 'KRIPTO', 'strategy': 'KRİPTO 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)', 'signal': 'SAT',
                    'entry_time': curr_time, 'entry_price': row['close'], 'sl': sl, 'tp': tp,
                    'lowest_low': row['close'], 'trailing_dist': sl_dist
                }
    return None

def _check_crypto_vwap(row, curr_time, sym, df_4h, last_1d):
    if last_1d is None or pd.isna(last_1d.get('EMA_20')) or pd.isna(last_1d.get('EMA_50')):
        return None
    if last_1d['EMA_20'] <= last_1d['EMA_50']:
        return None
    if row.get('ADX_14', 0) <= config.CRYPTO_VWAP_ADX_MIN:
        return None
        
    avail_4h = df_4h[df_4h.index <= curr_time]
    if len(avail_4h) < 20:
        return None
    vwap_val = calculate_anchored_vwap(avail_4h, anchor_type="weekly")
    if vwap_val is not None:
        bounce_ok, wick_low = detect_vwap_bounce(avail_4h, vwap_val)
        if bounce_ok and wick_low is not None:
            sl = wick_low * config.CRYPTO_VWAP_SL_MULT
            sl_dist = abs(row['close'] - sl)
            tp = row['close'] + (sl_dist * config.BEAR_HUNTER_TP_RR)
            return {
                'symbol': sym, 'market': 'KRIPTO', 'strategy': 'KRİPTO 6: VWAP KURUMSAL MIKNATISI', 'signal': 'AL',
                'entry_time': curr_time, 'entry_price': row['close'], 'sl': sl, 'tp': tp,
                'highest_high': row['close'], 'trailing_dist': sl_dist
            }
    return None

def _check_crypto_obv(row, curr_time, sym, df_1d, last_1d):
    avail_1d = df_1d[df_1d.index <= curr_time.floor('d')]
    if len(avail_1d) < 30:
        return None
    obv_ok, obv_box_high, obv_box_low = detect_obv_accumulation(avail_1d, max_change_pct=config.CRYPTO_OBV_ACC_MAX_CHANGE_PCT)
    if obv_ok and obv_box_high is not None:
        sl = (obv_box_high + obv_box_low) / 2
        sl_dist = abs(row['close'] - sl)
        tp = row['close'] + (sl_dist * config.BEAR_HUNTER_TP_RR)
        return {
            'symbol': sym, 'market': 'KRIPTO', 'strategy': 'KRİPTO 7: SESSİZ BİRİKİM RADARI (OBV)', 'signal': 'AL',
            'entry_time': curr_time, 'entry_price': row['close'], 'sl': sl, 'tp': tp,
            'highest_high': row['close'], 'trailing_dist': sl_dist
        }
    return None

def _check_crypto_entry_triggers(row, curr_time, sym, df_1d, df_4h, df_btc, atr_val, dynamic_sl_dist):
    avail_1d = df_1d[df_1d.index <= curr_time.floor('d')]
    if len(df_4h[df_4h.index <= curr_time]) < 20 or len(avail_1d) < 30: 
        return None
        
    last_1d = avail_1d.iloc[-1]
    is_weekend = _is_crypto_weekend(curr_time)
    
    res = None
    res_dip = _check_crypto_dip_hunter(row, curr_time, sym, is_weekend)
    if res_dip:
        res = res_dip
    else:
        res_trend = _check_crypto_trend_following(row, curr_time, sym, last_1d, atr_val, dynamic_sl_dist)
        if res_trend:
            res = res_trend
        else:
            res_retest = _check_crypto_retest(row, curr_time, sym, avail_1d, df_4h, is_weekend)
            if res_retest:
                res = res_retest
            else:
                res_squeeze = _check_crypto_squeeze(row, curr_time, sym, df_4h, last_1d)
                if res_squeeze:
                    res = res_squeeze
                else:
                    res_vwap = _check_crypto_vwap(row, curr_time, sym, df_4h, last_1d)
                    if res_vwap:
                        res = res_vwap
                    else:
                        res_obv = _check_crypto_obv(row, curr_time, sym, df_1d, last_1d)
                        if res_obv:
                            res = res_obv
                        elif not is_weekend and _is_btc_not_pumping(df_btc, curr_time):
                            res_short = _check_crypto_shorts(row, curr_time, sym, df_4h, last_1d, atr_val)
                            if res_short:
                                res = res_short
                                
    if res:
        res['entry_rsi'] = float(row.get('RSI_14')) if not pd.isna(row.get('RSI_14')) else None
        res['entry_adx'] = float(row.get('ADX_14')) if not pd.isna(row.get('ADX_14')) else None
        res['entry_volume'] = float(row.get('volume')) if not pd.isna(row.get('volume')) else None
        res['entry_vol_sma'] = float(row.get('vol_sma_20')) if not pd.isna(row.get('vol_sma_20')) else None
        res['entry_atr'] = float(atr_val) if not pd.isna(atr_val) else None
        return res
            
    return None

def _handle_crypto_long_stop_hit(row, open_trade, curr_time, df_4h, sym):
    if row['low'] <= open_trade['sl'] * 0.97:
        open_trade['exit_time'] = curr_time
        open_trade['exit_price'] = min(open_trade['sl'] * 0.97, row['low'])
        open_trade['status'] = 'KARA KUĞU (ACİL SAT)'
        pnl_val = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
        open_trade['pnl_pct'] = (5.0 + pnl_val) / 2.0 if open_trade.get("partial_tp_hit", False) else pnl_val
        completed_trades.append(open_trade)
        print(f"\n🚨 KIRMIZI ALARM: {sym} ({curr_time}) - Fiyat aniden %3'ten fazla çakıldı. Savaş Masası İPTAL, ACİL SATILDI!")
        return None
        
    score = _check_war_table(row, df_4h, curr_time, False, sym, open_trade)
    if score is not None:
        if score >= 2:
            print("🤖 ASİSTAN KARARI: İŞLEMDE KAL! (SATMA). Tahtacı stop patlatıyor olabilir.")
            return open_trade
        else:
            print("🤖 ASİSTAN KARARI: GERÇEK ÇÖKÜŞ (SAT).")
            open_trade['exit_time'] = curr_time
            open_trade['exit_price'] = row['close']
            open_trade['status'] = 'GERÇEK ÇÖKÜŞ (SAT)'
            pnl_val = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
            open_trade['pnl_pct'] = (5.0 + pnl_val) / 2.0 if open_trade.get("partial_tp_hit", False) else pnl_val
            completed_trades.append(open_trade)
            return None
    return open_trade

def _simulate_crypto_long_trade(row, open_trade, curr_time, df_4h, sym):
    if 'tp' not in open_trade:
        atr = open_trade.get('entry_atr')
        if not atr: atr = open_trade['entry_price'] * 0.02
        open_trade['tp'] = open_trade['entry_price'] + (1.5 * atr)

    if row['high'] >= open_trade['tp']:
        open_trade['exit_time'] = curr_time
        open_trade['exit_price'] = open_trade['tp']
        open_trade['status'] = 'KAR AL (TP)'
        pnl_val = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
        open_trade['pnl_pct'] = pnl_val
        completed_trades.append(open_trade)
        return None

    profit_pct = ((row['high'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
    if profit_pct >= 1.5 and not open_trade.get("partial_tp_hit", False):
        open_trade["partial_tp_hit"] = True
        if open_trade['sl'] < open_trade['entry_price']:
            open_trade['sl'] = open_trade['entry_price']
            
    if profit_pct >= 15.0:
        current_trailing_dist = row['high'] * 0.005
    elif profit_pct >= 10.0:
        current_trailing_dist = row['high'] * 0.015
    else:
        current_trailing_dist = open_trade['trailing_dist']

    if row['high'] > open_trade['highest_high']:
        open_trade['highest_high'] = row['high']
        new_sl = open_trade['highest_high'] - current_trailing_dist
        if new_sl > open_trade['sl']:
            open_trade['sl'] = new_sl

    if row['low'] <= open_trade['sl']:
        return _handle_crypto_long_stop_hit(row, open_trade, curr_time, df_4h, sym)
    return open_trade

def _handle_crypto_short_stop_hit(row, open_trade, curr_time, df_4h, sym, scale_out_target):
    if row['high'] >= open_trade['sl'] * 1.03:
        open_trade['exit_time'] = curr_time
        open_trade['exit_price'] = max(open_trade['sl'] * 1.03, row['high'])
        open_trade['status'] = 'KARA KUĞU (ACİL ÇIK)'
        pnl_val = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
        open_trade['pnl_pct'] = (scale_out_target + pnl_val) / 2.0 if open_trade.get("partial_tp_hit", False) else pnl_val
        completed_trades.append(open_trade)
        print(f"\n🚨 KIRMIZI ALARM: {sym} ({curr_time}) - Fiyat aniden %3'ten fazla fırladı. Savaş Masası İPTAL, ACİL ÇIKILDI!")
        return None
        
    score = _check_war_table(row, df_4h, curr_time, True, sym, open_trade)
    if score is not None:
        if score >= 2:
            print("🤖 ASİSTAN KARARI: İŞLEMDE KAL! (ÇIKMA). Tahtacı stop patlatıyor olabilir.")
            return open_trade
        else:
            print("🤖 ASİSTAN KARARI: GERÇEK YÜKSELİŞ (ÇIK).")
            open_trade['exit_time'] = curr_time
            open_trade['exit_price'] = row['close']
            open_trade['status'] = 'GERÇEK YÜKSELİŞ (ÇIK)'
            pnl_val = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
            open_trade['pnl_pct'] = (scale_out_target + pnl_val) / 2.0 if open_trade.get("partial_tp_hit", False) else pnl_val
            completed_trades.append(open_trade)
            return None
    return open_trade

def _update_crypto_short_trailing(row, open_trade, profit_pct, strategy_name):
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
    return current_trailing_dist

def _simulate_crypto_short_trade(row, open_trade, curr_time, df_4h, sym):
    if 'tp' not in open_trade:
        atr = open_trade.get('entry_atr')
        if not atr: atr = open_trade['entry_price'] * 0.02
        open_trade['tp'] = open_trade['entry_price'] - (1.5 * atr)

    if row['low'] <= open_trade['tp']:
        open_trade['exit_time'] = curr_time
        open_trade['exit_price'] = open_trade['tp']
        open_trade['status'] = 'KAR AL (TP)'
        pnl_val = ((open_trade['entry_price'] - open_trade['exit_price']) / open_trade['entry_price']) * 100
        open_trade['pnl_pct'] = pnl_val
        completed_trades.append(open_trade)
        return None

    profit_pct = ((open_trade['entry_price'] - row['low']) / open_trade['entry_price']) * 100
    strategy_name = open_trade['strategy']
    scale_out_target = 10.0 if "FOMO İNFAZI" in strategy_name else 1.5
    
    if profit_pct >= scale_out_target and not open_trade.get("partial_tp_hit", False):
        open_trade["partial_tp_hit"] = True
        if open_trade['sl'] > open_trade['entry_price']:
            open_trade['sl'] = open_trade['entry_price']
            
    current_trailing_dist = _update_crypto_short_trailing(row, open_trade, profit_pct, strategy_name)

    if row['low'] < open_trade['lowest_low']:
        open_trade['lowest_low'] = row['low']
        new_sl = open_trade['lowest_low'] + current_trailing_dist
        if new_sl < open_trade['sl']:
            open_trade['sl'] = new_sl

    if row['high'] >= open_trade['sl']:
        return _handle_crypto_short_stop_hit(row, open_trade, curr_time, df_4h, sym, scale_out_target)
    return open_trade

def _prepare_bist_data(sym):
    df_1h = yf.download(sym, start=start_sim - timedelta(days=60), end=end_sim + timedelta(days=1), interval="1h", progress=False)
    df_1d = yf.download(sym, start=start_sim - timedelta(days=180), end=end_sim + timedelta(days=1), interval="1d", progress=False)
    
    if df_1h.empty or df_1d.empty:
        return None, None, None
        
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
    if len(df_4h) < 20: 
        return None, None, None
    df_4h.ta.adx(length=14, append=True)
    df_4h.ta.ema(length=5, append=True)
    df_4h.ta.ema(length=13, append=True)
    
    return df_1h, df_1d, df_4h

def _process_bist_bar(row, curr_time, open_trade, df_1h, df_1d, df_4h, sym):
    if open_trade is not None:
        return _simulate_bist_trade(row, open_trade, curr_time, df_1h, sym)
    
    curr_day = curr_time.normalize()
    avail_1d = df_1d[df_1d.index <= curr_day]
    avail_4h = df_4h[df_4h.index <= curr_time]
    
    if len(avail_1d) < 30 or len(avail_4h) < 20: 
        return None
    
    last_1d = avail_1d.iloc[-1]
    last_4h = avail_4h.iloc[-1]
    try:
        curr_pos = df_1h.index.get_loc(curr_time)
    except Exception:
        return None
    if curr_pos < 1: 
        return None
    prev_1h = df_1h.iloc[curr_pos - 1]
    current_price = row['close']
    
    atr_val = last_1d.get('ATRr_14', last_1d.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val): 
        atr_val = current_price * 0.02
    dynamic_sl_dist = max(2.0 * atr_val, current_price * 0.03)
    
    return _check_bist_entry_triggers(row, curr_time, sym, df_1d, df_1h, prev_1h, last_1d, last_4h, curr_pos, atr_val, dynamic_sl_dist)

def simulate_bist():
    print("BIST PnL Simülasyonu Başlatılıyor...")
    for sym in TOP_BIST:
        df_1h, df_1d, df_4h = _prepare_bist_data(sym)
        if df_1h is None:
            continue
            
        sim_bars = df_1h[(df_1h.index >= start_sim) & (df_1h.index <= end_sim)]
        open_trade = None
        
        for idx, row in sim_bars.iterrows():
            curr_time = idx
            res = _process_bist_bar(row, curr_time, open_trade, df_1h, df_1d, df_4h, sym)
            if open_trade is not None:
                open_trade = res
            else:
                if res is not None:
                    open_trade = res
        
        if open_trade is not None:
            last_bar = sim_bars.iloc[-1]
            open_trade['exit_time'] = sim_bars.index[-1]
            open_trade['exit_price'] = last_bar['close']
            open_trade['status'] = 'OPEN_AT_END'
            end_pnl = ((open_trade['exit_price'] - open_trade['entry_price']) / open_trade['entry_price']) * 100
            open_trade['pnl_pct'] = (5.0 + end_pnl) / 2.0 if open_trade.get("partial_tp_hit", False) else end_pnl
            completed_trades.append(open_trade)

def _prepare_crypto_data(sym, start_ts):
    try:
        ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', since=start_ts, limit=1000)
        if not ohlcv_4h: 
            return None, None
        df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_4h['timestamp'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
        df_4h.set_index('timestamp', inplace=True)
        
        df_1d = df_4h.resample('1d').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        
        df_4h = inject_smart_indicators(df_4h)
        df_4h['vol_sma_20'] = ta.sma(df_4h['volume'], length=20)
        
        df_1d = inject_smart_indicators(df_1d)
        return df_4h, df_1d
    except Exception as e:
        logging.warning(f"[simulate_crypto] {sym} veri hazırlama hatası: {e}")
        return None, None

def _process_crypto_bar(row, curr_time, open_trade, df_4h, df_1d, df_btc, sym):
    if open_trade is not None:
        is_short = open_trade.get('signal') == 'SAT'
        if not is_short:
            return _simulate_crypto_long_trade(row, open_trade, curr_time, df_4h, sym)
        else:
            return _simulate_crypto_short_trade(row, open_trade, curr_time, df_4h, sym)
    
    current_price = row['close']
    atr_val = row.get('ATRr_14', row.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val): 
        atr_val = current_price * 0.02
    dynamic_sl_dist = 1.5 * atr_val
    
    return _check_crypto_entry_triggers(row, curr_time, sym, df_1d, df_4h, df_btc, atr_val, dynamic_sl_dist)

def _handle_open_trade_at_end(open_trade, last_close):
    open_trade['exit_price'] = last_close
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

def simulate_crypto():
    print("Kripto PnL Simülasyonu Başlatılıyor...")
    
    start_ts = int(start_sim.timestamp() * 1000) - (60 * 24 * 60 * 60 * 1000)
    
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
        df_4h, df_1d = _prepare_crypto_data(sym, start_ts)
        if df_4h is None:
            continue
            
        sim_bars = df_4h[(df_4h.index >= start_sim) & (df_4h.index <= end_sim)]
        open_trade = None
        
        for idx, row in sim_bars.iterrows():
            curr_time = idx
            res = _process_crypto_bar(row, curr_time, open_trade, df_4h, df_1d, df_btc, sym)
            if open_trade is not None:
                open_trade = res
            else:
                if res is not None:
                    open_trade = res
                                    
        if open_trade is not None:
            last_bar = sim_bars.iloc[-1]
            open_trade['exit_time'] = sim_bars.index[-1]
            _handle_open_trade_at_end(open_trade, last_bar['close'])

def simulate_pnl():
    completed_trades.clear()
    # BIST simülasyonu devre dışı bırakıldı (Sadece Kripto varlıklar için)
    # simulate_bist()
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
        
        print("\n=== GENEL KRİPTO ÖZETİ ===")
        print(f"Toplam İşlem: {total_trades}")
        print(f"Karlı İşlem: {wins}")
        print(f"Zararlı İşlem: {losses}")
        print(f"Kazanma Oranı (Win Rate): %{(wins/total_trades*100):.2f}" if total_trades > 0 else "N/A")
        print(f"Toplam Net Getiri Yüzdesi: %{total_pnl:.2f}")
        
        # Strateji bazlı kırılım analizi
        print("\n=== STRATEJİ BAZLI ANALİZ KIRILIMI ===")
        strategies = df_trades['strategy'].unique()
        for strat in sorted(strategies):
            strat_trades = df_trades[df_trades['strategy'] == strat]
            s_total = len(strat_trades)
            s_wins = len(strat_trades[strat_trades['pnl_pct'] > 0])
            s_losses = len(strat_trades[strat_trades['pnl_pct'] <= 0])
            s_wr = (s_wins / s_total * 100) if s_total > 0 else 0
            s_pnl = strat_trades['pnl_pct'].sum()
            print(f"\nStrateji: {strat}")
            print(f"  └─ Toplam Sinyal/İşlem Sayısı: {s_total}")
            print(f"  └─ W/R Oranı                 : %{s_wr:.2f} ({s_wins} Win / {s_losses} Loss)")
            print(f"  └─ Toplam Net PnL            : %{s_pnl:.2f}")
            
        df_trades.to_csv("simulation_results.csv", index=False)
        print("\nTüm detaylı işlem logları ve giriş parametreleri 'simulation_results.csv' dosyasına kaydedildi.")
    else:
        print("Hiç işlem gerçekleşmedi.")

if __name__ == "__main__":
    simulate_pnl()
