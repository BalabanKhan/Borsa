"""
data_guard.py — Veri Boru Hattı Güvenlik Duvarı (DataGuard Middleware)
6 katmanlı veri akıl sağlığı (Data Sanity) kontrol sistemi.

DG-01: API Halüsinasyonları ve NaN Sızıntısı
DG-02: Bayat Veri Körlüğü (Stale Data)
DG-03: Değişken Kirlenmesi (Scope Leak / Routing)
DG-04: Kurumsal Eylem Anomali Filtresi (Split/Dividend)
DG-05: Çözünürlük ve Hizalama (Timeframe Misalignment)
DG-06: Çıktı Dağıtım Bütünlüğü (Output Integrity)
"""
import logging
import math
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional

# ════════════════════════════════════════
# YAPILANDIRMA SABİTLERİ
# ════════════════════════════════════════

# DG-01: Minimum satır sayıları
MIN_ROWS = {"1d": 30, "4h": 20, "1h": 20, "15m": 10}

# DG-01: Ardışık aynı close tekrarı (API ghost candle tespiti)
MAX_IDENTICAL_CLOSES = 5

# DG-02: Bayatlık eşikleri (dakika)
STALENESS_LIMITS = {
    "1d": 26 * 60,     # 26 saat (hafta sonu toleransı)
    "4h": 5 * 60,      # 5 saat
    "1h": 2 * 60,      # 2 saat
    "15m": 45,          # 45 dakika
}

# DG-04: Tek mum anomali eşiği (yüzde)
SINGLE_CANDLE_ANOMALY_PCT = 25.0

# DG-05: MTF hizalama maksimum boşluk (saat)
MTF_MAX_GAP_HOURS = 48

# DG-06: Fiyat geçerlilik sınırları
PRICE_MIN = 1e-8        # Minimum fiyat (sıfır değil ama sıfıra çok yakın engelle)
PRICE_MAX = 1_000_000   # Mantıklı üst sınır (BTC bile 1M altında)


# ════════════════════════════════════════
# DG-01: OHLCV BÜTÜNLÜK DOĞRULAMA
# ════════════════════════════════════════
def validate_ohlcv_integrity(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1d",
    min_rows: Optional[int] = None
) -> tuple[bool, str]:
    """
    DataFrame'in OHLCV bütünlüğünü doğrular.

    Kontroller:
    1. None / boş DataFrame kontrolü
    2. Gerekli OHLCV sütunları mevcut mu?
    3. Minimum satır sayısı
    4. Son N mumda NaN var mı?
    5. Sıfır veya negatif fiyat var mı?
    6. high < low anomalisi
    7. Ardışık aynı close (API ghost candle / tekrar sızıntısı)

    Returns:
        (is_valid, rejection_reason)
    """
    tag = f"[DG-01] {symbol}/{timeframe}"

    # 1. None / boş
    if df is None:
        return False, f"{tag}: DataFrame None"
    if isinstance(df, pd.DataFrame) and df.empty:
        return False, f"{tag}: DataFrame boş"

    # 2. Gerekli sütunlar
    required_cols = {'open', 'high', 'low', 'close', 'volume'}
    actual_cols = {c.lower() for c in df.columns}
    missing = required_cols - actual_cols
    if missing:
        return False, f"{tag}: Eksik sütunlar: {missing}"

    # 3. Minimum satır sayısı
    threshold = min_rows if min_rows is not None else MIN_ROWS.get(timeframe, 20)
    if len(df) < threshold:
        return False, f"{tag}: Yetersiz satır ({len(df)} < {threshold})"

    # 4. Son 5 mumda NaN kontrolü (indikatör hesaplama bölgesinde NaN tehlikeli)
    tail_5 = df[['open', 'high', 'low', 'close']].tail(5)
    nan_count = tail_5.isna().sum().sum()
    if nan_count > 0:
        return False, f"{tag}: Son 5 mumda {nan_count} NaN tespit edildi"

    # 5. Sıfır veya negatif fiyat
    price_cols = ['open', 'high', 'low', 'close']
    # Sütun isimlerini normalize et (büyük/küçük harf uyumu)
    actual_price_cols = [c for c in df.columns if c.lower() in {'open', 'high', 'low', 'close'}]
    for col in actual_price_cols:
        if (df[col].tail(10) <= 0).any():
            return False, f"{tag}: '{col}' sütununda sıfır/negatif fiyat"
        # K-01: Mutlak fiyat aralığı kontrolü (PRICE_MIN/MAX)
        if col.lower() != 'volume':  # Volume farklı ölçekte
            if (df[col].tail(10) > PRICE_MAX).any():
                return False, f"{tag}: '{col}' sütununda PRICE_MAX ({PRICE_MAX}) aşıldı"

    # 6. high < low anomalisi (son 10 mum)
    h_col = next((c for c in df.columns if c.lower() == 'high'), None)
    l_col = next((c for c in df.columns if c.lower() == 'low'), None)
    if h_col and l_col:
        invalid_bars = (df[h_col].tail(10) < df[l_col].tail(10)).sum()
        if invalid_bars > 0:
            return False, f"{tag}: {invalid_bars} mumda high < low anomalisi"

    # 7. Ardışık aynı close (API ghost candle tespiti)
    c_col = next((c for c in df.columns if c.lower() == 'close'), None)
    if c_col:
        closes = df[c_col].tail(MAX_IDENTICAL_CLOSES + 2)
        if len(closes) >= MAX_IDENTICAL_CLOSES:
            # Son N close değeri tamamen aynı mı?
            last_n = closes.tail(MAX_IDENTICAL_CLOSES)
            if last_n.nunique() == 1:
                return False, (
                    f"{tag}: Son {MAX_IDENTICAL_CLOSES} mum aynı close "
                    f"({last_n.iloc[0]:.4f}) → API ghost candle şüphesi"
                )

    return True, ""


