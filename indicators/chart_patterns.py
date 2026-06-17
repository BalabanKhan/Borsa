import numpy as np
import pandas as pd
import config
import logging
import math
import pandas_ta as ta
from typing import Optional

def _check_squeeze_count(df, bbu_c, bbl_c, kcu_c, kcl_c):
    squeeze_count = 0
    for i in range(-6, -1):
        if abs(i) > len(df):
            continue
        r = df.iloc[i]
        if (not pd.isna(r.get(bbu_c)) and not pd.isna(r.get(kcu_c)) and
                r[bbu_c] < r[kcu_c] and r[bbl_c] > r[kcl_c]):
            squeeze_count += 1
    return squeeze_count >= 3

def _determine_squeeze_direction(last, prev, bbu_c, bbl_c):
    if last['close'] > last[bbu_c] and last['close'] > last['open']:
        if prev is not None and not pd.isna(prev.get(bbu_c)):
            if prev['close'] > prev[bbu_c] * 0.995:
                return "up"
        else:
            return "up"
    elif last['close'] < last[bbl_c] and last['close'] < last['open']:
        if prev is not None and not pd.isna(prev.get(bbl_c)):
            if prev['close'] < prev[bbl_c] * 1.005:
                return "down"
        else:
            return "down"
    return None

def _verify_squeeze_momentum(df, direction):
    if not config.SQUEEZE_MOMENTUM_ALIGN_REQUIRED:
        return True
    df.ta.macd(append=True)
    macdh_cols = [c for c in df.columns if 'MACDh' in c]
    if macdh_cols:
        macd_h = df[macdh_cols[0]]
        if len(macd_h) >= 2:
            is_rising = macd_h.iloc[-1] > macd_h.iloc[-2]
            if direction == "up" and not is_rising:
                return False
            elif direction == "down" and is_rising:
                return False
    return True

def _verify_squeeze_volume(df, last):
    vol_sma = df['volume'].rolling(config.IND_VOL_SMA_LENGTH).mean()
    if not pd.isna(vol_sma.iloc[-1]) and last['volume'] < vol_sma.iloc[-1] * config.IND_VOL_BREAKOUT_MULTIPLIER:
        return False
    return True

def detect_squeeze(df):
    """
    BB(20,2) Keltner(20, 1.5×ATR) içine girdi mi? Kırılım olduysa yön döner.
    Returns: (squeeze_fired, direction, breakout_candle)
    """
    if len(df) < 25:
        return False, None, None

    df = df.copy()

    if not [c for c in df.columns if 'BBU_20_2' in c]:
        df.ta.bbands(length=config.IND_BBANDS_LENGTH, std=config.IND_BBANDS_STD, append=True)
    if not [c for c in df.columns if 'KCU_20_1' in c]:
        df.ta.kc(length=config.IND_BBANDS_LENGTH, scalar=1.5, append=True)

    bbu = [c for c in df.columns if 'BBU' in c]
    bbl = [c for c in df.columns if 'BBL' in c]
    kcu = [c for c in df.columns if 'KCU' in c]
    kcl = [c for c in df.columns if 'KCL' in c]

    if not (bbu and bbl and kcu and kcl):
        return False, None, None

    bbu_c, bbl_c, kcu_c, kcl_c = bbu[0], bbl[0], kcu[0], kcl[0]

    if not _check_squeeze_count(df, bbu_c, bbl_c, kcu_c, kcl_c):
        return False, None, None

    last = df.iloc[-1]
    if pd.isna(last.get(bbu_c)) or pd.isna(last.get(bbl_c)):
        return False, None, None

    prev = df.iloc[-2] if len(df) >= 2 else None
    direction = _determine_squeeze_direction(last, prev, bbu_c, bbl_c)
    if direction is None:
        return False, None, None

    if not _verify_squeeze_momentum(df, direction):
        return False, None, None

    if not _verify_squeeze_volume(df, last):
        return False, None, None

    return True, direction, last

