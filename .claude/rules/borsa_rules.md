# Borsa / Kripto Trading Bot Geliştirme Kuralları (Borsa Rules)

Bu kurallar, Borsa uygulamasının mimari, güvenlik ve kod kalitesi standartlarını korumak amacıyla tasarlanmıştır. Bu projede yapılan tüm geliştirmelerde aşağıdaki kurallara uyulması zorunludur:

## 1. Hata Yutma Yasağı (No Silent Exception Swallowing)
- Asla bare `except: pass` veya `except Exception: pass` yazılmamalıdır.
- Tüm hata durumları loglanmalı ya da `core/defensive_engine.py` altındaki `DefensiveExceptionManager.swallow_safely` ile limitli şekilde yönetilmelidir. Hata limiti aşıldığında sistem otomatik olarak şalteri indirir.

## 2. Veri Bütünlüğü ve NaN/None Koruması (Anti-Hallucination)
- API veya yfinance'den gelen verilerin NaN veya None değerleri içermesi durumunda varsayılan değerlerle bota tahmin yaptırmak (halüsinasyon) yasaktır.
- İşleme girmeden önce `data_guard.validate_indicators_integrity` veya `validate_ohlcv_integrity` kontrolleri çalıştırılmalıdır.

## 3. Kaynak Sızıntılarını Önleme (Resource Leak Prevention)
- Tüm dosya, socket veya veritabanı işlemlerinde `with` (context manager) ifadesi kullanılmalıdır.
- Durum (state) dosyaları yazılırken `DefensiveStateGuard.save_state_atomic` (geçici dosya + os.replace) metodu kullanılarak atomik disk işlemleri garanti edilmelidir.

## 4. Karmaşıklık Sınırı (Cyclomatic Complexity Limit)
- Radon notu E veya F olan devasa "God" fonksiyonlar yazılması yasaktır.
- Fonksiyonlar tek bir mantıksal sorumlulukla sınırlandırılmalı ve Radon skoru en fazla B (skor < 20) seviyesinde tutulmalıdır.

## 5. Karakter Kodlama Standartları (UTF-8 without BOM)
- Kod dosyaları her zaman BOM (Byte Order Mark) içermeyen standart UTF-8 formatında kaydedilmelidir.

## 6. Regex ve Kaçış Karakterleri (Raw Strings)
- Düzenli ifadeler (Regex) veya Windows dosya yolları tanımlanırken `invalid escape sequence` uyarılarını önlemek için `r"..."` (raw string) yapısı kullanılmalıdır.

## 7. HTTP İstek Güvenliği (HTTP Timeout Enforcement)
- `requests` veya `urllib` ile yapılan tüm dış HTTP isteklerinde mutlaka `timeout` parametresi belirtilmelidir (Örn: `requests.post(..., timeout=10)`).

## 8. Güvenli Şifre/Secret Yönetimi (No Hardcoded Secrets)
- Kod dosyalarında şifre, token veya API key hardcoded olarak yazılmamalıdır. Her zaman `.env` dosyasından yüklenmelidir.

## 9. Tek Kaynak Prensibi (SSOT)
- Tüm sihirli sayılar, limitler, katsayılar ve strateji parametreleri `config.py` içinde tanımlanmalıdır.

## 10. Test Odaklı Geliştirme (TDD)
- Her geliştirme veya refactor sonrasında birim testlerin (`python -m unittest discover`) kırılmadığı doğrulanmalıdır.