# ════════════════════════════════════════
# DG-02: BAYAT VERİ KONTROLÜ
# ════════════════════════════════════════
def check_data_freshness(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1d",
    max_staleness_minutes: Optional[int] = None
) -> tuple[bool, str]:
    """
    Son mumun zaman damgasını UTC şimdiki zamanla karşılaştırır.
    Hafta sonu (Cumartesi/Pazar) BIST verisi için tolerans uygulanır.

    Returns:
        (is_fresh, staleness_reason)
    """
    tag = f"[DG-02] {symbol}/{timeframe}"

    if df is None or df.empty:
        return False, f"{tag}: DataFrame None/boş"

    # Son mumun zaman damgasını al
    last_index = df.index[-1]

    # Timestamp'i UTC-aware yap
    if isinstance(last_index, pd.Timestamp):
        if last_index.tzinfo is None:
            last_ts = last_index.tz_localize('UTC')
        else:
            last_ts = last_index.tz_convert('UTC')
    else:
        # Sayısal index (Binance ms timestamp olabilir)
        try:
            last_ts = pd.Timestamp(last_index, unit='ms', tz='UTC')
        except Exception:
            # Index tarih değilse freshness kontrolü atlanır
            logging.debug(f"{tag}: İndeks tarih değil, freshness atlandı")
            return True, ""

    now_utc = pd.Timestamp.now(tz='UTC')
    age_minutes = (now_utc - last_ts).total_seconds() / 60

    # Hafta sonu toleransı: BIST hisseleri (.IS) Cuma kapanışından Pazartesi açılışına kadar bayat görünür
    is_bist = symbol.endswith('.IS') or symbol.endswith('.E')
    if is_bist and now_utc.weekday() in (5, 6):  # Cumartesi, Pazar
        # Hafta sonu BIST verisi doğal olarak bayat, 72 saat tolerans
        max_minutes = 72 * 60
    else:
        max_minutes = max_staleness_minutes or STALENESS_LIMITS.get(timeframe, 26 * 60)

    if age_minutes > max_minutes:
        hours = age_minutes / 60
        return False, (
            f"{tag}: Veri {hours:.1f} saat eski "
            f"(limit: {max_minutes / 60:.0f} saat)"
        )

    return True, ""


