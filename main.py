"""
main.py
Borsa Asistanı Ana Döngü (Hibrit Sistem: BIST 100 + Kripto)
"""
import os
import sys
import asyncio
import gc
import time
import json
import tempfile
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode

# ════ Profesyonel Logging Yapılandırması ════
import logging
logger = logging.getLogger("quant_bot")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    _file_handler = RotatingFileHandler(
        "bot.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(_file_handler)
    
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_console_handler)

from data_fetcher import scan_all_markets, get_current_prices
from trade_tracker import add_trade, check_active_trades, load_trades
from circuit_breaker import is_circuit_open, get_status_message as cb_status
from market_snapshot import send_snapshot_excel

# ════ V3.2 Kaos Çözümleri ════
from penalty_box import (
    is_asset_penalized, is_daily_commission_exceeded,
    record_trade_commission, get_penalty_status
)
from signal_decay import should_block_entry
from strategy_scorecard import (
    is_strategy_disabled, run_darwinism, generate_weekly_report,
    get_scorecard_status
)
import config
from config import SCORECARD_MIN_TRADES, SCORECARD_AUTO_DISABLE_DAYS
from quarantine import (
    check_staleness, is_quarantined, generate_quarantine_alert,
    get_quarantine_status, cleanup_expired_quarantines
)
from filter_health import (
    flush_cycle_stats, check_analysis_paralysis, get_filter_health_summary,
    record_filter_kill, record_candidate, record_survivor
)

# Aynı sinyal tekrar spamını önlemek için cooldown mekanizması (dosyaya yazılır → restart korumalı)
COOLDOWN_FILE = "signal_cooldown.json"
COOLDOWN_SECONDS = 3600  # 1 saat

def _load_cooldown():
    """Cooldown state'ini dosyadan yükle (restart sonrası amnezi koruması)."""
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, 'r') as f:
                data = json.load(f)
                return {tuple(k.split("|")): v for k, v in data.items()}
        except Exception:
            logger.warning("[_load_cooldown] Dosya okunamadı, sıfırdan başlatılıyor", exc_info=True)
    return {}

def _save_cooldown(cooldown_dict):
    """Cooldown state'ini dosyaya atomik olarak kaydet."""
    try:
        data = {f"{k[0]}|{k[1]}": v for k, v in cooldown_dict.items()}
        # Atomic write — crash-safe
        tmp_fd, tmp_path = tempfile.mkstemp(dir='.', suffix='.tmp')
        with os.fdopen(tmp_fd, 'w') as f:
            json.dump(data, f)
        os.replace(tmp_path, COOLDOWN_FILE)
    except Exception:
        logger.warning("[_save_cooldown] Cooldown kaydedilemedi", exc_info=True)

signal_cooldown = _load_cooldown()
HEARTBEAT_INTERVAL = 6 * 3600  # 6 saatte bir heartbeat
last_heartbeat = 0
FAILED_MSG_FILE = "failed_messages.json"
_price_fail_count = 0
_last_hourly_summary = 0
_last_darwinism_run = 0  # V3.2: Haftalık Darwinizm son çalışma zamanı
last_snapshot_sent_date = ""
latest_scan_metrics = {}

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id_env = os.getenv("TELEGRAM_CHAT_ID", "")
CHAT_IDS = [cid.strip() for cid in chat_id_env.split(",") if cid.strip()]

# V3.3.2: WATCH sinyalleri için ayrı Telegram kanalı
WATCH_BOT_TOKEN = os.getenv('TELEGRAM_WATCH_BOT_TOKEN')
watch_chat_id_env = os.getenv('TELEGRAM_WATCH_CHAT_ID', '')
WATCH_CHAT_IDS = [cid.strip() for cid in watch_chat_id_env.split(',') if cid.strip()]

