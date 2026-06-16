"""
circuit_breaker.py — Psikolojik Devre Kesici (Drawdown / Tilt Shield)

Amaç: Piyasa testere modundayken botu sessiz moda alıp
trader'ın intikam işlemine (revenge trading) girmesini engellemek.

Strateji ve Market bazlı devre kesici ile sadece zarar eden stratejiler susturulur.
OOM ve I/O darboğazını önlemek için in-memory cache mekanizması (Lazy Write) kullanılır.
"""
import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from config import MAX_CONSECUTIVE_SL, COOLDOWN_HOURS, DAILY_MAX_SL

# V3.3.4 Hibrit Şalter: Global günlük limit
GLOBAL_DAILY_MAX_SL = 15

CB_STATE_FILE = "circuit_breaker_state.json"
_cb_lock = threading.RLock()

_STATE_CACHE = None
_LAST_MTIME = 0

# --- EVENT-DRIVEN OBSERVER PATTERN ---
class CircuitBreakerObserver:
    def on_circuit_breaker_triggered(self, ticker: str, strategy: str, reason: str):
        pass

class CircuitBreakerObservable:
    def __init__(self):
        self._observers = []
        
    def attach(self, observer: CircuitBreakerObserver):
        if observer not in self._observers:
            self._observers.append(observer)
            
    def detach(self, observer: CircuitBreakerObserver):
        if observer in self._observers:
            self._observers.remove(observer)
            
    def notify_triggered(self, ticker: str, strategy: str, reason: str):
        for observer in self._observers:
            observer.on_circuit_breaker_triggered(ticker, strategy, reason)

# Global observable instance
cb_events = CircuitBreakerObservable()
# ------------------------------------

def _get_namespace(ticker: str, strategy: str) -> str:
    market = "CRYPTO" if "USDT" in ticker else "BIST"
    return f"{market}_{strategy}"

def _default_state() -> dict:
    return {
        "daily_date": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        "total_daily_sl": 0,
        "strategies": {}
    }

def _default_strategy_state() -> dict:
    return {
        "consecutive_sl": 0,
        "daily_sl_count": 0,
        "silent_mode": False,
        "silent_until": None,
        "last_sl_tickers": []
    }

