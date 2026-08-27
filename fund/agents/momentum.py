"""
Momentum Agent: EMA + RSI + Bollinger + Volume scoring.
Best in trending markets (ADX >= 25).
"""

import logging
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from indicators import ema, rsi, bollinger_bands, atr, adx

from .base import BaseAgent, Signal

log = logging.getLogger(__name__)

EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
BB_PERIOD = 20
BB_STD = 2.0
MIN_SCORE = 3
SIGNAL_COOLDOWN = 2
ADX_TRENDING = 25
VOL_MIN_ATR_RATIO = 0.5


class MomentumAgent(BaseAgent):
    """Trend-following agent. Only signals when ADX indicates trending regime."""

    def __init__(self):
        super().__init__("momentum")

    def analyze(self, candles: list, symbol: str, timeframe: str) -> Signal | None:
        lookback = max(EMA_SLOW + 5, 55)
        if len(candles) < lookback:
            return None

        key = self._get_key(symbol, timeframe)
        self.bar_count[key] = self.bar_count.get(key, 0) + 1

        if self.bar_count[key] - self.last_signal_bar.get(key, -999) < SIGNAL_COOLDOWN:
            return None

        closes = np.array([c[4] for c in candles], dtype=float)
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)
        volumes = np.array([c[5] for c in candles], dtype=float)

        ema_fast = ema(closes, EMA_FAST)
        ema_slow = ema(closes, EMA_SLOW)
        rsi_vals = rsi(closes, RSI_PERIOD)
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes, BB_PERIOD, BB_STD)
        atr_vals = atr(highs, lows, closes, 14)
        adx_vals = adx(highs, lows, closes, 14)

        price = closes[-1]
        cur_atr = atr_vals[-1]
        cur_adx = adx_vals[-1]
        if cur_atr <= 0 or price <= 0 or cur_adx < ADX_TRENDING:
            return None

        # Volatility filter
        atr_pct = (cur_atr / price) * 100
        atr_pct_hist = (atr_vals[-50:] / closes[-50:]) * 100
        if np.mean(atr_pct_hist) > 0 and atr_pct < VOL_MIN_ATR_RATIO * np.mean(atr_pct_hist):
            return None

        ef, es = ema_fast[-1], ema_slow[-1]
        cur_rsi, prev_rsi = rsi_vals[-1], rsi_vals[-2]
        bb_up, bb_low, bb_m = bb_upper[-1], bb_lower[-1], bb_mid[-1]
        avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
        cur_vol = volumes[-1]

        long_score, long_reasons = 0, []
        if ef > es:
            long_score += 1
            long_reasons.append("EMA uptrend")
        if cur_rsi < RSI_OVERSOLD:
            long_score += 1
            long_reasons.append(f"RSI oversold ({cur_rsi:.0f})")
        elif cur_rsi < 50 and cur_rsi > prev_rsi:
            long_score += 1
            long_reasons.append(f"RSI rising ({cur_rsi:.0f})")
        if bb_low > 0 and price <= bb_low + (bb_m - bb_low) * 0.3:
            long_score += 1
            long_reasons.append("Near lower BB")
        if cur_vol > avg_vol * 1.1:
            long_score += 1
            long_reasons.append("Volume surge")

        short_score, short_reasons = 0, []
        if ef < es:
            short_score += 1
            short_reasons.append("EMA downtrend")
        if cur_rsi > RSI_OVERBOUGHT:
            short_score += 1
            short_reasons.append(f"RSI overbought ({cur_rsi:.0f})")
        elif cur_rsi > 50 and cur_rsi < prev_rsi:
            short_score += 1
            short_reasons.append(f"RSI falling ({cur_rsi:.0f})")
        if bb_up > 0 and price >= bb_up - (bb_up - bb_m) * 0.3:
            short_score += 1
            short_reasons.append("Near upper BB")
        if cur_vol > avg_vol * 1.1:
            short_score += 1
            short_reasons.append("Volume surge")

        atr_mult = 2.0
        rr = 2.0
        if long_score >= MIN_SCORE and long_score > short_score:
            stop_loss = price - atr_mult * cur_atr
            risk = price - stop_loss
            take_profit = price + risk * rr
            self.last_signal_bar[key] = self.bar_count[key]
            return Signal(
                agent_id=self.agent_id,
                symbol=symbol,
                timeframe=timeframe,
                side="long",
                entry=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                atr=cur_atr,
                score=long_score,
                risk_distance=risk,
                reasons=long_reasons,
            )
        if short_score >= MIN_SCORE and short_score > long_score:
            stop_loss = price + atr_mult * cur_atr
            risk = stop_loss - price
            take_profit = price - risk * rr
            self.last_signal_bar[key] = self.bar_count[key]
            return Signal(
                agent_id=self.agent_id,
                symbol=symbol,
                timeframe=timeframe,
                side="short",
                entry=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                atr=cur_atr,
                score=short_score,
                risk_distance=risk,
                reasons=short_reasons,
            )
        return None
