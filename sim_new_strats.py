import pandas as pd
import yfinance as yf
import ccxt
import sys

sys.path.append('C:\\Users\\YSR_MONSTER\\.antigravity\\Borsa')
from data_fetcher import analyze_strategies_bist, analyze_strategies_crypto, TOP_BIST, TOP_CRYPTO, clean_yf_df

print("Downloading Data...")
# We need data from a month ago to today
bist_data = {}
for ticker in TOP_BIST[:15]: # Limit to top 15 BIST to save time
    try:
        df_1h = yf.download(ticker, period="2mo", interval="1h", progress=False)
        df_1h = clean_yf_df(df_1h)
        if not df_1h.empty:
            df_1d = df_1h.resample('1d').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
            df_4h = df_1h.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
            bist_data[ticker] = {'1d': df_1d, '4h': df_4h, '1h': df_1h}
    except:
        pass

crypto_data = {}
exchange = ccxt.kraken({'enableRateLimit': True})
for ticker in TOP_CRYPTO[:15]: # Limit to top 15 Crypto
    try:
        sym = ticker.replace('/USDT', '/USD')
        ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=1500)
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='ms')
        df_1h.set_index('timestamp', inplace=True)
        if not df_1h.empty:
            df_1d = df_1h.resample('1d').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
            df_4h = df_1h.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
            crypto_data[ticker] = {'1d': df_1d, '4h': df_4h, '1h': df_1h}
    except:
        pass

print(f"Loaded {len(bist_data)} BIST and {len(crypto_data)} CRYPTO.")

target_strats = [
    'BIST 5: VOLATİLİTE SIKIŞMASI', 'BIST 6: GÖRECELİ GÜÇ (RS)', 'BIST 7: VWAP MIKNATISI', 'BIST 8: OBV BİRİKİMİ', 'BIST 9: ORB (ZAMAN KAFESİ)',
    'KRİPTO 5: SQUEEZE (DARALMA)', 'KRİPTO 6: VWAP MIKNATISI', 'KRİPTO 7: OBV DIVERGENCE'
]

results = []

# Simulate from last Friday (June 5, 2026) to June 12
start_date_base = pd.to_datetime("2026-06-05")

for ticker, data in bist_data.items():
    df_1d_full, df_4h_full, df_1h_full = data['1d'], data['4h'], data['1h']
    
    # Iterate through days
    start_date = start_date_base.tz_localize(df_1d_full.index.tz) if getattr(df_1d_full.index, 'tz', None) is not None else start_date_base
    unique_days = df_1d_full[df_1d_full.index >= start_date].index
    for current_day in unique_days:
        # Slice up to current day
        df_1d_slice = df_1d_full[df_1d_full.index <= current_day]
        df_4h_slice = df_4h_full[df_4h_full.index <= current_day + pd.Timedelta(days=1)]
        df_1h_slice = df_1h_full[df_1h_full.index <= current_day + pd.Timedelta(days=1)]
        
        try:
            signals = analyze_strategies_bist(ticker, df_1d_slice, df_4h_slice, df_1h_slice)
            for s in signals:
                if s['strategy'] in target_strats:
                    # Look forward to check profit/loss
                    forward_data = df_1h_full[df_1h_full.index > current_day]
                    outcome = "Açık (Bekliyor)"
                    pnl_pct = 0
                    if not forward_data.empty:
                        for _, row in forward_data.iterrows():
                            if s['signal'] == 'AL':
                                if row['high'] >= s['tp']:
                                    outcome = "KAR (TP)"
                                    pnl_pct = (s['tp'] - s['entry_price'])/s['entry_price'] * 100
                                    break
                                elif row['low'] <= s['sl']:
                                    outcome = "ZARAR (SL)"
                                    pnl_pct = (s['sl'] - s['entry_price'])/s['entry_price'] * 100
                                    break
                    results.append({'Date': current_day.date(), 'Ticker': ticker, 'Strategy': s['strategy'], 'Entry': s['entry_price'], 'Outcome': outcome, 'PNL': pnl_pct})
        except Exception as e:
            pass

for ticker, data in crypto_data.items():
    df_1d_full, df_4h_full, df_1h_full = data['1d'], data['4h'], data['1h']
    start_date = start_date_base.tz_localize(df_1d_full.index.tz) if getattr(df_1d_full.index, 'tz', None) is not None else start_date_base
    unique_days = df_1d_full[df_1d_full.index >= start_date].index
    for current_day in unique_days:
        df_1d_slice = df_1d_full[df_1d_full.index <= current_day]
        df_4h_slice = df_4h_full[df_4h_full.index <= current_day + pd.Timedelta(days=1)]
        try:
            signals = analyze_strategies_crypto(ticker, df_1d_slice, df_4h_slice, btc_ok=True, btc_sniper_bias=1)
            for s in signals:
                if s['strategy'] in target_strats:
                    forward_data = df_1h_full[df_1h_full.index > current_day]
                    outcome = "Açık (Bekliyor)"
                    pnl_pct = 0
                    if not forward_data.empty:
                        for _, row in forward_data.iterrows():
                            if s['signal'] == 'AL':
                                if row['high'] >= s['tp']:
                                    outcome = "KAR (TP)"
                                    pnl_pct = (s['tp'] - s['entry_price'])/s['entry_price'] * 100
                                    break
                                elif row['low'] <= s['sl']:
                                    outcome = "ZARAR (SL)"
                                    pnl_pct = (s['sl'] - s['entry_price'])/s['entry_price'] * 100
                                    break
                            elif s['signal'] == 'SAT':
                                if row['low'] <= s['tp']:
                                    outcome = "KAR (TP)"
                                    pnl_pct = (s['entry_price'] - s['tp'])/s['entry_price'] * 100
                                    break
                                elif row['high'] >= s['sl']:
                                    outcome = "ZARAR (SL)"
                                    pnl_pct = (s['entry_price'] - s['sl'])/s['entry_price'] * 100
                                    break
                    results.append({'Date': current_day.date(), 'Ticker': ticker, 'Strategy': s['strategy'], 'Signal': s['signal'], 'Outcome': outcome, 'PNL': pnl_pct})
        except Exception as e:
            pass

df_res = pd.DataFrame(results)
if not df_res.empty:
    print(df_res.to_string())
    tp_count = len(df_res[df_res['Outcome'] == 'KAR (TP)'])
    sl_count = len(df_res[df_res['Outcome'] == 'ZARAR (SL)'])
    print(f"\nTotal TP: {tp_count}, Total SL: {sl_count}")
    print(f"Win Rate: {tp_count/(tp_count+sl_count)*100 if tp_count+sl_count > 0 else 0:.2f}%")
else:
    print("No signals generated by these 8 strategies in the timeframe.")
