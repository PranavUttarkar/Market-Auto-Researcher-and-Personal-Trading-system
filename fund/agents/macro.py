"""
Macro: oil / trucking / AI-memory / power / gold.
Universe is whatever the desk promoted under those theses.
"""

from typing import Optional

from .ai_base import AIBaseAgent
from .base import Signal


class MacroAgent(AIBaseAgent):
    def __init__(self, ai_client=None, news_search=None, desk=None):
        super().__init__(
            agent_id="macro",
            personality="Macro / thematic",
            focus="Oil, trucking, AI memory, power, gold — desk names",
            ai_client=ai_client,
            news_search=news_search,
            analysis_interval=3600,
        )
        self.desk = desk

    @property
    def system_prompt(self):
        return (
            "You are a macro/thematic agent. Trade only names tied to oil, "
            "autonomous trucking, AI memory, datacenter power, or gold. "
            "JSON: {\"bias\":\"bullish\",\"conviction\":1,\"action\":\"buy\","
            "\"reasoning\":\"...\",\"risk_score\":1,\"stop_pct\":10.0,"
            "\"target_pct\":25.0}"
        )

    def _format_prompt(self, candles, symbol, ind):
        extra = ""
        if self.desk:
            c = self.desk.candidate_for(symbol)
            if c:
                extra = f"theses={c.thesis_ids} MOS={c.mos} {c.note}\n"
            mem = ""
            if getattr(self.desk, "memory", None):
                mem = self.desk.memory.format(symbol + " oil trucking memory power", k=5)
                extra += f"Memories:\n{mem}\n"
        return (
            f"{extra}{symbol} ${ind['price']:.2f} ADX {ind['adx']:.0f} "
            f"RSI {ind['rsi']:.0f}\nMacro stance?"
        )

    def analyze(self, candles, symbol, timeframe) -> Optional[Signal]:
        if self.desk:
            allowed = self.desk.agent_universe().get("macro", [])
            if allowed and symbol not in allowed:
                return None
        return super().analyze(candles, symbol, timeframe)
