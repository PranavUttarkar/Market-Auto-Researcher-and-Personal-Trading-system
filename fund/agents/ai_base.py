"""
Base class for AI-powered trading agents.
Combines technical indicator analysis with LLM reasoning.
"""

import time
import logging
import numpy as np
from typing import Optional

from .base import BaseAgent, Signal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from indicators import ema, rsi, bollinger_bands, atr, adx

log = logging.getLogger(__name__)


class AIBaseAgent(BaseAgent):
    """AI-powered agent base: runs indicators, calls LLM, emits Signals."""

    COOLDOWN = 2  # minimum bars between signals

    def __init__(self, agent_id: str, personality: str, focus: str,
                 ai_client=None, news_search=None,
                 analysis_interval: int = 300):
        super().__init__(agent_id)
        self.personality = personality
        self.focus = focus
        self.ai_client = ai_client
        self.news_search = news_search          # Tavily MarketNewsSearch
        self.analysis_interval = analysis_interval

        # cached AI results
        self._ai_cache: dict[str, dict] = {}
        self._ai_cache_ts: dict[str, float] = {}
        self._reasoning_log: list[dict] = []
        self._pnl = 0.0

    # ── Subclass hooks ─────────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        raise NotImplementedError

    def _format_prompt(self, candles, symbol, indicators: dict) -> str:
        raise NotImplementedError

    # ── Indicator computation (shared by all AI agents) ────────────

    @staticmethod
    def compute_indicators(candles) -> Optional[dict]:
        if len(candles) < 55:
            return None
        closes = np.array([c[4] for c in candles], dtype=float)
        highs  = np.array([c[2] for c in candles], dtype=float)
        lows   = np.array([c[3] for c in candles], dtype=float)
        volumes = np.array([c[5] for c in candles], dtype=float)

        ema_f = ema(closes, 9)
        ema_s = ema(closes, 21)
        rsi_v = rsi(closes, 14)
        bb_up, bb_mid, bb_lo = bollinger_bands(closes, 20, 2.0)
        atr_v = atr(highs, lows, closes, 14)
        adx_v = adx(highs, lows, closes, 14)

        price = closes[-1]
        cur_atr = atr_v[-1]
        if cur_atr <= 0 or price <= 0:
            return None

        return {
            "price": price,
            "ema_fast": ema_f[-1],
            "ema_slow": ema_s[-1],
            "rsi": rsi_v[-1],
            "bb_upper": bb_up[-1],
            "bb_mid": bb_mid[-1],
            "bb_lower": bb_lo[-1],
            "atr": cur_atr,
            "atr_pct": (cur_atr / price) * 100,
            "adx": adx_v[-1],
            "volume": volumes[-1],
            "avg_volume": float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)),
            "closes_5": [float(c[4]) for c in candles[-5:]],
        }

    # ── AI call (rate-limited & cached) ────────────────────────────

    def _should_call_ai(self, key: str) -> bool:
        return (time.time() - self._ai_cache_ts.get(key, 0)) >= self.analysis_interval

    def _get_news_context(self, symbol: str) -> str:
        """Fetch latest market news for this symbol via Tavily."""
        if not self.news_search:
            return ""
        try:
            news = self.news_search.get_news(symbol)
            return news if news else ""
        except Exception:
            return ""

    def _call_ai(self, candles, symbol, timeframe, indicators) -> Optional[dict]:
        if not self.ai_client:
            return None

        key = self._get_key(symbol, timeframe)
        if not self._should_call_ai(key):
            return self._ai_cache.get(key)

        prompt = self._format_prompt(candles, symbol, indicators)

        # Append real-time news if available
        news = self._get_news_context(symbol)
        if news:
            prompt += f"\n\n--- LATEST MARKET NEWS ---\n{news}\n"

        result = self.ai_client.analyze(self.system_prompt, prompt)

        if result:
            self._ai_cache[key] = result
            self._ai_cache_ts[key] = time.time()
            reasoning = result.get("reasoning", "")
            if reasoning:
                self._reasoning_log.append({
                    "time": time.time(),
                    "agent": self.agent_id,
                    "text": reasoning,
                    "bias": result.get("bias", "neutral"),
                    "conviction": result.get("conviction", 0),
                    "symbol": symbol,
                })
                if len(self._reasoning_log) > 50:
                    self._reasoning_log = self._reasoning_log[-50:]
            log.info(f"[{self.agent_id}] AI → {symbol}: {result.get('bias','?')} "
                     f"conv={result.get('conviction',0)} {result.get('action','?')}")
        return result

    # ── Signal generation ──────────────────────────────────────────

    def analyze(self, candles: list, symbol: str, timeframe: str) -> Optional[Signal]:
        indicators = self.compute_indicators(candles)
        if not indicators:
            return None

        key = self._get_key(symbol, timeframe)
        self.bar_count[key] = self.bar_count.get(key, 0) + 1
        if self.bar_count[key] - self.last_signal_bar.get(key, -999) < self.COOLDOWN:
            return None

        ai = self._call_ai(candles, symbol, timeframe, indicators)
        if not ai:
            return None

        action = ai.get("action", "hold")
        conviction = int(ai.get("conviction", 0))
        if action == "hold" or conviction < 6:
            return None

        price = indicators["price"]
        cur_atr = indicators["atr"]
        side = "long" if action == "buy" else "short"
        stop_pct = float(ai.get("stop_pct", 2.5)) / 100
        target_pct = float(ai.get("target_pct", 5.0)) / 100

        if side == "long":
            stop_loss = price * (1 - stop_pct)
            take_profit = price * (1 + target_pct)
        else:
            stop_loss = price * (1 + stop_pct)
            take_profit = price * (1 - target_pct)

        risk_distance = abs(price - stop_loss)
        score = min(4, max(1, conviction // 3 + 1))
        self.last_signal_bar[key] = self.bar_count[key]

        return Signal(
            agent_id=self.agent_id,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            entry=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=cur_atr,
            score=score,
            risk_distance=risk_distance,
            reasons=[ai.get("reasoning", "AI signal")],
        )

    # ── Dashboard helpers ──────────────────────────────────────────

    def get_reasoning_log(self) -> list[dict]:
        return self._reasoning_log[-20:]

    def get_latest_analysis(self) -> dict:
        if not self._ai_cache:
            return {"bias": "neutral", "conviction": 0,
                    "reasoning": "Waiting for data…"}
        latest_key = max(self._ai_cache_ts, key=self._ai_cache_ts.get, default=None)
        return self._ai_cache.get(latest_key, {})

    def record_pnl(self, pnl: float):
        self._pnl += pnl

    @property
    def total_pnl(self) -> float:
        return self._pnl
