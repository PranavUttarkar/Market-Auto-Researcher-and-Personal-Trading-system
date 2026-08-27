"""Base agent interface — all strategy agents implement this."""

from dataclasses import dataclass
from typing import Any


@dataclass
class Signal:
    """Trade signal produced by an agent."""
    agent_id: str
    symbol: str
    timeframe: str
    side: str                    # "long" | "short"
    entry: float
    stop_loss: float
    take_profit: float
    atr: float
    score: int                   # Conviction 1–4
    risk_distance: float
    reasons: list[str]


class BaseAgent:
    """Base class for strategy agents. Subclasses implement analyze()."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.last_signal_bar: dict[str, int] = {}
        self.bar_count: dict[str, int] = {}

    def _get_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}::{timeframe}"

    def analyze(self, candles: list, symbol: str, timeframe: str) -> Signal | None:
        """
        Analyze candles and return a signal or None.
        Each candle: [timestamp, open, high, low, close, volume]
        """
        raise NotImplementedError

    def reset(self):
        """Reset agent state (e.g. for backtests)."""
        self.last_signal_bar.clear()
        self.bar_count.clear()
