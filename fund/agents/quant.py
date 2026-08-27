"""Quant: Donchian + time-series momentum on the desk universe (1d/4h)."""

from .trend import TrendFollowAgent


class QuantAgent(TrendFollowAgent):
    def __init__(self, ai_client=None, news_search=None, desk=None):
        super().__init__(agent_id="quant")
        self.ai_client = ai_client
        self.news_search = news_search
        self.desk = desk
        self.personality = "Trend / systematic"
        self.focus = "Donchian 20 + 20/60-bar momentum — not 5m"
        self._reasoning_log = []
        self._pnl = 0.0
        self._ai_cache = {"quant": {"bias": "neutral", "conviction": 6,
                                    "reasoning": "Waiting on a channel break.",
                                    "action": "hold"}}

    def get_latest_analysis(self) -> dict:
        return self._ai_cache.get("quant", {})

    def get_reasoning_log(self) -> list:
        return self._reasoning_log[-20:]

    def record_pnl(self, pnl: float):
        self._pnl += pnl

    @property
    def total_pnl(self) -> float:
        return self._pnl

    def analyze(self, candles, symbol, timeframe):
        sig = super().analyze(candles, symbol, timeframe)
        if sig:
            self._ai_cache["quant"] = {
                "bias": "bullish" if sig.side == "long" else "bearish",
                "conviction": 7,
                "reasoning": "; ".join(sig.reasons),
                "action": "buy" if sig.side == "long" else "sell",
            }
            self._reasoning_log.append({
                "time": __import__("time").time(),
                "agent": "quant",
                "text": "; ".join(sig.reasons),
                "bias": self._ai_cache["quant"]["bias"],
                "conviction": 7,
                "symbol": symbol,
            })
        return sig
