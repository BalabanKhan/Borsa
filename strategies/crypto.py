"""
strategies/crypto.py — Kripto Strateji Katmanı
Tüm Kripto strateji fonksiyonları.
"""
import math
import pandas as pd
import pandas_ta as ta
import config

from config import (
    ATR_MULTIPLIER_CRYPTO, ATR_CAP_CRYPTO,
)
from conviction_scorer import (
    calculate_conviction,
    build_trend_scores, build_dip_scores, build_breakout_scores,
    build_short_scores, build_sniper_scores,
    CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH, SNIPER_CRYPTO_WEIGHTS,
    check_hard_blocks,
)
from indicators import (
    sniper_find_swing_points, sniper_detect_sweep,
    sniper_detect_msb, sniper_detect_fvg,
    detect_bullish_divergence, detect_bearish_divergence,
    detect_vwap_bounce, detect_obv_accumulation,
    detect_squeeze, calculate_cmf, sniper_calculate_ote_body,
    sniper_calculate_ote, calculate_anchored_vwap, get_trend_sma,
)
from data_sources import (
    get_crypto_1h_data, get_funding_rate, fetch_crypto_oi_crash,
    get_btc_dominance_trend, check_btc_not_pumping, check_token_unlocks,
)
from .helpers import (
    _extract_raw_indicators, _apply_volume_sma_guard, _is_meaningful_volume,
    _get_consecutive_sl, _has_absolute_hourly_volume, _get_darth_maul_ratio,
    _is_funding_safe_for_short,
)


def _check_crypto_1_liquidation(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]
    btc_ok = ctx["btc_ok"]

    has_needed = (
        not pd.isna(last_4h.get('RSI_14')) and
        not pd.isna(last_4h.get('EMA_20')) and
        not pd.isna(last_4h.get('vol_sma_20'))
    )
    if not has_needed:
        return signals

    ema_50_1d = last_1d.get(f'EMA_{config.IND_EMA_SLOW}') if last_1d is not None else None
    trend_aligned = not config.DIP_RSI_1D_EMA50_ALIGN_ENABLED or (
        ema_50_1d is not None and not pd.isna(ema_50_1d) and current_price > ema_50_1d
    )
    if not trend_aligned:
        return signals

    div_found, _, _, _, _ = detect_bullish_divergence(df_4h)
    if not div_found:
        return signals

    guarded_vol_sma = _apply_volume_sma_guard(df_4h, last_4h['vol_sma_20'])
    volume_spike_ok = not config.DIP_VOLUME_SPIKE_REQUIRED or (
        last_4h['volume'] >= guarded_vol_sma * config.DIP_VOLUME_SPIKE_MULT
    )
    if not volume_spike_ok:
        return signals

    if not _is_meaningful_volume(last_4h['volume'], guarded_vol_sma, current_price, "KRIPTO"):
        return signals

    # Golden Filter: ADX > 64.14 (Relaxed/Removed to increase signals)
    # if last_4h.get('ADX_14', 0) <= 64.14:
    #     return signals

    if current_price > last_4h['open']:
        oi_crash = fetch_crypto_oi_crash(symbol)
        
        lowest_wick = last_4h['low']
        sl = lowest_wick * config.CRYPTO_DIP_SL_MULT
        sl_dist = abs(current_price - sl)
        tp = current_price + (sl_dist * config.BEAR_HUNTER_TP_RR)
        _rr_c1 = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
        _prev_4h = df_4h.iloc[-2] if len(df_4h) >= 2 else last_4h
        dm_ratio = _get_darth_maul_ratio(last_4h)
        
        raw_vars = locals()
        
        _scores_c1 = build_dip_scores(
            rsi_daily=last_4h.get('RSI_14', 50), rsi_hourly=last_4h.get('RSI_14', 50),
            rsi_prev=_prev_4h.get('RSI_14', 50),
            price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'),
            volume=last_4h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_4h['volume'] * current_price,
            rr=_rr_c1, has_engulfing=False, regime="BULL",
            macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
            dg_is_darth_maul=dm_ratio,
            oi_crash=oi_crash
        )
        _conv_c1 = calculate_conviction(_scores_c1, ctx=ctx)
        if _conv_c1.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
            reason_str = "4S Pozitif Uyumsuzluk + Hacim Zirvesi"
            if oi_crash:
                reason_str += " + OI Çöküşü (Balina Alımı)"
            reason_str += "." + _conv_c1.to_reason_suffix()

            signals.append({
                "raw_indicators": _extract_raw_indicators(raw_vars),
                "ticker": symbol, "market": "KRIPTO",
                "strategy": "KRİPTO 1: LİKİDASYON AVI", "signal": "AL",
                "entry_price": current_price, "sl": sl, "tp": tp,
                "conviction_score": _conv_c1.total_score, "conviction_grade": _conv_c1.grade,
                "conviction_details": _conv_c1.component_scores, "position_size_pct": _conv_c1.position_size_pct,
                "reason": reason_str
            })
    return signals


def _check_mega_trend_1d_squeeze(last_1d, df_1d):
    if not config.TREND_BB_SQUEEZE_BLOCKED:
        return True
    bb_upper = [c for c in df_1d.columns if 'BBU' in c]
    bb_lower = [c for c in df_1d.columns if 'BBL' in c]
    bb_mid = [c for c in df_1d.columns if 'BBM' in c]
    if not (bb_upper and bb_lower and bb_mid):
        return True
    bbu = last_1d[bb_upper[0]]
    bbl = last_1d[bb_lower[0]]
    bbm = last_1d[bb_mid[0]]
    if bbm == 0:
        return True
    return (bbu - bbl) / bbm >= config.CRYPTO_SQUEEZE_WIDTH_LIMIT


def _check_mega_trend_1d_trend(last_1d):
    ema_mid_val = last_1d.get(f'EMA_{config.IND_EMA_MID}')
    ema_slow_val = last_1d.get(f'EMA_{config.IND_EMA_SLOW}')
    if ema_mid_val is None or ema_slow_val is None or pd.isna(ema_mid_val) or pd.isna(ema_slow_val):
        return False
    return ema_mid_val > ema_slow_val and last_1d['close'] > ema_mid_val


def _check_mega_trend_4h_indicators(last_4h, current_price):
    atr_col = 'ATRr_14' if 'ATRr_14' in last_4h.index else 'ATR_14'
    if pd.isna(last_4h.get('ADX_14')) or pd.isna(last_4h.get('EMA_20')) or pd.isna(last_4h.get(atr_col)):
        return False
    # HARD FILTER REMOVED: ADX Threshold delegated to conviction_scorer
    # if last_4h['ADX_14'] <= config.CRYPTO_TREND_ADX_MIN:
    #     return False
    ema_mid_4h = last_4h.get(f'EMA_{config.IND_EMA_MID}')
    if ema_mid_4h is None or pd.isna(ema_mid_4h):
        return False
    is_pullback = (
        last_4h['low'] <= ema_mid_4h and
        current_price > ema_mid_4h and
        current_price > last_4h['open']
    )
    return is_pullback and not pd.isna(last_4h.get('vol_sma_20'))


def _is_mega_trend_valid(last_1d, last_4h, df_1d, df_4h, current_price):
    if pd.isna(last_1d.get('EMA_20')) or pd.isna(last_1d.get('EMA_50')):
        return False
    if not _check_mega_trend_1d_squeeze(last_1d, df_1d):
        return False
    if not _check_mega_trend_1d_trend(last_1d):
        return False
    return _check_mega_trend_4h_indicators(last_4h, current_price)


