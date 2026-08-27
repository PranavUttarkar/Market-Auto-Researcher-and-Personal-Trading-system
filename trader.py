"""
Trader: the main trading loop.

Fetches data, runs strategy, manages positions, emits updates to the dashboard.
"""

import time
import logging
import threading

import config
from exchange import create_exchange, fetch_candles, fetch_price
from paper_engine import PaperEngine
from strategy import Strategy

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, engine: PaperEngine, emit_fn=None):
        """
        engine: PaperEngine (or a real engine with the same interface)
        emit_fn: callable to push updates to the dashboard (SocketIO emit)
        """
        self.exchange = create_exchange()
        self.engine = engine
        self.strategy = Strategy()
        self.emit = emit_fn or (lambda event, data: None)
        self.running = False
        self.markers = []  # Entry/exit markers for the chart
        self._thread = None
        self._latest_update = {  # Cached for REST API fallback
            "price": 0,
            "symbol": config.SYMBOL,
            "candles": [],
            "engine": engine.get_state(),
            "indicators": {},
            "overlays": {},
            "markers": [],
            "timestamp": time.time(),
        }

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
        # Keep last 100 markers
        if len(self.markers) > 100:
            self.markers = self.markers[-100:]

    def tick(self):
        """One trading cycle: fetch data, analyze, manage positions, emit update."""
        try:
            candles = fetch_candles(self.exchange, limit=200)
            if not candles:
                log.warning("No candle data received")
                return

            price = float(candles[-1][4])  # Latest close
            candle_time = int(candles[-1][0] / 1000)  # Unix seconds
            log.info(f"Tick | ${price:,.2f} | {len(candles)} candles | "
                     f"{len(self.engine.positions)} positions")

            # Update positions (check stops/TP)
            closed_trades = self.engine.update_positions(price)

            for trade in closed_trades:
                self._add_marker(
                    candle_time, trade.side, "exit", trade.exit_price,
                    f"{trade.reason} ${trade.pnl:+,.0f}"
                )

            # Run strategy
            signal = self.strategy.analyze(candles)

            if signal and len(self.engine.positions) < config.MAX_OPEN_POSITIONS:
                entry = signal["entry"]
                stop = signal["stop_loss"]
                risk_per_unit = abs(entry - stop)
                score = signal["score"]

                if risk_per_unit > 0:
                    equity = self.engine.get_state()["equity"]

                    # ── Score-based risk: higher conviction → more capital ──
                    # Modified Kelly: score 2 → 2%, score 3 → 3.5%, score 4 → 5%
                    risk_mult = config.SCORE_RISK_MULT.get(score, 1.0)
                    risk_amount = equity * config.RISK_PER_TRADE * risk_mult
                    size = risk_amount / risk_per_unit

                    # ── Exposure-based hedge: reduce directional overweight ──
                    # If already net-long and opening another long, reduce size
                    # (opposite direction = natural hedge, no reduction)
                    long_cost = sum(
                        p.cost() for p in self.engine.positions if p.side == "long"
                    )
                    short_cost = sum(
                        p.cost() for p in self.engine.positions if p.side == "short"
                    )
                    net_exposure = long_cost - short_cost
                    if equity > 0:
                        exposure_ratio = abs(net_exposure) / equity
                        same_direction = (
                            (signal["side"] == "long" and net_exposure > 0) or
                            (signal["side"] == "short" and net_exposure < 0)
                        )
                        if same_direction and exposure_ratio > 0.1:
                            hedge_factor = max(0.5, 1.0 - exposure_ratio)
                            size *= hedge_factor

                    # Cap at max position size
                    max_size = (equity * config.MAX_POSITION_PCT) / entry
                    size = min(size, max_size)

                    if size * entry >= 10:  # Min $10 position
                        trailing_dist = signal["atr"] * config.TRAILING_STOP_ATR
                        risk_distance = signal.get("risk_distance", risk_per_unit)

                        pos = self.engine.open_position(
                            symbol=config.SYMBOL,
                            side=signal["side"],
                            price=entry,
                            size=size,
                            stop_loss=signal["stop_loss"],
                            take_profit=signal["take_profit"],
                            trailing_stop_dist=trailing_dist,
                            score=score,
                            risk_distance=risk_distance,
                        )

                        if pos:
                            self._add_marker(
                                candle_time, signal["side"], "entry", entry,
                                f"{signal['side'].upper()} s:{score} r:{risk_mult:.1f}x"
                            )

            # Emit update to dashboard
            indicators = self.strategy.get_indicators(candles)
            overlays = self.strategy.get_chart_overlays(candles)

            update = {
                "price": price,
                "symbol": config.SYMBOL,
                "candles": [
                    {
                        "time": int(c[0] / 1000),
                        "open": c[1],
                        "high": c[2],
                        "low": c[3],
                        "close": c[4],
                    }
                    for c in candles
                ],
                "engine": self.engine.get_state(),
                "indicators": indicators,
                "overlays": overlays,
                "markers": self.markers,
                "timestamp": time.time(),
            }

            self._latest_update = update
            self.emit("update", update)

        except Exception as e:
            log.error(f"Tick error: {e}", exc_info=True)
            self.emit("error", {"msg": str(e)})

    def get_latest_update(self) -> dict:
        """Return the most recent update (used by REST endpoint)."""
        return self._latest_update

    def run(self):
        """Start the trading loop in the current thread."""
        self.running = True
        log.info(f"Trader started | {config.SYMBOL} | {config.TIMEFRAME} | "
                 f"Interval: {config.UPDATE_INTERVAL}s")

        while self.running:
            self.tick()
            time.sleep(config.UPDATE_INTERVAL)

    def start(self):
        """Start the trading loop in a background thread."""
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        log.info("Trading thread started")

    def stop(self):
        """Stop the trading loop."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=10)
        log.info("Trader stopped")
