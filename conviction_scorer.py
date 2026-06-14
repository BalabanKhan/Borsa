"""
conviction_scorer.py — Ağırlıklı İnanç Puanlama Motoru (V3.3)
════════════════════════════════════════════════════════════════

Boolean AND hapishanesini yıkar, fuzzy scoring ile değiştirir.
Hard Block'lar korunur (güvenlik), Soft Score'lar esneklik sağlar.

Mimari:
  1. Hard Block → Asla esnetilmez (sıfır likidite, karantina, flash crash)
  2. Soft Score → Sigmoid/linear/log fonksiyonlarla 0-100 puanlanır
  3. Weighted Sum → Ağırlıklı toplam → Conviction Grade
  4. Position Sizing → STRONG=%100, MEDIUM=%50, WATCH=sadece izle

Kullanım:
  from conviction_scorer import (
      check_hard_blocks, score_adx, score_volume_ratio,
      calculate_conviction, ConvictionResult, CONVICTION_STRONG
  )
"""

import math
import logging
import os
import json
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ════════════════════════════════════════
# Conviction Grade Sabitleri
# ════════════════════════════════════════
CONVICTION_STRONG = "STRONG"   # 75-100 → Normal pozisyon
CONVICTION_MEDIUM = "MEDIUM"   # 60-74  → Yarım pozisyon
CONVICTION_WATCH  = "WATCH"    # 45-59  → Sadece izle (Telegram watchlist)
CONVICTION_REJECT = "REJECT"   # 0-44   → Sinyal yok

# Grade eşikleri
THRESHOLD_STRONG = 75
THRESHOLD_MEDIUM = 60
THRESHOLD_WATCH  = 45

# Position sizing
POSITION_SIZE_MAP = {
    CONVICTION_STRONG: 100,
    CONVICTION_MEDIUM: 50,
    CONVICTION_WATCH:  0,
    CONVICTION_REJECT: 0,
}


# ════════════════════════════════════════
# Ağırlık Tablosu (toplamı 1.0)
# ════════════════════════════════════════
WEIGHTS = {
    "adx":              0.12,   # 0.15→0.12 (close-price küme azalt)
    "ema_alignment":    0.08,   # 0.10→0.08
    "rsi":              0.10,   # 0.12→0.10
    "rsi_direction":    0.03,   # 0.05→0.03 (RSI gölgesi minimize)
    "volume_ratio":     0.15,   # aynı
    "dollar_volume":    0.08,   # aynı
    "rr_ratio":         0.15,   # 0.12→0.15 (risk/ödül önem arttı)
    "engulfing":        0.07,   # 0.05→0.07
    "regime":           0.08,   # aynı
    "macro":            0.07,   # 0.05→0.07
    "penalty":          0.07,   # 0.05→0.07
}
# Close-price efektif küme: 0.42→0.33 | Bağımsız: 0.35→0.44

# Sanity check: ağırlıklar toplamı 1.0 olmalı
assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001, \
    f"WEIGHTS toplamı 1.0 olmalı, şu an: {sum(WEIGHTS.values())}"


# ════════════════════════════════════════
# Sigmoid / Fuzzy Puanlama Fonksiyonları
# ════════════════════════════════════════

