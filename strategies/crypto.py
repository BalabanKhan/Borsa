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
import config
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
    get_crypto_data_cached, get_crypto_1h_data, get_emtia_1h_data, clear_cycle_cache, purge_expired_cache,
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
    build_sniper_scores, SNIPER_CRYPTO_WEIGHTS
)



from .helpers import _extract_raw_indicators, _apply_volume_sma_guard, _is_meaningful_volume, _get_consecutive_sl, _has_absolute_hourly_volume, _apply_rr_filter, _apply_regime_filter, _resolve_dual_signals, _adx_momentum_ok, _is_darth_maul, _is_unclosed_candle, _get_darth_maul_ratio, _is_funding_safe_for_short
# ════════════════════════════════════════
def analyze_strategies_crypto(symbol, df_1d, df_4h, btc_ok=False, btc_sniper_bias=0, metrics_collector=None):
    signals = []

    if len(df_1d) < 50 or len(df_4h) < 20:
        return signals

    # Pandas Mutability koruması: kaynak DataFrame'leri kirletme
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
            "1D SMA 200": round(last_1d.get("SMA_200", 0), 2) if pd.notna(last_1d.get("SMA_200")) else None,
            "Trend": "Bullish" if last_1d.get("EMA_20", 0) > last_1d.get("EMA_50", float('inf')) else "Bearish",
            "1H Volume": last_4h.get("volume")
        }


    # KRİPTO 1: LİKİDASYON VE DİP AVCILIĞI
    if not is_weekend_fakeout_time():
        if not pd.isna(last_4h.get('RSI_14')) and not pd.isna(last_4h.get('EMA_20')) and not pd.isna(last_4h.get('vol_sma_20')):
            # DIP_RSI_1D_EMA50_ALIGN_ENABLED: Kripto 1G Fiyat > EMA50 trend hizalamasını sorgular (Long yönlü teyit)
            ema_50_1d = last_1d.get(f'EMA_{config.IND_EMA_SLOW}') if last_1d is not None else None
            trend_aligned = not config.DIP_RSI_1D_EMA50_ALIGN_ENABLED or (ema_50_1d is not None and not pd.isna(ema_50_1d) and current_price > ema_50_1d)

            if trend_aligned:
                div_found, _, _, _, _ = detect_bullish_divergence(df_4h)
                if div_found:
                    # RED-07: Anlamlı hacim kontrolü + RED-06: Darth Maul filtresi
                    guarded_vol_sma = _apply_volume_sma_guard(df_4h, last_4h['vol_sma_20'])
                    
                    # DIP_VOLUME_SPIKE_REQUIRED: dip dönüş mumunda hacim patlaması şartını sorgular (Volume Spike)
                    volume_spike_ok = not config.DIP_VOLUME_SPIKE_REQUIRED or (last_4h['volume'] >= guarded_vol_sma * config.DIP_VOLUME_SPIKE_MULT)
                    
                    if volume_spike_ok and _is_meaningful_volume(last_4h['volume'], guarded_vol_sma, current_price, "KRIPTO"):
                        if current_price > last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price > last_4h['open']:
                            oi_crash = fetch_crypto_oi_crash(symbol)
                            if oi_crash:
                                lowest_wick = last_4h['low']
                                sl = lowest_wick * 0.99
                                sl_dist = abs(current_price - sl)
                                tp = current_price + (sl_dist * 3.0)
                                _rr_c1 = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                                _prev_4h = df_4h.iloc[-2] if len(df_4h) >= 2 else last_4h
                                dm_ratio = _get_darth_maul_ratio(last_4h)
                                _scores_c1 = build_dip_scores(
                                    rsi_daily=last_4h.get('RSI_14', 50), rsi_hourly=last_4h.get('RSI_14', 50),
                                    rsi_prev=_prev_4h.get('RSI_14', 50),
                                    price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'),
                                    volume=last_4h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_4h['volume'] * current_price,
                                    rr=_rr_c1, has_engulfing=False, regime="BULL",
                                    macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                                    dg_is_darth_maul=dm_ratio
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
        # TREND_BB_SQUEEZE_BLOCKED: Dar bant squeeze içindeyken trend takibini bloke eder (Chop market engeli)
        in_squeeze = False
        if config.TREND_BB_SQUEEZE_BLOCKED:
            bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
            bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
            bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]
            if bb_upper_col and bb_lower_col and bb_mid_col:
                bbu = last_1d[bb_upper_col[0]]
                bbl = last_1d[bb_lower_col[0]]
                bbm = last_1d[bb_mid_col[0]]
                bb_width = (bbu - bbl) / bbm if not math.isclose(float(bbm), 0.0, abs_tol=1e-8) else 1
                if bb_width < 0.15:
                    in_squeeze = True

        if not in_squeeze and last_1d[f'EMA_{config.IND_EMA_MID}'] > last_1d[f'EMA_{config.IND_EMA_SLOW}'] and last_1d['close'] > last_1d[f'EMA_{config.IND_EMA_MID}']:
            atr_col = 'ATRr_14' if 'ATRr_14' in last_4h.index else 'ATR_14'
            if not pd.isna(last_4h.get('ADX_14')) and not pd.isna(last_4h.get('EMA_20')) and not pd.isna(last_4h.get(atr_col)):
                if last_4h['ADX_14'] > 25:
                    # RED-02: ADX olgunlaşma kontrolü
                    if last_4h['ADX_14'] > ADX_TOO_LATE:
                        pass  # Trend olgunlaşmış, geç kaldın
                    elif last_4h['low'] <= last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price > last_4h[f'EMA_{config.IND_EMA_MID}'] and current_price > last_4h['open']:
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
                                    sl_dist = abs(current_price - sl)
                                    _tp_c2 = current_price + (sl_dist * 3.0)
                                    _rr_c2 = abs(_tp_c2 - current_price) / max(abs(current_price - sl), 1e-8)
                                    _adx_prev_c2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                                    _prev_4h_c2 = df_4h.iloc[-2] if len(df_4h) >= 2 else last_4h
                                    dm_ratio = _get_darth_maul_ratio(last_4h)
                                    _scores_c2 = build_trend_scores(
                                        adx=last_4h['ADX_14'], adx_prev=_adx_prev_c2,
                                        price=current_price, ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                        rsi=last_4h.get('RSI_14'), rsi_prev=_prev_4h_c2.get('RSI_14'),
                                        volume=last_4h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_4h['volume'] * current_price,
                                        rr=_rr_c2, has_engulfing=False, regime="BULL",
                                        macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                                        dg_is_darth_maul=dm_ratio
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
                        local_high = df_4h['high'].tail(15).max()
                        # BREAKOUT_RETEST_REQUIRED: direnç kırılımı sonrası retest/pullback aralığı teyidi
                        retest_ok = True
                        if config.BREAKOUT_RETEST_REQUIRED:
                            max_limit = local_high * (1.0 + (config.BREAKOUT_RETEST_TOLERANCE_PCT / 100.0))
                            if not (local_high <= current_price <= max_limit):
                                retest_ok = False

                        if retest_ok and current_price > local_high and last_4h['low'] <= local_high * 0.99 and current_price > last_4h['open']:
                            has_unlocks = check_token_unlocks(symbol)
                            funding_rate = get_funding_rate(symbol)
                            if not has_unlocks and funding_rate <= 0.0:
                                # AM-03: Mutlak saatlik hacim eşiği
                                if _has_absolute_hourly_volume(last_4h['volume'], current_price, "KRIPTO"):
                                    sl = current_price * 0.95
                                    sl_dist = abs(current_price - sl)
                                    _tp_c3 = current_price + (sl_dist * 3.0)
                                    _rr_c3 = abs(_tp_c3 - current_price) / max(abs(current_price - sl), 1e-8)
                                    dm_ratio = _get_darth_maul_ratio(last_4h)
                                    _scores_c3 = build_breakout_scores(
                                        bb_width=last_width, price=current_price,
                                        ema_fast=last_4h.get('EMA_20'), ema_mid=last_4h.get('EMA_50'), ema_slow=None,
                                        volume=last_4h['volume'], vol_sma=last_4h['vol_sma_20'], dollar_vol=last_4h['volume'] * current_price,
                                        rr=_rr_c3, regime="BULL",
                                        macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                                        dg_is_darth_maul=dm_ratio
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
        if not pd.isna(last_4h.get('RSI_14')) and last_4h[f'RSI_{config.IND_RSI_LENGTH}'] > config.SHORT_RSI_OVERBOUGHT_LIMIT:
            # SHORT_TREND_ALIGN_REQUIRED: Short yönlü trend hizalamasını sorgular (fiyatın 50 EMA / 200 SMA altında olması)
            trend_aligned = True
            if config.SHORT_TREND_ALIGN_REQUIRED:
                ema_50_1d = last_1d.get(f'EMA_{config.IND_EMA_SLOW}')
                sma_200_1d = last_1d.get('SMA_200')
                if ema_50_1d is not None and not pd.isna(ema_50_1d) and current_price >= ema_50_1d:
                    trend_aligned = False
                if sma_200_1d is not None and not pd.isna(sma_200_1d) and current_price >= sma_200_1d:
                    trend_aligned = False

            if trend_aligned:
                funding_rate = get_funding_rate(symbol)
                # AM-04: Fonlama Vampiri Kalkanı — negatif fonlamada short YASAK
                if funding_rate is not None and _is_funding_safe_for_short(funding_rate) and funding_rate >= 0.01:
                    div_found, _, _, _, _ = detect_bearish_divergence(df_4h)
                    swing_lows = sniper_find_swing_points(df_4h, point_type="low")
                    msb_ok, msb_low, msb_idx = sniper_detect_msb(df_4h, swing_lows, point_type="low")
                    if div_found or msb_ok:
                        sl = last_4h['high'] * 1.02
                        sl_dist = abs(sl - current_price)
                        tp = current_price - (sl_dist * 3.0)
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
                                "reason": f"4S RSI>{config.SHORT_RSI_OVERBOUGHT_LIMIT:.0f} ve {trigger_reason}. Fonlama (+%{funding_rate:.4f}) pozitif." + _conv_s1.to_reason_suffix()
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
                            sl_dist = abs(sl - current_price)
                            tp = current_price - (sl_dist * 3.0)
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
                                sl_dist = abs(sl - current_price)
                                tp = current_price - (sl_dist * 3.0)
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
                        fvg_ok = not config.SMC_FVG_REQUIRED or has_fvg
                        
                        if fvg_ok:
                            # SMC LTF MSB Teyidi Kontrolü (1H grafikte MSB aranır)
                            ltf_confirm = True
                            df_1h_crypto = None
                            if config.SMC_LTF_MSB_CONFIRM:
                                df_1h_crypto = get_crypto_1h_data(symbol)
                                if df_1h_crypto is not None and not df_1h_crypto.empty:
                                    df_1h_crypto = df_1h_crypto.copy()
                                    df_1h_crypto.ta.ema(length=config.IND_EMA_FAST, append=True)
                                    df_1h_crypto.ta.ema(length=config.IND_EMA_21, append=True)
                                    swing_highs_1h = sniper_find_swing_points(df_1h_crypto, point_type="high", neighbors=2)
                                    ltf_msb_ok, _, _ = sniper_detect_msb(df_1h_crypto, swing_highs_1h, point_type="high")
                                    if not ltf_msb_ok:
                                        ltf_confirm = False
                                else:
                                    ltf_confirm = False
                            
                            if ltf_confirm:
                                funding_rate = get_funding_rate(symbol)
                                if funding_rate <= 0.0:
                                    sl = sweep_low * 0.995
                                    sl_dist = max(current_price - sl, 1e-8)
                                    tp = current_price + (sl_dist * 3.0)
                                    fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
                                    _rr_c4l = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                                    
                                    # 1H verisi varsa onun EMA'larını kullan
                                    ema_fast_val = None
                                    ema_mid_val = None
                                    if config.SMC_LTF_MSB_CONFIRM and df_1h_crypto is not None and not df_1h_crypto.empty:
                                        ema_fast_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_FAST}')
                                        ema_mid_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_21}')
                                    else:
                                        ema_fast_val = last_4h.get('EMA_20')
                                        ema_mid_val = last_4h.get('EMA_50')

                                    _scores_c4l = build_breakout_scores(
                                        bb_width=None, price=current_price,
                                        ema_fast=ema_fast_val, ema_mid=ema_mid_val, ema_slow=None,
                                        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
                                        dollar_vol=last_4h['volume'] * current_price,
                                        rr=_rr_c4l, regime="BULL", macro_aligned=True,
                                        consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                                    )
                                    if has_fvg:
                                        _scores_c4l["engulfing"] = min(100.0, _scores_c4l["engulfing"] + config.SMC_FVG_BONUS)
                                        
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
                        fvg_ok = not config.SMC_FVG_REQUIRED or has_fvg
                        
                        if fvg_ok:
                            # SMC LTF MSB Teyidi Kontrolü (1H grafikte MSB aranır)
                            ltf_confirm = True
                            df_1h_crypto = None
                            if config.SMC_LTF_MSB_CONFIRM:
                                df_1h_crypto = get_crypto_1h_data(symbol)
                                if df_1h_crypto is not None and not df_1h_crypto.empty:
                                    df_1h_crypto = df_1h_crypto.copy()
                                    df_1h_crypto.ta.ema(length=config.IND_EMA_FAST, append=True)
                                    df_1h_crypto.ta.ema(length=config.IND_EMA_21, append=True)
                                    swing_lows_1h = sniper_find_swing_points(df_1h_crypto, point_type="low", neighbors=2)
                                    ltf_msb_ok, _, _ = sniper_detect_msb(df_1h_crypto, swing_lows_1h, point_type="low")
                                    if not ltf_msb_ok:
                                        ltf_confirm = False
                                else:
                                    ltf_confirm = False
                                    
                            if ltf_confirm:
                                funding_rate = get_funding_rate(symbol)
                                if funding_rate >= 0.0:
                                    sl = sweep_high * 1.005
                                    sl_dist = max(sl - current_price, 1e-8)
                                    tp = current_price - (sl_dist * 3.0)
                                    fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
                                    _rr_c4s = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                                    _adx_prev_c4s = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                                    
                                    # 1H verisi varsa onun EMA'larını kullan
                                    ema_fast_val = None
                                    ema_mid_val = None
                                    if config.SMC_LTF_MSB_CONFIRM and df_1h_crypto is not None and not df_1h_crypto.empty:
                                        ema_fast_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_FAST}')
                                        ema_mid_val = df_1h_crypto.iloc[-1].get(f'EMA_{config.IND_EMA_21}')
                                    else:
                                        ema_fast_val = last_4h.get('EMA_20')
                                        ema_mid_val = last_4h.get('EMA_50')

                                    _scores_c4s = build_short_scores(
                                        adx=last_4h.get('ADX_14'), adx_prev=_adx_prev_c4s,
                                        price=current_price, ema_fast=ema_fast_val, ema_mid=ema_mid_val, ema_slow=None,
                                        rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
                                        volume=last_4h['volume'], vol_sma=last_4h.get('vol_sma_20'),
                                        dollar_vol=last_4h['volume'] * current_price,
                                        rr=_rr_c4s, has_engulfing=False, regime="BEAR", macro_aligned=True,
                                        consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                                    )
                                    if has_fvg:
                                        _scores_c4s["engulfing"] = min(100.0, _scores_c4s["engulfing"] + config.SMC_FVG_BONUS)
                                        
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
                    sl_dist = abs(current_price - sl)
                    tp = current_price + (sl_dist * 3.0)
                    sig_type = "AL"
                else:
                    sl = max(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                    sl_dist = abs(sl - current_price)
                    tp = current_price - (sl_dist * 3.0)
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
                sl_dist = abs(current_price - sl)
                _tp_c6 = current_price + (sl_dist * 3.0)
                _rr_c6 = abs(_tp_c6 - current_price) / max(abs(current_price - sl), 1e-8)
                _scores_c6 = build_trend_scores(
                    adx=None, adx_prev=None, price=current_price, ema_fast=vwap_val, ema_mid=None, ema_slow=None,
                    rsi=last_4h.get('RSI_14'), rsi_prev=df_4h.iloc[-2].get('RSI_14') if len(df_4h) >= 2 else None,
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
            sl = (obv_box_high + obv_box_low) / 2  # RED-12: Kutu ortası SL
            cmf_val = calculate_cmf(df_1d)
            cmf_label = f"CMF: {cmf_val:.3f} ✅" if cmf_val is not None else "CMF: N/A"
            sl_dist = abs(current_price - sl)
            _tp_c7 = current_price + (sl_dist * 3.0)
            _rr_c7 = abs(_tp_c7 - current_price) / max(abs(current_price - sl), 1e-8)
            _scores_c7 = build_dip_scores(
                rsi_daily=last_1d.get('RSI_14'), rsi_hourly=None, rsi_prev=None,
                price=current_price, ema_fast=last_1d.get('EMA_8'), ema_mid=last_1d.get('EMA_21'),
                volume=last_1d.get('volume', 0), vol_sma=None, dollar_vol=last_1d.get('volume', 0) * current_price,
                rr=_rr_c7, has_engulfing=False, regime="BULL",
                macro_aligned=(btcdom_trend != 'UP'), consecutive_sl=_get_consecutive_sl(symbol), market="KRIPTO",
                cmf=cmf_val if cmf_val is not None else 0.0
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

    # ════════════════════════════════════════
    # KRİPTO 6: KESKİN NİŞANCI (SNIPER)
    # ════════════════════════════════════════
    
    df_1h_sniper = get_crypto_1h_data(symbol)
    if df_1h_sniper is not None and not df_1h_sniper.empty:
        df_1h_sniper = df_1h_sniper.copy()
        df_1h_sniper.ta.kc(length=20, scalar=1.5, append=True)
        df_1h_sniper.ta.bbands(length=20, std=2.0, append=True)
        df_1h_sniper.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
        df_1h_sniper.ta.ema(length=config.IND_EMA_FAST, append=True)
        df_1h_sniper.ta.ema(length=config.IND_EMA_21, append=True)
        df_1h_sniper['vol_sma_20'] = ta.sma(df_1h_sniper['volume'], length=config.IND_VOL_SMA_LENGTH)
        
        kc_upper_col = [c for c in df_1h_sniper.columns if 'KCU' in c]
        kc_lower_col = [c for c in df_1h_sniper.columns if 'KCL' in c]
        bb_upper_col = [c for c in df_1h_sniper.columns if 'BBU' in c]
        bb_lower_col = [c for c in df_1h_sniper.columns if 'BBL' in c]
        bb_mid_col = [c for c in df_1h_sniper.columns if 'BBM' in c]
        bb_pct_col = [c for c in df_1h_sniper.columns if 'BBP' in c]
        
        if kc_upper_col and kc_lower_col and bb_upper_col and bb_lower_col and bb_mid_col and bb_pct_col:
            last_1h_s = df_1h_sniper.iloc[-1]
            prev_1h_s = df_1h_sniper.iloc[-2] if len(df_1h_sniper) >= 2 else last_1h_s
            
            kcu = last_1h_s[kc_upper_col[0]]
            kcl = last_1h_s[kc_lower_col[0]]
            bbu = last_1h_s[bb_upper_col[0]]
            bbl = last_1h_s[bb_lower_col[0]]
            bbm = last_1h_s[bb_mid_col[0]]
            bb_pct = last_1h_s[bb_pct_col[0]]
            
            bbw = (bbu - bbl) / bbm if bbm != 0 else 0
            kcw = (kcu - kcl) / bbm if bbm != 0 else 0
            
            guarded_vol_sma = _apply_volume_sma_guard(df_1h_sniper, last_1h_s.get('vol_sma_20', 0))

            # 🎯 LONG Keskin Nişancı
            has_fvg_long, _, _ = sniper_detect_fvg(df_1h_sniper, df_1h_sniper['high'].iloc[-1], df_1h_sniper['low'].iloc[-1], direction="bullish")
            swing_lows_s = sniper_find_swing_points(df_1h_sniper, point_type="low")
            sweep_ok_long, _ = sniper_detect_sweep(df_1h_sniper, swing_lows_s, point_type="low")
            has_sfp_long = sweep_ok_long
            
            sl_long = current_price * 0.95
            _tp_sn_long = current_price * 1.10
            _rr_sn_long = abs(_tp_sn_long - current_price) / max(abs(current_price - sl_long), 1e-8)
            
            _scores_sn_long = build_sniper_scores(
                price=current_price, ema_fast=last_1h_s.get(f'EMA_{config.IND_EMA_FAST}'), ema_mid=last_1h_s.get(f'EMA_{config.IND_EMA_21}'), ema_slow=None,
                rsi=last_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'), rsi_prev=prev_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'),
                volume=last_1h_s.get('volume', 0), vol_sma=guarded_vol_sma, dollar_vol=last_1h_s.get('volume', 0) * current_price,
                rr=_rr_sn_long, regime="BULL" if btc_ok else "BEAR",
                macro_aligned=btc_ok, consecutive_sl=_get_consecutive_sl(symbol),
                bbw=bbw, kcw=kcw, pb=bb_pct, fvg_present=has_fvg_long, sfp_present=has_sfp_long,
                market="KRIPTO", is_long=True
            )
            _conv_sn_long = calculate_conviction(_scores_sn_long, weights=SNIPER_CRYPTO_WEIGHTS)
            if _conv_sn_long.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "KRIPTO",
                    "strategy": "KRİPTO 6: KESKİN NİŞANCI (SNIPER)", "signal": "AL",
                    "entry_price": current_price, "sl": sl_long, "tp": _tp_sn_long,
                    "conviction_score": _conv_sn_long.total_score, "conviction_grade": _conv_sn_long.grade, "conviction_details": _conv_sn_long.component_scores,
                    "position_size_pct": _conv_sn_long.position_size_pct,
                    "reason": (
                        f"🎯 Keskin Nişancı LONG!\n"
                        f"Kanunlar: Squeeze: {_scores_sn_long['bbw_squeeze']:.1f}, %B: {_scores_sn_long['percent_b']:.1f}, FVG/SFP: {_scores_sn_long['fvg_sfp']:.1f}\n"
                        f"SL: %5 Dar Stop ({sl_long:.2f})"
                    ) + _conv_sn_long.to_reason_suffix()
                })

            # 🎯 SHORT Keskin Nişancı (SHORT-4 in implementation_plan.md)
            has_fvg_short, _, _ = sniper_detect_fvg(df_1h_sniper, df_1h_sniper['high'].iloc[-1], df_1h_sniper['low'].iloc[-1], direction="bearish")
            swing_highs_s = sniper_find_swing_points(df_1h_sniper, point_type="high")
            sweep_ok_short, _ = sniper_detect_sweep(df_1h_sniper, swing_highs_s, point_type="high")
            has_sfp_short = sweep_ok_short
            
            sl_short = current_price * 1.05
            _tp_sn_short = current_price * 0.90
            _rr_sn_short = abs(_tp_sn_short - current_price) / max(abs(sl_short - current_price), 1e-8)
            funding_rate = get_funding_rate(symbol)
            
            _scores_sn_short = build_sniper_scores(
                price=current_price, ema_fast=last_1h_s.get(f'EMA_{config.IND_EMA_FAST}'), ema_mid=last_1h_s.get(f'EMA_{config.IND_EMA_21}'), ema_slow=None,
                rsi=last_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'), rsi_prev=prev_1h_s.get(f'RSI_{config.IND_RSI_LENGTH}'),
                volume=last_1h_s.get('volume', 0), vol_sma=guarded_vol_sma, dollar_vol=last_1h_s.get('volume', 0) * current_price,
                rr=_rr_sn_short, regime="BEAR" if not btc_ok else "BULL",
                macro_aligned=not btc_ok, consecutive_sl=_get_consecutive_sl(symbol),
                bbw=bbw, kcw=kcw, pb=bb_pct, fvg_present=has_fvg_short, sfp_present=has_sfp_short,
                market="KRIPTO", is_long=False, funding_rate=funding_rate
            )
            _conv_sn_short = calculate_conviction(_scores_sn_short, weights=SNIPER_CRYPTO_WEIGHTS)
            if _conv_sn_short.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "KRIPTO",
                    "strategy": "KRİPTO SHORT 5: KESKİN NİŞANCI (SNIPER)", "signal": "SAT",
                    "entry_price": current_price, "sl": sl_short, "tp": _tp_sn_short,
                    "conviction_score": _conv_sn_short.total_score, "conviction_grade": _conv_sn_short.grade, "conviction_details": _conv_sn_short.component_scores,
                    "position_size_pct": _conv_sn_short.position_size_pct,
                    "reason": (
                        f"🎯 Keskin Nişancı SHORT!\n"
                        f"Kanunlar: Squeeze: {_scores_sn_short['bbw_squeeze']:.1f}, %B: {_scores_sn_short['percent_b']:.1f}, FVG/SFP: {_scores_sn_short['fvg_sfp']:.1f}\n"
                        f"SL: %5 Dar Stop ({sl_short:.2f})"
                    ) + _conv_sn_short.to_reason_suffix()
                })

    return signals


# ════════════════════════════════════════
# 3. EMTİA STRATEJİ MODÜLÜ
