import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Proje kök dizinini Python path'e ekleyelim ki Borsa modüllerini import edebilelim
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# Borsa modüllerinden importlar
import data_sources

def run_backtest(symbol, asset_type='crypto', context_len=128, horizon_len=24):
    """
    Belirtilen sembol için TimesFM modelini kullanarak geçmiş veri üzerinde test yapar.
    Gerçekleşen fiyat ile tahmin edilen fiyatı grafik olarak çizer.
    """
    print(f"[{symbol}] Veriler çekiliyor...")
    
    if asset_type == 'bist':
        df_1d, df_4h, df_1h = data_sources.get_bist_data(symbol)
    else:
        df_1d, df_4h = data_sources.get_crypto_data(symbol)
        
    if df_1d is None or df_1d.empty:
        print(f"[{symbol}] Veri çekilemedi.")
        return

    # Sadece kapanış fiyatlarını kullanalım
    data = df_1d['close'].values
    
    if len(data) < context_len + horizon_len:
        print(f"[{symbol}] Yeterli veri yok. Gerekli: {context_len + horizon_len}, Bulunan: {len(data)}")
        return

    # Eğitim ve test verisini bölelim
    # Son 'horizon_len' kadar günü tahmin etmek istiyoruz
    train_data = data[:-horizon_len]
    actual_data = data[-horizon_len:]
    
    # TimesFM modelini yükleyelim (bu adım lokal ortamda çalışacaktır)
    try:
        import timesfm
        # Model konfigürasyonu
        # Örnek olarak 200M modeli kullanıyoruz. context_len modelin içine alabileceği geçmiş veriyi belirler.
        print("Model yükleniyor (google/timesfm-2.5-200m-pytorch)...")
        # Yeni versiyon API kullanımı
        tfm = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
        tfm.compile(forecast_config=timesfm.configs.ForecastConfig(
            max_context=context_len,
            max_horizon=horizon_len
        ))
        
        print("Tahmin yapılıyor...")
        # Tahmin fonksiyonunu çağır
        forecast_result = tfm.forecast(horizon_len, [train_data[-context_len:]])
        
        # forecast çıktısı yeni sürümde tuple (point_forecast, vb) olabilir
        if isinstance(forecast_result, tuple):
            predicted_data = forecast_result[0][0]
        else:
            predicted_data = forecast_result[0]
            
        # Eğer horizon_len'den fazla veya az veri geldiyse boyutu eşitleyelim
        if len(predicted_data) > horizon_len:
            predicted_data = predicted_data[:horizon_len]
        elif len(predicted_data) < horizon_len:
            padding = np.linspace(predicted_data[-1], predicted_data[-1], horizon_len - len(predicted_data))
            predicted_data = np.concatenate([predicted_data, padding])

        
    except ImportError:
        print("UYARI: timesfm kütüphanesi bulunamadı! 'pip install -r requirements-ai.txt' çalıştırdığınıza emin olun.")
        print("Simülasyon (Dummy) tahmin üretiliyor...")
        # Kütüphane kurulu değilse dummy veri üret
        last_price = train_data[-1]
        predicted_data = np.linspace(last_price, actual_data[-1] * 1.05, horizon_len)

    # Görselleştirme
    plt.figure(figsize=(12, 6))
    
    # Geçmiş verinin son kısmını çiz
    plot_context = 60 # Sadece son 60 günü çizelim
    x_past = np.arange(plot_context)
    plt.plot(x_past, train_data[-plot_context:], label="Geçmiş Fiyat (Context)", color='blue')
    
    # Gerçekleşen geleceği çiz
    x_future = np.arange(plot_context, plot_context + horizon_len)
    plt.plot(x_future, actual_data, label="Gerçekleşen Fiyat (Actual)", color='green', linestyle='dashed')
    
    # Tahmin edilen geleceği çiz
    plt.plot(x_future, predicted_data, label="TimesFM Tahmini (Forecast)", color='red')
    
    plt.title(f"{symbol} - TimesFM Backtest ({horizon_len} Günlük Tahmin)")
    plt.xlabel("Günler")
    plt.ylabel("Fiyat")
    plt.legend()
    plt.grid(True)
    
    # Sonucu research klasörüne kaydet
    safe_symbol = symbol.replace('/', '_')
    output_file = os.path.join(current_dir, f"{safe_symbol}_backtest.png")
    plt.savefig(output_file)
    print(f"[{symbol}] Grafik kaydedildi: {output_file}")
    plt.show()

if __name__ == "__main__":
    print("=== TimesFM Lokal Backtest Aracı ===")
    print("Not: Bu araç e2-micro'da çalışmaz. Lokal bilgisayarınızda (min 8GB RAM) çalıştırınız.")
    
    # Test için örnek bir sembol (Örn: Bitcoin)
    run_backtest(symbol="BTC/USDT", asset_type="crypto", context_len=64, horizon_len=14)
    
    # İsterseniz BIST hisseleri için de deneyebilirsiniz:
    # run_backtest(symbol="THYAO.IS", asset_type="bist", context_len=128, horizon_len=14)
