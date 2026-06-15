"""
strategies.py — Strateji Katmanı
Tüm BIST, Kripto, Emtia ve Ayı Avcısı strateji fonksiyonları + scan_all_markets.
ThreadPoolExecutor ile toplu tarama.
"""
import logging
import math
import time as _time
import gc
import pandas as pd
import pandas_ta as ta
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    TOP_BIST, TOP_CRYPTO, TOP_EMTIA, TOP_HEAVY_SHORT, MEME_BLACKLIST,
    EMTIA_ATR_MULT, DXY_SENSITIVE, EMTIA_NAMES,
    API_SLEEP_BIST, API_SLEEP_CRYPTO, API_SLEEP_EMTIA, BATCH_MAX_WORKERS,
    ATR_MULTIPLIER_BIST, ATR_MULTIPLIER_CRYPTO,
    ATR_CAP_BIST, ATR_CAP_CRYPTO, ATR_CAP_EMTIA,
    MIN_DOLLAR_VOL_CRYPTO, MIN_DOLLAR_VOL_BIST,
    GAP_THRESHOLD_PCT, DARTH_MAUL_BODY_RATIO,
    VOL_SMA_LONG_RATIO, ADX_TOO_LATE,
    # AM Serisi Anti-Manipülasyon Kalkanları
    ENGULFING_MIN_BODY_RATIO,
    MIN_HOURLY_DOLLAR_VOL_CRYPTO, MIN_HOURLY_TL_VOL_BIST,
    FUNDING_SHORT_BLOCK_THRESHOLD,
    OTE_MIN_WAVE_PCT,
    LIQUIDITY_WINDOW_START_HOUR, LIQUIDITY_WINDOW_START_MIN,
    LIQUIDITY_WINDOW_END_HOUR, LIQUIDITY_WINDOW_END_MIN,
    RR_MINIMUM,
)
from data_sources import (
    get_bist_data, get_crypto_data, get_emtia_data, get_bist_15m_data,
    get_bist_data_batch, get_bist_15m_batch,
    get_crypto_data_cached, clear_cycle_cache, purge_expired_cache,
    is_bist_open, is_weekend_fakeout_time, check_xu100_wind,
    get_btc_status, check_btc_not_pumping,
    get_funding_rate, fetch_crypto_oi_crash, get_btc_dominance_trend,
    check_token_unlocks, _get_btc_htf_bias, _check_dxy_shield,
    _is_macro_news_hour, _is_btc_bullish_for_shorts, _get_xu100_daily_data,
    get_current_prices,
)
from indicators import (
    sniper_get_htf_bias, sniper_find_swing_points, sniper_detect_sweep,
    sniper_detect_msb, sniper_calculate_ote, sniper_detect_fvg,
    detect_sfp, detect_premium_rejection, detect_bearish_divergence,
    detect_bullish_divergence, detect_squeeze, calculate_relative_strength,
    calculate_anchored_vwap, detect_vwap_bounce, detect_obv_accumulation,
    calculate_orb_cage, calculate_time_specific_rvol,
    # AM Serisi
    check_bullish_engulfing_momentum, calculate_cmf, is_cmf_wash_trade,
    sniper_calculate_ote_body,
)
from data_guard import guard_mtf_bundle, guard_signal_output
from meta_engine import get_bist100_trend
from conviction_scorer import (
    check_hard_blocks, calculate_conviction,
    build_trend_scores, build_dip_scores, build_breakout_scores, build_short_scores,
    score_adx, score_rsi_oversold, score_rsi_trend, score_rsi_direction,
    score_volume_ratio, score_dollar_volume, score_rr_ratio,
    score_ema_alignment, score_ema_dip_distance, score_ema_short,
    score_regime, score_regime_short, score_engulfing,
    score_macro_alignment, score_penalty_level,
    CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH,
)



def _extract_raw_indicators(l_vars):
    """
    Sinyal üretildiği andaki (locals() üzerinden) mevcut zaman dilimlerine ait 
    ham indikatör verilerini (RSI, ADX, Hacim) dinamik olarak toplar.
    Bu sayede 31 farklı strateji bloğunda kod tekrarı yapılmadan ham veriler 
    Telegram loglarına ve CSV raporlarına aktarılır.
    """
    import pandas as pd
    res = {}
    for prefix in ['last_15m', 'last_1h', 'last_4h', 'last_1d', 'last_1w']:
        if prefix in l_vars and isinstance(l_vars[prefix], pd.Series):
            tf = prefix.split('_')[1].upper()
            s = l_vars[prefix]
            if not pd.isna(s.get('RSI_14')): res[f'RSI_{tf}'] = round(s[f'RSI_{config.IND_RSI_LENGTH}'], 2)
            if not pd.isna(s.get('ADX_14')): res[f'ADX_{tf}'] = round(s['ADX_14'], 2)
            if not pd.isna(s.get('volume')): res[f'Vol_{tf}'] = round(s.get('volume', 0), 2)
    return res

def _get_consecutive_sl(symbol):
    """Penalty box'tan ardışık SL sayısını al (yoksa 0)."""
    try:
        from penalty_box import get_penalty_status
        status = get_penalty_status(symbol)
        return status.get('consecutive_sl', 0) if status else 0
    except Exception:
        return 0


# ════════════════════════════════════════
# 🔴 RED TEAM YARDIMCI FONKSİYONLARI
# ════════════════════════════════════════
def _is_darth_maul(candle):
    """RED-06: Darth Maul mum tespiti — flash crash kaos filtresi."""
    body = abs(candle['close'] - candle['open'])
    total_range = candle['high'] - candle['low']
    if total_range <= 0:
        return False
    return (body / total_range) < DARTH_MAUL_BODY_RATIO


def _is_meaningful_volume(volume, vol_sma_20, price, market="KRIPTO"):
    """RED-07: Hacim gerçekten anlamlı mı, yoksa ölü piyasada gürültü mü?"""
    if pd.isna(vol_sma_20) or vol_sma_20 <= 0:
        return False
    dollar_volume = volume * price
    min_dollar = MIN_DOLLAR_VOL_CRYPTO if market == "KRIPTO" else MIN_DOLLAR_VOL_BIST
    if dollar_volume < min_dollar:
        return False
    return volume > (1.5 * vol_sma_20)


def _adx_momentum_ok(df, last_row):
    """RED-02: ADX momentum kontrolü — gecikmeli ve olgunlaşmış trend filtresi."""
    adx_current = last_row.get('ADX_14')
    if adx_current is None or pd.isna(adx_current):
        return False
    if adx_current <= 25:
        return False
    if adx_current > ADX_TOO_LATE:
        return False  # Trend olgunlaşmış, geç kaldın
    if len(df) >= 2:
        adx_prev = df.iloc[-2].get('ADX_14')
        if adx_prev is not None and not pd.isna(adx_prev):
            if adx_current < adx_prev:
                return False  # ADX düşüyor, trend gücünü kaybediyor
    return True


def _apply_volume_sma_guard(df, vol_sma_20):
    """RED-01: Volume SMA(20) manipülasyona açık mı? SMA(50) ile çapraz kontrol."""
    if pd.isna(vol_sma_20) or vol_sma_20 <= 0:
        return vol_sma_20
    vol_sma_50 = df['volume'].rolling(50).mean().iloc[-1] if len(df) >= 50 else None
    if vol_sma_50 is not None and not pd.isna(vol_sma_50) and vol_sma_50 > 0:
        if vol_sma_20 < (vol_sma_50 * VOL_SMA_LONG_RATIO):
            return vol_sma_50 * 0.7  # Baskılanmış SMA'yı yukarı düzelt
    return vol_sma_20


def _is_unclosed_candle(df, timeframe="1d"):
    """RED-13: Son mum henüz kapanmamış mı kontrol et."""
    from datetime import timezone
    if not hasattr(df.index, 'tz') or df.index.tz is None:
        return False  # Timezone bilgisi yoksa güvenli tarafta kal
    now_utc = datetime.now(timezone.utc)
    last_ts = df.index[-1]
    if hasattr(last_ts, 'tzinfo') and last_ts.tzinfo is not None:
        last_ts_utc = last_ts.astimezone(timezone.utc)
    else:
        return False
    if timeframe == "1d":
        return last_ts_utc.date() == now_utc.date()
    elif timeframe == "4h":
        return (now_utc - last_ts_utc).total_seconds() < 4 * 3600
    elif timeframe == "1h":
        return (now_utc - last_ts_utc).total_seconds() < 3600
    return False


def _resolve_dual_signals(signals):
    """RED-17: Aynı varlıkta hem AL hem SAT sinyali varsa,
    en iyi R:R oranına sahip olanı tut, diğerini sil."""
    from collections import defaultdict
    ticker_groups = defaultdict(list)
    for sig in signals:
        ticker_groups[sig["ticker"]].append(sig)

    resolved = []
    for ticker, sigs in ticker_groups.items():
        directions = set(s["signal"] for s in sigs)
        if "AL" in directions and "SAT" in directions:
            # Çatışma var — en iyi R:R'yi seç
            best = None
            best_rr = -1
            for s in sigs:
                entry = s.get("entry_price", 0)
                sl = s.get("sl", entry)
                tp = s.get("tp", entry)
                risk = abs(entry - sl) if abs(entry - sl) > 0 else 1e-8
                reward = abs(tp - entry)
                rr = reward / risk
                if rr > best_rr:
                    best_rr = rr
                    best = s
            if best:
                logging.warning(
                    f"[RED-17] {ticker}: AL+SAT çatışması → '{best['signal']}' "
                    f"({best['strategy']}) kazandı (R:R={best_rr:.2f})"
                )
                resolved.append(best)
        else:
            resolved.extend(sigs)
    return resolved


def _apply_rr_filter(signals, min_rr=None):
    """FM-01: Kurumsal R:R Filtresi.
    Reward:Risk oranı minimum eşiğin altındaki sinyalleri çöpe atar.
    Ayı Avcısı (SHORT) stratejileri zaten kendi R:R kapısına sahip → atlanır.
    """
    if min_rr is None:
        min_rr = RR_MINIMUM
    filtered = []
    for sig in signals:
        # Conviction-scored sinyaller kendi R:R puanlamasına sahip, atla
        if sig.get('conviction_score') is not None:
            entry = sig.get("entry_price", 0)
            sl = sig.get("sl", entry)
            tp = sig.get("tp", entry)
            direction = sig.get("signal", "AL")
            if direction == "AL":
                risk = entry - sl
                reward = tp - entry
            else:
                risk = sl - entry
                reward = entry - tp
            rr = reward / risk if risk > 0 else 0
            sig['rr_ratio'] = round(rr, 2) if rr > 0 else 0
            filtered.append(sig)
            continue

        entry = sig.get("entry_price", 0)
        sl = sig.get("sl", entry)
        tp = sig.get("tp", entry)
        direction = sig.get("signal", "AL")

        if direction == "AL":
            risk = entry - sl
            reward = tp - entry
        else:  # SAT
            risk = sl - entry
            reward = entry - tp

        if risk <= 0:
            # SL yönü yanlış → sinyal zaten bozuk, geçir (DG-06 yakalayacak)
            filtered.append(sig)
            continue

        rr = reward / risk
        if rr >= min_rr:
            # R:R bilgisini sinyale ekle (Telegram mesajında kullanılacak)
            sig["rr_ratio"] = round(rr, 2)
            filtered.append(sig)
        else:
            logging.info(
                f"[FM-01 RR_VETO] {sig.get('ticker')} ({sig.get('strategy')}) → "
                f"R:R={rr:.2f} < {min_rr} → SİNYAL REDDEDİLDİ. "
                f"Entry={entry:.4f} SL={sl:.4f} TP={tp:.4f}"
            )
    return filtered


# ════════════════════════════════════════
# FM-04: REJİM YÖNETİCİSİ (Regime Manager)
# ════════════════════════════════════════
# İzin/Yasak Matrisi:
# BOĞA  → Tüm stratejiler serbest
# NÖTR  → Kırılım/Squeeze/VWAP engelli (sahte kırılım riski yüksek)
# AYI   → Sadece RS, Dip Avcılığı, OBV, Ayı Avcısı serbest

_BIST_BEAR_BLOCKED = {
    "BIST 2: MEGA TREND TAKİBİ",
    "BIST 3: KIRILIM AVCILIĞI",
    "BIST 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)",
    "BIST 7: VWAP KURUMSAL MIKNATISI",
}

_BIST_NEUTRAL_BLOCKED = {
    "BIST 3: KIRILIM AVCILIĞI",
    "BIST 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)",
}


def _get_bist_regime(xu100_daily):
    """XU100 endeksine bakarak BIST piyasa rejimini belirle.
    
    Returns:
        'BULL'    → EMA20 > EMA50, fiyat EMA20 üstünde
        'BEAR'    → Fiyat EMA20 ve EMA50 altında
        'NEUTRAL' → Aradaki her şey
    """
    if xu100_daily is None or len(xu100_daily) < 50:
        return "NEUTRAL"  # Veri yetersiz → güvenli mod
    try:
        close = xu100_daily['close']
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        last_close = float(close.iloc[-1])
        last_ema20 = float(ema20.iloc[-1])
        last_ema50 = float(ema50.iloc[-1])

        if last_close > last_ema20 and last_ema20 > last_ema50:
            return "BULL"
        elif last_close < last_ema20 and last_close < last_ema50:
            return "BEAR"
        else:
            return "NEUTRAL"
    except Exception as e:
        logging.warning(f"[FM-04 Regime] XU100 rejim hesaplanamadı: {e}")
        return "NEUTRAL"


