"""
Fund Engine: Orchestrates multi-agent, multi-instrument paper trading.
"""

import time
import logging
import threading

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as main_config
from exchange import create_exchange
from paper_engine import PaperEngine

from . import config as fund_config
from .agents import MomentumAgent, MeanReversionAgent, VolatilityAgent
from .allocator import Allocator
from .risk_officer import RiskOfficer

log = logging.getLogger(__name__)


def _apply_fund_config():
    """Override main config with fund config for PaperEngine and exchange."""
    main_config.INITIAL_BALANCE = fund_config.INITIAL_BALANCE
    main_config.MAX_POSITION_PCT = fund_config.MAX_POSITION_PCT
    main_config.SLIPPAGE_PCT = fund_config.SLIPPAGE_PCT
    main_config.FEE_PCT = fund_config.FEE_PCT
    main_config.PARTIAL_CLOSE_ENABLED = False  # Simpler for fund
    main_config.PAPER_TRADING = True
    main_config.EXCHANGE_ID = fund_config.EXCHANGE_ID
    main_config.API_KEY = getattr(fund_config, "API_KEY", "") or ""
    main_config.API_SECRET = getattr(fund_config, "API_SECRET", "") or ""


def _fetch_candles(exchange, symbol: str, timeframe: str, limit: int = 100) -> list:
    """Fetch OHLCV candles for a symbol/timeframe."""
    for attempt in range(3):
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return candles
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"Fetch {symbol} {timeframe} failed: {e}. Retry in {wait}s...")
            time.sleep(wait)
    return []


