"""Data module — multi-asset market data feeds."""
from .market_data import MarketDataFeed, classify_asset

__all__ = ["MarketDataFeed", "classify_asset"]
