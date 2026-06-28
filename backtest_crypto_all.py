import os
import sys
import math
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf
import warnings

# Disable warnings
warnings.filterwarnings("ignore")

# Force UTF-8 stdout
sys.stdout.reconfigure(encoding='utf-8')

# Disable all logs at or below INFO globally
logging.disable(logging.WARNING)

# Import yf_cache to enable caching for all downloads
import yf_cache

# Force config variables for backtesting safety
import config
config.IS_USA_SERVER = True

# Import active strategy logic and utilities
import data_sources
from data_sources import clean_yf_df, guard_dataframe
from strategies.crypto import analyze_strategies_crypto, apply_5x_sl_cap

# Mock Conviction A/B Test shadow evaluation to prevent heavy atomic disk writes in loop
import conviction_scorer
conviction_scorer._ab_evaluate = lambda *args, **kwargs: None

# Patch indicators.core.calculate_anchored_vwap_series to bypass heavy groupby calculations in loop
import indicators.core
_orig_vwap_series = indicators.core.calculate_anchored_vwap_series

def mock_calculate_anchored_vwap_series(df, anchor_type="weekly"):
    col = 'vwap_weekly' if anchor_type == "weekly" else 'vwap_monthly'
    if col in df.columns:
        return df[col]
    return _orig_vwap_series(df, anchor_type)

indicators.core.calculate_anchored_vwap_series = mock_calculate_anchored_vwap_series

# ══════════════════════════════════════════════════════════════════
# MOCKING LAYER (To prevent live API calls during backtest)
# ══════════════════════════════════════════════════════════════════
current_ts = None
active_df_1h = None
active_df_btc = None

def mock_get_crypto_1h_data(symbol):
    """Mock to return the historical 1h data sliced up to the current backtest timestamp."""
    global current_ts, active_df_1h
    if active_df_1h is not None and current_ts is not None:
        # Slice the data up to the current timestamp to prevent lookahead bias
        sliced = active_df_1h[active_df_1h.index <= current_ts]
        return sliced.copy()
    return pd.DataFrame()

def mock_get_funding_rate(symbol):
    """Mock funding rate to prevent CCXT calls during backtest. Returns a small normal rate."""
    return 0.0001  # 0.01% standard funding rate

def mock_fetch_crypto_oi_crash(symbol):
    """Mock open interest crash check. Returns False to be conservative."""
    return False

def mock_get_btc_dominance_trend():
    """Mock dominance trend. Returns DOWN to allow altcoin trades."""
    return "DOWN"

def mock_check_btc_not_pumping():
    """Check if BTC has pumped > 4% in the last 4 hours based on historical BTC data."""
    global current_ts, active_df_btc
    if active_df_btc is not None and current_ts is not None:
        btc_slice = active_df_btc[active_df_btc.index <= current_ts]
        if len(btc_slice) >= 4:
            prev_price = btc_slice['close'].iloc[-4]
            curr_price = btc_slice['close'].iloc[-1]
            if prev_price > 0:
                ret = (curr_price - prev_price) / prev_price * 100
                if ret > 4.0:
                    return False  # BTC is pumping, block shorts
    return True

def mock_check_token_unlocks(symbol):
    """Mock unlock check. Returns False."""
    return False

def mock_get_usdt_dominance_trend():
    """Mock USDT dominance trend. Returns DOWN (bullish)."""
    return "DOWN"

# Apply all mocks to data_sources and strategies.crypto modules
import strategies.crypto

for module in [data_sources, strategies.crypto]:
    if hasattr(module, 'get_crypto_1h_data'):
        module.get_crypto_1h_data = mock_get_crypto_1h_data
    if hasattr(module, 'get_funding_rate'):
        module.get_funding_rate = mock_get_funding_rate
    if hasattr(module, 'fetch_crypto_oi_crash'):
        module.fetch_crypto_oi_crash = mock_fetch_crypto_oi_crash
    if hasattr(module, 'get_btc_dominance_trend'):
        module.get_btc_dominance_trend = mock_get_btc_dominance_trend
    if hasattr(module, 'check_btc_not_pumping'):
        module.check_btc_not_pumping = mock_check_btc_not_pumping
    if hasattr(module, 'check_token_unlocks'):
        module.check_token_unlocks = mock_check_token_unlocks
    if hasattr(module, 'get_usdt_dominance_trend'):
        module.get_usdt_dominance_trend = mock_get_usdt_dominance_trend

