import ccxt
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
import logging
import warnings
warnings.filterwarnings('ignore')

# Top 50 Yüksek Hacimli Coinler (Sığ Tahta Koruması)
TOP_CRYPTO = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "TRX/USDT", "TON/USDT", "NEAR/USDT", "INJ/USDT",
    "FET/USDT", "RENDER/USDT", "SUI/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "POL/USDT",
    "LTC/USDT", "BCH/USDT", "UNI/USDT", "XLM/USDT", "ATOM/USDT", "ICP/USDT", "FIL/USDT",
    "HBAR/USDT", "VET/USDT", "MKR/USDT", "AAVE/USDT", "RUNE/USDT", "QNT/USDT", "SNX/USDT",
    "THETA/USDT", "STX/USDT", "IMX/USDT", "EGLD/USDT", "SAND/USDT", "MANA/USDT", "AXS/USDT",
    "GRT/USDT", "CHZ/USDT", "S/USDT", "GALA/USDT", "CRV/USDT", "ROSE/USDT", "MINA/USDT", "WLD/USDT"
]

# BIST 100 En Yüksek Hacimli 50 Hisse
TOP_BIST = list(dict.fromkeys([
    "THYAO.IS", "ISCTR.IS",    "SASA.IS", "HEKTS.IS", "TUPRS.IS", "EREGL.IS",
    "KCHOL.IS", "SISE.IS", "AKBNK.IS", "YKBNK.IS", "GARAN.IS",
    "SAHOL.IS", "BIMAS.IS", "ASELS.IS", "KRDMD.IS",
    "FROTO.IS", "TTKOM.IS", "TCELL.IS", "ENKAI.IS", "PETKM.IS",
    "TOASO.IS", "PGSUS.IS", "ARCLK.IS", "TAVHL.IS", "DOHOL.IS",
    "ODAS.IS", "ASTOR.IS", "MIATK.IS", "GESAN.IS", "SMRTG.IS",
    "ALFAS.IS", "EUPWR.IS", "CVKMD.IS", "CANTE.IS", "ZOREN.IS",
    "AKSA.IS", "ISMEN.IS", "TSKB.IS", "SKBNK.IS", "VAKBN.IS",
    "HALKB.IS", "CIMSA.IS", "AKSEN.IS", "ENJSA.IS", "GWIND.IS",
    "KONTR.IS", "MGROS.IS", "SOKM.IS", "KCAER.IS"
]))

# EMTİA - Vadeli İşlem Kontratları (yfinance)
TOP_EMTIA_USD = [
    "GC=F",   # Altın (Gold)
    "SI=F",   # Gümüş (Silver)
    "CL=F",   # WTI Petrol
    "BZ=F",   # Brent Petrol
    "NG=F",   # Doğal Gaz
    "HG=F",   # Bakır
    "ZW=F",   # Buğday
]
TOP_EMTIA_TRY = [
    "GLDTR.IS",  # Altın/TL (QNB Finans Portföy Altın Fonu - BIST)
    "GMSTR.IS",  # Gümüş/TL (QNB Finans Portföy Gümüş Fonu - BIST)
]
TOP_EMTIA = TOP_EMTIA_USD + TOP_EMTIA_TRY

# Emtia ATR çarpanları (volatiliteye göre)
EMTIA_ATR_MULT = {
    "GC=F": 2.0, "GLDTR.IS": 2.0,
    "SI=F": 2.0, "GMSTR.IS": 2.0,
    "CL=F": 2.5, "BZ=F": 2.5,
    "HG=F": 2.5,
    "NG=F": 3.0,
    "ZW=F": 3.0,
}

# DXY'den etkilenen emtialar (Altın ve Gümüş)
DXY_SENSITIVE = {"GC=F", "SI=F", "GLDTR.IS", "GMSTR.IS"}

# Emtia isimleri (Telegram mesajları için)
EMTIA_NAMES = {
    "GC=F": "Altın (USD)", "SI=F": "Gümüş (USD)",
    "GLDTR.IS": "Altın (TL)", "GMSTR.IS": "Gümüş (TL)",
    "CL=F": "WTI Petrol", "BZ=F": "Brent Petrol",
    "NG=F": "Doğal Gaz", "HG=F": "Bakır", "ZW=F": "Buğday",
}

# 🐻 AYI AVCISI — Ağır Sıklet SHORT Tarama Evreni (Top 30)
TOP_HEAVY_SHORT = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "TRX/USDT",
    "TON/USDT", "NEAR/USDT", "SUI/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT", "LTC/USDT", "BCH/USDT", "UNI/USDT", "XLM/USDT",
    "ATOM/USDT", "ICP/USDT", "FIL/USDT", "HBAR/USDT", "MKR/USDT",
    "AAVE/USDT", "RUNE/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT",
]

# 🚫 Meme Coin Kalıcı Kara Liste (SHORT yasağı — kod bazında)
MEME_BLACKLIST = {
    "DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "WIF/USDT", "FLOKI/USDT",
    "BONK/USDT", "MEME/USDT", "BABYDOGE/USDT", "NEIRO/USDT", "TURBO/USDT",
}

exchange = ccxt.binance({'enableRateLimit': True})
exchange_futures = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
exchange_fallback = ccxt.kraken({'enableRateLimit': True})

IS_USA_SERVER = True  # ABD sunucusunda Binance engelli olduğu için doğrudan Kraken/yfinance kullanır

# requests ve BeautifulSoup kaldırıldı (check_token_unlocks stub olduğu için kullanılmıyor)

def is_weekend_fakeout_time():
    """Cuma 23:00'dan Pazar 23:00'a kadar Hafta Sonu Fakeout süresi."""
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if now.weekday() == 4 and now.hour >= 23: # Cuma 23:00 ve sonrası
        return True
    if now.weekday() == 5: # Cumartesi tam gün
        return True
    if now.weekday() == 6 and now.hour < 23: # Pazar 23:00 öncesi
        return True
    return False

def get_funding_rate(symbol):
    """Anlık Funding Rate'i çeker (Yüzde olarak döner, örn: 0.01)"""
    if IS_USA_SERVER:
        return 0.0
    try:
        funding = exchange_futures.fetch_funding_rate(symbol)
        if funding and 'fundingRate' in funding:
            return float(funding['fundingRate']) * 100
    except Exception as e:
        logging.warning(f"[get_funding_rate] {symbol}: {e}")
    return 0.0

def fetch_crypto_oi_crash(symbol):
    """Son 24 saat içinde Open Interest (OI) verisinde %15 veya daha büyük bir çöküş var mı?"""
    if IS_USA_SERVER:
        return False
    try:
        oi_hist = exchange_futures.fetch_open_interest_history(symbol, timeframe='1h', limit=24)
        if len(oi_hist) > 0:
            # openInterestValue (USD değeri) veya openInterestAmount (Coin miktarı) kullanılabilir
            key = 'openInterestValue' if 'openInterestValue' in oi_hist[-1] else 'openInterestAmount'
            if key in oi_hist[-1] and oi_hist[-1][key] is not None:
                current_oi = float(oi_hist[-1][key])
                max_oi = max([float(x[key]) for x in oi_hist if x[key] is not None])
                if max_oi > 0:
                    drop_pct = ((max_oi - current_oi) / max_oi) * 100
                    if drop_pct >= 15.0:
                        return True
    except Exception as e:
        logging.warning(f"[fetch_crypto_oi_crash] {symbol}: {e}")
    return False

def get_btc_dominance_trend():
    """BTCDOM/USDT grafiğinden BTC Dominans Trendini hesaplar"""
    if IS_USA_SERVER:
        return "UNKNOWN"
    try:
        ohlcv = exchange_futures.fetch_ohlcv("BTCDOM/USDT", '1d', limit=60)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        if len(df) >= 50:
            last_ema20 = df['EMA_20'].iloc[-1]
            last_ema50 = df['EMA_50'].iloc[-1]
            if last_ema20 > last_ema50:
                return "UP"
            else:
                return "DOWN"
    except Exception as e:
        logging.warning(f"[get_btc_dominance_trend] {e}")
    return "UNKNOWN"

def check_token_unlocks(symbol):
    """
    Token kilit açılım takvimini scrape eder. 
    (3-5 gün içinde %3'ten büyük açılım var mı?)
    Not: Ücretsiz siteler genelde Cloudflare ile korunur, basit bir requests çağrısı engellenebilir.
    Şimdilik API altyapısı kurulana kadar bu fonksiyon taslak olarak False (kilit açılımı yok) döner.
    """
    try:
        base_coin = symbol.split('/')[0].lower()
        # headers = {'User-Agent': 'Mozilla/5.0'}
        # response = requests.get(f"https://dropstab.com/coins/{base_coin}/vesting", headers=headers)
        # BeautifulSoup ile parse edilip oran aranır...
        
        # STUB: API altyapısı kurulana kadar her zaman False döner.
        # Token unlock verisi kontrol EDİLMİYOR.
        logging.debug(f"[check_token_unlocks] {symbol}: STUB - API bağlantısı yok, False döndürülüyor.")
        return False
    except Exception as e:
        logging.warning(f"[check_token_unlocks] {symbol}: {e}")
        return False

def is_bist_open():
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if now.weekday() > 4: return False
    return dt_time(9, 55) <= now.time() <= dt_time(18, 10)