def detect_obv_accumulation(df, max_change_pct=config.OBV_ACC_MAX_CHANGE_PCT):
    """Fiyat yatayda + OBV yükseliyor + kutu kırılımı → sinyal.
    Returns: (breakout_confirmed, box_high, box_low)
    """
    if len(df) < config.IND_OBV_ACC_MIN_LEN:
        return False, None, None

    df = df.copy()

    if 'OBV' not in df.columns:
        df.ta.obv(append=True)
    if 'OBV' not in df.columns:
        return False, None, None

    recent_box = df.iloc[-config.IND_OBV_ACC_PERIOD - 1 : -1]
    
    price_chg = abs((recent_box['close'].iloc[-1] - recent_box['close'].iloc[0]) / recent_box['close'].iloc[0]) * 100
    if price_chg > max_change_pct:
        return False, None, None

    box_high = float(recent_box['close'].max())
    box_low = float(recent_box['close'].min())

    obv_short = df['OBV'].iloc[-config.IND_OBV_ACC_SHORT_PERIOD:].mean()
    obv_long = df['OBV'].iloc[-config.IND_OBV_ACC_PERIOD:].mean()
    if obv_short <= obv_long:
        return False, None, None

    obv_old_max = df['OBV'].iloc[-config.IND_OBV_ACC_PERIOD:-config.IND_OBV_ACC_SHORT_PERIOD].max()
    if df['OBV'].iloc[-config.IND_OBV_ACC_SHORT_PERIOD:].max() <= obv_old_max:
        return False, None, None

    last = df.iloc[-1]
    if last['close'] <= box_high:
        return False, None, None

    if config.OBV_SMA_ALIGN_REQUIRED:
        df['OBV_SMA'] = df['OBV'].rolling(config.OBV_SMA_PERIOD).mean()
        if not pd.isna(df['OBV_SMA'].iloc[-1]) and df['OBV'].iloc[-1] <= df['OBV_SMA'].iloc[-1]:
            return False, None, None

    vol_sma = df['volume'].rolling(config.IND_OBV_ACC_PERIOD).mean()
    if not pd.isna(vol_sma.iloc[-1]) and last['volume'] < vol_sma.iloc[-1] * config.IND_OBV_ACC_VOL_MULTIPLIER:
        return False, None, None

    return True, box_high, box_low

def detect_obv_accumulation_bist(df, max_change_pct=config.OBV_ACC_MAX_CHANGE_PCT):
    """BIST 8 için özel yeni matematiksel mantık:
    1. 18/20 Yatay Kutu: Son 20 mumdan en az 18'i dar bir kutu (max_change_pct) içinde kalmalı.
    2. Kutu Zirvesinin %1-3.5 Yukarı Kırılımı: Son kapanış kutu zirvesinin %1.0 ile %3.5 üstünde olmalı.
    3. En Yüksek OBV Kapanışı: Son günün OBV'si önceki 20 günün zirve OBV'sinden büyük olmalı.
    """
    if len(df) < config.IND_OBV_ACC_MIN_LEN:
        return False, None, None

    df = df.copy()

    if 'OBV' not in df.columns:
        df.ta.obv(append=True)
    if 'OBV' not in df.columns:
        return False, None, None

    closes = df['close'].iloc[-21:-1].tolist()
    sorted_closes = sorted(closes)

    best_window = None
    min_chg = float('inf')

    for i in range(3):
        w_low = sorted_closes[i]
        w_high = sorted_closes[i + 17]
        w_chg = ((w_high - w_low) / w_low) * 100
        if w_chg <= max_change_pct and w_chg < min_chg:
            min_chg = w_chg
            best_window = (w_low, w_high)

    if best_window is None:
        return False, None, None

    box_low, box_high = best_window

    last_close = float(df['close'].iloc[-1])
    breakout_pct = ((last_close - box_high) / box_high) * 100
    if not (1.0 <= breakout_pct <= 3.5):
        return False, None, None

    last_obv = float(df['OBV'].iloc[-1])
    prev_obv_max = float(df['OBV'].iloc[-21:-1].max())
    if last_obv <= prev_obv_max:
        return False, None, None

    if config.OBV_SMA_ALIGN_REQUIRED:
        df['OBV_SMA'] = df['OBV'].rolling(config.OBV_SMA_PERIOD).mean()
        if not pd.isna(df['OBV_SMA'].iloc[-1]) and df['OBV'].iloc[-1] <= df['OBV_SMA'].iloc[-1]:
            return False, None, None

    vol_sma = df['volume'].rolling(config.IND_OBV_ACC_PERIOD).mean()
    if not pd.isna(vol_sma.iloc[-1]) and df['volume'].iloc[-1] < vol_sma.iloc[-1] * config.IND_OBV_ACC_VOL_MULTIPLIER:
        return False, None, None

    return True, box_high, box_low

def calculate_orb_cage(df_15m):
    """BIST 10:00-11:00 kafesi + günlük VWAP. Returns: (cage_high, cage_low, cage_mid, vwap)"""
    if df_15m is None or df_15m.empty:
        return None, None, None, None
    today = df_15m.index[-1].date()

    df = df_15m.copy()
    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Europe/Istanbul")
        else:
            df.index = df.index.tz_convert("Europe/Istanbul")
    except Exception as e:
        logging.warning(f"[calculate_orb_cage] Timezone dönüşüm hatası: {e}")
        return None, None, None, None

    df_today = df[df.index.date == today]
    if len(df_today) < config.ORB_MIN_BARS:
        return None, None, None, None

    cage_bars = df_today[df_today.index.hour == config.ORB_CAGE_HOUR]
    if len(cage_bars) < 2:
        return None, None, None, None

    cage_high = float(cage_bars['high'].max())
    cage_low = float(cage_bars['low'].min())
    cage_mid = (cage_high + cage_low) / 2

    tp = (df_today['high'] + df_today['low'] + df_today['close']) / 3
    cum = (tp * df_today['volume']).cumsum()
    cum_vol = df_today['volume'].cumsum()
    today_vwap = float(cum.iloc[-1] / cum_vol.iloc[-1]) if not math.isclose(cum_vol.iloc[-1], 0.0, abs_tol=1e-8) else None

    return cage_high, cage_low, cage_mid, today_vwap

