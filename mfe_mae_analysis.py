import pandas as pd
import yfinance as yf
import ta

def analyze_mfe_mae(symbols=["BTC-USD", "ETH-USD"], period="3mo", interval="1h"):
    print("Fetching data...")
    results = []
    
    for sym in symbols:
        df = yf.download(sym, period=period, interval=interval, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df.ffill().bfill().dropna()
        df.columns = [c.lower() for c in df.columns]
        
        df['ema_20'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        
        # ponytail: pure pandas vectorized MFE/MAE replaces 120 lines of manual row iterations
        fwd_high = df['high'].rolling(24).max().shift(-24)
        fwd_low = df['low'].rolling(24).min().shift(-24)
        
        longs = (df['close'] > df['ema_20']) & (df['close'].shift(1) <= df['ema_20'].shift(1))
        shorts = (df['close'] < df['ema_20']) & (df['close'].shift(1) >= df['ema_20'].shift(1))
        
        l_mfe = ((fwd_high - df['close']) / df['close'] * 100)[longs]
        l_mae = ((df['close'] - fwd_low) / df['close'] * 100)[longs]
        l_atr = (df['atr'] / df['close'] * 100)[longs]
        
        s_mfe = ((df['close'] - fwd_low) / df['close'] * 100)[shorts]
        s_mae = ((fwd_high - df['close']) / df['close'] * 100)[shorts]
        s_atr = (df['atr'] / df['close'] * 100)[shorts]
        
        results.append(pd.DataFrame({'Symbol': sym, 'Signal': 'LONG', 'MFE_Pct': l_mfe, 'MAE_Pct': l_mae, 'ATR_Pct': l_atr}))
        results.append(pd.DataFrame({'Symbol': sym, 'Signal': 'SHORT', 'MFE_Pct': s_mfe, 'MAE_Pct': s_mae, 'ATR_Pct': s_atr}))
        
    tdf = pd.concat(results).dropna()
    print(f"\nTotal signals analyzed: {len(tdf)}")
    print("\n--- Descriptive Statistics for MFE and MAE ---")
    print(tdf[['MFE_Pct', 'MAE_Pct', 'ATR_Pct']].describe())
    
    print("\nIf we set TP at 1% and SL at 1%, how many hit TP first?")
    # ponytail: naive heuristic (mae < sl). Upgrade path: true step-by-step tick simulation.
    for sl_mult in [1.0, 1.5, 2.0]:
        for tp_mult in [1.0, 2.0, 3.0]:
            sl_pct = tdf['ATR_Pct'] * sl_mult
            tp_pct = tdf['ATR_Pct'] * tp_mult
            
            wins = ((tdf['MAE_Pct'] < sl_pct) & (tdf['MFE_Pct'] >= tp_pct)).sum()
            losses = len(tdf) - wins
            if len(tdf) > 0:
                print(f"SL={sl_mult}xATR, TP={tp_mult}xATR -> WinRate: {wins/len(tdf)*100:.1f}% ({wins}W / {losses}L)")

if __name__ == "__main__":
    analyze_mfe_mae()
