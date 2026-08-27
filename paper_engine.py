"""
Paper Trading Engine: simulates order execution locally.

Same interface a real engine would use, making the switch trivial.
Tracks positions, balance, PnL, and trade history.
"""

import time
import logging
from dataclasses import dataclass, field

import config

log = logging.getLogger(__name__)


@dataclass
class Position:
    id: str
    symbol: str
    side: str                    # "long" or "short"
    entry_price: float
    size: float                  # In base currency (e.g. BTC)
    stop_loss: float
    take_profit: float
    trailing_stop_dist: float
    trailing_stop: float         # Current trailing stop level
    unrealized_pnl: float = 0.0
    opened_at: float = 0.0      # Unix timestamp
    # ── Conviction & Hedging fields ──
    partial_closed: bool = False       # Whether scale-out has executed
    initial_size: float = 0.0          # Original size before partial close
    risk_distance: float = 0.0         # 1R distance (for partial close trigger)
    score: int = 0                     # Signal score that opened this trade
    realized_partial_pnl: float = 0.0  # PnL banked from partial close (net of fees)
    entry_fee_paid: float = 0.0        # Fee paid on entry (for net PnL at close)
    agent_id: str = ""                 # Strategy agent (for multi-agent fund)
    timeframe: str = ""                # e.g. "5m" (for multi-instrument fund)

    def cost(self) -> float:
        return self.entry_price * self.size


@dataclass
class Trade:
    id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    reason: str                  # "stop_loss", "take_profit", "trailing_stop"
    opened_at: float = 0.0
    closed_at: float = 0.0
    # ── R-tracking (ground truth for strategy evaluation) ──
    score: int = 0               # Signal score that opened this trade
    risk_distance: float = 0.0   # 1R distance in price units
    pnl_in_r: float = 0.0       # Realized PnL in R-units (after slippage)
    agent_id: str = ""           # Strategy agent (for multi-agent fund)


