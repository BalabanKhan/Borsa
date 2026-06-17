"""
trade_tracker.py
Aktif işlemleri bir JSON dosyasına kaydeder ve periyodik olarak kontrol ederek
Kar Al (TP), Zarar Kes (SL) veya Çıkış Revizesi bildirimleri üretir.
"""
import json
import logging
import math
import os
import csv
import tempfile
import threading
from datetime import datetime, timezone
from typing import Optional
from data_sources import get_funding_rate
from data_guard import validate_signal_output
from circuit_breaker import cb_observer

# V3.2 Kaos Çözümleri
from penalty_box import record_asset_sl, record_asset_tp
from strategy_scorecard import record_trade_result

TRACKER_FILE = "active_trades.json"
HISTORY_FILE = "trade_history.json"
_trade_file_lock = threading.Lock()  # Thread-Safety: JSON dosya erişimini korur


# Y-05: İç kullanım — lock TUTULMADAN çağrılır, caller lock tutmalıdır
def _load_trades_unlocked():
    """Lock TUTULMADAN çağrılır — caller'ın _trade_file_lock tutması gerekir."""
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logging.warning(f"[load_trades] JSON bozuk, yedek alınıyor: {e}")
            backup = TRACKER_FILE + f".corrupt.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            try:
                os.rename(TRACKER_FILE, backup)
                logging.warning(f"[load_trades] Bozuk dosya yedeklendi: {backup}")
            except Exception as be:
                logging.warning(f"[load_trades] Yedekleme başarısız: {be}")
            return []
        except Exception as e:
            logging.warning(f"[load_trades] Dosya okuma hatası: {e}")
            return []
    return []


def _sanitize_for_json(obj):
    """Recursively converts numpy and pandas types to standard Python types."""
    try:
        import numpy as np
        if isinstance(obj, (np.int64, np.int32, np.int16, np.int8, np.integer)):
            return int(obj)
        if isinstance(obj, (np.float64, np.float32, np.float16, np.floating)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return [_sanitize_for_json(x) for x in obj.tolist()]
    except ImportError:
        pass

    try:
        import pandas as pd
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except ImportError:
        pass

    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(x) for x in obj]
    elif isinstance(obj, tuple):
        return tuple(_sanitize_for_json(x) for x in obj)
    return obj


def _save_trades_unlocked(trades):
    """Lock TUTULMADAN çağrılır — caller'ın _trade_file_lock tutması gerekir."""
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(mode='w', dir='.', suffix='.tmp', delete=False, encoding='utf-8')
        tmp_path = tmp.name
        sanitized = _sanitize_for_json(trades)
        json.dump(sanitized, tmp, indent=4, ensure_ascii=False)
        tmp.close()
        os.replace(tmp_path, TRACKER_FILE)
    except Exception as e:
        logging.warning(f"[save_trades] Kayıt hatası: {e}")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def load_trades():
    """Thread-safe: Aktif işlemleri JSON dosyasından yükle."""
    with _trade_file_lock:
        return _load_trades_unlocked()


def save_trades(trades):
    """Crash-safe atomic write: önce temp dosyaya yaz, sonra atomik replace."""
    with _trade_file_lock:
        _save_trades_unlocked(trades)


# 99 yapılmıştır
# V3.4: Sinyal verilerini detaylı analiz edebilmek için add_trade fonksiyonuna
# conviction skorları, dereceleri, pozisyon boyutları ve ham indikatör verileri eklenmiştir.
def add_trade(ticker, signal, entry_price, sl, tp, reason, provider, strategy="", indicators=None, is_watch=False,
              market=None, conviction_score=None, conviction_grade=None, position_size_pct=None, raw_indicators=None, conviction_details=None):
    # DG-06: Son Çıkış Kapısı — fiyat tutarlılığı kontrolü
    check_dict = {"ticker": ticker, "signal": signal, "entry_price": entry_price,
                  "sl": sl, "tp": tp, "market": market or ("KRIPTO" if "/" in ticker else "BIST")}
    ok, reason_dg = validate_signal_output(check_dict)
    if not ok:
        logging.warning(f"[add_trade] DG-06 VETO: {reason_dg}")
        return None

    # Y-05: Tüm read-modify-write döngüsü tek lock altında — TOCTOU koruması
    with _trade_file_lock:
        trades = _load_trades_unlocked()
        trade_id = f"{ticker}_{int(os.path.getmtime(TRACKER_FILE) if os.path.exists(TRACKER_FILE) else 0)}_{len(trades)}"

        # İzleyen stop için gerekli alanlar
        trailing_dist = entry_price - sl if signal == "AL" else sl - entry_price
        highest_high = entry_price
        lowest_low = entry_price

        new_trade = {
            "id": trade_id,
            "ticker": ticker,
            "signal": signal,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "reason": reason,
            "provider": provider,
            "strategy": strategy,
            "indicators": indicators or {},
            "status": "ACTIVE",
            "trailing_dist": trailing_dist,
            "highest_high": highest_high,
            "lowest_low": lowest_low,
            "entry_time": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00'),
            "is_watch": is_watch,
            "market": market or ("KRİPTO" if "/" in ticker else "BIST"),
            "conviction_score": conviction_score,
            "conviction_grade": conviction_grade,
            "position_size_pct": position_size_pct,
            "raw_indicators": raw_indicators or {},
            "conviction_details": conviction_details or {}
        }
        trades.append(new_trade)
        _save_trades_unlocked(trades)
    return new_trade


# ---------------------------------------------------------------------------
# Helper: Kademeli Kar Al (Scale-Out)
# ---------------------------------------------------------------------------
def _check_scale_out(t, profit_pct, signal, strategy_name, current_price=0):
    """
    Kademeli kâr alma kontrolü.
    LONG: +%5'te scale out, SL'yi entry'ye çek (breakeven).
    SHORT: FOMO İNFAZI için +%10, diğerleri +%5, SL'yi entry'ye çek.
    """
    notifications = []
    ticker = t["ticker"]

    if t.get("partial_tp_hit", False):
        return t, notifications

    if signal == "AL":
        if profit_pct >= 5.0:
            t["partial_tp_hit"] = True
            entry_price = float(t["entry_price"])
            notifications.append(
                f"💰 <b>KADEMELİ KÂR AL (Scale-Out)</b>\n"
                f"Varlık: <code>{ticker}</code>\n"
                f"Anlık Fiyat: <code>{current_price:.4f}</code>\n"
                f"Kâr: +%{profit_pct:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📋 <b>YAPMAN GEREKEN:</b>\n"
                f"1. Pozisyonun %50'sini <b>ŞİMDİ</b> sat\n"
                f"2. Kalan %50 için yeni SL: <code>{entry_price:.4f}</code> (giriş fiyatı)\n"
                f"3. Kalan hedef: Trailing Stop'a bırak"
            )
            if float(t["sl"]) < float(t["entry_price"]):
                new_sl = float(t["entry_price"])
                t["sl"] = new_sl
                notifications.append(
                    f"🛡️ <b>SIFIR RİSK MODU (Breakeven)</b>\n"
                    f"Varlık: <code>{ticker}</code>\n"
                    f"Stop-Loss giriş fiyatına çekildi: {new_sl:.4f}"
                )

    elif signal == "SAT":
        scale_out_target = 10.0 if "FOMO İNFAZI" in strategy_name else 5.0
        if profit_pct >= scale_out_target:
            t["partial_tp_hit"] = True
            entry_price = float(t["entry_price"])
            notifications.append(
                f"💰 <b>KADEMELİ KÂR AL (Scale-Out) [SHORT]</b>\n"
                f"Varlık: <code>{ticker}</code>\n"
                f"Anlık Fiyat: <code>{current_price:.4f}</code>\n"
                f"Kâr: +%{profit_pct:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📋 <b>YAPMAN GEREKEN:</b>\n"
                f"1. SHORT pozisyonun %50'sini <b>ŞİMDİ</b> kapat\n"
                f"2. Kalan %50 için yeni SL: <code>{entry_price:.4f}</code> (giriş fiyatı)\n"
                f"3. Kalan hedef: Trailing Stop'a bırak"
            )
            if float(t["sl"]) > float(t["entry_price"]):
                new_sl = float(t["entry_price"])
                t["sl"] = new_sl
                notifications.append(
                    f"🛡️ <b>SIFIR RİSK MODU (Breakeven) [SHORT]</b>\n"
                    f"Varlık: <code>{ticker}</code>\n"
                    f"Stop-Loss giriş fiyatına çekildi: {new_sl:.4f}"
                )

    return t, notifications