def calculate_time_specific_rvol(df_15m, target_hour: int, target_minute: int, period: int = 20) -> float:
    """
    Belirli bir saate (örneğin 10:15) ait son N günün ortalama hacmini hesaplar.
    """
    if df_15m is None or df_15m.empty:
        return 0.0
        
    try:
        df = df_15m.copy()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Europe/Istanbul")
        else:
            df.index = df.index.tz_convert("Europe/Istanbul")
            
        mask = (df.index.hour == target_hour) & (df.index.minute == target_minute)
        specific_bars = df[mask]
        
        if specific_bars.empty:
            return 0.0
            
        recent_bars = specific_bars.tail(period)
        avg_vol = recent_bars['volume'].mean()
        return float(avg_vol) if not math.isnan(avg_vol) else 0.0
        
    except Exception as e:
        logging.warning(f"[calculate_time_specific_rvol] Hata: {e}")
        return 0.0

def _check_pattern_hammer(ctx):
    if ctx['lower_shadow_curr'] >= config.CANDLE_HAMMER_LOWER_SHADOW_MULT * ctx['body_curr'] and ctx['upper_shadow_curr'] <= config.CANDLE_HAMMER_UPPER_SHADOW_LIMIT * ctx['tot_curr'] and ctx['body_curr'] > 0:
        if ctx['low_curr'] <= min(ctx['l'][ctx['idx']-5:ctx['idx']]):
            return "Hammer (Çekiç)", {"pattern": "Hammer", "body": ctx['body_curr'], "lower_shadow": ctx['lower_shadow_curr']}
    return None, {}

def _check_pattern_inverted_hammer(ctx):
    if ctx['upper_shadow_curr'] >= config.CANDLE_HAMMER_LOWER_SHADOW_MULT * ctx['body_curr'] and ctx['lower_shadow_curr'] <= config.CANDLE_HAMMER_UPPER_SHADOW_LIMIT * ctx['tot_curr'] and ctx['body_curr'] > 0:
        if ctx['low_curr'] <= min(ctx['l'][ctx['idx']-5:ctx['idx']]):
            return "Inverted Hammer (Ters Çekiç)", {"pattern": "Inverted Hammer", "body": ctx['body_curr'], "upper_shadow": ctx['upper_shadow_curr']}
    return None, {}

def _check_pattern_dragonfly_doji(ctx):
    if ctx['body_curr'] <= config.CANDLE_DRAGONFLY_BODY_LIMIT * ctx['tot_curr'] and ctx['lower_shadow_curr'] >= config.CANDLE_DRAGONFLY_LOWER_SHADOW_MULT * ctx['tot_curr'] and ctx['upper_shadow_curr'] <= config.CANDLE_HAMMER_UPPER_SHADOW_LIMIT * ctx['tot_curr']:
        if ctx['low_curr'] <= min(ctx['l'][ctx['idx']-5:ctx['idx']]):
            return "Dragonfly Doji (Yusufçuk Doji)", {"pattern": "Dragonfly Doji", "lower_shadow": ctx['lower_shadow_curr']}
    return None, {}

def _check_pattern_bullish_engulfing(ctx):
    if not ctx['is_green_prev'] and ctx['is_green_curr']:
        if ctx['open_curr'] <= ctx['close_prev'] and ctx['close_curr'] >= ctx['open_prev'] and (ctx['open_curr'] < ctx['close_prev'] or ctx['close_curr'] > ctx['open_prev']):
            if ctx['close_curr'] > ctx['close_prev']:
                return "Bullish Engulfing (Yutan Boğa)", {"pattern": "Bullish Engulfing", "body_prev": ctx['body_prev'], "body_curr": ctx['body_curr']}
    return None, {}

def _check_pattern_piercing_line(ctx):
    if not ctx['is_green_prev'] and ctx['is_green_curr']:
        half_body_prev = ctx['close_prev'] + 0.5 * (ctx['open_prev'] - ctx['close_prev'])
        if ctx['open_curr'] < ctx['close_prev'] and ctx['close_curr'] >= half_body_prev and ctx['close_curr'] < ctx['open_prev']:
            return "Piercing Line (Delen Hat)", {"pattern": "Piercing Line", "close_curr": ctx['close_curr'], "half_prev": half_body_prev}
    return None, {}

def _check_pattern_tweezer_bottom(ctx):
    diff_lows = abs(ctx['low_curr'] - ctx['low_prev']) / min(ctx['low_curr'], ctx['low_prev']) * 100
    if diff_lows <= 0.05 and ctx['is_green_curr']:
        if ctx['low_curr'] <= min(ctx['l'][ctx['idx']-8:ctx['idx']]):
            return "Tweezer Bottom (Cımbız Dip)", {"pattern": "Tweezer Bottom", "low_diff_pct": diff_lows}
    return None, {}