def _apply_regime_filter(signals, regime, market="BIST"):
    """FM-04: Rejime göre uygun olmayan stratejileri filtrele."""
    if regime == "BULL":
        return signals  # Boğa → hepsine izin

    if market == "BIST":
        blocked = _BIST_BEAR_BLOCKED if regime == "BEAR" else _BIST_NEUTRAL_BLOCKED
    else:
        return signals  # Kripto/Emtia rejim filtresi başka yerde (BTC/DXY)

    filtered = []
    for sig in signals:
        # Conviction-scored sinyaller rejim puanını zaten içeriyor
        if sig.get('conviction_score') is not None:
            filtered.append(sig)
            continue
        strat = sig.get("strategy", "")
        if strat in blocked:
            logging.info(
                f"[FM-04 REGIME_BLOCK] {sig.get('ticker')} ({strat}) → "
                f"Rejim={regime}, strateji ENGELLENDİ."
            )
        else:
            filtered.append(sig)
    return filtered


def _has_absolute_hourly_volume(volume, price, market="KRIPTO"):
    """AM-03: Saatlik mutlak dolar/TL hacim eşiği.
    SMA20'nin 5 katı bile olsa, mutlak hacim düşükse sahte kırılım."""
    dollar_vol = volume * price
    if market == "KRIPTO":
        return dollar_vol >= MIN_HOURLY_DOLLAR_VOL_CRYPTO
    else:
        return dollar_vol >= MIN_HOURLY_TL_VOL_BIST


def _is_funding_safe_for_short(funding_rate):
    """AM-04: Fonlama Vampiri Kalkanı.
    Negatif fonlama = herkes zaten short → balina likidasyonu riski.
    Returns: True (short güvenli), False (short YASAK)
    """
    if funding_rate is None:
        return False  # Veri yoksa short açma
    return funding_rate >= FUNDING_SHORT_BLOCK_THRESHOLD


def _is_in_liquidity_window():
    """AM-06: Likidite Saatleri Zaman Kilidi.
    DXY/Emtia korelasyon stratejileri sadece TSİ 15:30-20:00 arasında tetiklenir.
    Asya seansı hacimsiz yataylıklara kanmayı engeller.
    """
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    start = dt_time(LIQUIDITY_WINDOW_START_HOUR, LIQUIDITY_WINDOW_START_MIN)
    end = dt_time(LIQUIDITY_WINDOW_END_HOUR, LIQUIDITY_WINDOW_END_MIN)
    return start <= now.time() <= end


