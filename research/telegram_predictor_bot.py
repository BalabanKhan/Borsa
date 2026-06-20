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

    args_lower = [a.lower().strip("`'\".,") for a in args]
    interval = '1d'
    
    if 'saat' in args_lower:
        interval = '1h'
        args_lower.remove('saat')
    elif 'saatlik' in args_lower:
        interval = '1h'
        args_lower.remove('saatlik')
    elif 'gün' in args_lower:
        interval = '1d'
        args_lower.remove('gün')
    elif 'günlük' in args_lower:
        interval = '1d'
        args_lower.remove('günlük')
        
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
        
    # BIST Saatlik tahminlerde seans sonuna kadar (18:00 TR) dinamik horizon
    if interval == '1h' and asset_type == 'bist' and len(numbers) < 2:
        tz = pytz.timezone('Europe/Istanbul')
        now = datetime.datetime.now(tz)
        if now.weekday() < 5 and 10 <= now.hour < 18:
            horizon_len = 18 - now.hour
            if horizon_len <= 0:
                horizon_len = 8
        else:
            horizon_len = 8
            
    is_auto_optimized = False
    interval_str = "Saatlik" if interval == '1h' else "Günlük"
    
    # BIST tahminlerinde otomatik optimizasyon (Eğer kullanıcı manuel geçmiş gün/saat girmediyse)
    if asset_type == 'bist' and len(numbers) < 1:
        is_auto_optimized = True
        status_msg = await update.message.reply_text(f"🔍 *[{symbol}]* için en düşük hata payı veren {interval_str.lower()} veri aralığı hesaplanıyor (MAPE Optimizasyonu)...", parse_mode='Markdown')
        
        if interval == '1h':
            candidates = [32, 64, 96, 128]
            default_c = 60
        else:
            candidates = [60, 90, 120, 250]
            default_c = 90
            
        best_mape_val = float('inf')
        best_c = default_c
        
        # Ayrı thread'lerde hızlıca MAPE'leri hesapla
        for c in candidates:
            mape_candidate = await asyncio.to_thread(evaluate_model_accuracy, symbol, asset_type, interval, c, horizon_len)
            if mape_candidate is not None and mape_candidate < best_mape_val:
                best_mape_val = mape_candidate
                best_c = c
        
        await status_msg.delete()
        if best_mape_val != float('inf'):
            context_len = best_c
            best_mape = best_mape_val
            
    unit_label = "saat" if interval == '1h' else "gün"
    msg = await update.message.reply_text(f"⏳ *[{symbol}]* için TimesFM {interval_str} tahmin grafiği hazırlanıyor... Lütfen bekleyin. (Geçmiş: {context_len} {unit_label})", parse_mode='Markdown')
    
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
            
            if asset_type == 'bist':
                # Eğer optimizasyonda zaten hesaplanmadıysa burada hesapla
                if best_mape is None:
                    best_mape = await asyncio.to_thread(evaluate_model_accuracy, symbol, asset_type, interval, context_len, horizon_len)
                
                if best_mape is not None:
                    opt_tag = " (En Düşük Hata)" if is_auto_optimized else ""
                    unit_str = "saat" if interval == '1h' else "gün"
                    mape_text = f"⚙️ Veri Uzunluğu: *{context_len} {unit_str}*{opt_tag}\n📉 AI Hata Payı (MAPE): *%{best_mape:.2f}*\n"
                    
                import data_sources
                import pandas as pd
                df_1d_b, _, df_1h_b = await asyncio.to_thread(data_sources.get_bist_data, symbol)
                df_data = df_1h_b if interval == '1h' else df_1d_b
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
                # Esnek Kriter: Trend + RSI < 75 (Hacim veya MACD filtresine takılanları kurtar)
                for ticker in TOP_BIST_50:
                    if len(TOP_BIST_50) == 1:
                        df = data.copy()
                    else:
                        if ticker not in data.columns.get_level_values(0): continue
                        df = data[ticker].copy()
                    df = df.dropna()
                    if df.empty: continue
                    
                    delta = df['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss
                    rsi_val = 100 - (100 / (1 + rs)).iloc[-1]
                    
                    ema_5 = df['Close'].ewm(span=5, adjust=False).mean()
                    ema_20 = df['Close'].ewm(span=20, adjust=False).mean()
                    trend = (df['Close'] > ema_5) & (ema_5 > ema_20)
                    
                    if trend.iloc[-1] and rsi_val < 75:
                        price = df['Close'].iloc[-1]
                        results.append({
                            'Ticker': ticker,
                            'RSI': rsi_val,
                            'Price': price,
                            'TP': price * 1.05,
                            'SL': price * 0.97,
                            'TP_Pct': 5.0,
                            'SL_Pct': 3.0
                        })
            
            res_df = pd.DataFrame(results)
            if res_df.empty:
                return []
            
            return res_df.to_dict('records')

        top_stocks = await asyncio.to_thread(run_intraday_scan)
        
        if not top_stocks:
            await msg.edit_text("⚠️ *Gün İçi Sinyal*: Şu anki piyasa koşullarında kriterleri (Trend + RSI<75) karşılayan BIST 50 hissesi bulunamadı.", parse_mode='Markdown')
        else:
            # Adayları RSI değerine göre sıralayıp ilk 8'ini yapay zeka süzgecine alalım
            top_stocks.sort(key=lambda x: x['RSI'], reverse=True)
            candidates = top_stocks[:8]
            
            await msg.edit_text(f"🔍 Taramadan geçen *{len(candidates)}* aday hisse için TimesFM AI tahmini ve MAPE optimizasyonu yapılıyor... Lütfen bekleyin.", parse_mode='Markdown')
            
            # Dinamik seans sonu saati
            tz = pytz.timezone('Europe/Istanbul')
            now = datetime.datetime.now(tz)
            if now.weekday() < 5 and 10 <= now.hour < 18:
                horizon_len = 18 - now.hour
                if horizon_len <= 0:
                    horizon_len = 8
            else:
                horizon_len = 8
                
            verified_results = []
            for stock in candidates:
                ticker = stock['Ticker']
                
                # MAPE Optimizasyonu
                best_mape = float('inf')
                best_c = 60
                for c in [32, 64, 96, 128]:
                    mape_cand = await asyncio.to_thread(evaluate_model_accuracy, ticker, 'bist', '1h', c, horizon_len)
                    if mape_cand is not None and mape_cand < best_mape:
                        best_mape = mape_cand
                        best_c = c
                        
                # TimesFM Tahmini
                res = await asyncio.to_thread(
                    predict_future,
                    symbol=ticker,
                    asset_type='bist',
                    context_len=best_c,
                    horizon_len=horizon_len,
                    show_plot=False,
                    save_plot=False,
                    interval='1h'
                )
                
                if res:
                    _, final_pred, pct_change, _ = res
                    
                    # ATR TP/SL Hesaplaması
                    import data_sources
                    df_1d_b, _, df_1h_b = await asyncio.to_thread(data_sources.get_bist_data, ticker)
                    if df_1h_b is not None and not df_1h_b.empty:
                        last_close = df_1h_b['close'].iloc[-1]
                        tr1 = df_1h_b['high'] - df_1h_b['low']
                        tr2 = (df_1h_b['high'] - df_1h_b['close'].shift(1)).abs()
                        tr3 = (df_1h_b['low'] - df_1h_b['close'].shift(1)).abs()
                        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                        atr = tr.rolling(window=14).mean().iloc[-1]
                        
                        tp = last_close + (atr * 2.0)
                        sl = last_close - (atr * 1.5)
                        tp_pct = ((tp - last_close) / last_close) * 100
                        sl_pct = ((last_close - sl) / last_close) * 100
                    else:
                        tp, sl, tp_pct, sl_pct = stock['TP'], stock['SL'], stock['TP_Pct'], stock['SL_Pct']
                        last_close = stock['Price']
                        
                    verified_results.append({
                        'Ticker': ticker,
                        'Price': last_close,
                        'RSI': stock['RSI'],
                        'TP': tp,
                        'SL': sl,
                        'TP_Pct': tp_pct,
                        'SL_Pct': sl_pct,
                        'pct_change_1h': pct_change,
                        'final_pred': final_pred,
                        'mape': best_mape if best_mape != float('inf') else None,
                        'best_context': best_c
                    })
                    
            if not verified_results:
                await msg.edit_text("⚠️ Yapay zeka modeliyle tahmin doğrulanamadı.")
                return
                
            # Yapay zekanın en yüksek yükseliş beklediği ilk 3'ü seç (pct_change_1h)
            verified_results.sort(key=lambda x: x['pct_change_1h'], reverse=True)
            top_3 = verified_results[:3]
            
            text = f"⚡️ *Gün İçi Yapay Zeka Teyitli Sinyal Raporu ({horizon_len} Saatlik/Seans Sonu)*\n"
            text += f"(Kriter: Trend/Hacim Kırılımı + TimesFM AI & MAPE Doğrulaması)\n\n"
            
            for i, stock in enumerate(top_3, 1):
                trend_icon = "🟢" if stock['pct_change_1h'] > 0 else "🔴"
                mape_str = f" | Hata: %{stock['mape']:.2f}" if stock['mape'] is not None else ""
                text += f"{i}️⃣ {trend_icon} *{stock['Ticker']}* - Fiyat: {stock['Price']:.2f} (RSI: {stock['RSI']:.1f}{mape_str})\n"
                text += f"   ⚙️ Optimum Veri: *{stock['best_context']} saat*\n"
                text += f"   📈 Beklenen Değişim: *{stock['pct_change_1h']:+.2f}%* (Hedef Fiyat: {stock['final_pred']:.2f})\n"
                text += f"   🎯 Hedef (TP): {stock['TP']:.2f} (+%{stock['TP_Pct']:.2f})\n"
                text += f"   🛑 Stop (SL): {stock['SL']:.2f} (-%{stock['SL_Pct']:.2f})\n\n"
                
            text += "_Not: Seans sonuna (18:00 TRT) kadar geçerli yapay zeka tahminleridir._"
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

                    # Vur-kaç seans içi işlem odaklı sabit 64 saatlik lookback
                    best_c = 64
                    best_mape_val = await asyncio.to_thread(evaluate_model_accuracy, symbol, asset_type, '1h', best_c, 8)
                    if best_mape_val is None:
                        best_mape_val = 0.0


                    # Saatlik Tahmin (Strategy A için Çoklu Zaman Dilimi Teyidi)
                    res_1h = await asyncio.to_thread(
                        predict_future,
                        symbol=symbol,
                        asset_type=asset_type,
                        context_len=best_c,
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
                            'sl_pct': sl_pct,
                            'best_context_1h': best_c,
                            'mape_1h': best_mape_val if best_mape_val != float('inf') else None
                        })
                    else:
                        report_lines.append(f"❓ *{symbol}*: Saatlik veri alınamadı.")
                else:
                    report_lines.append(f"❓ *{symbol}*: Günlük veri alınamadı.")
            except Exception as e:
                report_lines.append(f"❌ *{symbol}*: Hata oluştu.")
                
        # Kademeli öncelik sınıflandırması (A -> B -> C) ve sıralama tuşunu oluşturma
        for cand in candidates:
            # Sınıf A: Yüksek Kazanç (>= %1.5) + Düşük Hata (< %1.2)
            if cand['pct_change_1h'] >= 1.5 and cand['mape_1h'] < 1.2:
                cand['category'] = 'A'
                cand['sort_key'] = (1, cand['mape_1h'], -cand['pct_change_1h'])
            # Sınıf B: Yüksek Kazanç (>= %1.5) + Orta/Yüksek Hata (>= %1.2)
            elif cand['pct_change_1h'] >= 1.5:
                cand['category'] = 'B'
                cand['sort_key'] = (2, cand['mape_1h'], -cand['pct_change_1h'])
            # Sınıf C: Düşük Kazanç (< %1.5) + Düşük Hata (< %1.2)
            else:
                cand['category'] = 'C'
                cand['sort_key'] = (3, cand['mape_1h'], -cand['pct_change_1h'])

        # Kademeli öncelik tuşuna göre sırala
        candidates.sort(key=lambda x: x.get('sort_key', (4, 999.0, 0.0)))
        top_3 = candidates[:3]
        
        if top_3:
            report_lines.append("\n🏆 *Günün En İyi Tahminleri (Teyitli)*:")
            for i, cand in enumerate(top_3, 1):
                sym = cand['symbol']
                mape_info = f" (Hata: %{cand['mape_1h']:.2f})" if cand.get('mape_1h') is not None else ""
                report_lines.append(f"{i}️⃣ *{sym}* [Sınıf {cand.get('category', 'C')}]: Günlük +{cand['pct_change_1d']:.1f}% | Saatlik +{cand['pct_change_1h']:.1f}%{mape_info} | RSI: {cand['rsi']:.1f}")
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
                        context_len=cand.get('best_context_1h', 60),
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
                                caption=f"🌟 *{sym}* Saatlik Detay Grafiği (Geçmiş: {cand.get('best_context_1h', 60)}s, Hata: %{cand.get('mape_1h', 0.0):.2f})", 
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

