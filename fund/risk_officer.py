"""
Risk Officer: Portfolio-level risk management.
Vetoes trades that would breach limits (drawdown, exposure, concentration).
"""

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RiskCheck:
    approved: bool
    reason: str = ""


class RiskOfficer:
    """
    Central risk control. Checks:
    - Drawdown circuit breaker
    - Net directional exposure
    - Position count limits
    - Per-agent limits
    """

    def __init__(
        self,
        max_drawdown: float = 0.15,
        max_correlated_exposure: float = 0.6,
        max_positions_total: int = 12,
        max_per_agent: int = 2,
        max_per_instrument: int = 2,
    ):
        self.max_drawdown = max_drawdown
        self.max_correlated_exposure = max_correlated_exposure
        self.max_positions_total = max_positions_total
        self.max_per_agent = max_per_agent
        self.max_per_instrument = max_per_instrument
        self.peak_equity: float | None = None

    def check_trade(
        self,
        signal_agent_id: str,
        signal_side: str,
        signal_symbol: str,
        signal_timeframe: str,
        equity: float,
        positions: list,
    ) -> RiskCheck:
        """
        Check if a proposed trade is allowed.
        positions: list of dicts with side, symbol, agent_id, cost
        """
        if equity <= 0:
            return RiskCheck(False, "Zero equity")

        # Track peak for drawdown
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        drawdown = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0
        if drawdown >= self.max_drawdown:
            return RiskCheck(False, f"Circuit breaker: drawdown {drawdown*100:.1f}%")

        # Count by agent and instrument
        agent_positions = [p for p in positions if p.get("agent_id") == signal_agent_id]
        instrument_key = f"{signal_symbol}::{signal_timeframe}"
        instrument_positions = [p for p in positions if p.get("instrument_key") == instrument_key]

        if len(positions) >= self.max_positions_total:
            return RiskCheck(False, "Max total positions")
        if len(agent_positions) >= self.max_per_agent:
            return RiskCheck(False, f"Max positions for agent {signal_agent_id}")
        if len(instrument_positions) >= self.max_per_instrument:
            return RiskCheck(False, f"Max positions for {instrument_key}")

        # Net exposure check
        long_cost = sum(p.get("cost", 0) for p in positions if p.get("side") == "long")
        short_cost = sum(p.get("cost", 0) for p in positions if p.get("side") == "short")
        net_exposure = abs(long_cost - short_cost)
        if net_exposure / equity > self.max_correlated_exposure:
            same_dir = (
                (signal_side == "long" and long_cost > short_cost) or
                (signal_side == "short" and short_cost > long_cost)
            )
            if same_dir:
                return RiskCheck(False, "Max directional exposure")

        return RiskCheck(True, "OK")

    def reset_peak(self, equity: float):
        """Reset peak equity (e.g. after manual intervention)."""
        self.peak_equity = equity
