"""
signal_decay.py — Sinyal Erime Motoru (V3.2 Kaos Çözümü #3)
Sinyal yaşlanmasını takip eder, R:R oranını yeniden hesaplar,
bayat sinyalleri otomatik iptal eder.

Sinyal Yaşam Döngüsü:
  t=0        → FRESH (Taze): Orijinal SL/TP geçerli
  t=30dk     → WARM (Ilık): SL/TP yeniden hesaplanır
  t=2saat    → STALE (Bayat): R:R kontrol edilir, düşükse iptal
  t=6saat    → DEAD (Ölü): Kripto sinyalleri otomatik iptal
  t=seans    → DEAD: BIST sinyalleri seans sonunda iptal
"""
import logging
from datetime import datetime, timezone

# 99 yapılmıştır
import config

# Sinyal yaşam eşikleri (saniye) - Config.py SSOT eşleşmesi
DECAY_WARM_SECONDS = getattr(config, 'SIGNAL_DECAY_WARM_SECONDS', 1800)
DECAY_STALE_SECONDS = getattr(config, 'SIGNAL_DECAY_STALE_SECONDS', 7200)
DECAY_DEAD_CRYPTO_SECONDS = getattr(config, 'SIGNAL_DECAY_DEAD_CRYPTO_SECONDS', 21600)
DECAY_DEAD_BIST_SECONDS = getattr(config, 'SIGNAL_DECAY_DEAD_BIST_SECONDS', 28800)

# Minimum R:R — bu değerin altına düşen sinyaller iptal edilir
DECAY_MIN_RR = getattr(config, 'SIGNAL_DECAY_MIN_RR', 1.5)


def get_signal_age_seconds(trade: dict) -> float:
    # 99 yapılmıştır
    if not getattr(config, 'SIGNAL_DECAY_ENABLED', True):
        return 0.0
    """
    Sinyalin yaşını saniye cinsinden hesaplar.
    entry_time alanı yoksa 0 döner (geriye uyumluluk).
    """
    entry_time_str = trade.get("entry_time")
    if not entry_time_str or entry_time_str == "Bilinmiyor":
        return 0.0
    
    try:
        if '+' in entry_time_str:
            entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S+00:00').replace(tzinfo=timezone.utc)
        else:
            entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
        
        age = (datetime.now(timezone.utc) - entry_dt).total_seconds()
        return max(0.0, age)
    except Exception as e:
        logging.warning(f"[signal_decay] Yaş hesaplama hatası: {e}")
        return 0.0


def get_decay_status(trade: dict) -> str:
    # 99 yapılmıştır
    if not getattr(config, 'SIGNAL_DECAY_ENABLED', True):
        return "FRESH"
    """
    Sinyalin mevcut erime durumunu döner.
    
    Returns:
        "FRESH" | "WARM" | "STALE" | "DEAD"
    """
    age = get_signal_age_seconds(trade)
    ticker = trade.get("ticker", "")
    is_crypto = "/" in ticker
    
    dead_threshold = DECAY_DEAD_CRYPTO_SECONDS if is_crypto else DECAY_DEAD_BIST_SECONDS
    
    if age >= dead_threshold:
        return "DEAD"
    elif age >= DECAY_STALE_SECONDS:
        return "STALE"
    elif age >= DECAY_WARM_SECONDS:
        return "WARM"
    return "FRESH"


def calculate_current_rr(trade: dict, current_price: float) -> float:
    # 99 yapılmıştır
    if not getattr(config, 'SIGNAL_DECAY_ENABLED', True):
        return float(trade.get("rr_ratio", 2.0))
    """
    Mevcut fiyata göre R:R oranını yeniden hesaplar.
    Sinyal üretildiğindeki fiyattan farklı bir noktada giriş yapılmışsa,
    R:R dramatik olarak değişmiş olabilir.
    
    Returns:
        R:R oranı (float). Negatif ise sinyal yönünün tersi hareket var.
    """
    signal = trade.get("signal", "AL")
    sl = float(trade.get("sl", 0))
    tp = float(trade.get("tp", 0))
    
    if sl == 0 or tp == 0 or current_price == 0:
        return 0.0
    
    try:
        if signal == "AL":
            risk = current_price - sl
            reward = tp - current_price
        else:  # SAT
            risk = sl - current_price
            reward = current_price - tp
        
        if risk <= 0:
            return 0.0  # Fiyat zaten SL'nin ötesinde
        
        return reward / risk
    except Exception:
        return 0.0


