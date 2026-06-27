import yf_cache
import yfinance as yf
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

symbols = {
    "RENDER/USDT": ("RENDER-USD", "2026-06-27 00:14:46+00:00", 1.597),
    "LAYER/USDT": ("LAYER-USD", "2026-06-27 00:39:43+00:00", 0.06641),
    "MYX/USDT": ("MYX-USD", "2026-06-27 01:54:38+00:00", 0.091),
    "MORPHO/USDT": ("MORPHO-USD", "2026-06-27 01:29:36+00:00", 1.7848),
    "ENS/USDT": ("ENS-USD", "2026-06-27 00:49:33+00:00", 4.276),
    "MON/USDT": ("MON-USD", "2026-06-27 00:14:46+00:00", 0.01957)
}

for ticker, (yf_symbol, entry_time_str, entry_price) in symbols.items():
    df = yf.download(yf_symbol, start="2026-06-26", end="2026-06-28", interval="5m", progress=False)
    if df.empty:
        print(ticker, "No data found")
        continue
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.columns = [c.lower() for c in df.columns]
    
    entry_dt = pd.to_datetime(entry_time_str)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
        
    df_after = df[df.index >= entry_dt]
    df_window = df_after[df_after.index <= pd.to_datetime("2026-06-27 05:30:21+00:00")]
    
    if df_window.empty:
        print(ticker, "Empty window")
        continue
        
    min_price = df_window["low"].min()
    max_price = df_window["high"].max()
    last_price = df_window["close"].iloc[-1]
    
    pnl_at_min = (entry_price - min_price) / entry_price * 100
    pnl_at_max = (entry_price - max_price) / entry_price * 100
    pnl_at_close = (entry_price - last_price) / entry_price * 100
    
    print(ticker, "Entry:", entry_price, "| Min:", round(min_price, 5), "(%PnL Short:", round(pnl_at_min, 2), ") | Max:", round(max_price, 5), "(%PnL Short:", round(pnl_at_max, 2), ") | Close:", round(last_price, 5), "(%PnL Short:", round(pnl_at_close, 2), ")")