# ════════════════════════════════════════
# 1. BIST 100 STRATEJİ MODÜLÜ
# ════════════════════════════════════════
def analyze_strategies_bist(symbol, df_1d, df_4h, df_1h, xu100_down=False, xu100_daily=None, metrics_collector=None):
    signals = []

    # Pandas Mutability koruması: kaynak DataFrame'leri kirletme
    df_1d = df_1d.copy()
    df_4h = df_4h.copy()
    df_1h = df_1h.copy()

    df_1d.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_1d.ta.ema(length=config.IND_EMA_FAST, append=True)
    df_1d.ta.ema(length=config.IND_EMA_21, append=True)
    df_1d.ta.sma(length=config.IND_SMA_SLOW, append=True)
    df_1d.ta.sma(length=config.IND_SMA_TREND, append=True)
    df_1d.ta.bbands(length=config.IND_BBANDS_LENGTH, std=config.IND_BBANDS_STD, append=True)
    df_1d.ta.atr(length=config.IND_ATR_LENGTH, append=True)

    month_high = df_1d['high'].tail(30).max() if len(df_1d) >= 30 else df_1d['high'].max()

    df_4h.ta.adx(length=config.IND_ADX_LENGTH, append=True)
    df_4h.ta.ema(length=config.IND_EMA_FAST, append=True)
    df_4h.ta.ema(length=config.IND_EMA_21, append=True)

    df_1h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_1h.ta.ema(length=config.IND_EMA_FAST, append=True)
    df_1h.ta.ema(length=config.IND_EMA_21, append=True)
    df_1h['vol_sma_20'] = ta.sma(df_1h['volume'], length=config.IND_VOL_SMA_LENGTH)

    if len(df_1d) < 2 or len(df_4h) < 2 or len(df_1h) < 3:
        return signals

    last_1d = df_1d.iloc[-1]
    last_4h = df_4h.iloc[-1]
    last_1h = df_1h.iloc[-1]
    prev_1h = df_1h.iloc[-2]
    current_price = last_1h['close']

    atr_val = last_1d.get('ATRr_14', last_1d.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
    # RED-08: ATR Cap — flash crash'te devasa stop mesafesini engelle
    raw_sl_dist = ATR_MULTIPLIER_BIST * atr_val
    dynamic_sl_dist = max(
        min(raw_sl_dist, current_price * ATR_CAP_BIST),  # Üst sınır
        current_price * 0.03  # Alt sınır
    )
    sl_pct = (dynamic_sl_dist / current_price) * 100

    # V3.3: Piyasa rejimi (Conviction Scoring için)
    bist_regime = _get_bist_regime(xu100_daily)

    if metrics_collector is not None:
        metrics_collector[symbol] = {
            "Symbol": symbol,
            "Market": "BIST",
            "Price": current_price,
            "1D RSI": round(last_1d.get("RSI_14", 0), 2) if pd.notna(last_1d.get("RSI_14")) else None,
            "4H ADX": round(last_4h.get("ADX_14", 0), 2) if pd.notna(last_4h.get("ADX_14")) else None,
            "1H RSI": round(last_1h.get("RSI_14", 0), 2) if pd.notna(last_1h.get("RSI_14")) else None,
            "1D SMA 50": round(last_1d.get("SMA_50", 0), 2) if pd.notna(last_1d.get("SMA_50")) else None,
            "1D SMA 200": round(last_1d.get("SMA_200", 0), 2) if pd.notna(last_1d.get("SMA_200")) else None,
            "Trend": "Bullish" if last_1d.get("EMA_8", 0) > last_1d.get("EMA_21", float('inf')) else "Bearish",
            "1H Volume": last_1h.get("volume")
        }

    # BIST 1: DİP AVCILIĞI (Turnaround)
    if not pd.isna(last_1d.get('RSI_14')):
        if last_1d[f'RSI_{config.IND_RSI_LENGTH}'] < 35:
            if not pd.isna(last_1h.get('RSI_14')) and not pd.isna(prev_1h.get('RSI_14')) and not pd.isna(last_1h.get('EMA_8')) and not pd.isna(last_1h.get('vol_sma_20')):
                if last_1h['close'] > last_1h['EMA_8'] and prev_1h['close'] <= prev_1h['EMA_8'] and last_1h['close'] > last_1h['open']:
                    # AM-01: Engulfing momentum onayı — ölü kedi sıçraması filtresi
                    if not check_bullish_engulfing_momentum(df_1h):
                        pass  # Yeşil mum önceki kırmızıyı yutmadı → sahte hareket
                    else:
                        # RED-01: Volume SMA manipülasyon koruması
                        guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                        if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                            if last_1h[f'RSI_{config.IND_RSI_LENGTH}'] > prev_1h[f'RSI_{config.IND_RSI_LENGTH}']:
                                sl = current_price - dynamic_sl_dist
                                tp = last_1d.get('EMA_21', current_price * 1.05)
                                _rr = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                                _scores = build_dip_scores(
                                    rsi_daily=last_1d[f'RSI_{config.IND_RSI_LENGTH}'], rsi_hourly=last_1h[f'RSI_{config.IND_RSI_LENGTH}'], rsi_prev=prev_1h[f'RSI_{config.IND_RSI_LENGTH}'],
                                    price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'),
                                    volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                                    rr=_rr, has_engulfing=True, regime=bist_regime,
                                    macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                                )
                                _conv = calculate_conviction(_scores)
                                if _conv.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                        "ticker": symbol, "market": "BIST", "strategy": "BIST 1: DİP AVCILIĞI", "signal": "AL",
                                        "entry_price": current_price, "sl": sl, "tp": tp,
                                        "conviction_score": _conv.total_score, "conviction_grade": _conv.grade, "conviction_details": _conv.component_scores,
                                        "position_size_pct": _conv.position_size_pct,
                                        "indicators": {"RSI_1G": round(last_1d.get("RSI_14", 0), 2), "RSI_1S": round(last_1h.get("RSI_14", 0), 2)},
                                        "reason": f"1G RSI<35 + Engulfing Onaylı Turnaround. (ATR Stop: -%{sl_pct:.1f})" + _conv.to_reason_suffix()
                                    })

    # BIST 2: TREND TAKİBİ
    if not pd.isna(last_4h.get('ADX_14')) and not pd.isna(last_4h.get('EMA_8')) and not pd.isna(last_4h.get('EMA_21')):
        # RED-02: ADX momentum kontrolü — gecikmeli ve olgunlaşmış trend filtresi
        if _adx_momentum_ok(df_4h, last_4h) and last_4h['EMA_8'] > last_4h[f'EMA_{config.IND_EMA_21}']:
            if not pd.isna(last_1h.get('EMA_21')):
                if last_1h['low'] <= last_1h[f'EMA_{config.IND_EMA_21}'] and last_1h['close'] > last_1h[f'EMA_{config.IND_EMA_21}'] and last_1h['close'] > last_1h['open']:
                    # AM-01: Engulfing momentum onayı — pullback'te gerçek dönüş mü?
                    if check_bullish_engulfing_momentum(df_1h):
                        sl = current_price - dynamic_sl_dist
                        _tp2 = current_price * 1.10
                        _rr2 = abs(_tp2 - current_price) / max(abs(current_price - sl), 1e-8)
                        _adx_prev2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                        _scores2 = build_trend_scores(
                            adx=last_4h['ADX_14'], adx_prev=_adx_prev2,
                            price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=None,
                            rsi=last_1h.get('RSI_14'), rsi_prev=prev_1h.get('RSI_14') if len(df_1h) >= 2 else None,
                            volume=last_1h['volume'], vol_sma=last_1h.get('vol_sma_20', 0), dollar_vol=last_1h['volume'] * current_price,
                            rr=_rr2, has_engulfing=True, regime=bist_regime,
                            macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                        )
                        _conv2 = calculate_conviction(_scores2)
                        if _conv2.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                "ticker": symbol, "market": "BIST", "strategy": "BIST 2: TREND TAKİBİ", "signal": "AL",
                                "entry_price": current_price, "sl": sl, "tp": _tp2,
                                "conviction_score": _conv2.total_score, "conviction_grade": _conv2.grade, "conviction_details": _conv2.component_scores,
                                "position_size_pct": _conv2.position_size_pct,
                                "indicators": {"ADX_4S": round(last_4h.get("ADX_14", 0), 2), "RSI_1S": round(last_1h.get("RSI_14", 0), 2)},
                                "reason": f"4S ADX>25 Trend + Engulfing Momentum. 1S EMA21 pullback. (ATR Stop: -%{sl_pct:.1f})" + _conv2.to_reason_suffix()
                            })

    # BIST 3: KIRILIM VE MOMENTUM
    bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
    bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
    bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]

    if bb_upper_col and bb_lower_col and bb_mid_col:
        bbu = last_1d[bb_upper_col[0]]
        bbl = last_1d[bb_lower_col[0]]
        bbm = last_1d[bb_mid_col[0]]

        bb_width = (bbu - bbl) / bbm if not math.isclose(float(bbm), 0.0, abs_tol=1e-8) else 1
        if bb_width < 0.15:
            if current_price > month_high:
                # RED-05: Gap-Up filtresi — sabah gap'i ile sahte kırılım engelle
                prev_close = df_1d.iloc[-2]['close'] if len(df_1d) >= 2 else current_price
                gap_pct = abs(last_1h['open'] - prev_close) / max(prev_close, 1e-8) * 100
                if gap_pct > GAP_THRESHOLD_PCT:
                    pass  # Gap > %3 → sahte kırılım riski, sinyal üretme
                elif not pd.isna(last_1h.get('vol_sma_20')):
                    guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                    if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                        # AM-03: Mutlak hacim eşiği — SMA'nın 5 katı bile olsa TL karşılığı yeterli mi?
                        if _has_absolute_hourly_volume(last_1h['volume'], current_price, "BIST"):
                            if not xu100_down:
                                now = datetime.now(ZoneInfo("Europe/Istanbul"))
                                if now.time() >= dt_time(10, 30):
                                    sl = current_price - dynamic_sl_dist
                                    _tp3 = current_price * 1.10
                                    _rr3 = abs(_tp3 - current_price) / max(abs(current_price - sl), 1e-8)
                                    _scores3 = build_breakout_scores(
                                        bb_width=bb_width, price=current_price,
                                        ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                                        volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                                        rr=_rr3, regime=bist_regime,
                                        macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                                    )
                                    _conv3 = calculate_conviction(_scores3)
                                    if _conv3.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                        signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                            "ticker": symbol, "market": "BIST", "strategy": "BIST 3: KIRILIM AVCILIĞI", "signal": "AL",
                                            "entry_price": current_price, "sl": sl, "tp": _tp3,
                                            "conviction_score": _conv3.total_score, "conviction_grade": _conv3.grade, "conviction_details": _conv3.component_scores,
                                            "position_size_pct": _conv3.position_size_pct,
                                            "reason": f"Günlükte daralma, hacimli direnç kırılımı + Mutlak TL hacmi onaylı. (ATR Stop: -%{sl_pct:.1f})" + _conv3.to_reason_suffix()
                                        })

    # BIST 4: KESKİN NİŞANCI (SMC / Likidite Avı ve OTE)
    htf_bias = sniper_get_htf_bias(df_1d)

    if htf_bias == 1:
        swing_lows = sniper_find_swing_points(df_4h, point_type="low")
        swing_highs = sniper_find_swing_points(df_4h, point_type="high")

        sweep_ok, sweep_low = sniper_detect_sweep(df_4h, swing_lows, point_type="low")
        if sweep_ok:
            msb_ok, msb_high, msb_idx = sniper_detect_msb(df_4h, swing_highs, point_type="high")
            if msb_ok:
                # AM-05: Gövde-bazlı OTE + minimum dalga amplitüdü kontrolü
                sweep_idx = swing_lows[-1][0] if swing_lows else None
                ote_top, ote_bottom = sniper_calculate_ote_body(df_4h, sweep_idx, msb_idx, direction="long")
                if ote_top > 0 and ote_bottom > 0 and ote_bottom <= current_price <= ote_top:
                    # RED-07: Anlamlı hacim kontrolü (tutarlılık: BIST 1/3/7 ile aynı)
                    if not pd.isna(last_1h.get('vol_sma_20')):
                        guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                        if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                            has_fvg, fvg_low, fvg_high = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bullish")

                            sl = sweep_low * 0.995
                            tp = msb_high * 1.05
                            fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
                            _rr4 = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                            _scores4 = build_breakout_scores(
                                bb_width=None, price=current_price,
                                ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                                volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                                rr=_rr4, regime=bist_regime,
                                macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                            )
                            _conv4 = calculate_conviction(_scores4)
                            if _conv4.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                    "ticker": symbol, "market": "BIST",
                                    "strategy": "BIST 4: KESKİN NİŞANCI (OTE)", "signal": "AL",
                                    "entry_price": current_price, "sl": sl, "tp": tp,
                                    "conviction_score": _conv4.total_score, "conviction_grade": _conv4.grade, "conviction_details": _conv4.component_scores,
                                    "position_size_pct": _conv4.position_size_pct,
                                    "reason": (
                                        f"🎯 SMC Kurulum (Gövde Fibo){fvg_label}\n"
                                        f"🧹 Likidite: Eski dip ({sweep_low:.2f}) temizlendi.\n"
                                        f"📐 MSB: Yapı kırılımı ({msb_high:.2f}) onaylı.\n"
                                        f"🎣 OTE Bölgesi (Gövde): {ote_bottom:.2f} - {ote_top:.2f}\n"
                                        f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
                                    ) + _conv4.to_reason_suffix()
                                })

    # BIST 5: VOLATİLİTE SIKIŞMASI (Squeeze)
    squeeze_fired, sq_dir, sq_candle = detect_squeeze(df_1d)
    if squeeze_fired and sq_dir == "up" and not xu100_down:
        # RED-07: Anlamlı hacim kontrolü (tutarlılık: BIST 1/3/7 ile aynı)
        if not pd.isna(last_1h.get('vol_sma_20')):
            guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
            if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
                ema_fallback = last_1d.get('EMA_21', last_1d.get('EMA_8', current_price * 0.95))
                sl = min(sq_mid, ema_fallback) if not pd.isna(ema_fallback) else sq_mid
                _tp5u = current_price * 1.15
                _rr5u = abs(_tp5u - current_price) / max(abs(current_price - sl), 1e-8)
                _scores5u = build_breakout_scores(
                    bb_width=None, price=current_price,
                    ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                    volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                    rr=_rr5u, regime=bist_regime,
                    macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                )
                _conv5u = calculate_conviction(_scores5u)
                if _conv5u.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                        "ticker": symbol, "market": "BIST",
                        "strategy": "BIST 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)", "signal": "AL",
                        "entry_price": current_price, "sl": sl, "tp": _tp5u,
                        "conviction_score": _conv5u.total_score, "conviction_grade": _conv5u.grade, "conviction_details": _conv5u.component_scores,
                        "position_size_pct": _conv5u.position_size_pct,
                        "reason": (
                            f"🗜️ Squeeze Patlaması!\n"
                            f"BB(20,2) Keltner(20,1.5) içinden yukarı kırıldı.\n"
                            f"Hacimli yeşil mum ile BB üst bandı aşıldı.\n"
                            f"SL: Kırılım mumunun %50'si ({sl:.2f})"
                        ) + _conv5u.to_reason_suffix()
                    })
    elif squeeze_fired and sq_dir == "down":
        # RED-07: Anlamlı hacim kontrolü (tutarlılık: BIST 1/3/7 ile aynı)
        if not pd.isna(last_1h.get('vol_sma_20')):
            guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
            if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
                ema_fallback = last_1d.get('EMA_21', last_1d.get('EMA_8', current_price * 1.05))
                sl = max(sq_mid, ema_fallback) if not pd.isna(ema_fallback) else sq_mid
                _tp5d = current_price * 0.85
                _rr5d = abs(current_price - _tp5d) / max(abs(sl - current_price), 1e-8)
                _scores5d = build_breakout_scores(
                    bb_width=None, price=current_price,
                    ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                    volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                    rr=_rr5d, regime=bist_regime,
                    macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                )
                _conv5d = calculate_conviction(_scores5d)
                if _conv5d.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                        "ticker": symbol, "market": "BIST",
                        "strategy": "BIST 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)", "signal": "SAT",
                        "entry_price": current_price, "sl": sl, "tp": _tp5d,
                        "conviction_score": _conv5d.total_score, "conviction_grade": _conv5d.grade, "conviction_details": _conv5d.component_scores,
                        "position_size_pct": _conv5d.position_size_pct,
                        "reason": (
                            f"🗜️ Squeeze Aşağı Patlaması!\n"
                            f"BB(20,2) Keltner(20,1.5) içinden aşağı kırıldı.\n"
                            f"Hacimli kırmızı mum ile BB alt bandı kırıldı.\n"
                            f"SL: Kırılım mumunun %50'si ({sl:.2f})"
                        ) + _conv5d.to_reason_suffix()
                    })

    # BIST 6: GÖRECELİ GÜÇ RADARI (RS)
    if xu100_daily is not None:
        rs_strong, rs_trend_up, idx_stressed, idx_recovering = calculate_relative_strength(df_1d, xu100_daily)
        # RED-14: İmkansız AND gevşetmesi — endeks stres dışındaysa da kabul et
        if rs_strong and rs_trend_up and (idx_recovering or not idx_stressed):
            # RED-07: Anlamlı hacim kontrolü (tutarlılık: BIST 1/3/7 ile aynı)
            if not pd.isna(last_1h.get('vol_sma_20')):
                guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                    swing_lows_rs = sniper_find_swing_points(df_1d, point_type="low", neighbors=2)
                    if swing_lows_rs:
                        sl = swing_lows_rs[-1][1] * 0.98
                    else:
                        sl = current_price * 0.95
                    _tp6 = current_price * 1.12
                    _rr6 = abs(_tp6 - current_price) / max(abs(current_price - sl), 1e-8)
                    _scores6 = build_trend_scores(
                        adx=None, adx_prev=None,
                        price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                        rsi=last_1h.get('RSI_14'), rsi_prev=prev_1h.get('RSI_14') if len(df_1h) >= 2 else None,
                        volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                        rr=_rr6, has_engulfing=False, regime=bist_regime,
                        macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                    )
                    _conv6 = calculate_conviction(_scores6)
                    if _conv6.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                        signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                            "ticker": symbol, "market": "BIST",
                            "strategy": "BIST 6: GÖRECELİ GÜÇ RADARI (RS)", "signal": "AL",
                            "entry_price": current_price, "sl": sl, "tp": _tp6,
                            "conviction_score": _conv6.total_score, "conviction_grade": _conv6.grade, "conviction_details": _conv6.component_scores,
                            "position_size_pct": _conv6.position_size_pct,
                            "reason": (
                                f"🏋️ Endekse Kafa Tutan Hisse!\n"
                                f"RS Çizgisi > 50G SMA (Güçlü ✅)\n"
                                f"Endeks toparlandı, EMA8 üzerine çıktı.\n"
                                f"Bu hisse endeks düşerken düşmedi → Kurumsal birikim."
                            ) + _conv6.to_reason_suffix()
                        })

    # BIST 7: VWAP KURUMSAL MIKNATISI
    sma_50 = last_1d.get('SMA_50')
    sma_200 = last_1d.get('SMA_200')
    is_bear_regime = (not pd.isna(sma_50) and not pd.isna(sma_200) and current_price < sma_50 and current_price < sma_200)
    ema_21_daily = last_1d.get('EMA_21')
    mtf_trend_down = (not pd.isna(ema_21_daily) and last_1d['close'] < ema_21_daily)
    macro_gravity_ok = not xu100_down

    if not is_bear_regime and not mtf_trend_down and macro_gravity_ok:
        vwap_val = calculate_anchored_vwap(df_1h, anchor_type="weekly")
        if vwap_val is not None:
            bounce_ok, wick_low = detect_vwap_bounce(df_1h, vwap_val)
            if bounce_ok and wick_low is not None:
                # RED-01: Volume SMA manipülasyon koruması
                vol_sma_20 = last_1h.get('vol_sma_20')
                guarded_vol_sma = _apply_volume_sma_guard(df_1h, vol_sma_20)
                if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                    sl = wick_low * 0.995
                    _tp7 = current_price * 1.06
                    _rr7 = abs(_tp7 - current_price) / max(abs(current_price - sl), 1e-8)
                    _scores7 = build_trend_scores(
                        adx=None, adx_prev=None,
                        price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                        rsi=last_1h.get('RSI_14'), rsi_prev=prev_1h.get('RSI_14') if len(df_1h) >= 2 else None,
                        volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                        rr=_rr7, has_engulfing=False, regime=bist_regime,
                        macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                    )
                    _conv7 = calculate_conviction(_scores7)
                    if _conv7.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                        signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                            "ticker": symbol, "market": "BIST",
                            "strategy": "BIST 7: VWAP KURUMSAL MIKNATISI", "signal": "AL",
                            "entry_price": current_price, "sl": sl, "tp": _tp7,
                            "conviction_score": _conv7.total_score, "conviction_grade": _conv7.grade, "conviction_details": _conv7.component_scores,
                            "position_size_pct": _conv7.position_size_pct,
                            "reason": (
                                f"⚓ VWAP Bounce (Kurumsal Mıknatıs) + 4 Kapı Zırhı!\n"
                                f"✅ Rejim: Boğa | ✅ Trend: Uyumlu | ✅ Endeks: Güvenli\n"
                                f"Anchored VWAP: {vwap_val:.2f} (1.5x Hacimle Sıçradı)\n"
                                f"SL: Fitil ucunun altı ({sl:.2f}) — Dar stop."
                            ) + _conv7.to_reason_suffix()
                        })

    # BIST 8: SESSİZ BİRİKİM RADARI (OBV)
    obv_ok, obv_box_high, obv_box_low = detect_obv_accumulation(df_1d, max_change_pct=7.0)
    if obv_ok and obv_box_high is not None:
        # AM-02: CMF Wash-Trade Kalkanı — OBV pozitif ama para çıkıyor mu?
        if is_cmf_wash_trade(df_1d):
            logging.info(f"[AM-02] {symbol}: OBV birikim pozitif ama CMF negatif → Wash Trade şüphesi, sinyal üretilmedi.")
        else:
            # RED-12: SL kutu ortasına indir — tepeden retest'te patlamayı engelle
            sl = (obv_box_high + obv_box_low) / 2
            cmf_val = calculate_cmf(df_1d)
            cmf_label = f"CMF: {cmf_val:.3f} (Temiz ✅)" if cmf_val is not None else "CMF: N/A"
            _tp8 = current_price * 1.12
            _rr8 = abs(_tp8 - current_price) / max(abs(current_price - sl), 1e-8)
            _scores8 = build_dip_scores(
                rsi_daily=last_1d.get('RSI_14', 50), rsi_hourly=last_1h.get('RSI_14', 50),
                rsi_prev=prev_1h.get('RSI_14', 50) if len(df_1h) >= 2 else 50,
                price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'),
                volume=last_1h.get('volume', 0), vol_sma=last_1h.get('vol_sma_20', 0),
                dollar_vol=last_1h.get('volume', 0) * current_price,
                rr=_rr8, has_engulfing=False, regime=bist_regime,
                macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
            )
            _conv8 = calculate_conviction(_scores8)
            if _conv8.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "BIST",
                    "strategy": "BIST 8: SESSİZ BİRİKİM RADARI (OBV)", "signal": "AL",
                    "entry_price": current_price, "sl": sl, "tp": _tp8,
                    "conviction_score": _conv8.total_score, "conviction_grade": _conv8.grade, "conviction_details": _conv8.component_scores,
                    "position_size_pct": _conv8.position_size_pct,
                    "reason": (
                        f"🕵️ Sessiz Birikim + CMF Onaylı!\n"
                        f"20 gün yatay kutu: {obv_box_low:.2f} - {obv_box_high:.2f}\n"
                        f"OBV sürekli yeni tepeler yapıyor + {cmf_label}\n"
                        f"Kutu direnci hacimli kırıldı → Ralli başlıyor."
                    ) + _conv8.to_reason_suffix()
                })

    return signals


