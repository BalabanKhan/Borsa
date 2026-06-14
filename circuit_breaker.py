"""
circuit_breaker.py — Psikolojik Devre Kesici (Drawdown / Tilt Shield)
Ardışık SL sayacı + günlük zarar limiti + sessiz mod yönetimi.

Amaç: Piyasa testere modundayken botu sessiz moda alıp
trader'ın intikam işlemine (revenge trading) girmesini engellemek.

Durum dosyaya yazılır → sunucu restart'ından sağ çıkar.
"""
import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone, timedelta

# ════════════════════════════════════════
# YAPILANDIRMA
# ════════════════════════════════════════
CB_STATE_FILE = "circuit_breaker_state.json"
_cb_lock = threading.Lock()  # Thread-Safety: circuit breaker state dosya erişimini korur
MAX_CONSECUTIVE_SL = 3       # Ard arda 3 SL → devre aç (sessiz mod)
COOLDOWN_HOURS = 24           # Sessiz mod süresi (saat)
DAILY_MAX_SL = 5              # Günlük toplam SL limiti (ardışık olmasa bile)


def _load_state() -> dict:
    """Devre kesici durumunu dosyadan yükle (thread-safe)."""
    with _cb_lock:
        if os.path.exists(CB_STATE_FILE):
            try:
                with open(CB_STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.warning(f"[CircuitBreaker] State dosyası okunamadı: {e}")
        return _default_state()


def _save_state(state: dict):
    """Devre kesici durumunu dosyaya atomik kaydet (crash-safe + thread-safe)."""
    with _cb_lock:
        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(mode='w', dir='.', suffix='.tmp', delete=False, encoding='utf-8')
            tmp_path = tmp.name
            json.dump(state, tmp, indent=2, ensure_ascii=False)
            tmp.close()
            os.replace(tmp_path, CB_STATE_FILE)
        except Exception as e:
            logging.warning(f"[CircuitBreaker] State kaydedilemedi: {e}")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


def _default_state() -> dict:
    return {
        "consecutive_sl": 0,
        "daily_sl_count": 0,
        "daily_date": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        "silent_mode": False,
        "silent_until": None,
        "last_sl_tickers": [],
    }


def _reset_daily_if_needed(state: dict) -> dict:
    """Gün değiştiyse günlük sayacı sıfırla."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state.get("daily_date") != today:
        state["daily_sl_count"] = 0
        state["daily_date"] = today
        state["consecutive_sl"] = 0
        state["last_sl_tickers"] = []
        # Sessiz mod süresi dolmuşsa kapat
        if state.get("silent_mode") and state.get("silent_until"):
            try:
                until = datetime.fromisoformat(state["silent_until"])
                if datetime.now(timezone.utc) > until:
                    state["silent_mode"] = False
                    state["silent_until"] = None
                    logging.info("[CircuitBreaker] ✅ Sessiz mod süresi doldu, devre kapandı.")
            except Exception:
                state["silent_mode"] = False
    return state


# ════════════════════════════════════════
# ANA API FONKSİYONLARI
# ════════════════════════════════════════
def record_sl(ticker: str) -> str | None:
    """
    Bir SL gerçekleştiğinde çağrılır.
    Ardışık SL sayacını artırır.
    Eşik aşılırsa sessiz modu aktive eder.

    Returns:
        Telegram bildirim mesajı (varsa), yoksa None.
    """
    state = _load_state()
    state = _reset_daily_if_needed(state)

    state["consecutive_sl"] = state.get("consecutive_sl", 0) + 1
    state["daily_sl_count"] = state.get("daily_sl_count", 0) + 1

    # Son SL'lerin listesi (debug için)
    last_tickers = state.get("last_sl_tickers", [])
    last_tickers.append(ticker)
    state["last_sl_tickers"] = last_tickers[-10:]  # Son 10

    notification = None

    # Kontrol 1: Ardışık SL eşiği
    if state["consecutive_sl"] >= MAX_CONSECUTIVE_SL and not state.get("silent_mode"):
        until = datetime.now(timezone.utc) + timedelta(hours=COOLDOWN_HOURS)
        state["silent_mode"] = True
        state["silent_until"] = until.isoformat()
        logging.warning(
            f"[CircuitBreaker] 🔴 DEVRE AÇILDI! Ardışık {state['consecutive_sl']} SL. "
            f"Sessiz mod: {until.strftime('%Y-%m-%d %H:%M UTC')}'e kadar."
        )
        notification = (
            f"🔴🔴🔴 <b>DEVRE KESİCİ AKTİF — SESSİZ MOD</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Ard arda <b>{state['consecutive_sl']}</b> işlem Stop-Loss oldu!\n"
            f"Son SL'ler: <code>{', '.join(last_tickers[-MAX_CONSECUTIVE_SL:])}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛑 Bot yeni sinyal atmayı <b>DURDURDU</b>.\n"
            f"⏰ Sessiz mod bitişi: <b>{until.strftime('%d/%m %H:%M')} UTC</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>SANA TAVSİYEM:</b>\n"
            f"1. Ekranı kapat, mola ver\n"
            f"2. Açık pozisyonlarını kontrol et\n"
            f"3. İntikam işlemine GİRME"
        )

    # Kontrol 2: Günlük toplam SL eşiği
    elif state["daily_sl_count"] >= DAILY_MAX_SL and not state.get("silent_mode"):
        until = datetime.now(timezone.utc) + timedelta(hours=COOLDOWN_HOURS)
        state["silent_mode"] = True
        state["silent_until"] = until.isoformat()
        logging.warning(
            f"[CircuitBreaker] 🔴 GÜNLÜK SL LİMİTİ AŞILDI! "
            f"Bugün {state['daily_sl_count']} SL."
        )
        notification = (
            f"🔴 <b>GÜNLÜK SL LİMİTİ AŞILDI</b>\n"
            f"Bugün toplam <b>{state['daily_sl_count']}</b> işlem Stop-Loss oldu.\n"
            f"Bot yeni sinyal atmayı <b>DURDURDU</b>.\n"
            f"⏰ Sessiz mod bitişi: <b>{until.strftime('%d/%m %H:%M')} UTC</b>"
        )

    _save_state(state)
    return notification


def record_tp():
    """
    Bir TP gerçekleştiğinde çağrılır.
    Ardışık SL sayacını SIFIRLAR (streak kırıldı).
    """
    state = _load_state()
    state = _reset_daily_if_needed(state)
    state["consecutive_sl"] = 0  # Kazanç geldi → streak kırıldı
    _save_state(state)


def is_circuit_open() -> bool:
    """
    Devre açık mı? (Sinyal gönderilmemeli mi?)

    Returns:
        True → DEVRE AÇIK, sinyal GÖNDERME
        False → Devre kapalı, normal çalış
    """
    state = _load_state()
    state = _reset_daily_if_needed(state)

    if not state.get("silent_mode"):
        return False

    # Süre doldu mu?
    silent_until = state.get("silent_until")
    if silent_until:
        try:
            until = datetime.fromisoformat(silent_until)
            if datetime.now(timezone.utc) > until:
                # Süre doldu → devreyi kapat
                state["silent_mode"] = False
                state["silent_until"] = None
                state["consecutive_sl"] = 0
                _save_state(state)
                logging.info("[CircuitBreaker] ✅ Sessiz mod süresi doldu, devre kapandı.")
                return False
        except Exception:
            pass

    return True


def get_status_message() -> str:
    """Telegram heartbeat'e eklenebilecek durum özeti."""
    state = _load_state()
    state = _reset_daily_if_needed(state)

    if state.get("silent_mode"):
        until = state.get("silent_until", "?")
        return (
            f"🔴 Devre Kesici: AKTİF (Sessiz Mod)\n"
            f"Ardışık SL: {state.get('consecutive_sl', 0)} | "
            f"Günlük SL: {state.get('daily_sl_count', 0)}\n"
            f"Bitiş: {until}"
        )

    return (
        f"🟢 Devre Kesici: Normal\n"
        f"Ardışık SL: {state.get('consecutive_sl', 0)}/{MAX_CONSECUTIVE_SL} | "
        f"Günlük SL: {state.get('daily_sl_count', 0)}/{DAILY_MAX_SL}"
    )


def force_reset():
    """Manuel sıfırlama (Telegram /reset komutu için)."""
    state = _default_state()
    _save_state(state)
    logging.info("[CircuitBreaker] ✅ Manuel sıfırlama yapıldı.")
    return "✅ Devre Kesici sıfırlandı. Sessiz mod kapatıldı."
