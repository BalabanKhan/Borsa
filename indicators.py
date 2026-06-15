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
from config import (
    SWING_MIN_AMPLITUDE_PCT, DIVERGENCE_MAX_AGE_CANDLES, SQUEEZE_CONFIRM_CANDLES,
    ENGULFING_MIN_BODY_RATIO, CMF_PERIOD, CMF_WASH_TRADE_THRESHOLD,
    OTE_MIN_WAVE_PCT,
)


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


def calculate_anchored_vwap(df, anchor_type="weekly"):
    """Haftalık veya Aylık açılışa göre Anchored VWAP hesaplar."""
    if len(df) < 10:
        return None
    try:
        df_copy = df.copy()  # Pandas Mutability koruması: her durumda copy
        if not isinstance(df_copy.index, pd.DatetimeIndex):
            df_copy.index = pd.to_datetime(df_copy.index)

        last_date = df_copy.index[-1]
        
        if anchor_type == "weekly":
            start_of_period = last_date.normalize() - pd.Timedelta(days=last_date.dayofweek)
        elif anchor_type == "monthly":
            start_of_period = last_date.replace(day=1).normalize()
        else:
            start_of_period = last_date - pd.Timedelta(days=7)

        vwap_df = df_copy[df_copy.index >= start_of_period]
        
        if len(vwap_df) == 0:
            vwap_df = df_copy.iloc[-20:]
            
        tp = (vwap_df['high'] + vwap_df['low'] + vwap_df['close']) / 3
        cum_tp_vol = (tp * vwap_df['volume']).cumsum()
        cum_vol = vwap_df['volume'].cumsum()
        
        if math.isclose(cum_vol.iloc[-1], 0.0, abs_tol=1e-8):
            return None
        return float(cum_tp_vol.iloc[-1] / cum_vol.iloc[-1])
    except Exception:
        if len(df) < 20:
            return None
        vwap_df = df.iloc[-20:]
        tp = (vwap_df['high'] + vwap_df['low'] + vwap_df['close']) / 3
        cum_tp_vol = (tp * vwap_df['volume']).cumsum()
        cum_vol = vwap_df['volume'].cumsum()
        if math.isclose(cum_vol.iloc[-1], 0.0, abs_tol=1e-8):
            return None
        return float(cum_tp_vol.iloc[-1] / cum_vol.iloc[-1])


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
    
    # 1. VWAP Eğim Kontrolü (VWAP Slope Confirmation)
    if config.VWAP_SLOPE_CONFIRMATION:
        # VWAP eğimini ölçmek için geçmiş N mumun Anchored VWAP değerlerini hesaplayıp kıyaslıyoruz.
        # Bu, VWAP'ın yatay/aşağı yönlü olduğu chop piyasalarda işleme girmeyi engeller.
        vwap_past = []
        for offset in range(config.VWAP_SLOPE_LOOKBACK):
            sub_df = df.iloc[:len(df) - offset]
            val = calculate_anchored_vwap(sub_df, anchor_type="weekly")
            if val is not None:
                vwap_past.append(val)
        if len(vwap_past) >= config.VWAP_SLOPE_LOOKBACK:
            # En yeni VWAP, geçmişteki VWAP değerlerinden büyük olmalı (yukarı eğimli trend)
            if vwap_past[0] <= vwap_past[-1]:
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

    recent = df.iloc[-config.IND_OBV_ACC_PERIOD:]
    price_chg = abs((recent['close'].iloc[-1] - recent['close'].iloc[0]) / recent['close'].iloc[0]) * 100
    if price_chg > max_change_pct:
        return False, None, None

    box_high = float(recent['close'].max())
    box_low = float(recent['close'].min())

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


def calculate_orb_cage(df_15m):
    """BIST 10:00-11:00 kafesi + günlük VWAP. Returns: (cage_high, cage_low, cage_mid, vwap)"""
    if df_15m is None or df_15m.empty:
        return None, None, None, None
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    today = now.date()

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
