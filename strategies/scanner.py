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



from .bist import analyze_strategies_bist, scan_orb_bist
from .crypto import analyze_strategies_crypto
from .emtia import analyze_strategies_emtia
from .bear_hunter import analyze_bear_hunter
from .helpers import _get_bist_regime, _apply_regime_filter, _resolve_dual_signals, _apply_rr_filter
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

    # ════ HİBRİT PİYASA ZAMANLAYICI (Market Routing) ════
    # Hafta içi 09:30 - 18:30 -> SADECE BIST 100
    # Hafta içi 18:30 - 09:30 -> SADECE Kripto
    # Hafta sonu (Cuma 18:30'dan Pazartesi 09:30'a) -> SADECE Kripto
    bypass_time_routing = getattr(config, 'BYPASS_TIME_ROUTING', False)
    
    if bypass_time_routing:
        scan_bist = True
        scan_crypto = True
        logging.info("[ZAMANLAYICI] Zamanlayıcı bypass edildi (BYPASS_TIME_ROUTING=True). Hem BIST hem Kripto taranıyor.")
    else:
        now_ist = datetime.now(ZoneInfo("Europe/Istanbul"))
        weekday = now_ist.weekday()  # 0=Pazartesi, 6=Pazar
        time_of_day = now_ist.time()

        # Hafta sonu bloğu: Cuma 18:30'dan Pazartesi 09:30'a kadar olan süre
        is_weekend_block = False
        if weekday == 4:  # Cuma
            if time_of_day >= dt_time(18, 30):
                is_weekend_block = True
        elif weekday in (5, 6):  # Cumartesi, Pazar
            is_weekend_block = True
        elif weekday == 0:  # Pazartesi
            if time_of_day < dt_time(9, 30):
                is_weekend_block = True

        if is_weekend_block:
            scan_bist = False
            scan_crypto = True
        else:
            # Hafta içi
            if dt_time(9, 30) <= time_of_day < dt_time(18, 30):
                scan_bist = True
                scan_crypto = False
            else:
                scan_bist = False
                scan_crypto = True
        
        logging.info(f"[ZAMANLAYICI] Gün/Saat: {weekday} / {time_of_day} | Aktif Tarama -> BIST: {scan_bist}, Kripto: {scan_crypto}")

    # 1. BIST TARAMALARI (Batch Download)
    if scan_bist and is_bist_open():
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
    if scan_crypto:
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
    # --- [GEÇİCİ BYPASS] Kullanıcı talebi üzerine Emtia taramaları geçici olarak kapatıldı ---
    bypass_emtia = True
    if bypass_emtia:
        logging.info("[scan_all_markets] 🛑 Kullanıcı isteği: EMTİA taraması geçici olarak atlandı.")
    elif _is_macro_news_hour():
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
    # --- [GEÇİCİ BYPASS] Kullanıcı talebi üzerine Ayı Avcısı taramaları geçici olarak kapatıldı ---
    bypass_bear_hunter = True
    t0 = _time.time()
    
    if bypass_bear_hunter:
        logging.info("[scan_all_markets] 🛑 Kullanıcı isteği: AYI AVCISI taraması geçici olarak atlandı.")
    else:
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