# ════════════════════════════════════════
# DG-03: SEMBOL YÖNLENDIRME DOĞRULAMASI
# ════════════════════════════════════════
def validate_signal_routing(
    signal_dict: dict,
    expected_market: Optional[str] = None
) -> tuple[bool, str]:
    """
    Sinyal dict'indeki ticker/market tutarlılığını kontrol eder.

    Kontroller:
    1. Zorunlu alanlar mevcut mu?
    2. Ticker formatı market türüne uygun mu?
       - BIST: '.IS' suffix
       - KRİPTO: '/' separator (BTC/USDT)
       - EMTİA: '=F' veya '=X' suffix
    3. Beklenen market ile gelen market eşleşiyor mu?

    Returns:
        (is_valid, rejection_reason)
    """
    tag = "[DG-03]"

    required_fields = {"ticker", "market", "signal", "entry_price", "sl", "tp"}
    missing = required_fields - set(signal_dict.keys())
    if missing:
        return False, f"{tag}: Eksik sinyal alanları: {missing}"

    ticker = signal_dict.get("ticker", "")
    market = signal_dict.get("market", "")
    signal = signal_dict.get("signal", "")

    # Ticker boş kontrolü
    if not ticker or not isinstance(ticker, str):
        return False, f"{tag}: Ticker boş veya geçersiz tip"

    # Signal geçerlilik
    if signal not in ("AL", "SAT"):
        return False, f"{tag}: Geçersiz sinyal tipi: '{signal}'"

    # Market-Ticker format uyumu
    format_rules = {
        "BIST": lambda t: t.endswith('.IS') or t.endswith('.E'),
        "KRIPTO": lambda t: '/' in t,
        "KRİPTO": lambda t: '/' in t,
        "EMTİA": lambda t: '=F' in t or '=X' in t or t.endswith('.IS'),
        "AYI_AVCISI": lambda t: '/' in t,  # Ayı Avcısı kripto SHORT'ları
    }

    checker = format_rules.get(market)
    if checker and not checker(ticker):
        return False, (
            f"{tag}: Ticker '{ticker}' formatı '{market}' piyasasıyla uyumsuz "
            f"→ Olası değişken kirlenmesi!"
        )

    # Beklenen market cross-check
    if expected_market and market != expected_market:
        return False, (
            f"{tag}: Beklenen market '{expected_market}', gelen '{market}' "
            f"→ Yönlendirme hatası!"
        )

    return True, ""


# ════════════════════════════════════════
# DG-04: KURUMSAL EYLEM ANOMALİ FİLTRESİ
# ════════════════════════════════════════
def detect_corporate_action_anomaly(
    df: pd.DataFrame,
    symbol: str,
    max_single_candle_pct: float = SINGLE_CANDLE_ANOMALY_PCT
) -> tuple[bool, str]:
    """
    Tek mumda anlamsız fiyat hareketi tespiti.

    Senaryolar:
    - BIST bedelsiz sermaye artırımı (%50 düşüş)
    - Kripto delist/rebrand
    - Emtia kontrat devri (rollover)

    Returns:
        (is_clean, anomaly_reason)  — True = anomali YOK, veri temiz
    """
    tag = f"[DG-04] {symbol}"

    if df is None or len(df) < 3:
        return True, ""  # Veri yetersiz, anomali taraması yapılamaz

    c_col = next((c for c in df.columns if c.lower() == 'close'), None)
    if c_col is None:
        return True, ""

    closes = df[c_col].tail(10)

    for i in range(1, len(closes)):
        prev_close = closes.iloc[i - 1]
        curr_close = closes.iloc[i]

        if prev_close <= 0 or curr_close <= 0:
            continue

        pct_change = abs((curr_close - prev_close) / prev_close) * 100

        if pct_change >= max_single_candle_pct:
            direction = "DÜŞÜŞ" if curr_close < prev_close else "ARTIŞ"
            return False, (
                f"{tag}: Tek mumda %{pct_change:.1f} {direction} "
                f"({prev_close:.4f} → {curr_close:.4f}) "
                f"→ Olası bedelsiz/split/rollover, veri BOZUK"
            )

    return True, ""