# ════════════════════════════════════════
# BIST 9: ZAMAN KAFESİ (ORB)
# ════════════════════════════════════════
def scan_orb_bist(symbol, df_15m):
    """BIST 9: ZAMAN KAFESİ (ORB) taraması."""
    signals = []
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if now.hour < config.BIST9_TRADE_START_HOUR or (now.hour >= config.BIST9_TRADE_END_HOUR and now.minute > config.BIST9_TRADE_END_MINUTE):
        return signals

    cage_high, cage_low, cage_mid, today_vwap = calculate_orb_cage(df_15m)
    if cage_high is None or today_vwap is None:
        return signals

    last = df_15m.iloc[-1]
    current_price = float(last['close'])
    tp_range = cage_high - cage_low
    
    # 1. Kafes Genişlik Sınırı
    cage_width_pct = (tp_range / cage_low) * 100
    if cage_width_pct > config.BIST9_MAX_CAGE_WIDTH_PCT:
        return signals  # Hard Block: Kafes çok geniş

    # 2. Hacim Bilgisi (Yetersiz olsa bile soft-score ile değerlendirilecek, Hard Block kaldırıldı)
    candle_time = df_15m.index[-1]
    rvol = calculate_time_specific_rvol(df_15m, target_hour=candle_time.hour, target_minute=candle_time.minute, period=config.BIST9_RVOL_PERIOD)
    current_vol = last['volume']

    # 3. EMA Hesaplaması (Soft-score içinde değerlendirilecek)
    df = df_15m.copy()
    df.ta.ema(length=config.BIST9_EMA_LENGTH, append=True)
    ema21 = float(df[f'EMA_{config.BIST9_EMA_LENGTH}'].iloc[-1])
    if math.isnan(ema21):
        return signals

    # 4. Endeks Korelasyonu
    bist100_trend = get_bist100_trend()

    # LONG Kırılım (Candle Close > Kafes, VWAP ve EMA21 onayları soft-score'a devredildi)
    if current_price > cage_high and last['close'] > last['open']:
        if bist100_trend != "BULL":
             return signals  # Hard Block: Endeks Bullish değil
             
        _sl9u = cage_mid
        _tp9u = current_price + tp_range
        _rr9u = abs(_tp9u - current_price) / max(abs(current_price - _sl9u), 1e-8)
        _scores9u = build_breakout_scores(
            bb_width=None, price=current_price,
            ema_fast=ema21, ema_mid=today_vwap, ema_slow=None,
            volume=current_vol, vol_sma=rvol, dollar_vol=current_vol * current_price,
            rr=_rr9u, regime="BULL",
            macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
        )
        _conv9u = calculate_conviction(_scores9u)
        if _conv9u.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                "ticker": symbol, "market": "BIST",
                "strategy": "BIST 9: ZAMAN KAFESİ (ORB)", "signal": "AL", "is_day_trade": True,
                "entry_price": current_price, "sl": cage_mid, "tp": _tp9u,
                "conviction_score": _conv9u.total_score, "conviction_grade": _conv9u.grade, "conviction_details": _conv9u.component_scores,
                "position_size_pct": _conv9u.position_size_pct,
                "reason": (
                    f"⏱️ Açılış Kafesi Kırılımı (ORB)\n"
                    f"📊 Kafes: {cage_low:.2f} - {cage_high:.2f} (Genişlik: %{cage_width_pct:.2f})\n"
                    f"📍 Fiyat: {current_price:.2f} TL (EMA21: {ema21:.2f}, VWAP: {today_vwap:.2f})\n"
                    f"📈 Hacim: {current_vol:,.0f} (Ort. RVOL: {rvol:,.0f}, Oran: {current_vol/max(rvol, 1e-8):.2f}x)\n"
                    f"🎯 Hedef: +{tp_range:.2f} TL\n"
                    f"⚠️ DAY TRADE: 17:55'te otomatik kapatılır."
                ) + _conv9u.to_reason_suffix()
            })
    # SHORT Kırılım (Candle Close < Kafes, VWAP ve EMA21 onayları soft-score'a devredildi)
    elif current_price < cage_low and last['close'] < last['open']:
        if bist100_trend == "BULL":
             return signals  # Hard Block: Endeks Bullish iken short açma
             
        _sl9d = cage_mid
        _tp9d = current_price - tp_range
        _rr9d = abs(tp_range) / max(abs(cage_mid - current_price), 1e-8)
        _scores9d = build_breakout_scores(
            bb_width=None, price=current_price, ema_fast=today_vwap, ema_mid=ema21, ema_slow=None,
            volume=current_vol, vol_sma=rvol, dollar_vol=current_vol * current_price,
            rr=_rr9d, regime="BEAR", macro_aligned=True,
            consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
        )
        _conv9d = calculate_conviction(_scores9d)
        if _conv9d.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                "ticker": symbol, "market": "BIST",
                "strategy": "BIST 9: ZAMAN KAFESİ (ORB)", "signal": "SAT", "is_day_trade": True,
                "entry_price": current_price, "sl": cage_mid, "tp": _tp9d,
                "conviction_score": _conv9d.total_score, "conviction_grade": _conv9d.grade, "conviction_details": _conv9d.component_scores,
                "position_size_pct": _conv9d.position_size_pct,
                "reason": (
                    f"⏱️ Açılış Kafesi Aşağı Kırılımı (ORB)\n"
                    f"📊 Kafes: {cage_low:.2f} - {cage_high:.2f} (Genişlik: %{cage_width_pct:.2f})\n"
                    f"📍 Fiyat: {current_price:.2f} TL (EMA21: {ema21:.2f}, VWAP: {today_vwap:.2f})\n"
                    f"📈 Hacim: {current_vol:,.0f} (Ort. RVOL: {rvol:,.0f}, Oran: {current_vol/max(rvol, 1e-8):.2f}x)\n"
                    f"🎯 Hedef: -{tp_range:.2f} TL\n"
                    f"⚠️ DAY TRADE: 17:55'te otomatik kapatılır."
                ) + _conv9d.to_reason_suffix()
            })

    return signals


