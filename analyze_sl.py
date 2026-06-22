import pandas as pd
import json

df = pd.read_excel('C:\\Users\\YSR_MONSTER\\Downloads\\market_snapshot_20260620_2000.xlsx')
with open('trade_history_2026_06.json') as f:
    history = json.load(f)

sl_trades = [t for t in history if 'sl' in str(t['status']).lower() or 'sl' in str(t.get('exit_reason', '')).lower()]
sl_df = pd.DataFrame(sl_trades)
print('SL trades found in JSON:', len(sl_df))

if not sl_df.empty:
    merged = pd.merge(sl_df, df, left_on='ticker', right_on='Symbol', how='inner')
    print('Merged rows:', len(merged))
    if len(merged) > 0:
        print(merged.head())
    else:
        print("No intersecting symbols between the JSON SL trades and the Market Snapshot.")
