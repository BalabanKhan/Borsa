import sys
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import ccxt
import json
import warnings
from datetime import datetime, timedelta

# Simülasyon için anlık API sorgularını kapat (Lookahead Bias ve IP Ban önlemi)
import config
config.IS_USA_SERVER = True 

from data_sources import clean_yf_df
from strategies import (
    analyze_strategies_bist,
    analyze_strategies_crypto,
    analyze_strategies_emtia,
    analyze_bear_hunter
)

# Force UTF-8 for Windows terminal emoji support
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════
# RENK KODLARI (X-Ray Loglaması için)
# ══════════════════════════════════════════════════════════════════
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# ══════════════════════════════════════════════════════════════════
# MEGA SİMÜLASYON AYARLARI & İZOLASYON
# ══════════════════════════════════════════════════════════════════
MEGA_ACTIVE_FILE = "mega_test_active.json"
MEGA_HISTORY_FILE = "mega_test_history.json"

TICKERS_BIST = ["THYAO.IS", "TUPRS.IS", "KCHOL.IS", "AKBNK.IS", "EREGL.IS"]
TICKERS_CRYPTO_LONG = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"]
TICKERS_CRYPTO_SHORT = ["DOGE/USDT", "PEPE/USDT", "WIF/USDT"]
TICKERS_EMTIA = ["GC=F", "SI=F"] # Altın, Gümüş

# Zaman Makinesi: Son 7 Gün
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=7)

# Savaş Masası İstatistikleri
stats = {
    "total_bars_scanned": 0,
    "total_days": 30,
    "rejections": {
        "BIST": {"gate1":0, "gate2":0, "gate3":0, "gate4":0, "armor":0},
        "CRYPTO_LONG": {"gate1":0, "gate2":0, "gate3":0, "gate4":0, "armor":0},
        "CRYPTO_SHORT": {"gate1":0, "gate2":0, "gate3":0, "gate4":0, "armor":0},
        "EMTIA": {"gate1":0, "gate2":0, "gate3":0, "gate4":0, "armor":0}
    },
    "trades": {
        "taken": 0, "won": 0, "lost": 0,
        "total_pnl_pct": 0.0, "total_rr": 0.0
    }
}

open_trades = {}
trade_history = []

def save_state():
    with open(MEGA_ACTIVE_FILE, "w") as f: json.dump(open_trades, f, indent=4)
    with open(MEGA_HISTORY_FILE, "w") as f: json.dump(trade_history, f, indent=4)

# ══════════════════════════════════════════════════════════════════
# VERİ MOTORU (MULTI-TIMEFRAME)
# ══════════════════════════════════════════════════════════════════
def apply_indicators(df):
    if df.empty or len(df) < 50: return df
    try:
        df.ta.sma(length=200, append=True) # Gate 1: Rejim
        df.ta.macd(fast=12, slow=26, signal=9, append=True) # Gate 2: MTF Momentum
        df['vol_sma_20'] = ta.sma(df['volume'], length=20) # Gate 4: Hacim
        df.ta.atr(length=14, append=True)
        df.ta.rsi(length=14, append=True) # Zırh hesaplamaları için
    except: pass
    return df

def fetch_multi_timeframe_data(symbol, market):
    """
    Stratejilerin çalışabilmesi için 1D, 4H ve 1H verileri çeker.
    """
    df_1d = pd.DataFrame()
    df_4h = pd.DataFrame()
    df_1h = pd.DataFrame()
    
    try:
        if market in ["BIST", "EMTIA", "MACRO"]:
            df_1d = yf.download(symbol, period="6mo", interval="1d", progress=False)
            df_1d = clean_yf_df(df_1d)
            
            df_1h = yf.download(symbol, period="2mo", interval="1h", progress=False)
            df_1h = clean_yf_df(df_1h)
            
            if not df_1h.empty:
                df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
                
        elif "CRYPTO" in market:
            yf_ticker = symbol.replace("/USDT", "-USD")
            df_1d = yf.download(yf_ticker, period="6mo", interval="1d", progress=False)
            df_1d = clean_yf_df(df_1d)
            
            df_1h = yf.download(yf_ticker, period="2mo", interval="1h", progress=False)
            df_1h = clean_yf_df(df_1h)
            
            if not df_1h.empty:
                df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
                
    except Exception as e:
        print(f"{Colors.FAIL}[HATA] {symbol} MTF veri çekilemedi: {e}{Colors.ENDC}")
        
    return df_1d, df_4h, df_1h