def _is_nan(value):
    """NaN kontrolü — None veya float NaN."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def sigmoid_score(value: float, center: float, k: float = 0.3) -> float:
    """
    Sigmoid tabanlı yumuşak eşik puanlama.

    Hard threshold'un yarattığı 0/1 uçurumu yerine yumuşak S-eğrisi geçişi.
    center = eski hard threshold (örn: ADX=25)
    k = geçiş keskinliği (düşük=daha yumuşak, yüksek=daha keskin)

    Örnek (center=25, k=0.3):
      ADX=15 → ~5,  ADX=20 → ~18,  ADX=25 → 50,
      ADX=30 → ~82, ADX=35 → ~95
    """
    if _is_nan(value):
        return 0.0
    try:
        return 100.0 / (1.0 + math.exp(-k * (value - center)))
    except OverflowError:
        return 0.0 if value < center else 100.0


def linear_score(value: float, low: float, high: float) -> float:
    """Lineer interpolasyon: low → 0 puan, high → 100 puan."""
    if _is_nan(value):
        return 0.0
    if value <= low:
        return 0.0
    if value >= high:
        return 100.0
    return (value - low) / (high - low) * 100.0


def inverse_linear_score(value: float, low: float, high: float) -> float:
    """Ters lineer: low → 100 puan (oversold iyi), high → 0 puan."""
    return 100.0 - linear_score(value, low, high)


def log_score(value: float, min_val: float, max_val: float) -> float:
    """Logaritmik puanlama (hacim gibi geniş aralıklı metrikler için)."""
    if _is_nan(value) or value <= 0 or min_val <= 0:
        return 0.0
    log_val = math.log(max(value, min_val))
    log_min = math.log(min_val)
    log_max = math.log(max(max_val, min_val + 1))
    if log_max <= log_min:
        return 50.0
    return min(100.0, max(0.0, (log_val - log_min) / (log_max - log_min) * 100))


# ════════════════════════════════════════
# Soft Score Hesaplayıcılar
# ════════════════════════════════════════

def score_adx(adx_value: float, adx_prev: float = None) -> float:
    """
    ADX puanlama — sigmoid ile yumuşak geçiş + olgunlaşma cezası.

    Eski: ADX <= 25 → REJECT, ADX > 45 → REJECT (binary uçurum)
    Yeni: Sürekli S-eğrisi + 40 sonrası azalan getiri

    ADX=20→18, 25→50, 30→82, 35→95, 40→97, 45→75, 50→50
    """
    if _is_nan(adx_value):
        return 0.0

    base = sigmoid_score(adx_value, center=25, k=0.3)

    # Olgunlaşma cezası: ADX > 40 → trend olgunlaştı, azalan fırsat
    if adx_value > 40:
        decay = (adx_value - 40) * 3
        base = max(15, base - decay)

    # Momentum bonusu/cezası: yükselen ADX = güç artıyor
    if not _is_nan(adx_prev):
        if adx_value > adx_prev:
            base = min(100, base * 1.10)
        else:
            base *= 0.85

    return round(base, 1)


def score_rsi_oversold(rsi: float, market: str = "BIST") -> float:
    """
    RSI dip avcılığı puanlama (düşük RSI = yüksek puan).

    Eski: RSI < 35 → GİR, RSI >= 35 → TAM REDDET
    Yeni: RSI=15→100, 25→80, 35→50, 40→30, 50→0
    """
    if _is_nan(rsi):
        return 0.0
    center = 35 if market == "BIST" else 28
    return round(inverse_linear_score(rsi, center - 20, center + 15), 1)


def score_rsi_trend(rsi: float, market: str = "BIST") -> float:
    """
    RSI trend takibi puanlama (orta bant = güçlü trend).
    Trend stratejilerinde RSI 40-60 bandı en sağlıklı.
    """
    if _is_nan(rsi):
        return 0.0
    center = 52
    dist = abs(rsi - center)
    return round(max(0, 100 - dist * 2.0), 1)  # 3→2.0: güçlü trendlerde RSI sürtünmesi azaltıldı


def score_volume_ratio(volume: float, vol_sma: float) -> float:
    """
    Hacim/SMA oranı puanlama — sigmoid ile yumuşak eşik.

    Eski: vol > 1.5x SMA → OK, değilse → TAM REDDET
    Yeni: 0.5x→2, 0.8x→10, 1.0x→27, 1.5x→73, 2.0x→95, 3.0x→100
    """
    if _is_nan(vol_sma) or vol_sma <= 0 or _is_nan(volume):
        return 0.0
    ratio = volume / vol_sma
    return round(sigmoid_score(ratio, center=1.5, k=2.5), 1)


def score_dollar_volume(dollar_vol: float, market: str = "KRIPTO") -> float:
    """Mutlak dolar/TL hacim puanlama (logaritmik ölçek)."""
    if _is_nan(dollar_vol) or dollar_vol <= 0:
        return 0.0
    if market == "KRIPTO":
        return round(log_score(dollar_vol, 100_000, 10_000_000), 1)
    elif market == "EMTIA":
        return round(log_score(dollar_vol, 50_000, 5_000_000), 1)
    else:  # BIST
        return round(log_score(dollar_vol, 1_000_000, 100_000_000), 1)


def score_rr_ratio(rr: float) -> float:
    """
    R:R oranı puanlama — sigmoid ile yumuşak eşik.

    Eski: R:R < 2.0 → TAM REDDET
    Yeni: 1.0→8, 1.5→38, 2.0→73, 2.5→92, 3.0→98
    """
    if _is_nan(rr) or rr <= 0:
        return 0.0
    return round(sigmoid_score(rr, center=2.0, k=2.0), 1)


def score_ema_alignment(price: float, ema_fast: float, ema_mid: float,
                        ema_slow: float = None) -> float:
    """
    EMA dizilimi puanlama — kademeli ödül.
    Tam dizilim (price > fast > mid > slow) = 100
    Kısmi dizilim = kademeli puan (sıfır değil!)
    """
    if _is_nan(price) or _is_nan(ema_fast) or _is_nan(ema_mid):
        return 0.0

    score = 0.0
    if price > ema_fast:
        score += 30
    if ema_fast > ema_mid:
        score += 40
    if not _is_nan(ema_slow):
        if ema_mid > ema_slow:
            score += 30
        elif ema_fast > ema_slow:
            score += 15
    else:
        score += 15  # Veri yoksa nötr

    return score


def score_ema_dip_distance(price: float, ema_fast: float, ema_mid: float,
                           ema_slow: float = None) -> float:
    """
    Dip avcılığı için EMA mesafe puanlama (B-01 fix).
    Fiyat EMA altındaysa → yüksek puan (derin dip = iyi fırsat).
    EMA yapısı hala boğaysa (fast > mid) → bonus.
    """
    if _is_nan(price) or _is_nan(ema_fast) or _is_nan(ema_mid):
        return 0.0

    score = 0.0

    # Fiyatın EMA'dan uzaklığı: daha aşağıda = daha iyi
    if price < ema_fast:
        pct_below = (ema_fast - price) / ema_fast * 100
        score += min(40, pct_below * 8)  # %5 aşağıda = 40 puan tam
    else:
        score += 5  # EMA üstünde = minimal puan

    # EMA yapısal sağlık: hala boğa dizilimi = bounce şansı yüksek
    if ema_fast > ema_mid:
        score += 35  # Yapı bozulmamış = büyük bonus
    else:
        score += 10  # Yapı bozuk = düşük bonus

    # Slow EMA bonus
    if not _is_nan(ema_slow):
        if ema_mid > ema_slow:
            score += 25  # Uzun vadeli trend sağlam
        elif ema_fast > ema_slow:
            score += 12
    else:
        score += 12  # Veri yoksa nötr

    return min(100.0, score)


def score_ema_short(price: float, ema_fast: float, ema_mid: float,
                    ema_slow: float = None) -> float:
    """
    SHORT stratejileri için EMA dizilimi puanlama (1D fix).
    Fiyat < EMA'lar → yüksek puan (düşüş trendi = SHORT için iyi).
    Ters dizilim (fast < mid < slow) = en iyi.
    """
    if _is_nan(price) or _is_nan(ema_fast) or _is_nan(ema_mid):
        return 50.0  # Veri yoksa nötr (Bear Hunter NaN koruması)

    score = 0.0
    if price < ema_fast:
        score += 30  # Fiyat EMA altında = SHORT güçlü
    if ema_fast < ema_mid:
        score += 40  # Death cross = düşüş trendi
    if not _is_nan(ema_slow):
        if ema_mid < ema_slow:
            score += 30  # Tam ayı dizilimi
        elif ema_fast < ema_slow:
            score += 15
    else:
        score += 15  # Veri yoksa nötr

    return score


def score_regime(regime: str) -> float:
    """Piyasa rejimi puanlama — LONG stratejiler (BULL/NEUTRAL/BEAR)."""
    return {"BULL": 100.0, "NEUTRAL": 50.0, "BEAR": 10.0}.get(regime, 50.0)


def score_regime_short(regime: str) -> float:
    """SHORT stratejileri için piyasa rejimi (BEAR = iyi, BULL = kötü)."""
    return {"BEAR": 100.0, "NEUTRAL": 50.0, "BULL": 10.0}.get(regime, 50.0)


def score_engulfing(has_engulfing: bool) -> float:
    """
    Engulfing mum onayı puanlama.
    Eski: yoksa → TAM REDDET
    Yeni: var→85, yok→30 (cezalandır ama öldürme)
    """
    return 85.0 if has_engulfing else 30.0


def score_rsi_direction(rsi_current: float, rsi_prev: float) -> float:
    """RSI yön puanlama: yükseliyor mu düşüyor mu."""
    if _is_nan(rsi_current) or _is_nan(rsi_prev):
        return 50.0
    if rsi_current > rsi_prev:
        return 80.0
    elif rsi_current < rsi_prev:
        return 20.0
    return 50.0


def score_macro_alignment(is_aligned: bool) -> float:
    """Makro uyum puanlama (endeks/BTC yönü)."""
    return 90.0 if is_aligned else 30.0


def score_penalty_level(consecutive_sl: int) -> float:
    """
    Ceza seviyesi puanlama.
    0 SL → 100, 1 SL → 75, 2 SL → 45, 3-4 → düşük, 5+ → hard block
    """
    if consecutive_sl <= 0:
        return 100.0
    elif consecutive_sl == 1:
        return 75.0
    elif consecutive_sl == 2:
        return 45.0
    return 0.0


# ════════════════════════════════════════
# Hard Block Kontrolleri
# ════════════════════════════════════════

def check_hard_blocks(
    volume: float,
    price: float,
    is_quarantined: bool = False,
    is_circuit_open: bool = False,
    is_darth_maul_flag: bool = False,
    sl_direction_ok: bool = True,
    rr_ratio: float = None,
    consecutive_sl: int = 0,
) -> tuple:
    """
    Asla esnetilemeyen güvenlik kontrolleri.
    Bu kontroller sigmoid'e tabi değildir — binary kalır.

    Returns:
        (blocked: bool, reason: str)
    """
    dollar_vol = (volume or 0) * (price or 0)

    if dollar_vol < 50_000:
        return True, "HB-1: Sıfıra yakın hacim — likidite yok"

    if is_quarantined:
        return True, "HB-2: Varlık karantinada — veri güvenilmez"

    if is_circuit_open:
        return True, "HB-3: Devre Kesici aktif — sistem korumada"

    if is_darth_maul_flag:
        return True, "HB-5: Darth Maul mumu — flash crash"

    if not sl_direction_ok:
        return True, "HB-4: SL yönü yanlış — veri bütünlüğü bozuk"

    if rr_ratio is not None and rr_ratio < 1.0:
        return True, "HB-6: R:R < 1.0 — risk ödülden büyük"

    if consecutive_sl >= 5:
        return True, "HB-7: 5+ ardışık SL — yapısal sorun"

    return False, ""


# ════════════════════════════════════════
# Conviction Sonuç Yapısı
# ════════════════════════════════════════

@dataclass
class ConvictionResult:
    """Conviction hesaplama sonucu."""
    total_score: float = 0.0
    grade: str = CONVICTION_REJECT
    hard_blocked: bool = False
    hard_block_reason: str = ""
    component_scores: dict = field(default_factory=dict)
    position_size_pct: float = 0.0

    def to_reason_suffix(self) -> str:
        """Sinyal reason metnine eklenecek conviction özeti."""
        emoji = {
            CONVICTION_STRONG: "🟢",
            CONVICTION_MEDIUM: "🟡",
            CONVICTION_WATCH: "🟠",
            CONVICTION_REJECT: "🔴",
        }
        e = emoji.get(self.grade, "⚪")
        return f"\n{e} Conviction: {self.total_score:.0f}/100 ({self.grade}) | Poz: %{self.position_size_pct:.0f}"

    def top_factors(self, n: int = 3) -> list:
        """En yüksek puanlı faktörleri döndür."""
        return sorted(self.component_scores.items(),
                      key=lambda x: x[1], reverse=True)[:n]

    def weak_factors(self, n: int = 2) -> list:
        """En düşük puanlı faktörleri döndür."""
        return sorted(self.component_scores.items(),
                      key=lambda x: x[1])[:n]


# ════════════════════════════════════════
# Conviction A/B Test — Shadow Evaluation
# ════════════════════════════════════════

_ab_lock = threading.Lock()
AB_STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ab_test_stats.json')


def _ab_evaluate(ticker, score, control_grade, control_thresholds, experiment_thresholds):
    """A/B Test: Experiment eşikleriyle shadow grade hesapla ve logla."""
    # Experiment grade hesapla
    if score >= experiment_thresholds['STRONG']:
        exp_grade = 'STRONG'
    elif score >= experiment_thresholds['MEDIUM']:
        exp_grade = 'MEDIUM'
    elif score >= experiment_thresholds['WATCH']:
        exp_grade = 'WATCH'
    else:
        exp_grade = 'REJECT'

    # Fark varsa logla
    if control_grade != exp_grade:
        logging.info(
            f'[A/B Test] {ticker}: Score={score:.0f} '
            f'Control={control_grade} vs Experiment={exp_grade} — '
            f'FARK TESPİT EDİLDİ'
        )

    # İstatistikleri dosyaya yaz (atomik)
    _ab_update_stats(ticker, score, control_grade, exp_grade)


def _ab_update_stats(ticker, score, control_grade, exp_grade):
    """A/B test istatistiklerini JSON dosyasına atomik olarak yaz."""
    with _ab_lock:
        stats = {}
        if os.path.exists(AB_STATS_FILE):
            try:
                with open(AB_STATS_FILE, 'r') as f:
                    stats = json.load(f)
            except (json.JSONDecodeError, IOError):
                stats = {}

        # Toplam sayaçlar
        stats.setdefault('total_evaluations', 0)
        stats['total_evaluations'] += 1
        stats.setdefault('divergence_count', 0)
        if control_grade != exp_grade:
            stats['divergence_count'] += 1

        # Grade dağılımları
        for group_name, grade in [('control', control_grade), ('experiment', exp_grade)]:
            key = f'{group_name}_grades'
            stats.setdefault(key, {})
            stats[key][grade] = stats[key].get(grade, 0) + 1

        # Son 10 farklılık kaydı (ring buffer)
        if control_grade != exp_grade:
            divergences = stats.setdefault('recent_divergences', [])
            from datetime import datetime, timezone
            divergences.append({
                'ticker': ticker,
                'score': round(score, 1),
                'control': control_grade,
                'experiment': exp_grade,
                'time': datetime.now(timezone.utc).isoformat()
            })
            stats['recent_divergences'] = divergences[-10:]  # Son 10

        # Atomik yaz
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(AB_STATS_FILE), suffix='.tmp'
        )
        try:
            with os.fdopen(tmp_fd, 'w') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, AB_STATS_FILE)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


# ════════════════════════════════════════
# Ana Conviction Hesaplayıcı
# ════════════════════════════════════════

def calculate_conviction(
    scores: dict,
    hard_blocked: bool = False,
    block_reason: str = "",
    weights: dict = None,
) -> ConvictionResult:
    """
    Ağırlıklı conviction skoru hesapla.

    Args:
        scores: Her soft faktör için 0-100 arası puan dict'i.
        hard_blocked: Hard block tetiklendi mi
        block_reason: Hard block nedeni
        weights: Özel ağırlıklar (None ise global WEIGHTS kullanılır)

    Returns:
        ConvictionResult
    """
    result = ConvictionResult()
    result.hard_blocked = hard_blocked
    result.hard_block_reason = block_reason

    if hard_blocked:
        result.grade = CONVICTION_REJECT
        result.total_score = 0
        result.position_size_pct = 0
        logger.debug(f"[Conviction] Hard Block: {block_reason}")
        return result

    w = weights or WEIGHTS
    total = 0.0

    for factor, weight in w.items():
        factor_score = scores.get(factor, 0.0)
        result.component_scores[factor] = round(factor_score, 1)
        total += factor_score * weight

    result.total_score = round(total, 1)

    # Rejim-adaptif eşikler: regime skoru düşükse eşikleri gevşet
    regime_score = scores.get("regime", 50.0)
    if regime_score >= 80:       # BULL (veya SHORT'ta BEAR → iyi)
        t_strong, t_medium, t_watch = THRESHOLD_STRONG, THRESHOLD_MEDIUM, THRESHOLD_WATCH
    elif regime_score >= 40:     # NEUTRAL
        t_strong, t_medium, t_watch = 68, 52, 38
    else:                        # BEAR long pozisyonlar (regime=10)
        t_strong, t_medium, t_watch = 65, 48, 35

    if total >= t_strong:
        result.grade = CONVICTION_STRONG
    elif total >= t_medium:
        result.grade = CONVICTION_MEDIUM
    elif total >= t_watch:
        result.grade = CONVICTION_WATCH
    else:
        result.grade = CONVICTION_REJECT

    result.position_size_pct = POSITION_SIZE_MAP.get(result.grade, 0)

    logger.info(
        f"[Conviction] Score={result.total_score:.0f} "
        f"Grade={result.grade} Pos={result.position_size_pct}%"
    )

    # ════════════════════════════════════════
    # Conviction A/B Test — Shadow Evaluation
    # ════════════════════════════════════════
    try:
        from config import CONVICTION_AB_ENABLED, CONVICTION_THRESHOLDS_CONTROL, CONVICTION_THRESHOLDS_EXPERIMENT
        if CONVICTION_AB_ENABLED:
            _ticker = scores.get('_ticker', 'N/A')
            _ab_evaluate(_ticker, result.total_score, result.grade,
                         CONVICTION_THRESHOLDS_CONTROL, CONVICTION_THRESHOLDS_EXPERIMENT)
    except Exception as e:
        logging.debug(f'[A/B Test] Hata: {e}')

    return result


# ════════════════════════════════════════
# Strateji Tipleri İçin Hazır Score Paketleri
# ════════════════════════════════════════

def build_trend_scores(
    adx, adx_prev,
    price, ema_fast, ema_mid, ema_slow,
    rsi, rsi_prev,
    volume, vol_sma, dollar_vol,
    rr,
    has_engulfing,
    regime,
    macro_aligned,
    consecutive_sl,
    market="BIST",
):
    """Trend stratejileri (BIST 2, KRİPTO 2) için skor paketi."""
    return {
        "adx":           score_adx(adx, adx_prev),
        "ema_alignment": score_ema_alignment(price, ema_fast, ema_mid, ema_slow),
        "rsi":           score_rsi_trend(rsi, market),
        "rsi_direction": score_rsi_direction(rsi, rsi_prev),
        "volume_ratio":  score_volume_ratio(volume, vol_sma),
        "dollar_volume": score_dollar_volume(dollar_vol, market),
        "rr_ratio":      score_rr_ratio(rr),
        "engulfing":     score_engulfing(has_engulfing),
        "regime":        score_regime(regime),
        "macro":         score_macro_alignment(macro_aligned),
        "penalty":       score_penalty_level(consecutive_sl),
    }


def build_dip_scores(
    rsi_daily, rsi_hourly, rsi_prev,
    price, ema_fast, ema_mid,
    volume, vol_sma, dollar_vol,
    rr,
    has_engulfing,
    regime,
    macro_aligned,
    consecutive_sl,
    market="BIST",
):
    """Dip avcılığı stratejileri (BIST 1, KRİPTO 1) için skor paketi."""
    return {
        "adx":           50.0,  # Dip avcılığında ADX önemsiz → nötr
        "ema_alignment": score_ema_dip_distance(price, ema_fast, ema_mid),
        "rsi":           score_rsi_oversold(rsi_daily, market),
        "rsi_direction": score_rsi_direction(rsi_hourly, rsi_prev),
        "volume_ratio":  score_volume_ratio(volume, vol_sma),
        "dollar_volume": score_dollar_volume(dollar_vol, market),
        "rr_ratio":      score_rr_ratio(rr),
        "engulfing":     score_engulfing(has_engulfing),
        "regime":        score_regime(regime),
        "macro":         score_macro_alignment(macro_aligned),
        "penalty":       score_penalty_level(consecutive_sl),
    }


def build_breakout_scores(
    bb_width,
    price, ema_fast, ema_mid, ema_slow,
    volume, vol_sma, dollar_vol,
    rr,
    regime,
    macro_aligned,
    consecutive_sl,
    market="BIST",
):
    """Kırılım/Squeeze stratejileri (BIST 3/5, KRİPTO 3) için skor paketi."""
    squeeze_score = inverse_linear_score(bb_width, 0.05, 0.20) if bb_width else 50.0

    return {
        "adx":           squeeze_score,
        "ema_alignment": score_ema_alignment(price, ema_fast, ema_mid, ema_slow),
        "rsi":           70.0,
        "rsi_direction": 70.0,
        "volume_ratio":  score_volume_ratio(volume, vol_sma),
        "dollar_volume": score_dollar_volume(dollar_vol, market),
        "rr_ratio":      score_rr_ratio(rr),
        "engulfing":     70.0,
        "regime":        score_regime(regime),
        "macro":         score_macro_alignment(macro_aligned),
        "penalty":       score_penalty_level(consecutive_sl),
    }


def build_short_scores(
    adx, adx_prev,
    price, ema_fast, ema_mid, ema_slow,
    rsi, rsi_prev,
    volume, vol_sma, dollar_vol,
    rr,
    has_engulfing,
    regime,
    macro_aligned,
    consecutive_sl,
    market="KRIPTO",
):
    """SHORT stratejileri (SHORT 1-4, Bear Hunter) için skor paketi."""
    return {
        "adx":           score_adx(adx, adx_prev),
        "ema_alignment": score_ema_short(price, ema_fast, ema_mid, ema_slow),
        "rsi":           score_rsi_trend(rsi, market),
        "rsi_direction": score_rsi_direction(rsi, rsi_prev),
        "volume_ratio":  score_volume_ratio(volume, vol_sma),
        "dollar_volume": score_dollar_volume(dollar_vol, market),
        "rr_ratio":      score_rr_ratio(rr),
        "engulfing":     score_engulfing(has_engulfing),
        "regime":        score_regime_short(regime),
        "macro":         score_macro_alignment(macro_aligned),
        "penalty":       score_penalty_level(consecutive_sl),
    }
