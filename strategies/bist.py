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
    calculate_anchored_vwap, detect_vwap_bounce, detect_obv_accumulation, detect_obv_accumulation_bist,
    calculate_orb_cage, calculate_time_specific_rvol,
    detect_bullish_candlestick_pattern, check_near_support,
    # AM Serisi
    check_bullish_engulfing_momentum, calculate_cmf, is_cmf_wash_trade,
    sniper_calculate_ote_body,
)
from data_guard import guard_mtf_bundle, guard_signal_output
from meta_engine import get_bist100_trend, get_bist100_intraday_trend

from conviction_scorer import (
    check_hard_blocks, calculate_conviction,
    build_trend_scores, build_dip_scores, build_breakout_scores, build_short_scores, build_sniper_scores, SNIPER_BIST_WEIGHTS,
    score_adx, score_rsi_oversold, score_rsi_trend, score_rsi_direction,
    score_volume_ratio, score_dollar_volume, score_rr_ratio,
    score_ema_alignment, score_ema_dip_distance, score_ema_short,
    score_regime, score_regime_short, score_engulfing,
    score_macro_alignment, score_penalty_level,
    CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH,
)



from .helpers import _extract_raw_indicators, _apply_volume_sma_guard, _is_meaningful_volume, _get_consecutive_sl, _get_bist_regime, _has_absolute_hourly_volume, _apply_rr_filter, _apply_regime_filter, _resolve_dual_signals, _adx_momentum_ok
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
    df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_4h.ta.atr(length=config.IND_ATR_LENGTH, append=True)

    df_1h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
    df_1h.ta.ema(length=config.IND_EMA_FAST, append=True)
    df_1h.ta.ema(length=config.IND_EMA_21, append=True)
    df_1h['vol_sma_20'] = ta.sma(df_1h['volume'], length=config.IND_VOL_SMA_LENGTH)

    if len(df_1d) < 50 or len(df_4h) < 20 or len(df_1h) < 20:
        return signals

    last_1d = df_1d.iloc[-1]
    last_4h = df_4h.iloc[-1]
    last_1h = df_1h.iloc[-1]
    prev_1h = df_1h.iloc[-2]
    current_price = last_1h['close']

    # 1. HARD BLOCK - Likidite ve Fiyat Filtreleri (Sistemik Yük Düşürme)
    volume_ma20_tl = (df_1d['close'] * df_1d['volume']).rolling(20).mean()
    if volume_ma20_tl.empty or pd.isna(volume_ma20_tl.iloc[-1]) or volume_ma20_tl.iloc[-1] < 20_000_000:
        return signals
    if current_price < 3.0:
        return signals


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
    # BIST 1: DİP AVCILIĞI (Turnaround)
    if not pd.isna(last_1d.get('RSI_14')):
        if last_1d[f'RSI_{config.IND_RSI_LENGTH}'] < 35:
            # DIP_RSI_1D_SMA200_ALIGN_ENABLED: 1D Fiyat > SMA200 trend hizalamasını sorgular (Long yönlü teyit)
            sma_200 = last_1d.get('SMA_200')
            trend_aligned = not config.DIP_RSI_1D_SMA200_ALIGN_ENABLED or (sma_200 is not None and not pd.isna(sma_200) and current_price > sma_200)
            
            if trend_aligned and not pd.isna(last_1h.get('RSI_14')) and not pd.isna(prev_1h.get('RSI_14')) and not pd.isna(last_1h.get('EMA_8')) and not pd.isna(last_1h.get('vol_sma_20')):
                if last_1h['close'] > last_1h['EMA_8'] and prev_1h['close'] <= prev_1h['EMA_8'] and last_1h['close'] > last_1h['open']:
                    # AM-01: Engulfing momentum onayı — ölü kedi sıçraması filtresi
                    if not check_bullish_engulfing_momentum(df_1h):
                        pass  # Yeşil mum önceki kırmızıyı yutmadı → sahte hareket
                    else:
                        # RED-01: Volume SMA manipülasyon koruması
                        guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                        
                        # DIP_VOLUME_SPIKE_REQUIRED: dip dönüş mumunda hacim patlaması şartını sorgular (Volume Spike)
                        volume_spike_ok = not config.DIP_VOLUME_SPIKE_REQUIRED or (last_1h['volume'] >= guarded_vol_sma * config.DIP_VOLUME_SPIKE_MULT)
                        
                        if volume_spike_ok and _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
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
                    has_engulfing = check_bullish_engulfing_momentum(df_1h)
                    sl = current_price - dynamic_sl_dist
                    _tp2 = current_price * 1.10
                    _rr2 = abs(_tp2 - current_price) / max(abs(current_price - sl), 1e-8)
                    _adx_prev2 = df_4h.iloc[-2].get('ADX_14') if len(df_4h) >= 2 else None
                    _scores2 = build_trend_scores(
                        adx=last_4h['ADX_14'], adx_prev=_adx_prev2,
                        price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=None,
                        rsi=last_1h.get('RSI_14'), rsi_prev=prev_1h.get('RSI_14') if len(df_1h) >= 2 else None,
                        volume=last_1h['volume'], vol_sma=last_1h.get('vol_sma_20', 0), dollar_vol=last_1h['volume'] * current_price,
                        rr=_rr2, has_engulfing=has_engulfing, regime=bist_regime,
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
                            "reason": (
                                f"4S ADX>25 Trend{ ' + Engulfing Momentum' if has_engulfing else ''}. "
                                f"1S EMA21 pullback. (ATR Stop: -%{sl_pct:.1f})"
                            ) + _conv2.to_reason_suffix()
                        })

    # BIST 3: KIRILIM VE MOMENTUM
    bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
    bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
    bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]

    if bb_upper_col and bb_lower_col and bb_mid_col:
        # HATA DÜZELTME: Sıkışma (Squeeze) durumu kırılım anında (t) bantların aniden genişlemesiyle 
        # kilitlenmemesi için bir önceki günlük mumda (t-1) sorgulanmalıdır.
        prev_1d = df_1d.iloc[-2] if len(df_1d) >= 2 else last_1d
        bbu_prev = prev_1d[bb_upper_col[0]]
        bbl_prev = prev_1d[bb_lower_col[0]]
        bbm_prev = prev_1d[bb_mid_col[0]]
        
        bb_width_prev = (bbu_prev - bbl_prev) / bbm_prev if not math.isclose(float(bbm_prev), 0.0, abs_tol=1e-8) else 1
        
        # Hard limit 0.15'ten 0.25'e genişletildi. 0.15 ile 0.25 arası genişlik Conviction Scorer
        # içinde soft ceza (puan kırıcı) olarak değerlendirilir.
        if bb_width_prev < 0.25:
            # BREAKOUT_RETEST_REQUIRED: direnç kırılımı sonrası retest/pullback aralığı teyidi
            retest_ok = True
            if config.BREAKOUT_RETEST_REQUIRED:
                max_limit = month_high * (1.0 + (config.BREAKOUT_RETEST_TOLERANCE_PCT / 100.0))
                if not (month_high <= current_price <= max_limit):
                    retest_ok = False

            if retest_ok and current_price > month_high:
                # RED-05: Gap-Up filtresi — sabah gap'i ile sahte kırılım engelle
                prev_close = df_1d.iloc[-2]['close'] if len(df_1d) >= 2 else current_price
                gap_pct = abs(last_1h['open'] - prev_close) / max(prev_close, 1e-8) * 100
                if not pd.isna(last_1h.get('vol_sma_20')):
                    guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                    if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                        # AM-03: Mutlak hacim eşiği — SMA'nın 5 katı bile olsa TL karşılığı yeterli mi?
                        if _has_absolute_hourly_volume(last_1h['volume'], current_price, "BIST"):
                            if not xu100_down:
                                now = datetime.now(ZoneInfo("Europe/Istanbul"))
                                # Açılış gap'lerini ve erken kırılımları kaçırmamak için saat kısıtı 10:00'a (açılış anı) çekildi
                                if now.time() >= dt_time(10, 0):
                                    sl = current_price - dynamic_sl_dist
                                    _tp3 = current_price + (dynamic_sl_dist * 3.0)
                                    _rr3 = abs(_tp3 - current_price) / max(abs(current_price - sl), 1e-8)
                                    _scores3 = build_breakout_scores(
                                        bb_width=bb_width_prev, price=current_price,
                                        ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                                        volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                                        rr=_rr3, regime=bist_regime,
                                        macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST",
                                        dg_gap_pct=gap_pct
                                    )
                                    _conv3 = calculate_conviction(_scores3)
                                    if _conv3.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                                        signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                                            "ticker": symbol, "market": "BIST", "strategy": "BIST 3: SQUEEZE KIRILIMI", "signal": "AL",
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
                    # SMC OTE FVG Filtresi (SMC_FVG_REQUIRED = True ise FVG bulunması şarttır)
                    has_fvg, Fvg_low, fvg_high = sniper_detect_fvg(df_4h, ote_top, ote_bottom, direction="bullish")
                    fvg_ok = not config.SMC_FVG_REQUIRED or has_fvg
                    
                    if fvg_ok:
                        # SMC LTF MSB Teyidi Kontrolü (1H grafikte MSB aranır) - BIST 4 için devre dışı bırakıldı!
                        # OTE bölgesine doğrudan temas anında işleme girmek için 1H MSB aranmaz.
                        # Çekilme hacim kuralı: Kırılım hacmi yerine düşük/ortalama pullback hacmi aranır.
                        if not pd.isna(last_1h.get('vol_sma_20')):
                            guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                            
                            # Mutlak TL hacmi yeterliyse ve aşırı yüksek bir satış (dump) hacmi yoksa giriş yapılır
                            if (_has_absolute_hourly_volume(last_1h['volume'], current_price, "BIST") and 
                                last_1h['volume'] <= guarded_vol_sma * 1.5): # Çekilme Hacim Kuralı (Düşük Hacim)
                                
                                sl = sweep_low * 0.995
                                sl_dist = max(current_price - sl, 1e-8)
                                tp = current_price + (sl_dist * 3.0)
                                fvg_label = " + FVG Onaylı ✅" if has_fvg else ""
                                _rr4 = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)
                                _scores4 = build_breakout_scores(
                                    bb_width=None, price=current_price,
                                    ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                                    volume=last_1h['volume'], vol_sma=guarded_vol_sma, dollar_vol=last_1h['volume'] * current_price,
                                    rr=_rr4, regime=bist_regime,
                                    macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
                                )
                                if has_fvg:
                                    # SMC_FVG_BONUS: FVG bulunması durumunda inanç skoruna (engulfing alt bileşeniyle) eklenir
                                    _scores4["engulfing"] = min(100.0, _scores4["engulfing"] + config.SMC_FVG_BONUS)
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
                                            f"🎣 OTE Bölgesi (Gövde): {ote_bottom:.2f} - {ote_top:.2f} (Temas anında & Düşük Hacim)\n"
                                            f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
                                        ) + _conv4.to_reason_suffix()
                                    })

    # BIST 5: HACİMLİ KIRILIM (Volatility Squeeze Breakout)
    daily_squeeze_setup = False
    prev_bbu_1d = None
    prev_bbl_1d = None
    
    # Calculate KC on daily chart
    df_1d.ta.kc(length=config.IND_BBANDS_LENGTH, scalar=1.5, append=True)
    
    bbu_cols_1d = [c for c in df_1d.columns if 'BBU' in c]
    bbl_cols_1d = [c for c in df_1d.columns if 'BBL' in c]
    kcu_cols_1d = [c for c in df_1d.columns if 'KCU' in c]
    kcl_cols_1d = [c for c in df_1d.columns if 'KCL' in c]
    
    if bbu_cols_1d and bbl_cols_1d and kcu_cols_1d and kcl_cols_1d:
        bbu_c = bbu_cols_1d[0]
        bbl_c = bbl_cols_1d[0]
        kcu_c = kcu_cols_1d[0]
        kcl_c = kcl_cols_1d[0]
        
        if len(df_1d) >= 2:
            prev_bbu_1d = df_1d.iloc[-2][bbu_c]
            prev_bbl_1d = df_1d.iloc[-2][bbl_c]
            
            squeeze_count = 0
            for idx in range(-7, -1):
                if abs(idx) <= len(df_1d):
                    row = df_1d.iloc[idx]
                    if (not pd.isna(row.get(bbu_c)) and not pd.isna(row.get(kcu_c)) and
                        row[bbu_c] < row[kcu_c] and row[bbl_c] > row[kcl_c]):
                        squeeze_count += 1
            
            if squeeze_count >= 3:
                daily_squeeze_setup = True

    if daily_squeeze_setup and not pd.isna(last_1h.get('vol_sma_20')):
        guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
        
        # LONG (AL)
        if (prev_bbu_1d is not None and current_price > prev_bbu_1d and 
            last_1h['close'] > last_1h['open'] and 
            _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST")):
            
            trend_aligned = True
            if config.SQUEEZE_TREND_ALIGN_REQUIRED:
                ema_21_1d = last_1d.get('EMA_21')
                if ema_21_1d is not None and not pd.isna(ema_21_1d):
                    trend_aligned = current_price > ema_21_1d

            if trend_aligned and not xu100_down:
                sq_mid = (last_1h['high'] + last_1h['low']) / 2
                ema21_1h = last_1h.get('EMA_21', current_price * 0.95)
                sl = min(sq_mid, ema21_1h) if not pd.isna(ema21_1h) else sq_mid
                _tp5u = current_price + (dynamic_sl_dist * 3.0)
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
                        "strategy": "BIST 5: HACİMLİ KIRILIM", "signal": "AL",
                        "entry_price": current_price, "sl": sl, "tp": _tp5u,
                        "conviction_score": _conv5u.total_score, "conviction_grade": _conv5u.grade, "conviction_details": _conv5u.component_scores,
                        "position_size_pct": _conv5u.position_size_pct,
                        "reason": (
                            f"🗜️ Günlük Squeeze Hacimli Yukarı Kırıldı!\n"
                            f"1G BB Keltner içindeydi (Daralma). 1S Fiyat Günlük BBU ({prev_bbu_1d:.2f}) üzerine çıktı.\n"
                            f"Hacimli yeşil mum ile 1S EMA21 üzerinde breakout.\n"
                            f"SL: 1S Kırılım barının %50'si veya 1S EMA21 ({sl:.2f})"
                        ) + _conv5u.to_reason_suffix()
                    })

        # SHORT (SAT)
        elif (prev_bbl_1d is not None and current_price < prev_bbl_1d and 
              last_1h['close'] < last_1h['open'] and 
              _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST")):
              
            trend_aligned = True
            if config.SQUEEZE_TREND_ALIGN_REQUIRED:
                ema_21_1d = last_1d.get('EMA_21')
                if ema_21_1d is not None and not pd.isna(ema_21_1d):
                    trend_aligned = current_price < ema_21_1d

            if trend_aligned:
                sq_mid = (last_1h['high'] + last_1h['low']) / 2
                ema21_1h = last_1h.get('EMA_21', current_price * 1.05)
                sl = max(sq_mid, ema21_1h) if not pd.isna(ema21_1h) else sq_mid
                _tp5d = current_price - (dynamic_sl_dist * 3.0)
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
                        "strategy": "BIST 5: HACİMLİ KIRILIM", "signal": "SAT",
                        "entry_price": current_price, "sl": sl, "tp": _tp5d,
                        "conviction_score": _conv5d.total_score, "conviction_grade": _conv5d.grade, "conviction_details": _conv5d.component_scores,
                        "position_size_pct": _conv5d.position_size_pct,
                        "reason": (
                            f"🗜️ Günlük Squeeze Hacimli Aşağı Kırıldı!\n"
                            f"1G BB Keltner içindeydi (Daralma). 1S Fiyat Günlük BBL ({prev_bbl_1d:.2f}) altına indi.\n"
                            f"Hacimli kırmızı mum ile 1S EMA21 altında breakout.\n"
                            f"SL: 1S Kırılım barının %50'si veya 1S EMA21 ({sl:.2f})"
                        ) + _conv5d.to_reason_suffix()
                    })

    # BIST 6: GÖRECELİ GÜÇ RADARI (RS)
    if xu100_daily is not None:
        rs_strong, rs_trend_up, idx_stressed, idx_recovering = calculate_relative_strength(df_1d, xu100_daily)
        if rs_strong and rs_trend_up and (idx_recovering or not idx_stressed):
            # RS_ENTRY_TIMING_RSI_LIMIT: timing teyidi (RSI çok aşırı alımda olmamalı)
            rsi_timing_ok = True
            if not pd.isna(last_1h.get('RSI_14')):
                if last_1h['RSI_14'] > config.RS_ENTRY_TIMING_RSI_LIMIT:
                    rsi_timing_ok = False

            # RED-07: Anlamlı hacim kontrolü (tutarlılık: BIST 1/3/7 ile aynı)
            if rsi_timing_ok and not pd.isna(last_1h.get('vol_sma_20')):
                guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h['vol_sma_20'])
                if _is_meaningful_volume(last_1h['volume'], guarded_vol_sma, current_price, "BIST"):
                    # Swing Low yerine dinamik ATR bazlı stop
                    sl = current_price - dynamic_sl_dist
                    _tp6 = current_price + (dynamic_sl_dist * 3.0)
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
    # Pazartesi-Salı günleri haftalık reset gürültüsünü engelle (Çarşamba ve sonrası aktiftir)
    last_1h_time = pd.to_datetime(last_1h.name) if last_1h.name is not None else None
    is_not_mon_tue = True
    if last_1h_time is not None and not pd.isna(last_1h_time):
        is_not_mon_tue = last_1h_time.weekday() not in (0, 1)

    sma_50 = last_1d.get('SMA_50')
    sma_200 = last_1d.get('SMA_200')
    is_bear_regime = (not pd.isna(sma_50) and not pd.isna(sma_200) and current_price < sma_50 and current_price < sma_200)
    ema_21_daily = last_1d.get('EMA_21')
    mtf_trend_down = (not pd.isna(ema_21_daily) and last_1d['close'] < ema_21_daily)
    macro_gravity_ok = not xu100_down

    if not is_bear_regime and not mtf_trend_down and macro_gravity_ok and is_not_mon_tue:
        vwap_val = calculate_anchored_vwap(df_1h, anchor_type="weekly")
        if vwap_val is not None:
            bounce_ok, wick_low = detect_vwap_bounce(df_1h, vwap_val)
            if bounce_ok and wick_low is not None:
                # RED-01: Volume SMA manipülasyon koruması
                vol_sma_20 = last_1h.get('vol_sma_20')
                guarded_vol_sma = _apply_volume_sma_guard(df_1h, vol_sma_20)
                
                # Kurumsal limit emir emilimi (absorption) nedeniyle temasta hacim patlaması aranmaz.
                # Sadece tahtanın likit olduğunu teyit etmek için asgari mutlak TL hacmi kontrol edilir.
                if _has_absolute_hourly_volume(last_1h['volume'], current_price, "BIST"):
                    sl = wick_low * 0.995
                    _tp7 = current_price + (dynamic_sl_dist * 3.0)
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

    obv_ok, obv_box_high, obv_box_low = detect_obv_accumulation_bist(df_1d, max_change_pct=7.0)
    if obv_ok and obv_box_high is not None:
        cmf_val = calculate_cmf(df_1d)
        # Wash trade / blok virman engellemesi için CMF >= 0.05 şartı
        if cmf_val is not None and not pd.isna(cmf_val) and cmf_val >= 0.05:
            # RED-12: SL kutu ortasına indir — tepeden retest'te patlamayı engelle
            sl = (obv_box_high + obv_box_low) / 2
            cmf_label = f"CMF: {cmf_val:.3f}"
            _tp8 = current_price + (dynamic_sl_dist * 3.0)
            _rr8 = abs(_tp8 - current_price) / max(abs(current_price - sl), 1e-8)
            _scores8 = build_dip_scores(
                rsi_daily=last_1d.get('RSI_14', 50), rsi_hourly=last_1h.get('RSI_14', 50),
                rsi_prev=prev_1h.get('RSI_14', 50) if len(df_1h) >= 2 else 50,
                price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'),
                volume=last_1h.get('volume', 0), vol_sma=last_1h.get('vol_sma_20', 0),
                dollar_vol=last_1h.get('volume', 0) * current_price,
                rr=_rr8, has_engulfing=False, regime=bist_regime,
                macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol), market="BIST",
                cmf=cmf_val
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

    # ════════════════════════════════════════
    # BIST 10: KESKİN NİŞANCI (SNIPER)
    # ════════════════════════════════════════
    
    df_1h_sniper = df_1h.copy()
    df_1h_sniper.ta.kc(length=20, scalar=1.5, append=True)
    df_1h_sniper.ta.bbands(length=20, std=2.0, append=True)
    
    kc_upper_col = [c for c in df_1h_sniper.columns if 'KCU' in c]
    kc_lower_col = [c for c in df_1h_sniper.columns if 'KCL' in c]
    bb_upper_col = [c for c in df_1h_sniper.columns if 'BBU' in c]
    bb_lower_col = [c for c in df_1h_sniper.columns if 'BBL' in c]
    bb_mid_col = [c for c in df_1h_sniper.columns if 'BBM' in c]
    
    if kc_upper_col and kc_lower_col and bb_upper_col and bb_lower_col and bb_mid_col:
        bbu_s = df_1h_sniper[bb_upper_col[0]]
        bbl_s = df_1h_sniper[bb_lower_col[0]]
        bbm_s = df_1h_sniper[bb_mid_col[0]]
        
        bbw_series = (bbu_s - bbl_s) / bbm_s
        bbw_lowest_30 = bbw_series.rolling(10).quantile(0.3)
        is_squeeze = bbw_series.iloc[-1] <= bbw_lowest_30.iloc[-1]
        
        bb_pct_series = (df_1h_sniper['close'] - bbl_s) / (bbu_s - bbl_s)
        has_bb_pct_touch = (bb_pct_series.iloc[-3:] <= 0.1).any()
        
        # GATEKEEPER: Bollinger Sıkışması veya son 3 barda Alt Band Teması yoksa devam etme
        if is_squeeze or has_bb_pct_touch:
            bbw = bbw_series.iloc[-1]
            kcu = df_1h_sniper[kc_upper_col[0]].iloc[-1]
            kcl = df_1h_sniper[kc_lower_col[0]].iloc[-1]
            kcw = (kcu - kcl) / bbm_s.iloc[-1] if bbm_s.iloc[-1] != 0 else 0
            bb_pct = bb_pct_series.iloc[-1]
            
            has_fvg, _, _ = sniper_detect_fvg(df_1h_sniper, df_1h_sniper['high'].iloc[-1], df_1h_sniper['low'].iloc[-1], direction="bullish")
            swing_lows_s = sniper_find_swing_points(df_1h_sniper, point_type="low")
            sweep_ok, _ = sniper_detect_sweep(df_1h_sniper, swing_lows_s, point_type="low")
            has_sfp = sweep_ok
            
            # Dinamik Stop Loss: Alt Bollinger Bandının %1.5 altı veya en fazla %5 genişlik
            sl = max(bbl_s.iloc[-1] * 0.985, current_price * 0.95)
            # Dinamik Take Profit: En az 2:1 risk/ödül oranı ile
            _tp_sn = current_price + 2.0 * (current_price - sl)
            _rr_sn = abs(_tp_sn - current_price) / max(abs(current_price - sl), 1e-8)
            guarded_vol_sma = _apply_volume_sma_guard(df_1h, last_1h.get('vol_sma_20', 0))
            
            _scores_sn = build_sniper_scores(
                price=current_price, ema_fast=last_1h.get('EMA_8'), ema_mid=last_1h.get('EMA_21'), ema_slow=last_1d.get('SMA_50'),
                rsi=last_1h.get('RSI_14'), rsi_prev=prev_1h.get('RSI_14') if len(df_1h) >= 2 else None,
                volume=last_1h.get('volume', 0), vol_sma=guarded_vol_sma, dollar_vol=last_1h.get('volume', 0) * current_price,
                rr=_rr_sn, regime=bist_regime,
                macro_aligned=not xu100_down, consecutive_sl=_get_consecutive_sl(symbol),
                bbw=bbw, kcw=kcw, pb=bb_pct, fvg_present=has_fvg, sfp_present=has_sfp,
                market="BIST", is_squeeze=is_squeeze
            )
            _conv_sn = calculate_conviction(_scores_sn, weights=SNIPER_BIST_WEIGHTS)
            if _conv_sn.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM):
                signals.append({
                    "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "BIST",
                    "strategy": "BIST 10: KESKİN NİŞANCI (SNIPER)", "signal": "AL",
                    "entry_price": current_price, "sl": sl, "tp": _tp_sn,
                    "conviction_score": _conv_sn.total_score, "conviction_grade": _conv_sn.grade, "conviction_details": _conv_sn.component_scores,
                    "position_size_pct": _conv_sn.position_size_pct,
                    "reason": (
                        f"🎯 Keskin Nişancı!\n"
                        f"Kanunlar: Squeeze: {_scores_sn['bbw_squeeze']:.1f}, %B: {_scores_sn['percent_b']:.1f}, FVG/SFP: {_scores_sn['fvg_sfp']:.1f}\n"
                        f"SL: Bollinger Alt Band Altı ({sl:.2f})"
                    ) + _conv_sn.to_reason_suffix()
                })

    # BIST 11: MUM FORMASYONLARI (CANDLESTICK) - 4H Grafik
    try:
        if len(df_4h) >= 20:
            pattern_name, pattern_details = detect_bullish_candlestick_pattern(df_4h)
            if pattern_name:
                near_support, support_reason = check_near_support(current_price, df_4h, df_1d, tolerance_pct=config.BIST11_SUPPORT_TOLERANCE_PCT)
                
                # Hacim teyidi: son mumun hacmi, son 10 tamamlanan mumun (idx-10'dan idx-1'e) hacim ortalamasının 1.2 katından büyük/eşit olmalı
                vol_4h = df_4h['volume'].values
                vol_sma_period = config.BIST11_VOLUME_SMA_PERIOD
                recent_vols = vol_4h[-(vol_sma_period+1):-1]
                avg_vol_prev = recent_vols.mean() if len(recent_vols) > 0 else 0
                vol_ratio = vol_4h[-1] / avg_vol_prev if avg_vol_prev > 0 else 0
                volume_ok = vol_ratio >= config.BIST11_VOLUME_MULT

                div_ok = True
                if config.BIST11_DIVERGENCE_REQUIRED:
                    div_ok, _, _, _, _ = detect_bullish_divergence(df_4h, neighbors=3)

                # Destek ve Hacim teyidi geçerlilik şartıdır
                if near_support and volume_ok:
                    atr_series_4h = df_4h['ATR_14'] if 'ATR_14' in df_4h.columns else df_4h.ta.atr(length=14)
                    atr_4h = float(atr_series_4h.iloc[-1]) if atr_series_4h is not None and not atr_series_4h.empty and not pd.isna(atr_series_4h.iloc[-1]) else (df_4h['high'].iloc[-1] - df_4h['low'].iloc[-1])
                    if atr_4h <= 0:
                        atr_4h = 1e-8
                        
                    sl = current_price - (atr_4h * config.BIST11_ATR_MULTIPLIER)
                    tp = current_price + 3.0 * (current_price - sl)
                    rr = abs(tp - current_price) / max(abs(current_price - sl), 1e-8)

                    # Conviction Scorer
                    rsi_d = df_1d['RSI_14'].iloc[-1] if 'RSI_14' in df_1d.columns else 50.0
                    rsi_h = df_4h['RSI_14'].iloc[-1] if 'RSI_14' in df_4h.columns else 50.0
                    rsi_p = df_4h['RSI_14'].iloc[-2] if len(df_4h) >= 2 and 'RSI_14' in df_4h.columns else rsi_h
                    
                    _scores_cand = build_dip_scores(
                        rsi_daily=rsi_d,
                        rsi_hourly=rsi_h,
                        rsi_prev=rsi_p,
                        price=current_price,
                        ema_fast=df_4h['EMA_8'].iloc[-1] if 'EMA_8' in df_4h.columns else None,
                        ema_mid=df_4h['EMA_21'].iloc[-1] if 'EMA_21' in df_4h.columns else None,
                        volume=vol_4h[-1],
                        vol_sma=avg_vol_prev,
                        dollar_vol=vol_4h[-1] * current_price,
                        rr=rr,
                        has_engulfing=True,
                        regime=bist_regime,
                        macro_aligned=not xu100_down,
                        consecutive_sl=_get_consecutive_sl(symbol),
                        market="BIST"
                    )
                    
                    if div_ok:
                        _scores_cand['rsi'] = 100.0
                        _scores_cand['rsi_direction'] = 100.0

                    _conv_cand = calculate_conviction(_scores_cand)
                    if _conv_cand.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                        signals.append({
                            "raw_indicators": _extract_raw_indicators(locals()),
                            "ticker": symbol, 
                            "market": "BIST",
                            "strategy": "BIST 11: MUM FORMASYONLARI (CANDLESTICK)", 
                            "signal": "AL",
                            "entry_price": current_price, 
                            "sl": sl, 
                            "tp": tp,
                            "conviction_score": _conv_cand.total_score, 
                            "conviction_grade": _conv_cand.grade, 
                            "conviction_details": _conv_cand.component_scores,
                            "position_size_pct": _conv_cand.position_size_pct,
                            "body_close_stop_required": True,
                            "timeframe": "4h",
                            "reason": (
                                f"🕯️ 4H Mum Formasyonu: {pattern_name}\n"
                                f"🛡️ Destek Teyidi: {support_reason}\n"
                                f"📊 Hacim Teyidi: {vol_ratio:.1f}x (Eşik: {config.BIST11_VOLUME_MULT:.1f}x)\n"
                                f"📈 Uyumsuzluk Teyidi: {'Evet' if div_ok else 'Hayır'}"
                            ) + _conv_cand.to_reason_suffix()
                        })
    except Exception as e:
        logging.warning(f"[analyze_strategies_bist] BIST 11 Hata: {e}", exc_info=True)

    return signals