class FundEngine:
    """Runs the multi-agent fund in paper trading mode."""

    def __init__(self, emit_fn=None):
        _apply_fund_config()
        self.exchange = create_exchange()
        self.engine = PaperEngine()
        self.emit = emit_fn or (lambda event, data: None)

        self.agents = {
            "momentum": MomentumAgent(),
            "mean_reversion": MeanReversionAgent(),
            "volatility": VolatilityAgent(),
        }
        self.allocator = Allocator(
            initial_weights=fund_config.AGENT_WEIGHTS,
            min_weight=fund_config.MIN_AGENT_WEIGHT,
            lookback=fund_config.ALLOCATION_LOOKBACK_TRADES,
        )
        self.risk_officer = RiskOfficer(
            max_drawdown=fund_config.MAX_DRAWDOWN_CIRCUIT_BREAKER,
            max_correlated_exposure=fund_config.MAX_CORRELATED_EXPOSURE,
            max_positions_total=fund_config.MAX_OPEN_POSITIONS_TOTAL,
            max_per_agent=fund_config.MAX_POSITIONS_PER_AGENT,
            max_per_instrument=fund_config.MAX_POSITIONS_PER_INSTRUMENT,
        )

        self.running = False
        self._thread = None
        self._latest_update = {}
        self.markers = []
        self.trailing_stop_atr = 2.0

    def _positions_for_risk(self) -> list[dict]:
        """Build position list for risk officer."""
        return [
            {
                "side": p.side,
                "cost": p.cost(),
                "agent_id": p.agent_id,
                "instrument_key": f"{p.symbol}::{p.timeframe or '5m'}",
            }
            for p in self.engine.positions
        ]

    def _instrument_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}::{timeframe}"

    def _add_marker(self, candle_time: int, side: str, marker_type: str, price: float, label: str):
        self.markers.append({
            "time": candle_time,
            "position": "belowBar" if side == "long" else "aboveBar",
            "color": "#22c55e" if marker_type == "entry" else (
                "#ef4444" if "stop" in label.lower() else "#3b82f6"
            ),
            "shape": "arrowUp" if side == "long" and marker_type == "entry" else (
                "arrowDown" if side == "short" and marker_type == "entry" else "circle"
            ),
            "text": label,
            "size": 2,
        })
        if len(self.markers) > 150:
            self.markers = self.markers[-150:]

    def _get_equity(self, price_by_symbol: dict[str, float]) -> float:
        """Compute total equity from balance + positions."""
        equity = self.engine.balance
        for p in self.engine.positions:
            price = price_by_symbol.get(p.symbol, p.entry_price)
            if p.side == "long":
                equity += p.entry_price * p.size + (price - p.entry_price) * p.size
            else:
                equity += (p.entry_price - price) * p.size
        return equity

    def tick(self):
        """One fund cycle: fetch all data, run agents, manage positions, emit."""
        try:
            price_by_symbol: dict[str, float] = {}
            candles_by_key: dict[str, list] = {}

            for i, inv in enumerate(fund_config.INSTRUMENTS):
                if i > 0:
                    time.sleep(1.5)  # Throttle to avoid Kraken rate limit
                sym, tf = inv["symbol"], inv["timeframe"]
                candles = _fetch_candles(self.exchange, sym, tf)
                if candles:
                    key = self._instrument_key(sym, tf)
                    candles_by_key[key] = candles
                    price_by_symbol[sym] = float(candles[-1][4])

            if not price_by_symbol:
                log.warning("No candle data received")
                return

            # Use first symbol's price for positions in that symbol
            for p in self.engine.positions:
                if p.symbol not in price_by_symbol:
                    price_by_symbol[p.symbol] = p.entry_price

            equity = self._get_equity(price_by_symbol)

            # Update positions (stops, TP) — use symbol-specific prices
            closed_trades = self.engine.update_positions(price_by_symbol)

            for trade in closed_trades:
                if trade.agent_id:
                    self.allocator.record_trade(trade.agent_id, trade.pnl)
                ts = int(time.time())
                self._add_marker(ts, trade.side, "exit", trade.exit_price,
                                 f"{trade.reason} ${trade.pnl:+,.0f}")

            # Run all agents on their instruments
            for inv in fund_config.INSTRUMENTS:
                sym, tf = inv["symbol"], inv["timeframe"]
                key = self._instrument_key(sym, tf)
                candles = candles_by_key.get(key)
                if not candles:
                    continue

                price = price_by_symbol.get(sym)
                if not price:
                    continue

                for agent in self.agents.values():
                    signal = agent.analyze(candles, sym, tf)
                    if not signal:
                        continue

                    # Risk check
                    pos_for_risk = self._positions_for_risk()
                    check = self.risk_officer.check_trade(
                        signal.agent_id, signal.side, signal.symbol, signal.timeframe,
                        equity, pos_for_risk,
                    )
                    if not check.approved:
                        log.debug(f"Risk veto: {signal.agent_id} {signal.symbol} - {check.reason}")
                        continue

                    # Size from allocator
                    risk_frac = self.allocator.get_risk_for_agent(
                        signal.agent_id, fund_config.RISK_PER_TRADE
                    )
                    risk_amount = equity * risk_frac
                    risk_per_unit = signal.risk_distance
                    if risk_per_unit <= 0:
                        continue
                    size = risk_amount / risk_per_unit

                    max_size = (equity * fund_config.MAX_POSITION_PCT) / signal.entry
                    size = min(size, max_size)

                    if size * signal.entry < 10:
                        continue

                    trailing_dist = signal.atr * self.trailing_stop_atr
                    pos = self.engine.open_position(
                        symbol=signal.symbol,
                        side=signal.side,
                        price=signal.entry,
                        size=size,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        trailing_stop_dist=trailing_dist,
                        score=signal.score,
                        risk_distance=signal.risk_distance,
                        agent_id=signal.agent_id,
                        timeframe=signal.timeframe,
                    )
                    if pos:
                        ts = int(candles[-1][0] / 1000)
                        self._add_marker(ts, signal.side, "entry", signal.entry,
                                         f"{signal.agent_id} {signal.side.upper()} s:{signal.score}")

            # Build update — use primary instrument for chart
            primary = fund_config.INSTRUMENTS[0]
            primary_key = self._instrument_key(primary["symbol"], primary["timeframe"])
            primary_candles = candles_by_key.get(primary_key, [])

            update = {
                "price": price_by_symbol.get(primary["symbol"], 0),
                "symbol": primary["symbol"],
                "timeframe": primary["timeframe"],
                "instruments": [
                    {"symbol": inv["symbol"], "timeframe": inv["timeframe"],
                     "price": price_by_symbol.get(inv["symbol"], 0)}
                    for inv in fund_config.INSTRUMENTS
                ],
                "candles": [
                    {"time": int(c[0]/1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4]}
                    for c in primary_candles
                ],
                "engine": self.engine.get_state(),
                "allocator_weights": self.allocator.get_weights(),
                "markers": self.markers,
                "timestamp": time.time(),
            }

            self._latest_update = update
            self.emit("update", update)

        except Exception as e:
            log.error(f"Fund tick error: {e}", exc_info=True)
            self.emit("error", {"msg": str(e)})

    def get_latest_update(self) -> dict:
        return self._latest_update

    def run(self):
        self.running = True
        log.info(f"Fund engine started | {len(fund_config.INSTRUMENTS)} instruments | "
                 f"Interval: {fund_config.UPDATE_INTERVAL}s")
        while self.running:
            self.tick()
            time.sleep(fund_config.UPDATE_INTERVAL)

    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=10)
