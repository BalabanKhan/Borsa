"""
indicators.py — Teknik Gösterge Katmanı
Tüm indikatör hesaplama, swing point tespiti ve strateji-öncesi analiz fonksiyonları.
Public API — leading underscore olmadan.
"""
import numpy as np
import pandas as pd
import config
import pandas_ta as ta
import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from config import (
    SWING_MIN_AMPLITUDE_PCT, DIVERGENCE_MAX_AGE_CANDLES, SQUEEZE_CONFIRM_CANDLES,
    ENGULFING_MIN_BODY_RATIO, CMF_PERIOD, CMF_WASH_TRADE_THRESHOLD,
    OTE_MIN_WAVE_PCT,
)

# ==========================================
# 🧠 SMART INDICATOR WRAPPER (TA-LIB / PANDAS-TA)
# ==========================================
try:
    import talib
    TA_LIB_AVAILABLE = True
    logging.info("TA-Lib tespit edildi, hizlandirilmis motor kullanilacak.")
except ImportError:
    TA_LIB_AVAILABLE = False
    logging.info("TA-Lib bulunamadi, Pandas-TA fallback modunda çalisiliyor.")

def inject_smart_indicators(df):
    """
    Kritik indikatörleri TA-Lib oncelikli, Pandas-TA fallback'li olarak df uzerine ekler.
    Tüm stratejilerin basinda cagirilir.
    """
    df_copy = df.copy()
    
    # EMA
    if TA_LIB_AVAILABLE:
        df_copy[f'EMA_{config.IND_EMA_FAST}'] = talib.EMA(df_copy['close'].values, timeperiod=config.IND_EMA_FAST)
        df_copy[f'EMA_{config.IND_EMA_MID}'] = talib.EMA(df_copy['close'].values, timeperiod=config.IND_EMA_MID)
        df_copy[f'EMA_{config.IND_EMA_SLOW}'] = talib.EMA(df_copy['close'].values, timeperiod=config.IND_EMA_SLOW)
        df_copy[f'EMA_{config.IND_EMA_21}'] = talib.EMA(df_copy['close'].values, timeperiod=config.IND_EMA_21)
        df_copy[f'EMA_{config.IND_EMA_55}'] = talib.EMA(df_copy['close'].values, timeperiod=config.IND_EMA_55)
        df_copy[f'EMA_20'] = talib.EMA(df_copy['close'].values, timeperiod=20)
    else:
        df_copy.ta.ema(length=config.IND_EMA_FAST, append=True)
        df_copy.ta.ema(length=config.IND_EMA_MID, append=True)
        df_copy.ta.ema(length=config.IND_EMA_SLOW, append=True)
        df_copy.ta.ema(length=config.IND_EMA_21, append=True)
        df_copy.ta.ema(length=config.IND_EMA_55, append=True)
        df_copy.ta.ema(length=20, append=True)
        
    # SMA
    if TA_LIB_AVAILABLE:
        df_copy[f'SMA_{config.IND_SMA_SLOW}'] = talib.SMA(df_copy['close'].values, timeperiod=config.IND_SMA_SLOW)
        df_copy[f'SMA_{config.IND_SMA_TREND}'] = talib.SMA(df_copy['close'].values, timeperiod=config.IND_SMA_TREND)
        df_copy[f'SMA_200'] = talib.SMA(df_copy['close'].values, timeperiod=200)
    else:
        df_copy.ta.sma(length=config.IND_SMA_SLOW, append=True)
        df_copy.ta.sma(length=config.IND_SMA_TREND, append=True)
        df_copy.ta.sma(length=200, append=True)
        
    # RSI
    if TA_LIB_AVAILABLE:
        df_copy[f'RSI_{config.IND_RSI_LENGTH}'] = talib.RSI(df_copy['close'].values, timeperiod=config.IND_RSI_LENGTH)
    else:
        df_copy.ta.rsi(length=config.IND_RSI_LENGTH, append=True)

    # ADX
    if TA_LIB_AVAILABLE:
        df_copy[f'ADX_{config.IND_ADX_LENGTH}'] = talib.ADX(df_copy['high'].values, df_copy['low'].values, df_copy['close'].values, timeperiod=config.IND_ADX_LENGTH)
    else:
        df_copy.ta.adx(length=config.IND_ADX_LENGTH, append=True)
        
    # ATR
    if TA_LIB_AVAILABLE:
        df_copy[f'ATRr_{config.IND_ATR_LENGTH}'] = talib.ATR(df_copy['high'].values, df_copy['low'].values, df_copy['close'].values, timeperiod=config.IND_ATR_LENGTH)
    else:
        df_copy.ta.atr(length=config.IND_ATR_LENGTH, append=True)
        
    # MACD
    if TA_LIB_AVAILABLE:
        macd, macdsignal, macdhist = talib.MACD(df_copy['close'].values, fastperiod=12, slowperiod=26, signalperiod=9)
        df_copy['MACD_12_26_9'] = macd
        df_copy['MACDh_12_26_9'] = macdhist
        df_copy['MACDs_12_26_9'] = macdsignal
    else:
        df_copy.ta.macd(fast=12, slow=26, signal=9, append=True)
        
    # BBANDS
    if TA_LIB_AVAILABLE:
        upper, middle, lower = talib.BBANDS(df_copy['close'].values, timeperiod=config.IND_BBANDS_LENGTH, nbdevup=config.IND_BBANDS_STD, nbdevdn=config.IND_BBANDS_STD, matype=0)
        df_copy[f'BBL_{config.IND_BBANDS_LENGTH}_{config.IND_BBANDS_STD}'] = lower
        df_copy[f'BBM_{config.IND_BBANDS_LENGTH}_{config.IND_BBANDS_STD}'] = middle
        df_copy[f'BBU_{config.IND_BBANDS_LENGTH}_{config.IND_BBANDS_STD}'] = upper
    else:
        df_copy.ta.bbands(length=config.IND_BBANDS_LENGTH, std=config.IND_BBANDS_STD, append=True)
        
    # Keltner Channels
    df_copy.ta.kc(length=config.IND_BBANDS_LENGTH, scalar=1.5, append=True) # TA-Lib has no native KC, use pandas-ta
    
    return df_copy



# ════════════════════════════════════════
# 🛡️ AM SERİSİ: Anti-Manipülasyon Kalkanları
# ════════════════════════════════════════

def check_bullish_engulfing_momentum(df, lookback=2):
    """AM-01: Ölü Kedi Giyotini — momentum shift doğrulayıcı.
    Son yeşil mumun gövdesi, bir önceki kırmızı mumun gövdesinin
    en az %50'sini (ENGULFING_MIN_BODY_RATIO) yutmuş olmalı.
    Returns: True (gerçek momentum), False (sahte hareket)
    """
    if len(df) < lookback + 1:
        return False

    current = df.iloc[-1]
    prev = df.iloc[-2]

    # Mevcut mum yeşil (boğa) olmalı
    if current['close'] <= current['open']:
        return False

    # Önceki mum kırmızı (ayı) olmalı
    if prev['close'] >= prev['open']:
        return True  # Zaten 2 yeşil üst üste → devam sinyali, engulfing gereksiz

    current_body = abs(current['close'] - current['open'])
    prev_body = abs(prev['open'] - prev['close'])

    if prev_body <= 0:
        return True  # Doji → engulfing aranmaz

    ratio = current_body / prev_body
    return ratio >= ENGULFING_MIN_BODY_RATIO


def calculate_cmf(df, period=None):
    """AM-02: Chaikin Money Flow (CMF) hesapla — vektörel Pandas.
    CMF = SUM(MFV * Volume, period) / SUM(Volume, period)
    MFV = ((Close - Low) - (High - Close)) / (High - Low)
    Returns: float (son CMF değeri) veya None
    """
    if period is None:
        period = CMF_PERIOD
    if len(df) < period:
        return None

    high = df['high']
    low = df['low']
    close = df['close']
    volume = df['volume']

    # Money Flow Multiplier (MFM)
    hl_range = high - low
    # Sıfıra bölünme koruması
    hl_range = hl_range.replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / hl_range
    mfm = mfm.fillna(0)

    # Money Flow Volume (MFV)
    mfv = mfm * volume

    # CMF = Rolling sum(MFV) / Rolling sum(Volume)
    cmf_num = mfv.rolling(period).sum()
    cmf_den = volume.rolling(period).sum()

    # Son değer
    num = cmf_num.iloc[-1]
    den = cmf_den.iloc[-1]
    if pd.isna(num) or pd.isna(den) or den == 0:
        return None
    return float(num / den)


def is_cmf_wash_trade(df, period=None):
    """AM-02: OBV pozitif ama CMF negatifse → Wash Trade tespiti.
    Hacim artıyor gibi görünüyor ama para aslında ÇIKIYOR.
    Returns: True (kurumsal boşaltma), False (temiz)
    """
    cmf = calculate_cmf(df, period)
    if cmf is None:
        return False  # Veri yoksa güvenli tarafta kal
    return cmf < CMF_WASH_TRADE_THRESHOLD