# ════════════════════════════════════════
# 2. KRİPTO STRATEJİ MODÜLÜ
# ════════════════════════════════════════
def analyze_strategies_crypto(symbol, df_1d, df_4h, btc_ok=False, btc_sniper_bias=0, metrics_collector=None):
    signals = []

    if len(df_1d) < 50 or len(df_4h) < 20:
        return signals

    # Pandas Mutability koruması: kaynak DataFrame'leri kirletme
    df_1d = df_1d.copy()
    df_4h = df_4h.copy()

    df_1d.ta.ema(length=config.IND_EMA_MID, append=True)
    df_1d.ta.ema(length=config.IND_EMA_SLOW, append=True)
    df_1d.ta.bbands(length=config.IND_BBANDS_LENGTH, std=config.IND_BBANDS_STD, append=True)

    df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_4h.ta.ema(length=config.IND_EMA_MID, append=True)
    df_4h.ta.ema(length=config.IND_EMA_SLOW, append=True)
    df_4h.ta.adx(length=config.IND_ADX_LENGTH, append=True)
    df_4h.ta.atr(length=config.IND_ATR_LENGTH, append=True)
    df_4h['vol_sma_20'] = ta.sma(df_4h['volume'], length=config.IND_VOL_SMA_LENGTH)

    last_1d = df_1d.iloc[-1]
    last_4h = df_4h.iloc[-1]
    current_price = last_4h['close']

    if metrics_collector is not None:
        metrics_collector[symbol] = {
            "Symbol": symbol,
            "Market": "KRIPTO",
            "Price": current_price,
            "1D RSI": round(last_1d.get("RSI_14", 0), 2) if pd.notna(last_1d.get("RSI_14")) else None,
            "4H ADX": round(last_4h.get("ADX_14", 0), 2) if pd.notna(last_4h.get("ADX_14")) else None,
            "1H RSI": None,
            "1D SMA 50": round(last_1d.get("EMA_50", 0), 2) if pd.notna(last_1d.get("EMA_50")) else None,
            "1D SMA 200": None,
            "Trend": "Bullish" if last_1d.get("EMA_20", 0) > last_1d.get("EMA_50", float('inf')) else "Bearish",
            "1H Volume": last_4h.get("volume")
        }


    # KRİPTO 1: LİKİDASYON VE DİP AVCILIĞI
    if not is_weekend_fakeout_time():
        if not pd.isna(last_4h.get('RSI_14')) and not pd.isna(last_4h.get('EMA_20')) and not pd.isna(last_4h.get('vol_sma_20')):
            div_found, _, _, _, _ = detect_bullish_divergence(df_4h)
            if div_found:
                # RED-07: Anlamlı hacim kontrolü + RED-06: Darth Maul filtresi
                guarded_vol_sma = _apply_volume_sma_guard(df_4h, last_4h['vol_sma_20'])
                if _is_meaningful_volume(last_4h['volume'], guarded_vol_sma, current_price, "KRIPTO"):
                    if not _is_darth_maul(last_4h):
                        if current_price > last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price > last_4h['open']:
                            oi_crash = fetch_crypto_oi_crash(symbol)
                            if oi_crash:
                                lowest_wick = last_4h['low']
                                sl = lowest_wick * 0.99
                                tp = current_price * 1.15
                                _rr_c1 = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                                _prev_4h = df_4h.iloc[-2] if len(df_4h) >= 2 else last_4h
                                _scores_c1 = build_dip_scores(
                                    rsi_daily=last_4h.get('RSI_14', 50), rsi_hourly=last_4h.get('RSI_14', 50),
                                    rsi_prev=_prev_4h.get('RSI_14', 50),
                                    price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'),
                                    volume=last_4h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_4h['volume'] * current_price,
                                    rr=_rr_c1, has_engulfing=False, regime="BULL",
                                    macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
                                )
                                _conv_c1 = calculate_conviction(_scores_c1)
                                if _conv_c1.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                        "ticker": symbol, "market": "KRIPTO", "strategy": "KRİPTO 1: LİKİDASYON VE DİP AVCILIĞI", "signal": "AL",
                                        "entry_price": current_price, "sl": sl, "tp": tp,
                                        "conviction_score": _conv_c1.total_score, "conviction_grade": _conv_c1.grade, "conviction_details": _conv_c1.component_scores,
                                        "position_size_pct": _conv_c1.position_size_pct,
                                        "indicators": {"RSI_4S": round(last_4h.get("RSI_14", 0), 2)},
                                        "reason": f"Pozitif Uyuşmazlık + OI Çöküşü (>%15) tespit edildi! Balina temizliği bitti." + _conv_c1.to_reason_suffix()
                                    })

    # KRİPTO 2: MEGA TREND TAKİBİ
    if not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')):
        if last_1d[f'EMA_{config.IND_EMA_MID}'] > last_1d[f'EMA_{config.IND_EMA_SLOW}'] and last_1d['close'] > last_1d[f'EMA_{config.IND_EMA_MID}']:
            atr_col = 'ATRr_14' if 'ATRr_14' in last_4h.index else 'ATR_14'
            if not pd.isna(last_4h.get('ADX_14')) and not pd.isna(last_4h.get('EMA_20')) and not pd.isna(last_4h.get(atr_col)):
                if last_4h['ADX_14'] > 25:
                    # RED-02: ADX olgunlaşma kontrolü
                    if last_4h['ADX_14'] > ADX_TOO_LATE:
                        pass  # Trend olgunlaşmış, geç kaldın
                    elif last_4h['low'] <= last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price > last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price > last_4h['open']:
                        # RED-06: Darth Maul mum filtresi
                        if not _is_darth_maul(last_4h):
                            # RED-07: Anlamlı hacim kontrolü (tutarlılık: KRİPTO 1/3 ile aynı)
                            if not pd.isna(last_4h.get('vol_sma_20')):
                                guarded_vol_sma = _apply_volume_sma_guard(df_4h, last_4h['vol_sma_20'])
                                if _is_meaningful_volume(last_4h['volume'], guarded_vol_sma, current_price, "KRIPTO"):
                                    btcdom_trend = get_btc_dominance_trend()
                                    if btcdom_trend != "UP":
                                        atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
                                        if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
                                        # RED-08: ATR Cap — kripto flash crash koruması
                                        raw_atr_sl = ATR_MULTIPLIER_CRYPTO * atr_val
                                        capped_sl_dist = min(raw_atr_sl, current_price * ATR_CAP_CRYPTO)
                                        sl_atr = current_price - capped_sl_dist
                                        sl_ema = last_4h.get('EMA_50', current_price) * 0.98
                                        sl = max(sl_atr, sl_ema)
                                        _tp_c2 = current_price * 1.30
                                        _rr_c2 = abs(_tp_c2 - current_price) / max(abs(current_price - sl), 1e-8)
                                        _adx_prev_c2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                                        _prev_4h_c2 = df_4h.iloc[-2] if len(df_4h) >= 2 else last_4h
                                        _scores_c2 = build_trend_scores(
                                            adx=last_4h['ADX_14'], adx_prev=_adx_prev_c2,
                                            price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                            rsi=last_4h.get('RSI_14'), rsi_prev=_prev_4h_c2.get('RSI_14'),
                                            volume=last_4h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_4h['volume'] * current_price,
                                            rr=_rr_c2, has_engulfing=False, regime="BULL",
                                            macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
                                        )
                                        _conv_c2 = calculate_conviction(_scores_c2)
                                        if _conv_c2.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                                "ticker": symbol, "market": "KRIPTO", "strategy": "KRİPTO 2: MEGA TREND TAKİBİ", "signal": "AL",
                                                "entry_price": current_price, "sl": sl, "tp": _tp_c2,
                                                "conviction_score": _conv_c2.total_score, "conviction_grade": _conv_c2.grade, "conviction_details": _conv_c2.component_scores,
                                                "position_size_pct": _conv_c2.position_size_pct,
                                                "reason": f"1G EMA20>50 Trendi. BTC Dominans '{btcdom_trend}' yönünde (Güvenli). Hacim onaylı. ATR Stop aktif." + _conv_c2.to_reason_suffix()
                                            })

    # KRİPTO 3: SAHTE KIRILIM FİLTRELİ BREAKOUT
    if not is_weekend_fakeout_time():
        bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
        bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
        bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]

        if bb_upper_col and bb_lower_col and bb_mid_col and btc_ok:
            df_1d['bb_width'] = (df_1d[bb_upper_col[0]] - df_1d[bb_lower_col[0]]) / df_1d[bb_mid_col[0]]
            min_width_30d = df_1d['bb_width'].tail(30).min()
            last_width = df_1d['bb_width'].iloc[-1]

            if last_width <= min_width_30d * 1.20:
                if not pd.isna(last_4h.get('vol_sma_20')):
                    if last_4h['volume'] > (2.0 * last_4h['vol_sma_20']):
                        # RED-06: Darth Maul kaos mumu filtresi
                        if not _is_darth_maul(last_4h):
                            local_high = df_4h['high'].tail(15).max()
                            if last_4h['low'] <= local_high * 0.99 and current_price > last_4h['open']:
                                has_unlocks = check_token_unlocks(symbol)
                                funding_rate = get_funding_rate(symbol)
                                if not has_unlocks and funding_rate <= 0.0:
                                    # AM-03: Mutlak saatlik hacim eşiği
                                    if _has_absolute_hourly_volume(last_4h['volume'], current_price, "KRIPTO"):
                                        sl = current_price * 0.95
                                        _tp_c3 = current_price * 1.15
                                        _rr_c3 = abs(_tp_c3 - current_price) / max(abs(current_price - sl), 1e-8)
                                        _scores_c3 = build_breakout_scores(
                                            bb_width=last_width, price=current_price,
                                            ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                            volume=last_4h['volume'], vol_sma=last_4h['vol_sma_20'], dollar_vol=last_4h['volume'] * current_price,
                                            rr=_rr_c3, regime="BULL",
                                            macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
                                        )
                                        _conv_c3 = calculate_conviction(_scores_c3)
                                        if _conv_c3.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                                "ticker": symbol, "market": "KRIPTO", "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)", "signal": "AL",
                                                "entry_price": current_price, "sl": sl, "tp": _tp_c3,
                                                "conviction_score": _conv_c3.total_score, "conviction_grade": _conv_c3.grade, "conviction_details": _conv_c3.component_scores,
                                                "position_size_pct": _conv_c3.position_size_pct,
                                                "reason": f"1G Daralma, Retest sekmesi. Fonlama: %{funding_rate:.4f}. Hacim: Onaylı." + _conv_c3.to_reason_suffix()
                                            })

    # SHORT STRATEJİLERİ
    btc_not_pumping = check_btc_not_pumping()

    if btc_not_pumping:
        # SHORT 1: FOMO İNFAZI (MSB / Divergence)
        if not pd.isna(last_4h.get('RSI_14')) and last_4h[f'RSI_{config.IND_RSI_LENGTH}'] > 85:
            funding_rate = get_funding_rate(symbol)
            # AM-04: Fonlama Vampiri Kalkanı — negatif fonlamada short YASAK
            if funding_rate is not None and _is_funding_safe_for_short(funding_rate) and funding_rate >= 0.01:
                div_found, _, _, _, _ = detect_bearish_divergence(df_4h)
                swing_lows = sniper_find_swing_points(df_4h, point_type="low")
                msb_ok, msb_low, msb_idx = sniper_detect_msb(df_4h, swing_lows, point_type="low")
                if div_found or msb_ok:
                    sl = last_4h['high'] * 1.02
                    tp = current_price * 0.85
                    trigger_reason = "Negatif Uyuşmazlık" if div_found else "Market Structure Break (Düşük Dip)"
                    _rr_s1 = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                    _adx_prev_s1 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                    _scores_s1 = build_short_scores(
                        adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_s1,
                        price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                        rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
                        dollar_vol=last_4h['volume'] * current_price,
                        rr=_rr_s1, has_engulfing=False, regime="BEAR", macro_aligned=True,
                        consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                    )
                    _conv_s1 = calculate_conviction(_scores_s1)
                    if _conv_s1.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                        signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                            "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 1: FOMO İNFAZI", "signal": "SAT",
                            "entry_price": current_price, "sl": sl, "tp": tp,
                            "conviction_score": _conv_s1.total_score, "conviction_grade": _conv_s1.grade, "conviction_details": _conv_s1.component_scores,
                            "position_size_pct": _conv_s1.position_size_pct,
                            "reason": f"4S RSI>85 ve {trigger_reason}. Fonlama (+%{funding_rate:.4f}) pozitif." + _conv_s1.to_reason_suffix()
                        })

        # SHORT 2: KANLI ŞELALE SÖRFÜ
        if not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')):
            if last_1d[f'EMA_{config.IND_EMA_MID}'] < last_1d[f'EMA_{config.IND_EMA_SLOW}'] and current_price < last_1d[f'EMA_{config.IND_EMA_MID}']:
                if not pd.isna(last_4h.get('ADX_14')) and last_4h['ADX_14'] > 30:
                    if last_4h['high'] >= last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price < last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price < last_4h['open']:
                        btcdom_trend = get_btc_dominance_trend()
                        if btcdom_trend == "UP":
                            atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
                            if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
                            # RED-08: ATR Cap — short tarafında da üst sınır
                            raw_atr_sl = ATR_MULTIPLIER_CRYPTO * atr_val
                            capped_sl_dist = min(raw_atr_sl, current_price * ATR_CAP_CRYPTO)
                            sl = current_price + capped_sl_dist
                            tp = current_price * 0.80
                            _rr_s2 = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                            _adx_prev_s2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                            _scores_s2 = build_short_scores(
                                adx=last_4h['ADX_14'], adx_prev=_adx_prev_s2,
                                price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                                volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20', 0),
                                dollar_vol=last_4h['volume'] * current_price,
                                rr=_rr_s2, has_engulfing=False, regime="BEAR",
                                macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                            )
                            _conv_s2 = calculate_conviction(_scores_s2)
                            if _conv_s2.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                    "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 2: KANLI ŞELALE SÖRFÜ", "signal": "SAT",
                                    "entry_price": current_price, "sl": sl, "tp": tp,
                                    "conviction_score": _conv_s2.total_score, "conviction_grade": _conv_s2.grade, "conviction_details": _conv_s2.component_scores,
                                    "position_size_pct": _conv_s2.position_size_pct,
                                    "reason": f"1G Ayı Trendi, 4S ADX>30. EMA20 Ret. BTC Dominans '{btcdom_trend}'." + _conv_s2.to_reason_suffix()
                                })

        # SHORT 3: UÇURUM ÇÖKÜŞÜ
        if len(df_4h) >= 90:
            support_lookback = df_4h['low'].iloc[-75:-15].min()
            breakout_zone = df_4h.iloc[-15:-1]
            breakout_happened = breakout_zone['low'].min() < support_lookback

            if breakout_happened:
                if current_price < support_lookback:
                    recent_high = max(last_4h['high'], df_4h.iloc[-2]['high'])
                    proximity = (support_lookback - recent_high) / support_lookback

                    # RED-15: Proximity math düzeltmesi — yüzde aralık daraltıldı
                    if -0.005 <= proximity <= 0.015:
                        if current_price < last_4h['open']:
                            funding_rate = get_funding_rate(symbol)
                            if funding_rate >= 0.0:
                                sl = support_lookback * 1.02
                                tp = current_price * 0.80
                                _rr_s3 = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                                _adx_prev_s3 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                                _scores_s3 = build_short_scores(
                                    adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_s3,
                                    price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                    rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                                    volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
                                    dollar_vol=last_4h['volume'] * current_price,
                                    rr=_rr_s3, has_engulfing=False, regime="BEAR", macro_aligned=True,
                                    consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                                )
                                _conv_s3 = calculate_conviction(_scores_s3)
                                if _conv_s3.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                        "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 3: UÇURUM ÇÖKÜŞÜ", "signal": "SAT",
                                        "entry_price": current_price, "sl": sl, "tp": tp,
                                        "conviction_score": _conv_s3.total_score, "conviction_grade": _conv_s3.grade, "conviction_details": _conv_s3.component_scores,
                                        "position_size_pct": _conv_s3.position_size_pct,
                                        "reason": f"90S Desteği kırıldı, %1.5 toleransla Retest yapıldı ve reddedildi." + _conv_s3.to_reason_suffix()
                                    })

    # KRİPTO 4: KESKİN NİŞANCI (SMC / OTE)
    if not is_weekend_fakeout_time():
        if btc_sniper_bias == 1:
            swing_lows_s = sniper_find_swing_points(df_4h, point_type="low")
            swing_highs_s = sniper_find_swing_points(df_4h, point_type="high")
            sweep_ok, sweep_low = sniper_detect_sweep(df_4h, swing_lows_s, point_type="low")
            if sweep_ok:
                msb_ok, msb_high, msb_idx = sniper_detect_msb(df_4h, swing_highs_s, point_type="high")
                if msb_ok:
                    # AM-05: Gövde-bazlı OTE + minimum dalga amplitüdü
                    sweep_idx = swing_lows_s[-1][0] if swing_lows_s else None
                    ote_top, ote_bottom = sniper_calculate_ote_body(df_4h, sweep_idx, msb_idx, direction="long")
                    if ote_top > 0 and ote_bottom > 0 and ote_bottom <= current_price <= ote_top:
                        has_fvg, _, _ = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bullish")
                        funding_rate = get_funding_rate(symbol)
                        if funding_rate <= 0.0:
                            sl = sweep_low * 0.995
                            tp = msb_high * 1.08
                            fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
                            _rr_c4l = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                            _scores_c4l = build_breakout_scores(
                                bb_width=None, price=current_price,
                                ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
                                dollar_vol=last_4h['volume'] * current_price,
                                rr=_rr_c4l, regime="BULL", macro_aligned=True,
                                consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                            )
                            _conv_c4l = calculate_conviction(_scores_c4l)
                            if _conv_c4l.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                    "ticker": symbol, "market": "KRIPTO",
                                    "strategy": "KRİPTO 4: KESKİN NİŞANCI (OTE)", "signal": "AL",
                                    "entry_price": current_price, "sl": sl, "tp": tp,
                                    "conviction_score": _conv_c4l.total_score, "conviction_grade": _conv_c4l.grade, "conviction_details": _conv_c4l.component_scores,
                                    "position_size_pct": _conv_c4l.position_size_pct,
                                    "reason": (
                                        f"🎯 SMC Kurulum (Gövde Fibo){fvg_label}\n"
                                        f"🧹 Likidite: Eski dip ({sweep_low:.4f}) temizlendi.\n"
                                        f"📐 MSB: Yapı kırılımı ({msb_high:.4f}) onaylı.\n"
                                        f"🎣 OTE Bölgesi (Gövde): {ote_bottom:.4f} - {ote_top:.4f}\n"
                                        f"📊 Fonlama: %{funding_rate:.4f} (Negatif Yakıt)\n"
                                        f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
                                    ) + _conv_c4l.to_reason_suffix()
                                })

        elif btc_sniper_bias == -1:
            swing_highs_s = sniper_find_swing_points(df_4h, point_type="high")
            swing_lows_s = sniper_find_swing_points(df_4h, point_type="low")
            sweep_ok, sweep_high = sniper_detect_sweep(df_4h, swing_highs_s, point_type="high")
            if sweep_ok:
                msb_ok, msb_low, msb_idx = sniper_detect_msb(df_4h, swing_lows_s, point_type="low")
                if msb_ok:
                    # RED-11: OTE Short parametre sırası düzeltmesi (yüksek, düşük)
                    ote_top, ote_bottom = sniper_calculate_ote(msb_low, sweep_high)
                    if ote_bottom <= current_price <= ote_top:
                        has_fvg, _, _ = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bearish")
                        funding_rate = get_funding_rate(symbol)
                        if funding_rate >= 0.0:
                            sl = sweep_high * 1.005
                            tp = msb_low * 0.92
                            fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
                            _rr_c4s = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                            _adx_prev_c4s = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                            _scores_c4s = build_short_scores(
                                adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_c4s,
                                price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                                volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
                                dollar_vol=last_4h['volume'] * current_price,
                                rr=_rr_c4s, has_engulfing=False, regime="BEAR", macro_aligned=True,
                                consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                            )
                            _conv_c4s = calculate_conviction(_scores_c4s)
                            if _conv_c4s.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                    "ticker": symbol, "market": "KRIPTO",
                                    "strategy": "SHORT 4: KESKİN NİŞANCI (OTE)", "signal": "SAT",
                                    "entry_price": current_price, "sl": sl, "tp": tp,
                                    "conviction_score": _conv_c4s.total_score, "conviction_grade": _conv_c4s.grade, "conviction_details": _conv_c4s.component_scores,
                                    "position_size_pct": _conv_c4s.position_size_pct,
                                    "reason": (
                                        f"🎯 SHORT SMC Kurulum{fvg_label}\n"
                                        f"🧹 Likidite: Eski tepe ({sweep_high:.4f}) temizlendi.\n"
                                        f"📐 Bearish MSB: Yapı kırılımı ({msb_low:.4f}) aşağı onaylı.\n"
                                        f"🎣 Premium OTE: {ote_bottom:.4f} - {ote_top:.4f}\n"
                                        f"📊 Fonlama: +%{funding_rate:.4f} (Pozitif = Short Yakıtı)\n"
                                        f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
                                    ) + _conv_c4s.to_reason_suffix()
                                })

    # KRİPTO 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)
    if not is_weekend_fakeout_time():
        sq_fired, sq_dir, sq_candle = detect_squeeze(df_4h)
        if sq_fired and sq_dir is not None:
            trend_up = (not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')) and
                        last_1d[f'EMA_{config.IND_EMA_MID}'] > last_1d[f'EMA_{config.IND_EMA_SLOW}'])
            valid_breakout = (sq_dir == "up" and trend_up) or (sq_dir == "down" and not trend_up)
            if valid_breakout:
                sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
                ema20_4h = last_4h.get('EMA_20', current_price)
                if sq_dir == "up":
                    sl = min(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                    tp = current_price * 1.20
                    sig_type = "AL"
                else:
                    sl = max(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                    tp = current_price * 0.80
                    sig_type = "SAT"
                _rr_c5 = abs(tp - current_price) / max(abs(current_price - sl), 1e-8) if sig_type == "AL" else abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                _scores_c5 = build_breakout_scores(
                    bb_width=None, price=current_price, ema_fast=ema20_4h, ema_mid=None, ema_slow=None,
                    volume=last_4h.get('volume', 0), vol_sma=None, dollar_vol=last_4h.get('volume', 0) * current_price,
                    rr=_rr_c5, regime="BULL" if sq_dir == "up" else "BEAR", macro_aligned=btc_ok,
                    consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
                )
                _conv_c5 = calculate_conviction(_scores_c5)
                if _conv_c5.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                        "ticker": symbol, "market": "KRIPTO",
                        "strategy": "KRİPTO 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)", "signal": sig_type,
                        "entry_price": current_price, "sl": sl, "tp": tp,
                        "conviction_score": _conv_c5.total_score, "conviction_grade": _conv_c5.grade, "conviction_details": _conv_c5.component_scores,
                        "position_size_pct": _conv_c5.position_size_pct,
                        "reason": (
                            f"🗜️ Squeeze Patlaması ({sq_dir.upper()})!\n"
                            f"4S BB(20,2) Keltner(20,1.5) içinden kırıldı.\n"
                            f"1G Trend {'Yukarı ✅' if trend_up else 'Aşağı ✅'} ile uyumlu.\n"
                            f"Hacimli {'yeşil' if sq_dir == 'up' else 'kırmızı'} mum onayı."
                        ) + _conv_c5.to_reason_suffix()
                    })

    # KRİPTO 6: VWAP KURUMSAL MIKNATISI
    if not is_weekend_fakeout_time() and btc_ok:
        vwap_val = calculate_anchored_vwap(df_4h, anchor_type="weekly")
        if vwap_val is not None:
            bounce_ok, wick_low = detect_vwap_bounce(df_4h, vwap_val)
            if bounce_ok and wick_low is not None:
                sl = wick_low * 0.99
                _tp_c6 = current_price * 1.10
                _rr_c6 = abs(_tp_c6 - current_price) / max(abs(current_price - sl), 1e-8)
                _scores_c6 = build_trend_scores(
                    adx=None, price=current_price, ema_fast=vwap_val, ema_mid=None, ema_slow=None,
                    volume=last_4h.get('volume', 0), vol_sma=None, dollar_vol=last_4h.get('volume', 0) * current_price,
                    rr=_rr_c6, has_engulfing=True, regime="BULL", macro_aligned=btc_ok,
                    consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
                )
                _conv_c6 = calculate_conviction(_scores_c6)
                if _conv_c6.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                        "ticker": symbol, "market": "KRIPTO",
                        "strategy": "KRİPTO 6: VWAP KURUMSAL MIKNATISI", "signal": "AL",
                        "entry_price": current_price, "sl": sl, "tp": _tp_c6,
                        "conviction_score": _conv_c6.total_score, "conviction_grade": _conv_c6.grade, "conviction_details": _conv_c6.component_scores,
                        "position_size_pct": _conv_c6.position_size_pct,
                        "reason": (
                            f"⚓ VWAP Bounce (Kurumsal Mıknatıs)!\n"
                            f"4S Anchored VWAP: {vwap_val:.4f}\n"
                            f"Pin Bar onayı: VWAP'a değip sıçradı.\n"
                            f"BTC > EMA20 (Piyasa izni var ✅)"
                        ) + _conv_c6.to_reason_suffix()
                    })

    # KRİPTO 7: SESSİZ BİRİKİM RADARI (OBV)
    obv_ok, obv_box_high, obv_box_low = detect_obv_accumulation(df_1d, max_change_pct=5.0)
    if obv_ok and obv_box_high is not None:
        btcdom_trend = get_btc_dominance_trend()
        if btcdom_trend != "UP":
            # AM-02: CMF Wash-Trade Kalkanı
            if is_cmf_wash_trade(df_1d):
                logging.info(f"[AM-02] {symbol}: OBV pozitif ama CMF negatif → Wash Trade, sinyal üretilmedi.")
            else:
                sl = (obv_box_high + obv_box_low) / 2  # RED-12: Kutu ortası SL
                cmf_val = calculate_cmf(df_1d)
                cmf_label = f"CMF: {cmf_val:.3f} ✅" if cmf_val is not None else "CMF: N/A"
                _tp_c7 = current_price * 1.20
                _rr_c7 = abs(_tp_c7 - current_price) / max(abs(current_price - sl), 1e-8)
                _scores_c7 = build_dip_scores(
                    rsi_daily=last_1d.get('RSI_14'), rsi_hourly=None, rsi_prev=None,
                    price=current_price, ema_fast=last_1d.get('EMA_8'), ema_mid=last_1d.get('EMA_21'),
                    volume=last_1d.get('volume', 0), vol_sma=None, dollar_vol=last_1d.get('volume', 0) * current_price,
                    rr=_rr_c7, has_engulfing=False, regime="BULL",
                    macro_aligned=(btcdom_trend != 'UP'), consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
                )
                _conv_c7 = calculate_conviction(_scores_c7)
                if _conv_c7.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                    signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                        "ticker": symbol, "market": "KRIPTO",
                        "strategy": "KRİPTO 7: SESSİZ BİRİKİM RADARI (OBV)", "signal": "AL",
                        "entry_price": current_price, "sl": sl, "tp": _tp_c7,
                        "conviction_score": _conv_c7.total_score, "conviction_grade": _conv_c7.grade, "conviction_details": _conv_c7.component_scores,
                        "position_size_pct": _conv_c7.position_size_pct,
                        "reason": (
                            f"🕵️ Sessiz Birikim + CMF Onaylı!\n"
                            f"1G 20 gün yatay kutu: {obv_box_low:.4f} - {obv_box_high:.4f}\n"
                            f"OBV yeni tepeler + {cmf_label}\n"
                            f"BTC Dominans '{btcdom_trend}' (Altcoin dostu ✅)"
                        ) + _conv_c7.to_reason_suffix()
                    })

    return signals


