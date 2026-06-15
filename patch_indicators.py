import re

with open("strategies.py", "r", encoding="utf-8") as f:
    content = f.read()

# Ekleme fonksiyonunu tanımla
helper_func = """
def _extract_raw_indicators(l_vars):
    import pandas as pd
    res = {}
    for prefix in ['last_15m', 'last_1h', 'last_4h', 'last_1d', 'last_1w']:
        if prefix in l_vars and isinstance(l_vars[prefix], pd.Series):
            tf = prefix.split('_')[1].upper()
            s = l_vars[prefix]
            if not pd.isna(s.get('RSI_14')): res[f'RSI_{tf}'] = round(s['RSI_14'], 2)
            if not pd.isna(s.get('ADX_14')): res[f'ADX_{tf}'] = round(s['ADX_14'], 2)
            if not pd.isna(s.get('volume')): res[f'Vol_{tf}'] = round(s.get('volume', 0), 2)
    return res

"""

if "def _extract_raw_indicators" not in content:
    # imports sonrasına ekle
    content = content.replace("def _get_consecutive_sl(symbol):", helper_func + "def _get_consecutive_sl(symbol):")

# Şimdi tüm signals.append({ yerlerini bulup değiştireceğiz
# Ama içinde zaten raw_indicators varsa atla
count = 0
def replacer(match):
    global count
    count += 1
    return match.group(1) + ' "raw_indicators": _extract_raw_indicators(locals()),'

new_content = re.sub(r'(signals\.append\(\{)', replacer, content)

with open("strategies.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"Replaced {count} instances.")