# ════════════════════════════════════════
# DG-05: MTF HİZALAMA KİLİDİ
# ════════════════════════════════════════
def validate_timeframe_alignment(
    symbol: str,
    df_1d: Optional[pd.DataFrame] = None,
    df_4h: Optional[pd.DataFrame] = None,
    df_1h: Optional[pd.DataFrame] = None,
    max_gap_hours: int = MTF_MAX_GAP_HOURS
) -> tuple[bool, str]:
    """
    Çoklu zaman dilimi (MTF) verilerinin birbiriyle hizalı olduğunu doğrular.

    Kontrol: Her timeframe çiftinin son mum tarihleri arasındaki fark
    max_gap_hours'u aşmamalıdır.

    Returns:
        (is_aligned, alignment_reason)
    """
    tag = f"[DG-05] {symbol}"

    def _get_last_ts(df: pd.DataFrame, label: str) -> Optional[pd.Timestamp]:
        if df is None or df.empty:
            return None
        idx = df.index[-1]
        if isinstance(idx, pd.Timestamp):
            return idx.tz_localize('UTC') if idx.tzinfo is None else idx.tz_convert('UTC')
        try:
            return pd.Timestamp(idx, unit='ms', tz='UTC')
        except Exception:
            logging.debug(f"{tag}: {label} indeks tarih değil")
            return None

    timestamps = {}
    for df, label in [(df_1d, "1D"), (df_4h, "4H"), (df_1h, "1H")]:
        ts = _get_last_ts(df, label)
        if ts is not None:
            timestamps[label] = ts

    if len(timestamps) < 2:
        # Tek timeframe veya tarihsiz indeks → kontrol atlanır
        return True, ""

    # Tüm çiftleri karşılaştır
    labels = list(timestamps.keys())
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            a, b = labels[i], labels[j]
            gap = abs((timestamps[a] - timestamps[b]).total_seconds()) / 3600
            if gap > max_gap_hours:
                return False, (
                    f"{tag}: {a} ({timestamps[a].strftime('%Y-%m-%d %H:%M')}) ile "
                    f"{b} ({timestamps[b].strftime('%Y-%m-%d %H:%M')}) arasında "
                    f"{gap:.1f} saat boşluk (limit: {max_gap_hours}h)"
                )

    return True, ""


# ════════════════════════════════════════
# DG-06: ÇIKTI BÜTÜNLÜK DOĞRULAMASI
# ════════════════════════════════════════
def validate_signal_output(signal_dict: dict) -> tuple[bool, str]:
    """
    Son Çıkış Kapısı: Sinyal JSON'a veya Telegram'a gönderilmeden önce
    fiyat tutarlılığını ve tip güvenliğini sınar.

    Kontroller:
    1. entry_price, sl, tp değerleri sayısal mı?
    2. Fiyatlar makul aralıkta mı? (0 < fiyat < PRICE_MAX)
    3. LONG (AL): SL < Entry < TP
    4. SHORT (SAT): TP < Entry < SL
    5. SL/TP entry'den en az %0.1 uzakta mı? (yuvarlama hatası koruması)

    Returns:
        (is_valid, rejection_reason)
    """
    tag = "[DG-06]"
    ticker = signal_dict.get("ticker", "?")

    # 1. Tip kontrolü
    try:
        entry = float(signal_dict.get("entry_price", 0))
        sl = float(signal_dict.get("sl", 0))
        tp = float(signal_dict.get("tp", 0))
    except (TypeError, ValueError) as e:
        return False, f"{tag} {ticker}: Fiyat tipi geçersiz → {e}"

    signal = signal_dict.get("signal", "AL")

    # 2. NaN kontrolü
    if math.isnan(entry) or math.isnan(sl) or math.isnan(tp):
        return False, f"{tag} {ticker}: Fiyatta NaN tespit edildi (Entry={entry}, SL={sl}, TP={tp})"

    # 3. Sıfır / negatif / aşırı büyük kontrolü
    for label, val in [("Entry", entry), ("SL", sl), ("TP", tp)]:
        if val <= PRICE_MIN:
            return False, f"{tag} {ticker}: {label} çok düşük ({val})"
        if val > PRICE_MAX:
            return False, f"{tag} {ticker}: {label} çok yüksek ({val})"

    # 4. Mantıksal tutarlılık
    if signal == "AL":
        # LONG: SL < Entry < TP
        if sl >= entry:
            return False, (
                f"{tag} {ticker} [LONG]: SL ({sl:.4f}) >= Entry ({entry:.4f}) "
                f"→ Stop-Loss giriş fiyatından yüksek/eşit!"
            )
        if tp <= entry:
            return False, (
                f"{tag} {ticker} [LONG]: TP ({tp:.4f}) <= Entry ({entry:.4f}) "
                f"→ Kar hedefi giriş fiyatından düşük/eşit!"
            )
    elif signal == "SAT":
        # SHORT: TP < Entry < SL
        if sl <= entry:
            return False, (
                f"{tag} {ticker} [SHORT]: SL ({sl:.4f}) <= Entry ({entry:.4f}) "
                f"→ Stop-Loss giriş fiyatından düşük/eşit!"
            )
        if tp >= entry:
            return False, (
                f"{tag} {ticker} [SHORT]: TP ({tp:.4f}) >= Entry ({entry:.4f}) "
                f"→ Kar hedefi giriş fiyatından yüksek/eşit!"
            )

    # 5. Minimum mesafe kontrolü (%0.1 → yuvarlama hatası koruması)
    min_distance_pct = 0.001  # %0.1
    sl_dist = abs(entry - sl) / entry
    tp_dist = abs(tp - entry) / entry

    if sl_dist < min_distance_pct:
        return False, (
            f"{tag} {ticker}: SL-Entry mesafesi çok küçük "
            f"(%{sl_dist * 100:.3f} < %0.1) → Yuvarlama hatası şüphesi"
        )
    if tp_dist < min_distance_pct:
        return False, (
            f"{tag} {ticker}: TP-Entry mesafesi çok küçük "
            f"(%{tp_dist * 100:.3f} < %0.1) → Yuvarlama hatası şüphesi"
        )

    return True, ""


