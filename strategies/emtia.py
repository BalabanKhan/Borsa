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
)



from .helpers import _extract_raw_indicators, _apply_volume_sma_guard, _is_meaningful_volume, _get_consecutive_sl, _has_absolute_hourly_volume, _apply_rr_filter, _apply_regime_filter, _resolve_dual_signals, _is_in_liquidity_window
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
    if len(df_1d) >= 200:
        df_1d.ta.sma(length=200, append=True)

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
            "1D SMA 200": round(last_1d.get("SMA_200", 0), 2) if pd.notna(last_1d.get("SMA_200")) else None,
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

        last_4h = df_4h.iloc[-1]
        adx_4h = last_4h.get('ADX_14')
        ema8_4h = last_4h.get('EMA_8')
        ema21_4h = last_4h.get('EMA_21')

        if (not pd.isna(adx_4h) and not pd.isna(ema8_4h) and not pd.isna(ema21_4h)):
            # RED-02: ADX momentum kontrolü
            if not in_squeeze and _adx_momentum_ok(df_4h, last_4h) and ema8_4h > ema21_4h:
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

            elif not in_squeeze and adx_4h > 25 and ema8_4h < ema21_4h:
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
                        fvg_ok = not config.SMC_FVG_REQUIRED or has_fvg
                        
                        if fvg_ok:
                            # SMC LTF MSB Teyidi Kontrolü (1H grafikte MSB aranır)
                            ltf_confirm = True
                            df_1h_emtia = None
                            if config.SMC_LTF_MSB_CONFIRM:
                                df_1h_emtia = get_emtia_1h_data(symbol)
                                if df_1h_emtia is not None and not df_1h_emtia.empty:
                                    df_1h_emtia = df_1h_emtia.copy()
                                    df_1h_emtia.ta.ema(length=config.IND_EMA_FAST, append=True)
                                    df_1h_emtia.ta.ema(length=config.IND_EMA_21, append=True)
                                    swing_highs_1h = sniper_find_swing_points(df_1h_emtia, point_type="high", neighbors=2)
                                    ltf_msb_ok, _, _ = sniper_detect_msb(df_1h_emtia, swing_highs_1h, point_type="high")
                                    if not ltf_msb_ok:
                                        ltf_confirm = False
                                else:
                                    ltf_confirm = False

                            if ltf_confirm:
                                sl = sweep_low - (atr_val * 0.5)
                                sl_dist = max(current_price - sl, 1e-8)
                                tp = current_price + (sl_dist * 3.0)
                                fvg_label = " + FVG ✅" if has_fvg else ""
                                dxy_note = "\n🛡️ DXY: Dolar zayıf ✅" if is_dxy_sensitive else ""
                                _rr_e2l = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                                
                                # 1H verisi varsa onun EMA'larını kullan
                                ema_fast_val = None
                                ema_mid_val = None
                                if config.SMC_LTF_MSB_CONFIRM and df_1h_emtia is not None and not df_1h_emtia.empty:
                                    ema_fast_val = df_1h_emtia.iloc[-1].get(f'EMA_{config.IND_EMA_FAST}')
                                    ema_mid_val = df_1h_emtia.iloc[-1].get(f'EMA_{config.IND_EMA_21}')
                                else:
                                    ema_fast_val = last_4h.get('EMA_8')
                                    ema_mid_val = last_4h.get('EMA_21')

                                _scores_e2l = build_breakout_scores(
                                    bb_width=None, price=current_price, ema_fast=ema_fast_val, ema_mid=ema_mid_val, ema_slow=None,
                                    volume=last_4h.get('volume', 0), vol_sma=last_4h.get('vol_sma_20'),
                                    dollar_vol=last_4h.get('volume', 0) * current_price,
                                    rr=_rr_e2l, regime="BULL",
                                    macro_aligned=(not dxy_block_long), consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
                                )
                                if has_fvg:
                                    _scores_e2l["engulfing"] = min(100.0, _scores_e2l["engulfing"] + config.SMC_FVG_BONUS)

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
                        fvg_ok = not config.SMC_FVG_REQUIRED or has_fvg
                        
                        if fvg_ok:
                            # SMC LTF MSB Teyidi Kontrolü (1H grafikte MSB aranır)
                            ltf_confirm = True
                            df_1h_emtia = None
                            if config.SMC_LTF_MSB_CONFIRM:
                                df_1h_emtia = get_emtia_1h_data(symbol)
                                if df_1h_emtia is not None and not df_1h_emtia.empty:
                                    df_1h_emtia = df_1h_emtia.copy()
                                    df_1h_emtia.ta.ema(length=config.IND_EMA_FAST, append=True)
                                    df_1h_emtia.ta.ema(length=config.IND_EMA_21, append=True)
                                    swing_lows_1h = sniper_find_swing_points(df_1h_emtia, point_type="low", neighbors=2)
                                    ltf_msb_ok, _, _ = sniper_detect_msb(df_1h_emtia, swing_lows_1h, point_type="low")
                                    if not ltf_msb_ok:
                                        ltf_confirm = False
                                else:
                                    ltf_confirm = False

                            if ltf_confirm:
                                sl = sweep_high + (atr_val * 0.5)
                                sl_dist = max(sl - current_price, 1e-8)
                                tp = current_price - (sl_dist * 3.0)
                                fvg_label = " + FVG ✅" if has_fvg else ""
                                _rr_e2s = abs(current_price - tp) / max(abs(sl - current_price), 1e-8)
                                
                                # 1H verisi varsa onun EMA'larını kullan
                                ema_fast_val = None
                                ema_mid_val = None
                                if config.SMC_LTF_MSB_CONFIRM and df_1h_emtia is not None and not df_1h_emtia.empty:
                                    ema_fast_val = df_1h_emtia.iloc[-1].get(f'EMA_{config.IND_EMA_FAST}')
                                    ema_mid_val = df_1h_emtia.iloc[-1].get(f'EMA_{config.IND_EMA_21}')
                                else:
                                    ema_fast_val = last_4h.get('EMA_8')
                                    ema_mid_val = last_4h.get('EMA_21')

                                _scores_e2s = build_breakout_scores(
                                    bb_width=None, price=current_price, ema_fast=ema_fast_val, ema_mid=ema_mid_val, ema_slow=None,
                                    volume=last_4h.get('volume', 0), vol_sma=last_4h.get('vol_sma_20'),
                                    dollar_vol=last_4h.get('volume', 0) * current_price,
                                    rr=_rr_e2s, regime="BEAR",
                                    macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="EMTIA"
                                )
                                if has_fvg:
                                    _scores_e2s["engulfing"] = min(100.0, _scores_e2s["engulfing"] + config.SMC_FVG_BONUS)

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
