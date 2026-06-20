import os
import json
import logging

logger = logging.getLogger("research.bot.database")

# Favorites file stays in the research folder for backward compatibility
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RESEARCH_DIR = os.path.dirname(CURRENT_DIR)
FAVORITES_FILE = os.path.join(RESEARCH_DIR, 'favorites.json')

def load_favorites():
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Favoriler okunurken hata: {e}")
    return {}

def save_favorites(favs):
    try:
        with open(FAVORITES_FILE, 'w') as f:
            json.dump(favs, f, indent=4)
    except Exception as e:
        logger.error(f"Favoriler kaydedilirken hata: {e}")
