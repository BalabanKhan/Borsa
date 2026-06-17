import numpy as np
import pandas as pd
import config
import logging
from config import (
    ENGULFING_MIN_BODY_RATIO, CMF_PERIOD, CMF_WASH_TRADE_THRESHOLD, OTE_MIN_WAVE_PCT,
)

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
    hl_range = hl_range.replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / hl_range
    mfm = mfm.fillna(0)

    # Money Flow Volume (MFV)
    mfv = mfm * volume

    # CMF = Rolling sum(MFV) / Rolling sum(Volume)
    cmf_num = mfv.rolling(period).sum()
    cmf_den = volume.rolling(period).sum()

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
        return False
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
        sweep_body = min(sweep_candle['close'], sweep_candle['open'])
        msb_body = max(msb_candle['close'], msb_candle['open'])
    else:
        sweep_body = max(sweep_candle['close'], sweep_candle['open'])
        msb_body = min(msb_candle['close'], msb_candle['open'])

    fib_range = abs(msb_body - sweep_body)
    if fib_range < 1e-10:
        return 0, 0

    mid_price = (sweep_body + msb_body) / 2
    wave_pct = (fib_range / mid_price) * 100
    if wave_pct < OTE_MIN_WAVE_PCT:
        logging.debug(f"[AM-05] Dalga çok küçük: %{wave_pct:.2f} < %{OTE_MIN_WAVE_PCT}")
        return 0, 0

    if sweep_body < msb_body:  # LONG
        ote_top = msb_body - (fib_range * config.FIB_618)
        ote_bottom = msb_body - (fib_range * config.FIB_786)
    else:  # SHORT
        ote_bottom = msb_body + (fib_range * config.FIB_618)
        ote_top = msb_body + (fib_range * config.FIB_786)

    return ote_top, ote_bottom