# ════════════════════════════════════════
# 3. EMTİA STRATEJİ MODÜLÜ
# ════════════════════════════════════════
def analyze_strategies_emtia(symbol, df_1d, df_4h, dxy_bullish=False, metrics_collector=None):
    """Emtia strateji analizi. 3 strateji + DXY/ATR/Haber kalkanları."""
    signals = []

    if _is_macro_news_hour():
        return signals

    if is_weekend_fakeout_time():
        return signals

    if df_1d is None or len(df_1d) < 30:
        return signals

    # Pandas Mutability koruması: kaynak DataFrame'leri kirletme
    df_1d = df_1d.copy()
    if df_4h is not None:
        df_4h = df_4h.copy()

    df_1d.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_1d.ta.ema(length=config.IND_EMA_FAST, append=True)
    df_1d.ta.ema(length=config.IND_EMA_21, append=True)
    df_1d.ta.ema(length=config.IND_EMA_SLOW, append=True)
    df_1d.ta.adx(length=config.IND_ADX_LENGTH, append=True)
    df_1d.ta.atr(length=config.IND_ATR_LENGTH, append=True)
    df_1d.ta.bbands(length=config.IND_BBANDS_LENGTH, std=config.IND_BBANDS_STD, append=True)

    if df_4h is not None and len(df_4h) >= 20:
        df_4h.ta.ema(length=config.IND_EMA_FAST, append=True)
        df_4h.ta.ema(length=config.IND_EMA_21, append=True)
        df_4h.ta.ema(length=config.IND_EMA_MID, append=True)
        df_4h.ta.adx(length=config.IND_ADX_LENGTH, append=True)
        df_4h.ta.atr(length=config.IND_ATR_LENGTH, append=True)
        # Emtia vol_sma hesapla (1E fix)
        df_4h['vol_sma_20'] = df_4h['volume'].rolling(20).mean()

    last_1d = df_1d.iloc[-1]
    current_price = float(last_1d['close'])

    if metrics_collector is not None:
        metrics_collector[symbol] = {
            "Symbol": symbol,
            "Market": "EMTIA",
            "Price": current_price,
            "1D RSI": round(last_1d.get("RSI_14", 0), 2) if pd.notna(last_1d.get("RSI_14")) else None,
            "4H ADX": round(df_4h.iloc[-1].get("ADX_14", 0), 2) if df_4h is not None and not df_4h.empty and pd.notna(df_4h.iloc[-1].get("ADX_14")) else None,
            "1H RSI": None,
            "1D SMA 50": round(last_1d.get("EMA_50", 0), 2) if pd.notna(last_1d.get("EMA_50")) else None,
            "1D SMA 200": None,
            "Trend": "Bullish" if last_1d.get("EMA_8", 0) > last_1d.get("EMA_21", float('inf')) else "Bearish",
            "1H Volume": None
        }


    atr_mult = EMTIA_ATR_MULT.get(symbol, 2.5)
    atr_val = last_1d.get('ATRr_14', last_1d.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val):
        atr_val = current_price * 0.02
    # RED-08: Emtia ATR Cap — flash crash koruması
    raw_sl_dist = atr_mult * atr_val
    dynamic_sl_dist = max(
        min(raw_sl_dist, current_price * ATR_CAP_EMTIA),
        current_price * 0.03
    )
    sl_pct = (dynamic_sl_dist / current_price) * 100

    is_dxy_sensitive = symbol in DXY_SENSITIVE
    dxy_block_long = is_dxy_sensitive and dxy_bullish
    emtia_name = EMTIA_NAMES.get(symbol, symbol)

    # AM-06: Likidite Saatleri Zaman Kilidi — DXY-hassas emtialar sadece 15:30-20:00
    if is_dxy_sensitive and not _is_in_liquidity_window():
        logging.debug(f"[AM-06] {symbol}: DXY-hassas emtia, likidite penceresi dışında → sinyal yok.")
        return signals

    # EMTİA 1: TREND SÖRFÜ
    if df_4h is not None and len(df_4h) >= 20:
        last_4h = df_4h.iloc[-1]
        adx_4h = last_4h.get('ADX_14')
        ema8_4h = last_4h.get('EMA_8')
        ema21_4h = last_4h.get('EMA_21')

        if (not pd.isna(adx_4h) and not pd.isna(ema8_4h) and not pd.isna(ema21_4h)):
            # RED-02: ADX momentum kontrolü
            if _adx_momentum_ok(df_4h, last_4h) and ema8_4h > ema21_4h:
                if (last_4h['low'] <= ema21_4h and last_4h['close'] > ema21_4h
                        and last_4h['close'] > last_4h['open']):
                    if not dxy_block_long:
                        sl = current_price - dynamic_sl_dist
                        tp = current_price + (dynamic_sl_dist * 3)
                        dxy_note = "\n🛡️ DXY Kontrolü: Dolar zayıf ✅" if is_dxy_sensitive else ""
                        _rr_e1l = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                        _scores_e1l = build_trend_scores(
                            adx=adx_4h, adx_prev=df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None,
                            price=current_price, ema_fast=ema8_4h, ema_mid=ema21_4h, ema_slow=None,
                            rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                            volume=last_4h.get('volume', 0), vol_sma=last_4h.get('vol_sma_20'),
                            dollar_vol=last_4h.get('volume', 0) * current_price,
                            rr=_rr_e1l, has_engulfing=True, regime="BULL",
                            macro_aligned=(not dxy_block_long), consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
                        )
                        _conv_e1l = calculate_conviction(_scores_e1l)
                        if _conv_e1l.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                "ticker": symbol, "market": "EMTİA",
                                "strategy": "EMTİA 1: TREND SÖRFÜ (MEGA TREND)", "signal": "AL",
                                "entry_price": current_price, "sl": sl, "tp": tp,
                                "conviction_score": _conv_e1l.total_score, "conviction_grade": _conv_e1l.grade, "conviction_details": _conv_e1l.component_scores,
                                "position_size_pct": _conv_e1l.position_size_pct,
                                "reason": (
                                    f"🏄 {emtia_name} Mega Trend!\n"
                                    f"4S ADX>{adx_4h:.0f} Güçlü Trend. EMA8>EMA21.\n"
                                    f"4S EMA21'e pullback + yeşil mum onayı.\n"
                                    f"SL: {atr_mult}× ATR ({sl_pct:.1f}%){dxy_note}"
                                ) + _conv_e1l.to_reason_suffix()
                            })

            elif adx_4h > 25 and ema8_4h < ema21_4h:
                if (last_4h['high'] >= ema21_4h and last_4h['close'] < ema21_4h
                        and last_4h['close'] < last_4h['open']):
                    sl = current_price + dynamic_sl_dist
                    tp = current_price - (dynamic_sl_dist * 3)
                    _rr_e1s = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                    _scores_e1s = build_short_scores(
                        adx=adx_4h, adx_prev=df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None,
                        price=current_price, ema_fast=ema8_4h, ema_mid=ema21_4h, ema_slow=None,
                        rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                        volume=last_4h.get('volume', 0), vol_sma=last_4h.get('vol_sma_20'),
                        dollar_vol=last_4h.get('volume', 0) * current_price,
                        rr=_rr_e1s, has_engulfing=True, regime="BEAR",
                        macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
                    )
                    _conv_e1s = calculate_conviction(_scores_e1s)
                    if _conv_e1s.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                        signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                            "ticker": symbol, "market": "EMTİA",
                            "strategy": "EMTİA 1: TREND SÖRFÜ (MEGA TREND)", "signal": "SAT",
                            "entry_price": current_price, "sl": sl, "tp": tp,
                            "conviction_score": _conv_e1s.total_score, "conviction_grade": _conv_e1s.grade, "conviction_details": _conv_e1s.component_scores,
                            "position_size_pct": _conv_e1s.position_size_pct,
                            "reason": (
                                f"🏄 {emtia_name} Düşüş Trendi!\n"
                                f"4S ADX &gt; {adx_4h:.0f} Güçlü Düşüş. EMA8 &lt; EMA21.\n"
                                f"4S EMA21'e pullback + kırmızı mum onayı.\n"
                                f"SL: {atr_mult}× ATR ({sl_pct:.1f}%)"
                            ) + _conv_e1s.to_reason_suffix()
                        })

    # EMTİA 2: KESKİN NİŞANCI (SMC / OTE)
    if df_4h is not None and len(df_4h) >= 30:
        htf_bias = sniper_get_htf_bias(df_1d)

        if htf_bias == 1 and not dxy_block_long:
            swing_lows = sniper_find_swing_points(df_4h, point_type="low")
            swing_highs = sniper_find_swing_points(df_4h, point_type="high")
            sweep_ok, sweep_low = sniper_detect_sweep(df_4h, swing_lows, point_type="low")
            if sweep_ok:
                msb_ok, msb_high, msb_idx = sniper_detect_msb(df_4h, swing_highs, point_type="high")
                if msb_ok:
                    ote_top, ote_bottom = sniper_calculate_ote(sweep_low, msb_high)
                    if ote_bottom <= current_price <= ote_top:
                        has_fvg, _, _ = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bullish")
                        sl = sweep_low - (atr_val * 0.5)
                        tp = msb_high * 1.05
                        fvg_label = " + FVG ✅" if has_fvg else ""
                        dxy_note = "\n🛡️ DXY: Dolar zayıf ✅" if is_dxy_sensitive else ""
                        _rr_e2l = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                        _scores_e2l = build_breakout_scores(
                            bb_width=None, price=current_price, ema_fast=None, ema_mid=None, ema_slow=None,
                            volume=last_4h.get('volume', 0) if 'last_4h' in dir() else 0, vol_sma=last_4h.get('vol_sma_20') if 'last_4h' in dir() else None,
                            dollar_vol=(last_4h.get('volume', 0) if 'last_4h' in dir() else 0) * current_price,
                            rr=_rr_e2l, regime="BULL",
                            macro_aligned=(not dxy_block_long), consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
                        )
                        _conv_e2l = calculate_conviction(_scores_e2l)
                        if _conv_e2l.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                "ticker": symbol, "market": "EMTİA",
                                "strategy": "EMTİA 2: KESKİN NİŞANCI (SMC/OTE)", "signal": "AL",
                                "entry_price": current_price, "sl": sl, "tp": tp,
                                "conviction_score": _conv_e2l.total_score, "conviction_grade": _conv_e2l.grade, "conviction_details": _conv_e2l.component_scores,
                                "position_size_pct": _conv_e2l.position_size_pct,
                                "reason": (
                                    f"🎯 {emtia_name} SMC Kurulum{fvg_label}\n"
                                    f"🧹 Likidite: Eski dip ({sweep_low:.2f}) temizlendi.\n"
                                    f"📐 MSB: Yapı kırılımı ({msb_high:.2f}) onaylı.\n"
                                    f"🎣 OTE Bölgesi: {ote_bottom:.2f} - {ote_top:.2f}\n"
                                    f"🛡️ ATR Stop: {atr_mult}× ({sl_pct:.1f}%){dxy_note}"
                                ) + _conv_e2l.to_reason_suffix()
                            })

        elif htf_bias == -1:
            swing_lows = sniper_find_swing_points(df_4h, point_type="low")
            swing_highs = sniper_find_swing_points(df_4h, point_type="high")
            sweep_ok, sweep_high = sniper_detect_sweep(df_4h, swing_highs, point_type="high")
            if sweep_ok:
                msb_ok, msb_low, msb_idx = sniper_detect_msb(df_4h, swing_lows, point_type="low")
                if msb_ok:
                    # RED-11: OTE Short parametre sırası düzeltmesi (yüksek, düşük)
                    ote_top, ote_bottom = sniper_calculate_ote(msb_low, sweep_high)
                    if ote_bottom <= current_price <= ote_top:
                        has_fvg, _, _ = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bearish")
                        sl = sweep_high + (atr_val * 0.5)
                        tp = msb_low * 0.95
                        fvg_label = " + FVG ✅" if has_fvg else ""
                        _rr_e2s = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                        _scores_e2s = build_breakout_scores(
                            bb_width=None, price=current_price, ema_fast=None, ema_mid=None, ema_slow=None,
                            volume=last_4h.get('volume', 0) if 'last_4h' in dir() else 0, vol_sma=last_4h.get('vol_sma_20') if 'last_4h' in dir() else None,
                            dollar_vol=(last_4h.get('volume', 0) if 'last_4h' in dir() else 0) * current_price,
                            rr=_rr_e2s, regime="BEAR",
                            macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
                        )
                        _conv_e2s = calculate_conviction(_scores_e2s)
                        if _conv_e2s.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                            signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                "ticker": symbol, "market": "EMTİA",
                                "strategy": "EMTİA 2: KESKİN NİŞANCI (SMC/OTE)", "signal": "SAT",
                                "entry_price": current_price, "sl": sl, "tp": tp,
                                "conviction_score": _conv_e2s.total_score, "conviction_grade": _conv_e2s.grade, "conviction_details": _conv_e2s.component_scores,
                                "position_size_pct": _conv_e2s.position_size_pct,
                                "reason": (
                                    f"🎯 {emtia_name} SHORT SMC Kurulum{fvg_label}\n"
                                    f"🧹 Likidite: Eski tepe ({sweep_high:.2f}) temizlendi.\n"
                                    f"📐 MSB: Aşağı yapı kırılımı ({msb_low:.2f}).\n"
                                    f"🎣 OTE Bölgesi: {ote_bottom:.2f} - {ote_top:.2f}\n"
                                    f"🛡️ ATR Stop: {atr_mult}× ({sl_pct:.1f}%)"
                                ) + _conv_e2s.to_reason_suffix()
                            })

    # EMTİA 3: VOLATİLİTE SIKIŞMASI (Squeeze)
    squeeze_fired, sq_dir, sq_candle = detect_squeeze(df_1d)
    if squeeze_fired:
        if sq_dir == "up" and not dxy_block_long:
            sl = current_price - dynamic_sl_dist
            tp = current_price + (dynamic_sl_dist * 3)
            dxy_note = "\n🛡️ DXY: Dolar zayıf ✅" if is_dxy_sensitive else ""
            _rr_e3l = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
            _scores_e3l = build_breakout_scores(
                bb_width=None, price=current_price, ema_fast=None, ema_mid=None, ema_slow=None,
                volume=last_1d.get('volume', 0), vol_sma=df_1d['volume'].rolling(20).mean().iloc[-1] if len(df_1d) >= 20 else None,
                dollar_vol=last_1d.get('volume', 0) * current_price,
                rr=_rr_e3l, regime="BULL",
                macro_aligned=(not dxy_block_long), consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
            )
            _conv_e3l = calculate_conviction(_scores_e3l)
            if _conv_e3l.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "EMTİA",
                    "strategy": "EMTİA 3: VOLATİLİTE SIKIŞMASI (SQUEEZE)", "signal": "AL",
                    "entry_price": current_price, "sl": sl, "tp": tp,
                    "conviction_score": _conv_e3l.total_score, "conviction_grade": _conv_e3l.grade, "conviction_details": _conv_e3l.component_scores,
                    "position_size_pct": _conv_e3l.position_size_pct,
                    "reason": (
                        f"🗜️ {emtia_name} Squeeze Patlaması!\n"
                        f"1G BB(20,2) Keltner(20,1.5) içinden yukarı kırıldı.\n"
                        f"Hacimli yeşil mum ile BB üst bandı aşıldı.\n"
                        f"SL: {atr_mult}× ATR ({sl_pct:.1f}%){dxy_note}"
                    ) + _conv_e3l.to_reason_suffix()
                })
        elif sq_dir == "down":
            sl = current_price + dynamic_sl_dist
            tp = current_price - (dynamic_sl_dist * 3)
            _rr_e3s = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
            _scores_e3s = build_breakout_scores(
                bb_width=None, price=current_price, ema_fast=None, ema_mid=None, ema_slow=None,
                volume=last_1d.get('volume', 0), vol_sma=df_1d['volume'].rolling(20).mean().iloc[-1] if len(df_1d) >= 20 else None,
                dollar_vol=last_1d.get('volume', 0) * current_price,
                rr=_rr_e3s, regime="BEAR",
                macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
            )
            _conv_e3s = calculate_conviction(_scores_e3s)
            if _conv_e3s.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "EMTİA",
                    "strategy": "EMTİA 3: VOLATİLİTE SIKIŞMASI (SQUEEZE)", "signal": "SAT",
                    "entry_price": current_price, "sl": sl, "tp": tp,
                    "conviction_score": _conv_e3s.total_score, "conviction_grade": _conv_e3s.grade, "conviction_details": _conv_e3s.component_scores,
                    "position_size_pct": _conv_e3s.position_size_pct,
                    "reason": (
                        f"🗜️ {emtia_name} Aşağı Squeeze Patlaması!\n"
                        f"1G BB(20,2) Keltner(20,1.5) içinden aşağı kırıldı.\n"
                        f"Hacimli kırmızı mum ile BB alt bandı kırıldı.\n"
                        f"SL: {atr_mult}× ATR ({sl_pct:.1f}%)"
                    ) + _conv_e3s.to_reason_suffix()
                })

    return signals


