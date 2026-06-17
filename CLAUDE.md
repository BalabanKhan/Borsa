# Borsa / Kripto Tarama Sistemi — Demir Kılavuz (Iron Guide)

Bu dosya, projenin yapısal bütünlüğünü korumak ve geliştirme standartlarını belirlemek amacıyla oluşturulmuştur.

## Komutlar

- **Tarama Çalıştırma (BIST ve Kripto):** `venv\Scripts\python test_strats_v5.py`
- **Soft Skor Testleri:** `venv\Scripts\python verify_soft_scores.py`
- **Birim Testleri Çalıştırma:** `venv\Scripts\python -m unittest discover`
- **Kod Karmaşıklığı Analizi (Radon):** `venv\Scripts\python -m radon cc . -a`
- **Sözdizimi & Stil Denetimi (Flake8):** `venv\Scripts\python -m flake8 . --exclude=venv,backups,antigravity-panel,scratch`

## Mimari Kurallar (V6.0 Anayasası)

### KURAL 1: Boolean Dönüş Yasağı (No Boolean Returns)
- Strateji modülleri (`strategies/*.py`) içerisinde, indikatör durumlarını kontrol eden katı boolean `if-else` kararlarıyla veya `return None` şeklinde veto / filtre uygulanması yasaktır.
- Tüm filtre ve onay durumları `conviction_scorer.py` içindeki fuzzy/soft skorlama mantığına delege edilmelidir.
- Aday işlemler 0-100 arası yumuşak puanlanmalı ve nihai karar **Conviction Score** ve **Grade** üzerinden verilmelidir.

### KURAL 2: Hata Yutma Yasağı (No Silent Exception Swallowing)
- Hataları `except: pass` veya `except Exception: pass` şeklinde sessizce yutmak kesinlikle yasaktır.
- Beklenmedik hata olasılıkları için her zaman `logging` kullanılmalı veya hatalar [defensive_engine.py](file:///c:/Users/YSR_MONSTER/.antigravity/Borsa/core/defensive_engine.py) içindeki `DefensiveExceptionManager.swallow_safely` üzerinden yönetilmelidir.
- Ardışık hata kotası aşıldığında sistem otomatik olarak şalteri indirip güvenli moda geçmelidir.

### KURAL 3: Veri Bütünlüğü & NaN/None Koruması (Anti-Hallucination)
- API'den veya yfinance'den gelen verilerin NaN veya None olması durumunda bota işlem açtırmak veya varsayılan değerlerle bota işlem tahmini yaptırmak (halüsinasyon) yasaktır.
- İşleme girmeden önce mutlaka [data_guard.py](file:///c:/Users/YSR_MONSTER/.antigravity/Borsa/data_guard.py) üzerindeki bütünlük doğrulamaları (`validate_indicators_integrity`, `validate_ohlcv_integrity`) çağrılmalıdır.

### KURAL 4: Kaynak Güvenliği & Atomik Disk İşlemleri (Resource Leak Prevention)
- Dosya veya veri tabanı işlemlerinde `with` context manager kullanılması zorunludur. Kapatılmamış dosya/bağlantı akışı (resource leak) bırakılamaz.
- Durum (state) dosyaları doğrudan yazılmamalı, kesinti anında verinin bozulmasını önlemek için `DefensiveStateGuard.save_state_atomic` (geçici dosya + os.replace) üzerinden atomik olarak diske yazılmalıdır.

### KURAL 5: Karmaşıklık ve Modülerlik Sınırı (Cyclomatic Complexity Limit)
- Radon notu **E** veya **F** olan, tek başına birden fazla iş yapan "God Function" (Devasa Fonksiyon) yazılması yasaktır.
- Yazılan her fonksiyon tek bir mantıksal sorumluluğa sahip olmalı ve Radon skorunun en fazla **B** (skor < 20) olması sağlanmalıdır.

### KURAL 6: Tek Kaynak Prensibi (Config SSOT)
- Tüm sihirli sayılar, eşikler, limitler ve katsayılar `config.py` içinde tanımlanmalıdır.
- Kod blokları içinde sabit tanımlamaları yapılmamalı, `config` modülü üzerinden okunmalıdır.

### KURAL 7: Karakter Kodlama Standartları (UTF-8 without BOM)
- Yeni oluşturulan veya düzenlenen tüm kod dosyaları **BOM içermeyen standart UTF-8 (UTF-8 without BOM)** kodlamasıyla kaydedilmelidir.

### KURAL 8: Regex ve Kaçış Karakter Standartları (Raw Strings)
- Düzenli ifadeler (Regex) veya ters eğik çizgi (`\`) içeren dizgiler (örn. Windows dosya yolları) tanımlanırken `r"..."` (raw string) yapısı kullanılmalıdır. Geçersiz kaçış dizisi (`invalid escape sequence`) uyarılarına yol açacak standart dizgiler yazılması yasaktır.

### KURAL 9: HTTP İstek Güvenliği (HTTP Timeout Enforcement)
- `requests` veya `urllib` ile yapılan tüm dış HTTP çağrılarında mutlaka `timeout` parametresi belirtilmelidir (Örn: `requests.post(..., timeout=10)`). Timeout belirtilmeyen, sonsuz kilitlenmeye müsait istekler yasaktır.

### KURAL 10: Güvenli Şifre/Secret Yönetimi (No Hardcoded Secrets)
- Kod dosyalarında asla şifre, API anahtarı veya gizli anahtar (secret) hardcoded olarak yazılmamalıdır. Her zaman `.env` dosyasından okunmalıdır.

## Sniper (Keskin Nişancı) Stratejisi
- **SHORT-4 (Keskin Nişancı SHORT):** İstatistiksel 3 Kanun (BBW Squeeze, BBP Pullback, FVG/SFP Likidite Avı) temelinde çalışan stratejidir.
- **Kripto Kısıtı:** Bu strateji **sadece kripto varlıklar** için çalışır (`strategies/crypto.py`).
- **Skorlama:** Sert veto filtreleri yerine, tolerans sınırları dahilinde soft ve dinamik cezalandırma (`score_bbw_squeeze`, `score_percent_b`, `score_fvg_sfp` fonksiyonları üzerinden `build_sniper_scores`) uygulanır.
