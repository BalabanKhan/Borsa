"""
conflict_resolver.py — Sinyal Çelişki Çözücü
31 stratejinin aynı anda çalıştırılmasından doğan çelişki ve logic hatalarını engeller.
"""
import logging
import config

logger = logging.getLogger("quant_bot.conflict_resolver")

class SignalConflictResolver:
    def __init__(self):
        pass

    @staticmethod
    def get_strategy_type(strategy_name):
        """
        Strateji ismine göre strateji tipini belirler:
        - MEAN_REVERSION_DIP: Dip alımı, VWAP Bounce, Mean Reversion
        - TREND_BREAKOUT: Trend takip, Breakout, Squeeze, ORB vb.
        """
        if not strategy_name:
            return "UNKNOWN"
        name_upper = strategy_name.upper()
        # Dip / Ortalama dönüş stratejilerini yakala
        if any(x in name_upper for x in ["DİP", "DIP", "VWAP", "MEAN REVERSION", "MEAN_REV", "TURNAROUND"]):
            return "MEAN_REVERSION_DIP"
        # Trend / Kırılım stratejilerini yakala
        if any(x in name_upper for x in ["TREND", "KIRILIM", "BREAKOUT", "ORB", "SMC OTE", "VOLUME BREAKOUT", "RELATIVE STRENGTH", "OBV", "SQUEEZE", "SFP", "BOS", "BREAK OF STRUCTURE", "DEATH CROSS"]):
            return "TREND_BREAKOUT"
        return "UNKNOWN"

    def resolve_conflicts(self, candidate_signals, active_trades):
        """
        Aday sinyaller arasındaki ve aktif işlemlerle olan çelişkileri çözer.
        Returns: Filtrelenmiş, çelişkisiz sinyal listesi.
        """
        if not candidate_signals:
            return []

        # 1. Aşama: Ticker bazlı aday sinyalleri grupla ve zıt/mükerrer yönlü olanları çöz (Mutual Exclusivity)
        ticker_groups = {}
        for sig in candidate_signals:
            ticker = sig.get('ticker')
            if ticker:
                ticker_groups.setdefault(ticker, []).append(sig)

        resolved_candidates = []
        for ticker, sigs in ticker_groups.items():
            if len(sigs) == 1:
                resolved_candidates.append(sigs[0])
                continue

            # Birden fazla sinyal varsa, yönlerini kontrol et
            long_sigs = [s for s in sigs if s.get('signal') == 'AL']
            short_sigs = [s for s in sigs if s.get('signal') == 'SAT']

            if long_sigs and short_sigs:
                # Zıt sinyaller çelişkisi: En yüksek conviction skoru kazansın
                max_long = max(long_sigs, key=lambda s: s.get('conviction_score', 0))
                max_short = max(short_sigs, key=lambda s: s.get('conviction_score', 0))
                
                score_long = max_long.get('conviction_score', 0)
                score_short = max_short.get('conviction_score', 0)

                if score_long > score_short:
                    logger.info(f"[ConflictResolver] {ticker} zıt sinyal çelişkisi çözüldü: LONG ({max_long.get('strategy')} - Skor: {score_long:.1f}) tercih edildi, SHORT ({max_short.get('strategy')} - Skor: {score_short:.1f}) elendi.")
                    resolved_candidates.append(max_long)
                elif score_short > score_long:
                    logger.info(f"[ConflictResolver] {ticker} zıt sinyal çelişkisi çözüldü: SHORT ({max_short.get('strategy')} - Skor: {score_short:.1f}) tercih edildi, LONG ({max_long.get('strategy')} - Skor: {score_long:.1f}) elendi.")
                    resolved_candidates.append(max_short)
                else:
                    # Skorlar tam eşitse riskten kaçınmak için ikisini de iptal et
                    logger.warning(f"[ConflictResolver] {ticker} zıt sinyal çelişkisi: Skorlar eşit ({score_long:.1f}). Güvenlik nedeniyle iki sinyal de iptal edildi.")
            else:
                # Aynı yönlü birden fazla sinyal varsa, en yüksek conviction olan tek sinyali al
                best_sig = max(sigs, key=lambda s: s.get('conviction_score', 0))
                logger.info(f"[ConflictResolver] {ticker} aynı yönlü mükerrer sinyal çözüldü: En yüksek skorlu {best_sig.get('strategy')} (Skor: {best_sig.get('conviction_score', 0):.1f}) seçildi.")
                resolved_candidates.append(best_sig)

        # 2. Aşama: Aktif işlemlerle olan çelişkileri kontrol et (Ters yön engelleme)
        final_signals = []
        for sig in resolved_candidates:
            ticker = sig.get('ticker')
            sig_type = sig.get('signal')

            has_opposite_active = False
            for active in active_trades:
                if active.get('status') == 'ACTIVE' and active.get('ticker') == ticker:
                    active_signal = active.get('signal')
                    if active_signal != sig_type:
                        has_opposite_active = True
                        logger.warning(f"[ConflictResolver] {ticker} engellendi: Aktif {active_signal} pozisyonu varken ters yönlü yeni {sig_type} ({sig.get('strategy')}) sinyali açılması reddedildi.")
                        break

            if has_opposite_active:
                continue

            final_signals.append(sig)

        return final_signals
