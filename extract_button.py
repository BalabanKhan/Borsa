import cv2
import numpy as np
import sys

image_path = r'C:\Users\YSR_MONSTER\.gemini\antigravity-ide\brain\0f61eb55-d52e-4c2a-8c5d-edfe7b43be9d\media__1781704423704.png'
out_path = r'C:\Users\YSR_MONSTER\.antigravity\Borsa\run_button.png'

img = cv2.imread(image_path)
if img is None:
    print("Could not read image")
    sys.exit(1)

hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

# Mavi tonunu bul
lower_blue = np.array([90, 50, 50])
upper_blue = np.array([130, 255, 255])

mask = cv2.inRange(hsv, lower_blue, upper_blue)

contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

if not contours:
    print("Mavi buton bulunamadi")
    sys.exit(1)

# En buyuk mavi alani sec
c = max(contours, key=cv2.contourArea)
x, y, w, h = cv2.boundingRect(c)

# Ortasindan bir parca al
cropped = img[y+5:y+h-5, x+5:x+w-5]

cv2.imwrite(out_path, cropped)
print(f"Basariyla {out_path} konumuna kaydedildi!")
