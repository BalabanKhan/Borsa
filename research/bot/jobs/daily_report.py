import os
import asyncio
import logging
import pandas as pd
from telegram.ext import ContextTypes
from research.bot.database import load_favorites
from research.market_predictor import predict_future, evaluate_model_accuracy
import data_sources

logger = logging.getLogger("research.bot.jobs.daily_report")

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
                # Günlük Tahmin
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
                        report_lines.append(f"⚠️ *{symbol}*: Elendi (RSI {rsi:.1f} > 75 - Aşırı Alım)")
                        continue
                        
                    if pct_change_1d <= 0:
                        report_lines.append(f"🔴 *{symbol}*: Elendi (Günlük trend negatif)")
                        continue
 
                    best_c = 64
                    best_mape_val = await asyncio.to_thread(evaluate_model_accuracy, symbol, asset_type, '1h', best_c, 8)
                    if best_mape_val is None:
                        best_mape_val = 0.0

                    # Saatlik Tahmin
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
                        
                        if pct_change_1h <= 0:
                            report_lines.append(f"🔴 *{symbol}*: Elendi (Saatlik trend negatif)")
                            continue
                            
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