# ════════════════════════════════════════
# 4. 🐻 AYI AVCISI STRATEJİ MODÜLÜ
# ════════════════════════════════════════
def analyze_bear_hunter(symbol, df_1d, df_4h, btc_bullish=False, metrics_collector=None):
    """Ağır Sıklet SHORT tarayıcı. 3 strateji + 3 çelik kalkan."""
    signals = []

    if btc_bullish:
        return signals

    if df_4h is None or len(df_4h) < 20:
        return signals

    # Pandas Mutability koruması: kaynak DataFrame'leri kirletme
    df_1d = df_1d.copy() if df_1d is not None else None
    df_4h = df_4h.copy()

    df_4h.ta.atr(length=config.IND_ATR_LENGTH, append=True)
    # Bear Hunter: EMA/ADX/RSI/vol_sma hesapla (1F fix — NaN sorunu çözümü)
    df_4h.ta.ema(length=config.IND_EMA_MID, append=True)
    df_4h.ta.ema(length=config.IND_EMA_SLOW, append=True)
    df_4h.ta.adx(length=config.IND_ADX_LENGTH, append=True)
    df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_4h['vol_sma_20'] = df_4h['volume'].rolling(20).mean()
    last_4h = df_4h.iloc[-1]
    current_price = float(last_4h['close'])

    if metrics_collector is not None and symbol not in metrics_collector:
        metrics_collector[symbol] = {
            "Symbol": symbol,
            "Market": "KRIPTO (Ayı)",
            "Price": current_price,
            "1D RSI": round(df_1d.iloc[-1].get("RSI_14", 0), 2) if df_1d is not None and not df_1d.empty and pd.notna(df_1d.iloc[-1].get("RSI_14")) else None,
            "4H ADX": round(last_4h.get("ADX_14", 0), 2) if pd.notna(last_4h.get("ADX_14")) else None,
            "1H RSI": None,
            "1D SMA 50": round(df_1d.iloc[-1].get("EMA_50", 0), 2) if df_1d is not None and not df_1d.empty and pd.notna(df_1d.iloc[-1].get("EMA_50")) else None,
            "1D SMA 200": None,
            "Trend": "Bullish" if df_1d is not None and not df_1d.empty and df_1d.iloc[-1].get("EMA_20", 0) > df_1d.iloc[-1].get("EMA_50", float('inf')) else "Bearish",
            "1H Volume": last_4h.get("volume")
        }


    atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val):
        atr_val = current_price * 0.02

    funding_rate = get_funding_rate(symbol)
    funding_ok = True
    funding_note = ""
    if funding_rate is not None:
        if funding_rate < -0.01:
            funding_ok = False
        elif funding_rate >= 0:
            funding_note = f"\n🧲 Funding: +{funding_rate:.4f}% (Shortçu az) ✅"
        else:
            funding_note = f"\n🧲 Funding: {funding_rate:.4f}% (Normal)"

    if not funding_ok:
        return signals

    # SHORT 1: ZİRVE TUZAĞI (SFP)
    sfp_found, swing_high, sfp_candle = detect_sfp(df_4h)
    if sfp_found and sfp_candle is not None:
        sl = float(sfp_candle['high']) + (atr_val * 0.3)
        recent_low = float(df_4h.tail(20)['low'].min())
        tp = recent_low
        risk = sl - current_price
        reward = current_price - tp
        if risk > 0 and reward > 0 and (reward / risk) >= 2.0:
            rr_ratio = reward / risk
            sl_pct = (risk / current_price) * 100
            _adx_prev_bh1 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
            _scores_bh1 = build_short_scores(
                adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_bh1,
                price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                volume=last_4h.get('volume', 0), vol_sma=last_4h.get('vol_sma_20'),
                dollar_vol=last_4h.get('volume', 0) * current_price,
                rr=rr_ratio, has_engulfing=False, regime="BEAR",
                macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
            )
            _conv_bh1 = calculate_conviction(_scores_bh1)
            if _conv_bh1.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "AYI_AVCISI",
                    "strategy": "SHORT 1: ZİRVE TUZAĞI (SFP)", "signal": "SAT",
                    "entry_price": current_price, "sl": sl, "tp": tp,
                    "conviction_score": _conv_bh1.total_score, "conviction_grade": _conv_bh1.grade, "conviction_details": _conv_bh1.component_scores,
                    "position_size_pct": _conv_bh1.position_size_pct,
                    "reason": (
                        f"🧹 {symbol} Zirve Tuzağı!\n"
                        f"Önceki tepe ({swing_high:.2f}) süpürüldü.\n"
                        f"Devasa üst fitil + kırmızı gövde.\n"
                        f"📐 R:R Oranı: {rr_ratio:.1f}:1\n"
                        f"🛑 SL: {sl:.2f} ({sl_pct:.1f}%)\n"
                        f"👑 BTC: Zayıf ✅{funding_note}"
                    ) + _conv_bh1.to_reason_suffix()
                })

    # SHORT 2: PAHALI BÖLGE REDDİ (SMC Premium)
    prem_found, fib_618, fib_786, prem_candle = detect_premium_rejection(df_4h, df_1d)
    if prem_found:
        sl = fib_786 + (atr_val * 0.5)
        recent_low = float(df_4h.tail(30)['low'].min())
        tp = recent_low * 0.97
        risk = sl - current_price
        reward = current_price - tp
        if risk > 0 and reward > 0 and (reward / risk) >= 2.0:
            rr_ratio = reward / risk
            sl_pct = (risk / current_price) * 100
            _adx_prev_bh2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
            _scores_bh2 = build_short_scores(
                adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_bh2,
                price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                volume=last_4h.get('volume', 0), vol_sma=last_4h.get('vol_sma_20'),
                dollar_vol=last_4h.get('volume', 0) * current_price,
                rr=rr_ratio, has_engulfing=False, regime="BEAR",
                macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
            )
            _conv_bh2 = calculate_conviction(_scores_bh2)
            if _conv_bh2.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "AYI_AVCISI",
                    "strategy": "SHORT 2: PAHALI BÖLGE REDDİ (SMC PREMIUM)", "signal": "SAT",
                    "entry_price": current_price, "sl": sl, "tp": tp,
                    "conviction_score": _conv_bh2.total_score, "conviction_grade": _conv_bh2.grade, "conviction_details": _conv_bh2.component_scores,
                    "position_size_pct": _conv_bh2.position_size_pct,
                    "reason": (
                        f"🎯 {symbol} Premium Bölge Reddi!\n"
                        f"1G düşüş trendi (EMA20 &lt; EMA50) onaylı.\n"
                        f"Fib 0.618-0.786 bölgesinde bearish red.\n"
                        f"📐 Premium: {fib_618:.2f} - {fib_786:.2f}\n"
                        f"📐 R:R Oranı: {rr_ratio:.1f}:1\n"
                        f"👑 BTC: Zayıf ✅{funding_note}"
                    ) + _conv_bh2.to_reason_suffix()
                })

    # SHORT 3: YORGUNLUK TEPESİ (Divergence)
    div_found, sh_1, sh_2, rsi_1, rsi_2 = detect_bearish_divergence(df_4h)
    if div_found:
        sl = sh_2 + (atr_val * 0.5)
        recent_low = float(df_4h.tail(20)['low'].min())
        tp = recent_low
        risk = sl - current_price
        reward = current_price - tp
        if risk > 0 and reward > 0 and (reward / risk) >= 2.0:
            rr_ratio = reward / risk
            sl_pct = (risk / current_price) * 100
            _adx_prev_bh3 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
            _scores_bh3 = build_short_scores(
                adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_bh3,
                price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                volume=last_4h.get('volume', 0), vol_sma=last_4h.get('vol_sma_20'),
                dollar_vol=last_4h.get('volume', 0) * current_price,
                rr=rr_ratio, has_engulfing=False, regime="BEAR",
                macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
            )
            _conv_bh3 = calculate_conviction(_scores_bh3)
            if _conv_bh3.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "AYI_AVCISI",
                    "strategy": "SHORT 3: YORGUNLUK TEPESİ (DİVERGENCE)", "signal": "SAT",
                    "entry_price": current_price, "sl": sl, "tp": tp,
                    "conviction_score": _conv_bh3.total_score, "conviction_grade": _conv_bh3.grade, "conviction_details": _conv_bh3.component_scores,
                    "position_size_pct": _conv_bh3.position_size_pct,
                    "reason": (
                        f"🪫 {symbol} Yorgunluk Tepesi!\n"
                        f"Fiyat: {sh_1:.2f} → {sh_2:.2f} (Higher High)\n"
                        f"RSI: {rsi_1:.0f} → {rsi_2:.0f} (Lower High) ⚠️\n"
                        f"Hacim düştü + 4S EMA20 kırıldı.\n"
                        f"📐 R:R Oranı: {rr_ratio:.1f}:1\n"
                        f"👑 BTC: Zayıf ✅{funding_note}"
                    ) + _conv_bh3.to_reason_suffix()
                })

    return signals


