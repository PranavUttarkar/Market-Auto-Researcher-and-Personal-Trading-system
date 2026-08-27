"""
Production crypto sleeve: daily/4h trend following.

Donchian breakout + time-series momentum. Not 5m scalping — that is not
a fight you win against actual HFT. Trailing ATR is the exit.
"""

import logging
import numpy as np

import config
from indicators import atr, adx, donchian, ts_momentum

log = logging.getLogger(__name__)


class Strategy:
    def __init__(self):
        self.last_signal_bar = -999
        self.bar_count = 0

    def analyze(self, candles: list) -> dict | None:
        n_entry = int(getattr(config, "DONCHIAN_ENTRY", 20))
        n_mom = int(getattr(config, "MOMENTUM_LOOKBACK", 60))
        need = max(n_entry, n_mom, 55) + 5
        if len(candles) < need:
            return None

        self.bar_count += 1
        if self.bar_count - self.last_signal_bar < config.SIGNAL_COOLDOWN:
            return None

        closes = np.array([c[4] for c in candles], dtype=float)
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)

        atr_vals = atr(highs, lows, closes, 14)
        adx_vals = adx(highs, lows, closes, 14)
        price = float(closes[-1])
        cur_atr = float(atr_vals[-1])
        cur_adx = float(adx_vals[-1])
        if price <= 0 or cur_atr <= 0:
            return None

        if getattr(config, "VOLATILITY_FILTER_ENABLED", False):
            atr_pct = (cur_atr / price) * 100
            hist = (atr_vals[-50:] / closes[-50:]) * 100
            if np.mean(hist) > 0 and atr_pct < config.MIN_ATR_PCT_RATIO * np.mean(hist):
                return None

        adx_min = float(getattr(config, "ADX_TREND_MIN", 18))
        if cur_adx < adx_min:
            return None

        prior_high = float(np.max(highs[-n_entry - 1 : -1]))
        prior_low = float(np.min(lows[-n_entry - 1 : -1]))
        mom = ts_momentum(closes, n_mom)
        mom_f = ts_momentum(closes, max(10, n_mom // 3))

        side = None
        reasons = []
        if price > prior_high and mom > 0 and mom_f > 0:
            side = "long"
            reasons = [f"Donchian{n_entry} up", f"mom{n_mom}={mom:+.1%}", f"ADX {cur_adx:.0f}"]
        elif price < prior_low and mom < 0 and mom_f < 0:
            side = "short"
            reasons = [f"Donchian{n_entry} dn", f"mom{n_mom}={mom:+.1%}", f"ADX {cur_adx:.0f}"]
        if not side:
            return None

        atr_mult = config.SCORE_ATR_STOP.get(3, config.STOP_LOSS_ATR_MULT)
        rr = float(getattr(config, "TAKE_PROFIT_RR", 20.0))
        if side == "long":
            stop = price - atr_mult * cur_atr
            risk = price - stop
            tp = price + risk * rr
        else:
            stop = price + atr_mult * cur_atr
            risk = stop - price
            tp = price - risk * rr

        self.last_signal_bar = self.bar_count
        log.info(f"SIGNAL {side.upper()} {reasons}")
        return {
            "side": side,
            "entry": price,
            "stop_loss": stop,
            "take_profit": tp,
            "atr": cur_atr,
            "score": 3,
            "reasons": reasons,
            "risk_distance": risk,
        }

    def get_indicators(self, candles: list) -> dict:
        if len(candles) < 60:
            return {}
        closes = np.array([c[4] for c in candles], dtype=float)
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)
        atr_vals = atr(highs, lows, closes, 14)
        adx_vals = adx(highs, lows, closes, 14)
        n = int(getattr(config, "DONCHIAN_ENTRY", 20))
        upper, lower = donchian(highs, lows, n)
        mom = ts_momentum(closes, int(getattr(config, "MOMENTUM_LOOKBACK", 60)))
        return {
            "atr": round(float(atr_vals[-1]), 2),
            "adx": round(float(adx_vals[-1]), 1),
            "donchian_upper": round(float(upper[-1]), 2),
            "donchian_lower": round(float(lower[-1]), 2),
            "ts_momentum": round(mom, 4),
            "regime": "Trend" if adx_vals[-1] >= 18 else "Chop",
            "trend": "UP" if mom > 0 else "DOWN",
        }

    def get_chart_overlays(self, candles: list) -> dict:
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)
        timestamps = [int(c[0] / 1000) for c in candles]
        n = int(getattr(config, "DONCHIAN_ENTRY", 20))
        upper, lower = donchian(highs, lows, n)

        def to_series(values):
            return [
                {"time": t, "value": round(float(v), 2)}
                for t, v in zip(timestamps, values)
                if v > 0
            ]

        return {
            "ema_fast": to_series(upper),
            "ema_slow": to_series(lower),
            "bb_upper": to_series(upper),
            "bb_lower": to_series(lower),
        }