def _check_crypto_2_mega_trend(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_1d = ctx["df_1d"]
    df_4h = ctx["df_4h"]
    btc_ok = ctx["btc_ok"]

    if not _is_mega_trend_valid(last_1d, last_4h, df_1d, df_4h, current_price):
        return signals

    guarded_vol_sma = _apply_volume_sma_guard(df_4h, last_4h['vol_sma_20'])
    if last_4h['volume'] < guarded_vol_sma * config.CRYPTO_TREND_VOLUME_SMA_MULT:
        return signals
    if not _is_meaningful_volume(last_4h['volume'], guarded_vol_sma, current_price, "KRIPTO"):
        return signals

    btcdom_trend = get_btc_dominance_trend()

    # Golden Filter: CMF < -0.0357 (Relaxed/Removed to increase signals)
    # cmf = calculate_cmf(df_4h)
    # if cmf is not None and cmf >= -0.0357:
    #     return signals

    atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val):
        atr_val = current_price * config.BEAR_HUNTER_DEFAULT_ATR_MULT
    dynamic_mult = ctx.get("dynamic_atr_mult", ATR_MULTIPLIER_CRYPTO)
    raw_atr_sl = dynamic_mult * atr_val
    capped_sl_dist = min(raw_atr_sl, current_price * ATR_CAP_CRYPTO)
    sl_atr = current_price - capped_sl_dist
    sl_ema = last_4h.get('EMA_50', current_price) * config.CRYPTO_TREND_SL_EMA_MULT
    sl = max(sl_atr, sl_ema)
    sl_dist = abs(current_price - sl)
    _tp_c2 = current_price + (sl_dist * config.BEAR_HUNTER_TP_RR)
    _rr_c2 = abs(_tp_c2 - current_price) / max(abs(current_price - sl), 1e-8)
    _adx_prev_c2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
    _prev_4h_c2 = df_4h.iloc[-2] if len(df_4h) >= 2 else last_4h
    dm_ratio = _get_darth_maul_ratio(last_4h)
    
    raw_vars = locals()
    
    _scores_c2 = build_trend_scores(
        adx=last_4h['ADX_14'], adx_prev=_adx_prev_c2,
        price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
        rsi=last_4h.get('RSI_14'), rsi_prev=_prev_4h_c2.get('RSI_14'),
        volume=last_4h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_4h['volume'] * current_price,
        rr=_rr_c2, has_engulfing=False, regime="BULL",
        macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
        dg_is_darth_maul=dm_ratio
    )

    btcdom_warning = ""
    if btcdom_trend == "UP":
        _scores_c2["conflict_penalty"] -= 15.0
        btcdom_warning = " (Riskli: BTC Dominans UP)"

    _conv_c2 = calculate_conviction(_scores_c2, ctx=ctx)
    if _conv_c2.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO",
            "strategy": "KRİPTO 2: MEGA TREND TAKİBİ", "signal": "AL",
            "entry_price": current_price, "sl": sl, "tp": _tp_c2,
            "conviction_score": _conv_c2.total_score, "conviction_grade": _conv_c2.grade,
            "conviction_details": _conv_c2.component_scores, "position_size_pct": _conv_c2.position_size_pct,
            "reason": f"1G EMA20>50 Trendi. BTC Dominans '{btcdom_trend}' yönünde{btcdom_warning}. Hacim onaylı. ATR Stop aktif." + _conv_c2.to_reason_suffix()
        })
    return signals


def _is_breakout_setup(symbol, last_4h, current_price, df_1d, df_4h):
    bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
    bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
    bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]

    if not bb_upper_col:
        return False, 0.0
    if not bb_lower_col:
        return False, 0.0
    if not bb_mid_col:
        return False, 0.0

    df_1d['bb_width'] = (df_1d[bb_upper_col[0]] - df_1d[bb_lower_col[0]]) / df_1d[bb_mid_col[0]]
    min_width_30d = df_1d['bb_width'].tail(config.CRYPTO_BREAKOUT_LOOKBACK).min()
    last_width = df_1d['bb_width'].iloc[-1]

    if last_width > min_width_30d * config.CRYPTO_BREAKOUT_WIDTH_MULT:
        return False, 0.0

    vol_sma = last_4h.get('vol_sma_20')
    if pd.isna(vol_sma):
        return False, 0.0
    if last_4h['volume'] <= config.CRYPTO_BREAKOUT_VOLUME_MULT * vol_sma:
        return False, 0.0

    return True, last_width


def _is_breakout_retest_valid(symbol, last_4h, current_price, df_4h):
    local_high = df_4h['high'].tail(config.CRYPTO_BREAKOUT_RETEST_LOOKBACK).max()
    if config.BREAKOUT_RETEST_REQUIRED:
        if not (local_high <= current_price <= local_high * (1.0 + (config.BREAKOUT_RETEST_TOLERANCE_PCT / 100.0))):
            return False, 0.0
    
    if current_price <= local_high:
        return False, 0.0
    if last_4h['low'] > local_high * config.CRYPTO_BREAKOUT_RETEST_SL_MULT:
        return False, 0.0
    if current_price <= last_4h['open']:
        return False, 0.0

    if check_token_unlocks(symbol):
        return False, 0.0

    return True, local_high


def _check_crypto_3_breakout(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_1d = ctx["df_1d"]
    df_4h = ctx["df_4h"]
    btc_ok = ctx["btc_ok"]

    # HARD FILTER REMOVED: RSI and ADX constraints delegated to conviction_scorer
    # if last_4h.get('RSI_14', 0) >= config.CRYPTO_RETEST_RSI_MAX:
    #     return signals
    # if last_4h.get('ADX_14', 0) < config.CRYPTO_RETEST_ADX_MIN:
    #     return signals

    ok_setup, last_width = _is_breakout_setup(symbol, last_4h, current_price, df_1d, df_4h)
    if not ok_setup:
        return signals

    ok_retest, local_high = _is_breakout_retest_valid(symbol, last_4h, current_price, df_4h)
    if not ok_retest:
        return signals

    funding_rate = get_funding_rate(symbol)
    if funding_rate is not None and funding_rate > config.BREAKOUT_CRYPTO_FUNDING_RATE_MAX:
        return signals

    if not _has_absolute_hourly_volume(last_4h['volume'], current_price, "KRIPTO"):
        return signals

    atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val):
        atr_val = current_price * config.BEAR_HUNTER_DEFAULT_ATR_MULT
    dynamic_mult = ctx.get("dynamic_atr_mult", config.ATR_MULTIPLIER_CRYPTO)
    raw_atr_sl = dynamic_mult * atr_val
    sl_dist = min(max(raw_atr_sl, current_price * config.CRYPTO_BREAKOUT_MIN_SL), current_price * config.CRYPTO_BREAKOUT_MAX_SL)
    sl = current_price - sl_dist
    _tp_c3 = current_price + (sl_dist * config.BEAR_HUNTER_TP_RR)
    _rr_c3 = abs(_tp_c3 - current_price) / max(abs(current_price - sl), 1e-8)
    dm_ratio = _get_darth_maul_ratio(last_4h)
    
    raw_vars = locals()
    
    _scores_c3 = build_breakout_scores(
        bb_width=last_width, price=current_price,
        ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
        volume=last_4h['volume'], vol_sma=last_4h['vol_sma_20'], dollar_vol=last_4h['volume'] * current_price,
        rr=_rr_c3, regime="BULL",
        macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
        dg_is_darth_maul=dm_ratio, funding_rate=funding_rate,
        rsi=last_4h.get('RSI_14'),
        rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else last_4h.get('RSI_14'),
        has_engulfing=False
    )
    _conv_c3 = calculate_conviction(_scores_c3, ctx=ctx)
    if _conv_c3.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO",
            "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)", "signal": "AL",
            "entry_price": current_price, "sl": sl, "tp": _tp_c3,
            "conviction_score": _conv_c3.total_score, "conviction_grade": _conv_c3.grade,
            "conviction_details": _conv_c3.component_scores, "position_size_pct": _conv_c3.position_size_pct,
            "reason": f"1G Daralma, Retest sekmesi. Fonlama: %{funding_rate:.4f}. Hacim: Onaylı." + _conv_c3.to_reason_suffix()
        })
    return signals