# ════════════════════════════════════════
# WRAPPER FONKSİYONLARI (Kolay Entegrasyon)
# ════════════════════════════════════════
def guard_dataframe(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1d",
    check_freshness: bool = True,
    check_anomaly: bool = True
) -> Optional[pd.DataFrame]:
    """
    Tek çağrıda DG-01 + DG-02 + DG-04 uygular.
    Geçersiz veri → None döner (sinyal üretilmez).
    Geçerli veri → aynı DataFrame döner.
    """
    # DG-01: OHLCV Bütünlük
    ok, reason = validate_ohlcv_integrity(df, symbol, timeframe)
    if not ok:
        logging.warning(reason)
        return None

    # DG-02: Bayatlık
    if check_freshness:
        ok, reason = check_data_freshness(df, symbol, timeframe)
        if not ok:
            logging.warning(reason)
            return None

    # DG-04: Kurumsal Eylem Anomalisi
    if check_anomaly:
        ok, reason = detect_corporate_action_anomaly(df, symbol)
        if not ok:
            logging.warning(reason)
            return None

    return df


def guard_mtf_bundle(
    symbol: str,
    df_1d: Optional[pd.DataFrame] = None,
    df_4h: Optional[pd.DataFrame] = None,
    df_1h: Optional[pd.DataFrame] = None
) -> bool:
    """
    DG-05: Multi-Timeframe hizalama kontrolü.
    Hizalı → True, Hizasız → False (sinyal üretilmemeli).
    """
    ok, reason = validate_timeframe_alignment(symbol, df_1d, df_4h, df_1h)
    if not ok:
        logging.warning(reason)
        return False
    return True


def guard_signal_output(signals: list[dict]) -> list[dict]:
    """
    DG-03 + DG-06: Sinyal listesini yönlendirme + çıktı bütünlük
    filtresinden geçirir. Geçersiz sinyalleri sessizce eler.
    """
    clean_signals = []
    for sig in signals:
        # DG-03: Yönlendirme
        ok, reason = validate_signal_routing(sig)
        if not ok:
            logging.warning(f"[DataGuard] Sinyal reddedildi (routing): {reason}")
            continue

        # DG-06: Çıktı bütünlüğü
        ok, reason = validate_signal_output(sig)
        if not ok:
            logging.warning(f"[DataGuard] Sinyal reddedildi (output): {reason}")
            continue

        clean_signals.append(sig)

    rejected = len(signals) - len(clean_signals)
    if rejected > 0:
        logging.info(
            f"[DataGuard] Son Çıkış Kapısı: {len(signals)} sinyal → "
            f"{len(clean_signals)} geçerli, {rejected} reddedildi"
        )

    return clean_signals