def sniper_calculate_ote_body(df, sweep_idx, msb_idx, direction="long"):
    """AM-05: Gövde-bazlı OTE — fitil uçları yerine mum gövdeleri kullanır.
    Devasa volatilitelerde fitillerin yarattığı sahte OTE bölgesini engeller.
    Returns: (ote_top, ote_bottom) veya (0, 0)
    """
    if sweep_idx is None or msb_idx is None:
        return 0, 0
    if sweep_idx >= len(df) or msb_idx >= len(df):
        return 0, 0

    sweep_candle = df.iloc[sweep_idx]
    msb_candle = df.iloc[msb_idx]

    if direction == "long":
        # Sweep noktası: gövdenin altı (close veya open hangisi düşükse)
        sweep_body = min(sweep_candle['close'], sweep_candle['open'])
        # MSB noktası: gövdenin üstü
        msb_body = max(msb_candle['close'], msb_candle['open'])
    else:
        # SHORT: tam tersi
        sweep_body = max(sweep_candle['close'], sweep_candle['open'])
        msb_body = min(msb_candle['close'], msb_candle['open'])

    fib_range = abs(msb_body - sweep_body)
    if fib_range < 1e-10:
        return 0, 0

    # AM-05: Minimum dalga amplitüdü kontrolü
    mid_price = (sweep_body + msb_body) / 2
    wave_pct = (fib_range / mid_price) * 100
    if wave_pct < OTE_MIN_WAVE_PCT:
        logging.debug(f"[AM-05] Dalga çok küçük: %{wave_pct:.2f} < %{OTE_MIN_WAVE_PCT}")
        return 0, 0

    if sweep_body < msb_body:  # LONG
        ote_top = msb_body - (fib_range * 0.618)
        ote_bottom = msb_body - (fib_range * 0.786)
    else:  # SHORT
        ote_bottom = msb_body + (fib_range * 0.618)
        ote_top = msb_body + (fib_range * 0.786)

    return ote_top, ote_bottom


# ════════════════════════════════════════
# SNIPER Strateji Yardımcıları (SMC)
# ════════════════════════════════════════

def sniper_get_htf_bias(df):
    """1 Günlük EMA20 vs EMA50 ile trend yönü belirle.
    Returns: 1 (Bullish/AL), -1 (Bearish/SAT), 0 (Nötr)
    NOT: DataFrame mutasyonunu önlemek için .copy() ile çalışır.
    """
    if len(df) < 50:
        return 0
    df = df.copy()
    if f'EMA_{config.IND_EMA_MID}' not in df.columns:
        df.ta.ema(length=config.IND_EMA_MID, append=True)
    if f'EMA_{config.IND_EMA_SLOW}' not in df.columns:
        df.ta.ema(length=config.IND_EMA_SLOW, append=True)

    ema20 = df[f'EMA_{config.IND_EMA_MID}'].iloc[-1]
    ema50 = df[f'EMA_{config.IND_EMA_SLOW}'].iloc[-1]
    close = df['close'].iloc[-1]

    if pd.isna(ema20) or pd.isna(ema50):
        return 0
    if ema20 > ema50 and close > ema20:
        return 1
    elif ema20 < ema50 and close < ema20:
        return -1
    return 0


def sniper_find_swing_points(df, point_type="low", neighbors=3, min_amplitude_pct=None):
    """Swing high veya swing low noktaları tespit et.
    NumPy vektörel hesaplama ile O(N) performans.
    RED-03: min_amplitude_pct filtresi — gürültü swing'leri eler.
    Returns: [(index, price), ...] listesi
    """
    if min_amplitude_pct is None:
        min_amplitude_pct = SWING_MIN_AMPLITUDE_PCT
    col = 'low' if point_type == "low" else 'high'
    values = df[col].values
    n = len(values)
    swings = []

    if n < 2 * neighbors + 1:
        return swings

    for i in range(neighbors, n - neighbors):
        val = values[i]
        if point_type == "low":
            is_swing = all(val <= values[i - j] for j in range(1, neighbors + 1))
            is_swing = is_swing and all(val < values[i + j] for j in range(1, neighbors + 1))
        else:
            is_swing = all(val >= values[i - j] for j in range(1, neighbors + 1))
            is_swing = is_swing and all(val > values[i + j] for j in range(1, neighbors + 1))
        if is_swing:
            # RED-03: Amplitude filtresi — gerçek swing mi yoksa gürültü mü?
            window = values[max(0, i - neighbors):i + neighbors + 1]
            local_range = window.max() - window.min()
            if val > 0:
                amplitude_pct = (local_range / val) * 100
                if amplitude_pct >= min_amplitude_pct:
                    swings.append((i, val))
            else:
                swings.append((i, val))
    return swings


def sniper_detect_sweep(df, swing_points, point_type="low", lookback=10):
    """Son lookback mum içinde eski bir swing noktasının ihlal edilip geri çekilmesini tespit et.
    LONG (low): Fitil swing low altına sardı ama gövde yukarıda kapandı.
    SHORT (high): Fitil swing high üstüne sardı ama gövde aşağıda kapandı.
    """
    if not swing_points:
        return False, None

    check_start = max(0, len(df) - lookback)

    for i in range(check_start, len(df)):
        row = df.iloc[i]
        for sw_idx, sw_price in swing_points:
            if sw_idx >= i:
                continue

            if point_type == "low":
                if row['low'] < sw_price and row['close'] > sw_price:
                    return True, sw_price
            else:
                if row['high'] > sw_price and row['close'] < sw_price:
                    return True, sw_price

    return False, None


def sniper_detect_msb(df, swing_points, point_type="high"):
    """Market Structure Break tespiti.
    LONG (high): Son kapanış en son swing high'ın üzerinde mi?
    SHORT (low): Son kapanış en son swing low'un altında mı?
    """
    if not swing_points:
        return False, None, None

    last_sw_idx, last_sw_price = swing_points[-1]
    current_close = df['close'].iloc[-1]

    if point_type == "high" and current_close > last_sw_price:
        return True, last_sw_price, last_sw_idx
    elif point_type == "low" and current_close < last_sw_price:
        return True, last_sw_price, last_sw_idx

    return False, None, None


def sniper_calculate_ote(sweep_price, msb_price):
    """Fibonacci 0.618 - 0.786 OTE (Optimal Trade Entry) bölgesini hesapla."""
    fib_range = abs(msb_price - sweep_price)
    if math.isclose(fib_range, 0.0, abs_tol=1e-10):
        return 0, 0

    if sweep_price < msb_price:
        ote_top = msb_price - (fib_range * 0.618)
        ote_bottom = msb_price - (fib_range * 0.786)
    else:
        ote_bottom = msb_price + (fib_range * 0.618)
        ote_top = msb_price + (fib_range * 0.786)
    return ote_top, ote_bottom


def sniper_detect_fvg(df, ote_top, ote_bottom, lookback=15, direction="bullish"):
    """OTE bölgesi içinde doldurulmamış FVG (Fair Value Gap) tespit et."""
    search_start = max(1, len(df) - lookback)

    for i in range(search_start, len(df) - 1):
        if i < 1:
            continue

        if direction == "bullish":
            candle1_high = df['high'].iloc[i - 1]
            candle3_low = df['low'].iloc[i + 1]
            if candle3_low > candle1_high:
                gap_bottom = candle1_high
                gap_top = candle3_low
                if gap_bottom <= ote_top and gap_top >= ote_bottom:
                    filled = any(df['low'].iloc[j] <= gap_top for j in range(i + 2, len(df)))
                    if not filled:
                        return True, gap_bottom, gap_top
        else:
            candle1_low = df['low'].iloc[i - 1]
            candle3_high = df['high'].iloc[i + 1]
            if candle3_high < candle1_low:
                gap_top = candle1_low
                gap_bottom = candle3_high
                if gap_bottom <= ote_top and gap_top >= ote_bottom:
                    filled = any(df['high'].iloc[j] >= gap_bottom for j in range(i + 2, len(df)))
                    if not filled:
                        return True, gap_bottom, gap_top

    return False, None, None


# ════════════════════════════════════════
# 🐻 AYI AVCISI (Bear Hunter) Göstergeleri
# ════════════════════════════════════════

