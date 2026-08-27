"""
Multi-asset data feed: Crypto (ccxt), Stocks & Gold (yfinance).
Returns normalised OHLCV candles: [timestamp_ms, open, high, low, close, volume].
"""

import time
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Asset classification ──────────────────────────────────────────────

CRYPTO_PAIRS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"}
GOLD_SYMBOLS = {"GLD", "IAU", "XAUUSD", "GC=F"}


def classify_asset(symbol: str) -> str:
    if symbol in CRYPTO_PAIRS or "/" in symbol:
        return "crypto"
    if symbol in GOLD_SYMBOLS:
        return "gold"
    return "stock"


# ── Unified data feed ─────────────────────────────────────────────────

class MarketDataFeed:
    """Fetch candles for any asset; returns ccxt-style list."""

    def __init__(self, crypto_exchange=None):
        self.exchange = crypto_exchange
        self._cache: dict[str, list] = {}
        self._cache_ts: dict[str, float] = {}
        self._cache_ttl = 90

    def fetch_candles(self, symbol: str, timeframe: str = "1d",
                      limit: int = 200) -> list:
        key = f"{symbol}:{timeframe}"
        now = time.time()
        ttl = 180 if timeframe in ("1d", "1w", "4h") else 25
        if key in self._cache and (now - self._cache_ts.get(key, 0)) < ttl:
            return self._cache[key]

        asset = classify_asset(symbol)
        candles: list = []
        req_tf = timeframe
        if asset != "crypto" and timeframe in ("4h", "1h", "15m", "5m"):
            req_tf = "1d"

        try:
            if asset == "crypto":
                candles = self._fetch_crypto(symbol, timeframe, limit)
            else:
                candles = self._fetch_yfinance(symbol, req_tf, limit)
        except Exception as exc:
            log.warning(f"Data fetch failed for {symbol} {timeframe}: {exc}")

        if not candles and key in self._cache:
            return self._cache[key]          # stale cache beats no data

        if candles:
            self._cache[key] = candles
            self._cache_ts[key] = now

        return candles

    def fetch_price(self, symbol: str) -> float:
        candles = self.fetch_candles(symbol, "1d", limit=5)
        if candles:
            return float(candles[-1][4])
        return 0.0

    # ── Private fetchers ──────────────────────────────────────────

    def _fetch_crypto(self, symbol: str, timeframe: str, limit: int) -> list:
        if not self.exchange:
            return []
        for attempt in range(3):
            try:
                return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except Exception as exc:
                wait = 2 ** attempt
                log.warning(f"Crypto fetch {symbol} attempt {attempt+1}: {exc}")
                time.sleep(wait)
        return []

    def _fetch_yfinance(self, symbol: str, timeframe: str, limit: int) -> list:
        import yfinance as yf

        tf_map = {
            "1m":  ("1m",  "1d"),
            "5m":  ("5m",  "5d"),
            "15m": ("15m", "5d"),
            "30m": ("30m", "5d"),
            "1h":  ("1h",  "3mo"),
            "4h":  ("1h",  "6mo"),
            "1d":  ("1d",  "2y"),
            "1w":  ("1wk", "5y"),
        }
        interval, period = tf_map.get(timeframe, ("1d", "2y"))

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            # Fallback to daily if intraday unavailable
            if interval != "1d":
                log.info(f"{symbol} intraday empty, falling back to 1d")
                df = ticker.history(period="3mo", interval="1d")
            if df.empty:
                return []

        candles = []
        for idx, row in df.iterrows():
            candles.append([
                int(idx.timestamp() * 1000),
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                float(row.get("Volume", 0)),
            ])
        return candles[-limit:]
