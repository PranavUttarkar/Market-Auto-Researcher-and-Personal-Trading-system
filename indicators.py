"""
Technical indicators: EMA, RSI, Bollinger Bands, ATR.
All functions take numpy arrays and return numpy arrays.
"""

import numpy as np


def ema(prices: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    if len(prices) < period:
        return np.zeros(len(prices))

    result = np.zeros(len(prices))
    multiplier = 2.0 / (period + 1)

    # Seed with SMA
    result[period - 1] = np.mean(prices[:period])

    for i in range(period, len(prices)):
        result[i] = prices[i] * multiplier + result[i - 1] * (1 - multiplier)

    return result


def rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index (Wilder's smoothing)."""
    if len(prices) < period + 1:
        return np.full(len(prices), 50.0)  # Neutral default

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    result = np.full(len(prices), 50.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, len(prices)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def bollinger_bands(prices: np.ndarray, period: int = 20, std_mult: float = 2.0):
    """Bollinger Bands. Returns (upper, middle, lower) arrays."""
    n = len(prices)
    if n < period:
        return np.zeros(n), np.zeros(n), np.zeros(n)

    upper = np.zeros(n)
    middle = np.zeros(n)
    lower = np.zeros(n)

    for i in range(period - 1, n):
        window = prices[i - period + 1 : i + 1]
        mid = np.mean(window)
        std = np.std(window)
        middle[i] = mid
        upper[i] = mid + std_mult * std
        lower[i] = mid - std_mult * std

    return upper, middle, lower


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range."""
    n = len(closes)
    if n < period + 1:
        return np.zeros(n)

    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    result = np.zeros(n)
    result[period] = np.mean(tr[1 : period + 1])

    for i in range(period + 1, n):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period

    return result


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Average Directional Index (Wilder). ADX < 25 = ranging, >= 25 = trending."""
    n = len(closes)
    if n < period + 2:
        return np.zeros(n)

    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        elif down > up and down > 0:
            minus_dm[i] = down

    # Wilder smoothing: first = sum of first N, then recursive
    atr_smooth = np.zeros(n)
    plus_smooth = np.zeros(n)
    minus_smooth = np.zeros(n)
    atr_smooth[period] = np.mean(tr[1 : period + 1])
    plus_smooth[period] = np.sum(plus_dm[1 : period + 1])
    minus_smooth[period] = np.sum(minus_dm[1 : period + 1])
    for i in range(period + 1, n):
        atr_smooth[i] = (atr_smooth[i - 1] * (period - 1) + tr[i]) / period
        plus_smooth[i] = (plus_smooth[i - 1] * (period - 1) + plus_dm[i]) / period
        minus_smooth[i] = (minus_smooth[i - 1] * (period - 1) + minus_dm[i]) / period

    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    for i in range(period, n):
        if atr_smooth[i] > 0:
            plus_di[i] = 100 * plus_smooth[i] / atr_smooth[i]
            minus_di[i] = 100 * minus_smooth[i] / atr_smooth[i]

    dx = np.zeros(n)
    for i in range(period, n):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum

    adx_vals = np.zeros(n)
    adx_vals[period * 2 - 1] = np.mean(dx[period : period * 2])
    for i in range(period * 2, n):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period

    return adx_vals


def z_score(prices: np.ndarray, period: int) -> np.ndarray:
    """Rolling z-score: (price - rolling_mean) / rolling_std. NaN-safe."""
    n = len(prices)
    result = np.zeros(n)
    for i in range(period - 1, n):
        window = prices[i - period + 1 : i + 1]
        mean_val = np.mean(window)
        std_val = np.std(window)
        if std_val > 0:
            result[i] = (prices[i] - mean_val) / std_val
    return result


def sma(prices: np.ndarray, period: int) -> np.ndarray:
    n = len(prices)
    out = np.zeros(n)
    if n < period:
        return out
    csum = np.cumsum(prices)
    out[period - 1] = csum[period - 1] / period
    for i in range(period, n):
        out[i] = (csum[i] - csum[i - period]) / period
    return out


def donchian(highs: np.ndarray, lows: np.ndarray, period: int):
    """Rolling channel. upper[i] = max(highs[i-period+1:i+1]), same for min lows."""
    n = len(highs)
    upper = np.zeros(n)
    lower = np.zeros(n)
    for i in range(period - 1, n):
        upper[i] = np.max(highs[i - period + 1 : i + 1])
        lower[i] = np.min(lows[i - period + 1 : i + 1])
    return upper, lower


def ts_momentum(closes: np.ndarray, lookback: int) -> float:
    """Time-series momentum: sign-ready return over lookback bars."""
    if len(closes) <= lookback or closes[-lookback - 1] <= 0:
        return 0.0
    return float(closes[-1] / closes[-lookback - 1] - 1.0)
