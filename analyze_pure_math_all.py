import pandas as pd
import numpy as np

def find_best_filter(df, strategy_name, metric, is_greater_than=True):
    wins = df[df['Result'] == 'WIN']
    losses = df[df['Result'] == 'LOSS']
    
    if len(wins) == 0 or len(losses) == 0:
        return None
        
    best_threshold = 0
    best_pnl = (len(wins) * 2.0) - len(losses)
    best_filtered_wins = len(wins)
    best_filtered_losses = len(losses)
    
    min_val = df[metric].min()
    max_val = df[metric].max()
    
    # Test 100 thresholds
    step = (max_val - min_val) / 100
    if step == 0: return None
    
    for thresh in np.arange(min_val, max_val, step):
        if is_greater_than:
            filt_wins = len(wins[wins[metric] > thresh])
            filt_losses = len(losses[losses[metric] > thresh])
        else:
            filt_wins = len(wins[wins[metric] < thresh])
            filt_losses = len(losses[losses[metric] < thresh])
            
        pnl = (filt_wins * 2.0) - filt_losses
        
        # Only accept if it improves PnL AND keeps at least 30% of original wins
        if pnl > best_pnl and filt_wins >= len(wins) * 0.3:
            best_pnl = pnl
            best_threshold = thresh
            best_filtered_wins = filt_wins
            best_filtered_losses = filt_losses
            
    if best_pnl > ((len(wins) * 2.0) - len(losses)):
        return {
            'strategy': strategy_name,
            'metric': metric,
            'condition': '>' if is_greater_than else '<',
            'threshold': best_threshold,
            'orig_pnl': (len(wins) * 2.0) - len(losses),
            'new_pnl': best_pnl,
            'orig_wins': len(wins),
            'orig_losses': len(losses),
            'new_wins': best_filtered_wins,
            'new_losses': best_filtered_losses,
            'pnl_diff': best_pnl - ((len(wins) * 2.0) - len(losses))
        }
    return None

def main():
    try:
        df = pd.read_csv("backtest_all_strategies_results.csv")
    except FileNotFoundError:
        print("Error: backtest_all_strategies_results.csv not found.")
        return
        
    metrics = ['RSI', 'ADX', 'Relative_Volume', 'ATR_Pct', 'EMA_Diff_Pct', 'Candle_Body_Pct']
    
    print("="*50)
    print("PURE MATH OPTIMIZATION RESULTS")
    print("="*50)
    
    improvements = []
    
    for strategy in df['Strategy'].unique():
        s_df = df[df['Strategy'] == strategy]
        print(f"\nAnalyzing: {strategy} (Total Signals: {len(s_df)})")
        
        strat_improvements = []
        for metric in metrics:
            for is_greater in [True, False]:
                res = find_best_filter(s_df, strategy, metric, is_greater)
                if res:
                    strat_improvements.append(res)
                    
        # Sort by PnL Diff
        strat_improvements.sort(key=lambda x: x['pnl_diff'], reverse=True)
        
        if not strat_improvements:
            print("  No mathematical filter found that improves PnL.")
        else:
            for idx, best in enumerate(strat_improvements[:3]): # Show top 3
                print(f"  [{idx+1}] Filter: {best['metric']} {best['condition']} {best['threshold']:.4f}")
                print(f"      Original: {best['orig_wins']}W / {best['orig_losses']}L | PnL: {best['orig_pnl']:.2f}R")
                print(f"      New     : {best['new_wins']}W / {best['new_losses']}L | PnL: {best['new_pnl']:.2f}R")
                print(f"      Improvement: +{best['pnl_diff']:.2f}R")

if __name__ == "__main__":
    main()