# ══════════════════════════════════════════════════════════════════
# BACKTEST CONFIGURATION
# ══════════════════════════════════════════════════════════════════
import json

# Load tickers dynamically from assets.json
try:
    with open("assets.json", "r", encoding="utf-8") as f:
        _assets_data = json.load(f)
    TICKERS = _assets_data.get("TOP_CRYPTO_SCAN", [])
except Exception as e:
    print(f"Error loading assets.json: {e}")
    TICKERS = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT",
        "XRP/USDT", "ADA/USDT", "DOT/USDT", "DOGE/USDT",
        "WIF/USDT", "NEAR/USDT", "SUI/USDT", "APT/USDT", "OP/USDT"
    ]

YF_CRYPTO_TICKER_MAP = {
    "SUI/USDT": "SUI20947-USD",
    "APT/USDT": "APT21794-USD"
}

def get_yf_crypto_ticker(symbol: str) -> str:
    if symbol in YF_CRYPTO_TICKER_MAP:
        return YF_CRYPTO_TICKER_MAP[symbol]
    return symbol.replace("/USDT", "-USD")

BACKTEST_DAYS = 30
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=BACKTEST_DAYS)

# ══════════════════════════════════════════════════════════════════
# VERİ YÜKLEYİCİ
# ══════════════════════════════════════════════════════════════════
def fetch_ticker_data(symbol):
    """
    Downloads historical 1d and 1h data for backtesting.
    """
    yf_ticker = get_yf_crypto_ticker(symbol)
    print(f"Loading data for {symbol} (yfinance: {yf_ticker})...", flush=True)
    
    # 1d data (1 year for daily EMA/BB indicators warmup)
    df_1d = yf.download(yf_ticker, period="1y", interval="1d", progress=False, timeout=10)
    df_1d = clean_yf_df(df_1d)
    
    # 1h data (2 months to cover the 30 backtest days + warmup)
    df_1h = yf.download(yf_ticker, period="2mo", interval="1h", progress=False, timeout=10)
    df_1h = clean_yf_df(df_1h)
    
    if df_1h.empty or df_1d.empty:
        return None, None, None
        
    # Strip timezone info if present to avoid tz-aware vs tz-naive TypeError
    if df_1d.index.tz is not None:
        df_1d.index = df_1d.index.tz_localize(None)
    if df_1h.index.tz is not None:
        df_1h.index = df_1h.index.tz_localize(None)
        
    # Resample 4h data from 1h
    df_4h = df_1h.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    
    return df_1d, df_4h, df_1h

# ══════════════════════════════════════════════════════════════════
# OPTIMIZATION LAYER (Pre-compute indicators and bypass in loop)
# ══════════════════════════════════════════════════════════════════
import pandas_ta as ta
AnalysisIndicators = type(pd.DataFrame().ta)

original_methods = {}
for method_name in ['rsi', 'ema', 'adx', 'bbands', 'sma', 'atr', 'cmf', 'kc']:
    original_methods[method_name] = getattr(AnalysisIndicators, method_name)

USE_MOCK_TA = False

def make_wrapper(method_name):
    orig = original_methods[method_name]
    def wrapper(self, *args, **kwargs):
        if USE_MOCK_TA:
            return None
        return orig(self, *args, **kwargs)
    return wrapper

for method_name in original_methods:
    setattr(AnalysisIndicators, method_name, make_wrapper(method_name))