def _check_crypto_short_1_fomo(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]

    # HARD FILTER REMOVED: RSI constraint delegated to conviction_scorer
    # if pd.isna(last_4h.get('RSI_14')) or last_4h['RSI_14'] <= config.SHORT_RSI_OVERBOUGHT_LIMIT:
    #     return signals

    trend_aligned = True
    if config.SHORT_TREND_ALIGN_REQUIRED:
        ema_50_1d = last_1d.get(f'EMA_{config.IND_EMA_SLOW}')
        trend_sma = get_trend_sma(last_1d)
        if ema_50_1d is not None and not pd.isna(ema_50_1d) and current_price >= ema_50_1d:
            trend_aligned = False
        if trend_sma is not None and not pd.isna(trend_sma) and current_price >= trend_sma:
            trend_aligned = False

    if not trend_aligned:
        return signals

    funding_rate = get_funding_rate(symbol)
    if funding_rate is None or not _is_funding_safe_for_short(funding_rate) or funding_rate < config.SHORT1_CRYPTO_FUNDING_RATE_MIN:
        return signals

    div_found, _, _, _, _ = detect_bearish_divergence(df_4h)
    swing_lows = sniper_find_swing_points(df_4h, point_type="low")
    msb_ok, msb_low, _ = sniper_detect_msb(df_4h, swing_lows, point_type="low")
    
    if not (div_found or msb_ok):
        return signals

    # Golden Filter: Vortex_Diff > 0.5207 (Relaxed/Removed to increase signals)
    # if 'high' in df_4h and 'low' in df_4h and 'close' in df_4h:
    #     vortex = ta.vortex(df_4h['high'], df_4h['low'], df_4h['close'], length=14)
    #     if vortex is not None and not vortex.empty:
    #         vortex_diff = vortex.iloc[-1, 0] - vortex.iloc[-1, 1]  # VIp - VIm
    #         if vortex_diff <= 0.5207:
    #             return signals

    sl = last_4h['high'] * config.CRYPTO_SHORT1_SL_MULT
    sl_dist = abs(sl - current_price)
    tp = current_price - (sl_dist * config.BEAR_HUNTER_TP_RR)
    trigger_reason = "Negatif Uyuşmazlık" if div_found else "Market Structure Break (Düşük Dip)"
    _rr_s1 = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
    _adx_prev_s1 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
    
    raw_vars = locals()
    
    _scores_s1 = build_short_scores(
        adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_s1,
        price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
        rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
        dollar_vol=last_4h['volume'] * current_price,
        rr=_rr_s1, has_engulfing=False, regime="BEAR", macro_aligned=True,
        consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
    )
    _conv_s1 = calculate_conviction(_scores_s1, ctx=ctx)
    if _conv_s1.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 1: FOMO İNFAZI", "signal": "SAT",
            "entry_price": current_price, "sl": sl, "tp": tp,
            "conviction_score": _conv_s1.total_score, "conviction_grade": _conv_s1.grade,
            "conviction_details": _conv_s1.component_scores, "position_size_pct": _conv_s1.position_size_pct,
            "reason": f"4S RSI>{config.SHORT_RSI_OVERBOUGHT_LIMIT:.0f} ve {trigger_reason}. Fonlama (+%{funding_rate:.4f}) pozitif." + _conv_s1.to_reason_suffix()
        })
    return signals


def _check_crypto_short_2_waterfall(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]

    if not (last_1d[f'EMA_{config.IND_EMA_MID}'] < last_1d[f'EMA_{config.IND_EMA_SLOW}'] and current_price < last_1d[f'EMA_{config.IND_EMA_MID}']):
        return signals

    # HARD FILTER REMOVED: ADX constraint delegated to conviction_scorer
    # if pd.isna(last_4h.get('ADX_14')) or last_4h['ADX_14'] <= config.CRYPTO_SHORT2_ADX_MIN:
    #     return signals
        
    vol_sma = last_4h.get('vol_sma_20', 0)
    if vol_sma > 0 and last_4h.get('volume', 0) < vol_sma * config.CRYPTO_SHORT2_VOLUME_SMA_MULT:
        return signals

    if not (last_4h['high'] >= last_4h['EMA_20'] and current_price < last_4h['EMA_20'] and current_price < last_4h['open']):
        return signals

    btcdom_trend = get_btc_dominance_trend()
    if btcdom_trend != "UP":
        return signals

    # Golden Filter: BB Width < 0.0544 (Relaxed/Removed to increase signals)
    # bb_upper = [c for c in df_4h.columns if 'BBU' in c]
    # bb_lower = [c for c in df_4h.columns if 'BBL' in c]
    # bb_mid = [c for c in df_4h.columns if 'BBM' in c]
    # if bb_upper and bb_lower and bb_mid:
    #     bbu = last_4h[bb_upper[0]]
    #     bbl = last_4h[bb_lower[0]]
    #     bbm = last_4h[bb_mid[0]]
    #     if bbm > 0:
    #         bbw = (bbu - bbl) / bbm
    #         if bbw >= 0.0544:
    #             return signals

    atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val):
        atr_val = current_price * config.BEAR_HUNTER_DEFAULT_ATR_MULT
    dynamic_mult = ctx.get("dynamic_atr_mult", ATR_MULTIPLIER_CRYPTO)
    raw_atr_sl = dynamic_mult * atr_val
    capped_sl_dist = min(raw_atr_sl, current_price * ATR_CAP_CRYPTO)
    sl = current_price + capped_sl_dist
    sl_dist = abs(sl - current_price)
    tp = current_price - (sl_dist * config.BEAR_HUNTER_TP_RR)
    _rr_s2 = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
    _adx_prev_s2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
    
    raw_vars = locals()
    
    _scores_s2 = build_short_scores(
        adx=last_4h['ADX_14'], adx_prev=_adx_prev_s2,
        price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
        rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20', 0),
        dollar_vol=last_4h['volume'] * current_price,
        rr=_rr_s2, has_engulfing=False, regime="BEAR",
        macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
    )
    _conv_s2 = calculate_conviction(_scores_s2, ctx=ctx)
    if _conv_s2.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 2: KANLI ŞELALE SÖRFÜ", "signal": "SAT",
            "entry_price": current_price, "sl": sl, "tp": tp,
            "conviction_score": _conv_s2.total_score, "conviction_grade": _conv_s2.grade,
            "conviction_details": _conv_s2.component_scores, "position_size_pct": _conv_s2.position_size_pct,
            "reason": f"1G Ayı Trendi, 4S ADX>30. EMA8 Ret. BTC Dominans '{btcdom_trend}'." + _conv_s2.to_reason_suffix()
        })
    return signals


