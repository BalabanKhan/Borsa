import matplotlib
matplotlib.use('Agg') # Non-interactive backend for server environments
import matplotlib.pyplot as plt
import pandas as pd
import os
import time

def generate_signal_chart(symbol: str, df_4h: pd.DataFrame, entry_price: float, sl: float, tp: float, signal_dir: str) -> str:
    """
    Generates a beautiful dark-themed line chart for the signal and saves it to a temp file.
    Returns the path to the saved image file.
    """
    try:
        # Take the last 30 periods for readability
        df = df_4h.tail(30).copy()
        
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
        
        # Plot close prices
        ax.plot(df.index, df['close'], color='#38bdf8', label='Fiyat (4S)', linewidth=2.0)
        
        # Highlight entry, SL, and TP lines
        # Entry (Green)
        ax.axhline(y=entry_price, color='#22c55e', linestyle='--', linewidth=1.5, label=f'Giriş: {entry_price:.4f}')
        
        # SL (Red)
        ax.axhline(y=sl, color='#ef4444', linestyle='--', linewidth=1.5, label=f'SL: {sl:.4f}')
        
        # TP (Blue)
        ax.axhline(y=tp, color='#3b82f6', linestyle='--', linewidth=1.5, label=f'TP: {tp:.4f}')
        
        # Format title & labels
        direction_text = "LONG (AL)" if signal_dir == "AL" else "SHORT (SAT)"
        ax.set_title(f"{symbol} — {direction_text} Sinyal Analizi", fontsize=14, pad=15, fontweight='bold', color='#f8fafc')
        ax.set_ylabel("Fiyat (USDT)", fontsize=10, color='#94a3b8')
        ax.set_xlabel("Tarih", fontsize=10, color='#94a3b8')
        
        # Customize grid and spines
        ax.grid(True, linestyle=':', alpha=0.3, color='#475569')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#475569')
        ax.spines['bottom'].set_color('#475569')
        
        # Legends
        ax.legend(loc='best', framealpha=0.8, facecolor='#1e293b', edgecolor='#475569')
        
        # Layout spacing
        plt.tight_layout()
        
        # Save to temp path
        output_dir = "temp_charts"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{symbol.replace('/', '_')}_{int(time.time())}.png"
        filepath = os.path.join(output_dir, filename)
        
        plt.savefig(filepath, bbox_inches='tight')
        plt.close(fig)
        return filepath
    except Exception as e:
        import logging
        logging.error(f"Grafik çizilemedi: {e}")
        return ""
