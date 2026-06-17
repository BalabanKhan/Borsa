import pandas as pd
import time
import random
from data_fetcher import TOP_50_COINS, exchange
from ai_analyzer import get_ai_decisions_batch

# 1 gün = 24 saat * 4 (15m periyot) = 96
# İndikatör hesaplamaları için (RSI vb.) ek 35 mum pay = 131
LIMIT = 131 

def _fetch_backtest_data(selected_coins):
    all_data = {}
    for symbol in selected_coins:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=LIMIT)
            if not ohlcv or len(ohlcv) < 50: 
                continue
            
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.ta.rsi(length=14, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.atr(length=14, append=True)
            
            all_data[symbol] = df
            time.sleep(0.1) # Rate limit
        except Exception as e:
            print(f"Hata {symbol}: {e}")
            
    try:
        btc_ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=LIMIT)
        btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'], unit='ms')
        btc_df.ta.ema(length=50, append=True)
    except Exception as e:
        print(f"BTC verisi çekilemedi: {e}")
        btc_df = None
        
    return all_data, btc_df

def _get_btc_trend(btc_df, ts):
    if btc_df is None:
        return "Neutral"
    btc_row = btc_df[btc_df['timestamp'] == ts]
    if len(btc_row) == 0:
        return "Neutral"
    btc_price = btc_row.iloc[0]['close']
    btc_ema50 = btc_row.iloc[0]['EMA_50']
    if pd.isna(btc_ema50):
        return "Neutral"
    return "Bullish" if btc_price > btc_ema50 else "Bearish"

def _extract_opp_data(df, idx, ts, symbol, btc_trend):
    prev_closed = df.iloc[idx - 2]
    last_closed = df.iloc[idx - 1]
    row = df.iloc[idx]
    
    current_price = row['close']
    rsi_val = last_closed['RSI_14']
    prev_rsi_val = prev_closed['RSI_14']
    macd_val = last_closed['MACD_12_26_9']
    macds_val = last_closed['MACDs_12_26_9']
    atr_val = last_closed['ATRr_14'] if 'ATRr_14' in last_closed else (current_price * 0.02)
    
    if pd.isna(rsi_val) or pd.isna(macd_val) or pd.isna(macds_val) or pd.isna(prev_rsi_val) or pd.isna(atr_val):
        return None
        
    if rsi_val >= 35 and rsi_val <= 65:
        return None
        
    trend = "Bearish"
    if idx >= 20 and current_price > df.iloc[idx - 20]['close']:
        trend = "Bullish"
        
    return {
        "timestamp": str(ts),
        "ticker": symbol,
        "current_price": current_price,
        "rsi": round(rsi_val, 2),
        "prev_rsi": round(prev_rsi_val, 2),
        "atr": round(atr_val, 4),
        "macd": round(macd_val, 4),
        "macd_signal": round(macds_val, 4),
        "coin_trend": trend,
        "btc_trend": btc_trend
    }

def _prepare_backtest_opportunities(all_data, btc_df, timestamps):
    all_filtered_data = []
    for ts in timestamps:
        btc_trend = _get_btc_trend(btc_df, ts)
        for symbol, df in all_data.items():
            idx_list = df[df['timestamp'] == ts].index
            if len(idx_list) == 0: 
                continue
            idx = idx_list[0]
            if idx < 2: 
                continue
            
            opp = _extract_opp_data(df, idx, ts, symbol, btc_trend)
            if opp is not None:
                all_filtered_data.append(opp)
    return all_filtered_data

def _check_active_trade_exits(symbol, row, active_trades, ts, closed_trades):
    for t in active_trades:
        if t['ticker'] == symbol and t['status'] == 'ACTIVE':
            low_price = row['low']
            high_price = row['high']
            
            if t['signal'] == 'AL':
                if low_price <= t['sl']:
                    t['status'] = 'CLOSED_SL'
                    t['exit_price'] = t['sl']
                    t['exit_time'] = ts
                    closed_trades.append(t)
                elif high_price >= t['tp']:
                    t['status'] = 'CLOSED_TP'
                    t['exit_price'] = t['tp']
                    t['exit_time'] = ts
                    closed_trades.append(t)
            elif t['signal'] == 'SAT':
                if high_price >= t['sl']:
                    t['status'] = 'CLOSED_SL'
                    t['exit_price'] = t['sl']
                    t['exit_time'] = ts
                    closed_trades.append(t)
                elif low_price <= t['tp']:
                    t['status'] = 'CLOSED_TP'
                    t['exit_price'] = t['tp']
                    t['exit_time'] = ts
                    closed_trades.append(t)

def _handle_new_trade_signals(current_signals, active_trades, current_prices_dict, ts):
    for d in current_signals:
        ticker = d.get('ticker')
        signal = d.get('signal')
        if not ticker or signal not in ['AL', 'SAT']: 
            continue
        if any(t['ticker'] == ticker and t['status'] == 'ACTIVE' for t in active_trades):
            continue
        if ticker not in current_prices_dict: 
            continue
        
        entry_price = current_prices_dict[ticker]['close']
        sl = d.get('sl')
        tp = d.get('tp')
        if not sl or not tp: 
            continue
        
        active_trades.append({
            'ticker': ticker,
            'signal': signal,
            'entry_price': entry_price,
            'sl': float(sl),
            'tp': float(tp),
            'status': 'ACTIVE',
            'entry_time': ts
        })
        print(f"[{ts}] YENİ İŞLEM: {ticker} | Sinyal: {signal} | Giriş: {entry_price} | TP: {tp} | SL: {sl}")

