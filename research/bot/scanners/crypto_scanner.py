import logging
from config import TOP_CRYPTO_SCAN
import data_sources
from research.market_predictor import predict_future, evaluate_model_accuracy

logger = logging.getLogger("research.bot.scanners.crypto")

def run_crypto_scan():
    """Kripto para piyasalarında TimesFM tahmini ve trend/RSI taraması yapar."""
    results = []
    for symbol in TOP_CRYPTO_SCAN:
        try:
            # 1h verisini çek
            df_1h = data_sources.get_crypto_1h_data(symbol)
            if df_1h is None or df_1h.empty or len(df_1h) < 150:
                continue
            
            close = df_1h['close'].iloc[-1]
            ema_20 = df_1h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            ema_50 = df_1h['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            
            # RSI hesaplama
            delta = df_1h['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = (100 - (100 / (1 + rs))).iloc[-1]
            
            # MAPE Optimizasyonu
            best_mape = float('inf')
            best_c = 64
            for c in [64, 128]:
                mape = evaluate_model_accuracy(
                    symbol=symbol,
                    asset_type='crypto',
                    interval='1h',
                    context_len=c,
                    horizon_len=24,
                    preloaded_dfs=(None, None, df_1h)
                )
                if mape is not None and mape < best_mape:
                    best_mape = mape
                    best_c = c
                    
            if best_mape == float('inf'):
                best_mape = 0.0
                
            res = predict_future(
                symbol=symbol,
                asset_type='crypto',
                context_len=best_c,
                horizon_len=24,
                show_plot=False,
                save_plot=True,
                interval='1h',
                preloaded_dfs=(None, None, df_1h)
            )
            
            if res and res[0]:
                image_path, final_pred, pct_change, _ = res
                results.append({
                    'symbol': symbol,
                    'price': close,
                    'final_pred': final_pred,
                    'pct_change': pct_change,
                    'mape': best_mape,
                    'best_context': best_c,
                    'ema_20': ema_20,
                    'ema_50': ema_50,
                    'rsi': rsi,
                    'image_path': image_path
                })
        except Exception as e:
            logger.error(f"Scan error for {symbol}: {e}")
    
    # Trend ve indikatör filtreleriyle adayları ayır
    long_candidates = []
    short_candidates = []
    
    for item in results:
        is_bullish = item['price'] > item['ema_20']
        is_bearish = item['price'] < item['ema_20']
        
        if item['pct_change'] > 0 and is_bullish and item['rsi'] < 70:
            long_candidates.append(item)
        elif item['pct_change'] < 0 and is_bearish and item['rsi'] > 30:
            short_candidates.append(item)
    
    # Sırala
    long_candidates.sort(key=lambda x: x['pct_change'], reverse=True)
    short_candidates.sort(key=lambda x: x['pct_change'])
    
    # Yetersiz aday durumunda yedekleri kullan
    if len(long_candidates) < 3:
        fallback_longs = [r for r in results if r['pct_change'] > 0 and r not in long_candidates]
        fallback_longs.sort(key=lambda x: x['pct_change'], reverse=True)
        long_candidates.extend(fallback_longs)
        
    if len(short_candidates) < 3:
        fallback_shorts = [r for r in results if r['pct_change'] < 0 and r not in short_candidates]
        fallback_shorts.sort(key=lambda x: x['pct_change'])
        short_candidates.extend(fallback_shorts)
        
    return long_candidates[:3], short_candidates[:3]
