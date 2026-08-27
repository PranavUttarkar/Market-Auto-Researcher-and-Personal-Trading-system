"""
Warren: names come from the research desk (DCF MOS + supported theses).
Not a hardcoded mega-cap list. Wide stops; thesis is the hold.
"""

from typing import Optional

from .ai_base import AIBaseAgent
from .base import Signal


class WarrenAgent(AIBaseAgent):
    def __init__(self, ai_client=None, news_search=None, desk=None):
        super().__init__(
            agent_id="warren",
            personality="Value / name identification",
            focus="DCF + supported theses — open universe",
            ai_client=ai_client,
            news_search=news_search,
            analysis_interval=3600,
        )
        self.desk = desk

    @property
    def system_prompt(self):
        return (
            "You are a value researcher. You only trade names the research desk "
            "already promoted. Confirm or skip. JSON only:\n"
            '{"bias":"bullish"|"bearish"|"neutral","conviction":1,'
            '"action":"buy"|"sell"|"hold","reasoning":"...","risk_score":1,'
            '"stop_pct":15.0,"target_pct":40.0}'
        )

    def _format_prompt(self, candles, symbol, ind):
        extra = ""
        if self.desk:
            c = self.desk.candidate_for(symbol)
            if c:
                extra = (
                    f"Desk: source={c.source} MOS={c.mos} theses={c.thesis_ids} "
                    f"elo={c.elo:.0f} note={c.note}\n"
                )
        p = ind["price"]
        return (
            f"{extra}{symbol} ${p:.2f} RSI {ind['rsi']:.0f} ADX {ind['adx']:.0f}\n"
            "Hold for the thesis unless the DCF MOS collapsed. Action?"
        )

    def analyze(self, candles, symbol, timeframe) -> Optional[Signal]:
        mechanical = self._desk_signal(candles, symbol, timeframe)
        if mechanical:
            return mechanical
        return super().analyze(candles, symbol, timeframe)

    def _desk_signal(self, candles, symbol, timeframe) -> Optional[Signal]:
        if not self.desk or "/" in symbol:
            return None
        c = self.desk.candidate_for(symbol)
        if not c:
            return None
        indicators = self.compute_indicators(candles)
        if not indicators:
            return None
        key = self._get_key(symbol, timeframe)
        self.bar_count[key] = self.bar_count.get(key, 0) + 1
        if self.bar_count[key] - self.last_signal_bar.get(key, -999) < 5:
            return None

        mos = c.mos
        qualitative = (mos is None) and bool(c.thesis_ids)
        if not ((mos is not None and mos >= 0.12) or qualitative):
            return None

        price = indicators["price"]
        atr = indicators["atr"]
        stop_pct = 0.18 if qualitative else 0.12
        stop = price * (1 - stop_pct)
        tp = price * 1.50
        risk = price - stop
        if risk <= 0:
            return None
        self.last_signal_bar[key] = self.bar_count[key]
        reason = c.note or f"desk MOS={mos} {c.thesis_ids}"
        return Signal(
            agent_id="warren",
            symbol=symbol,
            timeframe=timeframe,
            side="long",
            entry=price,
            stop_loss=stop,
            take_profit=tp,
            atr=atr,
            score=3 if (mos or 0) >= 0.2 else 2,
            risk_distance=risk,
            reasons=[reason],
        )