def _run_backtest_loop(all_data, timestamps, signals_by_time):
    active_trades = []
    closed_trades = []
    
    for i, ts in enumerate(timestamps):
        current_prices_dict = {}
        for symbol, df in all_data.items():
            row_idx = df[df['timestamp'] == ts].index
            if len(row_idx) == 0: 
                continue
            idx = row_idx[0]
            row = df.iloc[idx]
            
            current_prices_dict[symbol] = {
                'close': row['close'],
                'high': row['high'],
                'low': row['low']
            }
            _check_active_trade_exits(symbol, row, active_trades, ts, closed_trades)
                            
        # Aktif işlemleri güncelle
        active_trades = [t for t in active_trades if t['status'] == 'ACTIVE']
        
        # Bu timestamp için sinyal var mı?
        current_signals = signals_by_time.get(ts, [])
        _handle_new_trade_signals(current_signals, active_trades, current_prices_dict, ts)
            
        if (i + 1) % 100 == 0:
            print(f"Simülasyon İlerleme: {i + 1} / {len(timestamps)} periyot tamamlandı...")
            
    return closed_trades, active_trades

def _print_backtest_report(closed_trades, active_trades, initial_investment_per_trade):
    print("\n===========================================")
    print("[ RAPOR ] 1 GÜNLÜK SİMÜLASYON RAPORU")
    print("===========================================")
    
    total_trades = len(closed_trades)
    win_trades = len([t for t in closed_trades if t['status'] == 'CLOSED_TP'])
    loss_trades = len([t for t in closed_trades if t['status'] == 'CLOSED_SL'])
    
    total_profit_loss = 0.0
    if total_trades > 0:
        for t in closed_trades:
            entry = t['entry_price']
            exit = t['exit_price']
            pct_change = (exit - entry) / entry
            if t['signal'] == 'SAT':
                pct_change = -pct_change
                
            profit_loss = initial_investment_per_trade * pct_change
            total_profit_loss += profit_loss
            
            durum_str = "[+] KAR" if t['status'] == 'CLOSED_TP' else "[-] ZARAR"
            print(f"[{t['entry_time']} - {t['exit_time']}] {t['ticker']} | {t['signal']} | P&L: ${round(profit_loss, 2)} ({durum_str})")
    
    print("\n-------------------------------------------")
    print(f"Zaman Aralığı: Son 1 Gün")
    print(f"İşlem Başına Sermaye: ${initial_investment_per_trade}")
    print(f"Kapanan Toplam İşlem: {total_trades}")
    if total_trades > 0:
        print(f"Başarı Oranı (Win Rate): %{round((win_trades / total_trades) * 100, 2)} ({win_trades} Win / {loss_trades} Loss)")
        print(f"Toplam Net Kâr/Zarar: ${round(total_profit_loss, 2)}")
    else:
        print("Hiç işlem kapatılmadı.")
        
    print(f"Hâlâ Açık İşlem Sayısı: {len(active_trades)}")
    print("===========================================\n")

def run_backtest():
    print("Geçmiş 1 günlük veriler çekiliyor (15m)...")
    selected_coins = random.sample(TOP_50_COINS, min(10, len(TOP_50_COINS)))
    print(f"Rastgele seçilen 10 coin: {selected_coins}")
    
    all_data, btc_df = _fetch_backtest_data(selected_coins)

    if not all_data:
        print("Hiç veri çekilemedi.")
        return
        
    print(f"Toplam {len(all_data)} coin verisi çekildi. Zaman hizalaması yapılıyor...")
    first_coin = list(all_data.keys())[0]
    timestamps = all_data[first_coin]['timestamp'].dropna().tolist()
    timestamps = timestamps[35:] # İlk 35 mum indikatörler için
    initial_investment_per_trade = 100.0
    
    print(f"Simülasyon başlıyor... Tüm veriler tek seferde yapay zekaya gönderilecek.")
    print("Bu işlem verilerin büyüklüğüne bağlı olarak biraz zaman alabilir.\n")
    
    all_filtered_data = _prepare_backtest_opportunities(all_data, btc_df, timestamps)
    print(f"Toplam {len(all_filtered_data)} potansiyel fırsat bulundu. Yapay zekaya gönderiliyor...")
    
    all_decisions = []
    if all_filtered_data:
        try:
            all_decisions = get_ai_decisions_batch(all_filtered_data, None)
            print(f"Yapay zeka {len(all_decisions)} adet işlem kararı verdi.")
        except Exception as e:
            print(f"Yapay zeka hatası: {e}")
            
    signals_by_time = {}
    for d in all_decisions:
        ts_str = d.get('timestamp')
        if not ts_str: 
            continue
        try:
            ts_parsed = pd.to_datetime(ts_str)
            if ts_parsed not in signals_by_time:
                signals_by_time[ts_parsed] = []
            signals_by_time[ts_parsed].append(d)
        except Exception as e:
            print(f"[Timestamp parse hatası] {e}")

    closed_trades, active_trades = _run_backtest_loop(all_data, timestamps, signals_by_time)
    _print_backtest_report(closed_trades, active_trades, initial_investment_per_trade)

if __name__ == "__main__":
    run_backtest()