def _check_pattern_morning_star(ctx):
    if not ctx['is_green_prev2'] and ctx['is_green_curr']:
        if ctx['body_prev'] <= config.CANDLE_MORNING_STAR_BODY_LIMIT * ctx['body_prev2']:
            half_body_prev2 = ctx['close_prev2'] + 0.5 * (ctx['open_prev2'] - ctx['close_prev2'])
            if ctx['close_curr'] >= half_body_prev2 and ctx['open_curr'] >= ctx['close_prev']:
                return "Morning Star (Sabah Yıldızı)", {"pattern": "Morning Star"}
    return None, {}

def _check_pattern_three_white_soldiers(ctx):
    if ctx['is_green_prev2'] and ctx['is_green_prev'] and ctx['is_green_curr']:
        if ctx['close_curr'] > ctx['close_prev'] > ctx['close_prev2']:
            if ctx['body_curr'] > config.CANDLE_SOLDIERS_BODY_MIN * ctx['atr'] and ctx['body_prev'] > config.CANDLE_SOLDIERS_BODY_MIN * ctx['atr'] and ctx['body_prev2'] > config.CANDLE_SOLDIERS_BODY_MIN * ctx['atr']:
                if ctx['upper_shadow_curr'] <= config.CANDLE_SOLDIERS_SHADOW_LIMIT * ctx['body_curr'] and (ctx['high_prev'] - ctx['close_prev']) <= config.CANDLE_SOLDIERS_SHADOW_LIMIT * ctx['body_prev'] and (ctx['high_prev2'] - ctx['close_prev2']) <= config.CANDLE_SOLDIERS_SHADOW_LIMIT * ctx['body_prev2']:
                    return "Three White Soldiers (Üç Beyaz Asker)", {"pattern": "Three White Soldiers"}
    return None, {}

def detect_bullish_candlestick_pattern(df_4h) -> tuple[Optional[str], dict]:
    if df_4h is None or len(df_4h) < 10:
        return None, {}

    o = df_4h['open'].values
    h = df_4h['high'].values
    l = df_4h['low'].values
    c = df_4h['close'].values
    
    atr_series = df_4h.ta.atr(length=14) if 'ATR_14' not in df_4h.columns else df_4h['ATR_14']
    atr = float(atr_series.iloc[-1]) if atr_series is not None and not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (h[-1] - l[-1])
    if atr <= 0:
        atr = 1e-8

    idx = len(df_4h) - 1

    open_curr = float(o[idx])
    high_curr = float(h[idx])
    low_curr = float(l[idx])
    close_curr = float(c[idx])
    body_curr = abs(close_curr - open_curr)
    tot_curr = high_curr - low_curr if high_curr - low_curr > 0 else 1e-8
    upper_shadow_curr = high_curr - max(open_curr, close_curr)
    lower_shadow_curr = min(open_curr, close_curr) - low_curr
    is_green_curr = close_curr > open_curr

    open_prev = float(o[idx - 1])
    high_prev = float(h[idx - 1])
    low_prev = float(l[idx - 1])
    close_prev = float(c[idx - 1])
    body_prev = abs(close_prev - open_prev)
    is_green_prev = close_prev > open_prev

    open_prev2 = float(o[idx - 2])
    high_prev2 = float(h[idx - 2])
    low_prev2 = float(l[idx - 2])
    close_prev2 = float(c[idx - 2])
    body_prev2 = abs(close_prev2 - open_prev2)
    is_green_prev2 = close_prev2 > open_prev2

    ctx = {
        'o': o, 'h': h, 'l': l, 'c': c, 'atr': atr, 'idx': idx,
        'open_curr': open_curr, 'high_curr': high_curr, 'low_curr': low_curr, 'close_curr': close_curr,
        'body_curr': body_curr, 'tot_curr': tot_curr, 'upper_shadow_curr': upper_shadow_curr, 'lower_shadow_curr': lower_shadow_curr,
        'is_green_curr': is_green_curr,
        'open_prev': open_prev, 'high_prev': high_prev, 'low_prev': low_prev, 'close_prev': close_prev,
        'body_prev': body_prev, 'is_green_prev': is_green_prev,
        'open_prev2': open_prev2, 'high_prev2': high_prev2, 'low_prev2': low_prev2, 'close_prev2': close_prev2,
        'body_prev2': body_prev2, 'is_green_prev2': is_green_prev2
    }

    checkers = [
        _check_pattern_hammer,
        _check_pattern_inverted_hammer,
        _check_pattern_dragonfly_doji,
        _check_pattern_bullish_engulfing,
        _check_pattern_piercing_line,
        _check_pattern_tweezer_bottom,
        _check_morning_star,
        _check_pattern_three_white_soldiers
    ]

    # Support custom helper sabah yıldızı (morning star) renamed to morning_star or mapped
    # The original Morning star check was named _check_pattern_morning_star
    for check in checkers:
        try:
            name, details = check(ctx)
            if name:
                return name, details
        except NameError:
            if check == _check_morning_star:
                name, details = _check_pattern_morning_star(ctx)
                if name:
                    return name, details

    return None, {}

