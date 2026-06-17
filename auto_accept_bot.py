import time
import sys
import os

try:
    import pyautogui
except ImportError:
    print("pyautogui kütüphanesi bulunamadı. Lütfen 'python -m pip install pyautogui opencv-python pillow' komutuyla kurun.")
    sys.exit(1)

# Ayarlar
TARGET_IMAGE = 'run_button.png'
CONFIDENCE = 0.8  # Eşleşme hassasiyeti (0.8 = %80 benzerlik). Gerekirse artırın veya azaltın.
CHECK_INTERVAL = 1.0  # Saniyede bir kontrol et.

def main():
    print("Auto-Accept Bot başlatılıyor...")
    if not os.path.exists(TARGET_IMAGE):
        print(f"\nHATA: '{TARGET_IMAGE}' dosyası bulunamadı!")
        print("LÜTFEN ŞUNU YAPIN:")
        print("1. Ekrandaki 'Run' veya 'Accept' butonunun SADECE kendisinin küçük bir ekran görüntüsünü alın (Win+Shift+S kullanabilirsiniz).")
        print(f"2. Bu görüntüyü uygulamanın bulunduğu bu klasöre ({os.getcwd()}) '{TARGET_IMAGE}' adıyla kaydedin.")
        print("3. Uygulamayı tekrar çalıştırın.\n")
        sys.exit(1)
        
    print(f"'{TARGET_IMAGE}' ekranda aranıyor... (Kapatmak için CTRL+C tuşlarına basın)")
    
    try:
        while True:
            try:
                # Ekranda hedef görseli ara (opencv gerekir)
                location = pyautogui.locateCenterOnScreen(TARGET_IMAGE, confidence=CONFIDENCE)
                
                if location:
                    print(f"[{time.strftime('%H:%M:%S')}] Buton bulundu! Tıklanıyor: {location}")
                    # Butona tıkla
                    pyautogui.click(location.x, location.y)
                    # Art arda çok fazla tıklamayı engellemek için biraz bekle
                    time.sleep(1.5)
            except pyautogui.ImageNotFoundException:
                pass # Ekranda bulunamadı, devam et
            except Exception as e:
                # opencv yüklü değilse confidence olmadan da şansımızı deneyelim
                try:
                    location = pyautogui.locateCenterOnScreen(TARGET_IMAGE)
                    if location:
                        print(f"[{time.strftime('%H:%M:%S')}] Buton bulundu! Tıklanıyor: {location}")
                        pyautogui.click(location.x, location.y)
                        time.sleep(1.5)
                except:
                    pass

            # Belirlenen süre kadar bekle
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\nBot durduruldu. İyi günler!")

if __name__ == "__main__":
    main()
