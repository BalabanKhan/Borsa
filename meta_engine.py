import yfinance as yf
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math

_cache = {
    "trend": "NEUTRAL",
    "timestamp": datetime.min
}

def get_bist100_trend() -> str:
    """
    BIST100 (XU100.IS) endeksinin günlük rejimini döndürür.
    Returns "BULL" eğer endeks artıda/alıcılıysa, "BEAR" eğer ekside/satıcılıysa.
    Hatalarda veya veri yoksa "NEUTRAL" döner.
    Performans için 5 dakikalık basit cache kullanır.
    """
    now = datetime.now()
    # 5 dakikalık cache
    if now - _cache["timestamp"] < timedelta(minutes=5):
        return _cache["trend"]

    try:
        ticker = yf.Ticker("XU100.IS")
        df = ticker.history(period="5d", interval="1d")
        
        if df.empty or len(df) < 2:
            return "NEUTRAL"
            
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_close = float(last['Close'])
        prev_close = float(prev['Close'])
        
        # Eğer bir şekilde NaN veri varsa
        if math.isnan(current_close) or math.isnan(prev_close):
             return "NEUTRAL"
        
        pct_change = (current_close - prev_close) / prev_close * 100
        
        if pct_change >= 0:
            trend = "BULL"
        else:
            trend = "BEAR"
            
        _cache["trend"] = trend
        _cache["timestamp"] = now
        return trend
            
    except Exception as e:
        logging.warning(f"[meta_engine] BIST100 veri çekme hatası: {e}")
        # Hata anında varsa eski cache'i dön, yoksa NEUTRAL
        return _cache.get("trend", "NEUTRAL")
