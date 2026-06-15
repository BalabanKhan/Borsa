#!/bin/bash
# Bu betik günlük rapor komutunu crontab'a ekler
# Her gün Türkiye saati ile 23:55'te (Sunucu UTC ise saati ona göre ayarlamış olursunuz, burada 23:55 UTC referans alınmıştır)

CRON_JOB="55 23 * * * cd /home/hib0796/quant_bot && /home/hib0796/quant_bot/venv/bin/python daily_report.py >> /home/hib0796/quant_bot/daily_report.log 2>&1"

# Mevcut crontab'ı kontrol et ve zaten yoksa ekle
(crontab -l 2>/dev/null | grep -v "daily_report.py"; echo "$CRON_JOB") | crontab -

echo "✅ Günlük rapor Telegram görevi başarıyla crontab'a eklendi!"
echo "Her gün 23:55'te rapor Telegram'a gönderilecektir."
