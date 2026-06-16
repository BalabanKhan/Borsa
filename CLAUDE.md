# Borsa / Kripto Tarama Sistemi — Demir Kılavuz (Iron Guide)

Bu dosya, projenin yapısal bütünlüğünü korumak ve geliştirme standartlarını belirlemek amacıyla oluşturulmuştur.

## Komutlar

- **Tarama Çalıştırma (BIST ve Kripto):** `venv\Scripts\python test_strats_v5.py`
- **Soft Skor Testleri:** `venv\Scripts\python verify_soft_scores.py`

## Mimari Kurallar (V5.0 Anayasası)

### KURAL 1: Boolean Dönüş Yasağı (No Boolean Returns)
- Strateji modülleri (`strategies/*.py`) içerisinde, indikatör durumlarını kontrol eden katı boolean `if-else` kararlarıyla veya `return None` şeklinde veto / filtre uygulanması yasaktır.
- Tüm filtre ve onay durumları `conviction_scorer.py` içindeki fuzzy/soft skorlama mantığına delege edilmelidir.
- Aday işlemler 0-100 arası yumuşak puanlanmalı ve nihai karar **Conviction Score** ve **Grade** üzerinden verilmelidir.

### KURAL 6: Tek Kaynak Prensibi (Config SSOT)
- Tüm sihirli sayılar, eşikler, limitler ve katsayılar `config.py` içinde tanımlanmalıdır.
- Kod blokları içinde sabit tanımlamaları yapılmamalı, `config` modülü üzerinden okunmalıdır.

## Sniper (Keskin Nişancı) Stratejisi
- **SHORT-4 (Keskin Nişancı SHORT):** İstatistiksel 3 Kanun (BBW Squeeze, BBP Pullback, FVG/SFP Likidite Avı) temelinde çalışan stratejidir.
- **Kripto Kısıtı:** Bu strateji **sadece kripto varlıklar** için çalışır (`strategies/crypto.py`).
- **Skorlama:** Sert veto filtreleri yerine, tolerans sınırları dahilinde soft ve dinamik cezalandırma (`score_bbw_squeeze`, `score_percent_b`, `score_fvg_sfp` fonksiyonları üzerinden `build_sniper_scores`) uygulanır.
