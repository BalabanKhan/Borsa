import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Proje kök dizinini Python path'e ekleyelim
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

import data_sources

def predict_future(symbol, asset_type='crypto', context_len=128, horizon_len=14, show_plot=True, save_plot=True, interval='1d'):
    """
    Belirtilen sembol için güncel veriyi çeker ve TimesFM ile gelecekteki 'horizon_len' 
    günlük tahmini yapar.
    """
    print(f"[{symbol}] Güncel veriler çekiliyor...")
    
    if asset_type == 'bist':
        df_1d, df_4h, df_1h = data_sources.get_bist_data(symbol)
        if interval == '1h' and df_1h is not None:
            df_use = df_1h
        elif interval == '4h' and df_4h is not None:
            df_use = df_4h
        else:
            df_use = df_1d
    else:
        df_1d, df_4h = data_sources.get_crypto_data(symbol)
        if interval == '4h' and df_4h is not None:
            df_use = df_4h
        else:
            df_use = df_1d
            
    if df_use is None or df_use.empty:
        print(f"[{symbol}] Veri çekilemedi.")
        return None, None, None

    data = df_use['close'].values
    dates = df_use.index
    
    if len(data) < context_len:
        print(f"[{symbol}] Yeterli veri yok. Gerekli: {context_len}, Bulunan: {len(data)}")
        return None, None, None

    # Sadece en güncel veriyi model girdisi olarak alıyoruz
    recent_data = data[-context_len:]

    # 1. EMA Smoothing (Noise Reduction) - Sadece Günlük (1d) Veriler İçin
    if interval != '1h':
        ema_period = 3
        if len(recent_data) >= ema_period:
            # EMA hesaplama
            weights = np.exp(np.linspace(-1., 0., ema_period))
            weights /= weights.sum()
            # Sadece son kısımları yumuşat, başlarda yeterli veri yoksa normal kalsın
            smoothed_data = np.copy(recent_data)
            for i in range(ema_period - 1, len(recent_data)):
                smoothed_data[i] = np.dot(recent_data[i - ema_period + 1:i + 1], weights)
            recent_data = smoothed_data

    # 2. Logarithmic Transformation
    # Veriyi logaritmik uzaya alıyoruz (sıfır veya negatif fiyat varsayımı yok)
    recent_data_log = np.log(recent_data)

    try:
        import timesfm
        print("Model yükleniyor (google/timesfm-2.5-200m-pytorch)...")
        tfm = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
        tfm.compile(forecast_config=timesfm.configs.ForecastConfig(
            max_context=context_len,
            max_horizon=horizon_len
        ))
        
        print("Gelecek tahmini yapılıyor (Logaritmik)...")
        # Modele log dönüşümlü veriyi veriyoruz
        forecast_result = tfm.forecast(horizon_len, [recent_data_log])
        
        if isinstance(forecast_result, tuple):
            predicted_data_log = forecast_result[0][0]
        else:
            predicted_data_log = forecast_result[0]
            
        if len(predicted_data_log) > horizon_len:
            predicted_data_log = predicted_data_log[:horizon_len]
        elif len(predicted_data_log) < horizon_len:
            padding = np.linspace(predicted_data_log[-1], predicted_data_log[-1], horizon_len - len(predicted_data_log))
            predicted_data_log = np.concatenate([predicted_data_log, padding])

        # 3. Inverse Logarithmic Transformation
        # Çıktıyı tekrar normal fiyat uzayına çeviriyoruz
        predicted_data = np.exp(predicted_data_log)
        
    except ImportError:
        print("UYARI: timesfm kütüphanesi bulunamadı! 'pip install -r requirements-ai.txt' çalıştırdığınıza emin olun.")
        print("Simülasyon (Dummy) tahmin üretiliyor...")
        last_price = recent_data[-1]
        predicted_data = np.linspace(last_price, last_price * 1.05, horizon_len)

    last_price = data[-1]
    final_pred = predicted_data[-1]
    pct_change = ((final_pred - last_price) / last_price) * 100

    # Calculate RSI on 1d data for filtering
    current_rsi = 50.0
    try:
        if df_1d is not None and not df_1d.empty and len(df_1d) >= 15:
            import pandas_ta as ta
            df_1d_copy = df_1d.copy()
            df_1d_copy.ta.rsi(length=14, append=True)
            rsi_col = 'rsi_14' if 'rsi_14' in df_1d_copy.columns else 'RSI_14'
            if rsi_col in df_1d_copy.columns:
                current_rsi = df_1d_copy[rsi_col].iloc[-1]
    except Exception as e:
        print(f"[{symbol}] RSI hesaplanamadı: {e}")

    if not save_plot:
        return None, final_pred, pct_change, current_rsi

    # Görselleştirme - Koyu Tema (Dark Mode)
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor('#131722')
    ax.set_facecolor('#131722')
    
    plot_context = 60
    
    # Tarihleri al
    past_dates = dates[-plot_context:]
    df_plot = df_use.iloc[-plot_context:]
    
    last_date = dates[-1]
    if interval == '1h':
        future_dates = pd.date_range(start=last_date, periods=horizon_len+1, freq='h')[1:]
    else:
        if asset_type == 'bist':
            future_dates = pd.date_range(start=last_date, periods=horizon_len+1, freq='B')[1:]
        else:
            future_dates = pd.date_range(start=last_date, periods=horizon_len+1, freq='D')[1:]
    
    # 2. Mum Grafiği veya Çizgi Grafiği
    if interval == '1h':
        # Saatlik seans için sade ve şık çizgi grafiği (Line Chart)
        ax.plot(df_plot.index, df_plot['close'], color='#00E676', linewidth=2.5, label="Fiyat", zorder=3)
        # Çizginin altını hafifçe doldurarak modern bir görünüm verelim (Gradient/Area efekti)
        ax.fill_between(df_plot.index, df_plot['close'], df_plot['close'].min() * 0.99, color='#00E676', alpha=0.08, zorder=2)
    else:
        # Mum Grafiği (Candlestick)
        color_up = '#00E676'   # Neon yeşil
        color_down = '#FF1744' # Neon kırmızı
        up = df_plot[df_plot['close'] >= df_plot['open']]
        down = df_plot[df_plot['close'] < df_plot['open']]
        
        # Bar genişliği ayarı (Matplotlib tarih ekseni gün bazlı çalıştığı için)
        if interval == '4h':
            bar_width = 0.100  # ~2.4 saat (4 saatin %60'ı)
        else:
            bar_width = 0.600  # ~14.4 saat (1 günün %60'ı)
            
        ax.bar(up.index, up['close'] - up['open'], bar_width, bottom=up['open'], color=color_up, zorder=3)
        ax.vlines(up.index, up['low'], up['high'], color=color_up, linewidth=1, zorder=2)
        
        ax.bar(down.index, down['open'] - down['close'], bar_width, bottom=down['close'], color=color_down, zorder=3)
        ax.vlines(down.index, down['low'], down['high'], color=color_down, linewidth=1, zorder=2)

    # 4. Kopukluğu Giderme
    last_price = data[-1]
    connected_dates = [last_date] + list(future_dates)
    connected_preds = [last_price] + list(predicted_data)

    # Tahmin Çizgisi
    time_unit = "Gün" if interval == '1d' else ("Saat" if interval in ('1h', '4h') else "Bar")
    ax.plot(connected_dates, connected_preds, label=f"TimesFM Tahmini ({horizon_len} {time_unit})", color='#2962FF', linewidth=2, linestyle='dashed', zorder=4)

    # 3. Tahmin Bandı (Confidence Interval) +/- %4
    lower_bound = np.array(connected_preds) * 0.96
    upper_bound = np.array(connected_preds) * 1.04
    ax.fill_between(connected_dates, lower_bound, upper_bound, color='#2962FF', alpha=0.15, zorder=1)

    # 5. Grafik Üzeri Metinler (Annotations)
    final_pred = connected_preds[-1]
    pct_change = ((final_pred - last_price) / last_price) * 100
    
    # Güncel fiyat çizgisi ve etiketi
    ax.axhline(last_price, color='gray', linestyle='--', linewidth=1, alpha=0.5)
    ax.text(past_dates[0], last_price, f" Güncel: {last_price:.2f}", color='white', verticalalignment='bottom', fontsize=10)

    # Hedef Tahmin Noktası
    ax.scatter([connected_dates[-1]], [final_pred], color='#2962FF', s=50, zorder=5)
    
    # Metni okunabilir yapmak için pozisyon ayarı
    text_color = '#00E676' if pct_change >= 0 else '#FF1744'
    ax.text(connected_dates[-1], final_pred, f"Hedef: {final_pred:.2f} ({pct_change:+.1f}%)", color=text_color, verticalalignment='bottom', horizontalalignment='right', fontsize=10, fontweight='bold')

    type_str = "Günlük" if interval == '1d' else ("Saatlik" if interval == '1h' else "4 Saatlik")
    ax.set_title(f"{symbol} - TimesFM Canlı Piyasa Tahmini ({type_str})", color='white', fontsize=14)
    ax.set_xlabel("Tarih", color='lightgray')
    ax.set_ylabel("Fiyat", color='lightgray')
    ax.tick_params(colors='lightgray')
    
    ax.legend(facecolor='#131722', edgecolor='gray', labelcolor='white')
    ax.grid(True, color='gray', linestyle='--', alpha=0.2)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Sonucu research klasörüne kaydet
    safe_symbol = symbol.replace('/', '_')
    output_file = os.path.join(current_dir, f"{safe_symbol}_prediction.png")
    plt.savefig(output_file)
    print(f"[{symbol}] Tahmin grafiği kaydedildi: {output_file}")
    
    if show_plot:
        plt.show()
    
    # Arka planda bellek sızıntısını önlemek için grafiği kapat
    plt.close()
    
    return output_file, final_pred, pct_change, current_rsi