def _check_morning_star(ctx):
    return _check_pattern_morning_star(ctx)

def check_near_support(current_price: float, df_4h, df_1d, tolerance_pct: float = 2.0) -> tuple[bool, str]:
    """
    Fiyatın önemli destek seviyelerine yakınlığını kontrol eder.
    Destekler:
    - 4H EMA_8, EMA_21
    - 1D EMA_21, SMA_50, SMA_200
    - 4H Bollinger Alt Bandı
    """
    import pandas as pd
    if df_4h is None or len(df_4h) < 10 or df_1d is None or len(df_1d) < 10:
        return False, "Yetersiz veri"

    supports = {}
    
    for length in [8, 21]:
        col = f"EMA_{length}"
        if col in df_4h.columns:
            supports[f"4H {col}"] = float(df_4h[col].iloc[-1])
            
    for col in ["EMA_21", "SMA_50", "SMA_200"]:
        if col in df_1d.columns:
            supports[f"1D {col}"] = float(df_1d[col].iloc[-1])

    bbl_cols = [c for c in df_4h.columns if 'BBL' in c]
    if bbl_cols:
        supports["4H BBL"] = float(df_4h[bbl_cols[0]].iloc[-1])

    closest_support = None
    min_dist_pct = float('inf')
    
    for name, val in supports.items():
        if pd.isna(val) or val <= 0:
            continue
        dist_pct = (current_price - val) / val * 100
        if -0.5 <= dist_pct <= tolerance_pct:
            if abs(dist_pct) < abs(min_dist_pct):
                min_dist_pct = dist_pct
                closest_support = name

    if closest_support:
        return True, f"{closest_support} yakinlarinda (Mesafe: %{min_dist_pct:.2f})"
    return False, "Destek bolgesine yakin degil"

def _check_session_aware_volume(df_4h, current_volume: float, current_hour: int) -> bool:
    session_bars = df_4h[df_4h.index.hour == current_hour]
    if len(session_bars) >= 2:
        avg_vol = float(session_bars.iloc[:-1]['volume'].mean())
    else:
        avg_vol = float(df_4h['volume'].rolling(config.BIST_CHART_RVOL_LOOKBACK).mean().iloc[-1])
        
    if avg_vol <= 0:
        avg_vol = 1.0
        
    return current_volume >= (avg_vol * config.BIST12_VOLUME_MULT)

def _check_rectangle_breakout(df_4h, close_arr, high_arr, low_arr, volume_arr, current_price):
    box_len = 20
    if len(close_arr) >= box_len:
        box_highs = high_arr[-box_len:-1]
        box_lows = low_arr[-box_len:-1]
        max_high = float(np.max(box_highs))
        min_low = float(np.min(box_lows))
        box_height_pct = (max_high - min_low) / min_low * 100.0
        
        if box_height_pct <= config.BIST12_RECTANGLE_HEIGHT_PCT:
            upper_touches = np.sum((max_high - box_highs) / max_high * 100.0 <= 1.0)
            lower_touches = np.sum((box_lows - min_low) / min_low * 100.0 <= 1.0)
            
            if upper_touches >= 2 and lower_touches >= 2:
                if current_price > max_high:
                    current_hour = df_4h.index[-1].hour
                    if _check_session_aware_volume(df_4h, volume_arr[-1], current_hour):
                        return "Dikdörtgen (Darvas Box) Yukarı Kırılımı", {
                            "pattern": "Rectangle Breakout",
                            "signal": "AL",
                            "box_high": max_high,
                            "box_low": min_low,
                            "sl": min_low
                        }
    return None, {}