# Makro Veriler (Gate 3 ve Zırhlar)
print(f"{Colors.CYAN}Makro veriler çekiliyor (XU100, BTC, DXY)...{Colors.ENDC}")
_, _, df_xu100 = fetch_multi_timeframe_data("XU100.IS", "MACRO")
df_xu100 = apply_indicators(df_xu100)

_, _, df_btc = fetch_multi_timeframe_data("BTC/USDT", "CRYPTO")
df_btc = apply_indicators(df_btc)

_, _, df_dxy = fetch_multi_timeframe_data("DX-Y.NYB", "MACRO")
df_dxy = apply_indicators(df_dxy)

# ══════════════════════════════════════════════════════════════════
# SİMÜLASYON MOTORU
# ══════════════════════════════════════════════════════════════════
def run_simulation(market_type, tickers, strategy_name):
    print(f"\n{Colors.HEADER}>>> {market_type} MEGA SİMÜLASYONU BAŞLIYOR ({strategy_name}) <<<{Colors.ENDC}")
    
    for symbol in tickers:
        df_1d, df_4h, df_1h = fetch_multi_timeframe_data(symbol, market_type)
        if df_1h.empty or len(df_1h) < 200: 
            print(f"{Colors.FAIL}[ATLANDI] {symbol} için yeterli veri yok.{Colors.ENDC}")
            continue
            
        # Ana tarama motoru için 1H df'yi kullanıyoruz, göstergeleri ekliyoruz
        df_1h = apply_indicators(df_1h)
        test_df = df_1h[df_1h.index.tz_localize(None) >= START_DATE]
        print(f"{Colors.CYAN}[TARAMA] {symbol} | Test Mum Sayısı: {len(test_df)}{Colors.ENDC}")
        
        for i in range(10, len(test_df)):
            stats["total_bars_scanned"] += 1
            timestamp = test_df.index[i]
            bar = test_df.iloc[i]
            price = float(bar['close'])
            
            # --- 1. AÇIK İŞLEMLERİN YÖNETİMİ (ATR STOP & SCALE-OUT) ---
            if symbol in open_trades:
                trade = open_trades[symbol]
                direction = trade['type']
                
                # LONG Yönetimi
                if direction == "LONG":
                    if float(bar['high']) >= trade['tp']:
                        pnl = ((trade['tp'] - trade['entry']) / trade['entry']) * 100
                        print(f"{Colors.GREEN}[A+ SETUP KAPANIŞ] {timestamp} | {symbol} Hedefe Ulaştı (TP)! Kâr: +%{pnl:.2f}{Colors.ENDC}")
                        stats["trades"]["won"] += 1
                        stats["trades"]["total_pnl_pct"] += pnl
                        stats["trades"]["total_rr"] += 2.0
                        del open_trades[symbol]
                        continue
                    if float(bar['low']) <= trade['sl']:
                        pnl = ((trade['sl'] - trade['entry']) / trade['entry']) * 100
                        print(f"{Colors.FAIL}[ZARAR KES] {timestamp} | {symbol} Stop-Loss (SL) Patladı! Zarar: %{pnl:.2f}{Colors.ENDC}")
                        stats["trades"]["lost"] += 1
                        stats["trades"]["total_pnl_pct"] += pnl
                        stats["trades"]["total_rr"] -= 1.0
                        del open_trades[symbol]
                        continue
                    # Dinamik İzleyen Stop (Kâr %2'yi geçince stop'u girişe çek)
                    current_pnl = ((price - trade['entry']) / trade['entry']) * 100
                    if current_pnl >= 2.0 and trade['sl'] < trade['entry']:
                        trade['sl'] = trade['entry'] * 1.002
                        print(f"{Colors.BLUE}[DİNAMİK STOP] {timestamp} | {symbol} Kâr %{current_pnl:.2f}'e ulaştı, SL maliyete (+%0.2) çekildi.{Colors.ENDC}")

                # SHORT Yönetimi
                elif direction == "SHORT":
                    if float(bar['low']) <= trade['tp']:
                        pnl = ((trade['entry'] - trade['tp']) / trade['entry']) * 100
                        print(f"{Colors.GREEN}[A+ SETUP KAPANIŞ] {timestamp} | {symbol} SHORT Hedefe Ulaştı (TP)! Kâr: +%{pnl:.2f}{Colors.ENDC}")
                        stats["trades"]["won"] += 1
                        stats["trades"]["total_pnl_pct"] += pnl
                        stats["trades"]["total_rr"] += 2.0
                        del open_trades[symbol]
                        continue
                    if float(bar['high']) >= trade['sl']:
                        pnl = ((trade['entry'] - trade['sl']) / trade['entry']) * 100
                        print(f"{Colors.FAIL}[ZARAR KES] {timestamp} | {symbol} SHORT Stop-Loss (SL) Patladı! Zarar: -%{abs(pnl):.2f}{Colors.ENDC}")
                        stats["trades"]["lost"] += 1
                        stats["trades"]["total_pnl_pct"] -= abs(pnl)
                        stats["trades"]["total_rr"] -= 1.0
                        del open_trades[symbol]
                        continue
                continue # İşlemdeyken yeni sinyal arama

            # --- 2. GERÇEK STRATEJİ SİNYAL ÜRETİMİ ---
            signal_type = None
            strategy_reason = ""
            sl_strat = 0.0
            tp_strat = 0.0
            strategy_identified = ""

            # Zamanda yolculuk: Geçmişteki sadece o ana kadar olan veriyi kesiyoruz
            slice_1d = df_1d[df_1d.index.tz_localize(None) <= timestamp.tz_localize(None)].copy()
            slice_4h = df_4h[df_4h.index.tz_localize(None) <= timestamp.tz_localize(None)].copy()
            slice_1h = df_1h[df_1h.index.tz_localize(None) <= timestamp.tz_localize(None)].copy()

            if len(slice_1d) >= 30 and len(slice_4h) >= 20 and len(slice_1h) >= 20:
                sigs = []
                
                if market_type == "BIST":
                    xu100_down = False
                    m_bar_xu100 = df_xu100[df_xu100.index.tz_localize(None) <= timestamp.tz_localize(None)]
                    df_xu100_daily = None
                    if not m_bar_xu100.empty:
                        xu100_last = m_bar_xu100.iloc[-1]
                        xu100_down = bool(float(xu100_last['close']) < float(xu100_last.get('SMA_200', 0)))
                        # Günlük XU100 verisi (Göreli güç için)
                        df_xu100_daily = m_bar_xu100.resample('1d').last().dropna()
                    
                    sigs = analyze_strategies_bist(symbol, slice_1d, slice_4h, slice_1h, xu100_down=xu100_down, xu100_daily=df_xu100_daily)
                    
                elif market_type == "CRYPTO_LONG":
                    btc_ok = False
                    m_bar_btc = df_btc[df_btc.index.tz_localize(None) <= timestamp.tz_localize(None)]
                    if not m_bar_btc.empty:
                        btc_last = m_bar_btc.iloc[-1]
                        btc_ok = bool(float(btc_last['close']) > float(btc_last.get('SMA_200', 0)))
                        
                    # btc_sniper_bias hesabı pas geçildi (simülasyonda 0)
                    sigs = analyze_strategies_crypto(symbol, slice_1d, slice_4h, btc_ok=btc_ok, btc_sniper_bias=0)
                    
                elif market_type == "CRYPTO_SHORT":
                    btc_bullish = False
                    m_bar_btc = df_btc[df_btc.index.tz_localize(None) <= timestamp.tz_localize(None)]
                    if not m_bar_btc.empty:
                        btc_last = m_bar_btc.iloc[-1]
                        btc_bullish = bool(float(btc_last['close']) > float(btc_last.get('SMA_200', 0)))
                        
                    sigs = analyze_bear_hunter(symbol, slice_1d, slice_4h, btc_bullish=btc_bullish)
                    
                elif market_type == "EMTIA":
                    dxy_bullish = False
                    m_bar_dxy = df_dxy[df_dxy.index.tz_localize(None) <= timestamp.tz_localize(None)]
                    if not m_bar_dxy.empty:
                        dxy_last = m_bar_dxy.iloc[-1]
                        dxy_bullish = bool(float(dxy_last['close']) > float(dxy_last.get('SMA_200', 0)))
                        
                    sigs = analyze_strategies_emtia(symbol, slice_1d, slice_4h, dxy_bullish=dxy_bullish)

                if sigs:
                    sig = sigs[0] # İlk sinyali alıyoruz
                    signal_type = "LONG" if sig['signal'] == "AL" else "SHORT"
                    strategy_reason = sig['reason']
                    sl_strat = float(sig['sl'])
                    tp_strat = float(sig['tp'])
                    strategy_identified = sig['strategy']

            if not signal_type: continue

            # --- 3. GÜMRÜK KAPILARI VE ZIRHLAR (RÖNTGEN) ---
            sma200 = float(bar.get('SMA_200', 0))
            macd_hist = float(bar.get('MACDh_12_26_9', 0))
            vol_sma = float(bar.get('vol_sma_20', 1))
            rsi = float(bar.get('RSI_14', 50))
            volume = float(bar['volume'])
            
            # Kapı 1: Rejim
            if signal_type == "LONG" and price < sma200:
                print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 1. Kapı (SMA 200 Altında - Ayı Rejimi){Colors.ENDC}")
                stats["rejections"][market_type]["gate1"] += 1; continue
            elif signal_type == "SHORT" and price > sma200:
                print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 1. Kapı (SMA 200 Üzerinde - Boğa Rejimi){Colors.ENDC}")
                stats["rejections"][market_type]["gate1"] += 1; continue
                
            # Kapı 2: MTF Momentum
            if signal_type == "LONG" and macd_hist <= 0:
                print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 2. Kapı (MACD Negatif - Momentum Zayıf){Colors.ENDC}")
                stats["rejections"][market_type]["gate2"] += 1; continue
            elif signal_type == "SHORT" and macd_hist >= 0:
                print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 2. Kapı (MACD Pozitif - Düşüş Momentumu Yok){Colors.ENDC}")
                stats["rejections"][market_type]["gate2"] += 1; continue

            # Kapı 3: Macro Gravity
            if market_type == "BIST" and not df_xu100.empty:
                try:
                    m_bar = df_xu100[df_xu100.index.tz_localize(None) <= timestamp.tz_localize(None)].iloc[-1]
                    if float(m_bar['close']) < float(m_bar.get('SMA_200', 0)):
                        print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 3. Kapı (XU100 Endeksi Ayı Rejiminde){Colors.ENDC}")
                        stats["rejections"][market_type]["gate3"] += 1; continue
                except: pass
            elif "CRYPTO" in market_type and not df_btc.empty:
                try:
                    m_bar = df_btc[df_btc.index.tz_localize(None) <= timestamp.tz_localize(None)].iloc[-1]
                    if signal_type == "LONG" and float(m_bar['close']) < float(m_bar.get('SMA_200', 0)):
                        print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 3. Kapı (BTC Ayı Rejiminde, Long Yasak){Colors.ENDC}")
                        stats["rejections"][market_type]["gate3"] += 1; continue
                    elif signal_type == "SHORT" and float(m_bar['close']) > float(m_bar.get('SMA_200', 0)):
                        print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 3. Kapı (BTC Boğa Rejiminde, Short Açmak İntihardır){Colors.ENDC}")
                        stats["rejections"][market_type]["gate3"] += 1; continue
                except: pass

            # Kapı 4: Hacim
            if volume < (vol_sma * 1.5):
                print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: 4. Kapı (Hacim Şiddeti Yetersiz){Colors.ENDC}")
                stats["rejections"][market_type]["gate4"] += 1; continue

            # ÖZEL ZIRHLAR
            if market_type == "EMTIA" and not df_dxy.empty:
                try:
                    dxy_bar = df_dxy[df_dxy.index.tz_localize(None) <= timestamp.tz_localize(None)].iloc[-1]
                    if float(dxy_bar['close']) > float(dxy_bar.get('SMA_200', 0)):
                        print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: Zırh Aktif (DXY Dolar Endeksi Boğa Rejiminde){Colors.ENDC}")
                        stats["rejections"][market_type]["armor"] += 1; continue
                except: pass
            elif market_type == "CRYPTO_SHORT":
                if rsi < 35: # Aşırı satım, fonlama muhtemelen negatif
                    print(f"{Colors.WARNING}[{strategy_identified}] Sinyal Reddedildi: Zırh Aktif (Fonlama Oranı Aşırı Negatif - Squeeze Riski){Colors.ENDC}")
                    stats["rejections"][market_type]["armor"] += 1; continue

            # --- 4. A+ SETUP: İŞLEME GİR ---
            open_trades[symbol] = {"type": signal_type, "entry": price, "sl": sl_strat, "tp": tp_strat, "timestamp": str(timestamp)}
            stats["trades"]["taken"] += 1
            save_state()
            
            # Formatted Reason Print
            reason_lines = strategy_reason.split('\n')
            reason_str = " | ".join(reason_lines)
            
            print(f"{Colors.GREEN}{Colors.BOLD}🚀 [A+ SETUP ATEŞLENDİ] {timestamp} | {symbol} 4 Kapı ve Makro Zırhları Geçti! {signal_type} İşlem Açıldı.{Colors.ENDC}")
            print(f"{Colors.GREEN}   ▶ Strateji: {strategy_identified}{Colors.ENDC}")
            print(f"{Colors.GREEN}   ▶ Detaylar: {reason_str}{Colors.ENDC}")
            print(f"{Colors.GREEN}   ▶ Giriş: {price:.3f} | SL: {sl_strat:.3f} | TP: {tp_strat:.3f}{Colors.ENDC}")

