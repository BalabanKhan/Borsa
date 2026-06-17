import csv
import os
from collections import defaultdict

TRADE_JOURNAL_CSV = "trade_journal.csv"

def parse_indicators(ind_str):
    """
    Parses 'RSI:35.2 | ADX:20.1' into a dict of floats where possible.
    """
    if not ind_str or ind_str == "N/A":
        return {}
    
    parts = [p.strip() for p in ind_str.split("|")]
    parsed = {}
    for part in parts:
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip()
            v = v.strip()
            try:
                parsed[k] = float(v)
            except ValueError:
                # Eger numara degilse string olarak birak
                parsed[k] = v
    return parsed

def get_median(lst):
    if not lst:
        return 0
    sorted_lst = sorted(lst)
    n = len(sorted_lst)
    if n % 2 == 1:
        return sorted_lst[n // 2]
    else:
        return (sorted_lst[n // 2 - 1] + sorted_lst[n // 2]) / 2

def run_autopsy():
    if not os.path.exists(TRADE_JOURNAL_CSV):
        print(f"[!] {TRADE_JOURNAL_CSV} bulunamadı. Önce işlem yapılması gerekiyor.")
        return

    wins = []
    losses = []
    
    # Gruplamalar
    strategies = defaultdict(lambda: {"wins": 0, "losses": 0})
    watch_stats = {"wins": 0, "losses": 0}
    real_stats = {"wins": 0, "losses": 0}

    with open(TRADE_JOURNAL_CSV, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sonuc = row.get("sonuc", "")
            strategy = row.get("strateji", "Bilinmiyor")
            is_watch = row.get("is_watch", "FALSE").upper() == "TRUE"
            ind_str = row.get("indicators", "")
            
            indicators = parse_indicators(ind_str)
            row["parsed_indicators"] = indicators
            
            if sonuc == "KAZANC":
                wins.append(row)
                strategies[strategy]["wins"] += 1
                if is_watch: watch_stats["wins"] += 1
                else: real_stats["wins"] += 1
            elif sonuc == "KAYIP":
                losses.append(row)
                strategies[strategy]["losses"] += 1
                if is_watch: watch_stats["losses"] += 1
                else: real_stats["losses"] += 1

    if not wins and not losses:
        print("[!] Analiz edilecek KAZANÇ veya KAYIP işlemi bulunamadı.")
        return

    total_trades = len(wins) + len(losses)
    win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0

    print("=" * 70)
    print(" [ANALIZ] KANTITATIF OTOPSI RAPORU (V2)")
    print("=" * 70)
    print(f"Genel Win Rate   : %{win_rate:.2f} ({len(wins)} KAZANÇ / {len(losses)} KAYIP)")
    print(f"Gerçek İşlemler  : {real_stats['wins']} KAZANÇ / {real_stats['losses']} KAYIP")
    print(f"Sanal (WATCH)    : {watch_stats['wins']} KAZANÇ / {watch_stats['losses']} KAYIP\n")

    print("STRATEJI BAZLI PERFORMANS")
    print("-" * 70)
    for strat, stats in sorted(strategies.items(), key=lambda x: x[1]['wins'] + x[1]['losses'], reverse=True):
        st_total = stats['wins'] + stats['losses']
        if st_total > 0:
            st_wr = (stats['wins'] / st_total) * 100
            print(f"  {strat:<20} | Win Rate: %{st_wr:>5.2f} ({stats['wins']}W / {stats['losses']}L)")

    # Sayısal indikatörlerin analizi
    all_indicator_keys = set()
    for t in wins + losses:
        all_indicator_keys.update([k for k, v in t["parsed_indicators"].items() if isinstance(v, float)])
        
    print("\nINDIKATOR KARSILASTIRMASI (MEDYAN DEGERLER)")
    print("-" * 70)
    print(f"{'İNDİKATÖR':<15} | {'KAZANAN (W)':>12} | {'KAYBEDEN (L)':>12} | {'FARK (W - L)':>12}")
    print("-" * 70)
    
    for key in sorted(all_indicator_keys):
        win_vals = [t["parsed_indicators"][key] for t in wins if key in t["parsed_indicators"]]
        loss_vals = [t["parsed_indicators"][key] for t in losses if key in t["parsed_indicators"]]
        
        med_win = get_median(win_vals) if win_vals else 0
        med_loss = get_median(loss_vals) if loss_vals else 0
        
        diff = med_win - med_loss
        diff_str = f"+{diff:.2f}" if diff > 0 else f"{diff:.2f}"
        
        print(f"{key:<15} | {med_win:>12.2f} | {med_loss:>12.2f} | {diff_str:>12}")

    print("\nCIKARIMLAR VE YORUMLAR")
    print("-" * 70)
    insights = []
    for key in sorted(all_indicator_keys):
        win_vals = [t["parsed_indicators"][key] for t in wins if key in t["parsed_indicators"]]
        loss_vals = [t["parsed_indicators"][key] for t in losses if key in t["parsed_indicators"]]
        
        if len(win_vals) < 3 or len(loss_vals) < 3:
            continue
            
        med_win = get_median(win_vals)
        med_loss = get_median(loss_vals)
        
        # Anlamlı fark varsa (> %10) yorum yap
        if med_win > med_loss * 1.1:
            insights.append(f"[+] {key} değeri yüksek olduğunda kazanma ihtimali daha yüksek.")
        elif med_loss > med_win * 1.1:
            insights.append(f"[!] {key} değeri yüksek olduğunda kaybetme riski daha yüksek (Zarar kesilebilir).")
            
    if insights:
        for insight in insights:
            print(insight)
    else:
        print("Yeterli belirgin fark saptanamadı. Daha fazla işlem verisine ihtiyaç var.")

    print("=" * 70)

if __name__ == "__main__":
    run_autopsy()