def _check_crypto_short_3_cliff(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]
    btc_ok = ctx["btc_ok"]

    if len(df_4h) < (config.CRYPTO_SHORT3_SUPPORT_LOOKBACK + config.CRYPTO_SHORT3_BREAKOUT_ZONE):
        return signals

    support_lookback = df_4h['low'].iloc[-config.CRYPTO_SHORT3_SUPPORT_LOOKBACK:-config.CRYPTO_SHORT3_BREAKOUT_ZONE].min()
    breakout_zone = df_4h.iloc[-config.CRYPTO_SHORT3_BREAKOUT_ZONE:-1]
    breakout_happened = breakout_zone['low'].min() < support_lookback

    if not breakout_happened:
        return signals

    cmf_4h_val = last_4h.get('CMF_20')
    cmf_ok_s3 = cmf_4h_val is None or math.isnan(cmf_4h_val) or cmf_4h_val < 0.0
    
    if not (cmf_ok_s3 and (current_price < support_lookback)):
        return signals

    recent_high = max(last_4h['high'], df_4h.iloc[-2]['high'])
    proximity = (support_lookback - recent_high) / support_lookback

    if not (config.SHORT3_CANYON_PROXIMITY_MIN <= proximity <= config.SHORT3_CANYON_PROXIMITY_MAX):
        return signals

    if not (current_price < last_4h['open']):
        return signals

    funding_rate = get_funding_rate(symbol)
    if funding_rate is None or funding_rate < config.SHORT1_CRYPTO_FUNDING_RATE_MIN:
        return signals

    sl = support_lookback * config.CRYPTO_SHORT3_SL_MULT
    sl_dist = abs(sl - current_price)
    tp = current_price - (sl_dist * config.CRYPTO_SHORT3_TP_RR)
    _rr_s3 = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
    _adx_prev_s3 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
    
    raw_vars = locals()
    
    _scores_s3 = build_short_scores(
        adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_s3,
        price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
        rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
        dollar_vol=last_4h['volume'] * current_price,
        rr=_rr_s3, has_engulfing=False, regime="BEAR", macro_aligned=not btc_ok,
        consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
    )
    _conv_s3 = calculate_conviction(_scores_s3, ctx=ctx)
    if _conv_s3.grade == CONVICTION_STRONG:
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 3: UÇURUM ÇÖKÜŞÜ", "signal": "SAT",
            "entry_price": current_price, "sl": sl, "tp": tp,
            "conviction_score": _conv_s3.total_score, "conviction_grade": _conv_s3.grade,
            "conviction_details": _conv_s3.component_scores, "position_size_pct": _conv_s3.position_size_pct,
            "reason": f"90S Desteği kırıldı, %1.5 toleransla Retest yapıldı ve reddedildi (Güvenli)." + _conv_s3.to_reason_suffix()
        })
    return signals


def _check_crypto_shorts(ctx):
    signals = []

    btc_not_pumping = check_btc_not_pumping()
    if not btc_not_pumping:
        return signals

    signals.extend(_check_crypto_short_1_fomo(ctx))
    signals.extend(_check_crypto_short_2_waterfall(ctx))
    signals.extend(_check_crypto_short_3_cliff(ctx))
    return signals


def _check_crypto_4_sniper_ote_long(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]
    btc_sniper_bias = ctx["btc_sniper_bias"]

    if btc_sniper_bias not in (1, 0):
        return signals

    swing_lows_s = sniper_find_swing_points(df_4h, point_type="low")
    swing_highs_s = sniper_find_swing_points(df_4h, point_type="high")
    sweep_ok, sweep_low = sniper_detect_sweep(df_4h, swing_lows_s, point_type="low")
    if not sweep_ok:
        # print("FAIL: No sweep")
        return signals

    msb_ok, msb_high, msb_idx = sniper_detect_msb(df_4h, swing_highs_s, point_type="high")
    if not msb_ok:
        # print("FAIL: No MSB")
        return signals

    sweep_idx = swing_lows_s[-1][0] if swing_lows_s else None
    ote_top, ote_bottom = sniper_calculate_ote_body(df_4h, sweep_idx, msb_idx, direction="long")
    if ote_top <= 0 or ote_bottom <= 0 or not (ote_bottom <= current_price <= ote_top):
        # print(f"FAIL: Not in OTE {ote_bottom} < {current_price} < {ote_top}")
        return signals

    has_fvg, _, _ = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bullish")
    if config.SMC_FVG_REQUIRED and not has_fvg:
        # print("FAIL: No FVG")
        return signals

    # ltf_confirm = True
    # df_1h_crypto = None
    # if config.SMC_LTF_MSB_CONFIRM:
    #     df_1h_crypto = get_crypto_1h_data(symbol)
    #     if df_1h_crypto is not None and not df_1h_crypto.empty:
    #         df_1h_crypto = df_1h_crypto.copy()
    #         df_1h_crypto.ta.ema(length=config.IND_EMA_FAST, append=True)
    #         df_1h_crypto.ta.ema(length=config.IND_EMA_21, append=True)
    #         swing_highs_1h = sniper_find_swing_points(df_1h_crypto, point_type="high", neighbors=2)
    #         ltf_confirm, _, _ = sniper_detect_msb(df_1h_crypto, swing_highs_1h, point_type="high")
    #     else:
    #         ltf_confirm = False

    # if not ltf_confirm:
    #     return signals

    funding_rate = get_funding_rate(symbol)
    df_1h_crypto = None

    sl = sweep_low * config.CRYPTO_LONG4_SL_MULT
    sl_dist = max(current_price - sl, 1e-8)
    tp = current_price + (sl_dist * config.BEAR_HUNTER_TP_RR)
    fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
    _rr_c4l = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
    
    ema_fast_val = None
    ema_mid_val = None
    if config.SMC_LTF_MSB_CONFIRM and df_1h_crypto is not None and not df_1h_crypto.empty:
        ema_fast_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_FAST}')
        ema_mid_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_21}')
    else:
        ema_fast_val = last_4h.get('EMA_20')
        ema_mid_val = last_4h.get('EMA_50')

    raw_vars = locals()
    
    _scores_c4l = build_breakout_scores(
        bb_width=None, price=current_price,
        ema_fast=ema_fast_val, ema_mid=ema_mid_val, ema_slow=None,
        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
        dollar_vol=last_4h['volume'] * current_price,
        rr=_rr_c4l, regime="BULL", macro_aligned=True,
        consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
        funding_rate=funding_rate,
        rsi=last_4h.get('RSI_14'),
        rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else last_4h.get('RSI_14'),
        has_engulfing=False
    )
    if has_fvg:
        _scores_c4l["engulfing"] = min(100.0, _scores_c4l["engulfing"] + config.SMC_FVG_BONUS)
        
    _conv_c4l = calculate_conviction(_scores_c4l, ctx=ctx)
    if _conv_c4l.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO",
            "strategy": "KRİPTO 4: KESKİN NİŞANCI (OTE)", "signal": "AL",
            "entry_price": current_price, "sl": sl, "tp": tp,
            "conviction_score": _conv_c4l.total_score, "conviction_grade": _conv_c4l.grade,
            "conviction_details": _conv_c4l.component_scores, "position_size_pct": _conv_c4l.position_size_pct,
            "reason": (
                f"🎯 SMC Kurulum (Gövde Fibo){fvg_label}\n"
                f"🧹 Likidite: Eski dip ({sweep_low:.4f}) temizlendi.\n"
                f"📐 MSB: Yapı kırılımı ({msb_high:.4f}) onaylı.\n"
                f"🎣 OTE Bölgesi (Gövde): {ote_bottom:.4f} - {ote_top:.4f}\n"
                f"📊 Fonlama: %{funding_rate:.4f} (Negatif Yakıt)\n"
                f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
            ) + _conv_c4l.to_reason_suffix()
        })
    return signals


