"""
filter_health.py — Filtre Geçirgenlik İzleyicisi (V3.2 Kaos Çözümü #5)
Her tarama döngüsünde kaç sinyal hangi katmanda öldürüldüğünü izler.
'Analiz Felci' erken tespit sistemi.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

FILTER_STATS_FILE = "filter_health_state.json"
_fh_lock = threading.Lock()

# Her katman için sayaçlar (döngü bazlı)
_cycle_stats = {
    "total_candidates": 0,
    "killed_by_dataguard": 0,
    "killed_by_strategy": 0,
    "killed_by_regime": 0,
    "killed_by_rr": 0,
    "killed_by_circuit_breaker": 0,
    "killed_by_commission": 0,
    "killed_by_cooldown": 0,
    "killed_by_active_trade": 0,
    "killed_by_penalty": 0,
    "killed_by_scorecard": 0,
    "killed_by_quarantine": 0,
    "survived": 0,
}


def record_filter_kill(layer: str):
    """Bir sinyalin hangi katmanda öldürüldüğünü kaydet."""
    key = f"killed_by_{layer}"
    if key in _cycle_stats:
        _cycle_stats[key] += 1


def record_candidate():
    """Değerlendirilen aday sayısını artır."""
    _cycle_stats["total_candidates"] += 1


def record_survivor():
    """Tüm filtrelerden geçen sinyal sayısını artır."""
    _cycle_stats["survived"] += 1


def flush_cycle_stats() -> dict:
    """Döngü sonunda istatistikleri kaydet ve sıfırla. Analiz felci kontrolü yap."""
    with _fh_lock:
        stats = dict(_cycle_stats)
        stats["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Tarihsel veri
        history = []
        if os.path.exists(FILTER_STATS_FILE):
            try:
                with open(FILTER_STATS_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                history = []

        history.append(stats)
        history = history[-96:]  # Son 24 saat (15dk × 96 döngü)

        try:
            with open(FILTER_STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.warning(f"[filter_health] Kayıt hatası: {e}")

        # Sıfırla
        for k in _cycle_stats:
            _cycle_stats[k] = 0

        return stats


def check_analysis_paralysis() -> str | None:
    """
    Analiz felci tespiti — son 6 saatte (24 döngü) sıfır sinyal geçtiyse uyar.
    Heartbeat'te çağrılır.
    """
    if not os.path.exists(FILTER_STATS_FILE):
        return None
    try:
        with open(FILTER_STATS_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except Exception:
        return None

    # Son 24 döngü (6 saat)
    recent = history[-24:] if len(history) >= 24 else history
    if len(recent) < 8:  # En az 2 saatlik veri lazım
        return None

    total_survived = sum(h.get("survived", 0) for h in recent)
    total_candidates = sum(h.get("total_candidates", 0) for h in recent)

    if total_candidates > 50 and total_survived == 0:
        # En çok öldüren katmanı bul
        kill_counts = {}
        for h in recent:
            for k, v in h.items():
                if k.startswith("killed_by_") and isinstance(v, (int, float)) and v > 0:
                    kill_counts[k] = kill_counts.get(k, 0) + v
        worst = max(kill_counts, key=kill_counts.get) if kill_counts else "bilinmiyor"
        return (
            f"⚠️ <b>ANALİZ FELCİ TESPİT EDİLDİ</b>\n"
            f"Son 6 saatte {total_candidates} aday değerlendirildi, "
            f"0 sinyal geçti.\n"
            f"En çok öldüren katman: <code>{worst}</code> ({kill_counts.get(worst, 0)} kill)\n"
            f"Filtre gevşetme veya parametre ayarı gerekli."
        )
    return None


def get_filter_health_summary() -> str:
    """Heartbeat için kısa filtre sağlık özeti."""
    if not os.path.exists(FILTER_STATS_FILE):
        return "📊 Filtre: Veri yok"
    try:
        with open(FILTER_STATS_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except Exception:
        return "📊 Filtre: Okunamadı"

    recent = history[-4:] if len(history) >= 4 else history  # Son 1 saat
    total_c = sum(h.get("total_candidates", 0) for h in recent)
    total_s = sum(h.get("survived", 0) for h in recent)
    rate = (total_s / total_c * 100) if total_c > 0 else 0
    return f"📊 Filtre: {total_s}/{total_c} geçti (%{rate:.1f})"