def detect_sfp(df_4h, neighbors=3):
    """Swing Failure Pattern (Zirve Tuzağı) tespit eder.
    Returns: (sfp_found, swing_high_price, sfp_candle) veya (False, None, None)
    """
    if df_4h is None or len(df_4h) < 20:
        return False, None, None

    highs = df_4h['high'].values
    n = len(highs)
    swing_highs = []

    for i in range(neighbors, n - neighbors - 1):
        is_swing = True
        for j in range(1, neighbors + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_highs.append((i, highs[i]))

    if not swing_highs:
        return False, None, None

    last_swing_idx, last_swing_high = swing_highs[-1]
    last_candle = df_4h.iloc[-1]

    if last_candle['high'] > last_swing_high:
        # SFP_BODY_CLOSE_INSIDE_REQUIRED: Mum gövdesinin eski tepe seviyesinin altında (içeride) kapanması şartı
        body_close_ok = not config.SFP_BODY_CLOSE_INSIDE_REQUIRED or (last_candle['close'] < last_swing_high)
        if body_close_ok and last_candle['close'] < last_candle['open']:
            body = abs(last_candle['close'] - last_candle['open'])
            upper_wick = last_candle['high'] - max(last_candle['close'], last_candle['open'])
            if body > 0 and upper_wick > (2 * body):
                # SFP Hacim Teyidi Kontrolü
                # SFP barındaki hacmin, son 20 mumun ortalama hacminin config.SFP_VOLUME_CONFIRMATION_MULT katı olmasını şart koşar.
                if config.SFP_VOLUME_CONFIRMATION_MULT > 0:
                    vol_sma = df_4h['volume'].rolling(20).mean().iloc[-1]
                    if not pd.isna(vol_sma) and last_candle['volume'] < vol_sma * config.SFP_VOLUME_CONFIRMATION_MULT:
                        return False, None, None

                # SFP MFE / Zaman Filtresi: Fiyatın mum kapanışında hızlıca dönmüş olması (mumun alt %40'lık kısmında kapanması)
                if getattr(config, 'SFP_MFE_TIME_FILTER_REQUIRED', False):
                    candle_range = last_candle['high'] - last_candle['low']
                    if candle_range > 0:
                        close_percentile = (last_candle['close'] - last_candle['low']) / candle_range
                        if close_percentile > 0.40:
                            return False, None, None

                return True, last_swing_high, last_candle

    return False, None, None


def detect_premium_rejection(df_4h, df_1d):
    """Pahalı Bölge Reddi (SMC Premium Short) tespit eder.
    Fibonacci 0.618-0.786 bölgesinde bearish red arar.
    Returns: (found, fib_618, fib_786, entry_candle) veya (False, None, None, None)
    """
    if df_4h is None or len(df_4h) < 30 or df_1d is None or len(df_1d) < 20:
        return False, None, None, None

    # Pandas Mutability koruması: kaynak DataFrame'leri kirletme
    df_1d = df_1d.copy()
    df_4h = df_4h.copy()

    if f'EMA_{config.IND_EMA_MID}' not in df_1d.columns:
        df_1d.ta.ema(length=config.IND_EMA_MID, append=True)
    if f'EMA_{config.IND_EMA_SLOW}' not in df_1d.columns:
        df_1d.ta.ema(length=config.IND_EMA_SLOW, append=True)
    last_1d = df_1d.iloc[-1]
    ema20_1d = last_1d.get(f'EMA_{config.IND_EMA_MID}')
    ema50_1d = last_1d.get(f'EMA_{config.IND_EMA_SLOW}')

    if ema20_1d is None or ema50_1d is None or pd.isna(ema20_1d) or pd.isna(ema50_1d):
        return False, None, None, None
    if ema20_1d >= ema50_1d:
        return False, None, None, None

    recent = df_4h.tail(30)
    swing_high_val = float(recent['high'].max())
    swing_high_idx = recent['high'].idxmax()
    after_high = recent.loc[swing_high_idx:]
    if len(after_high) < 5:
        return False, None, None, None

    # RED-10: Tepe çok eski mi? İlk 10 mumda ise yapı "taze" değil
    high_position = list(recent.index).index(swing_high_idx)
    if high_position < 10:
        return False, None, None, None

    swing_low_val = float(after_high['low'].min())

    leg_range = swing_high_val - swing_low_val
    if leg_range <= 0:
        return False, None, None, None

    # RED-10: Fibonacci aralığı çok geniş mi? (aşırı volatilite filtresi)
    fib_width_pct = (leg_range / swing_high_val) * 100
    if fib_width_pct > 15:
        return False, None, None, None

    fib_618 = swing_low_val + 0.618 * leg_range
    fib_786 = swing_low_val + 0.786 * leg_range

    last_4h = df_4h.iloc[-1]
    current_close = float(last_4h['close'])

    if fib_618 <= current_close <= fib_786:
        is_bearish_engulfing = (
            last_4h['close'] < last_4h['open'] and
            len(df_4h) >= 2 and
            last_4h['open'] > df_4h.iloc[-2]['close'] and
            last_4h['close'] < df_4h.iloc[-2]['open']
        )

        df_4h.ta.ema(length=config.IND_EMA_MID, append=True)
        ema20_4h = last_4h.get(f'EMA_{config.IND_EMA_MID}')
        ema_rejection = False
        if ema20_4h is not None and not pd.isna(ema20_4h):
            ema_rejection = (last_4h['high'] >= ema20_4h and last_4h['close'] < ema20_4h
                             and last_4h['close'] < last_4h['open'])

        if is_bearish_engulfing or ema_rejection:
            return True, fib_618, fib_786, last_4h

    return False, None, None, None


def detect_bearish_divergence(df_4h, neighbors=3):
    """Negatif Uyumsuzluk (Yorgunluk Tepesi) tespit eder.
    Fiyat Higher High + RSI Lower High + Hacim düşük + EMA20 kırılımı.
    Returns: (found, swing_high_1, swing_high_2, rsi_1, rsi_2) veya (False, ...)
    """
    if df_4h is None or len(df_4h) < 30:
        return False, None, None, None, None

    df_4h = df_4h.copy()
    df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_4h.ta.ema(length=config.IND_EMA_MID, append=True)

    rsi_col = 'RSI_14'
    if rsi_col not in df_4h.columns:
        return False, None, None, None, None

    highs = df_4h['high'].values
    n = len(highs)
    swing_points = []

    for i in range(neighbors, n - 1):
        is_swing = True
        for j in range(1, neighbors + 1):
            if i - j < 0 or i + j >= n:
                is_swing = False
                break
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_points.append(i)

    if len(swing_points) < 2:
        return False, None, None, None, None

    idx1, idx2 = swing_points[-2], swing_points[-1]
    price_1 = float(df_4h.iloc[idx1]['high'])
    price_2 = float(df_4h.iloc[idx2]['high'])
    rsi_1 = float(df_4h.iloc[idx1][rsi_col])
    rsi_2 = float(df_4h.iloc[idx2][rsi_col])

    if price_2 > price_1 and rsi_2 < rsi_1 and (rsi_1 - rsi_2) >= 3:
        # SHORT_RSI_OVERBOUGHT_LIMIT: Uyumsuzluk teyidi için ilk zirvede RSI'ın aşırı alım bölgesinde olmasını şart koşar
        if rsi_1 < config.SHORT_RSI_OVERBOUGHT_LIMIT:
            return False, None, None, None, None

        # RED-16: Divergence tazelik kontrolü — çok eski swing'ler geçersiz
        if (len(df_4h) - 1 - idx2) > DIVERGENCE_MAX_AGE_CANDLES:
            return False, None, None, None, None

        # MACD Histogram Uyumsuzluk Doğrulaması
        # DIVERGENCE_MACD_CONFIRMATION_REQUIRED bayrağıyla aktifleşir.
        # Fiyat ile MACD Histogramı arasında negatif uyumsuzluk (divergence) olmasını şart koşar.
        if config.DIVERGENCE_MACD_CONFIRMATION_REQUIRED:
            df_4h.ta.macd(append=True)
            macdh_cols = [c for c in df_4h.columns if 'MACDh' in c]
            if macdh_cols:
                macd_1 = float(df_4h.iloc[idx1][macdh_cols[0]])
                macd_2 = float(df_4h.iloc[idx2][macdh_cols[0]])
                if price_2 > price_1 and macd_2 >= macd_1:
                    return False, None, None, None, None

        vol_1 = float(df_4h.iloc[idx1]['volume'])
        vol_2 = float(df_4h.iloc[idx2]['volume'])
        vol_divergence = vol_2 < vol_1

        last = df_4h.iloc[-1]
        ema20 = last.get(f'EMA_{config.IND_EMA_MID}')
        if ema20 is not None and not pd.isna(ema20):
            if float(last['close']) < float(ema20) and vol_divergence:
                return True, price_1, price_2, rsi_1, rsi_2

    return False, None, None, None, None


def detect_bullish_divergence(df_4h, neighbors=3):
    """Pozitif Uyumsuzluk (Dip Avcılığı Onayı) tespit eder.
    Fiyat Lower Low + RSI Higher Low + Hacim düşük + EMA20 kırılımı.
    Returns: (found, swing_low_1, swing_low_2, rsi_1, rsi_2) veya (False, ...)
    """
    if df_4h is None or len(df_4h) < 30:
        return False, None, None, None, None

    df_4h = df_4h.copy()
    df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_4h.ta.ema(length=config.IND_EMA_MID, append=True)

    rsi_col = 'RSI_14'
    if rsi_col not in df_4h.columns:
        return False, None, None, None, None

    lows = df_4h['low'].values
    n = len(lows)
    swing_points = []

    for i in range(neighbors, n - 1):
        is_swing = True
        for j in range(1, neighbors + 1):
            if i - j < 0 or i + j >= n:
                is_swing = False
                break
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_points.append(i)

    if len(swing_points) < 2:
        return False, None, None, None, None

    idx1, idx2 = swing_points[-2], swing_points[-1]
    price_1 = float(df_4h.iloc[idx1]['low'])
    price_2 = float(df_4h.iloc[idx2]['low'])
    rsi_1 = float(df_4h.iloc[idx1][rsi_col])
    rsi_2 = float(df_4h.iloc[idx2][rsi_col])

    if price_2 < price_1 and rsi_2 > rsi_1 and (rsi_2 - rsi_1) >= 3:
        # RED-16: Divergence tazelik kontrolü — çok eski swing'ler geçersiz
        if (len(df_4h) - 1 - idx2) > DIVERGENCE_MAX_AGE_CANDLES:
            return False, None, None, None, None

        # MACD Histogram Pozitif Uyumsuzluk Teyidi
        # DIVERGENCE_MACD_CONFIRMATION_REQUIRED bayrağıyla aktifleşir.
        # Fiyat ile MACD histogramı arasında pozitif uyumsuzluk (divergence) olmasını şart koşar.
        if config.DIVERGENCE_MACD_CONFIRMATION_REQUIRED:
            df_4h.ta.macd(append=True)
            macdh_cols = [c for c in df_4h.columns if 'MACDh' in c]
            if macdh_cols:
                macd_1 = float(df_4h.iloc[idx1][macdh_cols[0]])
                macd_2 = float(df_4h.iloc[idx2][macdh_cols[0]])
                if price_2 < price_1 and macd_2 <= macd_1:
                    return False, None, None, None, None

        vol_1 = float(df_4h.iloc[idx1]['volume'])
        vol_2 = float(df_4h.iloc[idx2]['volume'])
        vol_divergence = vol_2 < vol_1

        last = df_4h.iloc[-1]
        ema20 = last.get(f'EMA_{config.IND_EMA_MID}')
        if ema20 is not None and not pd.isna(ema20):
            if float(last['close']) > float(ema20) and vol_divergence:
                return True, price_1, price_2, rsi_1, rsi_2

    return False, None, None, None, None


# ════════════════════════════════════════
# Yeni Strateji Göstergeleri
# ════════════════════════════════════════

def detect_squeeze(df):
    """
    BB(20,2) Keltner(20, 1.5×ATR) içine girdi mi? Kırılım olduysa yön döner.
    Returns: (squeeze_fired, direction, breakout_candle)
    """
    if len(df) < 25:
        return False, None, None

    # Pandas Mutability koruması: kaynak DataFrame'i kirletme
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

    squeeze_count = 0
    for i in range(-6, -1):
        if abs(i) > len(df):
            continue
        r = df.iloc[i]
        if (not pd.isna(r.get(bbu_c)) and not pd.isna(r.get(kcu_c)) and
                r[bbu_c] < r[kcu_c] and r[bbl_c] > r[kcl_c]):
            squeeze_count += 1
    if squeeze_count < 3:
        return False, None, None

    last = df.iloc[-1]
    if pd.isna(last.get(bbu_c)) or pd.isna(last.get(bbl_c)):
        return False, None, None

    # RED-04: 2 mum onayı — tek mum sahte patlama engelleyici
    direction = None
    prev = df.iloc[-2] if len(df) >= 2 else None
    if last['close'] > last[bbu_c] and last['close'] > last['open']:
        # 2. mum teyidi: önceki mum da BB üzerinde veya yakınında mı?
        if prev is not None and not pd.isna(prev.get(bbu_c)):
            if prev['close'] > prev[bbu_c] * 0.995:  # %0.5 tolerans
                direction = "up"
        else:
            direction = "up"  # Önceki mum verisi yoksa tek mumla devam
    elif last['close'] < last[bbl_c] and last['close'] < last['open']:
        if prev is not None and not pd.isna(prev.get(bbl_c)):
            if prev['close'] < prev[bbl_c] * 1.005:
                direction = "down"
        else:
            direction = "down"
    if direction is None:
        return False, None, None

    # Squeeze Momentum Hizalama Kontrolü
    # SQUEEZE_MOMENTUM_ALIGN_REQUIRED bayrağıyla aktifleşir.
    # Momentum histogramının (MACD) kırılım yönüyle uyuşmasını şart koşar.
    if config.SQUEEZE_MOMENTUM_ALIGN_REQUIRED:
        df.ta.macd(append=True)
        macdh_cols = [c for c in df.columns if 'MACDh' in c]
        if macdh_cols:
            macd_h = df[macdh_cols[0]]
            if len(macd_h) >= 2:
                is_rising = macd_h.iloc[-1] > macd_h.iloc[-2]
                if direction == "up" and not is_rising:
                    return False, None, None
                elif direction == "down" and is_rising:
                    return False, None, None

    vol_sma = df['volume'].rolling(config.IND_VOL_SMA_LENGTH).mean()
    if not pd.isna(vol_sma.iloc[-1]) and last['volume'] < vol_sma.iloc[-1] * config.IND_VOL_BREAKOUT_MULTIPLIER:
        return False, None, None

    return True, direction, last


def calculate_relative_strength(df_stock, df_index):
    """Hissenin endekse göre göreceli gücünü hesaplar.
    Returns: (rs_strong, rs_trend_up, index_stressed, index_recovering)
    """
    if df_stock is None or df_index is None:
        return False, False, False, False
    if len(df_stock) < 55 or len(df_index) < 55:
        return False, False, False, False

    common_idx = df_stock.index.intersection(df_index.index)
    if len(common_idx) < 55:
        return False, False, False, False

    stock_c = df_stock.loc[common_idx]['close']
    index_c = df_index.loc[common_idx]['close']

    rs_line = stock_c / index_c
    rs_sma = rs_line.rolling(config.IND_RS_SMA_LENGTH).mean()

    rs_strong = bool(not pd.isna(rs_sma.iloc[-1]) and rs_line.iloc[-1] > rs_sma.iloc[-1])

    rs_trend_up = False
    if len(rs_line) >= config.IND_RS_MOMENTUM_LONG_START:
        rs_trend_up = bool(rs_line.iloc[-config.IND_RS_MOMENTUM_SHORT:].mean() > rs_line.iloc[-config.IND_RS_MOMENTUM_LONG_START:-config.IND_RS_MOMENTUM_LONG_END].mean())

    index_stressed = False
    if len(index_c) >= 6:
        idx_chg = (index_c.iloc[-1] - index_c.iloc[-6]) / index_c.iloc[-6] * 100
        index_stressed = bool(idx_chg < -2.0)

    index_recovering = False
    if len(df_index) >= 10:
        df_idx = df_index.copy()
        if 'EMA_8' not in df_idx.columns:
            df_idx.ta.ema(length=config.IND_EMA_FAST, append=True)
        ema_col = 'EMA_8' if 'EMA_8' in df_idx.columns else None
        if ema_col and not pd.isna(df_idx[ema_col].iloc[-1]):
            index_recovering = bool(df_idx['close'].iloc[-1] > df_idx[ema_col].iloc[-1])

    return rs_strong, rs_trend_up, index_stressed, index_recovering


def calculate_anchored_vwap_series(df, anchor_type="weekly"):
    """Haftalık veya Aylık açılışa göre Anchored VWAP Serisini tamamen vektörel hesaplar."""
    if len(df) < 10:
        return pd.Series(np.nan, index=df.index)
    
    df_copy = df.copy()
    if not isinstance(df_copy.index, pd.DatetimeIndex):
        df_copy.index = pd.to_datetime(df_copy.index)
        
    tp = (df_copy['high'] + df_copy['low'] + df_copy['close']) / 3
    tp_vol = tp * df_copy['volume']
    
    if anchor_type == "weekly":
        # W-MON means grouping by week ending on Monday. We use resample/transform or groupby week.
        # Equivalent: group by year and week number.
        grouper = [df_copy.index.isocalendar().year, df_copy.index.isocalendar().week]
    elif anchor_type == "monthly":
        grouper = [df_copy.index.year, df_copy.index.month]
    else:
        grouper = [df_copy.index.isocalendar().year, df_copy.index.isocalendar().week]
        
    cum_tp_vol = tp_vol.groupby(grouper).cumsum()
    cum_vol = df_copy['volume'].groupby(grouper).cumsum()
    
    vwap_series = cum_tp_vol / cum_vol
    return vwap_series

def calculate_anchored_vwap(df, anchor_type="weekly"):
    """Geriye donuk uyumluluk icin sadece son VWAP degerini dondurur."""
    vwap_series = calculate_anchored_vwap_series(df, anchor_type)
    if vwap_series.empty or pd.isna(vwap_series.iloc[-1]):
        return None
    return float(vwap_series.iloc[-1])


def detect_vwap_bounce(df, vwap_val):
    """
    Son mum VWAP'a değip Pin Bar bıraktı mı ve VWAP üzerinde tutundu mu?
    VWAP_SLOPE_CONFIRMATION: VWAP eğiminin pozitif olmasını şart koşar.
    VWAP_BOUNCE_CANDLE_CONFIRM: VWAP üzerinde kapanan ardışık onay mum sayısı.
    Returns: (bounce_ok, wick_low)
    """
    if vwap_val is None or len(df) < max(5, config.VWAP_SLOPE_LOOKBACK, config.VWAP_BOUNCE_CANDLE_CONFIRM):
        return False, None

    last = df.iloc[-1]
    
    # 1. VWAP Eğim Kontrolü (VWAP Slope Confirmation) - TAMAMEN VEKTOREL
    if config.VWAP_SLOPE_CONFIRMATION:
        vwap_series = calculate_anchored_vwap_series(df, anchor_type="weekly")
        if len(vwap_series) >= config.VWAP_SLOPE_LOOKBACK:
            vwap_past = vwap_series.iloc[-config.VWAP_SLOPE_LOOKBACK:]
            # Eger Vwap son X mumda artmiyorsa
            if vwap_past.iloc[0] >= vwap_past.iloc[-1]:
                return False, None

    # 2. VWAP Değme (Touch) ve İğne Kontrolü (Wick low <= VWAP)
    # Son (VWAP_BOUNCE_CANDLE_CONFIRM + 1) mumdan en az birinin VWAP altına iğne atmış (veya değmiş) olması gerekir.
    # Bu, VWAP seviyesinden sektiğini kanıtlar.
    touched_vwap = False
    for i in range(1, config.VWAP_BOUNCE_CANDLE_CONFIRM + 2):
        if i <= len(df):
            c = df.iloc[-i]
            if c['low'] <= vwap_val:
                touched_vwap = True
                break
    if not touched_vwap:
        return False, None

    # 3. Çoklu Mum Kapanış Onayı (Gövde Kapanışı - Close > VWAP)
    # Son N mumun kapanışının VWAP üzerinde olduğunu teyit ediyoruz.
    # Bu, fiyatın VWAP üzerinde tutunduğunu kanıtlayan 'Gövde Kapanışı' veya 'Çoklu Mum Onayı'dır.
    for i in range(1, config.VWAP_BOUNCE_CANDLE_CONFIRM + 1):
        c = df.iloc[-i]
        if c['close'] <= vwap_val:
            return False, None

    body = abs(last['close'] - last['open'])
    if math.isclose(body, 0.0, abs_tol=1e-10):
        body = last['close'] * 0.0001
    lower_wick = min(last['close'], last['open']) - last['low']
    if lower_wick < body * 2:
        return False, None

    return True, float(last['low'])



def detect_obv_accumulation(df, max_change_pct=8.0):
    """Fiyat yatayda + OBV yükseliyor + kutu kırılımı → sinyal.
    Returns: (breakout_confirmed, box_high, box_low)
    """
    if len(df) < config.IND_OBV_ACC_MIN_LEN:
        return False, None, None

    # Pandas Mutability koruması: kaynak DataFrame'i kirletme
    df = df.copy()

    if 'OBV' not in df.columns:
        df.ta.obv(append=True)
    if 'OBV' not in df.columns:
        return False, None, None

    # HATA DÜZELTME: Kutu sınırları (box_high, box_low) hesaplanırken 
    # son kırılım mumu (index -1) hariç tutulmalıdır. Aksi halde box_high en son kapanışa
    # eşit olacağı için 'last['close'] <= box_high' kontrolü her zaman True döner ve sinyal bloke olur.
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

    # OBV SMA Hizalama Kontrolü
    # OBV'nin kendi hareketli ortalamasının (SMA 20) üzerinde olması koşulunu denetler.
    if config.OBV_SMA_ALIGN_REQUIRED:
        df['OBV_SMA'] = df['OBV'].rolling(config.OBV_SMA_PERIOD).mean()
        if not pd.isna(df['OBV_SMA'].iloc[-1]) and df['OBV'].iloc[-1] <= df['OBV_SMA'].iloc[-1]:
            return False, None, None

    vol_sma = df['volume'].rolling(config.IND_OBV_ACC_PERIOD).mean()
    if not pd.isna(vol_sma.iloc[-1]) and last['volume'] < vol_sma.iloc[-1] * config.IND_OBV_ACC_VOL_MULTIPLIER:
        return False, None, None

    return True, box_high, box_low


def detect_obv_accumulation_bist(df, max_change_pct=8.0):
    """BIST 8 için özel yeni matematiksel mantık:
    1. 18/20 Yatay Kutu: Son 20 mumdan en az 18'i dar bir kutu (max_change_pct) içinde kalmalı.
    2. Kutu Zirvesinin %1-3.5 Yukarı Kırılımı: Son kapanış kutu zirvesinin %1.0 ile %3.5 üstünde olmalı.
    3. En Yüksek OBV Kapanışı: Son günün OBV'si önceki 20 günün zirve OBV'sinden büyük olmalı.
    """
    if len(df) < config.IND_OBV_ACC_MIN_LEN:
        return False, None, None

    # Pandas Mutability koruması: kaynak DataFrame'i kirletme
    df = df.copy()

    if 'OBV' not in df.columns:
        df.ta.obv(append=True)
    if 'OBV' not in df.columns:
        return False, None, None

    # Son 20 günlük kapanışlar (kırılım mumu hariç)
    closes = df['close'].iloc[-21:-1].tolist()
    sorted_closes = sorted(closes)

    # 18/20 Yatay Kutu Kontrolü
    best_window = None
    min_chg = float('inf')

    # 20 elemandan ardışık 18 eleman alan pencereler: 0:18, 1:19, 2:20
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

    # Kutu Zirvesinin %1.0 - %3.5 Yukarı Kırılımı
    last_close = float(df['close'].iloc[-1])
    breakout_pct = ((last_close - box_high) / box_high) * 100
    if not (1.0 <= breakout_pct <= 3.5):
        return False, None, None

    # En Yüksek OBV Kapanışı
    last_obv = float(df['OBV'].iloc[-1])
    prev_obv_max = float(df['OBV'].iloc[-21:-1].max())
    if last_obv <= prev_obv_max:
        return False, None, None

    # OBV SMA Hizalama Kontrolü
    if config.OBV_SMA_ALIGN_REQUIRED:
        df['OBV_SMA'] = df['OBV'].rolling(config.OBV_SMA_PERIOD).mean()
        if not pd.isna(df['OBV_SMA'].iloc[-1]) and df['OBV'].iloc[-1] <= df['OBV_SMA'].iloc[-1]:
            return False, None, None

    # Hacim Spike Kontrolü (Hacim ortalamasının üzerinde teyit)
    vol_sma = df['volume'].rolling(config.IND_OBV_ACC_PERIOD).mean()
    if not pd.isna(vol_sma.iloc[-1]) and df['volume'].iloc[-1] < vol_sma.iloc[-1] * config.IND_OBV_ACC_VOL_MULTIPLIER:
        return False, None, None

    return True, box_high, box_low


def calculate_orb_cage(df_15m):
    """BIST 10:00-11:00 kafesi + günlük VWAP. Returns: (cage_high, cage_low, cage_mid, vwap)"""
    if df_15m is None or df_15m.empty:
        return None, None, None, None
    # Bug-fix: use the last candle's date to support backtests/simulations
    today = df_15m.index[-1].date()

    df = df_15m.copy()
    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Europe/Istanbul")
        else:
            df.index = df.index.tz_convert("Europe/Istanbul")
    except Exception as e:
        logging.warning(f"[calculate_orb_cage] Timezone dönüşüm hatası: {e}")
        return None, None, None, None  # Yanlış timezone ile devam etme

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
    RVOL (Relative Volume) filtresi için kullanılır.
    """
    if df_15m is None or df_15m.empty:
        return 0.0
        
    try:
        df = df_15m.copy()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Europe/Istanbul")
        else:
            df.index = df.index.tz_convert("Europe/Istanbul")
            
        # Hedef saat ve dakikayı filtrele
        mask = (df.index.hour == target_hour) & (df.index.minute == target_minute)
        specific_bars = df[mask]
        
        if specific_bars.empty:
            return 0.0
            
        # Son N günü al
        recent_bars = specific_bars.tail(period)
        avg_vol = recent_bars['volume'].mean()
        return float(avg_vol) if not math.isnan(avg_vol) else 0.0
        
    except Exception as e:
        logging.warning(f"[calculate_time_specific_rvol] Hata: {e}")
        return 0.0

# ════════════════════════════════════════
# BIST 11: Mum Formasyonları Tespiti & Destek Kontrolleri
# ════════════════════════════════════════
def detect_bullish_candlestick_pattern(df_4h) -> tuple[Optional[str], dict]:
    """
    4H grafik üzerinde en son tamamlanan mumda (veya son 3 mumda) 8 adet 
    yükseliş (bullish) formasyonundan birinin olup olmadığını kontrol eder.
    Returns:
        (pattern_name, details_dict) - Bulunduysa pattern ismi ve detayları, yoksa (None, {})
    """
    from typing import Optional
    import pandas as pd
    if df_4h is None or len(df_4h) < 10:
        return None, {}

    o = df_4h['open'].values
    h = df_4h['high'].values
    l = df_4h['low'].values
    c = df_4h['close'].values
    
    # ATR hesapla (formasyon boyları ve fitil kontrolleri için referans)
    atr_series = df_4h.ta.atr(length=14) if 'ATR_14' not in df_4h.columns else df_4h['ATR_14']
    atr = float(atr_series.iloc[-1]) if atr_series is not None and not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (h[-1] - l[-1])
    if atr <= 0:
        atr = 1e-8

    idx = len(df_4h) - 1

    # Yardımcı değişkenler (Index idx için)
    open_curr = float(o[idx])
    high_curr = float(h[idx])
    low_curr = float(l[idx])
    close_curr = float(c[idx])
    body_curr = abs(close_curr - open_curr)
    tot_curr = high_curr - low_curr if high_curr - low_curr > 0 else 1e-8
    upper_shadow_curr = high_curr - max(open_curr, close_curr)
    lower_shadow_curr = min(open_curr, close_curr) - low_curr
    is_green_curr = close_curr > open_curr

    # Önceki mum değişkenleri (Index idx - 1)
    open_prev = float(o[idx - 1])
    high_prev = float(h[idx - 1])
    low_prev = float(l[idx - 1])
    close_prev = float(c[idx - 1])
    body_prev = abs(close_prev - open_prev)
    is_green_prev = close_prev > open_prev

    # İki önceki mum değişkenleri (Index idx - 2)
    open_prev2 = float(o[idx - 2])
    high_prev2 = float(h[idx - 2])
    low_prev2 = float(l[idx - 2])
    close_prev2 = float(c[idx - 2])
    body_prev2 = abs(close_prev2 - open_prev2)
    is_green_prev2 = close_prev2 > open_prev2

    # 1. HAMMER (Çekiç)
    # Alt fitil gövdenin en az 2 katı olmalı, üst fitil çok küçük olmalı
    if lower_shadow_curr >= 2.0 * body_curr and upper_shadow_curr <= 0.1 * tot_curr and body_curr > 0:
        # Fiyatın düşüş trendinde olduğunu veya son 5 mumun en düşüğü olduğunu teyit et
        if low_curr <= min(l[idx-5:idx]):
            return "Hammer (Çekiç)", {"pattern": "Hammer", "body": body_curr, "lower_shadow": lower_shadow_curr}

    # 2. INVERTED HAMMER (Ters Çekiç)
    # Üst fitil gövdenin en az 2 katı olmalı, alt fitil çok küçük olmalı
    if upper_shadow_curr >= 2.0 * body_curr and lower_shadow_curr <= 0.1 * tot_curr and body_curr > 0:
        if low_curr <= min(l[idx-5:idx]):
            return "Inverted Hammer (Ters Çekiç)", {"pattern": "Inverted Hammer", "body": body_curr, "upper_shadow": upper_shadow_curr}

    # 3. DRAGONFLY DOJI (Yusufçuk Doji)
    # Gövde neredeyse yok, alt fitil çok uzun, üst fitil neredeyse yok
    if body_curr <= 0.05 * tot_curr and lower_shadow_curr >= 0.7 * tot_curr and upper_shadow_curr <= 0.1 * tot_curr:
        if low_curr <= min(l[idx-5:idx]):
            return "Dragonfly Doji (Yusufçuk Doji)", {"pattern": "Dragonfly Doji", "lower_shadow": lower_shadow_curr}

    # 4. BULLISH ENGULFING (Yutan Boğa)
    # İlk mum kırmızı, ikinci yeşil ve gövdesi ilkini tamamen içine alıyor
    if not is_green_prev and is_green_curr:
        if open_curr <= close_prev and close_curr >= open_prev and (open_curr < close_prev or close_curr > open_prev):
            if close_curr > close_prev:
                return "Bullish Engulfing (Yutan Boğa)", {"pattern": "Bullish Engulfing", "body_prev": body_prev, "body_curr": body_curr}

    # 5. PIERCING LINE (Delen Hat)
    # İlk mum kırmızı, ikinci yeşil, açılışı eskinin altında, kapanışı eskinin gövdesinin en az yarısının üstünde ama açılışının altında
    if not is_green_prev and is_green_curr:
        half_body_prev = close_prev + 0.5 * (open_prev - close_prev)
        if open_curr < close_prev and close_curr >= half_body_prev and close_curr < open_prev:
            return "Piercing Line (Delen Hat)", {"pattern": "Piercing Line", "close_curr": close_curr, "half_prev": half_body_prev}

    # 6. TWEEZER BOTTOM (Cımbız Dip)
    # İki mumun dipleri neredeyse eşit, ikinci yeşil, ve dipler son 10 mumun alt yarısında
    diff_lows = abs(low_curr - low_prev) / min(low_curr, low_prev) * 100
    if diff_lows <= 0.05 and is_green_curr:
        if low_curr <= min(l[idx-8:idx]):
            return "Tweezer Bottom (Cımbız Dip)", {"pattern": "Tweezer Bottom", "low_diff_pct": diff_lows}

    # 7. MORNING STAR (Sabah Yıldızı)
    # Mum 1: kırmızı, Mum 2: küçük gövdeli kararsızlık, Mum 3: yeşil ve 1'in gövde yarısının üzerinde kapatıyor
    if not is_green_prev2 and is_green_curr:
        # Mum 2 gövdesi küçük (Mum 1 gövdesinin %30'undan az)
        if body_prev <= 0.3 * body_prev2:
            half_body_prev2 = close_prev2 + 0.5 * (open_prev2 - close_prev2)
            if close_curr >= half_body_prev2 and open_curr >= close_prev:
                return "Morning Star (Sabah Yıldızı)", {"pattern": "Morning Star"}

    # 8. THREE WHITE SOLDIERS (Üç Beyaz Asker)
    # Peş peşe üç yeşil mum, kapanışlar yükseliyor, gövdeler sağlıklı, üst fitiller kısa
    if is_green_prev2 and is_green_prev and is_green_curr:
        if close_curr > close_prev > close_prev2:
            if body_curr > 0.1 * atr and body_prev > 0.1 * atr and body_prev2 > 0.1 * atr:
                # Üst fitiller kısa
                if upper_shadow_curr <= 0.2 * body_curr and (high_prev - close_prev) <= 0.2 * body_prev and (high_prev2 - close_prev2) <= 0.2 * body_prev2:
                    return "Three White Soldiers (Üç Beyaz Asker)", {"pattern": "Three White Soldiers"}

    return None, {}

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
    
    # 4H EMA'lar
    for length in [8, 21]:
        col = f"EMA_{length}"
        if col in df_4h.columns:
            supports[f"4H {col}"] = float(df_4h[col].iloc[-1])
            
    # 1D EMA & SMA'lar
    for col in ["EMA_21", "SMA_50", "SMA_200"]:
        if col in df_1d.columns:
            supports[f"1D {col}"] = float(df_1d[col].iloc[-1])

    # 4H Bollinger Alt Bandı
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
        return True, f"{closest_support} desteğine yakın (Mesafe: %{min_dist_pct:.2f})"
        
    return False, "Hiçbir önemli desteğe yakın değil"


# ---------------------------------------------------------------------------
# BIST 12: Grafik Formasyonları (Chart Patterns) Tespiti
# ---------------------------------------------------------------------------
def _check_session_aware_volume(df_4h, current_volume: float, current_hour: int) -> bool:
    """
    Kırılım mumu hacmini son 10 gündeki AYNI seans saatine denk gelen mumların hacim ortalamasıyla karşılaştırır.
    BIST gün sonu karanlık oda veya açılış saati hacim anomalilerini engellemek için seans duyarlıdır.
    """
    import pandas as pd
    import logging
    
    # Aynı saat dilimine sahip geçmiş barları filtrele (mevcut bar hariç)
    session_bars = df_4h[df_4h.index.hour == current_hour]
    if len(session_bars) < 2:
        return True # Yetersiz geçmiş bar varsa geçişe izin ver
        
    past_session_bars = session_bars.iloc[:-1]
    if past_session_bars.empty:
        return True
        
    avg_session_vol = float(past_session_bars['volume'].mean())
    if avg_session_vol <= 0:
        return True
        
    vol_ratio = current_volume / avg_session_vol
    logging.info(f"[_check_session_aware_volume] Seans Saati: {current_hour}:00 | Hacim Oranı: {vol_ratio:.2f}x (Ortalama: {avg_session_vol:.0f})")
    return vol_ratio >= config.BIST12_VOLUME_MULT


def detect_chart_patterns(df_4h) -> tuple[Optional[str], dict]:
    """
    Taramada son tamamlanan barda oluşmuş/kırılmış boğa (bullish) grafik formasyonlarını tespit eder.
    OBO, TOBO, İkili Dip/Tepe, Bayrak/Flama ve Dikdörtgen Kırılımları.
    NumPy tabanlı vektörel/indeks karşılaştırmaları kullanarak performansı korur.
    """
    from scipy.signal import find_peaks
    import numpy as np
    import pandas as pd
    import logging
    
    if df_4h is None or len(df_4h) < 30:
        return None, {}
        
    # NumPy dizilerine dönüştürme (RAM optimizasyonu)
    close_arr = df_4h['close'].values.astype(np.float64)
    high_arr = df_4h['high'].values.astype(np.float64)
    low_arr = df_4h['low'].values.astype(np.float64)
    open_arr = df_4h['open'].values.astype(np.float64)
    volume_arr = df_4h['volume'].values.astype(np.float64)
    
    # Son bar fiyat ve volatilite verileri
    current_price = close_arr[-1]
    
    # RSI Hesaplaması
    if 'RSI_14' not in df_4h.columns:
        df_4h.ta.rsi(length=14, append=True)
    rsi_arr = df_4h['RSI_14'].values.astype(np.float64)
    
    atr_series = df_4h.ta.atr(length=14) if 'ATR_14' not in df_4h.columns else df_4h['ATR_14']
    atr = float(atr_series.iloc[-1]) if atr_series is not None and not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (high_arr[-1] - low_arr[-1])
    if atr <= 0:
        atr = 1e-8
        
    # Dinamik prominence ve esneklik toleransları (Volatilite uyumlu)
    prominence = atr * config.BIST12_PROMINENCE_ATR_MULT
    dynamic_double_tol = max(config.BIST12_DOUBLE_BASE_TOLERANCE_PCT, (atr / current_price) * 100.0 * config.BIST12_VOLATILITY_TOLERANCE_MULT) / 100.0
    dynamic_obo_tol = max(config.BIST12_OBO_BASE_TOLERANCE_PCT, (atr / current_price) * 100.0 * config.BIST12_VOLATILITY_TOLERANCE_MULT) / 100.0
    
    # ----------------------------------------------------
    # 1. Dikdörtgen Kırılımı (Darvas Box)
    # ----------------------------------------------------
    box_len = 20
    if len(close_arr) >= box_len:
        box_highs = high_arr[-box_len:-1]
        box_lows = low_arr[-box_len:-1]
        max_high = float(np.max(box_highs))
        min_low = float(np.min(box_lows))
        box_height_pct = (max_high - min_low) / min_low * 100.0
        
        # Sıkışma yeterince dar mı?
        if box_height_pct <= config.BIST12_RECTANGLE_HEIGHT_PCT:
            # En az ikişer kez test edilmiş mi?
            upper_touches = np.sum((max_high - box_highs) / max_high * 100.0 <= 1.0)
            lower_touches = np.sum((box_lows - min_low) / min_low * 100.0 <= 1.0)
            
            if upper_touches >= 2 and lower_touches >= 2:
                # Yukarı yönlü kırılım (AL)
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
                        
    peaks, _ = find_peaks(close_arr, prominence=prominence, distance=4)
    valleys, _ = find_peaks(-close_arr, prominence=prominence, distance=4)
    
    # ----------------------------------------------------
    # 2. TOBO (Ters Omuz Baş Omuz) - Bullish Reversal
    # ----------------------------------------------------
    if len(valleys) >= 3 and len(peaks) >= 2:
        v1, v2, v3 = valleys[-3], valleys[-2], valleys[-1]
        p1_candidates = peaks[(peaks > v1) & (peaks < v2)]
        p2_candidates = peaks[(peaks > v2) & (peaks < v3)]
        
        if len(p1_candidates) > 0 and len(p2_candidates) > 0:
            idx_v1, idx_v2, idx_v3 = v1, v2, v3
            idx_p1, idx_p2 = p1_candidates[-1], p2_candidates[-1]
            
            val_v1, val_v2, val_v3 = close_arr[idx_v1], close_arr[idx_v2], close_arr[idx_v3]
            val_p1, val_p2 = close_arr[idx_p1], close_arr[idx_p2]
            
            # Baş en dipte olmalı
            if val_v2 < val_v1 and val_v2 < val_v3:
                shoulder_diff = abs(val_v1 - val_v3) / max(val_v1, val_v3)
                neck_diff = abs(val_p1 - val_p2) / max(val_p1, val_p2)
                
                if shoulder_diff <= dynamic_obo_tol and neck_diff <= (config.BIST12_NECK_TOLERANCE_PCT / 100.0):
                    # Boyun çizgisi (Neckline) hesabı
                    m = (val_p2 - val_p1) / (idx_p2 - idx_p1)
                    neck_price = val_p2 + m * (len(close_arr) - 1 - idx_p2)
                    
                    if current_price > neck_price:
                        # RSI Uyumsuzluğu Kontrolü (Baş vs Sağ Omuz veya Sol vs Baş)
                        rsi_divergence = False
                        if rsi_arr[idx_v3] > rsi_arr[idx_v2] or rsi_arr[idx_v2] > rsi_arr[idx_v1]:
                            rsi_divergence = True
                            
                        # Hacim Kontrolü
                        current_hour = df_4h.index[-1].hour
                        vol_ok = _check_session_aware_volume(df_4h, volume_arr[-1], current_hour)
                        
                        if (not config.BIST12_RSI_DIVERGENCE_REQUIRED or rsi_divergence) and vol_ok:
                            return "Ters Omuz Baş Omuz (TOBO) Kırılımı", {
                                "pattern": "TOBO",
                                "signal": "AL",
                                "sl": val_v3 * 0.99,
                                "details": f"Sol: {val_v1:.2f}, Baş: {val_v2:.2f}, Sağ: {val_v3:.2f}"
                            }

    # ----------------------------------------------------
    # 3. İkili Dip (Double Bottom) - Bullish Reversal
    # ----------------------------------------------------
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
                        # RSI Uyumsuzluğu Kontrolü
                        rsi_divergence = False
                        if rsi_arr[idx_v2] > rsi_arr[idx_v1]: # Fiyat daha aşağıda veya eşitken RSI yükselmeli
                            rsi_divergence = True
                            
                        # Hacim Kontrolü
                        current_hour = df_4h.index[-1].hour
                        vol_ok = _check_session_aware_volume(df_4h, volume_arr[-1], current_hour)

                        if (not config.BIST12_RSI_DIVERGENCE_REQUIRED or rsi_divergence) and vol_ok:
                            sl_level = min(val_v1, val_v2) * 0.99
                            return "İkili Dip Kırılımı", {
                                "pattern": "Double Bottom",
                                "signal": "AL",
                                "sl": sl_level,
                                "details": f"Dip 1: {val_v1:.2f}, Dip 2: {val_v2:.2f}, Ara Tepe: {val_p:.2f}"
                            }

    # ----------------------------------------------------
    # 4. Boğa Bayrağı (Bull Flag) - Bullish Continuation
    # ----------------------------------------------------
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
                                "sl": flag_min_low * 0.99,
                                "details": f"Bayrak Direği: %{pole_pct:.1f}, Dinlenme Hacmi: {flag_avg_vol:.0f}"
                            }

    # ----------------------------------------------------
    # 5. Alçalan Takoz (Falling Wedge) - Bullish Breakout
    # ----------------------------------------------------
    if len(valleys) >= 3 and len(peaks) >= 3:
        p_idx = peaks[-3:]
        v_idx = valleys[-3:]
        
        slope_p, intercept_p = np.polyfit(p_idx, close_arr[p_idx], 1)
        slope_v, intercept_v = np.polyfit(v_idx, close_arr[v_idx], 1)
        
        norm_slope_p = slope_p / current_price * 100.0
        norm_slope_v = slope_v / current_price * 100.0
        
        if norm_slope_p < -0.05 and norm_slope_v < -0.05:
            if norm_slope_p < norm_slope_v - config.BIST12_WEDGE_CONVERGENCE_FACTOR:
                resistance_at_last = slope_p * (len(close_arr) - 1) + intercept_p
                
                # SMC Filtresi: CHoCH ve FVG kontrolü
                last_peak_val = close_arr[p_idx[-1]]
                choch_ok = current_price > last_peak_val
                fvg_ok = len(low_arr) >= 3 and (low_arr[-1] > high_arr[-3])
                
                # Liquidity Sweep: Vadilerin (destek bölgesi) fitille ihlal edilip temizlenmesi
                support_level = min(low_arr[v_idx[-3]], low_arr[v_idx[-2]])
                sweep_ok = False
                for idx in range(v_idx[-2], len(close_arr)):
                    if low_arr[idx] < support_level and close_arr[idx] >= support_level:
                        sweep_ok = True
                        break
                
                # SMC Strict Mode kontrolü
                smc_pass = (fvg_ok and sweep_ok) if config.BIST12_SMC_STRICT_MODE else True
                
                if choch_ok and smc_pass:
                    if current_price > resistance_at_last:
                        current_hour = df_4h.index[-1].hour
                        if _check_session_aware_volume(df_4h, volume_arr[-1], current_hour):
                            return "Alçalan Takoz Yukarı Kırılımı", {
                                "pattern": "Falling Wedge",
                                "signal": "AL",
                                "sl": close_arr[v_idx[-1]] * 0.99,
                                "details": f"Direnç Eğimi: %{norm_slope_p:.2f}, Destek Eğimi: %{norm_slope_v:.2f}, SMC Strict: {config.BIST12_SMC_STRICT_MODE}"
                            }

    # ----------------------------------------------------
    # 6. Yükselen Üçgen (Ascending Triangle) - Bullish Breakout
    # ----------------------------------------------------
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
                
                if p_var <= 2.5:
                    # SMC Filtresi: CHoCH ve FVG kontrolü
                    choch_ok = current_price > max_p
                    fvg_ok = len(low_arr) >= 3 and (low_arr[-1] > high_arr[-3])
                    
                    # Liquidity Sweep: Destek seviyelerinin fitille ihlali ve geri toparlanması
                    support_level = min(low_arr[v_idx[-3]], low_arr[v_idx[-2]])
                    sweep_ok = False
                    for idx in range(v_idx[-2], len(close_arr)):
                        if low_arr[idx] < support_level and close_arr[idx] >= support_level:
                            sweep_ok = True
                            break
                    
                    # SMC Strict Mode kontrolü
                    smc_pass = (fvg_ok and sweep_ok) if config.BIST12_SMC_STRICT_MODE else True
                    
                    if choch_ok and smc_pass:
                        current_hour = df_4h.index[-1].hour
                        if _check_session_aware_volume(df_4h, volume_arr[-1], current_hour):
                            return "Yükselen Üçgen Yukarı Kırılımı", {
                                "pattern": "Ascending Triangle",
                                "signal": "AL",
                                "sl": close_arr[v_idx[-1]] * 0.99,
                                "details": f"Direnç Varyansı: %{p_var:.2f}, Destek Eğimi: %{norm_slope_v:.2f}, SMC Strict: {config.BIST12_SMC_STRICT_MODE}"
                            }

    # ----------------------------------------------------
    # 7. Elmas Dip (Diamond Bottom) - Bullish Reversal
    # ----------------------------------------------------
    if len(valleys) >= 3 and len(peaks) >= 2:
        # Basit bir elmas dip tespiti: Genişleyen yapı sonrası daralan yapı.
        # V1 -> P1 -> V2 -> P2 -> V3 (V1 > V2 < V3, P1 < P2 > P3 veya benzeri)
        # Orta dip en düşük olmalı, tepeler önce yükselip sonra düşmeli.
        v1, v2, v3 = valleys[-3], valleys[-2], valleys[-1]
        p_candidates_left = peaks[(peaks > v1) & (peaks < v2)]
        p_candidates_right = peaks[(peaks > v2) & (peaks < v3)]
        
        if len(p_candidates_left) > 0 and len(p_candidates_right) > 0:
            p1 = p_candidates_left[-1]
            p2 = p_candidates_right[-1]
            
            val_v1, val_v2, val_v3 = close_arr[v1], close_arr[v2], close_arr[v3]
            val_p1, val_p2 = close_arr[p1], close_arr[p2]
            
            # Elmas karakteristiği: V2 en düşük (Head of Diamond)
            if val_v2 < val_v1 and val_v2 < val_v3:
                # Genişleme (P1 > V1, P2 > P1 veya P2 yakın P1)
                # Tam elmas için simetri aranır, ancak kırılım P2 ile V3 arasından çekilen düşen trendin kırılmasıdır.
                m_desc = (val_v3 - val_p2) / max(1, (v3 - p2))
                resistance_at_last = val_p2 + m_desc * (len(close_arr) - 1 - p2)
                
                # Elmas onayı: Daralma (V3 > V2) ve düşen trendin yukarı kırılması
                if val_v3 > val_v2 and val_p2 < val_p1 * 1.05: # P2, P1'i çok aşmamalı
                    if current_price > resistance_at_last:
                        # RSI Uyumsuzluğu Kontrolü
                        rsi_divergence = False
                        if rsi_arr[v3] > rsi_arr[v2] or rsi_arr[v2] > rsi_arr[v1]:
                            rsi_divergence = True
                            
                        current_hour = df_4h.index[-1].hour
                        vol_ok = _check_session_aware_volume(df_4h, volume_arr[-1], current_hour)
                        
                        if (not config.BIST12_RSI_DIVERGENCE_REQUIRED or rsi_divergence) and vol_ok:
                            return "Elmas Dip Yukarı Kırılımı", {
                                "pattern": "Diamond Bottom",
                                "signal": "AL",
                                "sl": val_v2 * 0.99,
                                "details": f"Orta Dip: {val_v2:.2f}, Kırılım Direnci: {resistance_at_last:.2f}"
                            }

    # ----------------------------------------------------
    # 8. Harmonik Formasyonlar (AB=CD, Gartley, Bat)
    # ----------------------------------------------------
    if len(peaks) >= 2 and len(valleys) >= 2:
        p_candidates = list(peaks[-3:])
        v_candidates = list(valleys[-3:])
        
        all_pivots = sorted(
            [(idx, 'P', close_arr[idx]) for idx in p_candidates] + 
            [(idx, 'V', close_arr[idx]) for idx in v_candidates],
            key=lambda x: x[0]
        )
        
        # Calculate RSI safely for cross-verification
        rsi_col = f'RSI_{config.IND_RSI_LENGTH}'
        rsi_series = df_4h[rsi_col] if rsi_col in df_4h.columns else ta.rsi(df_4h['close'], length=config.IND_RSI_LENGTH)
        
        if len(all_pivots) >= 5:
            pivots_5 = all_pivots[-5:]
            is_alt = True
            for i in range(4):
                if pivots_5[i][1] == pivots_5[i+1][1]:
                    is_alt = False
                    break
                    
            if is_alt and pivots_5[4][1] == 'V':
                idx_x, x_val = pivots_5[0][0], pivots_5[0][2]
                idx_a, a_val = pivots_5[1][0], pivots_5[1][2]
                idx_b, b_val = pivots_5[2][0], pivots_5[2][2]
                idx_c, c_val = pivots_5[3][0], pivots_5[3][2]
                idx_d, d_val = pivots_5[4][0], pivots_5[4][2]
                
                xa = abs(a_val - x_val)
                ab = abs(b_val - a_val)
                bc = abs(c_val - b_val)
                cd = abs(d_val - c_val)
                
                ratio_ab_xa = ab / max(xa, 1e-8)
                ratio_bc_ab = bc / max(ab, 1e-8)
                ratio_cd_bc = cd / max(bc, 1e-8)
                ratio_ad_xa = (a_val - d_val) / max(xa, 1e-8)
                
                tol = config.BIST12_HARMONIC_TOLERANCE
                
                # Verify Bullish RSI Divergence: D price < B price, and D RSI > B RSI
                rsi_b = float(rsi_series.iloc[idx_b]) if rsi_series is not None and len(rsi_series) > idx_b else None
                rsi_d = float(rsi_series.iloc[idx_d]) if rsi_series is not None and len(rsi_series) > idx_d else None
                has_rsi_div = (
                    rsi_b is not None and 
                    rsi_d is not None and 
                    not np.isnan(rsi_b) and 
                    not np.isnan(rsi_d) and 
                    d_val < b_val and 
                    rsi_d > rsi_b
                )
                
                if has_rsi_div:
                    if abs(ratio_ab_xa - 0.618) <= tol:
                        if 0.382 - tol <= ratio_bc_ab <= 0.886 + tol:
                            if 1.272 - tol <= ratio_cd_bc <= 1.618 + tol:
                                if abs(ratio_ad_xa - 0.786) <= tol:
                                    if current_price > d_val and (len(close_arr) - 1 - idx_d) <= 4:
                                        return "Harmonik Gartley Formasyonu (Boğa)", {
                                            "pattern": "Harmonic Gartley",
                                            "signal": "AL",
                                            "sl": d_val * 0.99,
                                            "details": f"D Noktası: {d_val:.2f}, Retracement: {ratio_ad_xa:.3f}, RSI Div: {rsi_d:.1f} > {rsi_b:.1f}"
                                        }
                                        
                    if 0.382 - tol <= ratio_ab_xa <= 0.50 + tol:
                        if 0.382 - tol <= ratio_bc_ab <= 0.886 + tol:
                            if 1.618 - tol <= ratio_cd_bc <= 2.618 + tol:
                                if abs(ratio_ad_xa - 0.886) <= tol:
                                    if current_price > d_val and (len(close_arr) - 1 - idx_d) <= 4:
                                        return "Harmonik Bat Formasyonu (Boğa)", {
                                            "pattern": "Harmonic Bat",
                                            "signal": "AL",
                                            "sl": d_val * 0.99,
                                            "details": f"D Noktası: {d_val:.2f}, Retracement: {ratio_ad_xa:.3f}, RSI Div: {rsi_d:.1f} > {rsi_b:.1f}"
                                        }
 
        if len(all_pivots) >= 4:
            pivots_4 = all_pivots[-4:]
            is_alt_4 = True
            for i in range(3):
                if pivots_4[i][1] == pivots_4[i+1][1]:
                    is_alt_4 = False
                    break
                    
            if is_alt_4 and pivots_4[3][1] == 'V':
                idx_a, a_val = pivots_4[0][0], pivots_4[0][2]
                idx_b, b_val = pivots_4[1][0], pivots_4[1][2]
                idx_c, c_val = pivots_4[2][0], pivots_4[2][2]
                idx_d, d_val = pivots_4[3][0], pivots_4[3][2]
                
                ab = abs(b_val - a_val)
                bc = abs(c_val - b_val)
                cd = abs(d_val - c_val)
                
                ratio_bc_ab = bc / max(ab, 1e-8)
                ratio_cd_bc = cd / max(bc, 1e-8)
                
                tol = config.BIST12_HARMONIC_TOLERANCE
                
                # Verify Bullish RSI Divergence: D price < B price, and D RSI > B RSI
                rsi_b = float(rsi_series.iloc[idx_b]) if rsi_series is not None and len(rsi_series) > idx_b else None
                rsi_d = float(rsi_series.iloc[idx_d]) if rsi_series is not None and len(rsi_series) > idx_d else None
                has_rsi_div = (
                    rsi_b is not None and 
                    rsi_d is not None and 
                    not np.isnan(rsi_b) and 
                    not np.isnan(rsi_d) and 
                    d_val < b_val and 
                    rsi_d > rsi_b
                )
                
                if has_rsi_div:
                    if 0.618 - tol <= ratio_bc_ab <= 0.786 + tol:
                        if 1.272 - tol <= ratio_cd_bc <= 1.618 + tol:
                            if abs(ab - cd) / max(ab, cd) <= tol:
                                if current_price > d_val and (len(close_arr) - 1 - idx_d) <= 4:
                                    return "Harmonik AB=CD Formasyonu (Boğa)", {
                                        "pattern": "Harmonic ABCD",
                                        "signal": "AL",
                                        "sl": d_val * 0.99,
                                        "details": f"AB: {ab:.2f}, CD: {cd:.2f}, RSI Div: {rsi_d:.1f} > {rsi_b:.1f}"
                                    }

    return None, {}