def _check_crypto_4_sniper_ote_short(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]
    btc_sniper_bias = ctx["btc_sniper_bias"]

    if btc_sniper_bias not in (-1, 0):
        return signals

    swing_highs_s = sniper_find_swing_points(df_4h, point_type="high")
    swing_lows_s = sniper_find_swing_points(df_4h, point_type="low")
    sweep_ok, sweep_high = sniper_detect_sweep(df_4h, swing_highs_s, point_type="high")
    if not sweep_ok:
        return signals

    msb_ok, msb_low, msb_idx = sniper_detect_msb(df_4h, swing_lows_s, point_type="low")
    if not msb_ok:
        return signals

    ote_top, ote_bottom = sniper_calculate_ote(msb_low, sweep_high)
    if not (ote_bottom <= current_price <= ote_top):
        return signals

    has_fvg, _, _ = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bearish")
    if config.SMC_FVG_REQUIRED and not has_fvg:
        return signals

    # ltf_confirm = True
    # df_1h_crypto = None
    # if config.SMC_LTF_MSB_CONFIRM:
    #     df_1h_crypto = get_crypto_1h_data(symbol)
    #     if df_1h_crypto is not None and not df_1h_crypto.empty:
    #         df_1h_crypto = df_1h_crypto.copy()
    #         df_1h_crypto.ta.ema(length=config.IND_EMA_FAST, append=True)
    #         df_1h_crypto.ta.ema(length=config.IND_EMA_21, append=True)
    #         swing_lows_1h = sniper_find_swing_points(df_1h_crypto, point_type="low", neighbors=2)
    #         ltf_confirm, _, _ = sniper_detect_msb(df_1h_crypto, swing_lows_1h, point_type="low")
    #     else:
    #         ltf_confirm = False

    # if not ltf_confirm:
    #     return signals

    funding_rate = get_funding_rate(symbol)
    df_1h_crypto = None

    sl = sweep_high * config.CRYPTO_SHORT4_SL_MULT
    sl_dist = max(sl - current_price, 1e-8)
    tp = current_price - (sl_dist * config.BEAR_HUNTER_TP_RR)
    fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
    _rr_c4s = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
    _adx_prev_c4s = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
    
    ema_fast_val = None
    ema_mid_val = None
    if config.SMC_LTF_MSB_CONFIRM and df_1h_crypto is not None and not df_1h_crypto.empty:
        ema_fast_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_FAST}')
        ema_mid_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_21}')
    else:
        ema_fast_val = last_4h.get('EMA_20')
        ema_mid_val = last_4h.get('EMA_50')

    raw_vars = locals()
    
    _scores_c4s = build_short_scores(
        adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_c4s,
        price=current_price, ema_fast=ema_fast_val, ema_mid=ema_mid_val, ema_slow=None,
        rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
        dollar_vol=last_4h['volume'] * current_price,
        rr=_rr_c4s, has_engulfing=False, regime="BEAR", macro_aligned=True,
        consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
        funding_rate=funding_rate
    )
    if has_fvg:
        _scores_c4s["engulfing"] = min(100.0, _scores_c4s["engulfing"] + config.SMC_FVG_BONUS)
        
    _conv_c4s = calculate_conviction(_scores_c4s, ctx=ctx)
    if _conv_c4s.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO",
            "strategy": "SHORT 4: KESKİN NİŞANCI (OTE)", "signal": "SAT",
            "entry_price": current_price, "sl": sl, "tp": tp,
            "conviction_score": _conv_c4s.total_score, "conviction_grade": _conv_c4s.grade,
            "conviction_details": _conv_c4s.component_scores, "position_size_pct": _conv_c4s.position_size_pct,
            "reason": (
                f"🎯 SHORT SMC Kurulum{fvg_label}\n"
                f"🧹 Likidite: Eski tepe ({sweep_high:.4f}) temizlendi.\n"
                f"📐 Bearish MSB: Yapı kırılımı ({msb_low:.4f}) aşağı onaylı.\n"
                f"🎣 Premium OTE: {ote_bottom:.4f} - {ote_top:.4f}\n"
                f"📊 Fonlama: +%{funding_rate:.4f} (Pozitif = Short Yakıtı)\n"
                f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
            ) + _conv_c4s.to_reason_suffix()
        })
    return signals


def _check_crypto_4_sniper_ote(ctx):
    signals = []
    signals.extend(_check_crypto_4_sniper_ote_long(ctx))
    signals.extend(_check_crypto_4_sniper_ote_short(ctx))
    return signals


