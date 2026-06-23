# Borsa (Quant Bot) - Sunucu Komutları

Bu dosya, botun barındırıldığı Ubuntu Linux sunucusunda (Sanal Makine) kullanılabilecek temel komutları içermektedir.

## 1. Kodu Güncellemek (Github'dan Çekmek)
Windows tarafında yaptığınız kod güncelliklerini sunucuya almak için proje klasöründe (`/home/hib0796/quant_bot/`) şu komutu çalıştırın:
```bash
git pull
```

## 2. Sistemi (Arka Plan Servisini) Yeniden Başlatmak
Otomatik çalışan botu en güncel haliyle sıfırdan yeniden başlatmak için:
```bash
systemctl --user restart quant_bot
```
*(Not: Eğer yetki hatası alırsanız `sudo systemctl restart quant_bot` komutunu deneyin.)*

## 3. Logları Canlı Olarak İzlemek
Botun arka planda ne yaptığını (aldığı sinyalleri, hataları vs.) canlı terminalde izlemek için:
```bash
tail -f bot.log
```
*(Çıkmak için klavyeden `CTRL + C` tuşlarına basabilirsiniz.)*

## 4. Manuel Olarak Tarama Başlatmak
Botu servisten bağımsız, anlık olarak kendiniz tarama yapmak için (UTF-8 formatında Türkçe karakter hatası almadan):

**Eğer Sanal Ortam (venv) aktif değilse, önce:**
```bash
source venv/bin/activate
```

**Sadece Kripto için Manuel Tarama:**
```bash
PYTHONIOENCODING=utf-8 python run_scan_once.py crypto
```

**Tüm Piyasalar (BIST + Kripto) için Manuel Tarama:**
```bash
PYTHONIOENCODING=utf-8 python run_scan_once.py
```