def _check_tobo(df_4h, close_arr, volume_arr, rsi_arr, peaks, valleys, current_price, dynamic_obo_tol):
    if len(valleys) >= 3 and len(peaks) >= 2:
        v1, v2, v3 = valleys[-3], valleys[-2], valleys[-1]
        p1_candidates = peaks[(peaks > v1) & (peaks < v2)]
        p2_candidates = peaks[(peaks > v2) & (peaks < v3)]
        
        if len(p1_candidates) > 0 and len(p2_candidates) > 0:
            idx_v1, idx_v2, idx_v3 = v1, v2, v3
            idx_p1, idx_p2 = p1_candidates[-1], p2_candidates[-1]
            
            val_v1, val_v2, val_v3 = close_arr[idx_v1], close_arr[idx_v2], close_arr[idx_v3]
            val_p1, val_p2 = close_arr[idx_p1], close_arr[idx_p2]
            
            if val_v2 < val_v1 and val_v2 < val_v3:
                shoulder_diff = abs(val_v1 - val_v3) / max(val_v1, val_v3)
                neck_diff = abs(val_p1 - val_p2) / max(val_p1, val_p2)
                
                if shoulder_diff <= dynamic_obo_tol and neck_diff <= (config.BIST12_NECK_TOLERANCE_PCT / 100.0):
                    m = (val_p2 - val_p1) / (idx_p2 - idx_p1)
                    neck_price = val_p2 + m * (len(close_arr) - 1 - idx_p2)
                    
                    if current_price > neck_price:
                        rsi_divergence = False
                        if rsi_arr[idx_v3] > rsi_arr[idx_v2] or rsi_arr[idx_v2] > rsi_arr[idx_v1]:
                            rsi_divergence = True
                            
                        current_hour = df_4h.index[-1].hour
                        vol_ok = _check_session_aware_volume(df_4h, volume_arr[-1], current_hour)
                        
                        if (not config.BIST12_RSI_DIVERGENCE_REQUIRED or rsi_divergence) and vol_ok:
                            return "Ters Omuz Baş Omuz (TOBO) Kırılımı", {
                                "pattern": "TOBO",
                                "signal": "AL",
                                "sl": val_v3 * (1.0 - config.PATTERN_SL_BUFFER),
                                "details": f"Sol: {val_v1:.2f}, Baş: {val_v2:.2f}, Sağ: {val_v3:.2f}"
                            }
    return None, {}

def _check_double_bottom(df_4h, close_arr, volume_arr, rsi_arr, peaks, valleys, current_price, dynamic_double_tol):
    if len(valleys) >= 2 and len(peaks) >= 1:
        v1, v2 = valleys[-2], valleys[-1]
        p_candidates = peaks[(peaks > v1) & (peaks < v2)]
        
        if len(p_candidates) > 0:
            idx_v1, idx_v2 = v1, v2
            idx_p = p_candidates[-1]
            
            val_v1, val_v2 = close_arr[idx_v1], close_arr[idx_v2]
            val_p = close_arr[idx_p]
            
            if val_p > max(val_v1, val_v2):
                dip_diff = abs(val_v1 - val_v2) / max(val_v1, val_v2)
                if dip_diff <= dynamic_double_tol:
                    if current_price > val_p:
                        rsi_divergence = False
                        if rsi_arr[idx_v2] > rsi_arr[idx_v1]:
                            rsi_divergence = True
                            
                        current_hour = df_4h.index[-1].hour
                        vol_ok = _check_session_aware_volume(df_4h, volume_arr[-1], current_hour)

                        if (not config.BIST12_RSI_DIVERGENCE_REQUIRED or rsi_divergence) and vol_ok:
                            sl_level = min(val_v1, val_v2) * (1.0 - config.PATTERN_SL_BUFFER)
                            return "İkili Dip Kırılımı", {
                                "pattern": "Double Bottom",
                                "signal": "AL",
                                "sl": sl_level,
                                "details": f"Dip 1: {val_v1:.2f}, Dip 2: {val_v2:.2f}, Ara Tepe: {val_p:.2f}"
                            }
    return None, {}

def _check_bull_flag(df_4h, close_arr, high_arr, low_arr, volume_arr, current_price):
    consolidation_len = config.BIST12_FLAG_CONSOLIDATION_BARS
    if len(close_arr) >= (15 + consolidation_len):
        past_section = close_arr[-(15 + consolidation_len):-consolidation_len]
        pole_low = float(np.min(past_section))
        pole_high = float(np.max(past_section))
        pole_pct = (pole_high - pole_low) / pole_low * 100.0
        
        if pole_pct >= config.BIST12_FLAG_POLE_MIN_PCT:
            flag_section_close = close_arr[-consolidation_len:]
            flag_section_volume = volume_arr[-consolidation_len:]
            flag_max_high = float(np.max(high_arr[-consolidation_len:]))
            flag_min_low = float(np.min(low_arr[-consolidation_len:]))
            
            if flag_max_high <= pole_high and flag_min_low >= pole_low:
                recent_avg_vol = float(np.mean(volume_arr[-(consolidation_len+10):-consolidation_len]))
                flag_avg_vol = float(np.mean(flag_section_volume))
                
                if flag_avg_vol < recent_avg_vol * 1.1:
                    flag_resistance = float(np.max(flag_section_close[:-1]))
                    if current_price > flag_resistance:
                        current_hour = df_4h.index[-1].hour
                        if _check_session_aware_volume(df_4h, volume_arr[-1], current_hour):
                            return "Boğa Bayrağı Kırılımı", {
                                "pattern": "Bull Flag",
                                "signal": "AL",
                                "sl": flag_min_low * (1.0 - config.PATTERN_SL_BUFFER),
                                "details": f"Bayrak Direği: %{pole_pct:.1f}, Dinlenme Hacmi: {flag_avg_vol:.0f}"
                            }
    return None, {}