# ════════════════════════════════════════
# TOPLU TARAMA ORKESTRATÖRLERİ
# ════════════════════════════════════════
def scan_all_markets():
    """Tüm piyasaları tarar ve (sinyal_listesi, scan_metrics) döndürür.
    
    Scale-Up Optimizasyonları:
    - Batch yfinance download (BIST 200 çağrı → 8 çağrı)
    - Cycle cache (Ayı Avcısı 96 gereksiz çağrı → 0)
    - gc.collect() (E2-micro 1GB RAM koruma)
    - Süre ölçümü (her piyasa segmenti)
    """
    all_signals = []
    scan_metrics = {}
    scan_start = _time.time()
    
    # Döngü başında temizlik
    clear_cycle_cache()
    purge_expired_cache()

    # 1. BIST TARAMALARI (Batch Download)
    if is_bist_open():
        t0 = _time.time()
        xu100_down = check_xu100_wind()
        xu100_daily = _get_xu100_daily_data()

        # FM-04: BIST Rejim Yöneticisi
        bist_regime = _get_bist_regime(xu100_daily)
        logging.info(f"[FM-04] BIST Rejimi: {bist_regime}")

        # Toplu BIST verisi çek (200 HTTP → ~8 batch çağrı)
        bist_data = get_bist_data_batch(TOP_BIST, batch_size=25)
        
        for sym in TOP_BIST:
            try:
                data = bist_data.get(sym, (None, None, None))
                df_1d, df_4h, df_1h = data
                if df_1d is not None:
                    # DG-05: MTF hizalama kontrolü
                    if not guard_mtf_bundle(sym, df_1d, df_4h, df_1h):
                        continue
                    sigs = analyze_strategies_bist(sym, df_1d, df_4h, df_1h, xu100_down, xu100_daily, metrics_collector=scan_metrics)
                    # FM-04: Rejime göre filtrele
                    sigs = _apply_regime_filter(sigs, bist_regime, market="BIST")
                    all_signals.extend(sigs)
            except Exception as e:
                logging.warning(f"[scan_all_markets] BIST {sym}: {e}")
        
        # Batch BIST verisi RAM'den temizle
        del bist_data
        gc.collect()

        # ORB (Zaman Kafesi) — Batch 15m
        now_ist = datetime.now(ZoneInfo("Europe/Istanbul"))
        if 11 <= now_ist.hour < 17 or (now_ist.hour == 17 and now_ist.minute <= 30):
            orb_data = get_bist_15m_batch(TOP_BIST, batch_size=25)
            for sym in TOP_BIST:
                try:
                    df_15m = orb_data.get(sym)
                    if df_15m is not None:
                        orb_sigs = scan_orb_bist(sym, df_15m)
                        all_signals.extend(orb_sigs)
                except Exception as e:
                    logging.warning(f"[scan_all_markets] ORB {sym}: {e}")
            del orb_data
            gc.collect()

        logging.info(f"[scan_all_markets] BIST tarama: {_time.time()-t0:.1f}s")

    # 2. KRİPTO TARAMALARI (Cycle Cache aktif)
    t0 = _time.time()
    btc_ok = get_btc_status()
    btc_sniper_bias = _get_btc_htf_bias()

    for sym in TOP_CRYPTO:
        try:
            # get_crypto_data_cached → hem burada hem Ayı Avcısı'nda kullanılır
            df_1d, df_4h = get_crypto_data_cached(sym)
            if df_1d is not None:
                # DG-05: MTF hizalama kontrolü
                if not guard_mtf_bundle(sym, df_1d, df_4h):
                    continue
                sigs = analyze_strategies_crypto(sym, df_1d, df_4h, btc_ok, btc_sniper_bias, metrics_collector=scan_metrics)
                all_signals.extend(sigs)
        except Exception as e:
            logging.warning(f"[scan_all_markets] KRİPTO {sym}: {e}")
        _time.sleep(API_SLEEP_CRYPTO)

    logging.info(f"[scan_all_markets] Kripto tarama: {_time.time()-t0:.1f}s")

    # 3. EMTİA TARAMALARI
    if _is_macro_news_hour():
        logging.info("[scan_all_markets] ⏳ Makro haber saati (15:00-16:30) - Emtia taraması atlandı.")
    else:
        t0 = _time.time()
        dxy_bullish = _check_dxy_shield()
        if dxy_bullish:
            logging.info("[scan_all_markets] 🛡️ DXY yükseliş trendinde - Altın/Gümüş LONG sinyalleri engellenecek.")

        for sym in TOP_EMTIA:
            try:
                df_1d, df_4h = get_emtia_data(sym)
                if df_1d is not None:
                    # DG-05: MTF hizalama kontrolü
                    if df_4h is not None and not guard_mtf_bundle(sym, df_1d, df_4h):
                        continue
                    sigs = analyze_strategies_emtia(sym, df_1d, df_4h, dxy_bullish, metrics_collector=scan_metrics)
                    all_signals.extend(sigs)
            except Exception as e:
                logging.warning(f"[scan_all_markets] EMTİA {sym}: {e}")
            _time.sleep(API_SLEEP_EMTIA)
        logging.info(f"[scan_all_markets] Emtia tarama: {_time.time()-t0:.1f}s")

    # 4. 🐻 AYI AVCISI (Cycle Cache → duplikasyon 0)
    t0 = _time.time()
    btc_bullish = _is_btc_bullish_for_shorts()
    if btc_bullish:
        logging.info("[scan_all_markets] 👑 BTC güçlü yükselişte - Tüm altcoin SHORT'lar engellendi.")
    else:
        for sym in TOP_HEAVY_SHORT:
            if sym in MEME_BLACKLIST:
                continue
            if sym == "BTC/USDT":
                continue
            try:
                # Cache'den okur → API çağrısı SIFIR (Kripto'da zaten çekildi)
                df_1d, df_4h = get_crypto_data_cached(sym)
                if df_1d is not None and df_4h is not None:
                    sigs = analyze_bear_hunter(sym, df_1d, df_4h, btc_bullish, metrics_collector=scan_metrics)
                    all_signals.extend(sigs)
            except Exception as e:
                logging.warning(f"[scan_all_markets] AYI_AVCISI {sym}: {e}")
            # Cache hit → sleep gereksiz, cache miss → zaten get_crypto_data içinde sleep var

    logging.info(f"[scan_all_markets] Ayı Avcısı: {_time.time()-t0:.1f}s")

    # Döngü sonu RAM temizliği (E2-micro 1GB koruma)
    clear_cycle_cache()
    gc.collect()
    
    total = _time.time() - scan_start
    logging.info(f"[scan_all_markets] ═══ TOPLAM TARAMA: {total:.1f}s ({total/60:.1f} dk) | Sinyal: {len(all_signals)} ═══")

    # RED-17: İkili sinyal çözücü — aynı varlıkta AL + SAT çatışmasını engelle
    all_signals = _resolve_dual_signals(all_signals)

    # FM-01: Kurumsal R:R Filtresi — çöp R:R sinyalleri veto et
    pre_rr = len(all_signals)
    all_signals = _apply_rr_filter(all_signals)
    if pre_rr > len(all_signals):
        logging.info(f"[FM-01] R:R Filtresi: {pre_rr} → {len(all_signals)} sinyal ({pre_rr - len(all_signals)} veto)")

    # DG-03 + DG-06: Son Çıkış Kapısı — Yönlendirme + Fiyat Bütünlüğü
    all_signals = guard_signal_output(all_signals)
    
    return all_signals, scan_metrics