class PaperEngine:
    def __init__(self):
        self.balance = config.INITIAL_BALANCE
        self.positions: list[Position] = []
        self.trades: list[Trade] = []
        self.trade_counter = 0
        self.equity_curve: list[dict] = []
        self.activity_log: list[dict] = []
        log.info(f"Paper engine started | Balance: ${self.balance:,.2f}")

    def _next_id(self) -> str:
        self.trade_counter += 1
        return f"PT-{self.trade_counter:04d}"

    def _log_activity(self, msg: str):
        entry = {"time": time.time(), "msg": msg}
        self.activity_log.append(entry)
        if len(self.activity_log) > 100:
            self.activity_log = self.activity_log[-100:]
        log.info(msg)

    # ── Open Position ───────────────────────────────────────────────────

    def open_position(self, symbol: str, side: str, price: float, size: float,
                      stop_loss: float, take_profit: float, trailing_stop_dist: float,
                      score: int = 0, risk_distance: float = 0.0, agent_id: str = "",
                      timeframe: str = "") -> Position | None:
        # Apply slippage (adverse fill simulation)
        if config.SLIPPAGE_PCT > 0:
            if side == "long":
                price = price * (1 + config.SLIPPAGE_PCT)   # Buy higher
            else:
                price = price * (1 - config.SLIPPAGE_PCT)   # Sell lower

        cost = price * size
        entry_fee = cost * getattr(config, "FEE_PCT", 0.0)
        total_cost = cost + entry_fee
        if total_cost > self.balance:
            self._log_activity(f"SKIP: Insufficient balance for {side} {size:.6f} {symbol}")
            return None

        if cost > self.balance * config.MAX_POSITION_PCT:
            size = (self.balance * config.MAX_POSITION_PCT) / price
            cost = price * size
            entry_fee = cost * getattr(config, "FEE_PCT", 0.0)
            total_cost = cost + entry_fee

        pos = Position(
            id=self._next_id(),
            symbol=symbol,
            side=side,
            entry_price=price,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_dist=trailing_stop_dist,
            trailing_stop=stop_loss,  # Start at initial stop
            opened_at=time.time(),
            initial_size=size,
            risk_distance=risk_distance,
            score=score,
            entry_fee_paid=entry_fee,
            agent_id=agent_id,
            timeframe=timeframe,
        )

        self.balance -= total_cost
        self.positions.append(pos)
        self._log_activity(
            f"OPEN {side.upper()} {pos.id} | score:{score} | "
            f"{size:.6f} {symbol} @ ${price:,.2f} | "
            f"SL: ${stop_loss:,.2f} | TP: ${take_profit:,.2f}"
        )
        return pos

    # ── Close Position ──────────────────────────────────────────────────

    def close_position(self, pos: Position, price: float, reason: str):
        # Apply slippage (adverse fill simulation)
        if config.SLIPPAGE_PCT > 0:
            if pos.side == "long":
                price = price * (1 - config.SLIPPAGE_PCT)   # Sell lower
            else:
                price = price * (1 + config.SLIPPAGE_PCT)   # Buy back higher

        if pos.side == "long":
            gross_pnl = (price - pos.entry_price) * pos.size
        else:
            gross_pnl = (pos.entry_price - price) * pos.size

        # Subtract exchange fees for net PnL
        exit_fee = price * pos.size * getattr(config, "FEE_PCT", 0.0)
        pnl = gross_pnl - exit_fee
        total_pnl = pnl + pos.realized_partial_pnl - pos.entry_fee_paid

        # Compute PnL in R-units (the ground truth for strategy evaluation)
        pnl_in_r = 0.0
        init_size = pos.initial_size if pos.initial_size > 0 else pos.size
        if pos.risk_distance > 0 and init_size > 0:
            pnl_in_r = total_pnl / (pos.risk_distance * init_size)

        self.balance += pos.cost() + pnl

        trade = Trade(
            id=pos.id,
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=price,
            size=init_size,
            pnl=total_pnl,
            pnl_in_r=pnl_in_r,
            score=pos.score,
            risk_distance=pos.risk_distance,
            reason=reason,
            opened_at=pos.opened_at,
            closed_at=time.time(),
            agent_id=pos.agent_id,
        )
        self.trades.append(trade)
        self.positions.remove(pos)

        emoji = "+" if total_pnl >= 0 else ""
        self._log_activity(
            f"CLOSE {pos.side.upper()} {pos.id} | {reason} @ ${price:,.2f} | "
            f"PnL: {emoji}${total_pnl:,.2f}"
        )
        return trade

    # ── Update All Positions (called each tick) ─────────────────────────

    def update_positions(self, price: float | dict[str, float]) -> list[Trade]:
        """Update unrealized PnL, handle partial closes (hedging), check stops.
        price: float for single-symbol, or dict[symbol -> price] for multi-symbol."""
        closed = []
        prices = price if isinstance(price, dict) else {p.symbol: price for p in self.positions}

        for pos in list(self.positions):  # Copy list since we may remove
            p = prices.get(pos.symbol, pos.entry_price)
            # Update unrealized PnL
            if pos.side == "long":
                pos.unrealized_pnl = (p - pos.entry_price) * pos.size
            else:
                pos.unrealized_pnl = (pos.entry_price - p) * pos.size

            # ── Partial Close: Scale-Out Hedge ───────────────────────
            # At 1R profit, close 40% to lock in gains.  Move stop to
            # breakeven so remaining 60% is a "free" trade.
            if (not pos.partial_closed and config.PARTIAL_CLOSE_ENABLED
                    and pos.risk_distance > 0):
                if pos.side == "long":
                    profit_r = (p - pos.entry_price) / pos.risk_distance
                else:
                    profit_r = (pos.entry_price - p) / pos.risk_distance

                if profit_r >= config.PARTIAL_CLOSE_AT_R:
                    close_size = pos.initial_size * config.PARTIAL_CLOSE_PCT
                    if 0 < close_size < pos.size:
                        # Calculate partial PnL (gross - slippage - exit fee)
                        if pos.side == "long":
                            partial_pnl = (p - pos.entry_price) * close_size
                        else:
                            partial_pnl = (pos.entry_price - p) * close_size
                        if config.SLIPPAGE_PCT > 0:
                            partial_pnl -= p * config.SLIPPAGE_PCT * close_size
                        partial_pnl -= p * close_size * getattr(config, "FEE_PCT", 0.0)

                        # Credit balance and reduce position
                        self.balance += pos.entry_price * close_size + partial_pnl
                        pos.realized_partial_pnl += partial_pnl
                        pos.size -= close_size
                        pos.partial_closed = True

                        # Move stop to breakeven (key hedge mechanism)
                        if config.MOVE_STOP_TO_BE:
                            pos.stop_loss = pos.entry_price

                        # Recalculate unrealized on remaining size
                        if pos.side == "long":
                            pos.unrealized_pnl = (p - pos.entry_price) * pos.size
                        else:
                            pos.unrealized_pnl = (pos.entry_price - p) * pos.size

                        self._log_activity(
                            f"HEDGE {pos.side.upper()} {pos.id} | Scale-out "
                            f"{close_size:.6f} @ ${p:,.2f} | "
                            f"Locked +${partial_pnl:,.2f} | Stop → BE"
                        )

            # ── Check Take Profit ────────────────────────────────────
            if pos.side == "long" and p >= pos.take_profit:
                closed.append(self.close_position(pos, pos.take_profit, "take_profit"))
                continue
            elif pos.side == "short" and p <= pos.take_profit:
                closed.append(self.close_position(pos, pos.take_profit, "take_profit"))
                continue

            # ── Update & Check Trailing Stop ─────────────────────────
            if pos.side == "long":
                new_trail = p - pos.trailing_stop_dist
                if new_trail > pos.trailing_stop:
                    pos.trailing_stop = new_trail
                if p <= pos.trailing_stop and pos.trailing_stop > pos.stop_loss:
                    closed.append(self.close_position(pos, pos.trailing_stop, "trailing_stop"))
                    continue
                if p <= pos.stop_loss:
                    closed.append(self.close_position(pos, pos.stop_loss, "stop_loss"))
                    continue
            else:  # short
                new_trail = p + pos.trailing_stop_dist
                if new_trail < pos.trailing_stop:
                    pos.trailing_stop = new_trail
                if p >= pos.trailing_stop and pos.trailing_stop < pos.stop_loss:
                    closed.append(self.close_position(pos, pos.trailing_stop, "trailing_stop"))
                    continue
                if p >= pos.stop_loss:
                    closed.append(self.close_position(pos, pos.stop_loss, "stop_loss"))
                    continue

        # Record equity snapshot
        unrealized = sum(p.unrealized_pnl for p in self.positions)
        position_cost = sum(p.cost() for p in self.positions)
        equity = self.balance + position_cost + unrealized
        self.equity_curve.append({"time": time.time(), "equity": equity})
        if len(self.equity_curve) > 500:
            self.equity_curve = self.equity_curve[-500:]

        return closed

    # ── State for Dashboard ─────────────────────────────────────────────

    def get_state(self) -> dict:
        unrealized = sum(p.unrealized_pnl for p in self.positions)
        realized = sum(t.pnl for t in self.trades)
        position_cost = sum(p.cost() for p in self.positions)
        equity = self.balance + position_cost + unrealized

        wins = [t for t in self.trades if t.pnl > 0]
        win_rate = len(wins) / len(self.trades) * 100 if self.trades else 0

        return {
            "balance": round(self.balance, 2),
            "equity": round(equity, 2),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(realized, 2),
            "total_pnl": round(realized + unrealized, 2),
            "return_pct": round((equity / config.INITIAL_BALANCE - 1) * 100, 3),
            "win_rate": round(win_rate, 1),
            "total_trades": len(self.trades),
            "open_positions": len(self.positions),
            "positions": [
                {
                    "id": p.id,
                    "side": p.side,
                    "symbol": p.symbol,
                    "entry_price": round(p.entry_price, 2),
                    "size": round(p.size, 6),
                    "stop_loss": round(p.stop_loss, 2),
                    "take_profit": round(p.take_profit, 2),
                    "trailing_stop": round(p.trailing_stop, 2),
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "cost": round(p.cost(), 2),
                    "score": p.score,
                    "partial_closed": p.partial_closed,
                    "agent_id": p.agent_id,
                    "timeframe": p.timeframe,
                }
                for p in self.positions
            ],
            "trades": [
                {
                    "id": t.id,
                    "side": t.side,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "size": round(t.size, 6),
                    "pnl": round(t.pnl, 2),
                    "pnl_in_r": round(t.pnl_in_r, 3),
                    "score": t.score,
                    "reason": t.reason,
                    "closed_at": t.closed_at,
                    "agent_id": t.agent_id,
                }
                for t in self.trades[-50:]  # Last 50 trades
            ],
            "activity_log": self.activity_log[-20:],
            "equity_curve": self.equity_curve[-100:],
        }
