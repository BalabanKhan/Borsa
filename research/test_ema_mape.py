import os
import sys
import numpy as np
import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

import data_sources

def test_ema_mape(symbol="BTC/USDT", asset_type="crypto", interval="1d", context_len=128, horizon_len=14):
    print(f"=== {symbol} için Farklı EMA Periyotlarında MAPE Testi ===")
    
    if asset_type == 'bist':
        df_1d, df_4h, df_1h = data_sources.get_bist_data(symbol)
        df_use = df_1h if interval == '1h' else df_1d
    else:
        if interval == '1h':
            df_use = data_sources.get_crypto_1h_data(symbol)
        else:
            df_1d, df_4h = data_sources.get_crypto_data(symbol)
            df_use = df_4h if interval == '4h' else df_1d

    if df_use is None or df_use.empty:
        print(f"[{symbol}] Veri çekilemedi.")
        return

    data = df_use['close'].values
    
    total_needed = context_len + horizon_len
    if len(data) < total_needed:
        print(f"[{symbol}] Yeterli veri yok.")
        return

    # Veriyi Train ve Test olarak ikiye ayır
    train_data_raw = data[-total_needed : -horizon_len]
    actual_future = data[-horizon_len:]

    try:
        from research.market_predictor import get_timesfm_model
        tfm = get_timesfm_model()
    except Exception as e:
        print(f"Model yüklenemedi: {e}")
        return

    ema_periods_to_test = [1, 3, 5, 10, 20, 50, 100, 200]
    
    results = []

    for ema_period in ema_periods_to_test:
        train_data = np.copy(train_data_raw)
        
        # EMA Smoothing uygula
        if ema_period > 1 and len(train_data) >= ema_period:
            weights = np.exp(np.linspace(-1., 0., ema_period))
            weights /= weights.sum()
            smoothed_data = np.copy(train_data)
            for i in range(ema_period - 1, len(train_data)):
                smoothed_data[i] = np.dot(train_data[i - ema_period + 1:i + 1], weights)
            train_data = smoothed_data

        train_data_log = np.log(train_data)
        
        try:
            forecast_result = tfm.forecast(horizon_len, [train_data_log])
            if isinstance(forecast_result, tuple):
                predicted_log = forecast_result[0][0]
            else:
                predicted_log = forecast_result[0]
                
            if len(predicted_log) > horizon_len:
                predicted_log = predicted_log[:horizon_len]
                
            predicted = np.exp(predicted_log)
            
            mape = np.mean(np.abs((actual_future - predicted) / actual_future)) * 100
            print(f"EMA Periyodu: {ema_period:3d} -> MAPE: %{mape:.2f}")
            results.append((ema_period, mape))
        except Exception as e:
            print(f"EMA {ema_period} için hata: {e}")

    if results:
        best_ema = min(results, key=lambda x: x[1])
        print(f"\nEN AZ HATA PAYI: EMA {best_ema[0]} (MAPE: %{best_ema[1]:.2f})")

if __name__ == "__main__":
    test_ema_mape(symbol="BTC/USDT", asset_type="crypto", interval="1d", context_len=128, horizon_len=14)
    test_ema_mape(symbol="ETH/USDT", asset_type="crypto", interval="1d", context_len=128, horizon_len=14)
