"""
config.py — Quant Bot Merkezi Yapılandırma
Tüm sabitler, eşikler, varlık listeleri ve magic number'lar burada toplanır.
Hiçbir strateji parametresi başka dosyada hardcoded olmamalıdır.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ════════════════════════════════════════
# Sunucu / Altyapı
# ════════════════════════════════════════
IS_USA_SERVER: bool = os.getenv("IS_USA_SERVER", "true").lower() == "true"

# ════════════════════════════════════════
# Varlık Listeleri
# ════════════════════════════════════════
TOP_CRYPTO = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "TRX/USDT", "TON/USDT", "NEAR/USDT", "INJ/USDT",
    "FET/USDT", "RENDER/USDT", "SUI/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "POL/USDT",
    "LTC/USDT", "BCH/USDT", "UNI/USDT", "XLM/USDT", "ATOM/USDT", "ICP/USDT", "FIL/USDT",
    "HBAR/USDT", "VET/USDT", "MKR/USDT", "AAVE/USDT", "RUNE/USDT", "QNT/USDT", "SNX/USDT",
    "THETA/USDT", "STX/USDT", "IMX/USDT", "EGLD/USDT", "SAND/USDT", "MANA/USDT", "AXS/USDT",
    "GRT/USDT", "CHZ/USDT", "S/USDT", "GALA/USDT", "CRV/USDT", "ROSE/USDT", "MINA/USDT", "WLD/USDT",
    "TIA/USDT", "SEI/USDT", "JUP/USDT", "STRK/USDT", "PYTH/USDT", "ENA/USDT", "W/USDT",
    "ONDO/USDT", "PENDLE/USDT", "JTO/USDT", "DYM/USDT", "ALT/USDT", "AEVO/USDT",
    "ETHFI/USDT", "TAO/USDT", "AR/USDT", "KAS/USDT", "ORDI/USDT",
    "TRB/USDT", "ALGO/USDT", "FLOW/USDT", "NEO/USDT", "ZIL/USDT", "IOTA/USDT", "EOS/USDT",
    "XTZ/USDT", "CAKE/USDT", "COMP/USDT", "YFI/USDT", "ZEC/USDT", "DASH/USDT", "DYDX/USDT",
    "1INCH/USDT", "ENS/USDT", "LDO/USDT", "SSV/USDT", "RPL/USDT", "BLUR/USDT", "MASK/USDT",
    "LRC/USDT", "ZRX/USDT", "BAL/USDT", "CELO/USDT", "ONE/USDT", "KAVA/USDT", "CFX/USDT",
    "ACH/USDT", "LISTA/USDT", "AGIX/USDT",
]

TOP_BIST = list(dict.fromkeys([
    "THYAO.IS", "ISCTR.IS", "SASA.IS", "HEKTS.IS", "TUPRS.IS", "EREGL.IS",
    "KCHOL.IS", "SISE.IS", "AKBNK.IS", "YKBNK.IS", "GARAN.IS",
    "SAHOL.IS", "BIMAS.IS", "ASELS.IS", "KRDMD.IS",
    "FROTO.IS", "TTKOM.IS", "TCELL.IS", "ENKAI.IS", "PETKM.IS",
    "TOASO.IS", "PGSUS.IS", "ARCLK.IS", "TAVHL.IS", "DOHOL.IS",
    "ODAS.IS", "ASTOR.IS", "MIATK.IS", "GESAN.IS", "SMRTG.IS",
    "ALFAS.IS", "EUPWR.IS", "CVKMD.IS", "CANTE.IS", "ZOREN.IS",
    "AKSA.IS", "ISMEN.IS", "TSKB.IS", "SKBNK.IS", "VAKBN.IS",
    "HALKB.IS", "CIMSA.IS", "AKSEN.IS", "ENJSA.IS", "GWIND.IS",
    "KONTR.IS", "MGROS.IS", "SOKM.IS", "KCAER.IS",
    "EKGYO.IS", "ISGYO.IS", "GUBRF.IS",
    "EGEEN.IS", "VESTL.IS", "VESBE.IS", "KLRHO.IS", "OTKAR.IS",
    "OYAKC.IS", "TTRAK.IS", "BRISA.IS", "AEFES.IS", "ULKER.IS",
    "ANHYT.IS", "ANSGR.IS", "TMSN.IS", "TRGYO.IS", "KORDS.IS",
    "BUCIM.IS", "ALARK.IS", "TURSG.IS", "AGHOL.IS", "ISDMR.IS",
    "SARKY.IS", "LOGO.IS", "MPARK.IS", "SUNTK.IS", "BASGZ.IS",
    "CEMAS.IS", "INDES.IS", "PAPIL.IS", "PENTA.IS", "YATAS.IS",
    "CWENE.IS", "NETAS.IS", "AYGAZ.IS",
    "TKFEN.IS", "ECILC.IS", "BERA.IS", "BTCIM.IS", "BRYAT.IS",
    "IEYHO.IS", "KENT.IS", "AVOD.IS", "OBAMS.IS", "QUAGR.IS",
    "BIOEN.IS",
]))

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

# 🐻 Ayı Avcısı — Ağır Sıklet SHORT Tarama Evreni (Top 50)
TOP_HEAVY_SHORT = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "TRX/USDT",
    "TON/USDT", "NEAR/USDT", "SUI/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT", "LTC/USDT", "BCH/USDT", "UNI/USDT", "XLM/USDT",
    "ATOM/USDT", "ICP/USDT", "FIL/USDT", "HBAR/USDT", "MKR/USDT",
    "AAVE/USDT", "RUNE/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT",
    "TIA/USDT", "SEI/USDT", "JUP/USDT", "ONDO/USDT", "PENDLE/USDT",
    "TAO/USDT", "AR/USDT", "KAS/USDT", "ORDI/USDT", "ALGO/USDT",
    "EOS/USDT", "COMP/USDT", "DYDX/USDT", "ENS/USDT", "LDO/USDT",
    "BLUR/USDT", "NEO/USDT", "FLOW/USDT", "CAKE/USDT", "DASH/USDT",
]

# 🚫 Meme Coin Kalıcı Kara Liste (SHORT yasağı)
MEME_BLACKLIST = {
    "DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "WIF/USDT", "FLOKI/USDT",
    "BONK/USDT", "MEME/USDT", "BABYDOGE/USDT", "NEIRO/USDT", "TURBO/USDT",
    "BRETT/USDT", "POPCAT/USDT", "BOME/USDT", "BOOK/USDT", "MEW/USDT",
    "NOT/USDT", "PEOPLE/USDT", "SATS/USDT",
}

# ════════════════════════════════════════
# ATR & Stop Parametreleri
# ════════════════════════════════════════
ATR_MULTIPLIER_BIST = 1.8
ATR_MULTIPLIER_CRYPTO = 2.2
MIN_SL_PCT = 0.03          # Minimum SL yüzdesi
TRAILING_ATR_FLOOR_RATIO = 0.3
TRAILING_TIGHT_PCT = 0.005   # %15+ kâr → sıkı trailing
TRAILING_MEDIUM_PCT = 0.015  # %10+ kâr → orta trailing

# ════════════════════════════════════════
# Scale-Out & Kâr Eşikleri
# ════════════════════════════════════════
SCALE_OUT_THRESHOLD_LONG = 5.0     # LONG %5'te kademeli çıkış
SCALE_OUT_THRESHOLD_SHORT_FOMO = 10.0  # FOMO İnfazı %10'da
TRAILING_TIER_1_PCT = 15.0  # Sıkı trailing başlar
TRAILING_TIER_2_PCT = 10.0  # Orta trailing başlar

# ════════════════════════════════════════
# RSI Eşikleri
# ════════════════════════════════════════
RSI_OVERSOLD_BIST = 40
RSI_OVERSOLD_CRYPTO = 28
RSI_OVERBOUGHT_FOMO = 85
RSI_BTC_PUMP_LIMIT = 70
BTC_PUMP_PCT_CHANGE = 4.0

# ════════════════════════════════════════
# ADX & Trend Eşikleri
# ════════════════════════════════════════
ADX_TREND_THRESHOLD = 25
ADX_STRONG_TREND = 30

# ════════════════════════════════════════
# BIST 9 (ORB) Parametreleri
# ════════════════════════════════════════
BIST9_MAX_CAGE_WIDTH_PCT = 2.0  # Kafes genişliği maksimum % kaç olabilir
BIST9_RVOL_MULTIPLIER = 1.5     # Kırılım mumunun hacmi, ortalama hacmin kaç katı olmalı
BIST9_EMA_LENGTH = 21           # Onay için kullanılacak EMA periyodu
BIST9_RVOL_PERIOD = 20          # RVOL hesaplaması için geriye dönük bakılacak gün sayısı
BIST9_TRADE_START_HOUR = 11     # Sinyal arama başlangıç saati
BIST9_TRADE_END_HOUR = 17       # Sinyal arama bitiş saati
BIST9_TRADE_END_MINUTE = 30     # Sinyal arama bitiş dakikası

ORB_CAGE_HOUR = 10              # Kafes oluşum saati
ORB_MIN_BARS = 4                # Kafes hesaplama için minimum gün içi bar sayısı

# ════════════════════════════════════════
# Indikatör ve Hareketli Ortalama Periyotları
# ════════════════════════════════════════
IND_RSI_LENGTH = 14
IND_ATR_LENGTH = 14
IND_ADX_LENGTH = 14

IND_EMA_FAST = 8
IND_EMA_MID = 20
IND_EMA_21 = 21
IND_EMA_SLOW = 50

IND_SMA_SLOW = 50
IND_SMA_TREND = 200

IND_BBANDS_LENGTH = 20
IND_BBANDS_STD = 2.0

IND_VOL_SMA_LENGTH = 20
IND_VOL_BREAKOUT_MULTIPLIER = 1.5

IND_RS_SMA_LENGTH = 50
IND_RS_MOMENTUM_SHORT = 5
IND_RS_MOMENTUM_LONG_START = 15
IND_RS_MOMENTUM_LONG_END = 10

IND_OBV_ACC_MIN_LEN = 21
IND_OBV_ACC_PERIOD = 20
IND_OBV_ACC_SHORT_PERIOD = 5
IND_OBV_ACC_MAX_CHANGE_PCT = 2.0
IND_OBV_ACC_VOL_MULTIPLIER = 1.5

# ════════════════════════════════════════
# V3.4 Conviction Soft Score Eşikleri (Sıkılaştırılmış)
# ════════════════════════════════════════
SOFT_ADX_CENTER = 28.0
SOFT_ADX_K = 0.35

SOFT_VOL_RATIO_CENTER = 1.8
SOFT_VOL_RATIO_K = 3.0

SOFT_RR_CENTER = 2.5
SOFT_RR_K = 2.5

SOFT_RSI_TREND_CENTER = 55.0
SOFT_RSI_TREND_MULT = 2.5

SOFT_RSI_OVERSOLD_BIST_CENTER = 30.0
SOFT_RSI_OVERSOLD_CRYPTO_CENTER = 25.0

SOFT_SQUEEZE_MIN = 0.03
SOFT_SQUEEZE_MAX = 0.15

SOFT_EMA_DIP_MULT = 5.7
SOFT_EMA_DIP_MAX_PCT = 7.0

# ════════════════════════════════════════
# V3.4 Conviction Scorer Alt-Puanlama (Fuzzy Logic) Sabitleri (SSOT)
# 
# Bu bölümdeki katsayılar conviction_scorer.py içindeki algoritmik esnetmeleri, 
# cezaları ve bonusları (magic numbers) kontrol eder. İnsan/Yapay Zeka anlaşılabilirliği
# için kategorize edilmiştir.
# ════════════════════════════════════════

# --- ADX & Momentum Sınırları ---
# ADX > 40 olduğunda trendin olgunlaştığı kabul edilir ve "decay" (ceza) uygulanır.
SOFT_ADX_MATURITY_START = 40.0       # Olgunlaşma cezasının başladığı ADX seviyesi
SOFT_ADX_MATURITY_MULT = 3.0         # Aşılan her 1 puan için uygulanacak ceza katsayısı
SOFT_ADX_MATURITY_MIN = 15.0         # Ceza sonrası düşülebilecek minimum puan sınırı
SOFT_ADX_MOMENTUM_UP = 1.10          # ADX yükseliyorsa uygulanacak bonus çarpanı (%10)
SOFT_ADX_MOMENTUM_DOWN = 0.85        # ADX düşüyorsa uygulanacak ceza çarpanı (%15)

# --- RSI Esneklik Limitleri ---
# RSI dip avcılığında hedeflenen merkez noktadan uzaklaşıldıkça puanı düşüren sapan sınırları
SOFT_RSI_OVERSOLD_MIN_DIST = 20.0    # Merkezden aşağı sapma toleransı (örn: merkez 30 ise 10'da puan 100 olur)
SOFT_RSI_OVERSOLD_MAX_DIST = 15.0    # Merkezden yukarı sapma toleransı (örn: merkez 30 ise 45'te puan sıfırlanır)

# --- EMA Hizalama ve Dizilim Puanları (LONG Stratejiler) ---
# Fiyatın ve EMA'ların birbiri üzerindeki konumlarına göre verilen kısmi puanlar (Toplamı ~100)
SOFT_EMA_ALIGN_PRICE_FAST = 30.0     # Fiyat > EMA(Fast) ise verilecek puan
SOFT_EMA_ALIGN_FAST_MID = 40.0       # EMA(Fast) > EMA(Mid) ise verilecek puan
SOFT_EMA_ALIGN_MID_SLOW = 30.0       # EMA(Mid) > EMA(Slow) ise verilecek puan
SOFT_EMA_ALIGN_FAST_SLOW = 15.0      # Sadece EMA(Fast) > EMA(Slow) ise verilecek puan (Mid tutmuyorsa)
SOFT_EMA_ALIGN_NO_SLOW = 15.0        # EMA(Slow) verisi yoksa verilen varsayılan puan

# --- EMA Dip Mesafesi Puanlaması (Dip Avcılığı İçin) ---
# Fiyatın EMA altındaki derinliğini fırsat bilip ekstra puan üreten lojik
SOFT_EMA_DIP_MAX_SCORE = 40.0        # Fiyat EMA'dan çok uzaktaysa alınabilecek maksimum puan
SOFT_EMA_DIP_MIN_SCORE = 5.0         # Fiyat EMA'nın üzerindeyse verilen minimum puan
SOFT_EMA_DIP_STRUCT_BULL = 35.0      # Fiyat dipte ama EMA yapısı boğa (Fast > Mid) kaldıysa fırsat bonusu
SOFT_EMA_DIP_STRUCT_BEAR = 10.0      # EMA yapısı ayıya döndüyse düşük fırsat bonusu
SOFT_EMA_DIP_SLOW_BULL = 25.0        # EMA(Slow) bazlı uzun vadeli yapı boğaysa eklenecek puan
SOFT_EMA_DIP_SLOW_HALF = 12.0        # Kısmi boğa yapısı (sadece Fast > Slow)
SOFT_EMA_DIP_SLOW_NONE = 12.0        # Slow verisi eksikse verilecek nötr puan

# --- EMA Hizalama ve Dizilim Puanları (SHORT Stratejiler) ---
# Fiyatın ve EMA'ların altında olması durumunda verilen puanlar (Ayı dizilimi)
SOFT_EMA_SHORT_PRICE_FAST = 30.0     # Fiyat < EMA(Fast) ise
SOFT_EMA_SHORT_FAST_MID = 40.0       # EMA(Fast) < EMA(Mid) ise (Death cross)
SOFT_EMA_SHORT_MID_SLOW = 30.0       # EMA(Mid) < EMA(Slow) ise (Tam ayı dizilimi)
SOFT_EMA_SHORT_FAST_SLOW = 15.0      # Kısmi ayı dizilimi
SOFT_EMA_SHORT_NO_SLOW = 15.0        # Veri yoksa verilen puan

# --- Piyasa Rejimi (Regime) Puan Çarpanları ---
# Makro rejim algılandığında temel skorun üzerine eklenecek taban puanlar
SOFT_REGIME_BULL = 100.0             # Boğa rejimindeyken
SOFT_REGIME_NEUTRAL = 50.0           # Nötr (Yatay) rejimdeyken
SOFT_REGIME_BEAR = 10.0              # Ayı rejimindeyken

# --- Mantıksal Eşik Puanları (İkili Durumlar) ---
SOFT_ENGULFING_YES = 85.0            # Yutan mum formasyonu varsa
SOFT_ENGULFING_NO = 30.0             # Yoksa (Cezalandırılır ama tamamen sıfırlanmaz)
SOFT_RSI_DIR_UP = 80.0               # RSI yukarı yönlüyse
SOFT_RSI_DIR_DOWN = 20.0             # RSI aşağı yönlüyse
SOFT_MACRO_ALIGNED = 90.0            # Endeks/BTC yönü stratejiyle aynı yöndeyse
SOFT_MACRO_NOT_ALIGNED = 30.0        # Makro uyum yoksa

# --- Stop Loss (SL) Ceza Seviyeleri ---
SOFT_PENALTY_0 = 100.0               # Ardışık SL yok (Tertemiz, tam puan)
SOFT_PENALTY_1 = 75.0                # 1 ardışık SL yemiş (%25 kesinti)
SOFT_PENALTY_2 = 45.0                # 2 ardışık SL yemiş (Riskli, skor düşürülür)
SOFT_PENALTY_3_PLUS = 0.0            # 3 veya daha fazla ardışık SL (Skor sıfırlanır)

# --- Logaritmik Hacim Ölçeklemesi (Min-Max Aralıkları) ---
# Mutlak hacimlerin logaritmik olarak puanlanmasında kullanılan sınırlar
SOFT_DOLLAR_VOL_CRYPTO_MIN = 100_000         # Kriptoda 0 puan getirecek en alt USD hacim sınırı
SOFT_DOLLAR_VOL_CRYPTO_MAX = 10_000_000      # Kriptoda 100 puan getirecek tavan USD hacim sınırı
SOFT_DOLLAR_VOL_EMTIA_MIN = 50_000           # Emtiada alt sınır
SOFT_DOLLAR_VOL_EMTIA_MAX = 5_000_000        # Emtiada üst sınır
SOFT_DOLLAR_VOL_BIST_MIN = 1_000_000         # BIST'te (TL) alt sınır
SOFT_DOLLAR_VOL_BIST_MAX = 100_000_000       # BIST'te (TL) üst sınır

# Rejim-Adaptif Conviction Eşikleri
REGIME_THRESHOLDS_BULL = {"STRONG": 75, "MEDIUM": 60, "WATCH": 45}
REGIME_THRESHOLDS_NEUTRAL = {"STRONG": 75, "MEDIUM": 52, "WATCH": 38}
REGIME_THRESHOLDS_BEAR = {"STRONG": 80, "MEDIUM": 48, "WATCH": 35}

# ════════════════════════════════════════
# Bollinger & Squeeze
# ════════════════════════════════════════
BB_SQUEEZE_WIDTH = 0.15
BB_LENGTH = 20
BB_STD = 2
KC_SCALAR = 1.5
SQUEEZE_MIN_COUNT = 3
VOLUME_BREAKOUT_MULT = 1.5

# ════════════════════════════════════════
# Fibonacci Seviyeleri
# ════════════════════════════════════════
FIB_OTE_LOW = 0.618
FIB_OTE_HIGH = 0.786

# ════════════════════════════════════════
# Funding Rate & Risk
# ════════════════════════════════════════
FUNDING_CRITICAL_LONG = 0.05
FUNDING_CRITICAL_SHORT = -0.05
FUNDING_SHORT_BLOCK = -0.01
OI_CRASH_PCT = 15.0
DANGER_ZONE_PCT = 2.0
DANGER_SAFE_PCT = 5.0
DANGER_COOLDOWN_SEC = 1800
BLACK_SWAN_PCT = 0.03
RR_MINIMUM = 2.0

# ════════════════════════════════════════
# Emtia Spesifik
# ════════════════════════════════════════
EMTIA_ATR_MULT = {
    "GC=F": 2.0, "GLDTR.IS": 2.0,
    "SI=F": 2.0, "GMSTR.IS": 2.0,
    "CL=F": 2.5, "BZ=F": 2.5,
    "HG=F": 2.5,
    "NG=F": 3.0,
    "ZW=F": 3.0,
}
DXY_SENSITIVE = {"GC=F", "SI=F", "GLDTR.IS", "GMSTR.IS"}

EMTIA_NAMES = {
    "GC=F": "Altın (USD)", "SI=F": "Gümüş (USD)",
    "GLDTR.IS": "Altın (TL)", "GMSTR.IS": "Gümüş (TL)",
    "CL=F": "WTI Petrol", "BZ=F": "Brent Petrol",
    "NG=F": "Doğal Gaz", "HG=F": "Bakır", "ZW=F": "Buğday",
}

# ════════════════════════════════════════
# Zamanlama
# ════════════════════════════════════════
CACHE_TTL_SECONDS = 300        # 5 dk cache
SCAN_INTERVAL_MINUTES = 15
HEARTBEAT_INTERVAL = 6 * 3600  # 6 saatte 1 heartbeat
COOLDOWN_SECONDS = 3600        # 1 saat sinyal cooldown
OHLCV_LIMIT = 100              # API'den çekilecek mum sayısı
API_SLEEP_BIST = 0.1
API_SLEEP_CRYPTO = 0.1
API_SLEEP_EMTIA = 0.2
BATCH_MAX_WORKERS = 3          # ThreadPoolExecutor max paralel çağrı

# ════════════════════════════════════════
# 🔴 Red Team Sabitleri (V3.1 Mantık Yamaları)
# ════════════════════════════════════════
# RED-08: ATR Stop üst sınırları (flash crash koruması)
ATR_CAP_BIST = 0.08            # BIST maksimum %8 stop
ATR_CAP_CRYPTO = 0.12          # Kripto maksimum %12 stop
ATR_CAP_EMTIA = 0.10           # Emtia maksimum %10 stop

# RED-07: Minimum anlamlı dolar hacmi (hayalet likidite filtresi)
MIN_DOLLAR_VOL_CRYPTO = 500_000    # 500K USD
MIN_DOLLAR_VOL_BIST = 5_000_000    # 5M TL

# RED-05: Gap-Up/Down filtresi
GAP_THRESHOLD_PCT = 3.0        # %3 üstü gap → sahte kırılım riski

# RED-06: Darth Maul mum filtresi
DARTH_MAUL_BODY_RATIO = 0.15   # Gövde/Toplam aralık < %15 → kaos mumu

# RED-03: Swing point minimum amplitude
SWING_MIN_AMPLITUDE_PCT = 1.5  # %1.5 altı swing → gürültü

# RED-16: Divergence tazelik kontrolü
DIVERGENCE_MAX_AGE_CANDLES = 10 # Divergence en fazla 10 mum eski olabilir

# RED-04: Squeeze minimum onay mum sayısı
SQUEEZE_CONFIRM_CANDLES = 2    # 2 mum onayı (tek mum sahte patlama engelleyici)

# RED-01: Volume SMA manipülasyon koruma oranı
VOL_SMA_LONG_RATIO = 0.6      # SMA(20) < SMA(50)*0.6 ise baskılanmış

# RED-02: ADX olgunlaşma eşiği
ADX_TOO_LATE = 45              # ADX > 45 → trend olgunlaşmış

# ════════════════════════════════════════
# 🛡️ Anti-Manipülasyon Kalkanları (AM Serisi)
# ════════════════════════════════════════
# AM-01: Engulfing / Momentum Onayı (Ölü Kedi Giyotini)
ENGULFING_MIN_BODY_RATIO = 0.50   # Yeşil mum, önceki kırmızı mumun en az %50'sini yutmalı

# AM-02: CMF Wash-Trade Kalkanı
CMF_PERIOD = 20                   # Chaikin Money Flow hesaplama periyodu
CMF_WASH_TRADE_THRESHOLD = 0.0    # CMF < 0 → Kurumsal boşaltma, ALIM REDDET

# AM-03: Mutlak Hacim Eşikleri (Sıfıra Bölünme Anomalisi)
MIN_HOURLY_DOLLAR_VOL_CRYPTO = 500_000   # Saatlik min 500K USD
MIN_HOURLY_TL_VOL_BIST = 10_000_000      # Saatlik min 10M TL

# AM-04: Funding Rate Short Kalkanı (Fonlama Vampiri)
FUNDING_SHORT_BLOCK_THRESHOLD = 0.0  # Negatif fonlamada SHORT AÇMA

# AM-05: Minimum Dalga Amplitüdü (Fraktal Körlüğü)
OTE_MIN_WAVE_PCT = 3.0          # SMC OTE: Dalga boyu en az %3 olmalı

# AM-06: Likidite Saatleri Zaman Kilidi (Zıt Korelasyon)
LIQUIDITY_WINDOW_START_HOUR = 15  # TSİ 15:30
LIQUIDITY_WINDOW_START_MIN = 30
LIQUIDITY_WINDOW_END_HOUR = 20    # TSİ 20:00
LIQUIDITY_WINDOW_END_MIN = 0

# ════════════════════════════════════════
# 🧬 V3.2 Kaos Çözümleri — Yeni Modül Parametreleri
# ════════════════════════════════════════

# --- Kaos #1: Adaptif Parametre Motoru (adaptive_params.py) ---
ADAPTIVE_VOL_SHORT_WINDOW = 30     # Kısa vadeli volatilite penceresi (gün)
ADAPTIVE_VOL_LONG_WINDOW = 180     # Uzun vadeli volatilite penceresi (gün)
ADAPTIVE_ATR_MIN_RATIO = 0.6      # ATR çarpan alt sınırı (base × 0.6)
ADAPTIVE_ATR_MAX_RATIO = 1.8      # ATR çarpan üst sınırı (base × 1.8)

# --- Kaos #2: Karantina Protokolü (quarantine.py) ---
QUARANTINE_STALE_SECONDS = 1800    # 30 dk fiyat gelmezse karantina
QUARANTINE_AUTO_CLOSE_HOURS = 72   # 72 saat sonra otomatik kapat
QUARANTINE_ENABLED = True          # Karantina modülü aktif mi

# --- Kaos #3: Sinyal Erime Motoru (signal_decay.py) ---
SIGNAL_DECAY_WARM_SECONDS = 1800        # 30 dk → ılık
SIGNAL_DECAY_STALE_SECONDS = 7200       # 2 saat → bayat
SIGNAL_DECAY_DEAD_CRYPTO_SECONDS = 21600  # 6 saat → kripto sinyali öldü
SIGNAL_DECAY_DEAD_BIST_SECONDS = 28800    # 8 saat → BIST sinyali öldü
SIGNAL_DECAY_MIN_RR = 1.5               # Bu R:R altında sinyal iptal
SIGNAL_DECAY_ENABLED = True              # Sinyal erime aktif mi

# --- Kaos #4: Ceza Kutusu (penalty_box.py) ---
PENALTY_CONSECUTIVE_WARNING = 2    # 2 ardışık SL → uyarı (R:R > 3:1 gerekir)
PENALTY_CONSECUTIVE_PENALTY = 3    # 3 ardışık SL → 24 saat yasak
PENALTY_CONSECUTIVE_BANNED = 5     # 5 ardışık SL → 72 saat yasak
PENALTY_DAILY_COMMISSION_LIMIT = 1.0  # Günlük komisyon limiti (sermaye %)
PENALTY_BOX_ENABLED = True         # Ceza kutusu aktif mi

# --- Kaos #5: Strateji Karnesi (strategy_scorecard.py) ---
SCORECARD_MAX_TRADES = 500         # Kayıtta tutulacak max işlem sayısı
SCORECARD_AUTO_DISABLE_DAYS = 60   # Darwinizm penceresi (gün)
SCORECARD_MIN_TRADES = 5           # Darwinizm için minimum işlem sayısı
SCORECARD_ENABLED = True           # Strateji karnesi aktif mi
SCORECARD_WEEKLY_REPORT_DAY = 6    # Pazar = 6 (0=Pazartesi)

# ════════════════════════════════════════
# Conviction A/B Test Konfigürasyonu
# ════════════════════════════════════════
CONVICTION_AB_ENABLED: bool = os.getenv('CONVICTION_AB_ENABLED', 'true').lower() == 'true'

# Control grubu (mevcut üretim eşikleri)
CONVICTION_THRESHOLDS_CONTROL = {
    'STRONG': 75,
    'MEDIUM': 60,
    'WATCH': 45,
}

# Experiment grubu (test eşikleri — daha agresif)
CONVICTION_THRESHOLDS_EXPERIMENT = {
    'STRONG': 70,
    'MEDIUM': 55,
    'WATCH': 40,
}

# ════════════════════════════════════════
# Devre Kesici (Circuit Breaker)
# ════════════════════════════════════════
MAX_CONSECUTIVE_SL = 3       # Ard arda 3 SL → devre aç (sessiz mod)
COOLDOWN_HOURS = 24          # Sessiz mod süresi (saat)
DAILY_MAX_SL = 5             # Günlük toplam SL limiti (ardışık olmasa bile)