def check_signal_decay(trade: dict, current_price: float) -> dict:
    # 99 yapılmıştır
    if not getattr(config, 'SIGNAL_DECAY_ENABLED', True):
        return {
            "status": "FRESH",
            "should_close": False,
            "current_rr": float(trade.get("rr_ratio", 2.0)),
            "age_seconds": 0.0,
            "notification": None
        }
    """
    Bir aktif işlemin sinyal erime durumunu kontrol eder.
    
    Returns:
        {
            "status": "FRESH" | "WARM" | "STALE" | "DEAD",
            "should_close": bool,
            "current_rr": float,
            "age_seconds": float,
            "notification": str | None
        }
    """
    age = get_signal_age_seconds(trade)
    status = get_decay_status(trade)
    current_rr = calculate_current_rr(trade, current_price)
    ticker = trade.get("ticker", "")
    signal = trade.get("signal", "AL")
    entry_price = float(trade.get("entry_price", 0))
    
    result = {
        "status": status,
        "should_close": False,
        "current_rr": current_rr,
        "age_seconds": age,
        "notification": None
    }
    
    # DEAD: Sinyal ömrü doldu
    if status == "DEAD":
        # Kârda değilse kapat
        if signal == "AL":
            profit_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        if profit_pct < 2.0:  # %2'den az kârdaysa → kapat
            result["should_close"] = True
            hours = age / 3600
            result["notification"] = (
                f"⏰ <b>SİNYAL ÖMRÜ DOLDU (Signal Decay)</b>\n"
                f"Varlık: <code>{ticker}</code>\n"
                f"Sinyal Yaşı: <b>{hours:.1f} saat</b>\n"
                f"Mevcut R:R: <b>{current_rr:.2f}:1</b>\n"
                f"Mevcut Kâr: %{profit_pct:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📋 <b>AKSİYON:</b> Bu pozisyonu kapat veya manuel takip et.\n"
                f"Sistem bu sinyali artık izlemeyecek."
            )
        # Kârdaysa: decay uyarısı ama kapatma önerme
        else:
            hours = age / 3600
            result["notification"] = (
                f"⏰ <b>SİNYAL YAŞLANDI (ama kârda)</b>\n"
                f"Varlık: <code>{ticker}</code>\n"
                f"Sinyal Yaşı: <b>{hours:.1f} saat</b>\n"
                f"Mevcut Kâr: %{profit_pct:.2f}\n"
                f"Trailing Stop ile takip devam ediyor."
            )
    
    # STALE: R:R kontrolü
    elif status == "STALE":
        # Zaten decay_notified edildiyse tekrar bildirim gönderme
        if trade.get("decay_notified"):
            return result
        
        if current_rr < DECAY_MIN_RR and current_rr >= 0:
            hours = age / 3600
            result["should_close"] = True
            result["notification"] = (
                f"📉 <b>SİNYAL ERİDİ — R:R ÇOK DÜŞÜK</b>\n"
                f"Varlık: <code>{ticker}</code>\n"
                f"Sinyal Yaşı: <b>{hours:.1f} saat</b>\n"
                f"Orijinal R:R → Mevcut R:R: <b>{current_rr:.2f}:1</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📋 <b>AKSİYON:</b> Bu pozisyonu kapat — R:R {DECAY_MIN_RR}:1 altında."
            )
    
    # WARM: Bilgilendirme (opsiyonel, agresif bildirim istemiyorsan kaldır)
    elif status == "WARM":
        pass  # Şimdilik sessiz, gerekirse bildirim eklenebilir
    
    return result


def should_block_entry(trade: dict, current_price: float) -> tuple[bool, str]:
    # 99 yapılmıştır
    if not getattr(config, 'SIGNAL_DECAY_ENABLED', True):
        return False, ""
    """
    Yeni bir işlem kaydedilmeden önce, sinyalin hâlâ geçerli olup olmadığını kontrol eder.
    entry_price ile current_price arasındaki fark TTL bandını aştıysa → engelle.
    
    Returns:
        (should_block: bool, reason: str)
    """
    entry_price = float(trade.get("entry_price", 0))
    if entry_price == 0 or current_price == 0:
        return False, ""
    
    ttl_pct = 0.015  # %1.5 (config'deki ile aynı)
    signal = trade.get("signal", "AL")
    
    if signal == "AL":
        if current_price > entry_price * (1 + ttl_pct):
            return True, f"Fiyat sinyal fiyatının %1.5 üstüne çıktı ({current_price:.4f} > {entry_price * (1 + ttl_pct):.4f})"
    else:  # SAT
        if current_price < entry_price * (1 - ttl_pct):
            return True, f"Fiyat sinyal fiyatının %1.5 altına düştü ({current_price:.4f} < {entry_price * (1 - ttl_pct):.4f})"
    
    return False, ""