# ════════════════════════════════════════
# BIST 9: ZAMAN KAFESİ (ORB)
# ════════════════════════════════════════
def scan_orb_bist(symbol, df_15m):
    """BIST 9: ZAMAN KAFESİ (ORB) taraması."""
    signals = []
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    start_time = now.replace(hour=config.BIST9_TRADE_START_HOUR, minute=config.BIST9_TRADE_START_MINUTE, second=0, microsecond=0)
    end_time = now.replace(hour=config.BIST9_TRADE_END_HOUR, minute=config.BIST9_TRADE_END_MINUTE, second=0, microsecond=0)
    if not (start_time <= now <= end_time):
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
    bist100_intraday_trend = get_bist100_intraday_trend()

    # LONG Kırılım (Candle Close > Kafes, VWAP ve EMA21 onayları soft-score'a devredildi)
    # LONG Kırılım (Candle Close > Kafes, VWAP ve EMA21 onayları soft-score'a devredildi)
    if current_price > cage_high and last['close'] > last['open']:
        if bist100_trend == "BEAR" or bist100_intraday_trend == "BEAR":
             return signals  # Hard Block: Endeks negatif (ekside)

        # ORB Hacim ve Gövde Kapanış Teyidi
        body_ok = not config.ORB_BODY_CLOSE_REQUIRED or (last['close'] > cage_high)
        vol_ok = current_vol >= rvol * config.ORB_VOLUME_MULT
             
        if body_ok and vol_ok:
            entry_price = cage_high * 1.001 if not config.ORB_BODY_CLOSE_REQUIRED else current_price
            _sl9u = cage_mid
            _risk9u = entry_price - _sl9u
            _tp9u = entry_price + (_risk9u * 2.0)
            _rr9u = 2.0
            _scores9u = build_breakout_scores(
                bb_width=None, price=entry_price,
                ema_fast=ema21, ema_mid=today_vwap, ema_slow=None,
                volume=current_vol, vol_sma=rvol, dollar_vol=current_vol * entry_price,
                rr=_rr9u, regime="BULL",
                macro_aligned=True, consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
            )
            _conv9u = calculate_conviction(_scores9u)
            if _conv9u.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "BIST",
                    "strategy": "BIST 9: ZAMAN KAFESİ (ORB)", "signal": "AL", "is_day_trade": True,
                    "entry_price": entry_price, "sl": _sl9u, "tp": _tp9u,
                    "conviction_score": _conv9u.total_score, "conviction_grade": _conv9u.grade, "conviction_details": _conv9u.component_scores,
                    "position_size_pct": _conv9u.position_size_pct,
                    "reason": (
                        f"⏱️ Açılış Kafesi Kırılımı (ORB)\n"
                        f"📊 Kafes: {cage_low:.2f} - {cage_high:.2f} (Genişlik: %{cage_width_pct:.2f})\n"
                        f"📍 Fiyat: {entry_price:.2f} TL (EMA21: {ema21:.2f}, VWAP: {today_vwap:.2f})\n"
                        f"📈 Hacim: {current_vol:,.0f} (Ort. RVOL: {rvol:,.0f}, Oran: {current_vol/max(rvol, 1e-8):.2f}x)\n"
                        f"🎯 Hedef: +{_tp9u-entry_price:.2f} TL\n"
                        f"⚠️ DAY TRADE: 17:55'te otomatik kapatılır."
                    ) + _conv9u.to_reason_suffix()
                })
    # SHORT Kırılım (Candle Close < Kafes, VWAP ve EMA21 onayları soft-score'a devredildi)
    elif current_price < cage_low and last['close'] < last['open']:
        if bist100_trend == "BULL" or bist100_intraday_trend == "BULL":
             return signals  # Hard Block: Endeks Bullish iken short açma


        # ORB Hacim ve Gövde Kapanış Teyidi
        body_ok = not config.ORB_BODY_CLOSE_REQUIRED or (last['close'] < cage_low)
        vol_ok = current_vol >= rvol * config.ORB_VOLUME_MULT
             
        if body_ok and vol_ok:
            entry_price = cage_low * 0.999 if not config.ORB_BODY_CLOSE_REQUIRED else current_price
            _sl9d = cage_mid
            _risk9d = _sl9d - entry_price
            _tp9d = entry_price - (_risk9d * 2.0)
            _rr9d = 2.0
            _scores9d = build_breakout_scores(
                bb_width=None, price=entry_price, ema_fast=today_vwap, ema_mid=ema21, ema_slow=None,
                volume=current_vol, vol_sma=rvol, dollar_vol=current_vol * entry_price,
                rr=_rr9d, regime="BEAR", macro_aligned=True,
                consecutive_sl=_get_consecutive_sl(symbol), market="BIST"
            )
            _conv9d = calculate_conviction(_scores9d)
            if _conv9d.grade in (CONVICTION_STRONG, CONVICTION_MEDIUM, CONVICTION_WATCH):
                signals.append({ "raw_indicators": _extract_raw_indicators(locals()),
                    "ticker": symbol, "market": "BIST",
                    "strategy": "BIST 9: ZAMAN KAFESİ (ORB)", "signal": "SAT", "is_day_trade": True,
                    "entry_price": entry_price, "sl": _sl9d, "tp": _tp9d,
                    "conviction_score": _conv9d.total_score, "conviction_grade": _conv9d.grade, "conviction_details": _conv9d.component_scores,
                    "position_size_pct": _conv9d.position_size_pct,
                    "reason": (
                        f"⏱️ Açılış Kafesi Aşağı Kırılımı (ORB)\n"
                        f"📊 Kafes: {cage_low:.2f} - {cage_high:.2f} (Genişlik: %{cage_width_pct:.2f})\n"
                        f"📍 Fiyat: {entry_price:.2f} TL (EMA21: {ema21:.2f}, VWAP: {today_vwap:.2f})\n"
                        f"📈 Hacim: {current_vol:,.0f} (Ort. RVOL: {rvol:,.0f}, Oran: {current_vol/max(rvol, 1e-8):.2f}x)\n"
                        f"🎯 Hedef: -{entry_price-_tp9d:.2f} TL\n"
                        f"⚠️ DAY TRADE: 17:55'te otomatik kapatılır."
                    ) + _conv9d.to_reason_suffix()
                })

    return signals


# ════════════════════════════════════════
# 2. KRİPTO STRATEJİ MODÜLÜ