def _check_crypto_5_vol_squeeze(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]
    btc_ok = ctx["btc_ok"]

    sq_fired, sq_dir, sq_candle = detect_squeeze(df_4h)
    if sq_fired and sq_dir is not None:
        # HARD FILTER REMOVED: ADX constraint delegated to conviction_scorer
        # if pd.isna(last_4h.get('ADX_14')) or last_4h['ADX_14'] < config.CRYPTO_SQUEEZE_ADX_MIN:
        #     return signals
        trend_up = (not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')) and
                    last_1d[f'EMA_{config.IND_EMA_MID}'] > last_1d[f'EMA_{config.IND_EMA_SLOW}'])
        valid_breakout = (sq_dir == "up" and trend_up) or (sq_dir == "down" and not trend_up)
        if valid_breakout:
            sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
            ema20_4h = last_4h.get('EMA_20', current_price)
            if sq_dir == "up":
                sl = min(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                sl_dist = abs(current_price - sl)
                tp = current_price + (sl_dist * config.BEAR_HUNTER_TP_RR)
                sig_type = "AL"
            else:
                sl = max(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                sl_dist = abs(sl - current_price)
                tp = current_price - (sl_dist * config.BEAR_HUNTER_TP_RR)
                sig_type = "SAT"
            _rr_c5 = abs(tp - current_price) / max(abs(current_price - sl), 1e-8) if sig_type == "AL" else abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
            
            raw_vars = locals()
            
            _scores_c5 = build_breakout_scores(
                bb_width=None, price=current_price, ema_fast=ema20_4h, ema_mid=None, ema_slow=None,
                volume=last_4h.get('volume', 0),
                vol_sma=last_4h.get('vol_sma_20'),
                dollar_vol=last_4h.get('volume', 0) * current_price,
                rr=_rr_c5, regime="BULL" if sq_dir == "up" else "BEAR", macro_aligned=btc_ok,
                consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                rsi=last_4h.get('RSI_14'),
                rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else last_4h.get('RSI_14'),
                is_long=(sq_dir == "up"),
                strategy_type="TREND_BREAKOUT",
                rsi_1h=last_4h.get('RSI_14'),
                sma200_1d=last_1d.get('SMA_200') if last_1d is not None else None
            )
            _conv_c5 = calculate_conviction(_scores_c5, ctx=ctx)
            if _conv_c5.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({
                    "raw_indicators": _extract_raw_indicators(raw_vars),
                    "ticker": symbol, "market": "KRIPTO",
                    "strategy": "KRİPTO 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)", "signal": sig_type,
                    "entry_price": current_price, "sl": sl, "tp": tp,
                    "conviction_score": _conv_c5.total_score, "conviction_grade": _conv_c5.grade,
                    "conviction_details": _conv_c5.component_scores, "position_size_pct": _conv_c5.position_size_pct,
                    "reason": (
                        f"🗜️ Squeeze Patlaması ({sq_dir.upper()})!\n"
                        f"4S BB(20,2) Keltner(20,1.5) içinden kırıldı.\n"
                        f"1G Trend {'Yukarı ✅' if trend_up else 'Aşağı ✅'} ile uyumlu.\n"
                        f"Hacimli {'yeşil' if sq_dir == 'up' else 'kırmızı'} mum onayı."
                    ) + _conv_c5.to_reason_suffix()
                })
    return signals


def _check_crypto_6_vwap(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    last_4h = ctx["last_4h"]
    current_price = ctx["current_price"]
    df_4h = ctx["df_4h"]
    btc_ok = ctx["btc_ok"]

    if last_1d is None or pd.isna(last_1d.get('EMA_20')) or pd.isna(last_1d.get('EMA_50')):
        return signals
    if last_1d['EMA_20'] <= last_1d['EMA_50']:
        return signals
    # HARD FILTER REMOVED: ADX constraint delegated to conviction_scorer
    # if pd.isna(last_4h.get('ADX_14')) or last_4h['ADX_14'] <= config.CRYPTO_VWAP_ADX_MIN:
    #     return signals

    # VWAP Golden Filters (RSI & Volatilite/ATR)
    # HARD FILTER REMOVED: RSI constraint delegated to conviction_scorer
    # if not pd.isna(last_4h.get('RSI_14')) and last_4h['RSI_14'] >= getattr(config, 'VWAP_LONG_MAX_RSI', 60.0):
    #     return signals
        
    if f'ATRr_14' not in df_4h.columns:
        df_4h.ta.atr(length=14, append=True)
    if 'ATR_SMA_14' not in df_4h.columns:
        df_4h['ATR_SMA_14'] = df_4h['ATRr_14'].rolling(window=14).mean()

    current_atr = df_4h['ATRr_14'].iloc[-1]
    atr_sma = df_4h['ATR_SMA_14'].iloc[-1]
    
    if pd.notna(current_atr) and pd.notna(atr_sma) and atr_sma > 0:
        if (current_atr / atr_sma) > getattr(config, 'VWAP_MAX_ATR_RATIO', 2.0):
            return signals # Aşırı Volatilite İptali

    vwap_val = calculate_anchored_vwap(df_4h, anchor_type="weekly")
    if vwap_val is not None:
        bounce_ok, wick_low = detect_vwap_bounce(df_4h, vwap_val)
        if bounce_ok and wick_low is not None:
            sl = wick_low * config.CRYPTO_VWAP_SL_MULT
            sl_dist = abs(current_price - sl)
            _tp_c6 = current_price + (sl_dist * config.BEAR_HUNTER_TP_RR)
            _rr_c6 = abs(_tp_c6 - current_price) / max(abs(current_price - sl), 1e-8)
            
            raw_vars = locals()
            
            _scores_c6 = build_trend_scores(
                adx=None, adx_prev=None, price=current_price, ema_fast=vwap_val, ema_mid=None, ema_slow=None,
                rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                volume=last_4h.get('volume', 0), vol_sma=None, dollar_vol=last_4h.get('volume', 0) * current_price,
                rr=_rr_c6, has_engulfing=True, regime="BULL", macro_aligned=btc_ok,
                consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO"
            )
            _conv_c6 = calculate_conviction(_scores_c6, ctx=ctx)
            if _conv_c6.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({
                    "raw_indicators": _extract_raw_indicators(raw_vars),
                    "ticker": symbol, "market": "KRIPTO",
                    "strategy": "KRİPTO 6: VWAP KURUMSAL MIKNATISI", "signal": "AL",
                    "entry_price": current_price, "sl": sl, "tp": _tp_c6,
                    "conviction_score": _conv_c6.total_score, "conviction_grade": _conv_c6.grade,
                    "conviction_details": _conv_c6.component_scores, "position_size_pct": _conv_c6.position_size_pct,
                    "reason": (
                        f"⚓ VWAP Bounce (Kurumsal Mıknatıs)!\n"
                        f"4S Anchored VWAP: {vwap_val:.4f}\n"
                        f"Pin Bar onayı: VWAP'a değip sıçradı.\n"
                        f"BTC > EMA20 (Piyasa izni var ✅)"
                    ) + _conv_c6.to_reason_suffix()
                })
    return signals


def _check_crypto_7_obv(ctx):
    signals = []
    symbol = ctx["symbol"]
    last_1d = ctx["last_1d"]
    current_price = ctx["current_price"]
    df_1d = ctx["df_1d"]

    obv_ok, obv_box_high, obv_box_low = detect_obv_accumulation(df_1d, max_change_pct=config.CRYPTO_OBV_ACC_MAX_CHANGE_PCT)
    if obv_ok and obv_box_high is not None:
        btcdom_trend = get_btc_dominance_trend()
        if btcdom_trend != "UP":
            sl = (obv_box_high + obv_box_low) / 2
            cmf_val = calculate_cmf(df_1d)
            cmf_label = f"CMF: {cmf_val:.3f} ✅" if cmf_val is not None else "CMF: N/A"
            sl_dist = abs(current_price - sl)
            _tp_c7 = current_price + (sl_dist * config.BEAR_HUNTER_TP_RR)
            _rr_c7 = abs(_tp_c7 - current_price) / max(abs(current_price - sl), 1e-8)
            
            raw_vars = locals()
            
            vol_sma_col = 'vol_sma_20'
            if vol_sma_col not in df_1d.columns:
                df_1d = df_1d.copy()
                df_1d[vol_sma_col] = df_1d['volume'].rolling(window=20).mean()
            daily_vol_sma = df_1d[vol_sma_col].iloc[-1] if not df_1d.empty else None

            _scores_c7 = build_breakout_scores(
                bb_width=None, price=current_price,
                ema_fast=last_1d.get('EMA_8'), ema_mid=last_1d.get('EMA_21'), ema_slow=None,
                volume=last_1d.get('volume', 0), vol_sma=daily_vol_sma, dollar_vol=last_1d.get('volume', 0) * current_price,
                rr=_rr_c7, regime="BULL",
                macro_aligned=(btcdom_trend != 'UP'), consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                rsi=last_1d.get('RSI_14'),
                rsi_prev=df_1d['RSI_14'].iloc[-2] if (len(df_1d) >= 2 and 'RSI_14' in df_1d.columns) else last_1d.get('RSI_14'),
                rsi_1h=None,
                is_long=True,
                strategy_type="TREND_BREAKOUT",
                sma200_1d=last_1d.get('SMA_200') if last_1d is not None else None,
                cmf=cmf_val if cmf_val is not None else 0.0,
                has_engulfing=False
            )
            _conv_c7 = calculate_conviction(_scores_c7, ctx=ctx)
            if _conv_c7.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({
                    "raw_indicators": _extract_raw_indicators(raw_vars),
                    "ticker": symbol, "market": "KRIPTO",
                    "strategy": "KRİPTO 7: SESSİZ BİRİKİM RADARI (OBV)", "signal": "AL",
                    "entry_price": current_price, "sl": sl, "tp": _tp_c7,
                    "conviction_score": _conv_c7.total_score, "conviction_grade": _conv_c7.grade,
                    "conviction_details": _conv_c7.component_scores, "position_size_pct": _conv_c7.position_size_pct,
                    "reason": (
                        f"🕵️ Sessiz Birikim + CMF Onaylı!\n"
                        f"1G 20 gün yatay kutu: {obv_box_low:.4f} - {obv_box_high:.4f}\n"
                        f"OBV yeni tepeler + {cmf_label}\n"
                        f"BTC Dominans '{btcdom_trend}' (Altcoin dostu ✅)"
                    ) + _conv_c7.to_reason_suffix()
                })
    return signals


def _check_crypto_sniper_1h_long(ctx_1h):
    signals = []
    symbol = ctx_1h["symbol"]
    current_price = ctx_1h["current_price"]
    btc_ok = ctx_1h["btc_ok"]
    df_1h_sniper = ctx_1h["df_1h_sniper"]
    last_1h_s = ctx_1h["last_1h_s"]
    prev_1h_s = ctx_1h["prev_1h_s"]
    guarded_vol_sma = ctx_1h["guarded_vol_sma"]
    bbw = ctx_1h["bbw"]
    kcw = ctx_1h["kcw"]
    bb_pct = ctx_1h["bb_pct"]
    bbl = ctx_1h["bbl"]

    has_fvg_long, _, _ = sniper_detect_fvg(df_1h_sniper, df_1h_sniper['high'].iloc[-1], df_1h_sniper['low'].iloc[-1], direction="bullish")
    swing_lows_s = sniper_find_swing_points(df_1h_sniper, point_type="low")
    sweep_ok_long, _ = sniper_detect_sweep(df_1h_sniper, swing_lows_s, point_type="low")
    has_sfp_long = sweep_ok_long
    
    sl_long = max(bbl * config.CRYPTO_SQUEEZE_SL_BBL_MULT, current_price * config.CRYPTO_SQUEEZE_SL_MIN_MULT)
    _tp_sn_long = current_price + config.BEAR_HUNTER_TP_RR * (current_price - sl_long)
    _rr_sn_long = abs(_tp_sn_long - current_price) / max(abs(current_price - sl_long), 1e-8)
    
    is_nan_ind = (pd.isna(last_1h_s.get('volume', float('nan'))) or pd.isna(current_price))
    blocked, block_reason = check_hard_blocks(
        volume=last_1h_s.get('volume', 0),
        price=current_price,
        vol_sma=guarded_vol_sma,
        is_quarantined=False,
        is_circuit_open=False,
        is_darth_maul_flag=False,
        sl_direction_ok=(sl_long < current_price),
        rr_ratio=_rr_sn_long,
        consecutive_sl=_get_consecutive_sl(symbol),
        is_core_indicators_nan=is_nan_ind,
        min_volume_usd=50_000
    )
    if blocked:
        return signals
        
    _scores_sn_long = build_sniper_scores(
        price=current_price, ema_fast=last_1h_s.get(f'EMA_{config.IND_EMA_FAST}'), ema_mid=last_1h_s.get(f'EMA_{config.IND_EMA_21}'), ema_slow=None,
        rsi=last_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'), rsi_prev=prev_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'),
        volume=last_1h_s.get('volume', 0), vol_sma=guarded_vol_sma, dollar_vol=last_1h_s.get('volume', 0) * current_price,
        rr=_rr_sn_long, regime="BULL" if btc_ok else "BEAR",
        macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol),
        bbw=bbw, kcw=kcw, pb=bb_pct, fvg_present=has_fvg_long, sfp_present=has_sfp_long,
        market="KRIPTO", is_long=True
    )
    _conv_sn_long = calculate_conviction(_scores_sn_long, weights=SNIPER_CRYPTO_WEIGHTS, ctx=ctx_1h)
    if _conv_sn_long.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM):
        raw_vars = locals()
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO",
            "strategy": "KRİPTO 6: KESKİN NİŞANCI (SNIPER)", "signal": "AL",
            "entry_price": current_price, "sl": sl_long, "tp": _tp_sn_long,
            "conviction_score": _conv_sn_long.total_score, "conviction_grade": _conv_sn_long.grade,
            "conviction_details": _conv_sn_long.component_scores, "position_size_pct": _conv_sn_long.position_size_pct,
            "reason": (
                f"🎯 Keskin Nişancı LONG!\n"
                f"Kanunlar: Squeeze: {_scores_sn_long['bbw_squeeze']:.1f}, %B: {_scores_sn_long['percent_b']:.1f}, FVG/SFP: {_scores_sn_long['fvg_sfp']:.1f}\n"
                f"SL: Bollinger Alt Band Altı ({sl_long:.2f})"
            ) + _conv_sn_long.to_reason_suffix()
        })
    return signals


