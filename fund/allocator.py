"""
Capital Allocator: Distributes equity across agents based on performance.
Uses rolling EV-per-trade to weight agents; floors ensure diversification.
"""

import logging
from collections import defaultdict

log = logging.getLogger(__name__)


class Allocator:
    """
    Tracks agent performance and computes allocation weights.
    Better-performing agents get more capital; floor prevents starvation.
    """

    def __init__(self, initial_weights: dict[str, float], min_weight: float = 0.10,
                 lookback: int = 50):
        self.initial_weights = initial_weights
        self.min_weight = min_weight
        self.lookback = lookback
        self.agent_pnl: dict[str, list[float]] = defaultdict(list)
        self.agent_trades: dict[str, int] = defaultdict(int)

    def record_trade(self, agent_id: str, pnl: float):
        """Record a closed trade's PnL for an agent."""
        self.agent_pnl[agent_id].append(pnl)
        self.agent_trades[agent_id] += 1
        # Keep only lookback trades
        if len(self.agent_pnl[agent_id]) > self.lookback:
            self.agent_pnl[agent_id] = self.agent_pnl[agent_id][-self.lookback:]

    def get_weights(self) -> dict[str, float]:
        """
        Compute allocation weights. Uses rolling EV; falls back to
        initial weights when insufficient data.
        """
        ev_by_agent: dict[str, float] = {}
        for agent_id in self.initial_weights:
            pnls = self.agent_pnl[agent_id]
            if len(pnls) >= 5:
                ev_by_agent[agent_id] = sum(pnls) / len(pnls)
            else:
                ev_by_agent[agent_id] = 0.0  # Neutral until we have data

        total_ev = sum(max(0, ev) for ev in ev_by_agent.values())
        if total_ev <= 0:
            return dict(self.initial_weights)

        # Raw weights from EV (only positive EV gets extra)
        raw = {}
        for agent_id, ev in ev_by_agent.items():
            if ev > 0:
                raw[agent_id] = ev / total_ev
            else:
                raw[agent_id] = self.initial_weights[agent_id] * 0.5  # Penalize

        # Apply floor
        for agent_id in raw:
            raw[agent_id] = max(self.min_weight, raw[agent_id])

        # Normalize to sum to 1
        s = sum(raw.values())
        if s > 0:
            return {k: v / s for k, v in raw.items()}
        return dict(self.initial_weights)

    def get_risk_for_agent(self, agent_id: str, base_risk: float) -> float:
        """Return risk amount (fraction of allocated capital) for this agent."""
        weights = self.get_weights()
        return base_risk * weights.get(agent_id, self.min_weight)
