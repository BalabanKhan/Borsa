import os
import asyncio
import datetime
import pytz
import logging
import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from research.bot.utils import check_auth
from research.bot.scanners import bist_scanner, crypto_scanner, smc_scanner
from research.market_predictor import predict_future, evaluate_model_accuracy
import data_sources

logger = logging.getLogger("research.bot.handlers.scan")

async def gunici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """BIST 50 içinden seans sonuna kadar yükselecek en iyi 3 hisseyi bulur."""
    if not await check_auth(update): return
    
    msg = await update.message.reply_text("⚡️ *BIST 50 Gün İçi Sinyal Taraması Başladı...*\n(Trend + Momentum + Hacim + RSI < 75 algoritması çalıştırılıyor, lütfen bekleyin)", parse_mode='Markdown')
    
    try:
        top_stocks = await asyncio.to_thread(bist_scanner.run_intraday_scan)
        
        if not top_stocks:
            await msg.edit_text("⚠️ *Gün İçi Sinyal*: Şu anki piyasa koşullarında kriterleri (Trend + RSI<75) karşılayan BIST 50 hissesi bulunamadı.", parse_mode='Markdown')
        else:
            top_stocks.sort(key=lambda x: x['RSI'], reverse=True)
            candidates = top_stocks[:8]
            
            await msg.edit_text(f"🔍 Taramadan geçen *{len(candidates)}* aday hisse için TimesFM AI tahmini ve MAPE optimizasyonu yapılıyor... Lütfen bekleyin.", parse_mode='Markdown')
            
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
                
                best_mape = float('inf')
                best_c = 60
                for c in [32, 64, 96, 128]:
                    mape_cand = await asyncio.to_thread(evaluate_model_accuracy, ticker, 'bist', '1h', c, horizon_len)
                    if mape_cand is not None and mape_cand < best_mape:
                        best_mape = mape_cand
                        best_c = c
                        
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

async def saatlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """BIST 50 içinden TimesFM hata payı en düşük olan 3 hisseyi bulur."""
    if not await check_auth(update): return
    
    msg = await update.message.reply_text("⏳ *Saatlik AI Taraması Başladı*\nBIST 50 hisseleri için en düşük hata payı veren veri aralığı hesaplanıyor (32, 64, 96, 128 saat candidates)...\n_(Bu işlem 5-10 dakika sürebilir, lütfen bekleyin)_", parse_mode='Markdown')
    
    try:
        best_stocks = await asyncio.to_thread(bist_scanner.run_hourly_scan)
        
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

async def sabah_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """BIST 100 içinden günün en iyi 3 teyitli hissesini bulup raporlar."""
    if not await check_auth(update): return
    
    msg = await update.message.reply_text("⏳ *BIST 100 Tarama Başladı*\nBugün en çok yükselme potansiyeli olan, saatlik hacmi yüksek ve aşırı şişmemiş teyitli 3 hisse belirleniyor...\n_(Toplu veri indirme ve filtreleme yapılıyor, bu işlem 30-40 saniye sürebilir)_", parse_mode='Markdown')
    
    try:
        candidates, level, batch_data = await asyncio.to_thread(bist_scanner.scan_all_bist100)
        
        report_lines = ["🌅 *BIST 100 Günlük/Saatlik Yapay Zeka Taraması Sonuçları*:\n"]
        
        for cand in candidates:
            if cand['pct_change_1h'] >= 1.5 and cand['mape_1h'] < 1.2:
                cand['category'] = 'A'
                cand['sort_key'] = (1, cand['mape_1h'], -cand['pct_change_1h'])
            elif cand['pct_change_1h'] >= 1.5:
                cand['category'] = 'B'
                cand['sort_key'] = (2, cand['mape_1h'], -cand['pct_change_1h'])
            else:
                cand['category'] = 'C'
                cand['sort_key'] = (3, cand['mape_1h'], -cand['pct_change_1h'])

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
        
        for cand in top_3:
            sym = cand['symbol']
            try:
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
        top_longs, top_shorts = await asyncio.to_thread(crypto_scanner.run_crypto_scan)
        
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