def _check_crypto_sniper_1h_short(ctx_1h):
    signals = []
    symbol = ctx_1h["symbol"]
    current_price = ctx_1h["current_price"]
    btc_ok = ctx_1h["btc_ok"]
    df_1h_sniper = ctx_1h["df_1h_sniper"]
    last_1h_s = ctx_1h["last_1h_s"]
    prev_1h_s = ctx_1h["prev_1h_s"]
    guarded_vol_sma = ctx_1h["guarded_vol_sma"]
    bbw = ctx_1h["bbw"]
    kcw = ctx_1h["kcw"]
    bb_pct = ctx_1h["bb_pct"]
    bbu = ctx_1h["bbu"]

    funding_rate = get_funding_rate(symbol)
    cmf_1h = last_1h_s.get('CMF_20')
    
    has_fvg_short, _, _ = sniper_detect_fvg(df_1h_sniper, df_1h_sniper['high'].iloc[-1], df_1h_sniper['low'].iloc[-1], direction="bearish")
    swing_highs_s = sniper_find_swing_points(df_1h_sniper, point_type="high")
    sweep_ok_short, _ = sniper_detect_sweep(df_1h_sniper, swing_highs_s, point_type="high")
    has_sfp_short = sweep_ok_short
    
    sl_short = max(bbu * config.CRYPTO_SQUEEZE_SHORT_SL_BBU_MULT, current_price * config.CRYPTO_SQUEEZE_SHORT_SL_MAX_MULT)
    _tp_sn_short = current_price - config.BEAR_HUNTER_TP_RR * (sl_short - current_price)
    _rr_sn_short = abs(_tp_sn_short - current_price) / max(abs(sl_short - current_price), 1e-8)
    
    is_nan_ind = (pd.isna(last_1h_s.get('volume', float('nan'))) or pd.isna(current_price))
    blocked, block_reason = check_hard_blocks(
        volume=last_1h_s.get('volume', 0),
        price=current_price,
        vol_sma=guarded_vol_sma,
        is_quarantined=False,
        is_circuit_open=False,
        is_darth_maul_flag=False,
        sl_direction_ok=(sl_short > current_price),
        rr_ratio=_rr_sn_short,
        consecutive_sl=_get_consecutive_sl(symbol),
        is_core_indicators_nan=is_nan_ind,
        min_volume_usd=50_000
    )
    if blocked:
        return signals
        
    _scores_sn_short = build_sniper_scores(
        price=current_price, ema_fast=last_1h_s.get(f'EMA_{config.IND_EMA_FAST}'), ema_mid=last_1h_s.get(f'EMA_{config.IND_EMA_21}'), ema_slow=None,
        rsi=last_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'), rsi_prev=prev_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'),
        volume=last_1h_s.get('volume', 0), vol_sma=guarded_vol_sma, dollar_vol=last_1h_s.get('volume', 0) * current_price,
        rr=_rr_sn_short, regime="BEAR" if not btc_ok else "BULL",
        macro_aligned=not btc_ok, consecutive_sl=_get_consecutive_sl(symbol),
        bbw=bbw, kcw=kcw, pb=bb_pct, fvg_present=has_fvg_short, sfp_present=has_sfp_short,
        market="KRIPTO", is_long=False, funding_rate=funding_rate,
        cmf=cmf_1h if cmf_1h is not None and not math.isnan(cmf_1h) else 0.0
    )
    _conv_sn_short = calculate_conviction(_scores_sn_short, weights=SNIPER_CRYPTO_WEIGHTS, ctx=ctx_1h)
    if _conv_sn_short.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM):
        raw_vars = locals()
        signals.append({
            "raw_indicators": _extract_raw_indicators(raw_vars),
            "ticker": symbol, "market": "KRIPTO",
            "strategy": "KRİPTO SHORT 5: KESKİN NİŞANCI (SNIPER)", "signal": "SAT",
            "entry_price": current_price, "sl": sl_short, "tp": _tp_sn_short,
            "conviction_score": _conv_sn_short.total_score, "conviction_grade": _conv_sn_short.grade,
            "conviction_details": _conv_sn_short.component_scores, "position_size_pct": _conv_sn_short.position_size_pct,
            "reason": (
                f"🎯 Keskin Nişancı SHORT!\n"
                f"Kanunlar: Squeeze: {_scores_sn_short['bbw_squeeze']:.1f}, %B: {_scores_sn_short['percent_b']:.1f}, FVG/SFP: {_scores_sn_short['fvg_sfp']:.1f}\n"
                f"SL: ~%5-7 Dinamik Stop ({sl_short:.2f})"
            ) + _conv_sn_short.to_reason_suffix()
        })
    return signals


