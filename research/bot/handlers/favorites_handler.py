import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from research.bot.utils import check_auth
from research.bot.database import load_favorites, save_favorites
from research.market_predictor import predict_future

async def favoriekle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update): return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Kullanım: `/favoriekle <SEMBOL> <TÜR>` (Örn: `/favoriekle THYAO.IS bist`)", parse_mode='Markdown')
        return
    
    symbol = args[0].upper()
    asset_type = args[1].lower()
    user_id = str(update.effective_user.id)
    
    favs = load_favorites()
    if user_id not in favs:
        favs[user_id] = []
        
    if any(item['symbol'] == symbol for item in favs[user_id]):
        await update.message.reply_text(f"⚠️ {symbol} zaten favorilerinizde ekli.")
        return
        
    favs[user_id].append({"symbol": symbol, "type": asset_type})
    save_favorites(favs)
    await update.message.reply_text(f"✅ {symbol} favorilere eklendi!")

async def favoricikar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update): return
    args = context.args
    if not args:
        await update.message.reply_text("Kullanım: `/favoricikar <SEMBOL>`", parse_mode='Markdown')
        return
        
    symbol = args[0].upper()
    user_id = str(update.effective_user.id)
    
    favs = load_favorites()
    if user_id in favs:
        initial_len = len(favs[user_id])
        favs[user_id] = [item for item in favs[user_id] if item['symbol'] != symbol]
        if len(favs[user_id]) < initial_len:
            save_favorites(favs)
            await update.message.reply_text(f"✅ {symbol} favorilerden çıkarıldı.")
            return
            
    await update.message.reply_text(f"⚠️ {symbol} favorilerinizde bulunamadı.")

async def favoriler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update): return
    user_id = str(update.effective_user.id)
    favs = load_favorites().get(user_id, [])
    
    if not favs:
        await update.message.reply_text("Favori listeniz boş. Eklemek için `/favoriekle` komutunu kullanın.", parse_mode='Markdown')
        return
        
    msg = await update.message.reply_text("⏳ Favori listeniz için tahminler hesaplanıyor (Sadece metin özeti)...")
    
    report_lines = ["📋 *Favoriler 7 Günlük Tahmin Özeti*:\n"]
    
    for item in favs:
        symbol = item['symbol']
        asset_type = item['type']
        try:
            res = await asyncio.to_thread(
                predict_future, 
                symbol=symbol, 
                asset_type=asset_type, 
                context_len=60, 
                horizon_len=7, 
                show_plot=False,
                save_plot=False
            )
            if res:
                _, final_pred, pct_change, rsi = res
                trend = "🟢" if pct_change > 0 else "🔴"
                report_lines.append(f"{trend} *{symbol}*: Hedef {final_pred:.2f} ({pct_change:+.2f}%) (RSI: {rsi:.1f})")
            else:
                report_lines.append(f"❓ *{symbol}*: Veri alınamadı.")
        except Exception as e:
            report_lines.append(f"❌ *{symbol}*: Hata oluştu.")
            
    await msg.edit_text("\n".join(report_lines), parse_mode='Markdown')

async def kiyasla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update): return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Kullanım: `/kiyasla <SEMBOL1> <SEMBOL2> <TÜR>`\nÖrn: `/kiyasla THYAO.IS PGSUS.IS bist`", parse_mode='Markdown')
        return
        
    sym1 = args[0].upper()
    sym2 = args[1].upper()
    asset_type = args[2].lower()
    
    msg = await update.message.reply_text(f"⚖️ *{sym1}* ve *{sym2}* karşılaştırılıyor...", parse_mode='Markdown')
    
    results = {}
    for sym in [sym1, sym2]:
        res = await asyncio.to_thread(
            predict_future, symbol=sym, asset_type=asset_type, 
            context_len=60, horizon_len=7, show_plot=False, save_plot=False
        )
        if res:
            results[sym] = res[2] # pct_change
            
    if len(results) == 2:
        if results[sym1] > results[sym2]:
            winner, loser = sym1, sym2
        else:
            winner, loser = sym2, sym1
            
        text = (
            f"🏆 *Karşılaştırma Sonucu (7 Günlük)*\n\n"
            f"1️⃣ *{winner}*: {results[winner]:+.2f}%\n"
            f"2️⃣ *{loser}*: {results[loser]:+.2f}%\n\n"
            f"💡 *Yapay Zeka Yorumu*: {winner}, {loser}'a göre daha yüksek kazanç potansiyeline sahip görünüyor."
        )
        await msg.edit_text(text, parse_mode='Markdown')
    else:
        await msg.edit_text("❌ Sembollerden birinin veya ikisinin verisi çekilemediği için kıyaslama yapılamadı.")
