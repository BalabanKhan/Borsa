import logging
import math
import config
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from data_sources import get_funding_rate
from core.defensive_engine import DefensiveExceptionManager

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

def _check_funding_shield(t, current_price, profit_pct, signal):
    """
    Kripto funding rate kontrolü.
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

def _check_danger_zone(t, current_price, signal):
    """
    Fiyat stop'a %2'den yakınsa SARI ALARM gönder.
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

    if distance_pct <= 2.0 and not already_warned:
        if now_ts - last_danger_time > 1800:
            t["danger_warned"] = True
            t["last_danger_time"] = now_ts
            notifications.append(
                f"⚠️ <b>SARI ALARM: Fiyat stop'a yaklaştı!</b>\n"
                f"Varlık: <code>{ticker}</code>\n"
                f"Fiyat: {current_price:.4f}\n"
                f"Stop-Loss: {sl:.4f}\n"
                f"Mesafe: %{distance_pct:.2f}"
            )

    elif distance_pct > 5.0 and already_warned:
        t["danger_warned"] = False
        notifications.append(
            f"✅ <b>TEHLİKE GEÇTİ</b>\n"
            f"Varlık: <code>{ticker}</code>\n"
            f"Fiyat stop'tan uzaklaştı (%{distance_pct:.2f}). Tehlike ortadan kalktı."
        )

    return t, notifications

def _check_sfp_mfe_time_filter(t, current_price, profit_pct):
    """
    SFP oluştuktan sonra fiyat hızla tersine gitmelidir.
    """
    notifications = []
    strategy_name = t.get("strategy", "")
    
    if "SFP" not in strategy_name or not config.SFP_MFE_TIME_FILTER_REQUIRED:
        return t, notifications, False

    entry_time_str = t.get("entry_time")
    if not entry_time_str:
        return t, notifications, False

    try:
        entry_dt = datetime.strptime(entry_time_str.split('+')[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        elapsed_hours = (now_dt - entry_dt).total_seconds() / 3600.0

        if elapsed_hours >= config.SFP_MFE_TIME_LIMIT_HOURS:
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

def _check_time_stop(t: dict, current_price: float, profit_pct: float) -> tuple[dict, list, bool]:
    """
    Kırılım gerçekleştikten sonra fiyat belirli süre (TIME_STOP_HOURS) içinde
    beklenen momentumu (TIME_STOP_MIN_PROFIT_PCT) yakalayamazsa işlem kapatılır.
    """
    notifications = []
    strategy_name = t.get("strategy", "")

    if not config.TIME_STOP_ENABLED or strategy_name not in config.TIME_STOP_STRATEGIES:
        return t, notifications, False

    entry_time_str = t.get("entry_time")
    if not entry_time_str:
        return t, notifications, False

    try:
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

def _check_black_swan(t, current_price, signal):
    """
    Fiyat stop'un %3'ten fazla ötesine geçtiyse → Kara Kuğu çıkışı.
    """
    import trade_tracker
    notifications = []
    is_black_swan = False
    sl = float(t["sl"])

    if math.isclose(sl, 0.0, abs_tol=1e-8):
        return t, notifications, is_black_swan

    if signal == "AL":
        if current_price < sl * 0.97:
            is_black_swan = True
            close_msg = trade_tracker._format_close_message(t, current_price, signal, "BLACK_SWAN")
            notifications.append(close_msg)
            t["status"] = "CLOSED_SL"

    elif signal == "SAT":
        if current_price > sl * 1.03:
            is_black_swan = True
            close_msg = trade_tracker._format_close_message(t, current_price, signal, "BLACK_SWAN")
            notifications.append(close_msg)
            t["status"] = "CLOSED_SL"

    return t, notifications, is_black_swan

def _get_last_completed_candle_close(ticker: str, timeframe: str) -> Optional[float]:
    """
    Belirtilen ticker ve timeframe için son tamamlanan mumun kapanış fiyatını döner.
    """
    from data_sources import get_bist_data, get_crypto_data, get_crypto_1h_data
    import pandas as pd
    from datetime import datetime, timezone

    timeframe_lower = timeframe.lower()
    df = None

    try:
        if ".IS" in ticker:
            df_1d, df_4h, df_1h = get_bist_data(ticker)
            if timeframe_lower == "1d":
                df = df_1d
            elif timeframe_lower == "1h":
                df = df_1h
            else:
                df = df_4h
        else:
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

    if timeframe_lower == "1d":
        duration = pd.Timedelta(days=1)
    elif timeframe_lower == "1h":
        duration = pd.Timedelta(hours=1)
    else:
        duration = pd.Timedelta(hours=4)

    try:
        last_time = df.index[-1]
        now = datetime.now(timezone.utc)

        if last_time.tzinfo is not None:
            now_compare = now.astimezone(last_time.tzinfo)
        else:
            now_compare = datetime.now()

        age = now_compare - last_time

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
            completed_val = float(df['close'].iloc[-1])
            logging.info(f"[_get_last_completed_candle_close] {ticker} ({timeframe}): Son mum tamamlandı ({age} >= {duration}). iloc[-1] kapanışı kullanılıyor: {completed_val}")
            return completed_val
    except Exception as e:
        logging.warning(f"[_get_last_completed_candle_close] İşleme hatası ({ticker}, {timeframe}): {e}")
        return None
