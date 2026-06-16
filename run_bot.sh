#!/bin/bash
cd /home/hib0796/quant_bot

# 1. Eski tüm bot, dashboard ve diğer run_bot.sh döngülerini temizle (Çift mesajı engellemek için)
pkill -f main.py || true
pkill -f dashboard.py || true

# Kendi PID'imiz ($$) hariç diğer tüm run_bot.sh süreçlerini sonlandır
for pid in $(pgrep -f run_bot.sh); do
    if [ "$pid" != "$$" ]; then
        kill -9 "$pid" 2>/dev/null || true
    fi
done

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