# 99 yapılmıştır
# Yapısal zemin (EMA-20 vb.) seviyesini dinamik olarak çeken yardımcı fonksiyondur.
def _get_structural_floor(ticker: str, signal: str) -> float:
    """
    Aktif işlemin yapıldığı varlık için 1H EMA-20 değerini çekerek yapısal zemin olarak döner.
    Hata durumlarında sessizce None döner (Kaos İzolasyonu).
    """
    import config
    try:
        from data_sources import get_bist_data, get_crypto_data, get_emtia_data
        df_1d = None
        df_4h = None
        df_1h = None

        if ticker.endswith(".IS"):
            # BIST
            _, _, df_1h = get_bist_data(ticker)
        elif "=" in ticker or "GLDTR" in ticker or "GMSTR" in ticker:
            # Emtia
            from data_sources import get_emtia_1h_data
            df_1h = get_emtia_1h_data(ticker)
        else:
            # Kripto
            from data_sources import get_crypto_1h_data
            df_1h = get_crypto_1h_data(ticker)

        if df_1h is not None and not df_1h.empty:
            # EMA_20 hesapla
            import pandas_ta as ta
            df_1h.ta.ema(length=config.IND_EMA_MID, append=True)
            ema_col = f"EMA_{config.IND_EMA_MID}"
            if ema_col in df_1h.columns:
                last_ema = df_1h[ema_col].iloc[-1]
                if last_ema is not None and not math.isnan(last_ema):
                    return float(last_ema)
    except Exception as e:
        logging.warning(f"[_get_structural_floor] {ticker} için EMA hesaplanamadı: {e}")
    return None


