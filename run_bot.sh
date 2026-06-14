#!/bin/bash
cd /home/hib0796/quant_bot

# 1. Eğer eski dashboard veya bot süreçleri varsa temizle
pkill -f dashboard.py || true

# 2. Web Dashboard'ı arka planda başlat (port 8080)
/home/hib0796/quant_bot/venv/bin/python -u dashboard.py >> /home/hib0796/quant_bot/dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "[$(date)] Web Dashboard port 8080 uzerinde baslatildi (PID: $DASHBOARD_PID)." >> /home/hib0796/quant_bot/bot.log

# 3. Ana Trading Botunu döngü halinde başlat
while true; do
    /home/hib0796/quant_bot/venv/bin/python -u main.py >> /home/hib0796/quant_bot/bot.log 2>&1
    echo "[$(date)] Bot durdu veya coktu. 30 saniye icinde yeniden baslatiliyor..." >> /home/hib0796/quant_bot/bot.log
    sleep 30
done
