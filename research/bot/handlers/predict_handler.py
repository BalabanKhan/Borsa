import os
import asyncio
import datetime
import pytz
import logging
from telegram import Update
from telegram.ext import ContextTypes
from research.bot.utils import check_auth
from research.market_predictor import predict_future, evaluate_model_accuracy
import data_sources
import pandas as pd

logger = logging.getLogger("research.bot.handlers.predict")

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
        # Ayrı thread'de çalıştır
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
                if best_mape is None:
                    best_mape = await asyncio.to_thread(evaluate_model_accuracy, symbol, asset_type, interval, context_len, horizon_len)
                
                if best_mape is not None:
                    opt_tag = " (En Düşük Hata)" if is_auto_optimized else ""
                    unit_str = "saat" if interval == '1h' else "gün"
                    mape_text = f"⚙️ Veri Uzunluğu: *{context_len} {unit_str}*{opt_tag}\n📉 AI Hata Payı (MAPE): *%{best_mape:.2f}*\n"
                    
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
            
            with open(image_path, 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption=caption, parse_mode='Markdown')
            
            await msg.delete()
        else:
            await msg.edit_text(f"❌ *[{symbol}]* verisi çekilemedi veya grafiği oluşturulurken bir hata meydana geldi.", parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Tahmin hatası: {e}", exc_info=True)
        await msg.edit_text(f"❌ Beklenmedik bir hata oluştu:\n`{str(e)}`", parse_mode='Markdown')
