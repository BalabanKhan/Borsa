import logging
import math
import config
import time
from datetime import datetime, timezone

_atr_cache = {}
_ATR_CACHE_TTL = 300  # 5 minutes

def _get_atr_cached(ticker: str) -> float:
    now = time.time()
    if ticker in _atr_cache:
        val, ts = _atr_cache[ticker]
        if now - ts < _ATR_CACHE_TTL:
            return val
            
    try:
        from data_sources import get_bist_data, get_crypto_1h_data, get_emtia_1h_data
        df_1h = None
        
        if ticker.endswith(".IS"):
            _, _, df_1h = get_bist_data(ticker)
        elif "=" in ticker or "GLDTR" in ticker or "GMSTR" in ticker:
            df_1h = get_emtia_1h_data(ticker)
        else:
            df_1h = get_crypto_1h_data(ticker)
            
        if df_1h is not None and not df_1h.empty:
            atr_series = df_1h.ta.atr(length=config.IND_ATR_LENGTH)
            if atr_series is not None and not atr_series.empty:
                last_atr = atr_series.iloc[-1]
                if last_atr is not None and not math.isnan(last_atr):
                    _atr_cache[ticker] = (float(last_atr), now)
                    return float(last_atr)
    except Exception as e:
        logging.warning(f"[_get_atr_cached] {ticker} için ATR hesaplanamadı: {e}")
        
    return None

def _get_structural_floor(ticker: str, signal: str) -> float:
    """
    Aktif işlemin yapıldığı varlık için 1H EMA-20 değerini çekerek yapısal zemin olarak döner.
    """
    try:
        from data_sources import get_bist_data
        df_1h = None

        if ticker.endswith(".IS"):
            _, _, df_1h = get_bist_data(ticker)
        elif "=" in ticker or "GLDTR" in ticker or "GMSTR" in ticker:
            from data_sources import get_emtia_1h_data
            df_1h = get_emtia_1h_data(ticker)
        else:
            from data_sources import get_crypto_1h_data
            df_1h = get_crypto_1h_data(ticker)

        if df_1h is not None and not df_1h.empty:
            df_1h.ta.ema(length=config.IND_EMA_MID, append=True)
            ema_col = f"EMA_{config.IND_EMA_MID}"
            if ema_col in df_1h.columns:
                last_ema = df_1h[ema_col].iloc[-1]
                if last_ema is not None and not math.isnan(last_ema):
                    return float(last_ema)
    except Exception as e:
        logging.warning(f"[_get_structural_floor] {ticker} için EMA hesaplanamadı: {e}")
    return None

def _calculate_long_trailing_stop(t, current_price, profit_pct, trailing_dist, atr_floor):
    ticker = t["ticker"]
    sl = float(t["sl"])
    
    # Kâr kilit mekanizması (Profit Locking)
    # Başlangıçta atr ile esnek bir takip alanı bırakıyoruz, kâr arttıkça çarpanı bir miktar daraltabiliriz
    # ancak eskisi gibi agresif yarıya kesme yapmayacağız.
    if ticker.endswith(".IS"):
        base_multiplier = config.ATR_MULTIPLIER_BIST
    elif "=" in ticker or "GLDTR" in ticker or "GMSTR" in ticker:
        base_multiplier = config.EMTIA_ATR_MULT.get(ticker, 2.5)
    else:
        base_multiplier = config.ATR_MULTIPLIER_CRYPTO

    # Güncel ATR değerini al (Chandelier Exit)
    real_atr = _get_atr_cached(ticker)
    
    if real_atr is not None and real_atr > 0:
        if config.HYBRID_STOP_ENABLED:
            # Çok kârlı pozisyonlarda stop'u biraz sıkılaştırıp kârı kilitleyelim (kademeli daralma)
            if profit_pct >= 20.0:
                current_trailing_dist = real_atr * (base_multiplier * 0.6)
            elif profit_pct >= 10.0:
                current_trailing_dist = real_atr * (base_multiplier * 0.8)
            else:
                current_trailing_dist = real_atr * base_multiplier
        else:
            current_trailing_dist = real_atr * base_multiplier
    else:
        # Fallback: ATR hesaplanamazsa eski sabit trailing dist'i kullanalım
        if config.HYBRID_STOP_ENABLED:
            if profit_pct >= 20.0:
                current_trailing_dist = trailing_dist * 0.6
            elif profit_pct >= 10.0:
                current_trailing_dist = trailing_dist * 0.8
            else:
                current_trailing_dist = trailing_dist
        else:
            current_trailing_dist = trailing_dist

    # En az atr_floor kadar mesafe bırak (çok daralmasını önle)
    current_trailing_dist = max(current_trailing_dist, atr_floor)

    raw_hh = t.get("highest_high")
    highest_high = float(t["entry_price"]) if raw_hh is None else float(raw_hh)
    if current_price > highest_high:
        highest_high = current_price
        t["highest_high"] = highest_high

    new_sl = highest_high - current_trailing_dist

    if config.STRUCTURAL_STOP_ENABLED:
        import trade_tracker
        struct_floor = trade_tracker._get_structural_floor(ticker, "AL")
        if struct_floor is not None:
            struct_sl = struct_floor * 0.999
            new_sl = max(new_sl, struct_sl)

    ticker_noise = (sum(ord(c) for c in ticker) % 100) / 100000.0
    asymmetric_offset = config.ANTI_HUNT_OFFSET_PCT + ticker_noise
    new_sl = new_sl * (1.0 - asymmetric_offset)

    entry_price = float(t["entry_price"])
    if sl >= entry_price:
        new_sl = max(new_sl, entry_price)

    return new_sl