def _load_state() -> dict:
    global _STATE_CACHE, _LAST_MTIME
    with _cb_lock:
        if not os.path.exists(CB_STATE_FILE):
            if _STATE_CACHE is None:
                _STATE_CACHE = _default_state()
            return _STATE_CACHE

        mtime = os.path.getmtime(CB_STATE_FILE)
        if _STATE_CACHE is None or mtime > _LAST_MTIME:
            try:
                with open(CB_STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    if "strategies" not in state:
                        state = _default_state()
                    if "total_daily_sl" not in state:
                        state["total_daily_sl"] = 0
                    _STATE_CACHE = state
                    _LAST_MTIME = mtime
            except Exception as e:
                logging.warning(f"[CircuitBreaker] State okunamadı, cache kullanılıyor: {e}")
                if _STATE_CACHE is None:
                    _STATE_CACHE = _default_state()
        return _STATE_CACHE

def _save_state(state: dict):
    global _STATE_CACHE, _LAST_MTIME
    with _cb_lock:
        _STATE_CACHE = state
        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(mode='w', dir='.', suffix='.tmp', delete=False, encoding='utf-8')
            tmp_path = tmp.name
            json.dump(state, tmp, indent=2, ensure_ascii=False)
            tmp.close()
            os.replace(tmp_path, CB_STATE_FILE)
            _LAST_MTIME = os.path.getmtime(CB_STATE_FILE)
        except Exception as e:
            logging.warning(f"[CircuitBreaker] State kaydedilemedi: {e}")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

def _reset_daily_if_needed(state: dict) -> dict:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    day_changed = state.get("daily_date") != today
    
    if day_changed:
        state["daily_date"] = today
        state["total_daily_sl"] = 0

    for strat_name, strat in state.get("strategies", {}).items():
        if day_changed:
            strat["daily_sl_count"] = 0
            strat["consecutive_sl"] = 0
            strat["last_sl_tickers"] = []

        if strat.get("silent_mode") and strat.get("silent_until"):
            try:
                until = datetime.fromisoformat(strat["silent_until"])
                if datetime.now(timezone.utc) > until:
                    strat["silent_mode"] = False
                    strat["silent_until"] = None
                    strat["consecutive_sl"] = 0
                    logging.info(f"[CircuitBreaker] ✅ {strat_name} sessiz mod süresi doldu.")
            except Exception:
                strat["silent_mode"] = False

    return state

def record_sl(ticker: str, strategy: str = "UNKNOWN") -> str | None:
    with _cb_lock:
        state = _load_state()
        state = _reset_daily_if_needed(state)

        strat_key = _get_namespace(ticker, strategy)

        if strat_key not in state["strategies"]:
            state["strategies"][strat_key] = _default_strategy_state()
        
        strat_state = state["strategies"][strat_key]

        strat_state["consecutive_sl"] = strat_state.get("consecutive_sl", 0) + 1
        strat_state["daily_sl_count"] = strat_state.get("daily_sl_count", 0) + 1
        state["total_daily_sl"] = state.get("total_daily_sl", 0) + 1

        last_tickers = strat_state.get("last_sl_tickers", [])
        last_tickers.append(ticker)
        strat_state["last_sl_tickers"] = last_tickers[-10:]

        notification = None

        if state["total_daily_sl"] >= GLOBAL_DAILY_MAX_SL:
            logging.critical(f"[CircuitBreaker] 🚨 HİBRİT ŞALTER ATTI! Sistem geneli {GLOBAL_DAILY_MAX_SL} SL limitine ulaşıldı.")
            if state["total_daily_sl"] == GLOBAL_DAILY_MAX_SL:
                notification = (
                    f"🚨🚨 <b>HİBRİT ŞALTER ATTI (MASTER SWITCH)</b> 🚨🚨\n"
                    f"Günlük toplam <b>{state['total_daily_sl']}</b> SL yenildi.\n"
                    f"Sermaye koruma protolü gereği <b>TÜM SİSTEM</b> durduruldu!\n"
                )

        elif strat_state["daily_sl_count"] >= DAILY_MAX_SL and not strat_state.get("silent_mode"):
            until = datetime.now(timezone.utc) + timedelta(hours=COOLDOWN_HOURS)
            strat_state["silent_mode"] = True
            strat_state["silent_until"] = until.isoformat()
            logging.warning(f"[CircuitBreaker] 🔴 {strat_key} GÜNLÜK SL LİMİTİ AŞILDI! Bugün {strat_state['daily_sl_count']} SL.")
            cb_events.notify_triggered(ticker, strategy, "DAILY_SL_LIMIT")
            notification = (
                f"🔴 <b>GÜNLÜK SL LİMİTİ AŞILDI — {strat_key}</b>\n"
                f"Bugün toplam <b>{strat_state['daily_sl_count']}</b> işlem Stop-Loss oldu.\n"
                f"Sadece <b>{strat_key}</b> stratejisi DURDURULDU.\n"
                f"⏰ Sessiz mod bitişi: <b>{until.strftime('%d/%m %H:%M')} UTC</b>"
            )

        elif strat_state["consecutive_sl"] >= MAX_CONSECUTIVE_SL and not strat_state.get("silent_mode"):
            until = datetime.now(timezone.utc) + timedelta(hours=COOLDOWN_HOURS)
            strat_state["silent_mode"] = True
            strat_state["silent_until"] = until.isoformat()
            logging.warning(f"[CircuitBreaker] 🔴 STRATEJİ DEVRESİ AÇILDI ({strat_key})! Ardışık {strat_state['consecutive_sl']} SL.")
            cb_events.notify_triggered(ticker, strategy, "CONSECUTIVE_SL_LIMIT")
            notification = (
                f"🔴🔴🔴 <b>DEVRE KESİCİ AKTİF — {strat_key}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ <b>{strat_key}</b> stratejisinde ard arda <b>{strat_state['consecutive_sl']}</b> SL!\n"
                f"Son SL'ler: <code>{', '.join(strat_state['last_sl_tickers'][-MAX_CONSECUTIVE_SL:])}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛑 Sadece <b>{strat_key}</b> stratejisi DURDURULDU.\n"
                f"⏰ Sessiz mod bitişi: <b>{until.strftime('%d/%m %H:%M')} UTC</b>"
            )

        _save_state(state)
        return notification

def record_tp(ticker: str, strategy: str = "UNKNOWN"):
    with _cb_lock:
        state = _load_state()
        state = _reset_daily_if_needed(state)
        
        strat_key = _get_namespace(ticker, strategy)
        if strat_key in state.get("strategies", {}):
            state["strategies"][strat_key]["consecutive_sl"] = 0
            _save_state(state)

def is_circuit_open(ticker: str, strategy: str = "UNKNOWN") -> bool:
    with _cb_lock:
        state = _load_state()
        state = _reset_daily_if_needed(state)

        if state.get("total_daily_sl", 0) >= GLOBAL_DAILY_MAX_SL:
            return True

        strat_key = _get_namespace(ticker, strategy)
        strat_state = state.get("strategies", {}).get(strat_key, {})
        return bool(strat_state.get("silent_mode"))

def get_status_message() -> str:
    with _cb_lock:
        state = _load_state()
        state = _reset_daily_if_needed(state)

        if state.get("total_daily_sl", 0) >= GLOBAL_DAILY_MAX_SL:
            return f"🚨 HİBRİT ŞALTER ATTI! Sistem geneli tüm işlemler durduruldu. Toplam SL: {state.get('total_daily_sl')}"

        closed_strats = []
        active_strats = []
        
        for strat_name, strat_state in state.get("strategies", {}).items():
            if strat_state.get("silent_mode"):
                until = strat_state.get("silent_until", "?")
                if "T" in until:
                    until = until.split("T")[1][:5]
                closed_strats.append(f"{strat_name} (Bitiş: {until})")
            else:
                cons_sl = strat_state.get("consecutive_sl", 0)
                daily_sl = strat_state.get("daily_sl_count", 0)
                if cons_sl > 0 or daily_sl > 0:
                    active_strats.append(f"{strat_name}(A:{cons_sl}/{MAX_CONSECUTIVE_SL} G:{daily_sl}/{DAILY_MAX_SL})")

        lines = ["🟢 Devre Kesici: Aktif (Strateji Bazlı)"]
        lines.append(f"📊 Global SL Sayacı: {state.get('total_daily_sl', 0)}/{GLOBAL_DAILY_MAX_SL}")
        
        if closed_strats:
            lines.append(f"🛑 Kapalı Stratejiler: {', '.join(closed_strats)}")
        if active_strats:
            lines.append(f"⚠️ Riskli Stratejiler: {', '.join(active_strats)}")

        if not closed_strats and not active_strats:
            lines.append("Tüm stratejiler temiz.")

        return "\n".join(lines)

def force_reset():
    with _cb_lock:
        state = _default_state()
        _save_state(state)
        logging.info("[CircuitBreaker] ✅ Manuel sıfırlama yapıldı.")
        return "✅ Tüm Devre Kesiciler ve Global Sayaç sıfırlandı. Sessiz modlar kapatıldı."

# --- Observer (Event-Driven) Pattern Implementation ---
class CircuitBreakerObserver:
    """
    Backtrader mimarisinden esinlenilmiş, olay güdümlü (event-driven) Devre Kesici Gözlemcisi.
    Trade kapandığında PnL değerine göre otomatik olarak SL veya TP kaydeder ve
    ilgili uyarıları abonelere (listeners) iletir.
    """
    def __init__(self):
        self._listeners = []

    def subscribe(self, listener_func):
        """
        Uyarıları almak isteyen servisleri listeye ekler (Örn: Telegram sender, logger).
        listener_func: Callable (fonksiyon), msg string alır.
        """
        if listener_func not in self._listeners:
            self._listeners.append(listener_func)

    def unsubscribe(self, listener_func):
        if listener_func in self._listeners:
            self._listeners.remove(listener_func)

    def on_trade_closed(self, trade_data: dict):
        """
        Trade kapandığında tetiklenir.
        trade_data beklenen format:
        {
            'ticker': 'BTCUSDT',
            'strategy': 'BIST_9_ORB',
            'pnl_percent': -1.5  # Zarar durumunda negatif
        }
        """
        ticker = trade_data.get('ticker', 'UNKNOWN')
        strategy = trade_data.get('strategy', 'UNKNOWN')
        pnl = trade_data.get('pnl_percent', 0.0)

        if pnl < 0:
            # Stop-Loss durumu
            msg = record_sl(ticker, strategy)
            if msg:
                self.notify_all(msg)
        elif pnl > 0:
            # Take-Profit / Kâr durumu
            record_tp(ticker, strategy)
            
    def notify_all(self, msg: str):
        """
        Devre kesici attığında tüm abonelere mesajı iletir.
        """
        for listener in self._listeners:
            try:
                listener(msg)
            except Exception as e:
                logging.error(f"[CircuitBreakerObserver] Listener hatası: {e}")

# Global Observer Instance
cb_observer = CircuitBreakerObserver()
