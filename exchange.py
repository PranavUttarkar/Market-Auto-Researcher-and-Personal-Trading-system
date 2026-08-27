"""
Exchange connection: fetches live market data via ccxt.
Works with any ccxt-supported exchange (Binance default).
"""

import time
import logging
import ccxt
import config

log = logging.getLogger(__name__)


def create_exchange() -> ccxt.Exchange:
    """Create exchange instance. No API keys needed for paper trading (public data only)."""
    exchange_class = getattr(ccxt, config.EXCHANGE_ID)

    params = {"enableRateLimit": True}

    if not config.PAPER_TRADING and config.API_KEY:
        params["apiKey"] = config.API_KEY
        params["secret"] = config.API_SECRET

    exchange = exchange_class(params)
    log.info(f"Connected to {config.EXCHANGE_ID} ({'paper' if config.PAPER_TRADING else 'LIVE'})")
    return exchange


def fetch_candles(exchange: ccxt.Exchange, limit: int = 100) -> list:
    """Fetch recent OHLCV candles. Returns list of [timestamp, O, H, L, C, volume]."""
    for attempt in range(3):
        try:
            candles = exchange.fetch_ohlcv(
                config.SYMBOL, config.TIMEFRAME, limit=limit
            )
            return candles
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as e:
            wait = 2 ** attempt
            log.warning(f"Fetch candles failed (attempt {attempt+1}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
        except ccxt.ExchangeError as e:
            log.error(f"Exchange error fetching candles: {e}")
            raise
    log.error("Failed to fetch candles after 3 attempts")
    return []


def fetch_price(exchange: ccxt.Exchange) -> float:
    """Fetch current price for the configured symbol."""
    for attempt in range(3):
        try:
            ticker = exchange.fetch_ticker(config.SYMBOL)
            return float(ticker["last"])
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as e:
            wait = 2 ** attempt
            log.warning(f"Fetch price failed (attempt {attempt+1}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
        except ccxt.ExchangeError as e:
            log.error(f"Exchange error fetching price: {e}")
            raise
    log.error("Failed to fetch price after 3 attempts")
    return 0.0