async def taracrypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """TimesFM ile kripto varlıkları tarayıp 24 saatlik en çok artacak ve düşecek 3 varlığı tahmin eder."""
    if not await check_auth(update): return
    
    msg = await update.message.reply_text(
        "⏳ *Kripto Yapay Zeka Taraması Başladı (24 Saatlik)*\n"
        "Varlıklar için en düşük hata payı veren veri aralığı hesaplanıyor ve TimesFM ile 24 saatlik gelecek tahmini yapılıyor...\n"
        "_(Bu işlem 1-2 dakika sürebilir, lütfen bekleyin)_",
        parse_mode='Markdown'
    )
    
    try:
        from config import TOP_CRYPTO_SCAN
        
        def run_crypto_scan():
            results = []
            for symbol in TOP_CRYPTO_SCAN:
                try:
                    import data_sources
                    # 1h verisini çek
                    df_1h = data_sources.get_crypto_1h_data(symbol)
                    if df_1h is None or df_1h.empty or len(df_1h) < 150:
                        continue
                    
                    close = df_1h['close'].iloc[-1]
                    ema_20 = df_1h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
                    ema_50 = df_1h['close'].ewm(span=50, adjust=False).mean().iloc[-1]
                    
                    # RSI hesaplama
                    delta = df_1h['close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss
                    rsi = (100 - (100 / (1 + rs))).iloc[-1]
                    
                    # MAPE Optimizasyonu
                    best_mape = float('inf')
                    best_c = 64
                    for c in [64, 128]:
                        mape = evaluate_model_accuracy(
                            symbol=symbol,
                            asset_type='crypto',
                            interval='1h',
                            context_len=c,
                            horizon_len=24,
                            preloaded_dfs=(None, None, df_1h)
                        )
                        if mape is not None and mape < best_mape:
                            best_mape = mape
                            best_c = c
                            
                    if best_mape == float('inf'):
                        best_mape = 0.0
                        
                    res = predict_future(
                        symbol=symbol,
                        asset_type='crypto',
                        context_len=best_c,
                        horizon_len=24,
                        show_plot=False,
                        save_plot=True,
                        interval='1h',
                        preloaded_dfs=(None, None, df_1h)
                    )
                    
                    if res and res[0]:
                        image_path, final_pred, pct_change, _ = res
                        results.append({
                            'symbol': symbol,
                            'price': close,
                            'final_pred': final_pred,
                            'pct_change': pct_change,
                            'mape': best_mape,
                            'best_context': best_c,
                            'ema_20': ema_20,
                            'ema_50': ema_50,
                            'rsi': rsi,
                            'image_path': image_path
                        })
                except Exception as e:
                    logger.error(f"Scan error for {symbol}: {e}")
            
            # Trend ve indikatör filtreleriyle adayları ayır
            long_candidates = []
            short_candidates = []
            
            for item in results:
                is_bullish = item['price'] > item['ema_20']
                is_bearish = item['price'] < item['ema_20']
                
                if item['pct_change'] > 0 and is_bullish and item['rsi'] < 70:
                    long_candidates.append(item)
                elif item['pct_change'] < 0 and is_bearish and item['rsi'] > 30:
                    short_candidates.append(item)
            
            # Sırala
            long_candidates.sort(key=lambda x: x['pct_change'], reverse=True)
            short_candidates.sort(key=lambda x: x['pct_change'])
            
            # Yetersiz aday durumunda yedekleri kullan
            if len(long_candidates) < 3:
                fallback_longs = [r for r in results if r['pct_change'] > 0 and r not in long_candidates]
                fallback_longs.sort(key=lambda x: x['pct_change'], reverse=True)
                long_candidates.extend(fallback_longs)
                
            if len(short_candidates) < 3:
                fallback_shorts = [r for r in results if r['pct_change'] < 0 and r not in short_candidates]
                fallback_shorts.sort(key=lambda x: x['pct_change'])
                short_candidates.extend(fallback_shorts)
                
            return long_candidates[:3], short_candidates[:3]

        top_longs, top_shorts = await asyncio.to_thread(run_crypto_scan)
        
        if not top_longs and not top_shorts:
            await msg.edit_text("⚠️ *Kripto Taraması*: Yeterli tahmin verisi üretilemedi.", parse_mode='Markdown')
            return
            
        text = "🚀 *TimesFM 24 Saatlik Yapay Zeka Kripto Tarama Raporu*\n"
        text += "_(Kriter: Trend/EMA/RSI Filtresi + TimesFM AI & MAPE Doğrulaması)_\n\n"
        
        text += "📈 *Yükseliş Beklenen En İyi 3 Varlık (LONG)*:\n"
        for i, stock in enumerate(top_longs, 1):
            text += f"{i}️⃣ 🟢 *{stock['symbol']}* - Fiyat: {stock['price']:.4f} (RSI: {stock['rsi']:.1f} | Hata: %{stock['mape']:.2f})\n"
            text += f"   ⚙️ Optimum Veri: *{stock['best_context']} saat*\n"
            text += f"   📈 Beklenen Değişim: *{stock['pct_change']:+.2f}%* (Hedef: {stock['final_pred']:.4f})\n\n"
            
        text += "📉 *Düşüş Beklenen En İyi 3 Varlık (SHORT)*:\n"
        for i, stock in enumerate(top_shorts, 1):
            text += f"{i}️⃣ 🔴 *{stock['symbol']}* - Fiyat: {stock['price']:.4f} (RSI: {stock['rsi']:.1f} | Hata: %{stock['mape']:.2f})\n"
            text += f"   ⚙️ Optimum Veri: *{stock['best_context']} saat*\n"
            text += f"   📉 Beklenen Değişim: *{stock['pct_change']:+.2f}%* (Hedef: {stock['final_pred']:.4f})\n\n"
            
        text += "_Not: Önümüzdeki 24 saat için geçerli yapay zeka tahminleridir._"
        
        await msg.edit_text(text, parse_mode='Markdown')
        
        # En iyi gainer ve en iyi loser grafiklerini gönder
        sent_images = []
        if top_longs:
            sent_images.append((top_longs[0], "📈 En Çok Yükseliş Beklenen (LONG)"))
        if top_shorts:
            sent_images.append((top_shorts[0], "📉 En Çok Düşüş Beklenen (SHORT)"))
            
        for stock, label in sent_images:
            try:
                if os.path.exists(stock['image_path']):
                    with open(stock['image_path'], 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption=f"🌟 *{stock['symbol']}* ({label}) 24s AI Grafiği\n(Geçmiş: {stock['best_context']}s, Hata: %{stock['mape']:.2f})",
                            parse_mode='Markdown'
                        )
            except Exception as e:
                logger.error(f"Grafik gönderme hatası {stock['symbol']}: {e}")
                
    except Exception as e:
        logger.error(f"Taracrypto hatası: {e}", exc_info=True)
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
    """BIST 100 içinden günün en iyi 3 teyitli hissesini bulup raporlar."""
    if not await check_auth(update): return
    
    msg = await update.message.reply_text("⏳ *BIST 100 Tarama Başladı*\nBugün en çok yükselme potansiyeli olan, saatlik hacmi yüksek ve aşırı şişmemiş teyitli 3 hisse belirleniyor...\n_(Toplu veri indirme ve filtreleme yapılıyor, bu işlem 30-40 saniye sürebilir)_", parse_mode='Markdown')
    
    try:
        from config import TOP_BIST
        
        # BIST 100 hisselerinin tamamını tarıyoruz
        bist_targets = TOP_BIST
        
        report_lines = ["🌅 *BIST 100 Günlük/Saatlik Yapay Zeka Taraması Sonuçları*:\n"]
        
        # Zaman alıcı işlemleri thread içinde yapabilmek için fonksiyon tanımlıyoruz
        def scan_all_bist100():
            import data_sources
            import pandas as pd
            import pandas_ta as ta
            
            # 1. BIST 100 verilerini toplu olarak çekiyoruz
            print(f"BIST 100 toplu veri indiriliyor (toplam {len(bist_targets)} hisse)...")
            batch_data = data_sources.get_bist_data_batch(bist_targets, batch_size=35)
            
            def apply_filter(vol_mult, rsi_limit, ema_check):
                scanned_candidates = []
                for symbol in bist_targets:
                    try:
                        dfs = batch_data.get(symbol)
                        if not dfs or dfs[0] is None or dfs[2] is None:
                            continue
                            
                        df_1d, df_4h, df_1h = dfs
                        
                        # Filtre A: Saatlik Hacim Kontrolü
                        if len(df_1h) >= 20:
                            last_vol = df_1h['volume'].iloc[-1]
                            avg_vol_20 = df_1h['volume'].rolling(20).mean().iloc[-1]
                            if pd.isna(avg_vol_20) or avg_vol_20 == 0:
                                avg_vol_20 = 1.0
                            if last_vol <= avg_vol_20 * vol_mult:
                                continue
                        else:
                            continue

                        # Filtre B: Saatlik (1h) RSI Kontrolü (RSI < rsi_limit)
                        if len(df_1h) >= 15:
                            df_1h_copy = df_1h.copy()
                            df_1h_copy.ta.rsi(length=14, append=True)
                            rsi_col = 'rsi_14' if 'rsi_14' in df_1h_copy.columns else 'RSI_14'
                            if rsi_col in df_1h_copy.columns:
                                rsi_1h = df_1h_copy[rsi_col].iloc[-1]
                                if pd.isna(rsi_1h) or rsi_1h > rsi_limit:
                                    continue
                            else:
                                continue
                        else:
                            continue

                        # Günlük Tahmin
                        res_1d = predict_future(
                            symbol=symbol, 
                            asset_type='bist', 
                            context_len=90,
                            horizon_len=7, 
                            show_plot=False,
                            save_plot=False,
                            interval='1d',
                            preloaded_dfs=dfs
                        )
                        
                        if res_1d:
                            _, final_pred_1d, pct_change_1d, rsi_1d = res_1d
                            
                            # Filtre C: Günlük trend negatifse ele
                            if pct_change_1d <= 0:
                                continue
                            
                            # Vur-kaç seans içi işlem odaklı sabit 64 saatlik lookback
                            best_c = 64
                            best_mape_val = evaluate_model_accuracy(symbol, 'bist', '1h', best_c, 8, preloaded_dfs=dfs)
                            if best_mape_val is None:
                                best_mape_val = 0.0

                            # Saatlik Tahmin
                            res_1h = predict_future(
                                symbol=symbol,
                                asset_type='bist',
                                context_len=best_c,
                                horizon_len=8,
                                show_plot=False,
                                save_plot=False,
                                interval='1h',
                                preloaded_dfs=dfs
                            )
                            
                            if res_1h:
                                _, final_pred_1h, pct_change_1h, _ = res_1h
                                
                                # Filtre D: Saatlik trend negatifse ele
                                if pct_change_1h <= 0:
                                    continue
                                    
                                last_close = df_1h['close'].iloc[-1]
                                
                                # Filtre E: EMA 5 Kontrolü
                                if ema_check:
                                    ema5 = df_1h['close'].ewm(span=5, adjust=False).mean()
                                    last_ema5 = ema5.iloc[-1]
                                    if last_close <= last_ema5:
                                        continue
                                    
                                # ATR ve TP/SL
                                tr1 = df_1h['high'] - df_1h['low']
                                tr2 = (df_1h['high'] - df_1h['close'].shift(1)).abs()
                                tr3 = (df_1h['low'] - df_1h['close'].shift(1)).abs()
                                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                                atr = tr.rolling(window=14).mean().iloc[-1]
                                
                                tp = last_close + (atr * 2.0)
                                sl = last_close - (atr * 1.5)
                                tp_pct = ((tp - last_close) / last_close) * 100
                                sl_pct = ((last_close - sl) / last_close) * 100
                                    
                                scanned_candidates.append({
                                    'symbol': symbol,
                                    'pct_change_1d': pct_change_1d,
                                    'pct_change_1h': pct_change_1h,
                                    'rsi': rsi_1h,
                                    'tp': tp,
                                    'sl': sl,
                                    'tp_pct': tp_pct,
                                    'sl_pct': sl_pct,
                                    'price': last_close,
                                    'best_context_1h': best_c,
                                    'mape_1h': best_mape_val
                                })
                    except Exception as e:
                        logger.error(f"Scan error for {symbol}: {e}")
                return scanned_candidates

            # Level 1 (Standart/Sabah Taraması): Hacim > 1.0, RSI < 70, EMA5 aktif
            level = 1
            results = apply_filter(vol_mult=1.0, rsi_limit=70.0, ema_check=True)
            
            # Level 2 (Esnek/Fallback): Hacim > 0.8, RSI < 75, EMA5 pasif
            if not results:
                print("Level 1 (Standart) filtrelerinden geçen hisse bulunamadı. Level 2 (Esnek/Fallback) deneniyor...")
                level = 2
                results = apply_filter(vol_mult=0.8, rsi_limit=75.0, ema_check=False)
                
            return results, level, batch_data
  
        candidates, level, batch_data = await asyncio.to_thread(scan_all_bist100)
        
        # 3. Kademeli öncelik sınıflandırması (A -> B -> C) ve sıralama tuşunu oluşturma
        for cand in candidates:
            # Sınıf A: Yüksek Kazanç (>= %1.5) + Düşük Hata (< %1.2)
            if cand['pct_change_1h'] >= 1.5 and cand['mape_1h'] < 1.2:
                cand['category'] = 'A'
                cand['sort_key'] = (1, cand['mape_1h'], -cand['pct_change_1h'])
            # Sınıf B: Yüksek Kazanç (>= %1.5) + Orta/Yüksek Hata (>= %1.2)
            elif cand['pct_change_1h'] >= 1.5:
                cand['category'] = 'B'
                cand['sort_key'] = (2, cand['mape_1h'], -cand['pct_change_1h'])
            # Sınıf C: Düşük Kazanç (< %1.5) + Düşük Hata (< %1.2)
            else:
                cand['category'] = 'C'
                cand['sort_key'] = (3, cand['mape_1h'], -cand['pct_change_1h'])

        # Kademeli öncelik tuşuna göre sırala (En düşük kademe sayısı, en düşük hata, en yüksek kazanç)
        candidates.sort(key=lambda x: x.get('sort_key', (4, 999.0, 0.0)))
        top_3 = candidates[:3]
        
        if top_3:
            if level == 2:
                report_lines.append("⚠️ *ÖNEMLİ NOT: Bugün standart tarama filtrelerini geçen hisse bulunamadığı için ESNEK/YEDEK filtreler (Hacim Artışı > 0.8x, RSI < 75, EMA 5 pasif) kullanılmıştır.*\n")
            else:
                report_lines.append("✅ *Filtre Durumu: Tüm standart tarama filtreleri (Hacim > 1.0x, RSI < 70, EMA 5) başarıyla karşılanmıştır.*\n")
                
            report_lines.append("🏆 *Günün En Çok Yükseliş Beklenen 3 Hissesi (Çoklu Zaman Dilimi Teyitli)*:\n")
            for i, cand in enumerate(top_3, 1):
                sym = cand['symbol']
                mape_info = f" (Hata: %{cand['mape_1h']:.2f})" if cand.get('mape_1h') is not None else ""
                report_lines.append(f"{i}️⃣ *{sym}* [Sınıf {cand.get('category', 'C')}] - Güncel: {cand['price']:.2f}\n"
                                     f"   📈 Günlük Beklenen: *+{cand['pct_change_1d']:.1f}%* | Saatlik: *+{cand['pct_change_1h']:.1f}%*{mape_info}\n"
                                     f"   🔥 Saatlik RSI: {cand['rsi']:.1f}\n"
                                     f"   🎯 Hedef (TP): {cand['tp']:.2f} (+%{cand['tp_pct']:.2f})\n"
                                     f"   🛑 Stop (SL): {cand['sl']:.2f} (-%{cand['sl_pct']:.2f})\n")
        else:
            report_lines.append("\n⚠️ *Bugün hem standart hem de esnek filtreleri geçen BIST 100 hissesi bulunamadı.*")
            
        await msg.delete()
        await update.message.reply_text("\n".join(report_lines), parse_mode='Markdown')
        
        # Grafikleri gönder
        for cand in top_3:
            sym = cand['symbol']
            try:
                # Grafiği çizerken batch verisini preloaded olarak pasla
                dfs = batch_data.get(sym)
                res_plot = await asyncio.to_thread(
                    predict_future,
                    symbol=sym,
                    asset_type='bist',
                    context_len=cand.get('best_context_1h', 64),
                    horizon_len=8,
                    show_plot=False,
                    save_plot=True,
                    interval='1h',
                    preloaded_dfs=dfs
                )
                if res_plot and res_plot[0] and os.path.exists(res_plot[0]):
                    with open(res_plot[0], 'rb') as photo:
                        await update.message.reply_photo(
                            photo=photo, 
                            caption=f"🌟 *{sym}* Saatlik Detay Grafiği (Geçmiş: {cand.get('best_context_1h', 64)}s, Hata: %{cand.get('mape_1h', 0.0):.2f})", 
                            parse_mode='Markdown'
                        )
            except Exception as e:
                logger.error(f"Grafik gönderme hatası {sym}: {e}")
                
    except Exception as e:
        logger.error(f"Sabah komutu hatası: {e}", exc_info=True)
        await msg.edit_text(f"❌ Beklenmedik bir hata oluştu:\n`{str(e)}`", parse_mode='Markdown')

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
    application.add_handler(CommandHandler("tara", sabah_komutu))
    application.add_handler(CommandHandler("taracrypto", taracrypto))

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
