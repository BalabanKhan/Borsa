"""
data_fetcher.py — Facade Katmanı (Geriye Dönük Uyumluluk)
════════════════════════════════════════════════════════════
Bu dosya artık tek bir "God Object" DEĞİLDİR.
Tüm mantık 4 modüle ayrılmıştır:

  config.py       → Sabitler, varlık listeleri, eşikler
  data_sources.py → Veri çekme, cache, exchange bağlantıları
  indicators.py   → Teknik göstergeler (SMC, Squeeze, OBV, RS, ORB...)
  strategies.py   → BIST/Kripto/Emtia/Ayı Avcısı stratejileri + scan_all_markets

Bu facade dosyası, mevcut `main.py` ve diğer dosyaların
`from data_fetcher import X` şeklindeki importlarını kırmamak için
tüm public isimleri yeniden dışa aktarır (re-export).
"""

# ═══ Config (Sabitler) ═══
from config import (  # noqa: F401
    IS_USA_SERVER,
    TOP_CRYPTO, TOP_BIST, TOP_EMTIA, TOP_EMTIA_USD, TOP_EMTIA_TRY,
    TOP_HEAVY_SHORT, MEME_BLACKLIST,
    ATR_MULTIPLIER_BIST, ATR_MULTIPLIER_CRYPTO, MIN_SL_PCT,
    TRAILING_ATR_FLOOR_RATIO, TRAILING_TIGHT_PCT, TRAILING_MEDIUM_PCT,
    SCALE_OUT_THRESHOLD_LONG, SCALE_OUT_THRESHOLD_SHORT_FOMO,
    TRAILING_TIER_1_PCT, TRAILING_TIER_2_PCT,
    RSI_OVERSOLD_BIST, RSI_OVERSOLD_CRYPTO, RSI_OVERBOUGHT_FOMO,
    RSI_BTC_PUMP_LIMIT, BTC_PUMP_PCT_CHANGE,
    ADX_TREND_THRESHOLD, ADX_STRONG_TREND,
    BB_SQUEEZE_WIDTH, BB_LENGTH, BB_STD, KC_SCALAR, SQUEEZE_MIN_COUNT, VOLUME_BREAKOUT_MULT,
    FIB_OTE_LOW, FIB_OTE_HIGH,
    FUNDING_CRITICAL_LONG, FUNDING_CRITICAL_SHORT, FUNDING_SHORT_BLOCK,
    OI_CRASH_PCT, DANGER_ZONE_PCT, DANGER_SAFE_PCT, DANGER_COOLDOWN_SEC, BLACK_SWAN_PCT, RR_MINIMUM,
    EMTIA_ATR_MULT, DXY_SENSITIVE, EMTIA_NAMES,
    CACHE_TTL_SECONDS, SCAN_INTERVAL_MINUTES, HEARTBEAT_INTERVAL, COOLDOWN_SECONDS, OHLCV_LIMIT,
    API_SLEEP_BIST, API_SLEEP_CRYPTO, API_SLEEP_EMTIA, BATCH_MAX_WORKERS,
)

# ═══ Data Sources (Veri Çekme) ═══
from data_sources import (  # noqa: F401
    get_bist_data, get_crypto_data, get_emtia_data, get_bist_15m_data,
    get_bist_data_batch, get_bist_15m_batch,
    get_crypto_data_cached, clear_cycle_cache, purge_expired_cache,
    is_bist_open, is_weekend_fakeout_time, check_xu100_wind,
    get_btc_status, check_btc_not_pumping,
    get_funding_rate, fetch_crypto_oi_crash, get_btc_dominance_trend,
    check_token_unlocks, get_current_prices,
)

# ═══ Indicators (Teknik Göstergeler) ═══
from indicators import (  # noqa: F401
    sniper_get_htf_bias, sniper_find_swing_points, sniper_detect_sweep,
    sniper_detect_msb, sniper_calculate_ote, sniper_detect_fvg,
    detect_sfp, detect_premium_rejection, detect_bearish_divergence,
    detect_squeeze, calculate_relative_strength,
    calculate_anchored_vwap, detect_vwap_bounce, detect_obv_accumulation,
    calculate_orb_cage,
)

# ═══ Strategies (Strateji Motorları) ═══
from strategies import (  # noqa: F401
    analyze_strategies_bist, analyze_strategies_crypto,
    analyze_strategies_emtia, analyze_bear_hunter,
    scan_orb_bist, scan_all_markets,
)
