import json
import urllib.request

try:
    with urllib.request.urlopen('https://fapi.binance.com/fapi/v1/ticker/24hr') as response:
        data = json.loads(response.read().decode())
except Exception as e:
    print(f"Error fetching data: {e}")
    exit(1)

import os
assets_path = os.path.join(os.path.dirname(__file__), 'assets.json')
with open(assets_path, 'r', encoding='utf-8') as f:
    assets = json.load(f)

meme_blacklist = assets.get('MEME_BLACKLIST', [])
meme_symbols = set([m.replace('/USDT', 'USDT') for m in meme_blacklist])

# Add explicit non-coin indices and speculative/meme targets
extra_blacklist = [
    'DEFIUSDT', 'FOOTBALLUSDT', 'BLUEBIRDUSDT', 'BTCDOMUSDT', 'USDCUSDT',
    'FARTCOINUSDT', 'PENGUUSDT', 'TRUMPUSDT', 'VVVUSDT', 'HMSTRUSDT', 'SAGAUSDT',
    # Traditional stocks and commodities that Binance Futures might return
    'NVDAUSDT', 'TSLAUSDT', 'AAPLUSDT', 'AMZNUSDT', 'MSFTUSDT', 'GOOGLUSDT',
    'AMDUSDT', 'ARMUSDT', 'SAMSUNGUSDT', 'SPYUSDT', 'QQQUSDT', 'SPXUSDT', 
    'XAUUSDT', 'XAGUSDT', 'XPTUSDT', 'PLTRUSDT', 'COHRUSDT', 'METAUSDT',
    'BILLUSDT', 'AVGOUSDT', 'IBMUSDT', 'QCOMUSDT', 'RKLBUSDT', 'HOODUSDT',
    'TSMUSDT', 'COINUSDT', 'NATGASUSDT', 'HEIUSDT', 'ORCLUSDT', 'SKHYNIXUSDT',
    'SOXLUSDT', 'CLUSDT', 'MRVLUSDT', 'INTCUSDT', 'DRAMUSDT', 'MSTRUSDT', 'EWYUSDT',
    # Problematic/delisted/ghost candles
    'SYNUSDT', 'REUSDT', 'BTWUSDT', 'BICOUSDT', 'ESPORTSUSDT', 'AAOIUSDT', 'NOKUSDT', 'ARXUSDT'
]
meme_symbols.update(extra_blacklist)

valid_symbols = []
for item in data:
    symbol = item.get('symbol', '')
    volume = float(item.get('quoteVolume', 0)) # USD volume
    
    # Must end with USDT
    if not symbol.endswith('USDT'):
        continue
        
    # Exclude 1000-multiplied tokens and other known memes
    if symbol in meme_symbols or symbol.startswith('1000'):
        continue
        
    # Exclude any symbol with chinese characters or weird lengths
    if not symbol.replace('USDT', '').isalnum():
        continue
        
    # > $5M volume
    if volume > 5_000_000:
        valid_symbols.append((symbol.replace('USDT', '/USDT'), volume))

# Sort by volume descending
valid_symbols.sort(key=lambda x: x[1], reverse=True)

# Select top 200
top_200 = [x[0] for x in valid_symbols[:200]]

assets['TOP_CRYPTO_SCAN'] = top_200

with open(assets_path, 'w', encoding='utf-8') as f:
    json.dump(assets, f, indent=2)

print(f"Updated TOP_CRYPTO_SCAN with {len(top_200)} symbols.")
