import os
import sys

# Kök dizinden çevresel değişkenleri ve diğer modülleri alabilmek için
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

from research.bot.main import main

if __name__ == "__main__":
    main()