def _check_crypto_sniper_1h(ctx):
    signals = []
    symbol = ctx["symbol"]
    current_price = ctx["current_price"]
    btc_ok = ctx["btc_ok"]

    df_1h_sniper = get_crypto_1h_data(symbol)
    if df_1h_sniper is None or df_1h_sniper.empty:
        return signals

    df_1h_sniper = df_1h_sniper.copy()
    df_1h_sniper.ta.kc(length=20, scalar=1.5, append=True)
    df_1h_sniper.ta.bbands(length=20, std=2.0, append=True)
    df_1h_sniper.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_1h_sniper.ta.ema(length=config.IND_EMA_FAST, append=True)
    df_1h_sniper.ta.ema(length=config.IND_EMA_21, append=True)
    df_1h_sniper.ta.cmf(length=20, append=True)
    df_1h_sniper['vol_sma_20'] = ta.sma(df_1h_sniper['volume'], length=config.IND_VOL_SMA_LENGTH)
    
    kc_upper_col = [c for c in df_1h_sniper.columns if 'KCU' in c]
    if not kc_upper_col:
        return signals
    kc_lower_col = [c for c in df_1h_sniper.columns if 'KCL' in c]
    if not kc_lower_col:
        return signals
    bb_upper_col = [c for c in df_1h_sniper.columns if 'BBU' in c]
    if not bb_upper_col:
        return signals
    bb_lower_col = [c for c in df_1h_sniper.columns if 'BBL' in c]
    if not bb_lower_col:
        return signals
    bb_mid_col = [c for c in df_1h_sniper.columns if 'BBM' in c]
    if not bb_mid_col:
        return signals
    bb_pct_col = [c for c in df_1h_sniper.columns if 'BBP' in c]
    if not bb_pct_col:
        return signals

    last_1h_s = df_1h_sniper.iloc[-1]
    prev_1h_s = last_1h_s
    if len(df_1h_sniper) >= 2:
        prev_1h_s = df_1h_sniper.iloc[-2]
    
    bbu = last_1h_s[bb_upper_col[0]]
    bbl = last_1h_s[bb_lower_col[0]]
    bbm = last_1h_s[bb_mid_col[0]]
    
    bbw = 0.0
    kcw = 0.0
    if bbm != 0:
        bbw = (bbu - bbl) / bbm
        kcw = (last_1h_s[kc_upper_col[0]] - last_1h_s[kc_lower_col[0]]) / bbm
    
    bb_pct = last_1h_s[bb_pct_col[0]]
    guarded_vol_sma = _apply_volume_sma_guard(df_1h_sniper, last_1h_s.get('vol_sma_20', 0))

    ctx_1h = {
        "symbol": symbol,
        "current_price": current_price,
        "btc_ok": btc_ok,
        "df_1h_sniper": df_1h_sniper,
        "last_1h_s": last_1h_s,
        "prev_1h_s": prev_1h_s,
        "guarded_vol_sma": guarded_vol_sma,
        "bbw": bbw,
        "kcw": kcw,
        "bb_pct": bb_pct,
        "bbl": bbl,
        "bbu": bbu
    }

    signals.extend(_check_crypto_sniper_1h_long(ctx_1h))
    signals.extend(_check_crypto_sniper_1h_short(ctx_1h))
    return signals


# KRİPTO STRATEJİ MOTORU
def analyze_strategies_crypto(symbol, df_1d, df_4h, btc_ok=False, btc_sniper_bias=0, metrics_collector=None):
    signals = []

    if len(df_1d) < 50 or len(df_4h) < 20:
        return signals

    # Pandas Mutability koruması
    df_1d = df_1d.copy()
    df_4h = df_4h.copy()

    df_1d.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_1d.ta.ema(length=config.IND_EMA_MID, append=True)
    df_1d.ta.ema(length=config.IND_EMA_SLOW, append=True)
    df_1d.ta.bbands(length=config.IND_BBANDS_LENGTH, std=config.IND_BBANDS_STD, append=True)
    if len(df_1d) >= 200:
        df_1d.ta.sma(length=200, append=True)

    df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_4h.ta.ema(length=config.IND_EMA_MID, append=True)
    df_4h.ta.ema(length=config.IND_EMA_SLOW, append=True)
    df_4h.ta.adx(length=config.IND_ADX_LENGTH, append=True)
    df_4h.ta.atr(length=config.IND_ATR_LENGTH, append=True)
    df_4h.ta.cmf(length=20, append=True)
    df_4h['vol_sma_20'] = ta.sma(df_4h['volume'], length=config.IND_VOL_SMA_LENGTH)

    last_1d = df_1d.iloc[-1]
    last_4h = df_4h.iloc[-1]
    current_price = last_4h['close']

    # --- DYNAMIC FILTERS (Variant F: Pure Math) ---
    body = abs(last_4h['close'] - last_4h['open'])
    upper_wick = last_4h['high'] - max(last_4h['close'], last_4h['open'])
    lower_wick = min(last_4h['close'], last_4h['open']) - last_4h['low']
    is_whipsaw = (upper_wick > body * 2.0) or (lower_wick > body * 2.0)
    
    adx_val = last_4h.get('ADX_14', 0)
    if pd.isna(adx_val): adx_val = 0
    rsi_val = last_4h.get('RSI_14', 50)
    if pd.isna(rsi_val): rsi_val = 50
        
    ema_20_val = last_4h.get('EMA_20', 0)
    ema_50_val = last_4h.get('EMA_50', 0)
    ema_diff_pct = abs(ema_20_val - ema_50_val) / current_price if current_price > 0 else 0
    candle_body_pct = body / current_price if current_price > 0 else 0
        
    # Önceki Varyans D Kuralları
    # HARD FILTERS REMOVED: Whipsaw, ADX, EMA diff logic delegated to conviction_scorer (Fuzzy)
    # if is_whipsaw or adx_val > 45 or ema_diff_pct > 0.015:
    #     return signals 
        
    # Yeni Varyans F (Pure Math) Kuralları
    # HARD FILTERS REMOVED: ADX, RSI, Candle Body pure math block limits delegated to fuzzy logic
    # if adx_val < 14.2 or rsi_val > 57.82 or candle_body_pct > 0.0257:
    #     return signals
        
    dynamic_atr_mult = 2.0 if adx_val > 25 else 1.2
    # -----------------------------------------

    if metrics_collector is not None:
        metrics_collector[symbol] = {
            "Symbol": symbol, "Market": "KRIPTO", "Price": current_price,
            "1D RSI": round(last_1d.get("RSI_14", 0), 2) if pd.notna(last_1d.get("RSI_14")) else None,
            "4H ADX": round(last_4h.get("ADX_14", 0), 2) if pd.notna(last_4h.get("ADX_14")) else None,
            "1H RSI": None,
            "1D SMA 50": round(last_1d.get("EMA_50", 0), 2) if pd.notna(last_1d.get("EMA_50")) else None,
            "1D Trend SMA": round(get_trend_sma(last_1d), 2) if pd.notna(get_trend_sma(last_1d)) else None,
            "Trend": "Bullish" if last_1d.get("EMA_20", 0) > last_1d.get("EMA_50", float('inf')) else "Bearish",
            "1H Volume": last_4h.get("volume")
        }

    ctx = {
        "symbol": symbol, "last_1d": last_1d, "last_4h": last_4h,
        "current_price": current_price, "df_1d": df_1d, "df_4h": df_4h,
        "btc_ok": btc_ok, "btc_sniper_bias": btc_sniper_bias,
        "dynamic_atr_mult": dynamic_atr_mult
    }

    signals.extend(_check_crypto_1_liquidation(ctx))
    signals.extend(_check_crypto_2_mega_trend(ctx))
    signals.extend(_check_crypto_3_breakout(ctx))
    signals.extend(_check_crypto_shorts(ctx))
    signals.extend(_check_crypto_4_sniper_ote(ctx))
    signals.extend(_check_crypto_5_vol_squeeze(ctx))
    signals.extend(_check_crypto_6_vwap(ctx))
    signals.extend(_check_crypto_7_obv(ctx))
    signals.extend(_check_crypto_sniper_1h(ctx))

    return signals
