"""
CTA-style trend follower: Donchian breakout + time-series momentum.

This is the crypto (and systematic equity) sleeve. Not 5m mean-reversion.
Entries on 4h/1d; exits are a wide ATR trail, not a tight 2R take-profit.
"""

from __future__ import annotations

import logging
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from indicators import atr, adx, donchian, ts_momentum

from .base import BaseAgent, Signal

log = logging.getLogger(__name__)

DONCHIAN_N = 20
MOM_FAST = 20
MOM_SLOW = 60
ADX_MIN = 18
ATR_STOP = 3.0
TRAIL_MULT = 3.0
COOLDOWN = 3


class TrendFollowAgent(BaseAgent):
    """Turtle-ish channel breakout confirmed by 20/60-bar momentum."""

    def __init__(self, agent_id: str = "trend",
                 personality: str = "Trend follower",
                 focus: str = "Donchian + time-series momentum, 1d/4h"):
        super().__init__(agent_id)
        self.personality = personality
        self.focus = focus
        self._pnl = 0.0
        self._reasoning_log: list[dict] = []
        self._last: dict = {}

    def analyze(self, candles: list, symbol: str, timeframe: str) -> Signal | None:
        need = max(DONCHIAN_N, MOM_SLOW) + 5
        if len(candles) < need:
            return None

        key = self._get_key(symbol, timeframe)
        self.bar_count[key] = self.bar_count.get(key, 0) + 1
        if self.bar_count[key] - self.last_signal_bar.get(key, -999) < COOLDOWN:
            return None

        closes = np.array([c[4] for c in candles], dtype=float)
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)

        atr_v = atr(highs, lows, closes, 14)
        adx_v = adx(highs, lows, closes, 14)
        upper, lower = donchian(highs, lows, DONCHIAN_N)

        price = float(closes[-1])
        cur_atr = float(atr_v[-1])
        cur_adx = float(adx_v[-1])
        if price <= 0 or cur_atr <= 0:
            return None
        if cur_adx < ADX_MIN:
            return None

        # Break the *prior* channel (exclude current bar) — classic turtle.
        prior_high = float(np.max(highs[-DONCHIAN_N - 1 : -1]))
        prior_low = float(np.min(lows[-DONCHIAN_N - 1 : -1]))
        mom_s = ts_momentum(closes, MOM_SLOW)
        mom_f = ts_momentum(closes, MOM_FAST)

        side = None
        reasons = []
        if price > prior_high and mom_s > 0 and mom_f > 0:
            side = "long"
            reasons = [
                f"Donchian{DONCHIAN_N} break up",
                f"TS mom {MOM_SLOW}={mom_s:+.1%}",
                f"ADX {cur_adx:.0f}",
            ]
        elif price < prior_low and mom_s < 0 and mom_f < 0:
            side = "short"
            reasons = [
                f"Donchian{DONCHIAN_N} break down",
                f"TS mom {MOM_SLOW}={mom_s:+.1%}",
                f"ADX {cur_adx:.0f}",
            ]
        if not side:
            return None

        risk = ATR_STOP * cur_atr
        if side == "long":
            stop = price - risk
            # Far TP so the trailing stop is the real exit (CTA).
            tp = price + risk * 20
        else:
            stop = price + risk
            tp = price - risk * 20

        self.last_signal_bar[key] = self.bar_count[key]
        self._last = {
            "bias": "bullish" if side == "long" else "bearish",
            "conviction": 7,
            "action": "buy" if side == "long" else "sell",
            "reasoning": "; ".join(reasons),
        }
        self._reasoning_log.append({
            "time": __import__("time").time(),
            "agent": self.agent_id,
            "text": f"{symbol} {timeframe}: " + "; ".join(reasons),
            "bias": self._last["bias"],
            "conviction": 7,
            "symbol": symbol,
        })
        if len(self._reasoning_log) > 40:
            self._reasoning_log = self._reasoning_log[-40:]
        log.info(f"TREND {side.upper()} {symbol} {timeframe} {reasons}")
        return Signal(
            agent_id=self.agent_id,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            entry=price,
            stop_loss=stop,
            take_profit=tp,
            atr=cur_atr,
            score=3,
            risk_distance=risk,
            reasons=reasons,
        )
