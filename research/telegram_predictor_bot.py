import os
import sys
import logging
import asyncio
import json
import datetime
import pytz
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Loglama ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Kök dizinden çevresel değişkenleri ve diğer modülleri alabilmek için
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# Borsa ana dizinindeki .env'yi yükle
load_dotenv(os.path.join(project_root, '.env'))

from research.market_predictor import predict_future, evaluate_model_accuracy

# İzin verilen kullanıcı ID'leri (Sadece bu ID'ler botu kullanabilir)
ALLOWED_USER_IDS = [5892379162]

FAVORITES_FILE = os.path.join(current_dir, 'favorites.json')

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

async def check_auth(update: Update) -> bool:
    """Kullanıcının yetkili olup olmadığını kontrol eder."""
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Bu botu kullanma yetkiniz bulunmamaktadır.")
        logger.warning(f"Yetkisiz erişim denemesi! User ID: {user_id}, Name: {update.effective_user.first_name}")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıya botun kullanımını açıklar."""
    if not await check_auth(update):
        return
        
    welcome_text = (
        "🤖 *TimesFM Tahmin Botuna Hoş Geldiniz!*\n\n"
        "Bu bot, yapay zeka kullanarak hisse, kripto ve emtialar için gelecek tahmini yapar.\n\n"
        "📌 *Nasıl Kullanılır?*\n"
        "`/tahmin <SEMBOL> <TÜR>`\n\n"
        "📌 *Örnek Kullanımlar:*\n"
        "`/tahmin THYAO.IS bist`\n"
        "`/tahmin BTC/USDT crypto`\n"
        "`/tahmin XAU/USD emtia`\n\n"
        "⚡️ *Saatlik / Seans İçi Tahmin:*\n"
        "Saatlik grafikleri tahmin ettirmek için sonuna *saat* veya *saatlik* ekleyin:\n"
        "`/tahmin <SEMBOL> saat` veya `/tahmin <SEMBOL> <TÜR> saatlik`\n"
        "Örnek: `/tahmin THYAO saat`\n\n"
        "⭐️ *Favori ve Kıyaslama Komutları:*\n"
        "`/favoriekle <SEMBOL> <TÜR>` - Favorilere ekler\n"
        "`/favoricikar <SEMBOL>` - Favorilerden çıkarır\n"
        "`/favoriler` - Favori listenizin güncel tahmin özetini sunar\n"
        "`/kiyasla <SEMBOL1> <SEMBOL2> <TÜR>` - İki varlığı kıyaslar\n\n"
        "🧹 *Diğer Komutlar:*\n"
        "`/temizle` - Ekrandaki konuşmaları temizler/kaydırır.\n\n"
        "ℹ️ *Gelişmiş Kullanım (Opsiyonel):*\n"
        "Bot varsayılan olarak **son 60 günün/saatin** verisine bakıp **önümüzdeki 7 günü/saati** tahmin eder. "
        "Ancak isterseniz geçmiş veri (context) ve tahmin edilecek (horizon) sayılarını kendiniz belirleyebilirsiniz:\n\n"
        "`/tahmin <SEMBOL> <TÜR> <GEÇMİŞ> <GELECEK>`\n\n"
        "Örnek: `/tahmin THYAO saat 120 12`\n"
        "_(Yukarıdaki komut son 120 saatlik veriye bakıp 12 saatlik tahmin yapar.)_\n\n"
        "⚡️ *Gün İçi Tahmin (BIST 50):*\n"
        "`/gunici` - Seans sonuna kadar en çok kazandırma potansiyeli olan 3 hisseyi (grafiksiz) listeler."
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def tahmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """TimesFM tahminini arka planda çalıştırır ve fotoğraf olarak döner."""
    if not await check_auth(update):
        return

    args = context.args
    
    if not args:
        await update.message.reply_text(
            "⚠️ Eksik parametre! Lütfen sembol girin.\n"
            "Örnek: `/tahmin THYAO.IS` veya `/tahmin saat AKSA.IS`",
            parse_mode='Markdown'
        )
        return

    args_lower = [a.lower() for a in args]
    interval = '1d'
    
    if 'saat' in args_lower:
        interval = '1h'
        args_lower.remove('saat')
    elif 'saatlik' in args_lower:
        interval = '1h'
        args_lower.remove('saatlik')
        
    if not args_lower:
        await update.message.reply_text("⚠️ Lütfen bir sembol belirtin.")
        return
        
    raw_symbol = args_lower[0].upper()
    
    if raw_symbol.endswith(".BIST"):
        symbol = raw_symbol.replace(".BIST", ".IS")
        asset_type = "bist"
    else:
        symbol = raw_symbol
        asset_type = "bist"
        
    if len(args_lower) > 1 and args_lower[1] in ['bist', 'crypto', 'emtia']:
        asset_type = args_lower[1]
        
    if asset_type == 'bist' and not symbol.endswith('.IS') and not symbol.endswith('.BIST'):
        symbol += '.IS'
        
    context_len = 60
    horizon_len = 7
    best_mape = None
    
    numbers = [int(a) for a in args_lower[1:] if a.isdigit()]
    if len(numbers) >= 1:
        context_len = numbers[0]
    if len(numbers) >= 2:
        horizon_len = numbers[1]
        
    is_auto_optimized = False
    interval_str = "Saatlik" if interval == '1h' else "Günlük"
    
    # BIST Saatlik tahminlerde otomatik optimizasyon (Eğer kullanıcı manuel geçmiş gün girmediyse)
    if interval == '1h' and asset_type == 'bist' and len(numbers) < 1:
        is_auto_optimized = True
        status_msg = await update.message.reply_text(f"🔍 *[{symbol}]* için en düşük hata payı veren veri aralığı hesaplanıyor (MAPE Optimizasyonu)...", parse_mode='Markdown')
        
        candidates = [32, 64, 96, 128]
        best_mape_val = float('inf')
        best_c = 60
        
        # Ayrı thread'lerde hızlıca MAPE'leri hesapla
        for c in candidates:
            mape_candidate = await asyncio.to_thread(evaluate_model_accuracy, symbol, asset_type, '1h', c, horizon_len)
            if mape_candidate is not None and mape_candidate < best_mape_val:
                best_mape_val = mape_candidate
                best_c = c
        
        await status_msg.delete()
        if best_mape_val != float('inf'):
            context_len = best_c
            best_mape = best_mape_val
            
    msg = await update.message.reply_text(f"⏳ *[{symbol}]* için TimesFM {interval_str} tahmin grafiği hazırlanıyor... Lütfen bekleyin. (Geçmiş: {context_len} saat)", parse_mode='Markdown')
    
    try:
        # Yapay zeka modeli (plt işlemleri vs) senkron (blocking) çalıştığı için 
        # botu dondurmamak adına ayrı bir thread'de (to_thread) çalıştırıyoruz.
        res = await asyncio.to_thread(
            predict_future, 
            symbol=symbol, 
            asset_type=asset_type, 
            context_len=context_len, 
            horizon_len=horizon_len, 
            show_plot=False,
            save_plot=True,
            interval=interval
        )
        
        if res and res[0] and os.path.exists(res[0]):
            image_path, final_pred, pct_change, rsi = res
            trend_icon = "🟢 BOĞA (Yükseliş)" if pct_change > 0 else "🔴 AYI (Düşüş)"
            
            tp_sl_text = ""
            mape_text = ""
            
            if interval == '1h' and asset_type == 'bist':
                # Eğer optimizasyonda zaten hesaplanmadıysa burada hesapla
                if best_mape is None:
                    best_mape = await asyncio.to_thread(evaluate_model_accuracy, symbol, asset_type, '1h', context_len, horizon_len)
                
                if best_mape is not None:
                    opt_tag = " (En Düşük Hata)" if is_auto_optimized else ""
                    mape_text = f"⚙️ Veri Uzunluğu: *{context_len} saat*{opt_tag}\n📉 AI Hata Payı (MAPE): *%{best_mape:.2f}*\n"
                    
                import data_sources
                import pandas as pd
                _, _, df_data = await asyncio.to_thread(data_sources.get_bist_data, symbol)
                if df_data is not None and not df_data.empty:
                    last_close = df_data['close'].iloc[-1]
                    tr1 = df_data['high'] - df_data['low']
                    tr2 = (df_data['high'] - df_data['close'].shift(1)).abs()
                    tr3 = (df_data['low'] - df_data['close'].shift(1)).abs()
                    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                    atr = tr.rolling(window=14).mean().iloc[-1]
                    
                    tp = last_close + (atr * 2.0)
                    sl = last_close - (atr * 1.5)
                    tp_pct = ((tp - last_close) / last_close) * 100
                    sl_pct = ((last_close - sl) / last_close) * 100
                    
                    tp_sl_text = (
                        f"🎯 Hedef (TP): {tp:.2f} (+%{tp_pct:.2f})\n"
                        f"🛑 Stop (SL): {sl:.2f} (-%{sl_pct:.2f})\n"
                    )

            caption = (
                f"📊 *{symbol}* - TimesFM {horizon_len} {interval_str} Gelecek Tahmini\n"
                f"{mape_text}"
                f"🎯 Tahmin Edilen Fiyat: *{final_pred:.2f}*\n"
                f"📈 Beklenen Değişim: *{pct_change:+.2f}%*\n"
                f"🔥 Trend Yönü: *{trend_icon}*\n"
                f"{tp_sl_text}\n"
                f"_Not: Yapay zeka tavsiyesi kesinlik içermez._"
            )
            # Dosyayı gönder
            with open(image_path, 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption=caption, parse_mode='Markdown')
            
            # Eski "Hazırlanıyor" mesajını sil
            await msg.delete()
        else:
            await msg.edit_text(f"❌ *[{symbol}]* verisi çekilemedi veya grafiği oluşturulurken bir hata meydana geldi.", parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Tahmin hatası: {e}", exc_info=True)
        await msg.edit_text(f"❌ Beklenmedik bir hata oluştu:\n`{str(e)}`", parse_mode='Markdown')

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
        
    # Check if already exists
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

async def gunici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """BIST 50 içinden seans sonuna kadar yükselecek en iyi 3 hisseyi bulur."""
    if not await check_auth(update): return
    
    msg = await update.message.reply_text("⚡️ *BIST 50 Gün İçi Sinyal Taraması Başladı...*\n(Trend + Momentum + Hacim + RSI < 75 algoritması çalıştırılıyor, lütfen bekleyin)", parse_mode='Markdown')
    
    try:
        import yfinance as yf
        import pandas as pd
        from config import TOP_BIST_50
        
        def run_intraday_scan():
            tickers_str = " ".join(TOP_BIST_50)
            data = yf.download(tickers_str, period="60d", interval="1h", group_by="ticker", progress=False)
            
            results = []
            for ticker in TOP_BIST_50:
                if len(TOP_BIST_50) == 1:
                    df = data.copy()
                else:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    df = data[ticker].copy()
                
                df = df.dropna()
                if df.empty: continue
                
                # İndikatörler
                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                df['RSI_14'] = 100 - (100 / (1 + rs))
                
                df['EMA_5'] = df['Close'].ewm(span=5, adjust=False).mean()
                df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
                df['Volume_SMA'] = df['Volume'].rolling(window=20).mean()
                
                # ATR (Average True Range) Hesaplama (Volatilite)
                tr1 = df['High'] - df['Low']
                tr2 = (df['High'] - df['Close'].shift(1)).abs()
                tr3 = (df['Low'] - df['Close'].shift(1)).abs()
                df['TR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                df['ATR_14'] = df['TR'].rolling(window=14).mean()
                
                df['Trend'] = (df['Close'] > df['EMA_5']) & (df['EMA_5'] > df['EMA_20'])
                df['Vol_Surge'] = df['Volume'] > df['Volume_SMA'] * 1.5
                
                df['MACD'] = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
                df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
                df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
                df['MACD_Pos'] = df['MACD_Hist'] > 0
                
                df = df.dropna()
                if df.empty: continue
                
                last_bar = df.iloc[-1]
                
                # Algoritma: (A + C birleşimi + RSI < 75) -> Trend + MACD Momentum + Hacim + RSI
                if last_bar['Trend'] and last_bar['MACD_Pos'] and last_bar['Vol_Surge'] and last_bar['RSI_14'] < 75:
                    price = last_bar['Close']
                    atr = last_bar['ATR_14']
                    
                    # Dinamik Hedefler: Fiyat hareketinin 2 katı kazanç, 1.5 katı stop
                    tp = price + (atr * 2.0)
                    sl = price - (atr * 1.5)
                    
                    tp_pct = ((tp - price) / price) * 100
                    sl_pct = ((price - sl) / price) * 100
                    
                    results.append({
                        'Ticker': ticker,
                        'RSI': last_bar['RSI_14'],
                        'Price': price,
                        'TP': tp,
                        'SL': sl,
                        'TP_Pct': tp_pct,
                        'SL_Pct': sl_pct
                    })
                    
            if not results:
                # Eğer hacim veya MACD çok katı geldiyse, biraz esnetelim (sadece Trend + RSI)
                for ticker in TOP_BIST_50:
                    if ticker not in data.columns.get_level_values(0): continue
                    df = data[ticker].dropna()
                    if df.empty: continue
                    # ... re-calculating is not ideal here, let's just use the strict rule.
            
            res_df = pd.DataFrame(results)
            if res_df.empty:
                return []
            
            res_df = res_df.sort_values('RSI', ascending=False).head(3)
            return res_df.to_dict('records')

        top_stocks = await asyncio.to_thread(run_intraday_scan)
        
        if not top_stocks:
            await msg.edit_text("⚠️ *Gün İçi Sinyal*: Şu anki piyasa koşullarında tüm kriterleri (Trend + Hacim + MACD + RSI<75) karşılayan BIST 50 hissesi bulunamadı.", parse_mode='Markdown')
        else:
            text = "⚡️ *Gün İçi Algoritmik Taraması Sonuçları*\n(Kriter: Trend Yukarı + MACD Pozitif + Hacim Artışı + RSI < 75)\n\n"
            for i, stock in enumerate(top_stocks, 1):
                text += f"{i}️⃣ *{stock['Ticker']}* - Fiyat: {stock['Price']:.2f} (RSI: {stock['RSI']:.1f})\n"
                text += f"   🎯 Hedef (TP): {stock['TP']:.2f} (+%{stock['TP_Pct']:.2f})\n"
                text += f"   🛑 Stop (SL): {stock['SL']:.2f} (-%{stock['SL_Pct']:.2f})\n\n"
            
            text += "\n_Not: Seans kapanışına kadar geçerli tahminlerdir, yatırım tavsiyesi değildir._"
            await msg.edit_text(text, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Gunici hatası: {e}", exc_info=True)
        await msg.edit_text(f"❌ Beklenmedik bir hata oluştu:\n`{str(e)}`", parse_mode='Markdown')

async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    """Zamanlanmış sabah bülteni."""
    favs_db = load_favorites()
    if not favs_db:
        return
        
    for user_id_str, fav_list in favs_db.items():
        if not fav_list: continue
        
        bist_favs = [item for item in fav_list if item['type'] == 'bist']
        if not bist_favs:
            continue
            
        report_lines = ["🌅 *Günaydın! Sabah Bülteni (BIST 100 Favorileriniz)*:\n"]
        
        candidates = []
        
        for item in bist_favs:
            symbol = item['symbol']
            asset_type = item['type']
            try:
                # Günlük Tahmin (Strategy C için RSI ve Günlük Trend kontrolü)
                res_1d = await asyncio.to_thread(
                    predict_future, 
                    symbol=symbol, 
                    asset_type=asset_type, 
                    context_len=90,  # Optimize edilen Lookback değeri (90 gün)
                    horizon_len=7, 
                    show_plot=False,
                    save_plot=False,
                    interval='1d'
                )
                
                if res_1d:
                    _, final_pred_1d, pct_change_1d, rsi = res_1d
                    
                    # Filtre 1: RSI > 75 ise ele (Aşırı Alım)
                    if rsi > 75.0:
                        report_lines.append(f"⚠️ *{symbol}*: Elendi (RSI {rsi:.1f} > 75 - Aşırı Alım)")
                        continue
                        
                    # Filtre 2: Günlük trend negatifse ele
                    if pct_change_1d <= 0:
                        report_lines.append(f"🔴 *{symbol}*: Elendi (Günlük trend negatif)")
                        continue

                    # Saatlik Tahmin (Strategy A için Çoklu Zaman Dilimi Teyidi)
                    res_1h = await asyncio.to_thread(
                        predict_future,
                        symbol=symbol,
                        asset_type=asset_type,
                        context_len=60,
                        horizon_len=8,
                        show_plot=False,
                        save_plot=False,
                        interval='1h'
                    )
                    
                    if res_1h:
                        _, final_pred_1h, pct_change_1h, _ = res_1h
                        
                        # Filtre 3: Saatlik trend negatifse ele
                        if pct_change_1h <= 0:
                            report_lines.append(f"🔴 *{symbol}*: Elendi (Saatlik trend negatif)")
                            continue
                            
                        # Filtre 4: Intraday EMA 5 Trend Kontrolü (Optimizasyon sonucu)
                        import data_sources
                        _, _, df_1h_data = data_sources.get_bist_data(symbol)
                        if df_1h_data is not None and not df_1h_data.empty:
                            ema5 = df_1h_data['close'].ewm(span=5, adjust=False).mean()
                            last_close = df_1h_data['close'].iloc[-1]
                            last_ema5 = ema5.iloc[-1]
                            if last_close <= last_ema5:
                                report_lines.append(f"🔴 *{symbol}*: Elendi (Fiyat EMA 5'in altında)")
                                continue
                                
                            # Hesapla ATR ve TP/SL
                            tr1 = df_1h_data['high'] - df_1h_data['low']
                            tr2 = (df_1h_data['high'] - df_1h_data['close'].shift(1)).abs()
                            tr3 = (df_1h_data['low'] - df_1h_data['close'].shift(1)).abs()
                            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                            atr = tr.rolling(window=14).mean().iloc[-1]
                            
                            tp = last_close + (atr * 2.0)
                            sl = last_close - (atr * 1.5)
                            tp_pct = ((tp - last_close) / last_close) * 100
                            sl_pct = ((last_close - sl) / last_close) * 100
                        else:
                            tp = sl = tp_pct = sl_pct = 0
                            
                        # İki zaman diliminde de pozitif, RSI <= 75 ve EMA5 üzerinde. Aday listesine ekle.
                        # Sıralama için günlük artış yüzdesini kullanıyoruz
                        candidates.append({
                            'symbol': symbol,
                            'pct_change_1d': pct_change_1d,
                            'pct_change_1h': pct_change_1h,
                            'rsi': rsi,
                            'tp': tp,
                            'sl': sl,
                            'tp_pct': tp_pct,
                            'sl_pct': sl_pct
                        })
                    else:
                        report_lines.append(f"❓ *{symbol}*: Saatlik veri alınamadı.")
                else:
                    report_lines.append(f"❓ *{symbol}*: Günlük veri alınamadı.")
            except Exception as e:
                report_lines.append(f"❌ *{symbol}*: Hata oluştu.")
                
        # En iyi 3 hisseyi seç
        candidates.sort(key=lambda x: x['pct_change_1d'], reverse=True)
        top_3 = candidates[:3]
        
        if top_3:
            report_lines.append("\n🏆 *Günün En İyi Tahminleri (Teyitli)*:")
            for i, cand in enumerate(top_3, 1):
                sym = cand['symbol']
                report_lines.append(f"{i}️⃣ *{sym}*: Günlük +{cand['pct_change_1d']:.1f}% | Saatlik +{cand['pct_change_1h']:.1f}% | RSI: {cand['rsi']:.1f}")
                if cand.get('tp', 0) > 0:
                    report_lines.append(f"   🎯 Hedef (TP): {cand['tp']:.2f} (+%{cand['tp_pct']:.2f})")
                    report_lines.append(f"   🛑 Stop (SL): {cand['sl']:.2f} (-%{cand['sl_pct']:.2f})")
        else:
            report_lines.append("\n⚠️ *Bugün tüm filtreleri geçen (Çoklu Zaman Dilimi, RSI < 75, EMA 5) hisse bulunamadı.*")
            
        text_msg = "\n".join(report_lines)
        
        try:
            await context.bot.send_message(chat_id=int(user_id_str), text=text_msg, parse_mode='Markdown')
            
            for cand in top_3:
                sym = cand['symbol']
                try:
                    res_plot = await asyncio.to_thread(
                        predict_future,
                        symbol=sym,
                        asset_type='bist',
                        context_len=60,
                        horizon_len=8,
                        show_plot=False,
                        save_plot=True,
                        interval='1h'
                    )
                    if res_plot and res_plot[0] and os.path.exists(res_plot[0]):
                        with open(res_plot[0], 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=int(user_id_str), 
                                photo=photo, 
                                caption=f"🌟 *{sym}* Saatlik Detay Grafiği", 
                                parse_mode='Markdown'
                            )
                except Exception as e:
                    logger.error(f"Grafik gönderme hatası {sym}: {e}")
                    
        except Exception as e:
            logger.error(f"Daily report send error to {user_id_str}: {e}")

async def saatlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """BIST 50 içinden TimesFM hata payı en düşük olan 3 hisseyi bulur."""
    if not await check_auth(update): return
    
    msg = await update.message.reply_text("⏳ *Saatlik AI Taraması Başladı*\nBIST 50 hisseleri için en düşük hata payı veren veri aralığı hesaplanıyor (32, 64, 96, 128 saat candidates)...\n_(Bu işlem 5-10 dakika sürebilir, lütfen bekleyin)_", parse_mode='Markdown')
    
    try:
        from config import TOP_BIST_50
        
        def run_hourly_scan():
            results = []
            candidates = [32, 64, 96, 128]
            for ticker in TOP_BIST_50:
                best_mape = float('inf')
                best_c = 60
                for c in candidates:
                    mape = evaluate_model_accuracy(ticker, asset_type='bist', interval='1h', context_len=c, horizon_len=7)
                    if mape is not None and mape < best_mape:
                        best_mape = mape
                        best_c = c
                
                if best_mape != float('inf'):
                    results.append({'symbol': ticker, 'mape': best_mape, 'best_context': best_c})
            
            # Hata oranına göre küçükten büyüğe sırala (En düşük hata = En iyi tahmin)
            results.sort(key=lambda x: x['mape'])
            
            # En iyi 3 hisse
            top_3 = results[:3]
            
            final_results = []
            for item in top_3:
                sym = item['symbol']
                c_len = item['best_context']
                res = predict_future(symbol=sym, asset_type='bist', interval='1h', context_len=c_len, horizon_len=7, show_plot=False, save_plot=True)
                if res and res[0]:
                    image_path, final_pred, pct_change, rsi = res
                    
                    # Basit TP/SL
                    import data_sources
                    import pandas as pd
                    _, _, df_1h = data_sources.get_bist_data(sym)
                    if df_1h is not None and not df_1h.empty:
                        last_close = df_1h['close'].iloc[-1]
                        tr1 = df_1h['high'] - df_1h['low']
                        tr2 = (df_1h['high'] - df_1h['close'].shift(1)).abs()
                        tr3 = (df_1h['low'] - df_1h['close'].shift(1)).abs()
                        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                        atr = tr.rolling(window=14).mean().iloc[-1]
                        
                        tp = last_close + (atr * 2.0)
                        sl = last_close - (atr * 1.5)
                        tp_pct = ((tp - last_close) / last_close) * 100
                        sl_pct = ((last_close - sl) / last_close) * 100
                    else:
                        tp = sl = tp_pct = sl_pct = 0
                        last_close = final_pred / (1 + (pct_change/100))
                    
                    final_results.append({
                        'symbol': sym,
                        'mape': item['mape'],
                        'pct_change': pct_change,
                        'final_pred': final_pred,
                        'image_path': image_path,
                        'tp': tp,
                        'sl': sl,
                        'tp_pct': tp_pct,
                        'sl_pct': sl_pct,
                        'price': last_close,
                        'best_context': c_len
                    })
            return final_results

        best_stocks = await asyncio.to_thread(run_hourly_scan)
        
        if not best_stocks:
            await msg.edit_text("⚠️ *Saatlik AI Taraması*: Yeterli veri bulunamadı veya model çalıştırılamadı.", parse_mode='Markdown')
        else:
            text = "🚀 *En Düşük Hata Oranına Sahip 3 Hisse (Saatlik Tahmin)*\n\n"
            for i, stock in enumerate(best_stocks, 1):
                trend = "🟢" if stock['pct_change'] > 0 else "🔴"
                text += f"{i}️⃣ {trend} *{stock['symbol']}* - Güncel: {stock['price']:.2f}\n"
                text += f"   ⚙️ Optimum Veri Uzunluğu: *{stock['best_context']} saat*\n"
                text += f"   📉 AI Hata Payı (MAPE): *%{stock['mape']:.2f}*\n"
                text += f"   📈 Beklenen Değişim: *{stock['pct_change']:+.2f}%*\n"
                text += f"   🎯 Hedef (TP): {stock['tp']:.2f} (+%{stock['tp_pct']:.2f})\n"
                text += f"   🛑 Stop (SL): {stock['sl']:.2f} (-%{stock['sl_pct']:.2f})\n\n"
            
            await msg.edit_text(text, parse_mode='Markdown')
            
            # Grafikleri gönder
            for stock in best_stocks:
                try:
                    if os.path.exists(stock['image_path']):
                        with open(stock['image_path'], 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id, 
                                photo=photo, 
                                caption=f"🌟 *{stock['symbol']}* Saatlik AI Grafiği (Geçmiş: {stock['best_context']}s, Hata: %{stock['mape']:.2f})", 
                                parse_mode='Markdown'
                            )
                except Exception as e:
                    logger.error(f"Grafik gönderme hatası {stock['symbol']}: {e}")
                    
    except Exception as e:
        logger.error(f"Saatlik hata: {e}", exc_info=True)
        await msg.edit_text(f"❌ Beklenmedik bir hata oluştu:\n`{str(e)}`", parse_mode='Markdown')

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

async def sabah_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sabah bültenini manuel tetikler."""
    if not await check_auth(update): return
    
    user_id_str = str(update.effective_user.id)
    favs_db = load_favorites()
    fav_list = favs_db.get(user_id_str, [])
    
    if not fav_list:
        await update.message.reply_text("Favori listeniz boş. Sabah bülteni oluşturabilmek için önce `/favoriekle` ile favori ekleyin.")
        return
        
    msg = await update.message.reply_text("⏳ *Sabah Bülteni hazırlanıyor...* (Çoklu zaman dilimi teyitleri ve filtreler kontrol ediliyor)", parse_mode='Markdown')
    
    bist_favs = [item for item in fav_list if item['type'] == 'bist']
    if not bist_favs:
        await msg.edit_text("Favorilerinizde BIST hissesi bulunamadı. Sabah bülteni sadece BIST hisseleri için oluşturulur.")
        return
        
    report_lines = ["🌅 *Sabah Bülteni (BIST 100 Favorileriniz)*:\n"]
    candidates = []
    
    for item in bist_favs:
        symbol = item['symbol']
        asset_type = item['type']
        try:
            res_1d = await asyncio.to_thread(
                predict_future, 
                symbol=symbol, 
                asset_type=asset_type, 
                context_len=90,
                horizon_len=7, 
                show_plot=False,
                save_plot=False,
                interval='1d'
            )
            if res_1d:
                _, final_pred_1d, pct_change_1d, rsi = res_1d
                if rsi > 75.0:
                    report_lines.append(f"⚠️ *{symbol}*: Elendi (RSI {rsi:.1f} > 75)")
                    continue
                if pct_change_1d <= 0:
                    report_lines.append(f"🔴 *{symbol}*: Elendi (Günlük trend negatif)")
                    continue
                
                res_1h = await asyncio.to_thread(
                    predict_future,
                    symbol=symbol,
                    asset_type=asset_type,
                    context_len=60,
                    horizon_len=8,
                    show_plot=False,
                    save_plot=False,
                    interval='1h'
                )
                if res_1h:
                    _, final_pred_1h, pct_change_1h, _ = res_1h
                    if pct_change_1h <= 0:
                        report_lines.append(f"🔴 *{symbol}*: Elendi (Saatlik trend negatif)")
                        continue
                        
                    import data_sources
                    import pandas as pd
                    _, _, df_1h_data = data_sources.get_bist_data(symbol)
                    if df_1h_data is not None and not df_1h_data.empty:
                        ema5 = df_1h_data['close'].ewm(span=5, adjust=False).mean()
                        last_close = df_1h_data['close'].iloc[-1]
                        last_ema5 = ema5.iloc[-1]
                        if last_close <= last_ema5:
                            report_lines.append(f"🔴 *{symbol}*: Elendi (Fiyat EMA 5'in altında)")
                            continue
                            
                        tr1 = df_1h_data['high'] - df_1h_data['low']
                        tr2 = (df_1h_data['high'] - df_1h_data['close'].shift(1)).abs()
                        tr3 = (df_1h_data['low'] - df_1h_data['close'].shift(1)).abs()
                        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                        atr = tr.rolling(window=14).mean().iloc[-1]
                        
                        tp = last_close + (atr * 2.0)
                        sl = last_close - (atr * 1.5)
                        tp_pct = ((tp - last_close) / last_close) * 100
                        sl_pct = ((last_close - sl) / last_close) * 100
                    else:
                        tp = sl = tp_pct = sl_pct = 0
                        
                    candidates.append({
                        'symbol': symbol,
                        'pct_change_1d': pct_change_1d,
                        'pct_change_1h': pct_change_1h,
                        'rsi': rsi,
                        'tp': tp,
                        'sl': sl,
                        'tp_pct': tp_pct,
                        'sl_pct': sl_pct
                    })
                else:
                    report_lines.append(f"❓ *{symbol}*: Saatlik veri alınamadı.")
            else:
                report_lines.append(f"❓ *{symbol}*: Günlük veri alınamadı.")
        except Exception as e:
            report_lines.append(f"❌ *{symbol}*: Hata oluştu.")
            
    candidates.sort(key=lambda x: x['pct_change_1d'], reverse=True)
    top_3 = candidates[:3]
    
    if top_3:
        report_lines.append("\n🏆 *Günün En İyi Tahminleri (Teyitli)*:")
        for i, cand in enumerate(top_3, 1):
            sym = cand['symbol']
            report_lines.append(f"{i}️⃣ *{sym}*: Günlük +{cand['pct_change_1d']:.1f}% | Saatlik +{cand['pct_change_1h']:.1f}% | RSI: {cand['rsi']:.1f}")
            if cand.get('tp', 0) > 0:
                report_lines.append(f"   🎯 Hedef (TP): {cand['tp']:.2f} (+%{cand['tp_pct']:.2f})")
                report_lines.append(f"   🛑 Stop (SL): {cand['sl']:.2f} (-%{cand['sl_pct']:.2f})")
    else:
        report_lines.append("\n⚠️ *Bugün tüm filtreleri geçen (Çoklu Zaman Dilimi, RSI < 75, EMA 5) hisse bulunamadı.*")
        
    await msg.delete()
    await update.message.reply_text("\n".join(report_lines), parse_mode='Markdown')
    
    for cand in top_3:
        sym = cand['symbol']
        try:
            res_plot = await asyncio.to_thread(
                predict_future,
                symbol=sym,
                asset_type='bist',
                context_len=60,
                horizon_len=8,
                show_plot=False,
                save_plot=True,
                interval='1h'
            )
            if res_plot and res_plot[0] and os.path.exists(res_plot[0]):
                with open(res_plot[0], 'rb') as photo:
                    await update.message.reply_photo(
                        photo=photo, 
                        caption=f"🌟 *{sym}* Saatlik Detay Grafiği", 
                        parse_mode='Markdown'
                    )
        except Exception as e:
            logger.error(f"Grafik gönderme hatası {sym}: {e}")