def _calculate_short_trailing_stop(t, current_price, profit_pct, trailing_dist, atr_floor_short, strategy_name):
    ticker = t["ticker"]
    sl = float(t["sl"])
    
    if ticker.endswith(".IS"):
        base_multiplier = config.ATR_MULTIPLIER_BIST
    elif "=" in ticker or "GLDTR" in ticker or "GMSTR" in ticker:
        base_multiplier = config.EMTIA_ATR_MULT.get(ticker, 2.5)
    else:
        base_multiplier = config.ATR_MULTIPLIER_CRYPTO

    real_atr = _get_atr_cached(ticker)
    
    if real_atr is not None and real_atr > 0:
        if config.HYBRID_STOP_ENABLED:
            if profit_pct >= 20.0:
                current_trailing_dist = real_atr * (base_multiplier * 0.6)
            elif profit_pct >= 10.0:
                current_trailing_dist = real_atr * (base_multiplier * 0.8)
            else:
                current_trailing_dist = real_atr * base_multiplier
        else:
            if "ŞELALE SÖRFÜ" in strategy_name:
                current_trailing_dist = real_atr * base_multiplier
            elif "UÇURUM ÇÖKÜŞÜ" in strategy_name:
                if profit_pct >= 15.0:
                    current_trailing_dist = real_atr * (base_multiplier * 0.4)
                else:
                    current_trailing_dist = real_atr * base_multiplier
            else:
                current_trailing_dist = real_atr * base_multiplier
    else:
        # Fallback
        if config.HYBRID_STOP_ENABLED:
            if profit_pct >= 20.0:
                current_trailing_dist = trailing_dist * 0.6
            elif profit_pct >= 10.0:
                current_trailing_dist = trailing_dist * 0.8
            else:
                current_trailing_dist = trailing_dist
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
                    current_trailing_dist = trailing_dist * 0.6
                elif profit_pct >= 10.0:
                    current_trailing_dist = trailing_dist * 0.8
                else:
                    current_trailing_dist = trailing_dist

    current_trailing_dist = max(current_trailing_dist, atr_floor_short)

    raw_ll = t.get("lowest_low")
    lowest_low = float(t["entry_price"]) if raw_ll is None else float(raw_ll)
    if current_price < lowest_low:
        lowest_low = current_price
        t["lowest_low"] = lowest_low

    new_sl = lowest_low + current_trailing_dist

    if config.STRUCTURAL_STOP_ENABLED:
        import trade_tracker
        struct_floor = trade_tracker._get_structural_floor(ticker, "SAT")
        if struct_floor is not None:
            struct_sl = struct_floor * 1.001
            new_sl = min(new_sl, struct_sl)

    ticker_noise = (sum(ord(c) for c in ticker) % 100) / 100000.0
    asymmetric_offset = config.ANTI_HUNT_OFFSET_PCT + ticker_noise
    new_sl = new_sl * (1.0 + asymmetric_offset)

    entry_price = float(t["entry_price"])
    if sl <= entry_price:
        new_sl = min(new_sl, entry_price)

    return new_sl

def _update_trailing_stop(t, current_price, profit_pct, signal, strategy_name):
    """
    Hibrit izleyen stop güncelleme motoru.
    Ters Mandal (Ratchet): LONG stop yalnızca YUKARI, SHORT stop yalnızca AŞAĞI gider.
    Freqtrade tarzı activation threshold (R:R >= TRAILING_STOP_ACTIVATION_RR) eklenmiştir.
    """
    notifications = []
    ticker = t["ticker"]
    sl = float(t["sl"])
    trailing_dist = float(t.get("trailing_dist", abs(float(t["entry_price"]) - sl)))
    entry_price = float(t["entry_price"])

    # Freqtrade-style Trailing Stop Activation Check
    initial_risk = trailing_dist
    current_rr = 0.0
    if initial_risk > 0:
        if signal == "AL":
            current_rr = (current_price - entry_price) / initial_risk
        else:
            current_rr = (entry_price - current_price) / initial_risk

    is_trailing_active = t.get("trailing_active", False)
    activation_rr = getattr(config, 'TRAILING_STOP_ACTIVATION_RR', 1.5)

    if not is_trailing_active and current_rr >= activation_rr:
        t["trailing_active"] = True
        is_trailing_active = True
        logging.info(f"[{ticker}] Trailing Stop aktif edildi! Mevcut R:R: {current_rr:.2f} >= Eşik: {activation_rr}")

    if not is_trailing_active:
        return t, notifications

    if signal == "AL":
        atr_floor = trailing_dist * 0.3
        new_sl = _calculate_long_trailing_stop(t, current_price, profit_pct, trailing_dist, atr_floor)

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
        atr_floor_short = trailing_dist * 0.3
        new_sl = _calculate_short_trailing_stop(t, current_price, profit_pct, trailing_dist, atr_floor_short, strategy_name)

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
