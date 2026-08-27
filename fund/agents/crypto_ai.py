"""Satoshi: crypto trend following on 1d/4h. Not a 5m scalp."""

from .trend import TrendFollowAgent


class SatoshiAgent(TrendFollowAgent):
    def __init__(self, ai_client=None, news_search=None, desk=None):
        super().__init__(agent_id="satoshi")
        self.ai_client = ai_client
        self.news_search = news_search
        self.desk = desk
        self.personality = "Crypto trend"
        self.focus = "BTC/ETH 1d+4h Donchian / TS momentum"
        self._reasoning_log = []
        self._pnl = 0.0
        self._ai_cache = {"satoshi": {"bias": "neutral", "conviction": 5,
                                      "reasoning": "Waiting for a daily/4h channel break.",
                                      "action": "hold"}}

    def get_latest_analysis(self) -> dict:
        return self._ai_cache.get("satoshi", {})

    def get_reasoning_log(self) -> list:
        return self._reasoning_log[-20:]

    def record_pnl(self, pnl: float):
        self._pnl += pnl

    @property
    def total_pnl(self) -> float:
        return self._pnl

    def analyze(self, candles, symbol, timeframe):
        if "/" not in symbol:
            return None
        sig = super().analyze(candles, symbol, timeframe)
        if sig:
            self._ai_cache["satoshi"] = {
                "bias": "bullish" if sig.side == "long" else "bearish",
                "conviction": 7,
                "reasoning": "; ".join(sig.reasons),
                "action": "buy" if sig.side == "long" else "sell",
            }
            self._reasoning_log.append({
                "time": __import__("time").time(),
                "agent": "satoshi",
                "text": "; ".join(sig.reasons),
                "bias": self._ai_cache["satoshi"]["bias"],
                "conviction": 7,
                "symbol": symbol,
            })
        return sig
