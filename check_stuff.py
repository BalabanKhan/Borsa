
import yfinance as yf
import json
import os

print('--- Active Trades ---')
tracker_file = 'C:\\Users\\YSR_MONSTER\\.antigravity\\Borsa\\tracker.json'
if os.path.exists(tracker_file):
    with open(tracker_file, 'r', encoding='utf-8') as f:
        trades = json.load(f)
        active = [t for t in trades if t.get('status') == 'ACTIVE']
        for t in active:
            print(f"{t.get('ticker')} - Strategy: {t.get('strategy')} - Entry: {t.get('entry_price')}")
else:
    print('No tracker.json found')

print('\n--- YFinance Test ---')
for t in ['XAUTRY=X', 'XAGTRY=X', 'XAUTRYG.IS', 'XAGGTRY=X']:
    try:
        df = yf.download(t, period='1d', progress=False)
        if not df.empty:
            print(f"{t}: FOUND (Close: {df['Close'].iloc[-1]})")
        else:
            print(f"{t}: NOT FOUND (Empty)")
    except Exception as e:
        print(f"{t}: ERROR {e}")
