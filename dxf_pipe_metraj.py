import os
import re
from collections import defaultdict, Counter

p = r'G:\Diğer bilgisayarlar\Dizüstü Bilgisayarım\YSR\PROJELER\ASKA_LARA\09_PROJELER\HAZİRAN 26\TSS_ASKA OTEL MEKANİK PROJE 24.09.2013.dxf'

layers = Counter()
codes = Counter()
sections = []
section = None

with open(p, encoding='utf-8', errors='ignore') as f:
    for raw in f:
        line = raw.strip()
        if line == 'ENTITIES':
            section = 'ENTITIES'
        elif line == 'ENDSEC':
            section = None
        elif line == 'SECTION':
            if section:
                sections.append(section)
            section = None
        elif section == 'ENTITIES' and line.startswith('  8'):
            next_line = next(f, '').strip()
            layers[next_line] += 1
        elif line in ('LINE', 'LWPOLYLINE', 'POLYLINE', 'ARC', 'CIRCLE', 'TEXT', 'MTEXT', 'INSERT', 'BLOCK'):
            codes[line] += 1

print('entities sections parsed:', len(sections))
print('\nLayers with entity count:')
for name, count in layers.most_common(30):
    print(name, count)
print('\nEntity types:')
for name, count in codes.most_common(10):
    print(name, count)