# ══════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ══════════════════════════════════════════════════════════════════
def run_backtest():
    global current_ts, active_df_1h, active_df_btc, USE_MOCK_TA
    
    print("\n" + "="*60)
    print(f"CRYPTO STRATEGIES BACKTEST: {BACKTEST_DAYS} DAYS")
    print("="*60)
    
    # 1. Download BTC data for DXY / BTC pump mocks
    USE_MOCK_TA = False
    _, _, active_df_btc = fetch_ticker_data("BTC/USDT")
    if active_df_btc is None:
        print("Failed to download BTC base data!")
        return
        
    trades = []
    
    # Loop over each symbol
    for symbol in TICKERS:
        USE_MOCK_TA = False
        df_1d, df_4h, df_1h = fetch_ticker_data(symbol)
        if df_1h is None or len(df_1h) < 200:
            print(f"Skipping {symbol} due to insufficient data.")
            continue
            
        # Precompute indicators on df_1d
        df_1d.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
        df_1d.ta.ema(length=config.IND_EMA_MID, append=True)
        df_1d.ta.ema(length=config.IND_EMA_SLOW, append=True)
        df_1d.ta.adx(length=config.IND_ADX_LENGTH, append=True)
        df_1d.ta.bbands(length=config.IND_BBANDS_LENGTH, std=config.IND_BBANDS_STD, append=True)
        if len(df_1d) >= 200:
            df_1d.ta.sma(length=200, append=True)
            
        # Precompute indicators on df_4h
        df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
        df_4h.ta.ema(length=config.IND_EMA_MID, append=True)
        df_4h.ta.ema(length=config.IND_EMA_SLOW, append=True)
        df_4h.ta.adx(length=config.IND_ADX_LENGTH, append=True)
        df_4h.ta.atr(length=config.IND_ATR_LENGTH, append=True)
        df_4h.ta.cmf(length=20, append=True)
        df_4h.ta.sma(length=200, append=True)
        df_4h.ta.ema(length=200, append=True)
        df_4h['vol_sma_20'] = df_4h['volume'].rolling(window=config.IND_VOL_SMA_LENGTH).mean()
        df_4h['vwap_weekly'] = _orig_vwap_series(df_4h, "weekly")
        
        # Precompute indicators on df_1h (for sniper_1h strategy)
        df_1h.ta.kc(length=20, scalar=1.5, append=True)
        df_1h.ta.bbands(length=20, std=2.0, append=True)
        df_1h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
        df_1h.ta.ema(length=config.IND_EMA_FAST, append=True)
        df_1h.ta.ema(length=config.IND_EMA_21, append=True)
        df_1h.ta.cmf(length=20, append=True)
        df_1h['vol_sma_20'] = df_1h['volume'].rolling(window=config.IND_VOL_SMA_LENGTH).mean()
        df_1h['vwap_weekly'] = _orig_vwap_series(df_1h, "weekly")
        
        # Store df_1h globally for the mock function
        active_df_1h = df_1h.copy()
        
        # Enable Mock TA during simulation loop to bypass heavy pandas-ta calculations
        USE_MOCK_TA = True
        
        # We start testing when timestamp >= START_DATE
        test_df_1h = df_1h[df_1h.index >= START_DATE]
        print(f"Simulating {symbol}... ({len(test_df_1h)} hours)", flush=True)
        
        open_positions = []
        
        for i in range(len(test_df_1h)):
            row_1h = test_df_1h.iloc[i]
            timestamp = test_df_1h.index[i]
            current_ts = timestamp
            
            # 1. Check exits for open positions
            remaining_positions = []
            for pos in open_positions:
                closed = False
                high_val = float(row_1h['high'])
                low_val = float(row_1h['low'])
                close_val = float(row_1h['close'])
                
                # Check Long Exit
                if pos['direction'] == 'LONG':
                    if low_val <= pos['sl']:
                        closed = True
                        pnl_pct = ((pos['sl'] - pos['entry']) / pos['entry']) * 100
                        exit_price = pos['sl']
                        exit_type = 'SL'
                    elif high_val >= pos['tp']:
                        closed = True
                        pnl_pct = ((pos['tp'] - pos['entry']) / pos['entry']) * 100
                        exit_price = pos['tp']
                        exit_type = 'TP'
                    else:
                        # Dynamic Trailing Stop: If profit >= 2%, drag SL to entry + 0.2%
                        current_profit_pct = ((close_val - pos['entry']) / pos['entry']) * 100
                        if current_profit_pct >= 2.0 and pos['sl'] < pos['entry']:
                            pos['sl'] = pos['entry'] * 1.002
                            
                # Check Short Exit
                elif pos['direction'] == 'SHORT':
                    if high_val >= pos['sl']:
                        closed = True
                        pnl_pct = ((pos['entry'] - pos['sl']) / pos['entry']) * 100
                        exit_price = pos['sl']
                        exit_type = 'SL'
                    elif low_val <= pos['tp']:
                        closed = True
                        pnl_pct = ((pos['entry'] - pos['tp']) / pos['entry']) * 100
                        exit_price = pos['tp']
                        exit_type = 'TP'
                
                if closed:
                    pos['exit_time'] = timestamp
                    pos['exit_price'] = exit_price
                    pos['pnl_pct'] = pnl_pct
                    pos['result'] = 'WIN' if pnl_pct > 0 else 'LOSS'
                    pos['exit_type'] = exit_type
                    trades.append(pos)
                else:
                    remaining_positions.append(pos)
                    
            open_positions = remaining_positions
            
            # 2. Strategy evaluation (every 4 hours, aligned with 4h candle closes)
            if timestamp.hour % 4 == 0:
                slice_1d = df_1d[df_1d.index < timestamp.normalize()].copy()
                slice_4h = df_4h[df_4h.index < timestamp].copy()
                
                if len(slice_1d) >= 50 and len(slice_4h) >= 20:
                    # BTC condition: is BTC > SMA200 on daily?
                    btc_ok = True
                    btc_slice = active_df_btc[active_df_btc.index <= timestamp]
                    # Resample hourly BTC data to daily to calculate daily SMA200
                    btc_daily = btc_slice.resample('1d').agg({'close': 'last'}).dropna()
                    if len(btc_daily) >= 200:
                        btc_daily_close = btc_daily['close'].iloc[-1]
                        btc_sma200 = btc_daily['close'].rolling(200).mean().iloc[-1]
                        if pd.notna(btc_sma200):
                            btc_ok = btc_daily_close > btc_sma200
                            
                    signals = analyze_strategies_crypto(symbol, slice_1d, slice_4h, btc_ok=btc_ok, btc_sniper_bias=0)
                    
                    for sig in signals:
                        strat_name = sig.get('strategy')
                        signal_type = "LONG" if sig.get('signal') == "AL" else "SHORT"
                        
                        # Prevent multiple concurrent trades of same strategy on same symbol
                        if any(p['strategy'] == strat_name for p in open_positions):
                            continue
                            
                        # Enter Trade
                        entry_price = float(row_1h['close'])
                        sl = float(sig['sl'])
                        tp = float(sig['tp'])
                        
                        # Double check SL cap
                        sl = apply_5x_sl_cap(sl, entry_price)
                        
                        open_positions.append({
                            'symbol': symbol,
                            'strategy': strat_name,
                            'direction': signal_type,
                            'entry_time': timestamp,
                            'entry': entry_price,
                            'sl': sl,
                            'tp': tp,
                            'score': sig.get('conviction_score', 0),
                            'grade': sig.get('conviction_grade', 'N/A')
                        })
                    
        # Close any lingering trades at the end of the simulation
        for pos in open_positions:
            close_price = float(df_1h['close'].iloc[-1])
            pnl_pct = ((close_price - pos['entry']) / pos['entry']) * 100 if pos['direction'] == 'LONG' else ((pos['entry'] - close_price) / pos['entry']) * 100
            pos['exit_time'] = df_1h.index[-1]
            pos['exit_price'] = close_price
            pos['pnl_pct'] = pnl_pct
            pos['result'] = 'WIN' if pnl_pct > 0 else 'LOSS'
            pos['exit_type'] = 'FORCE_CLOSE'
            trades.append(pos)
            
    # Reset USE_MOCK_TA after run
    USE_MOCK_TA = False
            
    # Convert to DataFrame
    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        print("\nNo trades were generated during the backtest.")
        return
        
    trades_df.to_csv("crypto_backtest_trades.csv", index=False)
    print(f"\nSaved {len(trades_df)} trades to crypto_backtest_trades.csv")
    
    # ══════════════════════════════════════════════════════════════════
    # ANALYTICS REPORT GENERATION
    # ══════════════════════════════════════════════════════════════════
    report_md = f"""# Crypto Backtesting Report

Analyzed **{len(TICKERS)}** assets over the last **{BACKTEST_DAYS}** days.
Period: **{START_DATE.strftime('%Y-%m-%d')}** to **{END_DATE.strftime('%Y-%m-%d')}**

## Overall Performance

"""
    total_trades = len(trades_df)
    wins = len(trades_df[trades_df['result'] == 'WIN'])
    losses = len(trades_df[trades_df['result'] == 'LOSS'])
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    total_pnl = trades_df['pnl_pct'].sum()
    avg_pnl = trades_df['pnl_pct'].mean()
    
    # SL/TP count breakdown
    sl_hits = len(trades_df[trades_df['exit_type'] == 'SL'])
    tp_hits = len(trades_df[trades_df['exit_type'] == 'TP'])
    force_close = len(trades_df[trades_df['exit_type'] == 'FORCE_CLOSE'])
    
    report_md += f"""- **Total Trades**: {total_trades}
- **Wins / Losses**: {wins} / {losses}
- **Win Rate**: {win_rate:.2f}%
- **Total Net PnL**: {total_pnl:.2f}%
- **Average PnL per Trade**: {avg_pnl:.2f}%
- **Exit Breakdown**:
  - Target Hit (TP): {tp_hits} ({tp_hits/total_trades*100:.1f}%)
  - Stop Loss Hit (SL): {sl_hits} ({sl_hits/total_trades*100:.1f}%)
  - Force Closed: {force_close} ({force_close/total_trades*100:.1f}%)

---

## Strategy Breakdown

| Strategy Name | Direction | Total Trades | Wins | Losses | Win Rate (%) | Net PnL (%) | Avg PnL (%) | SL Hit | TP Hit |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""
    
    grouped = trades_df.groupby(['strategy', 'direction'])
    
    for (strat, direction), group in grouped:
        st_trades = len(group)
        st_wins = len(group[group['result'] == 'WIN'])
        st_losses = len(group[group['result'] == 'LOSS'])
        st_winrate = st_wins / st_trades * 100
        st_pnl = group['pnl_pct'].sum()
        st_avg_pnl = group['pnl_pct'].mean()
        st_sl = len(group[group['exit_type'] == 'SL'])
        st_tp = len(group[group['exit_type'] == 'TP'])
        
        report_md += f"| {strat} | {direction} | {st_trades} | {st_wins} | {st_losses} | {st_winrate:.2f}% | {st_pnl:.2f}% | {st_avg_pnl:.2f}% | {st_sl} | {st_tp} |\n"
        
    report_md += "\n---\n\n## Asset Breakdown\n\n| Symbol | Total Trades | Win Rate (%) | Net PnL (%) | Avg PnL (%) |\n| :--- | :---: | :---: | :---: | :---: |\n"
    
    symbol_grouped = trades_df.groupby('symbol')
    for sym, group in symbol_grouped:
        sym_trades = len(group)
        sym_wins = len(group[group['result'] == 'WIN'])
        sym_winrate = sym_wins / sym_trades * 100
        sym_pnl = group['pnl_pct'].sum()
        sym_avg_pnl = group['pnl_pct'].mean()
        
        report_md += f"| {sym} | {sym_trades} | {sym_winrate:.2f}% | {sym_pnl:.2f}% | {sym_avg_pnl:.2f}% |\n"
        
    # Write to local file as an artifact
    artifact_path = r"C:\Users\YSR_MONSTER\.gemini\antigravity-ide\brain\fc0e6643-1d3d-4679-abcc-61159aa8f946\crypto_backtest_report.md"
    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print("\n=============================================")
    print("BACKTEST SUMMARY REPORT GENERATED")
    print("=============================================")
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate    : {win_rate:.2f}%")
    print(f"Net PnL     : {total_pnl:.2f}%")
    print(f"Average PnL : {avg_pnl:.2f}% per trade")
    print(f"SL Hits     : {sl_hits} | TP Hits: {tp_hits}")
    print("=============================================\n")

if __name__ == "__main__":
    run_backtest()
