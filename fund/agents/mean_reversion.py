"""
Mean Reversion Agent: Z-score + RSI, TP at BB mid.
Best in ranging markets (ADX < 25).
"""

import logging
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from indicators import rsi, bollinger_bands, atr, adx, z_score

from .base import BaseAgent, Signal

log = logging.getLogger(__name__)

RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
BB_PERIOD = 20
Z_LONG = -2.0
Z_SHORT = 2.0
ADX_RANGING = 25
SIGNAL_COOLDOWN = 2


class MeanReversionAgent(BaseAgent):
    """Mean reversion agent. Only signals when ADX indicates ranging regime."""

    def __init__(self):
        super().__init__("mean_reversion")

    def analyze(self, candles: list, symbol: str, timeframe: str) -> Signal | None:
        lookback = 55
        if len(candles) < lookback:
            return None

        key = self._get_key(symbol, timeframe)
        self.bar_count[key] = self.bar_count.get(key, 0) + 1

        if self.bar_count[key] - self.last_signal_bar.get(key, -999) < SIGNAL_COOLDOWN:
            return None

        closes = np.array([c[4] for c in candles], dtype=float)
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)
        _, bb_mid, _ = bollinger_bands(closes, BB_PERIOD, 2.0)
        atr_vals = atr(highs, lows, closes, 14)
        adx_vals = adx(highs, lows, closes, 14)
        z_scores = z_score(closes, BB_PERIOD)

        price = closes[-1]
        cur_atr = atr_vals[-1]
        cur_adx = adx_vals[-1]
        cur_z = z_scores[-1]
        cur_rsi = rsi(closes, RSI_PERIOD)[-1]
        bb_m = bb_mid[-1]

        if cur_atr <= 0 or price <= 0 or cur_adx >= ADX_RANGING:
            return None

        atr_mult = 2.0
        signal = None

        if cur_z <= Z_LONG and cur_rsi < RSI_OVERSOLD:
            stop_loss = price - atr_mult * cur_atr
            risk = price - stop_loss
            take_profit = bb_m if bb_m > price else price + risk
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
                reasons=[f"MR z={cur_z:.2f}", f"RSI oversold ({cur_rsi:.0f})"],
            )
        elif cur_z >= Z_SHORT and cur_rsi > RSI_OVERBOUGHT:
            stop_loss = price + atr_mult * cur_atr
            risk = stop_loss - price
            take_profit = bb_m if bb_m < price else price - risk
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
                reasons=[f"MR z={cur_z:.2f}", f"RSI overbought ({cur_rsi:.0f})"],
            )

        if signal:
            self.last_signal_bar[key] = self.bar_count[key]
        return signal