def format_signal_message(trade_data):
    market = trade_data.get("market", "KRİPTO")
    strategy = trade_data.get("strategy", "BİLİNMİYOR")
    
    if market == "BIST":
        header = "📈 [BIST 100 SİNYALİ]"
    elif market == "EMTİA":
        header = "⛏️ [EMTİA SİNYALİ]"
    elif market == "AYI_AVCISI":
        header = "🐻 [AYI AVCISI SHORT]"
    else:
        header = "🚀 [KRİPTO SİNYALİ]"
    
    entry_price = trade_data.get('entry_price', 0)
    sl_price = trade_data.get('sl', 0)
    tp_price = trade_data.get('tp', 0)
    signal_dir = trade_data.get('signal', 'AL')

    # FM-01: R:R bilgisi
    rr_ratio = trade_data.get('rr_ratio')
    rr_line = ""
    if rr_ratio:
        rr_line = f"<b>R:R Oranı:</b> <code>{rr_ratio:.1f}:1</code>\n"

    # V3.3: Conviction Scoring bilgisi
    conv_score = trade_data.get('conviction_score')
    conv_line = ""
    if conv_score is not None:
        conv_grade = trade_data.get('conviction_grade', 'N/A')
        conv_pos = trade_data.get('position_size_pct', 100)
        conv_emoji = {"STRONG": "🟢", "MEDIUM": "🟡", "WATCH": "🟠"}.get(conv_grade, "⚪")
        conv_line = f"{conv_emoji} <b>Conviction:</b> <code>{conv_score:.0f}/100 ({conv_grade})</code> | Poz: %{conv_pos}\n"

    conv_details = trade_data.get('conviction_details')
    details_str = ""
    if conv_details and isinstance(conv_details, dict):
        details_str = "<b>Puanlama Detayları:</b>\n"
        for k, v in conv_details.items():
            if v > 0:
                details_str += f" ├ {k}: <code>+{v:.1f}</code>\n"
        details_str += " └────────────────\n"

    # V3.4: Dinamik olarak toplanan ham göstergelerin (RSI, ADX vs.) mesaja eklenmesi
    raw_inds = trade_data.get('raw_indicators')
    if raw_inds and isinstance(raw_inds, dict):
        details_str += "<b>Giriş Metrikleri:</b>\n"
        for k, v in raw_inds.items():
            details_str += f" ├ {k}: <code>{v}</code>\n"
        details_str += " └────────────────\n"

    # FM-02: Signal TTL — Dinamik Geçerlilik Tavanı/Tabanı
    ttl_pct = 0.015  # %1.5
    if signal_dir == "AL":
        ttl_ceiling = entry_price * (1 + ttl_pct)
        ttl_floor = entry_price * (1 - ttl_pct)
        ttl_line = (
            f"\n⏰ <b>SİNYAL ÖMRÜ (TTL):</b>\n"
            f"❗ Fiyat <code>{ttl_ceiling:.4f}</code> üstüne çıkmışsa → SİNYAL ÖLDÜ, İŞLEME GİRME!\n"
            f"❗ Fiyat <code>{ttl_floor:.4f}</code> altına düşmüşse → SL YAKINLAŞMIŞ, DİKKATLİ OL!"
        )
    else:  # SAT
        ttl_floor = entry_price * (1 - ttl_pct)
        ttl_ceiling = entry_price * (1 + ttl_pct)
        ttl_line = (
            f"\n⏰ <b>SİNYAL ÖMRÜ (TTL):</b>\n"
            f"❗ Fiyat <code>{ttl_floor:.4f}</code> altına düşmüşse → SİNYAL ÖLDÜ, İŞLEME GİRME!\n"
            f"❗ Fiyat <code>{ttl_ceiling:.4f}</code> üstüne çıkmışsa → SL YAKINLAŞMIŞ, DİKKATLİ OL!"
        )

    msg = (
        f"<b>{header}</b>\n"
        f"<b>{strategy}</b>\n"
        f"-------------------------------------\n"
        f"<b>Varlık:</b> <code>{trade_data.get('ticker', 'Bilinmiyor')}</code>\n"
        f"<b>Giriş Fiyatı:</b> <code>{entry_price:.4f}</code>\n"
        f"<b>Zarar Kes (SL):</b> <code>{sl_price:.4f}</code>\n"
        f"<b>Kar Al (TP):</b> <code>{tp_price:.4f}</code>\n"
                f"{rr_line}"
        f"{conv_line}"
        f"{details_str}"
        f"-------------------------------------\n"
        f"<b>Sistem Gerekçesi:</b>\n"
        f"<i>{trade_data.get('reason', 'Sebep belirtilmemiş.')}</i>\n"
        f"{ttl_line}"
    )
    return msg