# 99 yapılmıştır
# İzleyen stop güncellemeleri; dinamik ATR çarpanı (Chandelier), yapısal trend desteği (EMA-20)
# ve avcı tuzaklarından kaçınmak için asimetrik deterministik gürültü (Anti-Hunt) ile hesaplanır.
def _update_trailing_stop(t, current_price, profit_pct, signal, strategy_name):
    """
    Hibrit izleyen stop güncelleme motoru.
    Ters Mandal (Ratchet): LONG stop yalnızca YUKARI, SHORT stop yalnızca AŞAĞI gider.
    """
    import config
    notifications = []
    ticker = t["ticker"]
    sl = float(t["sl"])
    trailing_dist = float(t.get("trailing_dist", abs(float(t["entry_price"]) - sl)))

    if signal == "AL":
        raw_hh = t.get("highest_high")
        if raw_hh is None:
            highest_high = float(t["entry_price"])
            t["highest_high"] = highest_high
        else:
            highest_high = float(raw_hh)

        # ATR bazlı minimum trailing mesafe (hiçbir zaman bunun altına düşmez)
        atr_floor = trailing_dist * 0.3  # Orijinal ATR mesafesinin %30'u

        # Hibrit Dynamic Chandelier ATR Çarpanı
        if config.HYBRID_STOP_ENABLED:
            if profit_pct >= 15.0:
                multiplier = 1.0
            elif profit_pct >= 10.0:
                multiplier = 1.5
            elif profit_pct >= 5.0:
                multiplier = 2.0
            else:
                multiplier = 2.5
            current_trailing_dist = trailing_dist * (multiplier / 2.5)
        else:
            # Standart trailing sıkıştırması
            if profit_pct >= 15.0:
                current_trailing_dist = max(current_price * 0.005, atr_floor)
            elif profit_pct >= 10.0:
                current_trailing_dist = max(current_price * 0.015, atr_floor)
            else:
                current_trailing_dist = trailing_dist

        current_trailing_dist = max(current_trailing_dist, atr_floor)

        # Highest high güncelle
        if current_price > highest_high:
            highest_high = current_price
            t["highest_high"] = highest_high

        new_sl = highest_high - current_trailing_dist

        # Yapısal Zemin (EMA-20 vb.) Koruması
        if config.STRUCTURAL_STOP_ENABLED:
            struct_floor = _get_structural_floor(ticker, signal)
            if struct_floor is not None:
                struct_sl = struct_floor * 0.999  # Yapısal zemin altında %0.1 marj bırak
                new_sl = max(new_sl, struct_sl)

        # Anti-Hunt Offset (Stop Avı Koruması)
        ticker_noise = (sum(ord(c) for c in ticker) % 100) / 100000.0  # Deterministik gürültü (örn: 0.00021)
        asymmetric_offset = config.ANTI_HUNT_OFFSET_PCT + ticker_noise
        new_sl = new_sl * (1.0 - asymmetric_offset)

        # RED-09: Trailing stop zemin koruması — bir kez BE geçildiyse asla geri gitme
        entry_price = float(t["entry_price"])
        if sl >= entry_price:
            new_sl = max(new_sl, entry_price)

        # Ters Mandal: LONG stop yalnızca YUKARI gider
        if new_sl > sl:
            old_sl = sl
            t["sl"] = new_sl
            sl_change_pct = (abs(new_sl - old_sl) / max(abs(old_sl), 1e-8)) * 100
            crossed_breakeven = old_sl < float(t["entry_price"]) <= new_sl
            last_trailing_notify = t.get("last_trailing_notify_time", 0)
            now_ts = datetime.now(timezone.utc).timestamp()
            notify_cooldown_ok = (now_ts - last_trailing_notify) > 1800
            if crossed_breakeven or (sl_change_pct >= 1.0 and notify_cooldown_ok):
                t["last_trailing_notify_time"] = now_ts
                label = " 🛡️ BREAKEVEN GEÇİLDİ!" if crossed_breakeven else ""
                notifications.append(
                    f"🔄 <b>İzleyen Stop Güncellendi</b>{label}\n"
                    f"Varlık: <code>{ticker}</code>\n"
                    f"Kâr: +%{profit_pct:.2f}\n"
                    f"Eski SL: {old_sl:.4f} → Yeni SL: <b>{new_sl:.4f}</b>\n"
                    f"Değişim: %{sl_change_pct:.2f}"
                )

    elif signal == "SAT":
        raw_ll = t.get("lowest_low")
        if raw_ll is None:
            lowest_low = float(t["entry_price"])
            t["lowest_low"] = lowest_low
        else:
            lowest_low = float(raw_ll)

        atr_floor_short = trailing_dist * 0.3

        # Hibrit Dynamic Chandelier ATR Çarpanı
        if config.HYBRID_STOP_ENABLED:
            if profit_pct >= 15.0:
                multiplier = 1.0
            elif profit_pct >= 10.0:
                multiplier = 1.5
            elif profit_pct >= 5.0:
                multiplier = 2.0
            else:
                multiplier = 2.5
            current_trailing_dist = trailing_dist * (multiplier / 2.5)
        else:
            if "ŞELALE SÖRFÜ" in strategy_name:
                current_trailing_dist = trailing_dist
            elif "UÇURUM ÇÖKÜŞÜ" in strategy_name:
                if profit_pct >= 15.0:
                    current_trailing_dist = trailing_dist * 0.4
                else:
                    current_trailing_dist = trailing_dist
            else:
                if profit_pct >= 15.0:
                    current_trailing_dist = max(current_price * 0.005, atr_floor_short)
                elif profit_pct >= 10.0:
                    current_trailing_dist = max(current_price * 0.015, atr_floor_short)
                else:
                    current_trailing_dist = trailing_dist

        current_trailing_dist = max(current_trailing_dist, atr_floor_short)

        # Lowest low güncelle
        if current_price < lowest_low:
            lowest_low = current_price
            t["lowest_low"] = lowest_low

        new_sl = lowest_low + current_trailing_dist

        # Yapısal Zemin (EMA-20 vb.) Koruması
        if config.STRUCTURAL_STOP_ENABLED:
            struct_floor = _get_structural_floor(ticker, signal)
            if struct_floor is not None:
                struct_sl = struct_floor * 1.001  # Yapısal zemin üstünde %0.1 marj bırak
                new_sl = min(new_sl, struct_sl)

        # Anti-Hunt Offset (Stop Avı Koruması)
        ticker_noise = (sum(ord(c) for c in ticker) % 100) / 100000.0
        asymmetric_offset = config.ANTI_HUNT_OFFSET_PCT + ticker_noise
        new_sl = new_sl * (1.0 + asymmetric_offset)

        # RED-09: Short trailing stop zemin koruması
        entry_price = float(t["entry_price"])
        if sl <= entry_price:
            new_sl = min(new_sl, entry_price)

        # Ters Mandal: SHORT stop yalnızca AŞAĞI gider
        if new_sl < sl:
            old_sl = sl
            t["sl"] = new_sl
            sl_change_pct = (abs(old_sl - new_sl) / max(abs(old_sl), 1e-8)) * 100
            crossed_breakeven = old_sl > float(t["entry_price"]) >= new_sl
            last_trailing_notify = t.get("last_trailing_notify_time", 0)
            now_ts = datetime.now(timezone.utc).timestamp()
            notify_cooldown_ok = (now_ts - last_trailing_notify) > 1800
            if crossed_breakeven or (sl_change_pct >= 1.0 and notify_cooldown_ok):
                t["last_trailing_notify_time"] = now_ts
                label = " 🛡️ BREAKEVEN GEÇİLDİ!" if crossed_breakeven else ""
                notifications.append(
                    f"🔄 <b>İzleyen Stop Güncellendi [SHORT]</b>{label}\n"
                    f"Varlık: <code>{ticker}</code>\n"
                    f"Kâr: +%{profit_pct:.2f}\n"
                    f"Eski SL: {old_sl:.4f} → Yeni SL: <b>{new_sl:.4f}</b>\n"
                    f"Değişim: %{sl_change_pct:.2f}"
                )

    return t, notifications


# ---------------------------------------------------------------------------
# Helper: Fonlama Oranı Kalkanı (Funding Rate Shield)
# ---------------------------------------------------------------------------
def _check_funding_shield(t, current_price, profit_pct, signal):
    """
    Kripto funding rate kontrolü.
    LONG: funding >= 0.05 → CLOSED_TP (fiş çekilme riski)
    SHORT: funding <= -0.05 → CLOSED_SL (short squeeze riski)
    """
    notifications = []
    should_close = False
    ticker = t["ticker"]

    if "/" not in ticker or profit_pct <= 0:
        return t, notifications, should_close

    funding_rate = get_funding_rate(ticker)

    if signal == "AL" and funding_rate >= 0.05:
        notifications.append(
            f"🛡️ <b>FONLAMA ORANI KALKANI (Funding Shield)</b>\n"
            f"Varlık: <code>{ticker}</code>\n"
            f"Fonlama Oranı: +%{funding_rate:.4f}\n"
            f"Durum: Piyasa kitle tarafından aşırı Long yönlü şişirildi "
            f"(Fiş Çekilme Riski!).\n"
            f"📋 <b>AKSİYON: Derhal borsayı aç ve bu pozisyonu kapat!</b>\n"
            f"Net Kâr: %{profit_pct:.2f}"
        )
        t["status"] = "CLOSED_TP"
        should_close = True

    elif signal == "SAT" and funding_rate <= -0.05:
        notifications.append(
            f"🛡️ <b>FONLAMA ORANI KALKANI (Funding Shield) [SHORT]</b>\n"
            f"Varlık: <code>{ticker}</code>\n"
            f"Fonlama Oranı: %{funding_rate:.4f}\n"
            f"Durum: Piyasa aşırı Short yönlü (Short Squeeze Riski!).\n"
            f"📋 <b>AKSİYON: Derhal borsayı aç ve bu pozisyonu kapat!</b>\n"
            f"Net Kâr: %{profit_pct:.2f}"
        )
        t["status"] = "CLOSED_SL"
        should_close = True

    return t, notifications, should_close