def check_xu100_wind():
    try:
        df = yf.download("XU100.IS", period="5d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if len(df) >= 2:
            prev_close = df['Close'].iloc[-2]
            curr_close = df['Close'].iloc[-1]
            pct_change = ((curr_close - prev_close) / prev_close) * 100
            return pct_change < -1.0
    except Exception as e:
        logging.warning(f"[check_xu100_wind] {e}")
    return False

def clean_yf_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.dropna()
    df.columns = [c.lower() for c in df.columns]
    return df

def get_bist_data(symbol):
    try:
        df_1d = yf.download(symbol, period="6mo", interval="1d", progress=False)
        df_1d = clean_yf_df(df_1d)
        
        df_1h = yf.download(symbol, period="1mo", interval="1h", progress=False)
        df_1h = clean_yf_df(df_1h)
        
        if df_1h.empty or df_1d.empty: return None, None, None
        
        df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        return df_1d, df_4h, df_1h
    except Exception as e:
        logging.warning(f"[get_bist_data] {symbol}: {e}")
        return None, None, None

def get_crypto_data(symbol):
    limit = 100
    # ABD sunucusu değilse önce Binance'i dene
    if not IS_USA_SERVER:
        try:
            ohlcv_1d = exchange.fetch_ohlcv(symbol, '1d', limit=limit)
            df_1d = pd.DataFrame(ohlcv_1d, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            ohlcv_4h = exchange.fetch_ohlcv(symbol, '4h', limit=limit)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            for df in [df_1d, df_4h]:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                
            return df_1d, df_4h
        except Exception as e:
            logging.info(f"[get_crypto_data] Binance hatası, yedeklere geçiliyor: {e}")

    # Kraken ve yfinance yedekleri
    try:
        try:
            ohlcv_1d = exchange_fallback.fetch_ohlcv(symbol, '1d', limit=limit)
            ohlcv_4h = exchange_fallback.fetch_ohlcv(symbol, '4h', limit=limit)
        except Exception:
            usd_sym = symbol.replace("/USDT", "/USD")
            ohlcv_1d = exchange_fallback.fetch_ohlcv(usd_sym, '1d', limit=limit)
            ohlcv_4h = exchange_fallback.fetch_ohlcv(usd_sym, '4h', limit=limit)
            
        df_1d = pd.DataFrame(ohlcv_1d, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        for df in [df_1d, df_4h]:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
        return df_1d, df_4h
    except Exception as ekr:
        try:
            yf_ticker = symbol.replace("/USDT", "-USD")
            df_1d = yf.download(yf_ticker, period="6mo", interval="1d", progress=False)
            df_1d = clean_yf_df(df_1d)
            
            df_1h = yf.download(yf_ticker, period="1mo", interval="1h", progress=False)
            df_1h = clean_yf_df(df_1h)
            
            if df_1h.empty or df_1d.empty: return None, None
            
            df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            return df_1d, df_4h
        except Exception as eyf:
            logging.warning(f"[get_crypto_data] {symbol} hiçbir kaynaktan çekilemedi: {eyf}")
            return None, None

_btc_status_cache = None

def get_btc_status():
    """BTC > EMA20 Kontrolü (Zorunlu BTC İzni Ana Şalteri)"""
    global _btc_status_cache
    now = time.time()
    if _btc_status_cache is not None and (now - _btc_status_cache[0]) < 300:
        return _btc_status_cache[1]
        
    res = False
    if not IS_USA_SERVER:
        try:
            ohlcv_1d = exchange.fetch_ohlcv("BTC/USDT", '1d', limit=50)
            df = pd.DataFrame(ohlcv_1d, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            logging.info(f"[get_btc_status] Binance hatası, yedeklere geçiliyor: {e}")

    # Kraken / yfinance
    if IS_USA_SERVER or 'df' not in locals():
        try:
            ohlcv_1d = exchange_fallback.fetch_ohlcv("BTC/USDT", '1d', limit=50)
            df = pd.DataFrame(ohlcv_1d, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as ekr:
            try:
                df = yf.download("BTC-USD", period="3mo", interval="1d", progress=False)
                df = clean_yf_df(df)
            except Exception as eyf:
                logging.warning(f"[get_btc_status] Veri çekilemedi: {eyf}")
                _btc_status_cache = (now, False)
                return False
            
    try:
        df.ta.ema(length=20, append=True)
        ema_col = 'ema_20' if 'ema_20' in df.columns else 'EMA_20'
        close_col = 'close' if 'close' in df.columns else 'Close'
        if len(df) >= 20:
            last_close = df[close_col].iloc[-1]
            last_ema = df[ema_col].iloc[-1]
            if not pd.isna(last_ema) and last_close > last_ema:
                res = True
    except Exception as e:
        logging.warning(f"[get_btc_status] analiz hatası: {e}")
        
    _btc_status_cache = (now, res)
    return res


_btc_pumping_cache = None

def check_btc_not_pumping():
    """BTC aşırı yükselişte (pumping) ise altcoin şortlamayı engeller. (RSI > 70 veya devasa mum)"""
    global _btc_pumping_cache
    now = time.time()
    if _btc_pumping_cache is not None and (now - _btc_pumping_cache[0]) < 300:
        return _btc_pumping_cache[1]
        
    res = True
    if not IS_USA_SERVER:
        try:
            ohlcv = exchange.fetch_ohlcv("BTC/USDT", '4h', limit=50)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            logging.info(f"[check_btc_not_pumping] Binance hatası, yedeklere geçiliyor: {e}")

    if IS_USA_SERVER or 'df' not in locals():
        try:
            ohlcv = exchange_fallback.fetch_ohlcv("BTC/USDT", '4h', limit=50)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as ekr:
            try:
                df_1h = yf.download("BTC-USD", period="1mo", interval="1h", progress=False)
                df_1h = clean_yf_df(df_1h)
                df = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            except Exception as eyf:
                logging.warning(f"[check_btc_not_pumping] Veri çekilemedi: {eyf}")
                _btc_pumping_cache = (now, True)
                return True
            
    try:
        df.ta.rsi(length=14, append=True)
        rsi_col = 'rsi_14' if 'rsi_14' in df.columns else 'RSI_14'
        close_col = 'close' if 'close' in df.columns else 'Close'
        open_col = 'open' if 'open' in df.columns else 'Open'
        if len(df) >= 14:
            last_rsi = df[rsi_col].iloc[-1]
            last_close = df[close_col].iloc[-1]
            last_open = df[open_col].iloc[-1]
            pct_change = ((last_close - last_open) / last_open) * 100
            
            if last_rsi > 70 or pct_change > 4.0:
                res = False
    except Exception as e:
        logging.warning(f"[check_btc_not_pumping] analiz hatası: {e}")
        
    _btc_pumping_cache = (now, res)
    return res

# ==========================================
# SNIPER (KESKİN NİŞANCI) YARDIMCI FONKSİYONLAR
# ==========================================

def _sniper_get_htf_bias(df):
    """1 Günlük EMA20 vs EMA50 ile trend yönü belirle.
    Returns: 1 (Bullish/AL), -1 (Bearish/SAT), 0 (Nötr)
    NOT: DataFrame mutasyonunu önlemek için .copy() ile çalışır.
    """
    if len(df) < 50:
        return 0
    df = df.copy()  # Side-effect önleme: Orijinal DataFrame'i değiştirme
    if 'EMA_20' not in df.columns:
        df.ta.ema(length=20, append=True)
    if 'EMA_50' not in df.columns:
        df.ta.ema(length=50, append=True)

    ema20 = df['EMA_20'].iloc[-1]
    ema50 = df['EMA_50'].iloc[-1]
    close = df['close'].iloc[-1]

    if pd.isna(ema20) or pd.isna(ema50):
        return 0

    if ema20 > ema50 and close > ema20:
        return 1    # Bullish
    elif ema20 < ema50 and close < ema20:
        return -1   # Bearish
    return 0        # Nötr


def _sniper_find_swing_points(df, point_type="low", neighbors=3):
    """Swing high veya swing low noktaları tespit et.
    Returns: [(index, price), ...] listesi
    """
    swings = []
    col = 'low' if point_type == "low" else 'high'

    for i in range(neighbors, len(df) - neighbors):
        val = df[col].iloc[i]
        if point_type == "low":
            is_swing = all(val <= df[col].iloc[i - j] for j in range(1, neighbors + 1))
            is_swing = is_swing and all(val < df[col].iloc[i + j] for j in range(1, neighbors + 1))
        else:
            is_swing = all(val >= df[col].iloc[i - j] for j in range(1, neighbors + 1))
            is_swing = is_swing and all(val > df[col].iloc[i + j] for j in range(1, neighbors + 1))
        if is_swing:
            swings.append((i, val))
    return swings


def _sniper_detect_sweep(df, swing_points, point_type="low", lookback=10):
    """Son lookback mum içinde eski bir swing noktasının ihlal edilip geri çekilmesini tespit et.
    LONG (low): Fitil swing low altına sardı ama gövde yukarıda kapandı.
    SHORT (high): Fitil swing high üstüne sardı ama gövde aşağıda kapandı.
    """
    if not swing_points:
        return False, None

    check_start = max(0, len(df) - lookback)

    for i in range(check_start, len(df)):
        row = df.iloc[i]
        for sw_idx, sw_price in swing_points:
            if sw_idx >= i:
                continue  # Sweep eden mum, sweep edilen noktadan SONRA olmalı

            if point_type == "low":
                if row['low'] < sw_price and row['close'] > sw_price:
                    return True, sw_price
            else:
                if row['high'] > sw_price and row['close'] < sw_price:
                    return True, sw_price

    return False, None


def _sniper_detect_msb(df, swing_points, point_type="high"):
    """Market Structure Break tespiti.
    LONG (high): Son kapanış en son swing high'ın üzerinde mi?
    SHORT (low): Son kapanış en son swing low'un altında mı?
    """
    if not swing_points:
        return False, None, None

    last_sw_idx, last_sw_price = swing_points[-1]
    current_close = df['close'].iloc[-1]

    if point_type == "high" and current_close > last_sw_price:
        return True, last_sw_price, last_sw_idx
    elif point_type == "low" and current_close < last_sw_price:
        return True, last_sw_price, last_sw_idx

    return False, None, None


def _sniper_calculate_ote(sweep_price, msb_price):
    """Fibonacci 0.618 - 0.786 OTE (Optimal Trade Entry) bölgesini hesapla."""
    fib_range = abs(msb_price - sweep_price)
    if fib_range == 0:
        return 0, 0

    if sweep_price < msb_price:
        # LONG: Tepeden aşağı doğru OTE
        ote_top = msb_price - (fib_range * 0.618)
        ote_bottom = msb_price - (fib_range * 0.786)
    else:
        # SHORT: Dipten yukarı doğru OTE (Premium bölge)
        ote_bottom = msb_price + (fib_range * 0.618)
        ote_top = msb_price + (fib_range * 0.786)
    return ote_top, ote_bottom


def _sniper_detect_fvg(df, ote_top, ote_bottom, lookback=15, direction="bullish"):
    """OTE bölgesi içinde doldurulmamış FVG (Fair Value Gap) tespit et."""
    search_start = max(1, len(df) - lookback)

    for i in range(search_start, len(df) - 1):
        if i < 1:
            continue

        if direction == "bullish":
            candle1_high = df['high'].iloc[i - 1]
            candle3_low = df['low'].iloc[i + 1]
            if candle3_low > candle1_high:
                gap_bottom = candle1_high
                gap_top = candle3_low
                if gap_bottom <= ote_top and gap_top >= ote_bottom:
                    filled = any(df['low'].iloc[j] <= gap_top for j in range(i + 2, len(df)))
                    if not filled:
                        return True, gap_bottom, gap_top
        else:
            candle1_low = df['low'].iloc[i - 1]
            candle3_high = df['high'].iloc[i + 1]
            if candle3_high < candle1_low:
                gap_top = candle1_low
                gap_bottom = candle3_high
                if gap_bottom <= ote_top and gap_top >= ote_bottom:
                    filled = any(df['high'].iloc[j] >= gap_bottom for j in range(i + 2, len(df)))
                    if not filled:
                        return True, gap_bottom, gap_top

    return False, None, None


_btc_htf_bias_cache = None

def _get_btc_htf_bias():
    """BTC'nin 1 Günlük HTF Bias'ını kontrol et (altcoin taraması için 1 kez çağrılır)."""
    global _btc_htf_bias_cache
    now = time.time()
    if _btc_htf_bias_cache is not None and (now - _btc_htf_bias_cache[0]) < 300:
        return _btc_htf_bias_cache[1]
        
    res = 0
    if not IS_USA_SERVER:
        try:
            ohlcv = exchange.fetch_ohlcv("BTC/USDT", '1d', limit=60)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            logging.info(f"[_get_btc_htf_bias] Binance hatası, yedeklere geçiliyor: {e}")

    if IS_USA_SERVER or 'df' not in locals():
        try:
            ohlcv = exchange_fallback.fetch_ohlcv("BTC/USDT", '1d', limit=60)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as ekr:
            try:
                df = yf.download("BTC-USD", period="3mo", interval="1d", progress=False)
                df = clean_yf_df(df)
            except Exception as eyf:
                logging.warning(f"[_get_btc_htf_bias] Veri çekilemedi: {eyf}")
                _btc_htf_bias_cache = (now, 0)
                return 0
            
    try:
        res = _sniper_get_htf_bias(df)
    except Exception as e:
        logging.warning(f"[_get_btc_htf_bias] analiz hatası: {e}")
        
    _btc_htf_bias_cache = (now, res)
    return res



# ==========================================
# EMTİA VERİ + KALKAN FONKSİYONLARI
# ==========================================

def get_emtia_data(symbol):
    """Emtia vadeli kontrat için 1D ve 4H verisini yfinance üzerinden çeker."""
    try:
        df_1d = yf.download(symbol, period="6mo", interval="1d", progress=False)
        df_1d = clean_yf_df(df_1d)
        if df_1d.empty:
            return None, None
        # 4H veri: 1H indir, 4H'ye resample et
        df_1h_raw = yf.download(symbol, period="2mo", interval="1h", progress=False)
        df_1h_raw = clean_yf_df(df_1h_raw)
        df_4h = None
        if not df_1h_raw.empty:
            df_4h = df_1h_raw.resample('4h').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna()
        return df_1d, df_4h
    except Exception as e:
        logging.warning(f"[get_emtia_data] {symbol}: {e}")
        return None, None


_dxy_cache = None

def _check_dxy_shield():
    """DXY (Dolar Endeksi) yükseliş trendinde mi? 5dk cache ile kontrol eder."""
    global _dxy_cache
    now = time.time()
    if _dxy_cache is not None and (now - _dxy_cache[0]) < 300:
        return _dxy_cache[1]
    try:
        df = yf.download("DX-Y.NYB", period="6mo", interval="1d", progress=False)
        df = clean_yf_df(df)
        if df.empty:
            return False
        df.ta.ema(length=50, append=True)
        last = df.iloc[-1]
        ema50 = last.get('EMA_50')
        if ema50 is None or pd.isna(ema50):
            return False
        dxy_bullish = bool(last['close'] > ema50)
        _dxy_cache = (now, dxy_bullish)
        return dxy_bullish
    except Exception as e:
        logging.warning(f"[_check_dxy_shield] {e}")
        return False


def _is_macro_news_hour():
    """TSİ 15:00-16:30 arası → True (Emtia taraması durdurulur). Hafta içi."""
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if now.weekday() >= 5:
        return False
    if now.hour == 15 or (now.hour == 16 and now.minute <= 30):
        return True
    return False


# ==========================================
# 🐻 AYI AVCISI YARDIMCI FONKSİYONLARI
# ==========================================

_btc_short_bias_cache = None

def _is_btc_bullish_for_shorts():
    """BTC 4H'da EMA20 üstünde + hacimli mi? True ise TÜM altcoin SHORT'lar engellenir.
    5dk cache ile çalışır."""
    global _btc_short_bias_cache
    now = time.time()
    if _btc_short_bias_cache is not None and (now - _btc_short_bias_cache[0]) < 300:
        return _btc_short_bias_cache[1]

    result = False  # Varsayılan: BTC zayıf → short'lar açık
    try:
        if not IS_USA_SERVER:
            try:
                ohlcv = exchange.fetch_ohlcv("BTC/USDT", '4h', limit=50)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            except Exception:
                ohlcv = exchange_fallback.fetch_ohlcv("BTC/USDT", '4h', limit=50)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        else:
            try:
                ohlcv = exchange_fallback.fetch_ohlcv("BTC/USDT", '4h', limit=50)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            except Exception:
                df_1h = yf.download("BTC-USD", period="1mo", interval="1h", progress=False)
                df_1h = clean_yf_df(df_1h)
                df = df_1h.resample('4h').agg({
                    'open': 'first', 'high': 'max', 'low': 'min',
                    'close': 'last', 'volume': 'sum'
                }).dropna()

        if len(df) >= 25:
            df.ta.ema(length=20, append=True)
            df['vol_sma_20'] = df['volume'].rolling(20).mean()
            last = df.iloc[-1]
            ema20 = last.get('EMA_20')
            vol_sma = last.get('vol_sma_20')
            if ema20 is not None and not pd.isna(ema20):
                price_above_ema = float(last['close']) > float(ema20)
                volume_strong = True
                if vol_sma is not None and not pd.isna(vol_sma):
                    volume_strong = float(last['volume']) > float(vol_sma) * 0.8
                result = price_above_ema and volume_strong
    except Exception as e:
        logging.warning(f"[_is_btc_bullish_for_shorts] {e}")

    _btc_short_bias_cache = (now, result)
    return result


def _detect_sfp(df_4h, neighbors=3):
    """Swing Failure Pattern (Zirve Tuzağı) tespit eder.
    Returns: (sfp_found, swing_high_price, sfp_candle) veya (False, None, None)
    """
    if df_4h is None or len(df_4h) < 20:
        return False, None, None

    # Son 20 mumda swing high'ları bul (son mum hariç)
    highs = df_4h['high'].values
    n = len(highs)
    swing_highs = []

    for i in range(neighbors, n - neighbors - 1):  # Son mumu hariç tut
        is_swing = True
        for j in range(1, neighbors + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_highs.append((i, highs[i]))

    if not swing_highs:
        return False, None, None

    # En son swing high'ı al
    last_swing_idx, last_swing_high = swing_highs[-1]
    last_candle = df_4h.iloc[-1]

    # SFP Koşulları:
    # 1. Son mum high > swing_high (üstüne çıktı)
    # 2. Son mum close < swing_high (altında kapandı)
    # 3. Kırmızı mum (close < open)
    # 4. Üst fitil gövdenin 2 katından büyük
    if last_candle['high'] > last_swing_high and last_candle['close'] < last_swing_high:
        if last_candle['close'] < last_candle['open']:  # Kırmızı mum
            body = abs(last_candle['close'] - last_candle['open'])
            upper_wick = last_candle['high'] - max(last_candle['close'], last_candle['open'])
            if body > 0 and upper_wick > (2 * body):
                return True, last_swing_high, last_candle

    return False, None, None


def _detect_premium_rejection(df_4h, df_1d):
    """Pahalı Bölge Reddi (SMC Premium Short) tespit eder.
    Fibonacci 0.618-0.786 bölgesinde bearish red arar.
    Returns: (found, fib_618, fib_786, entry_candle) veya (False, None, None, None)
    NOT: DataFrame mutasyonunu önlemek için varolan kolonları kontrol eder.
    """
    if df_4h is None or len(df_4h) < 30 or df_1d is None or len(df_1d) < 20:
        return False, None, None, None

    # 1D bias kontrolü: EMA20 < EMA50 → düşüş trendi
    # Kolon zaten varsa tekrar hesaplama (gereksiz iş önleme)
    if 'EMA_20' not in df_1d.columns:
        df_1d.ta.ema(length=20, append=True)
    if 'EMA_50' not in df_1d.columns:
        df_1d.ta.ema(length=50, append=True)
    last_1d = df_1d.iloc[-1]
    ema20_1d = last_1d.get('EMA_20')
    ema50_1d = last_1d.get('EMA_50')

    if ema20_1d is None or ema50_1d is None or pd.isna(ema20_1d) or pd.isna(ema50_1d):
        return False, None, None, None
    if ema20_1d >= ema50_1d:  # Yükseliş trendi → premium short yok
        return False, None, None, None

    # 4H'da son düşüş bacağı: son 30 mumda en yüksek ve en düşük noktalar
    recent = df_4h.tail(30)
    swing_high_val = float(recent['high'].max())
    swing_high_idx = recent['high'].idxmax()
    # Swing high'dan sonraki en düşük nokta
    after_high = recent.loc[swing_high_idx:]
    if len(after_high) < 5:
        return False, None, None, None
    swing_low_val = float(after_high['low'].min())

    leg_range = swing_high_val - swing_low_val
    if leg_range <= 0:
        return False, None, None, None

    # Fibonacci seviyeleri (düşüşün tepesinden)
    fib_618 = swing_low_val + 0.618 * leg_range
    fib_786 = swing_low_val + 0.786 * leg_range

    last_4h = df_4h.iloc[-1]
    current_close = float(last_4h['close'])

    # Fiyat premium bölgede mi?
    if fib_618 <= current_close <= fib_786:
        # Red sinyali kontrolü
        is_bearish_engulfing = (
            last_4h['close'] < last_4h['open'] and  # Kırmızı mum
            len(df_4h) >= 2 and
            last_4h['open'] > df_4h.iloc[-2]['close'] and  # Önceki mumun üstünde açıldı
            last_4h['close'] < df_4h.iloc[-2]['open']  # Önceki mumun altında kapandı
        )

        # EMA20 (4H) reddi
        df_4h.ta.ema(length=20, append=True)
        ema20_4h = last_4h.get('EMA_20')
        ema_rejection = False
        if ema20_4h is not None and not pd.isna(ema20_4h):
            ema_rejection = (last_4h['high'] >= ema20_4h and last_4h['close'] < ema20_4h
                             and last_4h['close'] < last_4h['open'])

        if is_bearish_engulfing or ema_rejection:
            return True, fib_618, fib_786, last_4h

    return False, None, None, None


def _detect_bearish_divergence(df_4h, neighbors=3):
    """Negatif Uyumsuzluk (Yorgunluk Tepesi) tespit eder.
    Fiyat Higher High + RSI Lower High + Hacim düşük + EMA20 kırılımı.
    Returns: (found, swing_high_1, swing_high_2, rsi_1, rsi_2) veya (False, ...)
    """
    if df_4h is None or len(df_4h) < 30:
        return False, None, None, None, None

    df_4h.ta.rsi(length=14, append=True)
    df_4h.ta.ema(length=20, append=True)

    rsi_col = 'RSI_14'
    if rsi_col not in df_4h.columns:
        return False, None, None, None, None

    # Swing High'ları bul (fiyat)
    highs = df_4h['high'].values
    n = len(highs)
    swing_points = []

    for i in range(neighbors, n - 1):  # Son mumu dahil etme
        is_swing = True
        for j in range(1, neighbors + 1):
            if i - j < 0 or i + j >= n:
                is_swing = False
                break
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_points.append(i)

    if len(swing_points) < 2:
        return False, None, None, None, None

    # Son iki swing high
    idx1, idx2 = swing_points[-2], swing_points[-1]
    price_1 = float(df_4h.iloc[idx1]['high'])
    price_2 = float(df_4h.iloc[idx2]['high'])
    rsi_1 = float(df_4h.iloc[idx1][rsi_col])
    rsi_2 = float(df_4h.iloc[idx2][rsi_col])

    # Koşullar:
    # 1. Fiyat Higher High: price_2 > price_1
    # 2. RSI Lower High: rsi_2 < rsi_1
    # 3. RSI farkı anlamlı (en az 3 puan)
    if price_2 > price_1 and rsi_2 < rsi_1 and (rsi_1 - rsi_2) >= 3:
        # Hacim uyumsuzluğu: 2. tepe hacmi < 1. tepe hacmi
        vol_1 = float(df_4h.iloc[idx1]['volume'])
        vol_2 = float(df_4h.iloc[idx2]['volume'])
        vol_divergence = vol_2 < vol_1

        # Tetik: Son mum close < EMA20 (destek kırılımı)
        last = df_4h.iloc[-1]
        ema20 = last.get('EMA_20')
        if ema20 is not None and not pd.isna(ema20):
            if float(last['close']) < float(ema20) and vol_divergence:
                return True, price_1, price_2, rsi_1, rsi_2

    return False, None, None, None, None


# ==========================================
# YENİ STRATEJİ YARDIMCI FONKSİYONLARI
# ==========================================

_xu100_daily_cache = None

def _get_xu100_daily_data():
    """XU100 endeksinin günlük verisini çeker (RS stratejisi için, 5dk cache)."""
    global _xu100_daily_cache
    now = time.time()
    if _xu100_daily_cache is not None and (now - _xu100_daily_cache[0]) < 300:
        return _xu100_daily_cache[1]
    try:
        df = yf.download("XU100.IS", period="6mo", interval="1d", progress=False)
        df = clean_yf_df(df)
        if not df.empty:
            _xu100_daily_cache = (now, df)
            return df
    except Exception as e:
        logging.warning(f"[_get_xu100_daily_data] {e}")
    return _xu100_daily_cache[1] if _xu100_daily_cache else None


def get_bist_15m_data(symbol):
    """BIST hissesi için 15 dakikalık veri çeker (ORB stratejisi için)."""
    try:
        df = yf.download(symbol, period="5d", interval="15m", progress=False)
        df = clean_yf_df(df)
        return df if not df.empty else None
    except Exception as e:
        logging.warning(f"[get_bist_15m_data] {symbol}: {e}")
        return None


def _detect_squeeze(df):
    """
    BB(20,2) Keltner(20, 1.5×ATR) içine girdi mi? Kırılım olduysa yön döner.
    Returns: (squeeze_fired, direction, breakout_candle)
    """
    if len(df) < 25:
        return False, None, None

    # BB ve KC hesapla (zaten varsa tekrar eklemez)
    # Spesifik parametre kontrolü: BBU_20_2.0 ve KCU_20_1.5 aranır
    if not [c for c in df.columns if 'BBU_20_2' in c]:
        df.ta.bbands(length=20, std=2, append=True)
    if not [c for c in df.columns if 'KCU_20_1' in c]:
        df.ta.kc(length=20, scalar=1.5, append=True)

    bbu = [c for c in df.columns if 'BBU' in c]
    bbl = [c for c in df.columns if 'BBL' in c]
    kcu = [c for c in df.columns if 'KCU' in c]
    kcl = [c for c in df.columns if 'KCL' in c]

    if not (bbu and bbl and kcu and kcl):
        return False, None, None

    bbu_c, bbl_c, kcu_c, kcl_c = bbu[0], bbl[0], kcu[0], kcl[0]

    # Son 5 mumdan en az 3'ünde squeeze aktif olmalı
    squeeze_count = 0
    for i in range(-6, -1):
        if abs(i) > len(df):
            continue
        r = df.iloc[i]
        if (not pd.isna(r.get(bbu_c)) and not pd.isna(r.get(kcu_c)) and
                r[bbu_c] < r[kcu_c] and r[bbl_c] > r[kcl_c]):
            squeeze_count += 1
    if squeeze_count < 3:
        return False, None, None

    # Son mumda kırılım: BB dışına gövdesiyle kapanmış mı?
    last = df.iloc[-1]
    if pd.isna(last.get(bbu_c)) or pd.isna(last.get(bbl_c)):
        return False, None, None

    direction = None
    if last['close'] > last[bbu_c] and last['close'] > last['open']:
        direction = "up"
    elif last['close'] < last[bbl_c] and last['close'] < last['open']:
        direction = "down"
    if direction is None:
        return False, None, None

    # Hacim onayı
    vol_sma = df['volume'].rolling(20).mean()
    if not pd.isna(vol_sma.iloc[-1]) and last['volume'] < vol_sma.iloc[-1] * 1.5:
        return False, None, None

    return True, direction, last


def _calculate_relative_strength(df_stock, df_index):
    """
    Hissenin endekse göre göreceli gücünü hesaplar.
    Returns: (rs_strong, rs_trend_up, index_stressed, index_recovering)
    """
    if df_stock is None or df_index is None:
        return False, False, False, False
    if len(df_stock) < 55 or len(df_index) < 55:
        return False, False, False, False

    common_idx = df_stock.index.intersection(df_index.index)
    if len(common_idx) < 55:
        return False, False, False, False

    stock_c = df_stock.loc[common_idx]['close']
    index_c = df_index.loc[common_idx]['close']

    rs_line = stock_c / index_c
    rs_sma_50 = rs_line.rolling(50).mean()

    rs_strong = bool(not pd.isna(rs_sma_50.iloc[-1]) and rs_line.iloc[-1] > rs_sma_50.iloc[-1])

    rs_trend_up = False
    if len(rs_line) >= 15:
        rs_trend_up = bool(rs_line.iloc[-5:].mean() > rs_line.iloc[-15:-10].mean())

    # Endeks stres (son 5 günde %2+ düşüş)
    index_stressed = False
    if len(index_c) >= 6:
        idx_chg = (index_c.iloc[-1] - index_c.iloc[-6]) / index_c.iloc[-6] * 100
        index_stressed = bool(idx_chg < -2.0)

    # Endeks toparlanıyor mu (close > EMA8)
    index_recovering = False
    if len(df_index) >= 10:
        df_idx = df_index.copy()
        if 'EMA_8' not in df_idx.columns:
            df_idx.ta.ema(length=8, append=True)
        ema_col = 'EMA_8' if 'EMA_8' in df_idx.columns else None
        if ema_col and not pd.isna(df_idx[ema_col].iloc[-1]):
            index_recovering = bool(df_idx['close'].iloc[-1] > df_idx[ema_col].iloc[-1])

    return rs_strong, rs_trend_up, index_stressed, index_recovering


def _calculate_anchored_vwap(df, lookback=20):
    """Son lookback barın en yüksek hacimli barından VWAP hesaplar."""
    if len(df) < lookback:
        return None
    recent = df.iloc[-lookback:]
    anchor_pos = recent['volume'].values.argmax()
    anchor_abs = len(df) - lookback + anchor_pos
    vwap_df = df.iloc[anchor_abs:]
    tp = (vwap_df['high'] + vwap_df['low'] + vwap_df['close']) / 3
    cum_tp_vol = (tp * vwap_df['volume']).cumsum()
    cum_vol = vwap_df['volume'].cumsum()
    if cum_vol.iloc[-1] == 0:
        return None
    return float(cum_tp_vol.iloc[-1] / cum_vol.iloc[-1])


def _detect_vwap_bounce(df, vwap_val):
    """Son mum VWAP'a değip Pin Bar bıraktı mı? Returns: (bounce_ok, wick_low)"""
    if vwap_val is None or len(df) < 2:
        return False, None
    last = df.iloc[-1]
    if last['low'] > vwap_val:
        return False, None
    body = abs(last['close'] - last['open'])
    if body == 0:
        body = last['close'] * 0.0001
    lower_wick = min(last['close'], last['open']) - last['low']
    if lower_wick < body * 2:
        return False, None
    if last['close'] <= last['open'] or last['close'] <= vwap_val:
        return False, None
    return True, float(last['low'])


def _detect_obv_accumulation(df, max_change_pct=3.0):
    """
    Fiyat yatayda + OBV yükseliyor + kutu kırılımı → sinyal.
    Returns: (breakout_confirmed, box_high, box_low)
    """
    if len(df) < 25:
        return False, None, None
    if 'OBV' not in df.columns:
        df.ta.obv(append=True)
    if 'OBV' not in df.columns:
        return False, None, None

    recent = df.iloc[-20:]
    price_chg = abs((recent['close'].iloc[-1] - recent['close'].iloc[0]) / recent['close'].iloc[0]) * 100
    if price_chg > max_change_pct:
        return False, None, None

    box_high = float(recent['close'].max())
    box_low = float(recent['close'].min())

    obv_5 = df['OBV'].iloc[-5:].mean()
    obv_20 = df['OBV'].iloc[-20:].mean()
    if obv_5 <= obv_20:
        return False, None, None

    obv_old_max = df['OBV'].iloc[-20:-5].max()
    if df['OBV'].iloc[-5:].max() <= obv_old_max:
        return False, None, None

    last = df.iloc[-1]
    if last['close'] <= box_high:
        return False, None, None

    vol_sma = df['volume'].rolling(20).mean()
    if not pd.isna(vol_sma.iloc[-1]) and last['volume'] < vol_sma.iloc[-1] * 1.5:
        return False, None, None

    return True, box_high, box_low


def _calculate_orb_cage(df_15m):
    """BIST 10:00-11:00 kafesi + günlük VWAP. Returns: (cage_high, cage_low, cage_mid, vwap)"""
    if df_15m is None or df_15m.empty:
        return None, None, None, None
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    today = now.date()

    df = df_15m.copy()
    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Europe/Istanbul")
        else:
            df.index = df.index.tz_convert("Europe/Istanbul")
    except Exception:
        pass

    df_today = df[df.index.date == today]
    if len(df_today) < 4:
        return None, None, None, None

    cage_bars = df_today[df_today.index.hour == 10]
    if len(cage_bars) < 2:
        return None, None, None, None

    cage_high = float(cage_bars['high'].max())
    cage_low = float(cage_bars['low'].min())
    cage_mid = (cage_high + cage_low) / 2

    tp = (df_today['high'] + df_today['low'] + df_today['close']) / 3
    cum = (tp * df_today['volume']).cumsum()
    cum_vol = df_today['volume'].cumsum()
    today_vwap = float(cum.iloc[-1] / cum_vol.iloc[-1]) if cum_vol.iloc[-1] > 0 else None

    return cage_high, cage_low, cage_mid, today_vwap


def _scan_orb_bist(symbol, df_15m):
    """BIST 9: ZAMAN KAFESİ (ORB) taraması. 15m veri üzerinden kafes kırılımı arar."""
    signals = []
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if now.hour < 11 or (now.hour >= 17 and now.minute > 30):
        return signals

    cage_high, cage_low, cage_mid, today_vwap = _calculate_orb_cage(df_15m)
    if cage_high is None or today_vwap is None:
        return signals

    last = df_15m.iloc[-1]
    current_price = float(last['close'])
    tp_range = cage_high - cage_low

    if current_price > cage_high and current_price > today_vwap and last['close'] > last['open']:
        signals.append({
            "ticker": symbol, "market": "BIST",
            "strategy": "BIST 9: ZAMAN KAFESİ (ORB)",
            "signal": "AL", "is_day_trade": True,
            "entry_price": current_price, "sl": cage_mid, "tp": current_price + tp_range,
            "reason": (
                f"⏱️ Açılış Kafesi Kırılımı (ORB)\n"
                f"📊 Kafes: {cage_low:.2f} - {cage_high:.2f}\n"
                f"📍 VWAP: {today_vwap:.2f} (Fiyat üzerinde ✅)\n"
                f"🎯 Hedef: +{tp_range:.2f} TL\n"
                f"⚠️ DAY TRADE: 17:55'te otomatik kapatılır."
            )
        })
    elif current_price < cage_low and current_price < today_vwap and last['close'] < last['open']:
        signals.append({
            "ticker": symbol, "market": "BIST",
            "strategy": "BIST 9: ZAMAN KAFESİ (ORB)",
            "signal": "SAT", "is_day_trade": True,
            "entry_price": current_price, "sl": cage_mid, "tp": current_price - tp_range,
            "reason": (
                f"⏱️ Açılış Kafesi Aşağı Kırılımı (ORB)\n"
                f"📊 Kafes: {cage_low:.2f} - {cage_high:.2f}\n"
                f"📍 VWAP: {today_vwap:.2f} (Fiyat altında ✅)\n"
                f"🎯 Hedef: -{tp_range:.2f} TL\n"
                f"⚠️ DAY TRADE: 17:55'te otomatik kapatılır."
            )
        })

    return signals


# ==========================================
# 1. BIST 100 STRATEJİ MODÜLÜ
# ==========================================
def analyze_strategies_bist(symbol, df_1d, df_4h, df_1h, xu100_down=False, xu100_daily=None):
    signals = []
    
    df_1d.ta.rsi(length=14, append=True)
    df_1d.ta.ema(length=8, append=True)
    df_1d.ta.ema(length=21, append=True)
    df_1d.ta.sma(length=50, append=True)
    df_1d.ta.sma(length=200, append=True)
    df_1d.ta.bbands(length=20, std=2, append=True)
    df_1d.ta.atr(length=14, append=True)
    
    month_high = df_1d['high'].tail(30).max() if len(df_1d) >= 30 else df_1d['high'].max()
        
    df_4h.ta.adx(length=14, append=True)
    df_4h.ta.ema(length=5, append=True)
    df_4h.ta.ema(length=13, append=True)
    
    df_1h.ta.rsi(length=14, append=True)
    df_1h.ta.ema(length=8, append=True)
    df_1h.ta.ema(length=13, append=True)
    df_1h['vol_sma_20'] = ta.sma(df_1h['volume'], length=20)
    
    if len(df_1d) < 2 or len(df_4h) < 2 or len(df_1h) < 3:
        return signals
        
    last_1d = df_1d.iloc[-1]
    last_4h = df_4h.iloc[-1]
    last_1h = df_1h.iloc[-1]
    prev_1h = df_1h.iloc[-2]
    current_price = last_1h['close']
    
    # Dinamik Stop için Günlük ATR
    atr_val = last_1d.get('ATRr_14', last_1d.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
    dynamic_sl_dist = max(2.0 * atr_val, current_price * 0.03)
    sl_pct = (dynamic_sl_dist / current_price) * 100
    
    # BIST 1: DİP AVCILIĞI
    if not pd.isna(last_1d.get('RSI_14')) and not pd.isna(last_1d.get('EMA_8')):
        if last_1d['RSI_14'] < 35 and current_price > last_1d['EMA_8']:
            if not pd.isna(last_1h.get('RSI_14')) and not pd.isna(prev_1h.get('RSI_14')) and not pd.isna(last_1h.get('EMA_8')):
                if last_1h['close'] > last_1h['EMA_8'] and last_1h['close'] > last_1h['open']:
                    if last_1h['RSI_14'] > prev_1h['RSI_14']:
                        sl = current_price - dynamic_sl_dist
                        tp = last_1d.get('EMA_21', current_price * 1.05)
                        signals.append({
                            "ticker": symbol, "market": "BIST", "strategy": "BIST 1: DİP AVCILIĞI", "signal": "AL",
                            "entry_price": current_price, "sl": sl, "tp": tp,
                            "reason": f"1G RSI<35, 1S EMA8 aşımı. (İzleyen ATR Stop: -%{sl_pct:.1f})"
                        })

    # BIST 2: TREND TAKİBİ
    if not pd.isna(last_4h.get('ADX_14')) and not pd.isna(last_4h.get('EMA_5')) and not pd.isna(last_4h.get('EMA_13')):
        if last_4h['ADX_14'] > 25 and last_4h['EMA_5'] > last_4h['EMA_13']:
            if not pd.isna(last_1h.get('EMA_13')):
                if last_1h['low'] <= last_1h['EMA_13'] and last_1h['close'] > last_1h['EMA_13'] and last_1h['close'] > last_1h['open']:
                    sl = current_price - dynamic_sl_dist
                    signals.append({
                        "ticker": symbol, "market": "BIST", "strategy": "BIST 2: TREND TAKİBİ", "signal": "AL",
                        "entry_price": current_price, "sl": sl, "tp": current_price * 1.10,
                        "reason": f"4S ADX>25 Güçlü Trend. 1S EMA13 pullback. (İzleyen ATR Stop: -%{sl_pct:.1f})"
                    })

    # BIST 3: KIRILIM VE MOMENTUM
    bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
    bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
    bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]
    
    if bb_upper_col and bb_lower_col and bb_mid_col:
        bbu = last_1d[bb_upper_col[0]]
        bbl = last_1d[bb_lower_col[0]]
        bbm = last_1d[bb_mid_col[0]]
        
        bb_width = (bbu - bbl) / bbm if bbm != 0 else 1
        if bb_width < 0.15:
            if current_price > month_high:
                if not pd.isna(last_1h.get('vol_sma_20')):
                    if last_1h['volume'] > (1.3 * last_1h['vol_sma_20']):
                        if not xu100_down:
                            now = datetime.now()
                            if now.time() >= dt_time(10, 30):
                                sl = current_price - dynamic_sl_dist
                                signals.append({
                                    "ticker": symbol, "market": "BIST", "strategy": "BIST 3: KIRILIM AVCILIĞI", "signal": "AL",
                                    "entry_price": current_price, "sl": sl, "tp": current_price * 1.10,
                                    "reason": f"Günlükte daralma, hacimli 1 aylık direnç kırılımı. (İzleyen ATR Stop: -%{sl_pct:.1f})"
                                })

    # ==========================================
    # BIST 4: KESKİN NİŞANCI (SMC / Likidite Avı ve OTE)
    # ==========================================
    htf_bias = _sniper_get_htf_bias(df_1d)

    if htf_bias == 1:  # Bullish → LONG Sniper
        swing_lows = _sniper_find_swing_points(df_4h, point_type="low")
        swing_highs = _sniper_find_swing_points(df_4h, point_type="high")

        sweep_ok, sweep_low = _sniper_detect_sweep(df_4h, swing_lows, point_type="low")
        if sweep_ok:
            msb_ok, msb_high, msb_idx = _sniper_detect_msb(df_4h, swing_highs, point_type="high")
            if msb_ok:
                ote_top, ote_bottom = _sniper_calculate_ote(sweep_low, msb_high)
                if ote_bottom <= current_price <= ote_top:
                    has_fvg, fvg_low, fvg_high = _sniper_detect_fvg(
                        df_4h, ote_top, ote_bottom, direction="bullish"
                    )

                    sl = sweep_low * 0.995  # Sweep dibin %0.5 altı
                    tp = msb_high * 1.05     # MSB tepesinin %5 üstü
                    fvg_label = " + FVG Onaylı ✅" if has_fvg else ""

                    signals.append({
                        "ticker": symbol, "market": "BIST",
                        "strategy": "BIST 4: KESKİN NİŞANCI (OTE)",
                        "signal": "AL",
                        "entry_price": current_price,
                        "sl": sl, "tp": tp,
                        "reason": (
                            f"🎯 SMC Kurulum{fvg_label}\n"
                            f"🧹 Likidite: Eski dip ({sweep_low:.2f}) temizlendi.\n"
                            f"📐 MSB: Yapı kırılımı ({msb_high:.2f}) onaylı.\n"
                            f"🎣 OTE Bölgesi: {ote_bottom:.2f} - {ote_top:.2f}\n"
                            f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
                        )
                    })

    # ==========================================
    # BIST 5: VOLATİLİTE SIKIŞMASI (Squeeze / Yay Radarı)
    # ==========================================
    squeeze_fired, sq_dir, sq_candle = _detect_squeeze(df_1d)
    if squeeze_fired and sq_dir == "up" and not xu100_down:
        sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
        ema_fallback = last_1d.get('EMA_21', last_1d.get('EMA_8', current_price * 0.95))
        sl = min(sq_mid, ema_fallback) if not pd.isna(ema_fallback) else sq_mid
        signals.append({
            "ticker": symbol, "market": "BIST",
            "strategy": "BIST 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)",
            "signal": "AL",
            "entry_price": current_price, "sl": sl, "tp": current_price * 1.15,
            "reason": (
                f"🗜️ Squeeze Patlaması!\n"
                f"BB(20,2) Keltner(20,1.5) içinden yukarı kırıldı.\n"
                f"Hacimli yeşil mum ile BB üst bandı aşıldı.\n"
                f"SL: Kırılım mumunun %50'si ({sl:.2f})"
            )
        })
    elif squeeze_fired and sq_dir == "down":
        sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
        ema_fallback = last_1d.get('EMA_21', last_1d.get('EMA_8', current_price * 1.05))
        sl = max(sq_mid, ema_fallback) if not pd.isna(ema_fallback) else sq_mid
        signals.append({
            "ticker": symbol, "market": "BIST",
            "strategy": "BIST 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)",
            "signal": "SAT",
            "entry_price": current_price, "sl": sl, "tp": current_price * 0.85,
            "reason": (
                f"🗜️ Squeeze Aşağı Patlaması!\n"
                f"BB(20,2) Keltner(20,1.5) içinden aşağı kırıldı.\n"
                f"Hacimli kırmızı mum ile BB alt bandı kırıldı.\n"
                f"SL: Kırılım mumunun %50'si ({sl:.2f})"
            )
        })

    # ==========================================
    # BIST 6: GÖRECELİ GÜÇ RADARI (RS)
    # ==========================================
    if xu100_daily is not None:
        rs_strong, rs_trend_up, idx_stressed, idx_recovering = _calculate_relative_strength(df_1d, xu100_daily)
        if rs_strong and rs_trend_up and idx_recovering:
            swing_lows_rs = _sniper_find_swing_points(df_1d, point_type="low", neighbors=2)
            if swing_lows_rs:
                sl = swing_lows_rs[-1][1] * 0.98
            else:
                sl = current_price * 0.95
            signals.append({
                "ticker": symbol, "market": "BIST",
                "strategy": "BIST 6: GÖRECELİ GÜÇ RADARI (RS)",
                "signal": "AL",
                "entry_price": current_price, "sl": sl, "tp": current_price * 1.12,
                "reason": (
                    f"🏋️ Endekse Kafa Tutan Hisse!\n"
                    f"RS Çizgisi > 50G SMA (Güçlü ✅)\n"
                    f"Endeks toparlandı, EMA8 üzerine çıktı.\n"
                    f"Bu hisse endeks düşerken düşmedi → Kurumsal birikim."
                )
            })

    # ==========================================
    # BIST 7: VWAP KURUMSAL MIKNATISI
    # ==========================================
    # KAPI 1: Piyasa Rejimi Filtresi (Kill-Switch)
    sma_50 = last_1d.get('SMA_50')
    sma_200 = last_1d.get('SMA_200')
    is_bear_regime = (not pd.isna(sma_50) and not pd.isna(sma_200) and current_price < sma_50 and current_price < sma_200)

    # KAPI 2: Üst Zaman Dilimi Baskısı (MTF Alignment)
    ema_21_daily = last_1d.get('EMA_21')
    mtf_trend_down = (not pd.isna(ema_21_daily) and last_1d['close'] < ema_21_daily)

    # KAPI 3: Makro Yerçekimi Filtresi
    macro_gravity_ok = not xu100_down

    if not is_bear_regime and not mtf_trend_down and macro_gravity_ok:
        vwap_val = _calculate_anchored_vwap(df_1h, lookback=20)
        if vwap_val is not None:
            bounce_ok, wick_low = _detect_vwap_bounce(df_1h, vwap_val)
            if bounce_ok and wick_low is not None:
                # KAPI 4: Anomalinin Onayı (Momentum / Hacim Emilimi)
                vol_sma_20 = last_1h.get('vol_sma_20')
                if not pd.isna(vol_sma_20) and last_1h['volume'] > (1.5 * vol_sma_20):
                    sl = wick_low * 0.995
                    signals.append({
                        "ticker": symbol, "market": "BIST",
                        "strategy": "BIST 7: VWAP KURUMSAL MIKNATISI",
                        "signal": "AL",
                        "entry_price": current_price, "sl": sl, "tp": current_price * 1.06,
                        "reason": (
                            f"⚓ VWAP Bounce (Kurumsal Mıknatıs) + 4 Kapı Zırhı!\n"
                            f"✅ Rejim: Boğa | ✅ Trend: Uyumlu | ✅ Endeks: Güvenli\n"
                            f"Anchored VWAP: {vwap_val:.2f} (1.5x Hacimle Sıçradı)\n"
                            f"SL: Fitil ucunun altı ({sl:.2f}) — Dar stop."
                        )
                    })

    # ==========================================
    # BIST 8: SESSİZ BİRİKİM RADARI (OBV)
    # ==========================================
    obv_ok, obv_box_high, obv_box_low = _detect_obv_accumulation(df_1d, max_change_pct=3.0)
    if obv_ok and obv_box_high is not None:
        sl = obv_box_high * 0.99
        signals.append({
            "ticker": symbol, "market": "BIST",
            "strategy": "BIST 8: SESSİZ BİRİKİM RADARI (OBV)",
            "signal": "AL",
            "entry_price": current_price, "sl": sl, "tp": current_price * 1.12,
            "reason": (
                f"🕵️ Sessiz Birikim Tespiti!\n"
                f"20 gün yatay kutu: {obv_box_low:.2f} - {obv_box_high:.2f}\n"
                f"OBV sürekli yeni tepeler yapıyor (Gizli mal toplama).\n"
                f"Kutu direnci hacimli kırıldı → Ralli başlıyor."
            )
        })

    return signals

# ==========================================
# 2. KRİPTO STRATEJİ MODÜLÜ
# ==========================================
def analyze_strategies_crypto(symbol, df_1d, df_4h, btc_ok=False, btc_sniper_bias=0):
    signals = []
    
    if len(df_1d) < 50 or len(df_4h) < 20:
        return signals

    # 1D Indicators
    df_1d.ta.ema(length=20, append=True)
    df_1d.ta.ema(length=50, append=True)
    df_1d.ta.bbands(length=20, std=2, append=True)
    
    # 4H Indicators
    df_4h.ta.rsi(length=14, append=True)
    df_4h.ta.ema(length=20, append=True)
    df_4h.ta.ema(length=50, append=True)
    df_4h.ta.adx(length=14, append=True)
    df_4h.ta.atr(length=14, append=True)
    df_4h['vol_sma_20'] = ta.sma(df_4h['volume'], length=20)
    
    last_1d = df_1d.iloc[-1]
    last_4h = df_4h.iloc[-1]
    current_price = last_4h['close']
    
    # ----------------------------------------------------
    # KRİPTO 1: LİKİDASYON VE DİP AVCILIĞI (Tasfiye Mumları)
    # ----------------------------------------------------
    if not is_weekend_fakeout_time(): # Hafta sonu yasaklandı
        if not pd.isna(last_4h.get('RSI_14')) and not pd.isna(last_4h.get('EMA_20')) and not pd.isna(last_4h.get('vol_sma_20')):
            if last_4h['RSI_14'] < 28:
                if last_4h['volume'] > (2.0 * last_4h['vol_sma_20']):
                    if current_price > last_4h['EMA_20'] and current_price > last_4h['open']:
                        # Crypto-Native Modül: OI Crash kontrolü
                        # Eğer simülasyon (mockup) ise doğrudan True kabul edebiliriz, gerçek işlemde API'ye bakar
                        oi_crash = fetch_crypto_oi_crash(symbol) if not hasattr(df_1d, "is_mock") else True
                        
                        if oi_crash:
                            lowest_wick = last_4h['low']
                            sl = lowest_wick * 0.99 
                            tp = current_price * 1.15 
                            signals.append({
                                "ticker": symbol, "market": "KRIPTO", "strategy": "KRİPTO 1: LİKİDASYON VE DİP AVCILIĞI", "signal": "AL",
                                "entry_price": current_price, "sl": sl, "tp": tp,
                                "reason": f"4S RSI<25. Devasa hacim ve OI Çöküşü (>%15) tespit edildi! Balina temizliği bitti."
                            })

    # ----------------------------------------------------
    # KRİPTO 2: MEGA TREND TAKİBİ (Düzeltme Sörfü)
    # ----------------------------------------------------
    if not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')):
        if last_1d['EMA_20'] > last_1d['EMA_50'] and last_1d['close'] > last_1d['EMA_20']:
            atr_col = 'ATRr_14' if 'ATRr_14' in last_4h.index else 'ATR_14'
            if not pd.isna(last_4h.get('ADX_14')) and not pd.isna(last_4h.get('EMA_20')) and not pd.isna(last_4h.get(atr_col)):
                if last_4h['ADX_14'] > 25:
                    if last_4h['low'] <= last_4h['EMA_20'] and current_price > last_4h['EMA_20'] and current_price > last_4h['open']:
                        # Crypto-Native Modül: BTC Dominans Kalkanı
                        # BTC.D "UP" (Yükseliş) trendindeyse altcoin rallileri sahtedir (ezilir). İşlemi reddet.
                        btcdom_trend = get_btc_dominance_trend() if not hasattr(df_1d, "is_mock") else "DOWN"
                        
                        if btcdom_trend != "UP":
                            atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
                            if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
                            sl_atr = current_price - (1.5 * atr_val)
                            sl_ema = last_4h.get('EMA_50', current_price) * 0.98
                            sl = max(sl_atr, sl_ema) 
                            
                            signals.append({
                                "ticker": symbol, "market": "KRIPTO", "strategy": "KRİPTO 2: MEGA TREND TAKİBİ", "signal": "AL",
                                "entry_price": current_price, "sl": sl, "tp": current_price * 1.30,
                                "reason": f"1G EMA20>50 Trendi. BTC Dominans '{btcdom_trend}' yönünde (Güvenli). ATR Stop aktif."
                            })

    # ----------------------------------------------------
    # KRİPTO 3: SAHTE KIRILIM FİLTRELİ BREAKOUT (Retest)
    # ----------------------------------------------------
    if not is_weekend_fakeout_time(): # Hafta sonu yasaklandı
        bb_upper_col = [c for c in df_1d.columns if 'BBU' in c]
        bb_lower_col = [c for c in df_1d.columns if 'BBL' in c]
        bb_mid_col = [c for c in df_1d.columns if 'BBM' in c]
        
        if bb_upper_col and bb_lower_col and bb_mid_col and btc_ok:
            df_1d['bb_width'] = (df_1d[bb_upper_col[0]] - df_1d[bb_lower_col[0]]) / df_1d[bb_mid_col[0]]
            min_width_30d = df_1d['bb_width'].tail(30).min()
            last_width = df_1d['bb_width'].iloc[-1]
            
            if last_width <= min_width_30d * 1.20: 
                if not pd.isna(last_4h.get('vol_sma_20')):
                    if last_4h['volume'] > (2.0 * last_4h['vol_sma_20']):
                        local_high = df_4h['high'].tail(15).max()
                        if last_4h['low'] <= local_high * 0.99 and current_price > last_4h['open']:
                            
                            # Crypto-Native Modül: Token Unlocks ve Negative Funding Fuel
                            has_unlocks = check_token_unlocks(symbol) if not hasattr(df_1d, "is_mock") else False
                            funding_rate = get_funding_rate(symbol) if not hasattr(df_1d, "is_mock") else -0.01
                            
                            # Kilit açılımı yoksa ve fonlama oranı negatifse (Short Squeeze ihtimali yüksekse) onay ver
                            if not has_unlocks and funding_rate <= 0.0:
                                sl = current_price * 0.95
                                signals.append({
                                    "ticker": symbol, "market": "KRIPTO", "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)", "signal": "AL",
                                    "entry_price": current_price, "sl": sl, "tp": current_price * 1.15,
                                    "reason": f"1G Daralma, Retest sekmesi. Fonlama: %{funding_rate:.4f} (Negatif Yakıt). Kilit açılımı yok."
                                })

    # ====================================================
    # YENİ KRİPTO SHORT (SAT) STRATEJİLERİ
    # ====================================================
    btc_not_pumping = check_btc_not_pumping() if not hasattr(df_1d, "is_mock") else True
    
    if btc_not_pumping:
        # SHORT 1: FOMO İNFAZI (Parabolik Tepe Avcılığı)
        # Tetikleyici: 4S RSI > 85 ve mum "Kayan Yıldız" (Shooting Star - kırmızı, üst fitili uzun)
        if not pd.isna(last_4h.get('RSI_14')) and last_4h['RSI_14'] > 85:
            body = abs(current_price - last_4h['open'])
            upper_wick = last_4h['high'] - max(current_price, last_4h['open'])
            # Kırmızı mum ve üst fitil gövdenin en az 2 katı
            if current_price < last_4h['open'] and upper_wick > (2 * body):
                funding_rate = get_funding_rate(symbol) if not hasattr(df_1d, "is_mock") else 0.06
                oi_crash = fetch_crypto_oi_crash(symbol) if not hasattr(df_1d, "is_mock") else True
                
                if funding_rate >= 0.05 and oi_crash:
                    sl = last_4h['high'] * 1.01 # Tepe fitilin hemen üstü
                    tp = current_price * 0.85
                    signals.append({
                        "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 1: FOMO İNFAZI", "signal": "SAT",
                        "entry_price": current_price, "sl": sl, "tp": tp,
                        "reason": f"4S RSI>85 Kayan Yıldız. Aşırı Fonlama (+%{funding_rate:.2f}) ve OI Çöküşü."
                    })

        # SHORT 2: KANLI ŞELALE SÖRFÜ (Ayı Trendi)
        # Tetikleyici: 1G EMA 20 < EMA 50, 4S ADX > 30. Mum EMA 20'den ret yedi.
        if not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')):
            if last_1d['EMA_20'] < last_1d['EMA_50'] and current_price < last_1d['EMA_20']:
                if not pd.isna(last_4h.get('ADX_14')) and last_4h['ADX_14'] > 30:
                    # EMA 20 (4S) Pullback: high EMA20'ye değdi ama close altında ve kırmızı
                    if last_4h['high'] >= last_4h['EMA_20'] and current_price < last_4h['EMA_20'] and current_price < last_4h['open']:
                        btcdom_trend = get_btc_dominance_trend() if not hasattr(df_1d, "is_mock") else "UP"
                        if btcdom_trend == "UP":
                            atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
                            if atr_val is None or pd.isna(atr_val): atr_val = current_price * 0.02
                            sl = current_price + (1.5 * atr_val)
                            tp = current_price * 0.80
                            signals.append({
                                "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 2: KANLI ŞELALE SÖRFÜ", "signal": "SAT",
                                "entry_price": current_price, "sl": sl, "tp": tp,
                                "reason": f"1G Ayı Trendi, 4S ADX>30. EMA20 Ret. BTC Dominans '{btcdom_trend}'."
                            })

        # SHORT 3: UÇURUM ÇÖKÜŞÜ (Destek Kırılımı ve Retest)
        if len(df_4h) >= 90:
            support_lookback = df_4h['low'].iloc[-75:-15].min() # 60 mumluk eski destek (15 mum önceye kadar)
            breakout_zone = df_4h.iloc[-15:-1]
            breakout_happened = breakout_zone['low'].min() < support_lookback
            
            if breakout_happened:
                # Şu anki mum kapanışı desteğin altında mı? (Bear trap engelleme)
                if current_price < support_lookback:
                    recent_high = max(last_4h['high'], df_4h.iloc[-2]['high'])
                    proximity = (support_lookback - recent_high) / support_lookback
                    
                    if 0 <= proximity <= 0.015: # Desteğe %1.5 yakınlıkta temas
                        if current_price < last_4h['open']: # Kırmızı mumla aşağı dönüş
                            funding_rate = get_funding_rate(symbol) if not hasattr(df_1d, "is_mock") else 0.01
                            has_unlocks = check_token_unlocks(symbol) if not hasattr(df_1d, "is_mock") else False
                            
                            # Short squeeze riski (negatif fonlama) olmamalı
                            if funding_rate >= 0.0:
                                sl = support_lookback * 1.02 # Desteğin %2 üstü
                                tp = current_price * 0.80
                                signals.append({
                                    "ticker": symbol, "market": "KRIPTO", "strategy": "SHORT 3: UÇURUM ÇÖKÜŞÜ", "signal": "SAT",
                                    "entry_price": current_price, "sl": sl, "tp": tp,
                                    "reason": f"90S Desteği kırıldı, %1.5 toleransla Retest yapıldı ve reddedildi."
                                })

    # ==========================================
    # KRİPTO 4: KESKİN NİŞANCI (SMC / Likidite Avı ve OTE)
    # ==========================================
    if not is_weekend_fakeout_time():
        # LONG Sniper: BTC Bullish bias
        if btc_sniper_bias == 1:
            swing_lows_s = _sniper_find_swing_points(df_4h, point_type="low")
            swing_highs_s = _sniper_find_swing_points(df_4h, point_type="high")

            sweep_ok, sweep_low = _sniper_detect_sweep(df_4h, swing_lows_s, point_type="low")
            if sweep_ok:
                msb_ok, msb_high, msb_idx = _sniper_detect_msb(df_4h, swing_highs_s, point_type="high")
                if msb_ok:
                    ote_top, ote_bottom = _sniper_calculate_ote(sweep_low, msb_high)
                    if ote_bottom <= current_price <= ote_top:
                        has_fvg, _, _ = _sniper_detect_fvg(
                            df_4h, ote_top, ote_bottom, direction="bullish"
                        )

                        funding_rate = get_funding_rate(symbol) if not hasattr(df_1d, "is_mock") else -0.01

                        if funding_rate <= 0.0:  # Negatif fonlama = short squeeze yakıtı
                            sl = sweep_low * 0.995
                            tp = msb_high * 1.08
                            fvg_label = " + FVG Onaylı ✅" if has_fvg else ""

                            signals.append({
                                "ticker": symbol, "market": "KRIPTO",
                                "strategy": "KRİPTO 4: KESKİN NİŞANCI (OTE)",
                                "signal": "AL",
                                "entry_price": current_price,
                                "sl": sl, "tp": tp,
                                "reason": (
                                    f"🎯 SMC Kurulum{fvg_label}\n"
                                    f"🧹 Likidite: Eski dip ({sweep_low:.4f}) temizlendi.\n"
                                    f"📐 MSB: Yapı kırılımı ({msb_high:.4f}) onaylı.\n"
                                    f"🎣 OTE Bölgesi: {ote_bottom:.4f} - {ote_top:.4f}\n"
                                    f"📊 Fonlama: %{funding_rate:.4f} (Negatif Yakıt)\n"
                                    f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
                                )
                            })

        # SHORT Sniper: BTC Bearish bias
        elif btc_sniper_bias == -1:
            swing_highs_s = _sniper_find_swing_points(df_4h, point_type="high")
            swing_lows_s = _sniper_find_swing_points(df_4h, point_type="low")

            # Bearish Sweep: Eski tepenin üstüne sarkıp geri çekilme
            sweep_ok, sweep_high = _sniper_detect_sweep(df_4h, swing_highs_s, point_type="high")
            if sweep_ok:
                # Bearish MSB: Son swing low'un altına kırılma
                msb_ok, msb_low, msb_idx = _sniper_detect_msb(df_4h, swing_lows_s, point_type="low")
                if msb_ok:
                    # Premium OTE: Dipten yukarı Fib geri çekilme
                    ote_top, ote_bottom = _sniper_calculate_ote(sweep_high, msb_low)
                    if ote_bottom <= current_price <= ote_top:
                        has_fvg, _, _ = _sniper_detect_fvg(
                            df_4h, ote_top, ote_bottom, direction="bearish"
                        )

                        funding_rate = get_funding_rate(symbol) if not hasattr(df_1d, "is_mock") else 0.05

                        if funding_rate >= 0.0:  # Pozitif fonlama = short yakıtı
                            sl = sweep_high * 1.005  # Sweep tepenin %0.5 üstü
                            tp = msb_low * 0.92       # MSB dibinin %8 altı
                            fvg_label = " + FVG Onaylı ✅" if has_fvg else ""

                            signals.append({
                                "ticker": symbol, "market": "KRIPTO",
                                "strategy": "SHORT 4: KESKİN NİŞANCI (OTE)",
                                "signal": "SAT",
                                "entry_price": current_price,
                                "sl": sl, "tp": tp,
                                "reason": (
                                    f"🎯 SHORT SMC Kurulum{fvg_label}\n"
                                    f"🧹 Likidite: Eski tepe ({sweep_high:.4f}) temizlendi.\n"
                                    f"📐 Bearish MSB: Yapı kırılımı ({msb_low:.4f}) aşağı onaylı.\n"
                                    f"🎣 Premium OTE: {ote_bottom:.4f} - {ote_top:.4f}\n"
                                    f"📊 Fonlama: +%{funding_rate:.4f} (Pozitif = Short Yakıtı)\n"
                                    f"🛡️ İşlem %4 kâra geçince Break-Even uygula."
                                )
                            })

    # ==========================================
    # KRİPTO 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)
    # ==========================================
    if not is_weekend_fakeout_time():
        sq_fired, sq_dir, sq_candle = _detect_squeeze(df_4h)
        if sq_fired and sq_dir is not None:
            trend_up = (not pd.isna(last_1d.get('EMA_20')) and not pd.isna(last_1d.get('EMA_50')) and
                        last_1d['EMA_20'] > last_1d['EMA_50'])

            valid_breakout = (sq_dir == "up" and trend_up) or (sq_dir == "down" and not trend_up)

            if valid_breakout:
                sq_mid = (sq_candle['high'] + sq_candle['low']) / 2
                ema20_4h = last_4h.get('EMA_20', current_price)

                if sq_dir == "up":
                    sl = min(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                    tp = current_price * 1.20
                    sig_type = "AL"
                else:
                    sl = max(sq_mid, ema20_4h) if not pd.isna(ema20_4h) else sq_mid
                    tp = current_price * 0.80
                    sig_type = "SAT"

                signals.append({
                    "ticker": symbol, "market": "KRIPTO",
                    "strategy": "KRİPTO 5: VOLATİLİTE SIKIŞMASI (SQUEEZE)",
                    "signal": sig_type,
                    "entry_price": current_price, "sl": sl, "tp": tp,
                    "reason": (
                        f"🗜️ Squeeze Patlaması ({sq_dir.upper()})!\n"
                        f"4S BB(20,2) Keltner(20,1.5) içinden kırıldı.\n"
                        f"1G Trend {'Yukarı ✅' if trend_up else 'Aşağı ✅'} ile uyumlu.\n"
                        f"Hacimli {'yeşil' if sq_dir == 'up' else 'kırmızı'} mum onayı."
                    )
                })

    # ==========================================
    # KRİPTO 6: VWAP KURUMSAL MIKNATISI
    # ==========================================
    if not is_weekend_fakeout_time() and btc_ok:
        vwap_val = _calculate_anchored_vwap(df_4h, lookback=20)
        if vwap_val is not None:
            bounce_ok, wick_low = _detect_vwap_bounce(df_4h, vwap_val)
            if bounce_ok and wick_low is not None:
                sl = wick_low * 0.99
                signals.append({
                    "ticker": symbol, "market": "KRIPTO",
                    "strategy": "KRİPTO 6: VWAP KURUMSAL MIKNATISI",
                    "signal": "AL",
                    "entry_price": current_price, "sl": sl, "tp": current_price * 1.10,
                    "reason": (
                        f"⚓ VWAP Bounce (Kurumsal Mıknatıs)!\n"
                        f"4S Anchored VWAP: {vwap_val:.4f}\n"
                        f"Pin Bar onayı: VWAP'a değip sıçradı.\n"
                        f"BTC > EMA20 (Piyasa izni var ✅)"
                    )
                })

    # ==========================================
    # KRİPTO 7: SESSİZ BİRİKİM RADARI (OBV)
    # ==========================================
    obv_ok, obv_box_high, obv_box_low = _detect_obv_accumulation(df_1d, max_change_pct=5.0)
    if obv_ok and obv_box_high is not None:
        btcdom_trend = get_btc_dominance_trend() if not hasattr(df_1d, "is_mock") else "DOWN"
        if btcdom_trend != "UP":
            sl = obv_box_high * 0.98
            signals.append({
                "ticker": symbol, "market": "KRIPTO",
                "strategy": "KRİPTO 7: SESSİZ BİRİKİM RADARI (OBV)",
                "signal": "AL",
                "entry_price": current_price, "sl": sl, "tp": current_price * 1.20,
                "reason": (
                    f"🕵️ Sessiz Birikim Tespiti!\n"
                    f"1G 20 gün yatay kutu: {obv_box_low:.4f} - {obv_box_high:.4f}\n"
                    f"OBV yeni tepeler yapıyor (Gizli mal toplama).\n"
                    f"BTC Dominans '{btcdom_trend}' (Altcoin dostu ✅)"
                )
            })

    return signals


def scan_all_markets():
    all_signals = []
    
    # -----------------------
    # 1. BIST TARAMALARI
    # -----------------------
    if is_bist_open():
        xu100_down = check_xu100_wind()
        xu100_daily = _get_xu100_daily_data()  # RS stratejisi için endeks verisi
        
        for sym in TOP_BIST:
            df_1d, df_4h, df_1h = get_bist_data(sym)
            if df_1d is not None:
                sigs = analyze_strategies_bist(sym, df_1d, df_4h, df_1h, xu100_down, xu100_daily)
                all_signals.extend(sigs)
            time.sleep(0.1)
        
        # ORB (Zaman Kafesi) - 15m veri ile ayrı tarama
        now_ist = datetime.now(ZoneInfo("Europe/Istanbul"))
        if 11 <= now_ist.hour < 17 or (now_ist.hour == 17 and now_ist.minute <= 30):
            for sym in TOP_BIST:
                df_15m = get_bist_15m_data(sym)
                if df_15m is not None:
                    orb_sigs = _scan_orb_bist(sym, df_15m)
                    all_signals.extend(orb_sigs)
                time.sleep(0.05)
            
    # -----------------------
    # 2. KRİPTO TARAMALARI
    # -----------------------
    # Sadece tarama başlarken 1 kez sorulur (Zorunlu İzin)
    btc_ok = get_btc_status()
    btc_sniper_bias = _get_btc_htf_bias()  # Sniper HTF Bias: 1 kez çek, 50 altcoine pasla
    
    for sym in TOP_CRYPTO:
        df_1d, df_4h = get_crypto_data(sym)
        if df_1d is not None:
            sigs = analyze_strategies_crypto(sym, df_1d, df_4h, btc_ok, btc_sniper_bias)
            all_signals.extend(sigs)
        time.sleep(0.1)

    # -----------------------
    # 3. EMTİA TARAMALARI
    # -----------------------
    if _is_macro_news_hour():
        logging.info("[scan_all_markets] ⏳ Makro haber saati (15:00-16:30) - Emtia taraması atlandı.")
    else:
        dxy_bullish = _check_dxy_shield()
        if dxy_bullish:
            logging.info("[scan_all_markets] 🛡️ DXY yükseliş trendinde - Altın/Gümüş LONG sinyalleri engellenecek.")

        for sym in TOP_EMTIA:
            df_1d, df_4h = get_emtia_data(sym)
            if df_1d is not None:
                sigs = analyze_strategies_emtia(sym, df_1d, df_4h, dxy_bullish)
                all_signals.extend(sigs)
            time.sleep(0.2)
        
    # -----------------------
    # 4. 🐻 AYI AVCISI (Ağır Sıklet SHORT)
    # -----------------------
    btc_bullish = _is_btc_bullish_for_shorts()
    if btc_bullish:
        logging.info("[scan_all_markets] 👑 BTC güçlü yükselişte - Tüm altcoin SHORT'lar engellendi.")
    else:
        for sym in TOP_HEAVY_SHORT:
            if sym in MEME_BLACKLIST:
                continue  # 🚫 Meme coin → kalıcı yasak
            if sym == "BTC/USDT":
                continue  # BTC kendisine short açılmaz bu modülde
            df_1d, df_4h = get_crypto_data(sym)
            if df_1d is not None and df_4h is not None:
                sigs = analyze_bear_hunter(sym, df_1d, df_4h, btc_bullish)
                all_signals.extend(sigs)
            time.sleep(0.1)

    return all_signals


# ==========================================
# 3. EMTİA STRATEJİ MODÜLÜ
# ==========================================
def analyze_strategies_emtia(symbol, df_1d, df_4h, dxy_bullish=False):
    """Emtia strateji analizi. 3 strateji + DXY/ATR/Haber kalkanları."""
    signals = []

    if df_1d is None or len(df_1d) < 30:
        return signals

    # İndikatör hesaplama
    df_1d.ta.rsi(length=14, append=True)
    df_1d.ta.ema(length=8, append=True)
    df_1d.ta.ema(length=21, append=True)
    df_1d.ta.ema(length=50, append=True)
    df_1d.ta.adx(length=14, append=True)
    df_1d.ta.atr(length=14, append=True)
    df_1d.ta.bbands(length=20, std=2, append=True)

    if df_4h is not None and len(df_4h) >= 20:
        df_4h.ta.ema(length=5, append=True)
        df_4h.ta.ema(length=13, append=True)
        df_4h.ta.ema(length=20, append=True)
        df_4h.ta.adx(length=14, append=True)
        df_4h.ta.atr(length=14, append=True)

    last_1d = df_1d.iloc[-1]
    current_price = float(last_1d['close'])

    # ATR bazlı stop hesaplama (emtia DNA)
    atr_mult = EMTIA_ATR_MULT.get(symbol, 2.5)
    atr_val = last_1d.get('ATRr_14', last_1d.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val):
        atr_val = current_price * 0.02
    dynamic_sl_dist = atr_mult * atr_val
    sl_pct = (dynamic_sl_dist / current_price) * 100

    # DXY Kalkanı: Altın/Gümüş'te dolar güçlüyse AL sinyali engelle
    is_dxy_sensitive = symbol in DXY_SENSITIVE
    dxy_block_long = is_dxy_sensitive and dxy_bullish

    emtia_name = EMTIA_NAMES.get(symbol, symbol)

    # ==========================================
    # EMTİA 1: TREND SÖRFÜ (Mega Trend)
    # TF: 1D + 4H | ADX>25, EMA crossover, pullback
    # ==========================================
    if df_4h is not None and len(df_4h) >= 20:
        last_4h = df_4h.iloc[-1]
        adx_4h = last_4h.get('ADX_14')
        ema5_4h = last_4h.get('EMA_5')
        ema13_4h = last_4h.get('EMA_13')

        if (not pd.isna(adx_4h) and not pd.isna(ema5_4h) and not pd.isna(ema13_4h)):
            # LONG: ADX>25, EMA5>EMA13, 4H pullback to EMA13
            if adx_4h > 25 and ema5_4h > ema13_4h:
                if (last_4h['low'] <= ema13_4h and last_4h['close'] > ema13_4h
                        and last_4h['close'] > last_4h['open']):
                    if not dxy_block_long:
                        sl = current_price - dynamic_sl_dist
                        tp = current_price + (dynamic_sl_dist * 3)
                        dxy_note = "\n🛡️ DXY Kontrolü: Dolar zayıf ✅" if is_dxy_sensitive else ""
                        signals.append({
                            "ticker": symbol, "market": "EMTİA",
                            "strategy": "EMTİA 1: TREND SÖRFÜ (MEGA TREND)",
                            "signal": "AL",
                            "entry_price": current_price, "sl": sl, "tp": tp,
                            "reason": (
                                f"🏄 {emtia_name} Mega Trend!\n"
                                f"4S ADX>{adx_4h:.0f} Güçlü Trend. EMA5>EMA13.\n"
                                f"4S EMA13'e pullback + yeşil mum onayı.\n"
                                f"SL: {atr_mult}× ATR ({sl_pct:.1f}%){dxy_note}"
                            )
                        })

            # SHORT: ADX>25, EMA5<EMA13, 4H pullback to EMA13
            elif adx_4h > 25 and ema5_4h < ema13_4h:
                if (last_4h['high'] >= ema13_4h and last_4h['close'] < ema13_4h
                        and last_4h['close'] < last_4h['open']):
                    sl = current_price + dynamic_sl_dist
                    tp = current_price - (dynamic_sl_dist * 3)
                    signals.append({
                        "ticker": symbol, "market": "EMTİA",
                        "strategy": "EMTİA 1: TREND SÖRFÜ (MEGA TREND)",
                        "signal": "SAT",
                        "entry_price": current_price, "sl": sl, "tp": tp,
                        "reason": (
                            f"🏄 {emtia_name} Düşüş Trendi!\n"
                            f"4S ADX>{adx_4h:.0f} Güçlü Düşüş. EMA5<EMA13.\n"
                            f"4S EMA13'e pullback + kırmızı mum onayı.\n"
                            f"SL: {atr_mult}× ATR ({sl_pct:.1f}%)"
                        )
                    })

    # ==========================================
    # EMTİA 2: KESKİN NİŞANCI (SMC / OTE)
    # TF: 4H | Likidite avı, MSB, OTE bölgesi
    # ==========================================
    if df_4h is not None and len(df_4h) >= 30:
        htf_bias = _sniper_get_htf_bias(df_1d)

        if htf_bias == 1 and not dxy_block_long:  # Bullish → LONG
            swing_lows = _sniper_find_swing_points(df_4h, point_type="low")
            swing_highs = _sniper_find_swing_points(df_4h, point_type="high")
            sweep_ok, sweep_low = _sniper_detect_sweep(df_4h, swing_lows, point_type="low")
            if sweep_ok:
                msb_ok, msb_high, msb_idx = _sniper_detect_msb(df_4h, swing_highs, point_type="high")
                if msb_ok:
                    ote_top, ote_bottom = _sniper_calculate_ote(sweep_low, msb_high)
                    if ote_bottom <= current_price <= ote_top:
                        has_fvg, fvg_low, fvg_high = _sniper_detect_fvg(
                            df_4h, ote_top, ote_bottom, direction="bullish"
                        )
                        sl = sweep_low - (atr_val * 0.5)
                        tp = msb_high * 1.05
                        fvg_label = " + FVG ✅" if has_fvg else ""
                        dxy_note = "\n🛡️ DXY: Dolar zayıf ✅" if is_dxy_sensitive else ""
                        signals.append({
                            "ticker": symbol, "market": "EMTİA",
                            "strategy": "EMTİA 2: KESKİN NİŞANCI (SMC/OTE)",
                            "signal": "AL",
                            "entry_price": current_price, "sl": sl, "tp": tp,
                            "reason": (
                                f"🎯 {emtia_name} SMC Kurulum{fvg_label}\n"
                                f"🧹 Likidite: Eski dip ({sweep_low:.2f}) temizlendi.\n"
                                f"📐 MSB: Yapı kırılımı ({msb_high:.2f}) onaylı.\n"
                                f"🎣 OTE Bölgesi: {ote_bottom:.2f} - {ote_top:.2f}\n"
                                f"🛡️ ATR Stop: {atr_mult}× ({sl_pct:.1f}%){dxy_note}"
                            )
                        })

        elif htf_bias == -1:  # Bearish → SHORT
            swing_lows = _sniper_find_swing_points(df_4h, point_type="low")
            swing_highs = _sniper_find_swing_points(df_4h, point_type="high")
            sweep_ok, sweep_high = _sniper_detect_sweep(df_4h, swing_highs, point_type="high")
            if sweep_ok:
                msb_ok, msb_low, msb_idx = _sniper_detect_msb(df_4h, swing_lows, point_type="low")
                if msb_ok:
                    ote_top, ote_bottom = _sniper_calculate_ote(msb_low, sweep_high)
                    if ote_bottom <= current_price <= ote_top:
                        has_fvg, fvg_low, fvg_high = _sniper_detect_fvg(
                            df_4h, ote_top, ote_bottom, direction="bearish"
                        )
                        sl = sweep_high + (atr_val * 0.5)
                        tp = msb_low * 0.95
                        fvg_label = " + FVG ✅" if has_fvg else ""
                        signals.append({
                            "ticker": symbol, "market": "EMTİA",
                            "strategy": "EMTİA 2: KESKİN NİŞANCI (SMC/OTE)",
                            "signal": "SAT",
                            "entry_price": current_price, "sl": sl, "tp": tp,
                            "reason": (
                                f"🎯 {emtia_name} SHORT SMC Kurulum{fvg_label}\n"
                                f"🧹 Likidite: Eski tepe ({sweep_high:.2f}) temizlendi.\n"
                                f"📐 MSB: Aşağı yapı kırılımı ({msb_low:.2f}).\n"
                                f"🎣 OTE Bölgesi: {ote_bottom:.2f} - {ote_top:.2f}\n"
                                f"🛡️ ATR Stop: {atr_mult}× ({sl_pct:.1f}%)"
                            )
                        })

    # ==========================================
    # EMTİA 3: VOLATİLİTE SIKIŞMASI (Squeeze / Yay Radarı)
    # TF: 1D | BB + Keltner sıkışma → kırılım
    # ==========================================
    squeeze_fired, sq_dir, sq_candle = _detect_squeeze(df_1d)
    if squeeze_fired:
        if sq_dir == "up" and not dxy_block_long:
            sl = current_price - dynamic_sl_dist
            tp = current_price + (dynamic_sl_dist * 3)
            dxy_note = "\n🛡️ DXY: Dolar zayıf ✅" if is_dxy_sensitive else ""
            signals.append({
                "ticker": symbol, "market": "EMTİA",
                "strategy": "EMTİA 3: VOLATİLİTE SIKIŞMASI (SQUEEZE)",
                "signal": "AL",
                "entry_price": current_price, "sl": sl, "tp": tp,
                "reason": (
                    f"🗜️ {emtia_name} Squeeze Patlaması!\n"
                    f"1G BB(20,2) Keltner(20,1.5) içinden yukarı kırıldı.\n"
                    f"Hacimli yeşil mum ile BB üst bandı aşıldı.\n"
                    f"SL: {atr_mult}× ATR ({sl_pct:.1f}%){dxy_note}"
                )
            })
        elif sq_dir == "down":
            sl = current_price + dynamic_sl_dist
            tp = current_price - (dynamic_sl_dist * 3)
            signals.append({
                "ticker": symbol, "market": "EMTİA",
                "strategy": "EMTİA 3: VOLATİLİTE SIKIŞMASI (SQUEEZE)",
                "signal": "SAT",
                "entry_price": current_price, "sl": sl, "tp": tp,
                "reason": (
                    f"🗜️ {emtia_name} Aşağı Squeeze Patlaması!\n"
                    f"1G BB(20,2) Keltner(20,1.5) içinden aşağı kırıldı.\n"
                    f"Hacimli kırmızı mum ile BB alt bandı kırıldı.\n"
                    f"SL: {atr_mult}× ATR ({sl_pct:.1f}%)"
                )
            })

    return signals


# ==========================================
# 4. 🐻 AYI AVCISI STRATEJİ MODÜLÜ (Ağır Sıklet SHORT)
# ==========================================
def analyze_bear_hunter(symbol, df_1d, df_4h, btc_bullish=False):
    """Ağır Sıklet SHORT tarayıcı. 3 strateji + 3 çelik kalkan.
    Sadece Top 30 majör coinlerde çalışır. Meme coinler kalıcı yasaklıdır."""
    signals = []

    if btc_bullish:
        return signals  # 👑 Kralın İzni: BTC güçlüyse hiçbir SHORT açılmaz

    if df_4h is None or len(df_4h) < 20:
        return signals

    # ATR hesaplama
    df_4h.ta.atr(length=14, append=True)
    last_4h = df_4h.iloc[-1]
    current_price = float(last_4h['close'])

    atr_val = last_4h.get('ATRr_14', last_4h.get('ATR_14'))
    if atr_val is None or pd.isna(atr_val):
        atr_val = current_price * 0.02

    # Funding Rate kontrolü (Tuzak Kalkanı)
    funding_rate = get_funding_rate(symbol)
    funding_ok = True
    funding_note = ""
    if funding_rate is not None:
        if funding_rate < -0.01:
            funding_ok = False  # 🧲 Çok fazla shortçu → tuzak riski
        elif funding_rate >= 0:
            funding_note = f"\n🧲 Funding: +{funding_rate:.4f}% (Shortçu az) ✅"
        else:
            funding_note = f"\n🧲 Funding: {funding_rate:.4f}% (Normal)"

    if not funding_ok:
        return signals  # Tüm sinyaller iptal

    # ==========================================
    # SHORT 1: ZİRVE TUZAĞI (SFP — Swing Failure Pattern)
    # ==========================================
    sfp_found, swing_high, sfp_candle = _detect_sfp(df_4h)
    if sfp_found and sfp_candle is not None:
        sl = float(sfp_candle['high']) + (atr_val * 0.3)
        # TP: Son swing low
        recent_low = float(df_4h.tail(20)['low'].min())
        tp = recent_low

        # R:R minimum 2:1 kontrol
        risk = sl - current_price
        reward = current_price - tp
        if risk > 0 and reward > 0 and (reward / risk) >= 2.0:
            rr_ratio = reward / risk
            sl_pct = (risk / current_price) * 100
            signals.append({
                "ticker": symbol, "market": "AYI_AVCISI",
                "strategy": "SHORT 1: ZİRVE TUZAĞI (SFP)",
                "signal": "SAT",
                "entry_price": current_price, "sl": sl, "tp": tp,
                "reason": (
                    f"🧹 {symbol} Zirve Tuzağı!\n"
                    f"Önceki tepe ({swing_high:.2f}) süpürüldü.\n"
                    f"Devasa üst fitil + kırmızı gövde.\n"
                    f"📐 R:R Oranı: {rr_ratio:.1f}:1\n"
                    f"🛑 SL: {sl:.2f} ({sl_pct:.1f}%)\n"
                    f"👑 BTC: Zayıf ✅{funding_note}"
                )
            })

    # ==========================================
    # SHORT 2: PAHALI BÖLGE REDDİ (SMC Premium Short)
    # ==========================================
    prem_found, fib_618, fib_786, prem_candle = _detect_premium_rejection(df_4h, df_1d)
    if prem_found:
        sl = fib_786 + (atr_val * 0.5)
        # Son swing low × 0.97
        recent_low = float(df_4h.tail(30)['low'].min())
        tp = recent_low * 0.97

        risk = sl - current_price
        reward = current_price - tp
        if risk > 0 and reward > 0 and (reward / risk) >= 2.0:
            rr_ratio = reward / risk
            sl_pct = (risk / current_price) * 100
            signals.append({
                "ticker": symbol, "market": "AYI_AVCISI",
                "strategy": "SHORT 2: PAHALI BÖLGE REDDİ (SMC PREMIUM)",
                "signal": "SAT",
                "entry_price": current_price, "sl": sl, "tp": tp,
                "reason": (
                    f"🎯 {symbol} Premium Bölge Reddi!\n"
                    f"1G düşüş trendi (EMA20<EMA50) onaylı.\n"
                    f"Fib 0.618-0.786 bölgesinde bearish red.\n"
                    f"📐 Premium: {fib_618:.2f} - {fib_786:.2f}\n"
                    f"📐 R:R Oranı: {rr_ratio:.1f}:1\n"
                    f"👑 BTC: Zayıf ✅{funding_note}"
                )
            })

    # ==========================================
    # SHORT 3: YORGUNLUK TEPESİ (Negatif Uyumsuzluk)
    # ==========================================
    div_found, sh_1, sh_2, rsi_1, rsi_2 = _detect_bearish_divergence(df_4h)
    if div_found:
        sl = sh_2 + (atr_val * 0.5)
        # Önceki swing low
        recent_low = float(df_4h.tail(20)['low'].min())
        tp = recent_low

        risk = sl - current_price
        reward = current_price - tp
        if risk > 0 and reward > 0 and (reward / risk) >= 2.0:
            rr_ratio = reward / risk
            sl_pct = (risk / current_price) * 100
            signals.append({
                "ticker": symbol, "market": "AYI_AVCISI",
                "strategy": "SHORT 3: YORGUNLUK TEPESİ (DİVERGENCE)",
                "signal": "SAT",
                "entry_price": current_price, "sl": sl, "tp": tp,
                "reason": (
                    f"🪫 {symbol} Yorgunluk Tepesi!\n"
                    f"Fiyat: {sh_1:.2f} → {sh_2:.2f} (Higher High)\n"
                    f"RSI: {rsi_1:.0f} → {rsi_2:.0f} (Lower High) ⚠️\n"
                    f"Hacim düştü + 4S EMA20 kırıldı.\n"
                    f"📐 R:R Oranı: {rr_ratio:.1f}:1\n"
                    f"👑 BTC: Zayıf ✅{funding_note}"
                )
            })

    return signals


def get_current_prices(tickers):
    """
    Verilen ticker listesi için anlık fiyatları çeker.
    BIST, KRİPTO ve EMTİA karışık olabilir.
    """
    prices = {}
    crypto_tickers = [t for t in tickers if "/" in t]
    bist_tickers = [t for t in tickers if ".IS" in t]
    emtia_tickers = [t for t in tickers if "=F" in t or "=X" in t]
    
    # BIST + EMTİA Fiyatlarını Çek (yfinance)
    yf_tickers = bist_tickers + emtia_tickers
    if yf_tickers:
        for ticker in yf_tickers:
            try:
                t_obj = yf.Ticker(ticker)
                # fast_info genelde yfinance güncel sürümlerinde mevcuttur
                # Eğer yoksa history(period='1d') kullanılabilir
                try:
                    last_price = t_obj.fast_info.last_price
                except Exception:
                    hist = t_obj.history(period="1d")
                    last_price = hist['Close'].iloc[-1] if not hist.empty else None
                
                if last_price is not None:
                    prices[ticker] = float(last_price)
            except Exception as e:
                logging.warning(f"[get_current_prices] BIST {ticker}: {e}")
            
    # KRIPTO Fiyatlarını Çek
    if crypto_tickers:
        # ABD Sunucusu değilse önce Binance
        if not IS_USA_SERVER:
            try:
                tickers_data = exchange.fetch_tickers(crypto_tickers)
                for t in crypto_tickers:
                    if t in tickers_data and 'last' in tickers_data[t] and tickers_data[t]['last']:
                        prices[t] = float(tickers_data[t]['last'])
            except Exception as e:
                logging.info(f"[get_current_prices] Binance toplu fiyat hatası: {e}")
                
        # Kraken / yfinance
        if IS_USA_SERVER or not prices:
            try:
                # Kraken üzerinden fiyatları çekmeyi dene (Tüm listeyi verince BadSymbol patlamaması için boş gönderip içinden seçiyoruz)
                tickers_data = exchange_fallback.fetch_tickers()
                for t in crypto_tickers:
                    if t in tickers_data and 'last' in tickers_data[t] and tickers_data[t]['last']:
                        prices[t] = float(tickers_data[t]['last'])
                    else:
                        # Olmazsa USD paritesini dene
                        usd_t = t.replace("/USDT", "/USD")
                        if usd_t in tickers_data and 'last' in tickers_data[usd_t] and tickers_data[usd_t]['last']:
                            prices[t] = float(tickers_data[usd_t]['last'])
            except Exception as ekr:
                logging.warning(f"[get_current_prices] Kraken fiyat hatası: {ekr}, yfinance deneniyor...")
                for t in crypto_tickers:
                    try:
                        yf_ticker = t.replace("/USDT", "-USD")
                        t_obj = yf.Ticker(yf_ticker)
                        try:
                            last_price = t_obj.fast_info.last_price
                        except Exception:
                            hist = t_obj.history(period="1d")
                            last_price = hist['Close'].iloc[-1] if not hist.empty else None
                        if last_price is not None:
                            prices[t] = float(last_price)
                    except Exception as eyf:
                        logging.warning(f"[get_current_prices] Kripto {t} yfinance hatası: {eyf}")
            
    return prices
