import re
from collections import Counter

log_path = '/home/ubuntu/quant_bot/bot.log'

def analyze():
    # Bu sözlükler ret ve atlama sebeplerini saklayacak
    execution_skips = []
    dataguard_rejections = []
    scanner_errors = []
    
    # Strateji bazlı atlama detayları
    strategy_skips = {} # strategy -> list of reasons
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # 1. Scanner Atlandı Kontrolü (Execution Layer)
                if '[Scanner] Atlandı:' in line:
                    # Format: [Scanner] Atlandı: Ticker (Strategy) - Reason
                    match = re.search(r'Atlandı:\s*(\S+)\s*\((.*?)\)\s*-\s*(.*)', line)
                    if match:
                        ticker = match.group(1)
                        strategy = match.group(2)
                        reason_raw = match.group(3).strip()
                        
                        # Temizle (örnek: "Zaten aktif pozisyon var (Mevcut Skor: ...)" -> "Zaten aktif pozisyon var")
                        reason = re.split(r'\(', reason_raw)[0].strip()
                        
                        execution_skips.append(reason)
                        if strategy not in strategy_skips:
                            strategy_skips[strategy] = []
                        strategy_skips[strategy].append(reason)
                
                # 2. DataGuard Rejections
                elif '[DataGuard]' in line:
                    # Format: [DataGuard] Sinyal reddedildi (routing): ...
                    # Veya: [DataGuard] Sinyal reddedildi (output): ...
                    match = re.search(r'Sinyal reddedildi\s*\((.*?)\):\s*(.*)', line)
                    if match:
                        dg_type = match.group(1)
                        reason = match.group(2).strip()
                        dataguard_rejections.append(f"{dg_type}: {reason}")
                
                # 3. Scanner Hataları (UnboundLocalError, vb.)
                elif 'UnboundLocalError' in line or 'Traceback' in line or 'Error' in line or 'Exception' in line:
                    if 'local variable \'ctx\' referenced before assignment' in line:
                        scanner_errors.append("UnboundLocalError: ctx referenced before assignment (Sinyalleri tamamen kesen kritik bug)")
                    elif 'Exception' in line or 'Error' in line:
                        scanner_errors.append(line.strip())
                        
        # Raporlama
        print("==================================================")
        print("             BOT RET/ATLAMA RAPORU")
        print("==================================================")
        
        print("\n--- 1. GENEL ATLAMA SEBEPLERİ (Execution Layer) ---")
        counter_exec = Counter(execution_skips)
        for reason, count in counter_exec.most_common():
            print(f"  * {reason}: {count} kez")
            
        print("\n--- 2. DATAGUARD TARAFINDAN REDDEDİLENLER ---")
        counter_dg = Counter(dataguard_rejections)
        if counter_dg:
            for reason, count in counter_dg.most_common():
                print(f"  * {reason}: {count} kez")
        else:
            print("  Herhangi bir DataGuard engellemesi bulunamadı.")
            
        print("\n--- 3. KRİTİK SCANNER/STRATEJİ HATALARI ---")
        counter_errors = Counter(scanner_errors)
        if counter_errors:
            for err, count in counter_errors.most_common(5):
                print(f"  * {err}: {count} kez")
        else:
            print("  Sistemde aktif kritik hata tespit edilmedi.")
            
        print("\n--- 4. STRATEJİ BAZINDA ATLAMA DETAYLARI ---")
        for strategy, reasons in sorted(strategy_skips.items()):
            print(f"\nStrateji: {strategy}")
            counter_strat = Counter(reasons)
            for reason, count in counter_strat.most_common():
                print(f"  - {reason}: {count} kez")
                
        print("==================================================")
        
    except Exception as e:
        print("Analiz hatası:", e)

if __name__ == '__main__':
    analyze()