# ---------------------------------------------------------------------------
# Helper: Tehlike Bölgesi (Danger Zone)
# ---------------------------------------------------------------------------
def _check_danger_zone(t, current_price, signal):
    """
    Fiyat stop'a %2'den yakınsa SARI ALARM gönder.
    Fiyat %5'e uzaklaşırsa TEHLİKE GEÇTİ gönder (geniş hysteresis → ping-pong önleme).
    30 dakikalık cooldown ile spam önlenir.
    """
    notifications = []
    sl = float(t["sl"])
    ticker = t["ticker"]

    if sl <= 0:
        return t, notifications

    if signal == "AL":
        distance_pct = ((current_price - sl) / sl) * 100
    else:  # SAT
        distance_pct = ((sl - current_price) / current_price) * 100

    already_warned = t.get("danger_warned", False)
    last_danger_time = t.get("last_danger_time", 0)
    now_ts = datetime.now(timezone.utc).timestamp()

    # SARI ALARM: %2 yakınlık + en az 30 dk cooldown
    if distance_pct <= 2.0 and not already_warned:
        if now_ts - last_danger_time > 1800:  # 30 dk cooldown
            t["danger_warned"] = True
            t["last_danger_time"] = now_ts
            notifications.append(
                f"⚠️ <b>SARI ALARM: Fiyat stop'a yaklaştı!</b>\n"
                f"Varlık: <code>{ticker}</code>\n"
                f"Fiyat: {current_price:.4f}\n"
                f"Stop-Loss: {sl:.4f}\n"
                f"Mesafe: %{distance_pct:.2f}"
            )

    # TEHLİKE GEÇTİ: %5'e uzaklaşırsa (geniş hysteresis)
    elif distance_pct > 5.0 and already_warned:
        t["danger_warned"] = False
        notifications.append(
            f"✅ <b>TEHLİKE GEÇTİ</b>\n"
            f"Varlık: <code>{ticker}</code>\n"
            f"Fiyat stop'tan uzaklaştı (%{distance_pct:.2f}). Tehlike ortadan kalktı."
        )

    return t, notifications


