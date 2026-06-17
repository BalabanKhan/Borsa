import unittest
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.defensive_engine import DefensiveExceptionManager
import circuit_breaker

class TestDefensiveEngine(unittest.TestCase):
    def setUp(self):
        DefensiveExceptionManager.reset_safe_mode()
        circuit_breaker.force_reset()

    def tearDown(self):
        DefensiveExceptionManager.reset_safe_mode()
        circuit_breaker.force_reset()

    def test_swallow_safely_below_threshold(self):
        """swallow_safely threshold'ın altında kaldığı sürece safe mode tetiklenmemeli."""
        err = ValueError("Test error")
        triggered = DefensiveExceptionManager.swallow_safely(err, "test_context", threshold=3)
        self.assertFalse(triggered)
        self.assertFalse(DefensiveExceptionManager.is_system_in_safe_mode())
        self.assertFalse(circuit_breaker.is_circuit_open("BTCUSDT", "UNKNOWN"))

    def test_swallow_safely_triggers_circuit_breaker(self):
        """swallow_safely threshold'a ulaştığında safe mode'a geçmeli ve circuit breaker'ı tetiklemeli."""
        err = ValueError("Test error")
        
        # 1. ve 2. hatalar sessizce yutulmalı
        self.assertFalse(DefensiveExceptionManager.swallow_safely(err, "test_context", threshold=3))
        self.assertFalse(DefensiveExceptionManager.swallow_safely(err, "test_context", threshold=3))
        
        # 3. hata circuit breaker tetiklemeli
        triggered = DefensiveExceptionManager.swallow_safely(err, "test_context", threshold=3)
        self.assertTrue(triggered)
        self.assertTrue(DefensiveExceptionManager.is_system_in_safe_mode())
        
        # Circuit Breaker'ın açık olduğunu doğrula
        self.assertTrue(circuit_breaker.is_circuit_open("BTCUSDT", "UNKNOWN"))

if __name__ == "__main__":
    unittest.main()
