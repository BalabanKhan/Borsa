import time
import sys
import os

try:
    import win32gui
    import win32con
    import win32api
    import win32ui
except ImportError:
    print("Gerekli kütüphaneler bulunamadı. Lütfen terminale şu komutu yazarak kurun:")
    print("pip install pywin32")
    sys.exit(1)

# Ayarlar
WINDOW_TITLE_SUBSTRING = "Borsa"  # VS Code pencere başlığında geçen kelime
CHECK_INTERVAL = 1.0  # Saniyede bir kontrol et.

# VS Code penceresine göre butonların yaklaşık koordinat oranları (Sağ ve alttan uzaklıkları)
TARGET_BUTTONS = [
    {"name": "Submit", "offset_x": 50, "offset_y": 40},       # Komut çalıştırma onay butonu
    {"name": "Accept All", "offset_x": 85, "offset_y": 110}   # Dosya değişiklikleri onay butonu
]

def find_vscode_hwnd():
    hwnd_list = []
    
    def enum_windows_callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if WINDOW_TITLE_SUBSTRING.lower() in title.lower():
                hwnd_list.append(hwnd)
        return True

    win32gui.EnumWindows(enum_windows_callback, None)
    return hwnd_list[0] if hwnd_list else None

def find_and_click_blue_button(hwnd):
    try:
        rect = win32gui.GetWindowRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        
        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC  = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(saveBitMap)
        
        import ctypes
        result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
        
        if result:
            # Sağ alt panel bölgesini tara (X: Sağdan 180 ile 15 piksel arası, Y: Alttan 140 ile 75 piksel arası)
            # Y limitini 75 yaparak en alttaki chat girdi alanındaki (mesaj gönderme) mavi butonu tarama dışı bırakıyoruz.
            start_x = max(0, w - 180)
            end_x = min(w - 15, w - 1)
            start_y = max(0, h - 140)
            end_y = min(h - 75, h - 1)
            
            for y in range(start_y, end_y + 1):
                for x in range(start_x, end_x + 1):
                    color = saveDC.GetPixel(x, y)
                    r = color & 0xff
                    g = (color >> 8) & 0xff
                    b = (color >> 16) & 0xff
                    
                    # Genişletilmiş mavi renk tanımı (Mavi belirgin şekilde baskın olmalı)
                    # VS Code mavi buton renkleri genellikle R: ~0-40, G: ~90-150, B: ~160-255 aralığındadır.
                    if b > 140 and r < 80 and b > r + 50:
                        # YAZI/LİNK KONTROLÜ: Butonlar katı mavi bloklardır.
                        # Tespit edilen pikselin 5x5'lik çevresinin de mavi olup olmadığını kontrol edelim.
                        # Bu sayede ince mavi yazılara (linkler, mentionlar) tıklanmasını engelleriz.
                        is_solid_block = True
                        for check_y in range(y, min(y + 5, end_y + 1)):
                            for check_x in range(x, min(x + 5, end_x + 1)):
                                n_color = saveDC.GetPixel(check_x, check_y)
                                nr = n_color & 0xff
                                ng = (n_color >> 8) & 0xff
                                nb = (n_color >> 16) & 0xff
                                if not (nb > 130 and nr < 90 and nb > nr + 40):
                                    is_solid_block = False
                                    break
                            if not is_solid_block:
                                break
                                
                        if is_solid_block:
                            # Temizlik
                            win32gui.DeleteObject(saveBitMap.GetHandle())
                            saveDC.DeleteDC()
                            mfcDC.DeleteDC()
                            win32gui.ReleaseDC(hwnd, hwndDC)
                            
                            print(f"[{time.strftime('%H:%M:%S')}] Katı mavi buton bloğu algılandı ({x}, {y}) [R:{r}, G:{g}, B:{b}]. Tıklanıyor...")
                            click_in_background(hwnd, x + 2, y + 2)
                            return True
            
            if int(time.time()) % 3 == 0:
                print(f"[{time.strftime('%H:%M:%S')}] Sağ alt alan taranıyor - Mavi buton bulunamadı.")
                
        # Temizlik
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)
        return False
    except Exception as e:
        if int(time.time()) % 3 == 0:
            print(f"HATA find_and_click_blue_button: {e}")
        return False

def click_in_background(hwnd, x, y):
    lParam = win32api.MAKELONG(x, y)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
    time.sleep(0.1)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)

def main():
    print("Windows Arka Plan Auto-Accept Bot (Gelişmiş Alan Taramalı) başlatılıyor...")
    print(f"Başlıkta '{WINDOW_TITLE_SUBSTRING}' aranan pencere takip ediliyor.")
    print("Sağ alt köşedeki tüm mavi onay butonları taranır.")
    print("Çıkış için CTRL+C tuşlarına basın.\n")

    try:
        while True:
            hwnd = find_vscode_hwnd()
            if hwnd:
                if not win32gui.IsIconic(hwnd):
                    # Alan içinde mavi butonu bul ve tıkla
                    if find_and_click_blue_button(hwnd):
                        time.sleep(1.0) # Peş peşe tıklamaları engellemek için bekle
            else:
                print(f"[{time.strftime('%H:%M:%S')}] VS Code penceresi bulunamadı.")
            
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\nBot durduruldu. İyi günler!")

if __name__ == "__main__":
    main()