def main():
    token = os.getenv("TELEGRAM_PREDICTOR_TOKEN")
    if not token:
        logger.error("TELEGRAM_PREDICTOR_TOKEN .env dosyasında bulunamadı!")
        sys.exit(1)
        
    logger.info("TimesFM Telegram Dinleyici Botu başlatılıyor...")
    
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("tahmin", tahmin))
    application.add_handler(CommandHandler("favoriekle", favoriekle))
    application.add_handler(CommandHandler("favoricikar", favoricikar))
    application.add_handler(CommandHandler("favoriler", favoriler))
    application.add_handler(CommandHandler("kiyasla", kiyasla))
    application.add_handler(CommandHandler("temizle", temizle))
    application.add_handler(CommandHandler("gunici", gunici))
    application.add_handler(CommandHandler("saatlik", saatlik))
    application.add_handler(CommandHandler("sabah", sabah_komutu))

    # JobQueue for daily report at 09:00 TR Time
    # If job_queue isn't installed, this might throw an error. In PTB v20 it's typically built-in or requires python-telegram-bot[job-queue].
    tz = pytz.timezone('Europe/Istanbul')
    t = datetime.time(hour=9, minute=55, tzinfo=tz)
    
    if application.job_queue:
        application.job_queue.run_daily(daily_report, time=t)
        logger.info("Sabah bülteni görevi saat 09:55 (TR) için zamanlandı.")
    else:
        logger.warning("JobQueue aktif değil. Sabah bülteni çalışmayacak. Lütfen 'pip install python-telegram-bot[job-queue]' kurulu olduğundan emin olun.")

    # Botu çalıştır
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
