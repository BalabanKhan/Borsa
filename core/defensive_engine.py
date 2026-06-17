import os
import json
import logging
import tempfile
from typing import Any, Callable, Dict

logger = logging.getLogger("DefensiveEngine")

class DefensiveStateGuard:
    """
    State koruması ve kendini iyileştirme (self-healing) mekanizması.
    Dosyaları atomik yazar (tempfile + os.replace) ve bozulma durumunda yedekten (.bak) geri yükler.
    """

    @staticmethod
    def save_state_atomic(filepath: str, data: Any) -> bool:
        """
        Dosyayı atomik olarak diske kaydeder ve bir yedek (.bak) oluşturur.
        """
        if not filepath:
            raise ValueError("Geçersiz dosya yolu")

        dir_name = os.path.dirname(filepath)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        temp_fd = None
        temp_path = None
        try:
            # 1. Geçici dosya oluştur
            temp_fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", prefix="def_", suffix=".tmp")
            
            # 2. JSON verisini yaz
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            # Dosyanın diske tamamen yazıldığından emin ol (fsync)
            # fdopen zaten kapatıldı ama temp_fd dosya tanımlayıcısını flush etmek veya fsync için manuel kullanabilirdik.
            # os.fdopen ile açılan blok kapandığında flush yapılmış olur.

            # 3. Eğer hedef dosya zaten varsa, onu .bak olarak yedekle
            bak_path = filepath + ".bak"
            if os.path.exists(filepath):
                try:
                    if os.path.exists(bak_path):
                        os.remove(bak_path)
                    os.rename(filepath, bak_path)
                except Exception as e:
                    logger.warning(f"Yedekleme oluşturulamadı: {filepath} -> {bak_path}. Hata: {e}")

            # 4. Geçici dosyayı hedef dosya ile değiştir (Atomik Değiştirme)
            os.replace(temp_path, filepath)
            return True
            
        except Exception as e:
            logger.error(f"Atomik dosya yazma hatası ({filepath}): {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return False

    @staticmethod
    def load_state_safe(filepath: str, default_factory: Callable[[], Any]) -> Any:
        """
        Dosyayı güvenli bir şekilde yükler. Bozulma algılanırsa yedek (.bak) dosyadan yüklemeye çalışır.
        Hem asıl hem yedek bozuksa default_factory çağrılarak varsayılan değer atanır.
        """
        bak_path = filepath + ".bak"

        # 1. Ana dosyadan okumayı dene
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Ana state dosyası bozuk veya okunamıyor ({filepath}): {e}. Yedek dosyadan geri yükleniyor...")
                
                # Kendini İyileştirme (Self-Healing): Ana dosya bozuksa hemen sil
                try:
                    os.remove(filepath)
                except Exception:
                    pass

        # 2. Yedek dosyadan okumayı dene
        if os.path.exists(bak_path):
            try:
                with open(bak_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Yedek sağlamsa, ana dosya olarak diske geri yaz
                DefensiveStateGuard.save_state_atomic(filepath, data)
                logger.info(f"State dosyası yedekten başarıyla kurtarıldı: {filepath}")
                return data
            except (json.JSONDecodeError, IOError) as e:
                logger.critical(f"Yedek state dosyası da bozuk ({bak_path}): {e}.")
                try:
                    os.remove(bak_path)
                except Exception:
                    pass

        # 3. Her şey başarısız olursa varsayılan durum üret ve diske yaz
        default_data = default_factory()
        DefensiveStateGuard.save_state_atomic(filepath, default_data)
        logger.info(f"Yeni varsayılan state oluşturuldu ve kaydedildi: {filepath}")
        return default_data


class DefensiveExceptionManager:
    """
    Sistem genelinde hata yutulmasını (swallowing) engelleyen ve
    ardışık hatalarda sistemi güvenliğe (circuit breaker) alan yönetici.
    """
    _error_counts: Dict[str, int] = {}
    _system_safe_mode: bool = False

    @classmethod
    def log_and_raise(cls, error: Exception, context_message: str) -> None:
        """
        Hatayı detaylıca loglar ve yukarı katmana fırlatır.
        """
        err_msg = f"CRITICAL EXCEPTION | {context_message} | {type(error).__name__}: {error}"
        logger.critical(err_msg, exc_info=True)
        raise error

    @classmethod
    def swallow_safely(cls, error: Exception, context_message: str, threshold: int = 10) -> bool:
        """
        Bir hatayı sessizce geçiştirmek yerine loglar ve sayacını artırır.
        Hata sayısı eşiği (threshold) aşarsa sistemi safe mode'a alır ve True döner (alarm tetiklendi).
        """
        err_key = f"{context_message}_{type(error).__name__}"
        cls._error_counts[err_key] = cls._error_counts.get(err_key, 0) + 1
        
        current_count = cls._error_counts[err_key]
        logger.warning(
            f"SWALLOWED EXCEPTION SAFEGUARD | {context_message} | Count: {current_count}/{threshold} | "
            f"{type(error).__name__}: {error}"
        )

        if current_count >= threshold:
            logger.critical(
                f"SAFETY THRESHOLD EXCEEDED | {context_message} {threshold} kez tetiklendi! "
                f"Sistem güvenli moda (Safe Mode Pause) geçiriliyor."
            )
            cls._system_safe_mode = True
            try:
                import circuit_breaker
                circuit_breaker.force_global_trip(
                    reason=f"{context_message} ({type(error).__name__} x{threshold})"
                )
            except Exception as cb_err:
                logger.error(f"Circuit Breaker tetiklenirken hata oluştu: {cb_err}")
            return True
            
        return False

    @classmethod
    def is_system_in_safe_mode(cls) -> bool:
        return cls._system_safe_mode

    @classmethod
    def reset_safe_mode(cls) -> None:
        cls._system_safe_mode = False
        cls._error_counts.clear()
        logger.info("Defensive System Safe Mode ve hata sayaçları sıfırlandı.")