def evaluate_model_accuracy(symbol, asset_type='bist', interval='1h', context_len=60, horizon_len=7):
    """
    Geçmiş verinin son kısmını test seti (actual) olarak ayırıp modelin hata oranını (MAPE) hesaplar.
    Düşük MAPE, modelin o hisseyi daha iyi 'anladığı' anlamına gelir.
    """
    if asset_type == 'bist':
        df_1d, df_4h, df_1h = data_sources.get_bist_data(symbol)
        df_use = df_1h if interval == '1h' else df_1d
    else:
        df_1d, df_4h = data_sources.get_crypto_data(symbol)
        df_use = df_4h if interval == '4h' else df_1d

    if df_use is None or df_use.empty:
        return None

    data = df_use['close'].values
    
    total_needed = context_len + horizon_len
    if len(data) < total_needed:
        return None

    # Veriyi Train ve Test olarak ikiye ayır
    train_data = data[-total_needed : -horizon_len]
    actual_future = data[-horizon_len:]

    train_data_log = np.log(train_data)

    try:
        import timesfm
        tfm = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
        tfm.compile(forecast_config=timesfm.configs.ForecastConfig(
            max_context=context_len,
            max_horizon=horizon_len
        ))
        
        forecast_result = tfm.forecast(horizon_len, [train_data_log])
        if isinstance(forecast_result, tuple):
            predicted_log = forecast_result[0][0]
        else:
            predicted_log = forecast_result[0]
            
        if len(predicted_log) > horizon_len:
            predicted_log = predicted_log[:horizon_len]
            
        predicted = np.exp(predicted_log)
        
        # MAPE (Mean Absolute Percentage Error) Hesapla
        mape = np.mean(np.abs((actual_future - predicted) / actual_future)) * 100
        return mape

    except Exception as e:
        print(f"[{symbol}] Hata hesaplanırken sorun oluştu: {e}")
        return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TimesFM Canlı Tahmin Aracı")
    parser.add_argument("--symbol", type=str, default="BTC/USDT", help="Tahmin edilecek sembol (Örn: THYAO.IS, BTC/USDT)")
    parser.add_argument("--type", type=str, default="crypto", choices=["crypto", "bist", "emtia"], help="Varlık türü")
    parser.add_argument("--context", type=int, default=128, help="Modele verilecek geçmiş gün sayısı")
    parser.add_argument("--horizon", type=int, default=14, help="Tahmin edilecek gelecek gün sayısı")
    args = parser.parse_args()

    print("=== TimesFM Canlı Tahmin Aracı ===")
    print("Not: Bu araç yatırım tavsiyesi değildir, sadece deneysel AI tahminleri sunar.")
    
    predict_future(symbol=args.symbol, asset_type=args.type, context_len=args.context, horizon_len=args.horizon)
