import json
import pandas as pd

def analyze_bist7():
    try:
        with open('active_trades.json', 'r') as f:
            active = json.load(f)
    except:
        active = []
        
    try:
        with open('test_trade_history.json', 'r') as f:
            history = json.load(f)
    except:
        history = []
        
    all_trades = active + history
    bist7_trades = [t for t in all_trades if "BIST 7" in str(t.get('strategy', ''))]
    
    print(f"Toplam BIST 7 Islem Sayisi (Active + History): {len(bist7_trades)}")
    for t in bist7_trades:
        print(f"{t.get('ticker')} - {t.get('entry_time')} - PNL: {t.get('pnl_pct', 0)}")
        
    try:
        df = pd.read_csv('sim_results.csv')
        df_bist7 = df[df['strategy'].str.contains("BIST 7", na=False)]
        print(f"\nSimulasyon Dosyasindaki BIST 7 Sinyal Sayisi: {len(df_bist7)}")
        if len(df_bist7) > 0:
            print(f"Ortalama PnL: {df_bist7['pnl_pct'].mean():.2f}%")
            print(f"Kazanma Orani: {len(df_bist7[df_bist7['pnl_pct'] > 0]) / len(df_bist7) * 100:.2f}%")
    except Exception as e:
        print(f"Simulasyon verisi okunamadi: {e}")

if __name__ == '__main__':
    analyze_bist7()