async def send_telegram_message(bot, chat_ids, message, max_retries=3):
    if not bot or not chat_ids:
        print("\n[Telegram] Konsol Çıktısı:")
        print(message.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", ""))
        return

    for chat_id in chat_ids:
        sent = False
        for attempt in range(max_retries):
            try:
                await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
                print(f"[Telegram] Mesaj gönderildi: chat_id={chat_id}")
                sent = True
                break
            except Exception as e:
                print(f"[Telegram] Deneme {attempt+1}/{max_retries} başarısız (chat_id={chat_id}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5 * (attempt + 1))  # 5s, 10s, 15s bekleme

        if not sent:
            _save_failed_message(chat_id, message)


def _save_failed_message(chat_id, message):
    """Gönderilememiş mesajları dosyaya yedekle."""
    failed = []
    if os.path.exists(FAILED_MSG_FILE):
        try:
            with open(FAILED_MSG_FILE, 'r', encoding='utf-8') as f:
                failed = json.load(f)
        except Exception:
            logger.warning(f"[_save_failed_message] Yedek dosya okunamadı", exc_info=True)
            failed = []
    failed.append({
        "chat_id": chat_id,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    try:
        with open(FAILED_MSG_FILE, 'w', encoding='utf-8') as f:
            json.dump(failed, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[_save_failed_message] Yedekleme hatası: {e}", exc_info=True)


async def _retry_failed_messages(bot):
    """Başarısız mesajları tekrar göndermeyi dene. Ana döngüde periyodik çağrılır."""
    if not os.path.exists(FAILED_MSG_FILE):
        return
    try:
        with open(FAILED_MSG_FILE, 'r', encoding='utf-8') as f:
            failed = json.load(f)
    except Exception:
        logger.warning("[_retry_failed_messages] Dosya okunamadı", exc_info=True)
        return
    if not failed:
        return

    remaining = []
    for item in failed:
        try:
            await bot.send_message(
                chat_id=item["chat_id"],
                text=f"⏰ <i>Gecikmeli mesaj ({item['timestamp'][:16]}):</i>\n\n{item['message']}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"[_retry_failed_messages] Retry başarısız chat_id={item.get('chat_id')}: {e}")
            remaining.append(item)

    with open(FAILED_MSG_FILE, 'w', encoding='utf-8') as f:
        json.dump(remaining, f, indent=2, ensure_ascii=False)

async def run_market_scan(bot, chat_ids, watch_bot=None):
    now_ist = datetime.now(ZoneInfo("Europe/Istanbul"))
    logger.info(f"[{now_ist.strftime('%Y-%m-%d %H:%M:%S')}] Hibrit piyasa taraması başlatılıyor (BIST & Kripto)...")
    
    # data_fetcher'da algoritmik taramaları yap
    # Eski cooldown'ları temizle (memory leak önleme)
    global signal_cooldown
    now_cleanup = time.time()
    signal_cooldown = {k: v for k, v in signal_cooldown.items() if now_cleanup - v < COOLDOWN_SECONDS}
    
    # FM-03: Devre Kesici kontrolü (Option B: Strateji bazlı olduğu için tarama atlanmıyor, sinyal bazlı kontrol edilecek)

    # FAZ 1: Taramayı ayrı thread'e taşı → Kör Pencere (Blind Spot) ÇÖZÜMÜ
    # scan_all_markets() senkron, 10-12 dk sürer. Bu sürede main event loop
    # SERBEST kalır → check_active_trades() her 60 saniye çalışmaya DEVAM EDER.
    loop = asyncio.get_event_loop()
    scan_start = time.time()
    signals, scan_metrics = await loop.run_in_executor(None, scan_all_markets)
    scan_duration = time.time() - scan_start
    print(f"⏱️ Tarama süresi: {scan_duration:.1f}s ({scan_duration/60:.1f} dk)")
    
    # ⚖️ Sinyal Çelişki Çözücü (Conflict Resolver)
    if getattr(config, 'CONFLICT_RESOLVER_ENABLED', False) and signals:
        try:
            from conflict_resolver import SignalConflictResolver
            resolver = SignalConflictResolver()
            active_trades = load_trades()
            original_len = len(signals)
            signals = resolver.resolve_conflicts(signals, active_trades)
            if len(signals) != original_len:
                logger.info(f"[ConflictResolver] Çelişki filtrelemesi tamamlandı: {original_len} sinyalden {len(signals)} tanesi onaylandı.")
        except Exception as cre:
            logger.error(f"[ConflictResolver] Çelişki çözümü sırasında hata: {cre}", exc_info=True)

    
    # 📊 Piyasa Snapshot'ını (Excel) güncel tut (gün sonu gönderilecektir)
    global latest_scan_metrics
    if scan_metrics:
        latest_scan_metrics = scan_metrics
        try:
            with open('last_scan_metrics.json', 'w', encoding='utf-8') as f:
                json.dump(scan_metrics, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[run_market_scan] Failed to save scan_metrics to json: {e}")

    
    # Tarama sonrası RAM temizliği (E2-micro 1GB RAM koruma)
    gc.collect()
    
    if not signals:
        global _last_hourly_summary
        now_ts = time.time()
        current_hour = datetime.now(ZoneInfo("Europe/Istanbul")).hour
        if (now_ts - _last_hourly_summary) >= 3600 and 8 <= current_hour <= 23:
            _last_hourly_summary = now_ts
            trades = load_trades()
            active_count = sum(1 for t in trades if t["status"] == "ACTIVE")
            summary = (
                f"📊 <b>Saatlik Özet</b>\n"
                f"⏰ {datetime.now(ZoneInfo('Europe/Istanbul')).strftime('%H:%M')}\n"
                f"Sinyal: 0 | Aktif Pozisyon: {active_count}\n"
                f"{get_filter_health_summary()}"
            )
            await send_telegram_message(bot, chat_ids, summary)
        return
        
    print(f"Sistem toplam {len(signals)} adet işlem kararı üretti!")

    # V3.2: Günlük komisyon limiti kontrolü (tüm sinyaller durdurulur)
    if is_daily_commission_exceeded():
        logger.warning("[V3.2] 🥊 Günlük komisyon limiti aşıldı — sinyal üretimi durduruldu.")
        await send_telegram_message(bot, chat_ids,
            "🥊 <b>GÜNLÜK KOMİSYON LİMİTİ AŞILDI</b>\n"
            "Bugün için tüm yeni sinyal üretimi durduruldu.\n"
            "Yarın otomatik sıfırlanacak."
        )
        return

    for decision in signals:
        ticker = decision.get("ticker", "Bilinmiyor")
        strategy = decision.get("strategy", "")
        
        # Cooldown kontrolü: Son 1 saat içinde aynı sinyal atıldıysa atla
        cooldown_key = (ticker, strategy)
        now_ts = time.time()
        if cooldown_key in signal_cooldown and (now_ts - signal_cooldown[cooldown_key]) < COOLDOWN_SECONDS:
            continue
        
        # Aktif işlemde zaten var mı kontrol et
        trades = load_trades()
        is_active = any(t["ticker"] == ticker and t["status"] == "ACTIVE" for t in trades)
        if is_active:
            continue

        # ════ V3.2 KAOS FİLTRELERİ (Sinyal üretilmeden ÖNCE) ════
        
        # FM-03: Devre Kesici (Per-Strategy)
        if is_circuit_open(ticker, strategy):
            logger.info(f"[FM-03] 🔴 Devre Kesici {strategy} için AKTİF — sinyal atlanıyor.")
            continue
        
        # V3.2 Kaos #4: Ceza Kutusu — varlık cezalı mı?
        if is_asset_penalized(ticker):
            logger.info(f"[V3.2 PenaltyBox] 🥊 {ticker} cezalı — sinyal engellendi.")
            continue
        
        # V3.2 Kaos #5: Darwinizm — strateji devre dışı mı?
        if is_strategy_disabled(strategy):
            logger.info(f"[V3.2 Scorecard] 🦕 {strategy} devre dışı — sinyal engellendi.")
            continue
        
        # V3.2 Kaos #2: Karantina — varlık karantinada mı?
        if is_quarantined(ticker):
            logger.info(f"[V3.2 Quarantine] 🔒 {ticker} karantinada — sinyal engellendi.")
            continue
        
        # V3.2 Kaos #3: Sinyal Erime — sinyal bayat mı?
        # should_block_entry kontrolü: fiyat TTL dışına çıkmışsa engelle
        entry_price = decision.get("entry_price", 0)
        sl_price = decision.get("sl", 0)
        tp_price = decision.get("tp", 0)
        if entry_price > 0 and sl_price > 0 and tp_price > 0:
            pseudo_trade = {
                "ticker": ticker,
                "entry_price": entry_price,
                "sl": sl_price,
                "tp": tp_price,
                "signal": decision.get("signal", "AL"),
                "signal_time": datetime.now(timezone.utc).isoformat(),
                "market": decision.get("market", "KRİPTO"),
            }
            # K-07: Signal Decay TTL kontrolü — fiyat entry'den çok saptıysa bloklansın
            should_block, block_reason = should_block_entry(pseudo_trade, entry_price)
            if should_block:
                logger.info(f'[V3.2 Signal Decay] ⏰ {ticker}: {block_reason} — sinyal engellendi.')
                continue
        
        # V3.3: Conviction Scoring bilgilerini logla
        conv_score = decision.get("conviction_score")
        conv_grade = decision.get("conviction_grade", "N/A")
        pos_size = decision.get("position_size_pct", 100)
        if conv_score is not None:
            conv_emoji = {"STRONG": "🟢", "MEDIUM": "🟡", "WATCH": "🟠"}.get(conv_grade, "⚪")
            logger.info(f"[V3.3 Conviction] {conv_emoji} {ticker}: Score={conv_score:.0f} Grade={conv_grade} Poz=%{pos_size}")
        
        # V3.3.2: WATCH grade → ayrı kanala gönder, sanal olarak izle
        if conv_grade == 'WATCH':
            if watch_bot and WATCH_CHAT_IDS:
                watch_msg = format_signal_message({
                    **decision,
                    'conviction_score': conv_score,
                    'conviction_grade': conv_grade,
                    'position_size_pct': pos_size,
                })
                # WATCH başlığı ekle
                watch_header = '👁️ <b>WATCH LIST</b> — Sadece İzle\n━━━━━━━━━━━━━━━━━━\n'
                await send_telegram_message(watch_bot, WATCH_CHAT_IDS, watch_header + watch_msg)
                logger.info(f'[WATCH] {ticker} izleme listesine gönderildi ({strategy}).')
            else:
                logger.debug(f'[WATCH] {ticker}: WATCH sinyali — bot/chat_id yok, atlanıyor.')

            # İşlemi SANAL olarak kaydet (is_watch=True)
            # İşlemi SANAL olarak kaydet (is_watch=True)
            # 99 yapılmıştır
            # V3.4: Sanal izleme işlem kaydına detaylı analiz için tüm conviction parametreleri ve
            # ham indikatör verileri doğrudan geçilmektedir.
            trade = add_trade(
                ticker=ticker,
                signal=decision.get("signal", "AL"),
                entry_price=entry_price,
                sl=sl_price,
                tp=tp_price,
                reason=decision.get("reason", "Neden belirtilmedi"),
                provider="Algorithm",
                strategy=strategy,
                indicators=decision.get("indicators", {}),
                is_watch=True,
                market=decision.get("market", "KRİPTO"),
                conviction_score=conv_score,
                conviction_grade=conv_grade,
                position_size_pct=pos_size,
                raw_indicators=decision.get("raw_indicators", {}),
                conviction_details=decision.get("conviction_details", {})
            )
            
            if trade is not None:
                if decision.get("is_day_trade"):
                    trade["is_day_trade"] = True
                    from trade_tracker import load_trades as _lt, save_trades as _st
                    all_t = _lt()
                    for t in all_t:
                        if t.get("id") == trade.get("id"):
                            t["is_day_trade"] = True
                    _st(all_t)

                logger.info(f'[WATCH] {ticker} sanal izlemeye eklendi.')

            continue  # Gerçek trade açma, sadece sanal izle
        print(f"✅ Sistem {ticker} için AL kararı verdi! ({decision.get('strategy')})")
        
        # İşlemi kaydet
        # 99 yapılmıştır
        # V3.4: Aktif işlem kaydına detaylı analiz için tüm conviction parametreleri ve
        # ham indikatör verileri doğrudan geçilmektedir.
        trade = add_trade(
            ticker=ticker,
            signal=decision.get("signal", "AL"),
            entry_price=entry_price,
            sl=sl_price,
            tp=tp_price,
            reason=decision.get("reason", "Neden belirtilmedi"),
            provider="Algorithm",
            strategy=strategy,
            indicators=decision.get("indicators", {}),
            market=decision.get("market", "KRİPTO"),
            conviction_score=conv_score,
            conviction_grade=conv_grade,
            position_size_pct=pos_size,
            raw_indicators=decision.get("raw_indicators", {}),
            conviction_details=decision.get("conviction_details", {})
        )

        if trade is None:
            continue  # DG-06 VETO veya başka sebep

        # V3.2: Komisyon kaydı
        record_trade_commission(ticker)

        # Day trade bayrağını ekle (ORB stratejisi için)
        if decision.get("is_day_trade"):
            trade["is_day_trade"] = True
            from trade_tracker import load_trades as _lt, save_trades as _st
            all_t = _lt()
            for t in all_t:
                if t.get("id") == trade.get("id"):
                    t["is_day_trade"] = True
            _st(all_t)
        
        # Telegram formatına ek verileri gönderelim
        trade["market"] = decision.get("market", "KRİPTO")
        trade["strategy"] = decision.get("strategy", "BİLİNMİYOR")
        if conv_score is not None:
            trade["conviction_score"] = conv_score
            trade["conviction_grade"] = conv_grade
            trade["position_size_pct"] = pos_size
        
        msg = format_signal_message(trade)
        await send_telegram_message(bot, chat_ids, msg)
        # K-04: Telegram gönderim başarı kontrolü
        logger.info(f'[Telegram] {ticker} sinyal mesajı gönderildi ({strategy}).')
        signal_cooldown[cooldown_key] = time.time()
        _save_cooldown(signal_cooldown)

async def main():
    print("==================================================")
    print("🤖 Borsa Asistanı (Algoritmik) Başlatılıyor...")
    print("==================================================")
    
    loop = asyncio.get_running_loop()
    bot = None
    if BOT_TOKEN:
        try:
            bot = Bot(token=BOT_TOKEN)
            print("✅ Telegram Bot bağlantısı kuruldu.")
        except Exception as e:
            print(f"❌ Telegram Bot başlatma hatası: {e}")
    else:
        print("⚠️ Uyarı: TELEGRAM_BOT_TOKEN eksik. Konsol modu aktif.")
    
    # V3.3.2: WATCH Bot başlatma
    watch_bot = None
    if WATCH_BOT_TOKEN:
        try:
            watch_bot = Bot(token=WATCH_BOT_TOKEN)
            print('✅ WATCH Telegram Bot bağlantısı kuruldu.')
            if WATCH_CHAT_IDS:
                await send_telegram_message(watch_bot, WATCH_CHAT_IDS, "👁️ <b>WATCH Bot Doğrulama</b>\nBu kanal üzerinden izleme sinyalleri (WATCH) iletilecektir. Bağlantı başarılı.")
            else:
                print('⚠️ TELEGRAM_WATCH_CHAT_ID tanımlı değil! WATCH sinyalleri gönderilemeyecek.')
        except Exception as e:
            print(f'⚠️ WATCH Bot başlatma hatası: {e}')
    else:
        print('ℹ️ WATCH Bot token tanımlı değil — WATCH sinyalleri ana kanala gönderilmeyecek.')
        
    # İlk tarama
    await run_market_scan(bot, CHAT_IDS, watch_bot=watch_bot)
    
    last_scan_time = time.time()
    SCAN_INTERVAL_MINUTES = 15
    
    print(f"\n⏰ Döngü aktif: Her {SCAN_INTERVAL_MINUTES} dakikada bir BIST ve Kripto taranacak.")
    
    global last_heartbeat
    last_heartbeat = time.time()
    
    while True:
        try:
            await asyncio.sleep(60) 
            
            # Heartbeat: 6 saatte bir "bot çalışıyor" mesajı
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
                trades = load_trades()
                active_count = sum(1 for t in trades if t["status"] == "ACTIVE")
                # V3.2: Heartbeat'e tüm modül durumlarını ekle
                hb_msg = (
                    f"💚 <b>Bot Aktif (V3.2)</b> | ⏰ {datetime.now(ZoneInfo('Europe/Istanbul')).strftime('%Y-%m-%d %H:%M')}\n"
                    f"Aktif Pozisyon: {active_count}\n"
                    f"{cb_status()}\n"
                    f"━━━ V3.2 Kaos Modülleri ━━━\n"
                    f"{get_penalty_status()}\n"
                    f"{get_quarantine_status()}\n"
                    f"{get_scorecard_status()}\n"
                    f"{get_filter_health_summary()}"
                )
                await send_telegram_message(bot, CHAT_IDS, hb_msg)
                last_heartbeat = time.time()
                
                # V3.2: Haftalık Darwinizm çalıştır (her 7 günde bir)
                global _last_darwinism_run
                if time.time() - _last_darwinism_run >= 7 * 24 * 3600:
                    _last_darwinism_run = time.time()
                    try:
                        # V3.3.2: Config parametrelerini kullan (hardcoded default yerine)
                        changes = run_darwinism(
                            min_trades=SCORECARD_MIN_TRADES,
                            window_days=SCORECARD_AUTO_DISABLE_DAYS
                        )
                        if changes:
                            darwin_msg = "🦕 <b>DARWİNİZM RAPORU</b>\n━━━━━━━━━━━━━━━━━━\n"
                            for c in changes:
                                icon = "🔴" if c["action"] == "DISABLED" else "⚠️"
                                darwin_msg += f"{icon} {c['strategy']}: {c['reason']}\n"
                            await send_telegram_message(bot, CHAT_IDS, darwin_msg)
                        
                        # Haftalık karne raporu
                        weekly = generate_weekly_report()
                        await send_telegram_message(bot, CHAT_IDS, weekly)
                        
                        # Haftalık karantina temizliği
                        cleanup_expired_quarantines()
                        # Haftalık penalty box pruning (90+ gün eski varlıkları temizle)
                        try:
                            from penalty_box import prune_old_assets
                            pruned = prune_old_assets(90)
                            if pruned > 0:
                                await send_telegram_message(bot, CHAT_IDS,
                                    f"🧹 Penalty Box temizliği: {pruned} eski varlık silindi.")
                        except Exception as e:
                            logger.warning(f"[V3.2] Penalty pruning hatası: {e}")
                        # Analiz felci kontrolü
                        paralysis = check_analysis_paralysis()
                        if paralysis:
                            await send_telegram_message(bot, CHAT_IDS, paralysis)
                    except Exception as e:
                        logger.warning(f"[V3.2] Darwinizm hatası: {e}")
            
            # Başarısız mesajları yeniden göndermeyi dene
            if bot:
                await _retry_failed_messages(bot)
            
            # Her 1 dakikada aktif işlemlerin fiyatlarını kontrol et (İzleyen Stop ve SL/TP için)
            global _price_fail_count
            trades = load_trades()
            active_tickers = list(set([t["ticker"] for t in trades if t["status"] == "ACTIVE"]))
            if active_tickers:
                current_prices = get_current_prices(active_tickers)
                if current_prices:
                    _price_fail_count = 0  # Başarılı → sayacı sıfırla
                    
                    # V3.2 Kaos #2: Karantina — stale data ve zombie trade kontrolü
                    for t_check in [t for t in trades if t["status"] == "ACTIVE"]:
                        t_ticker = t_check["ticker"]
                        if t_ticker in current_prices:
                            # Stale kontrolü: fiyat varsa karantinadan çıkar
                            from quarantine import remove_from_quarantine
                            if is_quarantined(t_ticker):
                                remove_from_quarantine(t_ticker)
                        else:
                            # Fiyat yoksa stale kontrolü
                            q_report = check_staleness(t_check)
                            if q_report:
                                q_alert = generate_quarantine_alert(q_report)
                                await send_telegram_message(bot, CHAT_IDS, q_alert)
                    
                    notifications = await loop.run_in_executor(
                        None, check_active_trades, current_prices
                    )
                    for msg in notifications:
                        await send_telegram_message(bot, CHAT_IDS, msg)
                else:
                    # Fiyat çekme başarısız → arka arkaya 3 kez olursa uyar
                    _price_fail_count += 1
                    if _price_fail_count >= 3:
                        await send_telegram_message(bot, CHAT_IDS,
                            f"🔴 <b>FİYAT ÇEKİLEMİYOR</b>\n"
                            f"⏰ {datetime.now(ZoneInfo('Europe/Istanbul')).strftime('%H:%M')}\n"
                            f"Son {_price_fail_count} denemede fiyat verisi alınamadı.\n"
                            f"Aktif pozisyonlar kontrol EDİLEMİYOR!\n"
                            f"<code>{', '.join(active_tickers[:10])}</code>"
                        )
                        _price_fail_count = -15  # 15dk cooldown (15 × 1dk = 15 döngü sessiz)
            
            # ORB Day Trade otomatik kapanış: 17:55 İstanbul saati
            now_ist = datetime.now(ZoneInfo("Europe/Istanbul"))
            if now_ist.hour == 17 and 55 <= now_ist.minute <= 59:
                trades = load_trades()
                day_trades = [t for t in trades if t.get("is_day_trade") and t["status"] == "ACTIVE"]
                if day_trades:
                    from trade_tracker import save_trades as _save_trades
                    current_prices = get_current_prices([t["ticker"] for t in day_trades])
                    for t in day_trades:
                        ticker = t["ticker"]
                        cp = current_prices.get(ticker)
                        if cp is None:
                            continue
                        entry = float(t["entry_price"])
                        pnl = ((cp - entry) / entry * 100) if t["signal"] == "AL" else ((entry - cp) / entry * 100)
                        t["status"] = "CLOSED_TP" if pnl > 0 else "CLOSED_SL"
                        close_msg = (
                            f"⏱️ <b>DAY TRADE KAPANDI (17:55)</b>\n"
                            f"Varlık: <code>{ticker}</code>\n"
                            f"Strateji: <i>{t.get('strategy', '')}</i>\n"
                            f"Giriş: {entry:.2f} → Çıkış: {cp:.2f}\n"
                            f"Net: %{pnl:.2f} {'✅' if pnl > 0 else '❌'}"
                        )
                        await send_telegram_message(bot, CHAT_IDS, close_msg)
                    # Kapanan day trade'leri arşivle
                    closed_day = [t for t in trades if t["status"] != "ACTIVE"]
                    if closed_day:
                        from trade_tracker import _archive_closed_trades
                        _archive_closed_trades(closed_day)
                    # Güncelle
                    remaining = [t for t in trades if t["status"] == "ACTIVE"]
                    _save_trades(remaining)

            # V3.4: Gün sonu (23:00 TSİ) Market Snapshot Excel Gönderimi
            if now_ist.hour == 23 and now_ist.minute == 0:
                global last_snapshot_sent_date
                today_str = now_ist.strftime("%Y-%m-%d")
                if last_snapshot_sent_date != today_str:
                    last_snapshot_sent_date = today_str
                    metrics_to_send = None
                    if latest_scan_metrics:
                        metrics_to_send = latest_scan_metrics
                    elif os.path.exists('last_scan_metrics.json'):
                        try:
                            with open('last_scan_metrics.json', 'r', encoding='utf-8') as f:
                                metrics_to_send = json.load(f)
                        except Exception:
                            pass
                    
                    if metrics_to_send and watch_bot:
                        logger.info(f"[main] Gün sonu Excel Snapshot gönderiliyor...")
                        asyncio.create_task(send_snapshot_excel(metrics_to_send))


            # 15 dakikada bir tam tarama
            if time.time() - last_scan_time >= (SCAN_INTERVAL_MINUTES * 60):
                await run_market_scan(bot, CHAT_IDS, watch_bot=watch_bot)
                last_scan_time = time.time()
                
        except KeyboardInterrupt:
            print("\n👋 Bot durduruluyor...")
            break
        except Exception as e:
            print(f"❌ Döngü hatası: {e}")
            # Hata mesajını Telegram'a gönder
            try:
                now_ist = datetime.now(ZoneInfo('Europe/Istanbul'))
                error_msg = f"⚠️ <b>SİSTEM HATASI</b>\n⏰ {now_ist.strftime('%Y-%m-%d %H:%M')}\n<code>{e}</code>\n<pre>{traceback.format_exc()[-500:]}</pre>\nBot çalışmaya devam ediyor."
                await send_telegram_message(bot, CHAT_IDS, error_msg)
            except Exception as notify_err:
                logger.error(f"[main] Hata bildirimi gönderilemedi: {notify_err}", exc_info=True)
            await asyncio.sleep(300)  # 5 dk bekle, spam yapma

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot kapatıldı.")
