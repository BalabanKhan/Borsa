from telegram import Update
from telegram.ext import ContextTypes
from research.bot.utils import check_auth

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıya botun kullanımını açıklar."""
    if not await check_auth(update):
        return
        
    welcome_text = (
        "🤖 *TimesFM Tahmin Botu Komut Kılavuzu*\n\n"
        "⚡️ *Tahmin Komutları:*\n"
        "• `/tahmin <SEM> <TÜR>`: Standart günlük tahmin yapar.\n"
        "  _Örn: `/tahmin THYAO bist` veya `/tahmin BTC/USDT crypto`_\n"
        "• `/tahmin <SEM> bist gün`: **7 Günlük** günlük grafik tahmini (En düşük MAPE optimize).\n"
        "• `/tahmin <SEM> bist saat`: **Seans sonuna kadar (18:00 TRT)** seans içi saatlik grafik tahmini.\n"
        "• `/tahmin <SEM> saat` / `saatlik`: Diğer türlerde saatlik grafik tahmini.\n"
        "  _Örn: `/tahmin BTC/USDT crypto saat`_\n\n"
        "⭐️ *Favori ve Karşılaştırma Komutları:*\n"
        "• `/favoriekle <SEM> <TÜR>`: Varlığı favorilere ekler.\n"
        "• `/favoricikar <SEM>`: Varlığı favorilerden çıkarır.\n"
        "• `/favoriler`: Favori listenizin 7 günlük tahmin özetini sunar.\n"
        "• `/kiyasla <SEM1> <SEM2> <TÜR>`: İki varlığın kazanç potansiyelini karşılaştırır.\n\n"
        "📊 *BIST 50 Tarama Komutları:*\n"
        "• `/gunici`: Seans sonuna kadarki en yüksek potansiyelli 3 hisseyi listeler.\n"
        "• `/saatlik`: Hata payı (MAPE) en düşük 3 hisseyi grafikli listeler.\n"
        "• `/tara`: Çoklu zaman dilimi teyitli (EMA5/RSI) günün en iyi 3 hissesini grafikli listeler.\n\n"
        "📊 *Kripto Tarama Komutları:*\n"
        "• `/taracrypto`: TimesFM ile 24 saatlik en yüksek yükseliş ve düşüş beklenen 3 kripto varlığı tarar.\n\n"
        "🧹 *Diğer:*\n"
        "• `/temizle`: Ekrandaki eski grafikleri gizlemek için boşluk bırakır.\n"
        "• `/help` veya `/start`: Bu menüyü gösterir.\n\n"
        "ℹ️ *Gelişmiş Manuel Kullanım:*\n"
        "`/tahmin <SEM> <TÜR> <GEÇMİŞ> <GELECEK>`\n"
        "_Örn: `/tahmin THYAO saat 120 12` (Son 120 bar veriyle 12 bar tahmin)_"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def temizle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sohbeti temizlemek için boşluk gönderir ve asıl temizlemenin nasıl yapılacağını açıklar."""
    if not await check_auth(update):
        return
        
    text = (
        "🧹 *Sohbeti Temizleme Bilgisi*\n\n"
        "Telegram API kuralları gereği botlar sizin adınıza tüm sohbet geçmişini silemez. "
        "Tamamen temizlemek için sağ üstteki **üç noktaya (⋮)** tıklayıp **'Sohbeti Temizle'** seçeneğine basabilirsiniz.\n\n"
        "*(Ekrandaki eski grafikleri gizlemek için aşağıya boşluk bırakıyorum...)*\n"
        + ".\n" * 40 +
        "✅ Ekran kaydırıldı. Yeni bir tahmin için `/tahmin` komutunu kullanabilirsiniz."
    )
    await update.message.reply_text(text, parse_mode='Markdown')
