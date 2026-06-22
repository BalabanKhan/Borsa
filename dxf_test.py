import os, re
from collections import defaultdict, Counter

p = r'G:\Diğer bilgisayarlar\Dizüstü Bilgisayarım\YSR\PROJELER\ASKA_LARA\09_PROJELER\HAZİRAN 26\TSS_ASKA OTEL MEKANİK PROJE 24.09.2013.dxf'
print('exists:', os.path.exists(p), 'size_mb:', round(os.path.getsize(p)/1024/1024,2))

# Kullanıcıya yanıt: dosya erişimi yok, wmic hata detayı, alternatif yol
print('DOSYA_BULUNADI')