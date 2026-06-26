# 99 yapılmıştır
# V3.4 Hibrit Stop Motoru ve Zaman Stopu mekanizmalarını doğrulamak için yazılmış birim test modülüdür.
# test_hybrid_stops.py

import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import sys
import os

# PYTHONPATH ayarı
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
import trade_tracker

class TestHybridStops(unittest.TestCase):
    """
    Zaman Stopu, Anti-Hunt gürültü payı ve Yapısal Zemin (EMA-20) stop-loss 
    korumalarını doğrulamak üzere geliştirilmiş test paketidir.
    """

    def setUp(self):
        """Test ortamını hazırlar; config değerlerini varsayılana çeker."""
        self.original_time_stop_enabled = config.TIME_STOP_ENABLED
        self.original_time_stop_hours = config.TIME_STOP_HOURS
        self.original_time_stop_min_profit = config.TIME_STOP_MIN_PROFIT_PCT
        self.original_time_stop_strategies = config.TIME_STOP_STRATEGIES
        self.original_hybrid_stop_enabled = config.HYBRID_STOP_ENABLED
        self.original_anti_hunt_offset = config.ANTI_HUNT_OFFSET_PCT
        self.original_structural_stop_enabled = config.STRUCTURAL_STOP_ENABLED

        # Varsayılan test parametreleri
        config.TIME_STOP_ENABLED = True
        config.TIME_STOP_HOURS = 4
        config.TIME_STOP_MIN_PROFIT_PCT = 0.5
        config.TIME_STOP_STRATEGIES = ["BIST 3: SQUEEZE KIRILIMI", "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)"]
        config.HYBRID_STOP_ENABLED = True
        config.ANTI_HUNT_OFFSET_PCT = 0.00034
        config.STRUCTURAL_STOP_ENABLED = True

    def tearDown(self):
        """Test sonrası config değerlerini orijinal hallerine geri yükler."""
        config.TIME_STOP_ENABLED = self.original_time_stop_enabled
        config.TIME_STOP_HOURS = self.original_time_stop_hours
        config.TIME_STOP_MIN_PROFIT_PCT = self.original_time_stop_min_profit
        config.TIME_STOP_STRATEGIES = self.original_time_stop_strategies
        config.HYBRID_STOP_ENABLED = self.original_hybrid_stop_enabled
        config.ANTI_HUNT_OFFSET_PCT = self.original_anti_hunt_offset
        config.STRUCTURAL_STOP_ENABLED = self.original_structural_stop_enabled

    def test_time_stop_triggered(self):
        """Zaman Stopu: Kırılım işlemi 4 saati geçtiğinde ve kâr %0.5'ten az olduğunda tetiklenmelidir."""
        # 5 saat önce açılmış bir trade simüle edelim
        entry_time = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S+00:00')
        t = {
            "ticker": "BTC/USDT",
            "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)",
            "entry_time": entry_time,
            "status": "ACTIVE",
            "entry_price": 50000.0,
            "sl": 48000.0
        }
        
        # Kâr %0.4 (Beklenen minimum %0.5'in altında)
        current_price = 50200.0
        profit_pct = 0.4
        
        t, notifications, is_closed = trade_tracker._check_time_stop(t, current_price, profit_pct)
        
        self.assertTrue(is_closed)
        self.assertEqual(t["status"], "CLOSED_TIME_STOP")
        self.assertEqual(len(notifications), 1)
        self.assertIn("ZAMAN STOPU TETİKLENDİ", notifications[0])

    def test_time_stop_not_triggered_early(self):
        """Zaman Stopu: Süre limiti (4 saat) dolmamışsa tetiklenmemelidir."""
        # 2 saat önce açılmış bir trade
        entry_time = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S+00:00')
        t = {
            "ticker": "BTC/USDT",
            "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)",
            "entry_time": entry_time,
            "status": "ACTIVE",
            "entry_price": 50000.0,
            "sl": 48000.0
        }
        
        current_price = 50200.0
        profit_pct = 0.4
        
        t, notifications, is_closed = trade_tracker._check_time_stop(t, current_price, profit_pct)
        
        self.assertFalse(is_closed)
        self.assertEqual(t["status"], "ACTIVE")
        self.assertEqual(len(notifications), 0)

    def test_time_stop_not_triggered_high_profit(self):
        """Zaman Stopu: Süre dolmuş ama kâr hedefe (%0.5) ulaşmışsa tetiklenmemelidir."""
        # 5 saat önce açılmış
        entry_time = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S+00:00')
        t = {
            "ticker": "BTC/USDT",
            "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)",
            "entry_time": entry_time,
            "status": "ACTIVE",
            "entry_price": 50000.0,
            "sl": 48000.0
        }
        
        # Kâr %0.6 (Hedefin üzerinde)
        current_price = 50300.0
        profit_pct = 0.6
        
        t, notifications, is_closed = trade_tracker._check_time_stop(t, current_price, profit_pct)
        
        self.assertFalse(is_closed)
        self.assertEqual(t["status"], "ACTIVE")
        self.assertEqual(len(notifications), 0)

    def test_time_stop_disabled_in_config(self):
        """Zaman Stopu: TIME_STOP_ENABLED = False ise süre geçse de tetiklenmemelidir."""
        config.TIME_STOP_ENABLED = False
        entry_time = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S+00:00')
        t = {
            "ticker": "BTC/USDT",
            "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)",
            "entry_time": entry_time,
            "status": "ACTIVE",
            "entry_price": 50000.0,
            "sl": 48000.0
        }
        
        current_price = 50200.0
        profit_pct = 0.4
        
        t, notifications, is_closed = trade_tracker._check_time_stop(t, current_price, profit_pct)
        
        self.assertFalse(is_closed)
        self.assertEqual(t["status"], "ACTIVE")

    @patch('trade_tracker.trailing._get_atr_cached')
    @patch('trade_tracker._get_structural_floor')
    def test_anti_hunt_offset_long(self, mock_floor, mock_atr):
        """Anti-Hunt: AL yönlü işlemde deterministik gürültü ve asimetrik offset SL seviyesine uygulanmalıdır."""
        mock_floor.return_value = None  # Yapısal zemin hesaplamasını devre dışı bırak
        mock_atr.return_value = None    # Gerçek ATR verisini devre dışı bırak
        
        ticker = "BTC/USDT"
        t = {
            "ticker": ticker,
            "strategy": "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)",
            "entry_price": 50000.0,
            "sl": 48000.0,
            "highest_high": 50000.0,
            "trailing_dist": 2000.0,
            "trailing_active": True
        }
        
        # Kar: %2.0, ATR Çarpanı: 2.5 (Çünkü profit_pct < 5.0). multiplier/2.5 = 1.0. current_trailing_dist = 2000.0
        # Fiyat yükselsin
        current_price = 51000.0
        profit_pct = 2.0
        
        t_updated, notifications = trade_tracker._update_trailing_stop(t, current_price, profit_pct, "AL", "KRİPTO 3: SAHTE KIRILIM FİLTRESİ (RETEST)")
        
        # En yüksek fiyat 51000 oldu. new_sl = 51000 - 2000 = 49000.
        # Ticker gürültüsü:
        ticker_noise = (sum(ord(c) for c in ticker) % 100) / 100000.0
        expected_offset = config.ANTI_HUNT_OFFSET_PCT + ticker_noise
        expected_sl = 49000.0 * (1.0 - expected_offset)
        
        self.assertAlmostEqual(t_updated["sl"], expected_sl, places=4)

    @patch('trade_tracker._get_structural_floor')
    def test_structural_floor_long_zemin_limit(self, mock_floor):
        """Yapısal Zemin: EMA-20 zemini, AL işleminde SL'yi yukarı taşımalıdır (Zemin Limit)."""
        # EMA-20 değeri normal SL'nin üzerinde olsun
        # En yüksek fiyat: 100. new_sl = 100 - 5 = 95.
        # Ama EMA-20 zemini 98 olsun. Yapısal zemin yeni SL'yi 98 * 0.999 = 97.902 yapmalıdır.
        mock_floor.return_value = 98.0
        
        t = {
            "ticker": "XU100.IS",
            "strategy": "BIST 3: SQUEEZE KIRILIMI",
            "entry_price": 100.0,
            "sl": 90.0,
            "highest_high": 100.0,
            "trailing_dist": 5.0,
            "trailing_active": True
        }
        
        current_price = 100.0
        profit_pct = 0.0
        
        t_updated, notifications = trade_tracker._update_trailing_stop(t, current_price, profit_pct, "AL", "BIST 3: SQUEEZE KIRILIMI")
        
        # EMA-20 olmadan SL: (100 - 5) * (1.0 - offset). Offset = 0.00034 + gürültü.
        # EMA-20 ile new_sl = max(95, 98 * 0.999) = 97.902.
        # offset uygulandıktan sonra: 97.902 * (1.0 - offset).
        ticker_noise = (sum(ord(c) for c in "XU100.IS") % 100) / 100000.0
        expected_offset = config.ANTI_HUNT_OFFSET_PCT + ticker_noise
        expected_sl = 97.902 * (1.0 - expected_offset)
        
        self.assertAlmostEqual(t_updated["sl"], expected_sl, places=4)

    # 99 yapılmıştır
    # Sinyal verilerinin inanç detayları ve ham indikatör verilerinin trade_journal.csv'ye
    # doğru şekilde aktarılmasını ve eski kayıtların göç (migration) uyumluluğunu test eder.
    def test_journal_writing_and_migration(self):
        """Trade Journal: Yeni eklenen conviction kolonlarının yazılmasını ve eski dosyaların otomatik göçünü doğrular."""
        import csv
        test_csv = "test_trade_journal.csv"
        
        # Orijinal dosyayı geçici olarak değiştir
        original_csv = trade_tracker.repository.TRADE_JOURNAL_CSV
        trade_tracker.repository.TRADE_JOURNAL_CSV = test_csv
        
        try:
            # 1. Eski 18-kolonlu bir dosya yapısı simüle et
            old_headers = [
                "tarih", "sembol", "market", "strateji", "sinyal", "giris_fiyat",
                "cikis_fiyat", "sl", "tp", "net_pnl_pct", "rr_ratio", "rr_achieved",
                "sure", "sonuc", "entry_time", "exit_time", "is_watch", "indicators"
            ]
            old_row = ["2026-06-15", "BTC/USDT", "KRIPTO", "KRİPTO 3", "AL", "50000.0", "51000.0", "48000.0", "54000.0", "2.0", "2.0", "0.5", "1s", "KAZANC", "", "", "FALSE", "RSI:50"]
            
            with open(test_csv, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(old_headers)
                writer.writerow(old_row)
                
            # 2. Yeni 32-kolonlu bir trade yazdır
            new_trade = {
                "ticker": "ETH/USDT",
                "market": "KRIPTO",
                "strategy": "KRİPTO 3",
                "signal": "AL",
                "entry_price": 3000.0,
                "exit_price": 3100.0,
                "sl": 2900.0,
                "tp": 3300.0,
                "status": "CLOSED_TP",
                "entry_time": "2026-06-15 12:00:00+00:00",
                "exit_time": "2026-06-15 13:00:00+00:00",
                "is_watch": False,
                "indicators": {"RSI": 55},
                "conviction_score": 75.0,
                "conviction_grade": "STRONG",
                "position_size_pct": 100.0,
                "conviction_details": {
                    "adx": 12.0, "ema_alignment": 8.0, "rsi": 10.0, "rsi_direction": 3.0,
                    "volume_ratio": 15.0, "dollar_volume": 8.0, "rr_ratio": 15.0,
                    "engulfing": 7.0, "regime": 8.0, "macro": 7.0, "penalty": 7.0
                }
            }
            
            # Yazma metodunu çağır (bu metot içten migrasyonu da tetikler)
            repo = trade_tracker.repository.JsonTradeRepository()
            repo._write_trade_journal_csv(new_trade)
            
            # 3. Dosyayı oku ve doğrula
            with open(test_csv, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                headers = next(reader)
                rows = list(reader)
                
            # Başlık boyutu kontrolü
            self.assertEqual(len(headers), 32)
            self.assertEqual(headers[-1], "c_penalty")
            
            # İlk satırın (eski veri) 32 kolona uzatıldığını ve son değerlerin boş olduğunu doğrula
            self.assertEqual(len(rows[0]), 32)
            self.assertEqual(rows[0][1], "BTC/USDT")
            self.assertEqual(rows[0][18], "")  # conviction_score alanı boş olmalı
            
            # İkinci satırın (yeni veri) 32 kolona ve doğru değerlere sahip olduğunu doğrula
            self.assertEqual(len(rows[1]), 32)
            self.assertEqual(rows[1][1], "ETH/USDT")
            self.assertEqual(rows[1][18], "75.0")  # conviction_score
            self.assertEqual(rows[1][19], "STRONG")  # conviction_grade
            self.assertEqual(rows[1][20], "100.0")  # position_size_pct
            self.assertEqual(rows[1][21], "12.0")  # c_adx
            self.assertEqual(rows[1][31], "7.0")  # c_penalty
            
        finally:
            # Temizlik
            trade_tracker.repository.TRADE_JOURNAL_CSV = original_csv
            if os.path.exists(test_csv):
                os.remove(test_csv)

if __name__ == "__main__":
    unittest.main()