# ══════════════════════════════════════════════════════════════════
# SAVAŞ MASASI ÖZET RAPORU (Executive Summary)
# ══════════════════════════════════════════════════════════════════
def print_executive_summary():
    print(f"\n{Colors.HEADER}{Colors.BOLD}════════════════════════════════════════════════════════════════════════════")
    print(f"👑 SAVAŞ MASASI ÖZET RAPORU (Executive Summary) - Son {stats['total_days']} Gün")
    print(f"════════════════════════════════════════════════════════════════════════════{Colors.ENDC}")
    print(f"{Colors.CYAN}Tarama Periyodu : {START_DATE.strftime('%Y-%m-%d')} ile {END_DATE.strftime('%Y-%m-%d')} Arası")
    print(f"Taranan Toplam Mum: {stats['total_bars_scanned']:,} Adet{Colors.ENDC}")
    
    print(f"\n{Colors.WARNING}🛡️ KALKAN PERFORMANSI (Reddedilen Sahte Sinyaller){Colors.ENDC}")
    print(f"{'PİYASA':<15} | {'1. KAPI (Rejim)':<16} | {'2. KAPI (Momentum)':<18} | {'3. KAPI (Macro)':<16} | {'4. KAPI (Hacim)':<16} | {'ZIRHLAR'}")
    print("-" * 105)
    
    total_rejected = 0
    for m, r in stats["rejections"].items():
        tr = sum(r.values())
        total_rejected += tr
        print(f"{m:<15} | {r['gate1']:<16} | {r['gate2']:<18} | {r['gate3']:<16} | {r['gate4']:<16} | {r['armor']} (Toplam: {tr})")
    
    print(f"\n{Colors.BOLD}Kasa Güvenliği: Sistem toplam {total_rejected} adet yanlış işleme girmeyi reddetti.{Colors.ENDC}")
    
    print(f"\n{Colors.GREEN}🎯 A+ SETUP İŞLEM SONUÇLARI{Colors.ENDC}")
    t_taken = stats['trades']['taken']
    t_won = stats['trades']['won']
    t_lost = stats['trades']['lost']
    win_rate = (t_won / (t_won + t_lost) * 100) if (t_won + t_lost) > 0 else 0
    avg_rr = (stats['trades']['total_rr'] / (t_won + t_lost)) if (t_won + t_lost) > 0 else 0
    total_pnl = stats['trades']['total_pnl_pct']
    
    print(f"Açılan A+ İşlem Sayısı : {t_taken}")
    print(f"Başarılı (TP Vuran)    : {t_won}")
    print(f"Başarısız (SL Vuran)   : {t_lost}")
    print(f"Kazanma Oranı (Win Rate): %{win_rate:.1f}")
    print(f"Ortalama R:R Oranı     : {avg_rr:.2f}")
    
    pnl_color = Colors.GREEN if total_pnl >= 0 else Colors.FAIL
    print(f"{Colors.BOLD}TOPLAM PNL (Kâr/Zarar) : {pnl_color}%{total_pnl:.2f}{Colors.ENDC}")
    
    if len(open_trades) > 0:
        print(f"\n{Colors.BLUE}Açık Kalan İşlemler:{Colors.ENDC}")
        for sym, t in open_trades.items():
            print(f"  - {sym} ({t['type']}) | Giriş: {t['entry']:.3f} | Hedef: {t['tp']:.3f}")

    print(f"{Colors.HEADER}════════════════════════════════════════════════════════════════════════════{Colors.ENDC}\n")

if __name__ == "__main__":
    print(f"{Colors.CYAN}{Colors.BOLD}MEGA ZAMAN MAKİNESİ BAŞLATILIYOR... (GERÇEK STRATEJİLER İLE){Colors.ENDC}")
    
    run_simulation("BIST", TICKERS_BIST, "BIST STRATEJİLERİ")
    run_simulation("CRYPTO_LONG", TICKERS_CRYPTO_LONG, "KRİPTO LONG STRATEJİLERİ")
    run_simulation("CRYPTO_SHORT", TICKERS_CRYPTO_SHORT, "KRİPTO SHORT (AYI AVCISI)")
    run_simulation("EMTIA", TICKERS_EMTIA, "EMTİA STRATEJİLERİ")
    
    print_executive_summary()