def _check_falling_wedge(df_4h, close_arr, high_arr, low_arr, volume_arr, peaks, valleys, current_price):
    if len(valleys) >= 3 and len(peaks) >= 3:
        p_idx = peaks[-3:]
        v_idx = valleys[-3:]
        
        slope_p, intercept_p = np.polyfit(p_idx, close_arr[p_idx], 1)
        slope_v, intercept_v = np.polyfit(v_idx, close_arr[v_idx], 1)
        norm_slope_p = slope_p / current_price * 100.0
        norm_slope_v = slope_v / current_price * 100.0
        
        if norm_slope_p < config.WEDGE_SLOPE_THRESHOLD and norm_slope_v < config.WEDGE_SLOPE_THRESHOLD:
            if norm_slope_p < norm_slope_v - config.BIST12_WEDGE_CONVERGENCE_FACTOR:
                resistance_at_last = slope_p * (len(close_arr) - 1) + intercept_p
                last_peak_val = close_arr[p_idx[-1]]
                choch_ok = current_price > last_peak_val
                fvg_ok = len(low_arr) >= 3 and (low_arr[-1] > high_arr[-3])
                
                support_level = min(low_arr[v_idx[-3]], low_arr[v_idx[-2]])
                sweep_ok = False
                for idx in range(v_idx[-2], len(close_arr)):
                    if low_arr[idx] < support_level and close_arr[idx] >= support_level:
                        sweep_ok = True
                        break
                
                smc_pass = (fvg_ok and sweep_ok) if config.BIST12_SMC_STRICT_MODE else True
                
                if choch_ok and smc_pass:
                    if current_price > resistance_at_last:
                        current_hour = df_4h.index[-1].hour
                        if _check_session_aware_volume(df_4h, volume_arr[-1], current_hour):
                            return "Alçalan Takoz Yukarı Kırılımı", {
                                "pattern": "Falling Wedge",
                                "signal": "AL",
                                "sl": close_arr[v_idx[-1]] * (1.0 - config.PATTERN_SL_BUFFER),
                                "details": f"Direnç Eğimi: %{norm_slope_p:.2f}, Destek Eğimi: %{norm_slope_v:.2f}, SMC Strict: {config.BIST12_SMC_STRICT_MODE}"
                            }
    return None, {}

def _check_ascending_triangle(df_4h, close_arr, high_arr, low_arr, volume_arr, peaks, valleys, current_price):
    if len(valleys) >= 3 and len(peaks) >= 3:
        p_idx = peaks[-3:]
        v_idx = valleys[-3:]
        
        slope_p, intercept_p = np.polyfit(p_idx, close_arr[p_idx], 1)
        slope_v, intercept_v = np.polyfit(v_idx, close_arr[v_idx], 1)
        norm_slope_p = slope_p / current_price * 100.0
        norm_slope_v = slope_v / current_price * 100.0
        
        if abs(norm_slope_p) <= config.BIST12_TRIANGLE_SLOPE_TOLERANCE:
            if norm_slope_v > config.BIST12_TRIANGLE_SLOPE_TOLERANCE:
                max_p = np.max(close_arr[p_idx])
                min_p = np.min(close_arr[p_idx])
                p_var = (max_p - min_p) / min_p * 100.0
                
                if p_var <= config.TRIANGLE_HEIGHT_VAR_LIMIT:
                    choch_ok = current_price > max_p
                    fvg_ok = len(low_arr) >= 3 and (low_arr[-1] > high_arr[-3])
                    
                    support_level = min(low_arr[v_idx[-3]], low_arr[v_idx[-2]])
                    sweep_ok = False
                    for idx in range(v_idx[-2], len(close_arr)):
                        if low_arr[idx] < support_level and close_arr[idx] >= support_level:
                            sweep_ok = True
                            break
                    
                    smc_pass = (fvg_ok and sweep_ok) if config.BIST12_SMC_STRICT_MODE else True
                    
                    if choch_ok and smc_pass:
                        current_hour = df_4h.index[-1].hour
                        if _check_session_aware_volume(df_4h, volume_arr[-1], current_hour):
                            return "Yükselen Üçgen Yukarı Kırılımı", {
                                "pattern": "Ascending Triangle",
                                "signal": "AL",
                                "sl": close_arr[v_idx[-1]] * (1.0 - config.PATTERN_SL_BUFFER),
                                "details": f"Direnç Varyansı: %{p_var:.2f}, Destek Eğimi: %{norm_slope_v:.2f}, SMC Strict: {config.BIST12_SMC_STRICT_MODE}"
                            }
    return None, {}

