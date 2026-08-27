"""
Volatility Agent: ATR breakout — trade expansion after squeeze.
Captures breakouts when volatility expands from a low base.
"""

import logging
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from indicators import atr, bollinger_bands

from .base import BaseAgent, Signal

log = logging.getLogger(__name__)

ATR_PERIOD = 14
BB_PERIOD = 20
ATR_EXPANSION = 1.3   # Current ATR > 1.3x recent low
LOOKBACK_ATR_LOW = 20
SIGNAL_COOLDOWN = 3


class VolatilityAgent(BaseAgent):
    """Volatility breakout agent. Long on upside breakout, short on downside."""

    def __init__(self):
        super().__init__("volatility")

    def analyze(self, candles: list, symbol: str, timeframe: str) -> Signal | None:
        lookback = max(ATR_PERIOD + LOOKBACK_ATR_LOW, 55)
        if len(candles) < lookback:
            return None

        key = self._get_key(symbol, timeframe)
        self.bar_count[key] = self.bar_count.get(key, 0) + 1

        if self.bar_count[key] - self.last_signal_bar.get(key, -999) < SIGNAL_COOLDOWN:
            return None

        closes = np.array([c[4] for c in candles], dtype=float)
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)

        atr_vals = atr(highs, lows, closes, ATR_PERIOD)
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes, BB_PERIOD, 2.0)

        price = closes[-1]
        cur_atr = atr_vals[-1]
        atr_low = np.min(atr_vals[-LOOKBACK_ATR_LOW:])
        bb_up, bb_low = bb_upper[-1], bb_lower[-1]

        if cur_atr <= 0 or price <= 0 or atr_low <= 0:
            return None

        # Must be volatility expansion
        if cur_atr < ATR_EXPANSION * atr_low:
            return None

        # Price must break out of recent range
        recent_high = np.max(highs[-5:])
        recent_low = np.min(lows[-5:])
        range_size = recent_high - recent_low
        if range_size <= 0:
            return None

        atr_mult = 1.5
        rr = 2.0
        signal = None

        # Upside breakout: close above upper BB, breaking recent high
        if price >= bb_up and price >= recent_high - range_size * 0.1:
            stop_loss = price - atr_mult * cur_atr
            risk = price - stop_loss
            take_profit = price + risk * rr
            signal = Signal(
                agent_id=self.agent_id,
                symbol=symbol,
                timeframe=timeframe,
                side="long",
                entry=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                atr=cur_atr,
                score=3,
                risk_distance=risk,
                reasons=["ATR breakout up", f"ATR {cur_atr/atr_low:.2f}x low"],
            )
        # Downside breakout: close below lower BB, breaking recent low
        elif price <= bb_low and price <= recent_low + range_size * 0.1:
            stop_loss = price + atr_mult * cur_atr
            risk = stop_loss - price
            take_profit = price - risk * rr
            signal = Signal(
                agent_id=self.agent_id,
                symbol=symbol,
                timeframe=timeframe,
                side="short",
                entry=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                atr=cur_atr,
                score=3,
                risk_distance=risk,
                reasons=["ATR breakout down", f"ATR {cur_atr/atr_low:.2f}x low"],
            )

        if signal:
            self.last_signal_bar[key] = self.bar_count[key]
        return signal