# ---------------------------------------------------------------------------
# Helper: Swing Failure Pattern (SFP) MFE & Zaman Filtresi
# ---------------------------------------------------------------------------
def _check_sfp_mfe_time_filter(t, current_price, profit_pct):
    """
    SFP oluştuktan sonra fiyat hızla tersine gitmelidir.
    Eğer limit süre (SFP_MFE_TIME_LIMIT_HOURS) sonunda beklenen kâr (SFP_MFE_MIN_PROFIT_PCT)
    sağlanamadıysa işlem erken kapatılır.
    """
    from datetime import datetime, timezone
    import config

    notifications = []
    strategy_name = t.get("strategy", "")
    
    # Sadece SFP stratejisi için çalışır
    if "SFP" not in strategy_name or not config.SFP_MFE_TIME_FILTER_REQUIRED:
        return t, notifications, False

    entry_time_str = t.get("entry_time")
    if not entry_time_str:
        return t, notifications, False

    try:
        # entry_time_str format: '%Y-%m-%d %H:%M:%S+00:00'
        entry_dt = datetime.strptime(entry_time_str.split('+')[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        elapsed_hours = (now_dt - entry_dt).total_seconds() / 3600.0

        if elapsed_hours >= config.SFP_MFE_TIME_LIMIT_HOURS:
            # Eğer kâr oranı beklenen minimum orandan düşükse pozisyonu kapat
            if profit_pct < config.SFP_MFE_MIN_PROFIT_PCT:
                t["status"] = "CLOSED_MFE_TIMEOUT"
                ticker = t["ticker"]
                notifications.append(
                    f"⏰ <b>SFP ZAMAN/MFE AŞIMI (Erken Kapanış)</b>\n"
                    f"Varlık: <code>{ticker}</code>\n"
                    f"Açılış Zamanı: {entry_time_str}\n"
                    f"Geçen Süre: {elapsed_hours:.1f} saat (Sınır: {config.SFP_MFE_TIME_LIMIT_HOURS} saat)\n"
                    f"Kâr Oranı: %{profit_pct:.2f} (Beklenen: %{config.SFP_MFE_MIN_PROFIT_PCT:.2f})\n"
                    f"Açıklama: SFP sonrası fiyat beklenen MFE momentumunu gösteremedi, işlem koruma amaçlı sonlandırıldı."
                )
                return t, notifications, True
    except Exception as e:
        logging.warning(f"[_check_sfp_mfe_time_filter] Hata: {e}")

    return t, notifications, False


# 99 yapılmıştır
# Kırılım stratejilerinde sahte kırılımları (fakeout) engellemek amacıyla Zaman Stopu (Time Stop) kontrolü yapılır.
def _check_time_stop(t: dict, current_price: float, profit_pct: float) -> tuple[dict, list, bool]:
    """
    Kırılım gerçekleştikten sonra fiyat belirli süre (TIME_STOP_HOURS) içinde
    beklenen momentumu (TIME_STOP_MIN_PROFIT_PCT) yakalayamazsa işlem kapatılır.
    """
    from datetime import datetime, timezone
    import config

    notifications = []
    strategy_name = t.get("strategy", "")

    if not config.TIME_STOP_ENABLED or strategy_name not in config.TIME_STOP_STRATEGIES:
        return t, notifications, False

    entry_time_str = t.get("entry_time")
    if not entry_time_str:
        return t, notifications, False

    try:
        # entry_time_str format: '%Y-%m-%d %H:%M:%S+00:00'
        entry_dt = datetime.strptime(entry_time_str.split('+')[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        elapsed_hours = (now_dt - entry_dt).total_seconds() / 3600.0

        if elapsed_hours >= config.TIME_STOP_HOURS:
            if profit_pct < config.TIME_STOP_MIN_PROFIT_PCT:
                t["status"] = "CLOSED_TIME_STOP"
                ticker = t["ticker"]
                notifications.append(
                    f"⏰ <b>ZAMAN STOPU TETİKLENDİ (Sahte Kırılım Koruması)</b>\n"
                    f"Varlık: <code>{ticker}</code>\n"
                    f"Strateji: {strategy_name}\n"
                    f"Geçen Süre: {elapsed_hours:.1f} saat (Sınır: {config.TIME_STOP_HOURS} saat)\n"
                    f"Kâr Oranı: %{profit_pct:.2f} (Beklenen: %{config.TIME_STOP_MIN_PROFIT_PCT:.2f})\n"
                    f"Açıklama: Kırılım sonrası fiyat beklenen momentumu gösteremedi. Sermaye koruması amacıyla break-even civarında kapatıldı."
                )
                return t, notifications, True
    except Exception as e:
        logging.warning(f"[_check_time_stop] Hata: {e}")

    return t, notifications, False


# ---------------------------------------------------------------------------
# Helper: Kara Kuğu (Black Swan)
# ---------------------------------------------------------------------------
def _check_black_swan(t, current_price, signal):
    """
    Fiyat stop'un %3'ten fazla ötesine geçtiyse → Kara Kuğu çıkışı.
    LONG: fiyat stop'un %3 altında
    SHORT: fiyat stop'un %3 üstünde
    """
    notifications = []
    is_black_swan = False
    sl = float(t["sl"])
    ticker = t["ticker"]

    if math.isclose(sl, 0.0, abs_tol=1e-8):
        return t, notifications, is_black_swan

    if signal == "AL":
        if current_price < sl * 0.97:
            is_black_swan = True
            close_msg = _format_close_message(t, current_price, signal, "BLACK_SWAN")
            notifications.append(close_msg)
            t["status"] = "CLOSED_SL"

    elif signal == "SAT":
        if current_price > sl * 1.03:
            is_black_swan = True
            close_msg = _format_close_message(t, current_price, signal, "BLACK_SWAN")
            notifications.append(close_msg)
            t["status"] = "CLOSED_SL"

    return t, notifications, is_black_swan


# ---------------------------------------------------------------------------
# Helper: Kapanış Mesajı Formatı
# ---------------------------------------------------------------------------
def _format_close_message(t, current_price, signal, close_type):
    """
    Kapanış mesajı üretir.
    close_type: 'TP', 'SL', 'BLACK_SWAN', 'FUNDING'
    """
    ticker = t["ticker"]
    entry_price = float(t["entry_price"])
    strategy_name = t.get("strategy", "Bilinmiyor")
    entry_time_str = t.get("entry_time", "Bilinmiyor")

    # İşlem süresi hesapla
    duration_str = "Bilinmiyor"
    if entry_time_str != "Bilinmiyor":
        try:
            # UTC-aware parse: yeni format (%S+00:00) ve eski format (%H:%M) uyumu
            if '+' in entry_time_str:
                entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
            else:
                entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
            duration = datetime.now(timezone.utc) - entry_dt
            hours, remainder = divmod(int(duration.total_seconds()), 3600)
            minutes = remainder // 60
            if hours >= 24:
                days = hours // 24
                hours = hours % 24
                duration_str = f"{days}g {hours}s {minutes}dk"
            else:
                duration_str = f"{hours}s {minutes}dk"
        except Exception:
            duration_str = "Hesaplanamadı"

    # Kâr hesabı
    if signal == "AL":
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        max_profit_price = float(t.get("highest_high", entry_price))
        max_profit_pct = ((max_profit_price - entry_price) / entry_price) * 100
    else:
        profit_pct = ((entry_price - current_price) / entry_price) * 100
        max_profit_price = float(t.get("lowest_low", entry_price))
        max_profit_pct = ((entry_price - max_profit_price) / entry_price) * 100

    # Kapanış tipi ikon ve başlık
    type_map = {
        "TP": ("🎉", "KAR ALINDI (TP)"),
        "SL": ("🛑", "ZARAR KESİLDİ (SL)"),
        "BLACK_SWAN": ("🦢", "KARA KUĞU ÇIKIŞI"),
        "FUNDING": ("🛡️", "FONLAMA KALKANI ÇIKIŞI"),
    }

    # Trailing ile kârda kapatıldıysa ikonu değiştir
    if close_type == "SL" and profit_pct > 0:
        icon = "🟢"
        title = "KÂR ALINDI (Trailing)"
    else:
        icon, title = type_map.get(close_type, ("❓", "BİLİNMEYEN ÇIKIŞ"))

    short_tag = " [SHORT]" if signal == "SAT" else ""

    # Kara Kuğu için aciliyet formatı
    if close_type == "BLACK_SWAN":
        gap_pct = abs((current_price - float(t["sl"])) / max(abs(float(t["sl"])), 1e-8)) * 100
        return (
            f"🚨🚨🚨 <b>KARA KUĞU — ACİL TASFİYE GEREKLİ</b>{short_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Strateji: <i>{strategy_name}</i>\n"
            f"Varlık: <code>{ticker}</code>\n"
            f"Giriş: ${entry_price:.4f}\n"
            f"Anlık Fiyat: ${current_price:.4f}\n"
            f"Stop Seviyesi: ${float(t['sl']):.4f}\n"
            f"⚠️ Stop'un <b>%{gap_pct:.1f}</b> ÖTESİNDE!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>ACİL AKSİYON:</b>\n"
            f"1. Derhal borsayı aç ve bu pozisyonu kapat\n"
            f"2. Diğer açık pozisyonları kontrol et\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Net Zarar: %{profit_pct:.2f} | Süre: {duration_str}"
        )

    return (
        f"{icon} <b>{title}{short_tag}</b>\n"
        f"Strateji: <i>{strategy_name}</i>\n"
        f"Varlık: <code>{ticker}</code>\n"
        f"Giriş: ${entry_price:.4f}\n"
        f"Çıkış: ${current_price:.4f}\n"
        f"Net Kâr: %{profit_pct:.2f}\n"
        f"Maks. Kâr: %{max_profit_pct:.2f}\n"
        f"Süre: {duration_str}\n"
        f"Durum: İşlem kapandı."
    )


def _stamp_exit_data(trade, current_price):
    """FM-05: Kapanan işleme exit_price ve exit_time damgası vurur."""
    trade["exit_price"] = current_price
    trade["exit_time"] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')
    return trade


# ---------------------------------------------------------------------------
# Arşiv: Kapanan işlemleri trade_history.json'a taşı
# ---------------------------------------------------------------------------
def _archive_closed_trades(closed_trades):
    month_tag = datetime.now(timezone.utc).strftime('%Y_%m')
    history_file = f"trade_history_{month_tag}.json"
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []
    history.extend(closed_trades)
    # Y-06: Atomic archive write — crash-safe
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(history_file) or '.', suffix='.tmp')
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as tmp_f:
            json.dump(history, tmp_f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, history_file)
    except Exception as e:
        logging.warning(f'[_archive_closed_trades] {e}')
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)

    # FM-05: CSV Günlüğüne de yaz
    for t in closed_trades:
        _write_trade_journal_csv(t)


# ---------------------------------------------------------------------------
# FM-05: Trade Günlüğü CSV (Post-Trade Analytics)
# ---------------------------------------------------------------------------
TRADE_JOURNAL_CSV = "trade_journal.csv"
# 99 yapılmıştır
# Sinyal inanç dereceleri (conviction) ve bireysel ağırlıklı puanlama parametreleri analize
# yardımcı olmak üzere genişletilerek _CSV_HEADERS listesine eklenmiştir.
_CSV_HEADERS = [
    "tarih", "sembol", "market", "strateji", "sinyal", "giris_fiyat",
    "cikis_fiyat", "sl", "tp", "net_pnl_pct", "rr_ratio", "rr_achieved",
    "sure", "sonuc", "entry_time", "exit_time", "is_watch", "indicators",
    "conviction_score", "conviction_grade", "position_size_pct",
    "c_adx", "c_ema_alignment", "c_rsi", "c_rsi_direction", "c_volume_ratio",
    "c_dollar_volume", "c_rr_ratio", "c_engulfing", "c_regime", "c_macro", "c_penalty"
]


# 99 yapılmıştır
# Eski CSV formatındaki kayıtların yeni sütunlar eklenirken bozulmasını önlemek için
# hizalama ve göç (migration) kontrolü sağlayan yardımcı fonksiyondur.
def _align_and_migrate_journal_csv():
    """
    Eğer trade_journal.csv zaten varsa ve eski sütun sayısına sahipse,
    verileri bozmamak için eski satırları yeni sütunlarla hizalar ve dosyayı günceller.
    """
    if not os.path.exists(TRADE_JOURNAL_CSV):
        return

    try:
        rows = []
        needs_migration = False
        with open(TRADE_JOURNAL_CSV, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if headers:
                if len(headers) < len(_CSV_HEADERS):
                    needs_migration = True
                    for row in reader:
                        migrated_row = row + [""] * (len(_CSV_HEADERS) - len(row))
                        rows.append(migrated_row)
        
        if needs_migration:
            with open(TRADE_JOURNAL_CSV, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(_CSV_HEADERS)
                writer.writerows(rows)
            logging.info(f"[FM-05 Journal] {TRADE_JOURNAL_CSV} yeni sütun yapısına başarıyla migrate edildi.")
    except Exception as e:
        logging.error(f"[FM-05 Journal] Journal migrasyonu sırasında hata: {e}")


def _write_trade_journal_csv(trade):
    """FM-05: Kapanan işlemi trade_journal.csv'ye satır olarak yaz.
    Excel/Google Sheets'te doğrudan açılabilir format."""
    try:
        # Migrasyon kontrolünü çalıştır
        _align_and_migrate_journal_csv()

        file_exists = os.path.exists(TRADE_JOURNAL_CSV)

        entry_price = float(trade.get("entry_price", 0))
        exit_price = float(trade.get("exit_price", 0))
        sl = float(trade.get("sl", 0))
        tp = float(trade.get("tp", 0))
        signal = trade.get("signal", "AL")
        status = trade.get("status", "")

        # Net PnL hesabı
        if entry_price > 0 and exit_price > 0:
            if signal == "AL":
                net_pnl = ((exit_price - entry_price) / entry_price) * 100
            else:
                net_pnl = ((entry_price - exit_price) / entry_price) * 100
        else:
            net_pnl = 0.0

        # Planlanan R:R
        risk = abs(entry_price - sl) if abs(entry_price - sl) > 0 else 1e-8
        reward = abs(tp - entry_price)
        rr_planned = round(reward / risk, 2)

        # Gerçekleşen R:R
        actual_reward = abs(exit_price - entry_price)
        rr_achieved = round(actual_reward / risk, 2) if risk > 0 else 0.0
        if net_pnl < 0:
            rr_achieved = -rr_achieved

        # Süre hesabı
        entry_time_str = trade.get("entry_time", "")
        exit_time_str = trade.get("exit_time", datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00'))
        duration_str = "?"
        try:
            if '+' in entry_time_str:
                entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
            else:
                entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
            if '+' in exit_time_str:
                exit_dt = datetime.strptime(exit_time_str, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
            else:
                exit_dt = datetime.now(timezone.utc)
            delta = exit_dt - entry_dt
            hours = int(delta.total_seconds()) // 3600
            mins = (int(delta.total_seconds()) % 3600) // 60
            duration_str = f"{hours}s {mins}dk"
        except Exception:
            pass

        # Sonuç
        if "TP" in status:
            sonuc = "KAZANC"
        elif "SL" in status:
            sonuc = "KAYIP"
        elif "BLACK_SWAN" in status:
            sonuc = "KARA_KUGU"
        else:
            sonuc = status

        # İndikatörleri düz string'e çevirme (Pipe-separated format: RSI:35.2|ADX:20.1)
        indicators = trade.get("indicators", {})
        raw_inds = trade.get("raw_indicators", {})
        merged_inds = {}
        if isinstance(indicators, dict): merged_inds.update(indicators)
        if isinstance(raw_inds, dict): merged_inds.update(raw_inds)
        
        if merged_inds:
            ind_str = " | ".join(f"{k}:{v}" for k, v in merged_inds.items())
        elif isinstance(indicators, str):
            ind_str = indicators
        else:
            ind_str = "N/A"

        # Puanlama detayları
        conv_score = trade.get("conviction_score")
        conv_grade = trade.get("conviction_grade", "")
        pos_size_pct = trade.get("position_size_pct")
        c_details = trade.get("conviction_details", {})
        if not isinstance(c_details, dict):
            c_details = {}

        row = [
            datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            trade.get("ticker", ""),
            trade.get("market", ""),
            trade.get("strategy", ""),
            signal,
            f"{entry_price:.6f}",
            f"{exit_price:.6f}",
            f"{sl:.6f}",
            f"{tp:.6f}",
            f"{net_pnl:.2f}",
            f"{rr_planned:.2f}",
            f"{rr_achieved:.2f}",
            duration_str,
            sonuc,
            entry_time_str,
            exit_time_str,
            "TRUE" if trade.get("is_watch", False) else "FALSE",
            ind_str,
            f"{conv_score:.1f}" if conv_score is not None else "",
            str(conv_grade),
            f"{pos_size_pct:.1f}" if pos_size_pct is not None else "",
            f"{c_details.get('adx', 0):.1f}",
            f"{c_details.get('ema_alignment', 0):.1f}",
            f"{c_details.get('rsi', 0):.1f}",
            f"{c_details.get('rsi_direction', 0):.1f}",
            f"{c_details.get('volume_ratio', 0):.1f}",
            f"{c_details.get('dollar_volume', 0):.1f}",
            f"{c_details.get('rr_ratio', 0):.1f}",
            f"{c_details.get('engulfing', 0):.1f}",
            f"{c_details.get('regime', 0):.1f}",
            f"{c_details.get('macro', 0):.1f}",
            f"{c_details.get('penalty', 0):.1f}"
        ]

        with open(TRADE_JOURNAL_CSV, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(_CSV_HEADERS)
            writer.writerow(row)

        logging.info(f"[FM-05 Journal] {trade.get('ticker')} → {sonuc} ({net_pnl:+.2f}%) CSV'ye yazıldı.")
    except Exception as e:
        logging.warning(f"[FM-05 Journal] CSV yazma hatası: {e}")


# ---------------------------------------------------------------------------
# Yardımcı Fonksiyonlar - Mum Kapanış Stopu
# ---------------------------------------------------------------------------
def _get_last_completed_candle_close(ticker: str, timeframe: str) -> Optional[float]:
    """
    Belirtilen ticker ve timeframe için son tamamlanan mumun kapanış fiyatını döner.
    Intraday fitil sarkmalarını (wicks) elemek için SMC (Smart Money Concepts) tarzı kapanış stopu sağlar.
    """
    from data_sources import get_bist_data, get_crypto_data, get_crypto_1h_data
    import pandas as pd
    from datetime import datetime, timezone

    timeframe_lower = timeframe.lower()
    df = None

    try:
        if ".IS" in ticker:
            # BIST ticker
            df_1d, df_4h, df_1h = get_bist_data(ticker)
            if timeframe_lower == "1d":
                df = df_1d
            elif timeframe_lower == "1h":
                df = df_1h
            else:
                df = df_4h
        else:
            # Kripto veya Emtia ticker
            if timeframe_lower == "1h":
                df = get_crypto_1h_data(ticker)
            elif timeframe_lower == "1d":
                df_1d, _ = get_crypto_data(ticker)
                df = df_1d
            else:
                _, df_4h = get_crypto_data(ticker)
                df = df_4h
    except Exception as e:
        logging.warning(f"[_get_last_completed_candle_close] Veri çekme hatası ({ticker}, {timeframe}): {e}")
        return None

    if df is None or df.empty:
        logging.warning(f"[_get_last_completed_candle_close] Veri boş döndü ({ticker}, {timeframe})")
        return None

    # Zaman diliminin süresini hesapla
    if timeframe_lower == "1d":
        duration = pd.Timedelta(days=1)
    elif timeframe_lower == "1h":
        duration = pd.Timedelta(hours=1)
    else:
        duration = pd.Timedelta(hours=4) # Varsayılan 4h

    try:
        last_time = df.index[-1]
        now = datetime.now(timezone.utc)

        # Timezone mismatch engelleme
        if last_time.tzinfo is not None:
            now_compare = now.astimezone(last_time.tzinfo)
        else:
            now_compare = datetime.now() # Naive karşılaştırma

        age = now_compare - last_time

        # Eğer son mumun yaşı periyot süresinden küçükse, mum henüz tamamlanmamıştır (active/live candle).
        # Bu durumda bir önceki tamamlanmış mumu (iloc[-2]) kullanırız.
        if age < duration:
            if len(df) >= 2:
                completed_val = float(df['close'].iloc[-2])
                logging.info(f"[_get_last_completed_candle_close] {ticker} ({timeframe}): Son mum henüz tamamlanmadı ({age} < {duration}). iloc[-2] kapanışı kullanılıyor: {completed_val}")
                return completed_val
            else:
                completed_val = float(df['close'].iloc[-1])
                logging.warning(f"[_get_last_completed_candle_close] {ticker} ({timeframe}): Veri boyutu yetersiz. iloc[-1] kapanışı kullanılıyor: {completed_val}")
                return completed_val
        else:
            # Son mum tamamlanmıştır
            completed_val = float(df['close'].iloc[-1])
            logging.info(f"[_get_last_completed_candle_close] {ticker} ({timeframe}): Son mum tamamlandı ({age} >= {duration}). iloc[-1] kapanışı kullanılıyor: {completed_val}")
            return completed_val
    except Exception as e:
        logging.warning(f"[_get_last_completed_candle_close] İşleme hatası ({ticker}, {timeframe}): {e}")
        return None


# ---------------------------------------------------------------------------
# Ana Kontrol Döngüsü
# ---------------------------------------------------------------------------
def check_active_trades(current_prices_dict):
    """
    current_prices_dict: {"BTC/USDT": 65000.5, "ETH/USDT": 3000.2} şeklinde güncel fiyat sözlüğü.
    Aktif işlemleri kontrol eder. Yardımcı fonksiyonlarla TP/SL/Kara Kuğu/Funding vb. kontrol eder.
    Kapanan işlemleri trade_history.json'a arşivler.
    """
    trades = load_trades()
    notifications = []
    active_trades = []
    closed_trades = []

    for t in trades:
        if t["status"] != "ACTIVE":
            closed_trades.append(t)
            continue

        ticker = t["ticker"]
        if ticker not in current_prices_dict:
            active_trades.append(t)
            continue

        current_price = current_prices_dict[ticker]
        signal = t["signal"]
        tp = float(t["tp"])
        sl = float(t["sl"])
        entry_price = float(t["entry_price"])
        strategy_name = t.get("strategy", "")

        # Eğer trailing_dist yoksa hesapla (eski datalar için uyumluluk)
        if "trailing_dist" not in t:
            t["trailing_dist"] = entry_price - sl if signal == "AL" else sl - entry_price

        # Gövde Kapanış Stopu (SMC-style body close stop) Kontrolü
        body_close_stop_required = t.get("body_close_stop_required", False)
        timeframe = t.get("timeframe", "4h")

        check_price = current_price
        if body_close_stop_required:
            completed_close = _get_last_completed_candle_close(ticker, timeframe)
            if completed_close is not None:
                check_price = completed_close

        # Kâr yüzdeleri (Fitil ve Gövde için ayrı hesaplama)
        if signal == "AL":
            profit_pct_wick = ((current_price - entry_price) / entry_price) * 100
            profit_pct_body = ((check_price - entry_price) / entry_price) * 100
        else:
            profit_pct_wick = ((entry_price - current_price) / entry_price) * 100
            profit_pct_body = ((entry_price - check_price) / entry_price) * 100

        # WATCH kontrolü
        is_watch = t.get("is_watch", False)

        # === 1. KARA KUĞU KONTROLÜ (en önce, fiyat patlayınca hemen çık - wicks) ===
        t, bs_notifs, is_black_swan = _check_black_swan(t, current_price, signal)
        if not is_watch: notifications.extend(bs_notifs)
        if is_black_swan:
            closed_trades.append(t)
            continue

        if not is_watch:
            # === 2. KADEMELİ KÂR AL (Scale-Out - wicks) ===
            t, so_notifs = _check_scale_out(t, profit_pct_wick, signal, strategy_name, current_price)
            notifications.extend(so_notifs)

            # === 3. DİNAMİK İZLEYEN STOP (Trailing Stop - body close if required) ===
            t, ts_notifs = _update_trailing_stop(t, check_price, profit_pct_body, signal, strategy_name)
            notifications.extend(ts_notifs)

            # === 4. FONLAMA ORANI KALKANI (Funding Shield - wicks) ===
            t, fs_notifs, funding_close = _check_funding_shield(t, current_price, profit_pct_wick, signal)
            notifications.extend(fs_notifs)
            if funding_close:
                _stamp_exit_data(t, current_price)
                closed_trades.append(t)
                continue

            # === 5. TEHLİKE BÖLGESİ (Danger Zone - body close if required) ===
            t, dz_notifs = _check_danger_zone(t, check_price, signal)
            notifications.extend(dz_notifs)

            # === 5.5. SFP MFE / ZAMAN FİLTRESİ (body close if required) ===
            t, sfp_notifs, sfp_close = _check_sfp_mfe_time_filter(t, check_price, profit_pct_body)
            if sfp_close:
                notifications.extend(sfp_notifs)
                _stamp_exit_data(t, check_price)
                closed_trades.append(t)
                continue

            # === 5.6. ZAMAN STOPU (Time Stop - body close if required) ===
            t, time_stop_notifs, time_stop_close = _check_time_stop(t, check_price, profit_pct_body)
            if time_stop_close:
                notifications.extend(time_stop_notifs)
                _stamp_exit_data(t, check_price)
                closed_trades.append(t)
                continue

        # === 6. ÇIKIŞ KONTROLLERI (TP & SL) ===
        sl = float(t["sl"])  # Güncellenmiş SL'yi al

        if signal == "AL":
            if current_price >= tp and tp > 0:
                close_msg = _format_close_message(t, current_price, signal, "TP")
                if not is_watch: notifications.append(close_msg)
                _stamp_exit_data(t, current_price)
                t["status"] = "CLOSED_TP"
            elif check_price <= sl:
                # Gövde stopu tetiklendiğinde candle close (check_price) exit price olarak damgalanır.
                close_msg = _format_close_message(t, check_price, signal, "SL")
                if not is_watch: notifications.append(close_msg)
                _stamp_exit_data(t, check_price)
                t["status"] = "CLOSED_SL"

        elif signal == "SAT":
            if current_price <= tp and tp > 0:
                close_msg = _format_close_message(t, current_price, signal, "TP")
                if not is_watch: notifications.append(close_msg)
                _stamp_exit_data(t, current_price)
                t["status"] = "CLOSED_TP"
            elif check_price >= sl:
                # Gövde stopu tetiklendiğinde candle close (check_price) exit price olarak damgalanır.
                close_msg = _format_close_message(t, check_price, signal, "SL")
                if not is_watch: notifications.append(close_msg)
                _stamp_exit_data(t, check_price)
                t["status"] = "CLOSED_SL"

        # Duruma göre listeye ekle
        if t["status"] == "ACTIVE":
            active_trades.append(t)
        else:
            closed_trades.append(t)

    # Fiyatı çekilemeyen aktif pozisyonları bildir
    missing_tickers = [t["ticker"] for t in trades
                       if t["status"] == "ACTIVE" and t["ticker"] not in current_prices_dict]
    if missing_tickers:
        notifications.append(
            f"⚠️ <b>FİYAT EKSİK — İZLENEMEYEN POZİSYONLAR</b>\n"
            f"Şu varlıkların fiyatı çekilemedi:\n"
            f"<code>{', '.join(missing_tickers)}</code>\n"
            f"Bu pozisyonlar ŞU AN kontrol edilemiyor!"
        )

    # Kapanan işlemleri arşivle + Circuit Breaker bildir
    if closed_trades:
        _archive_closed_trades(closed_trades)
        # FM-03: Lokal Devre Kesici (Circuit Breaker) — Hisse Bazlı İzolasyon
        # Sistem global bir devre kesici yerine hisse bazlı (lokal) çalışır.
        # Böylece bir hissede peş peşe stop olunursa, sadece o hisse cezalandırılır (penalty box),
        # sistemin geri kalanı veya diğer hisseler/stratejiler çalışmaya devam eder.
        # Bu yapı "cascading failure" (zincirleme çöküş) riskini önler.
        cb_notifications = []
        
        def _cb_listener(msg):
            if msg:
                cb_notifications.append(msg)
                
        cb_observer.subscribe(_cb_listener)
        try:
            for ct in closed_trades:
                status = ct.get("status", "")
                ticker_ct = ct.get("ticker", "?")
                strategy_ct = ct.get("strategy", "")
                entry_price_ct = float(ct.get("entry_price", 0))
                exit_price_ct = float(ct.get("exit_price", ct.get("entry_price", 0)))
                signal_ct = ct.get("signal", "AL")
                
                # PnL hesabı
                if entry_price_ct > 0 and exit_price_ct > 0:
                    if signal_ct == "AL":
                        pnl_pct = ((exit_price_ct - entry_price_ct) / entry_price_ct) * 100
                    else:
                        pnl_pct = ((entry_price_ct - exit_price_ct) / entry_price_ct) * 100
                else:
                    pnl_pct = 0.0
                
                # Tutma süresi
                hold_hours = 0.0
                entry_time_ct = ct.get("entry_time", "")
                if entry_time_ct:
                    try:
                        if '+' in entry_time_ct:
                            entry_dt_ct = datetime.strptime(entry_time_ct, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
                        else:
                            entry_dt_ct = datetime.strptime(entry_time_ct, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                        hold_hours = (datetime.now(timezone.utc) - entry_dt_ct).total_seconds() / 3600
                    except Exception:
                        pass
                
                # R:R hesabı
                sl_ct = float(ct.get("sl", 0))
                risk_ct = abs(entry_price_ct - sl_ct) if abs(entry_price_ct - sl_ct) > 0 else 1e-8
                rr_achieved = abs(exit_price_ct - entry_price_ct) / risk_ct
                if pnl_pct < 0:
                    rr_achieved = -rr_achieved
                
                if "SL" in status or "BLACK_SWAN" in status:
                    cb_observer.on_trade_closed({
                        "ticker": ticker_ct,
                        "strategy": strategy_ct,
                        "pnl_percent": -abs(pnl_pct) if pnl_pct != 0 else -0.01
                    })
                    
                    # V3.2 Kaos #4: Ceza Kutusu — SL kaydı
                    penalty_msg = record_asset_sl(ticker_ct)
                    if penalty_msg:
                        cb_notifications.append(penalty_msg)
                    
                    # V3.2 Kaos #5: Strateji Karnesi — SL kaydı
                    if strategy_ct:
                        record_trade_result(strategy_ct, {
                            "ticker": ticker_ct,
                            "outcome": "SL",
                            "pnl_pct": pnl_pct,
                            "hold_hours": hold_hours,
                            "entry_time": entry_time_ct,
                            "exit_time": ct.get("exit_time", ""),
                            "rr_achieved": round(rr_achieved, 2),
                        })
                    
                elif "TP" in status:
                    cb_observer.on_trade_closed({
                        "ticker": ticker_ct,
                        "strategy": strategy_ct,
                        "pnl_percent": abs(pnl_pct) if pnl_pct != 0 else 0.01
                    })
                    
                    # V3.2 Kaos #4: Ceza Kutusu — TP kaydı (SL sayacı düşer)
                    record_asset_tp(ticker_ct)
                    
                    # V3.2 Kaos #5: Strateji Karnesi — TP kaydı
                    if strategy_ct:
                        record_trade_result(strategy_ct, {
                            "ticker": ticker_ct,
                            "outcome": "TP",
                            "pnl_pct": pnl_pct,
                            "hold_hours": hold_hours,
                            "entry_time": entry_time_ct,
                            "exit_time": ct.get("exit_time", ""),
                            "rr_achieved": round(rr_achieved, 2),
                        })
                else:
                    # Manuel kapanış
                    if strategy_ct:
                        record_trade_result(strategy_ct, {
                            "ticker": ticker_ct,
                            "outcome": "MANUAL",
                            "pnl_pct": pnl_pct,
                            "hold_hours": hold_hours,
                            "entry_time": entry_time_ct,
                            "exit_time": ct.get("exit_time", ""),
                            "rr_achieved": round(rr_achieved, 2),
                        })
        finally:
            cb_observer.unsubscribe(_cb_listener)
                
        notifications.extend(cb_notifications)

    # Sadece aktif işlemleri kaydet
    save_trades(active_trades)
    return notifications


def get_learning_context(limit=5):
    """
    Kapanan başarılı (CLOSED_TP) ve başarısız (CLOSED_SL) işlemleri döndürür.
    Aylık trade_history dosyalarından okur.
    limit: Getirilecek maksimum işlem sayısı.
    """
    import glob
    history = []
    # Hem eski HISTORY_FILE hem de aylık dosyaları oku
    history_files = sorted(glob.glob("trade_history*.json"))
    for hf in history_files:
        try:
            with open(hf, 'r', encoding='utf-8') as f:
                history.extend(json.load(f))
        except Exception as e:
            logging.warning(f"[get_learning_context] {hf} okuma hatası: {e}")

    successful = [t for t in history if t.get("status") == "CLOSED_TP"]
    failed = [t for t in history if t.get("status") == "CLOSED_SL"]

    return {
        "successful_trades": successful[-limit:],
        "failed_trades": failed[-limit:]
    }