def _check_diamond_bottom(df_4h, close_arr, volume_arr, rsi_arr, peaks, valleys, current_price):
    if len(valleys) >= 3 and len(peaks) >= 2:
        v1, v2, v3 = valleys[-3], valleys[-2], valleys[-1]
        p_candidates_left = peaks[(peaks > v1) & (peaks < v2)]
        p_candidates_right = peaks[(peaks > v2) & (peaks < v3)]
        
        if len(p_candidates_left) > 0 and len(p_candidates_right) > 0:
            p1 = p_candidates_left[-1]
            p2 = p_candidates_right[-1]
            val_v1, val_v2, val_v3 = close_arr[v1], close_arr[v2], close_arr[v3]
            val_p1, val_p2 = close_arr[p1], close_arr[p2]
            
            if val_v2 < val_v1 and val_v2 < val_v3:
                m_desc = (val_v3 - val_p2) / max(1, (v3 - p2))
                resistance_at_last = val_p2 + m_desc * (len(close_arr) - 1 - p2)
                
                if val_v3 > val_v2 and val_p2 < val_p1 * config.DOUBLE_TOP_HIGH_TOLERANCE:
                    if current_price > resistance_at_last:
                        rsi_divergence = False
                        if rsi_arr[v3] > rsi_arr[v2] or rsi_arr[v2] > rsi_arr[v1]:
                            rsi_divergence = True
                            
                        current_hour = df_4h.index[-1].hour
                        vol_ok = _check_session_aware_volume(df_4h, volume_arr[-1], current_hour)
                        
                        if (not config.BIST12_RSI_DIVERGENCE_REQUIRED or rsi_divergence) and vol_ok:
                            return "Elmas Dip Yukarı Kırılımı", {
                                "pattern": "Diamond Bottom",
                                "signal": "AL",
                                "sl": val_v2 * (1.0 - config.PATTERN_SL_BUFFER),
                                "details": f"Orta Dip: {val_v2:.2f}, Kırılım Direnci: {resistance_at_last:.2f}"
                            }
    return None, {}

def detect_chart_patterns(df_4h) -> tuple[Optional[str], dict]:
    """
    Taramada son tamamlanan barda oluşmuş/kırılmış boğa (bullish) grafik formasyonlarını tespit eder.
    """
    from scipy.signal import find_peaks
    from .harmonics import _check_harmonic_patterns
    
    if df_4h is None or len(df_4h) < 30:
        return None, {}
        
    close_arr = df_4h['close'].values.astype(np.float64)
    high_arr = df_4h['high'].values.astype(np.float64)
    low_arr = df_4h['low'].values.astype(np.float64)
    volume_arr = df_4h['volume'].values.astype(np.float64)
    current_price = close_arr[-1]
    
    if 'RSI_14' not in df_4h.columns:
        df_4h.ta.rsi(length=14, append=True)
    rsi_arr = df_4h['RSI_14'].values.astype(np.float64)
    
    atr_series = df_4h.ta.atr(length=14) if 'ATR_14' not in df_4h.columns else df_4h['ATR_14']
    atr = float(atr_series.iloc[-1]) if atr_series is not None and not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (high_arr[-1] - low_arr[-1])
    if atr <= 0:
        atr = 1e-8
        
    prominence = atr * config.BIST12_PROMINENCE_ATR_MULT
    dynamic_double_tol = max(config.BIST12_DOUBLE_BASE_TOLERANCE_PCT, (atr / current_price) * 100.0 * config.BIST12_VOLATILITY_TOLERANCE_MULT) / 100.0
    dynamic_obo_tol = max(config.BIST12_OBO_BASE_TOLERANCE_PCT, (atr / current_price) * 100.0 * config.BIST12_VOLATILITY_TOLERANCE_MULT) / 100.0
    
    name, details = _check_rectangle_breakout(df_4h, close_arr, high_arr, low_arr, volume_arr, current_price)
    if name:
        return name, details
        
    peaks, _ = find_peaks(close_arr, prominence=prominence, distance=4)
    valleys, _ = find_peaks(-close_arr, prominence=prominence, distance=4)
    
    name, details = _check_tobo(df_4h, close_arr, volume_arr, rsi_arr, peaks, valleys, current_price, dynamic_obo_tol)
    if name:
        return name, details
        
    name, details = _check_double_bottom(df_4h, close_arr, volume_arr, rsi_arr, peaks, valleys, current_price, dynamic_double_tol)
    if name:
        return name, details
        
    name, details = _check_bull_flag(df_4h, close_arr, high_arr, low_arr, volume_arr, current_price)
    if name:
        return name, details
        
    name, details = _check_falling_wedge(df_4h, close_arr, high_arr, low_arr, volume_arr, peaks, valleys, current_price)
    if name:
        return name, details
        
    name, details = _check_ascending_triangle(df_4h, close_arr, high_arr, low_arr, volume_arr, peaks, valleys, current_price)
    if name:
        return name, details
        
    name, details = _check_diamond_bottom(df_4h, close_arr, volume_arr, rsi_arr, peaks, valleys, current_price)
    if name:
        return name, details
        
    name, details = _check_harmonic_patterns(df_4h, close_arr, peaks, valleys, current_price)
    if name:
        return name, details
        
    return None, {}
