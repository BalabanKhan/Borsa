import asyncio
import os
import sys

# Yolu ayarlayalım
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.ai_commentary import get_ai_commentary

async def main():
    test_signals = [
        {
            "ticker": "AKTUSDT",
            "signal": "AL",
            "conviction_score": 88,
            "reason": "Hacimli Kırılım ve Momentum",
            "strategy": "MOMENTUM_BREAKOUT"
        }
    ]
    
    print("AKTUSDT için Groq AI yorumu alınıyor...")
    commentary = await get_ai_commentary(test_signals)
    print("\n--- GROQ AI YORUMU ---")
    print(commentary)

if __name__ == "__main__":
    asyncio.run(main())