async def tarasmc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SMC ve Matematiksel yöntemlerle (FVG, Order Block, Z-Score, ATR) tarama yapar."""
    if not await check_auth(update): return
    
    asset_type = 'crypto'
    if context.args and context.args[0].lower() == 'bist':
        asset_type = 'bist'
        
    msg_type = "Kripto" if asset_type == 'crypto' else "BIST 50"
    msg = await update.message.reply_text(f"⏳ *{msg_type} SMC Matematiksel Taraması Başladı*\n(Hacim Profili, ATR Risk Yönetimi ve Z-Score hesaplanıyor...)", parse_mode='Markdown')
    
    try:
        top_longs, top_shorts = await asyncio.to_thread(smc_scanner.run_smc_scan, asset_type)
        
        if not top_longs and not top_shorts:
            await msg.edit_text("⚠️ *SMC Taraması*: Kriterlere uyan varlık bulunamadı.", parse_mode='Markdown')
            return
            
        text = "🚀 *Matematiksel Quant SMC Raporu (CCXT + TA-Lib + Freqtrade Mantığı)*\n"
        text += "_(Kriter: Volume POC + Z-Score + Scipy Swings + VWAP/OrderBook)_\n\n"
        
        text += "📈 *Yükseliş Beklenen En İyi 3 Varlık (LONG)*:\n"
        for i, stock in enumerate(top_longs, 1):
            tp1 = stock['price'] + (stock['atr'] * 1.5)
            tp2 = stock['price'] + (stock['atr'] * 2.5)
            sl = stock['price'] - (stock['atr'] * 1.5)
            ob_text = f" | Emir Defteri (Buy Wall): +%{stock['ob_imbalance']*100:.1f}" if asset_type == 'crypto' else ""
            
            text += f"{i}️⃣ 🟢 *{stock['symbol']}* - Fiyat: {stock['price']:.4f}\n"
            text += f"   📊 Hacim POC: {stock['poc']:.4f} | VWAP: {stock['vwap']:.4f}\n"
            text += f"   ⚡️ Z-Score: {stock['z_score']:.2f}{ob_text}\n"
            text += f"   🎯 TP1 (Kısmi Kâr): {tp1:.4f} | TP2 (Ana Hedef): {tp2:.4f}\n"
            text += f"   🛑 Stop (SL): {sl:.4f} (Öneri: Fiyat TP1'e gelirse Stop'u girişe çek)\n\n"
            
        text += "📉 *Düşüş Beklenen En İyi 3 Varlık (SHORT)*:\n"
        for i, stock in enumerate(top_shorts, 1):
            tp1 = stock['price'] - (stock['atr'] * 1.5)
            tp2 = stock['price'] - (stock['atr'] * 2.5)
            sl = stock['price'] + (stock['atr'] * 1.5)
            ob_text = f" | Emir Defteri (Sell Wall): {stock['ob_imbalance']*100:.1f}%" if asset_type == 'crypto' else ""
            
            text += f"{i}️⃣ 🔴 *{stock['symbol']}* - Fiyat: {stock['price']:.4f}\n"
            text += f"   📊 Hacim POC: {stock['poc']:.4f} | VWAP: {stock['vwap']:.4f}\n"
            text += f"   ⚡️ Z-Score: {stock['z_score']:.2f}{ob_text}\n"
            text += f"   🎯 TP1 (Kısmi Kâr): {tp1:.4f} | TP2 (Ana Hedef): {tp2:.4f}\n"
            text += f"   🛑 Stop (SL): {sl:.4f} (Öneri: Fiyat TP1'e gelirse Stop'u girişe çek)\n\n"
            
        await msg.edit_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"tarasmc hatası: {e}", exc_info=True)
        await msg.edit_text(f"❌ Beklenmedik bir hata oluştu:\n`{str(e)}`", parse_mode='Markdown')

