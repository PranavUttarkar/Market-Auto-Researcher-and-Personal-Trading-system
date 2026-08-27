"""
AI Hedge Fund Engine
Orchestrates AI agents across crypto, stocks and gold.
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
from ai.client import AIClient
from ai.web_search import MarketNewsSearch
from data.market_data import MarketDataFeed

from . import ai_config as cfg
from .agents import WarrenAgent, QuantAgent, MacroAgent, SatoshiAgent
from .allocator import Allocator
from .risk_officer import RiskOfficer
from research.desk import ResearchDesk

log = logging.getLogger(__name__)


def _apply_ai_fund_config():
    """Override root config for the AI fund paper engine."""
    main_config.INITIAL_BALANCE = cfg.INITIAL_BALANCE
    main_config.MAX_POSITION_PCT = cfg.MAX_POSITION_PCT
    main_config.SLIPPAGE_PCT = cfg.SLIPPAGE_PCT
    main_config.FEE_PCT = cfg.FEE_PCT
    main_config.PARTIAL_CLOSE_ENABLED = False
    main_config.PAPER_TRADING = True
    main_config.EXCHANGE_ID = cfg.EXCHANGE_ID
    main_config.API_KEY = cfg.API_KEY
    main_config.API_SECRET = cfg.API_SECRET


class AIFundEngine:
    """Runs the multi-agent AI hedge fund."""

    def __init__(self, emit_fn=None):
        _apply_ai_fund_config()

        # Crypto exchange (public data only)
        self.crypto_exchange = create_exchange()

        # Unified data feed
        self.data_feed = MarketDataFeed(crypto_exchange=self.crypto_exchange)

        # Paper trading engine
        self.engine = PaperEngine()

        # LLM optional — desk still runs crowd + DCF without a key
        self.ai_client = None
        if cfg.AI_API_KEY:
            self.ai_client = AIClient(
                api_key=cfg.AI_API_KEY,
                base_url=cfg.AI_BASE_URL,
                model=cfg.AI_MODEL,
            )

        self.news_search = None
        tavily_key = getattr(cfg, "TAVILY_API_KEY", "")
        if tavily_key:
            try:
                self.news_search = MarketNewsSearch(
                    api_key=tavily_key,
                    search_interval=getattr(cfg, "NEWS_SEARCH_INTERVAL", 1800),
                )
            except Exception as exc:
                log.warning(f"Tavily init failed (continuing without news): {exc}")

        self.desk = ResearchDesk(
            notebook_path=cfg.NOTEBOOK_PATH,
            ai_client=self.ai_client,
            news_search=self.news_search,
            max_names=cfg.RESEARCH_MAX_NAMES,
            refresh_s=cfg.RESEARCH_REFRESH_S,
        )

        self.agents = {
            "warren":  WarrenAgent(ai_client=self.ai_client,
                                   news_search=self.news_search, desk=self.desk),
            "quant":   QuantAgent(ai_client=self.ai_client,
                                  news_search=self.news_search, desk=self.desk),
            "macro":   MacroAgent(ai_client=self.ai_client,
                                  news_search=self.news_search, desk=self.desk),
            "satoshi": SatoshiAgent(ai_client=self.ai_client,
                                    news_search=self.news_search, desk=self.desk),
        }

        # Allocator & risk
        self.allocator = Allocator(
            initial_weights=cfg.AGENT_WEIGHTS,
            min_weight=cfg.MIN_AGENT_WEIGHT,
            lookback=cfg.ALLOCATION_LOOKBACK_TRADES,
        )
        self.risk_officer = RiskOfficer(
            max_drawdown=cfg.MAX_DRAWDOWN_CIRCUIT_BREAKER,
            max_correlated_exposure=cfg.MAX_CORRELATED_EXPOSURE,
            max_positions_total=cfg.MAX_OPEN_POSITIONS_TOTAL,
            max_per_agent=cfg.MAX_POSITIONS_PER_AGENT,
            max_per_instrument=cfg.MAX_POSITIONS_PER_INSTRUMENT,
        )

        self.emit = emit_fn or (lambda event, data: None)
        self.running = False
        self._thread = None
        self._latest_update: dict = {}
        self.markers: list[dict] = []
        self.trailing_stop_atr = 3.0
        self._tick_count = 0
        self._book: list[dict] = list(cfg.INSTRUMENTS)

    # ── helpers ────────────────────────────────────────────────────

    def _positions_for_risk(self):
        return [
            {"side": p.side, "cost": p.cost(),
             "agent_id": p.agent_id,
             "instrument_key": f"{p.symbol}::{p.timeframe or '15m'}"}
            for p in self.engine.positions
        ]

    def _add_marker(self, ts, side, kind, price, label):
        self.markers.append({
            "time": ts,
            "position": "belowBar" if side == "long" else "aboveBar",
            "color": "#22c55e" if kind == "entry" else (
                "#ef4444" if "stop" in label.lower() else "#3b82f6"),
            "shape": "arrowUp" if side == "long" and kind == "entry" else (
                "arrowDown" if side == "short" and kind == "entry" else "circle"),
            "text": label, "size": 2,
        })
        if len(self.markers) > 200:
            self.markers = self.markers[-200:]

    def _get_equity(self, prices):
        equity = self.engine.balance
        for p in self.engine.positions:
            px = prices.get(p.symbol, p.entry_price)
            if p.side == "long":
                equity += p.entry_price * p.size + (px - p.entry_price) * p.size
            else:
                equity += p.entry_price * p.size + (p.entry_price - px) * p.size
        return equity

    # ── main tick ──────────────────────────────────────────────────

    def tick(self):
        try:
            self._tick_count += 1
            try:
                if self.desk.maybe_refresh(force=self._tick_count == 1):
                    self._book = self.desk.instruments()
                    log.info(f"Book: {[i['symbol']+' '+i['timeframe'] for i in self._book]}")
            except Exception as exc:
                log.warning(f"Desk refresh skipped: {exc}")

            prices: dict[str, float] = {}
            candles_by_key: dict[str, list] = {}
            universe = self.desk.agent_universe()

            for i, inv in enumerate(self._book):
                sym, tf = inv["symbol"], inv["timeframe"]
                if i > 0 and inv.get("asset_class") == "crypto":
                    time.sleep(1.2)
                candles = self.data_feed.fetch_candles(sym, tf, limit=200)
                if candles:
                    candles_by_key[f"{sym}::{tf}"] = candles
                    prices[sym] = float(candles[-1][4])

            if not prices:
                log.warning("No market data this tick")
                return

            # Fill missing prices from positions
            for p in self.engine.positions:
                if p.symbol not in prices:
                    prices[p.symbol] = p.entry_price

            equity = self._get_equity(prices)

            # Update existing positions (SL, TP, trailing)
            closed_trades = self.engine.update_positions(prices)
            for trade in closed_trades:
                if trade.agent_id and trade.agent_id in self.agents:
                    self.allocator.record_trade(trade.agent_id, trade.pnl)
                    self.agents[trade.agent_id].record_pnl(trade.pnl)
                self._add_marker(int(time.time()), trade.side, "exit",
                                 trade.exit_price,
                                 f"{trade.reason} ${trade.pnl:+,.0f}")

            # Run AI agents
            for agent_id, agent in self.agents.items():
                allowed = universe.get(agent_id, [])
                for inv in self._book:
                    sym, tf = inv["symbol"], inv["timeframe"]
                    if allowed and sym not in allowed:
                        continue
                    key = f"{sym}::{tf}"
                    candles = candles_by_key.get(key)
                    if not candles:
                        continue

                    signal = agent.analyze(candles, sym, tf)
                    if not signal:
                        continue

                    # Risk check
                    check = self.risk_officer.check_trade(
                        signal.agent_id, signal.side, signal.symbol,
                        signal.timeframe, equity, self._positions_for_risk(),
                    )
                    if not check.approved:
                        log.debug(f"Risk veto: {signal.agent_id} {signal.symbol}"
                                  f" — {check.reason}")
                        continue

                    # Position sizing
                    risk_frac = self.allocator.get_risk_for_agent(
                        signal.agent_id, cfg.RISK_PER_TRADE)
                    risk_amount = equity * risk_frac
                    if signal.risk_distance <= 0:
                        continue
                    size = risk_amount / signal.risk_distance
                    max_size = (equity * cfg.MAX_POSITION_PCT) / signal.entry
                    size = min(size, max_size)
                    if size * signal.entry < 10:
                        continue

                    trailing = signal.atr * self.trailing_stop_atr
                    pos = self.engine.open_position(
                        symbol=signal.symbol, side=signal.side,
                        price=signal.entry, size=size,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        trailing_stop_dist=trailing,
                        score=signal.score,
                        risk_distance=signal.risk_distance,
                        agent_id=signal.agent_id,
                        timeframe=signal.timeframe,
                    )
                    if pos:
                        ts = int(candles[-1][0] / 1000)
                        self._add_marker(ts, signal.side, "entry",
                                         signal.entry,
                                         f"{signal.agent_id} "
                                         f"{signal.side.upper()} "
                                         f"s:{signal.score}")

            # Build dashboard payload
            self._latest_update = self._build_update(prices, candles_by_key,
                                                      equity)
            state = self._latest_update.get("engine", {})
            log.info(f"Tick {self._tick_count} complete | "
                     f"Equity: ${equity:,.0f} | "
                     f"Positions: {state.get('open_positions', 0)} | "
                     f"Trades: {state.get('total_trades', 0)} | "
                     f"AI calls: {self.ai_client.call_count if self.ai_client else 0}")
            self.emit("update", self._latest_update)

        except Exception as exc:
            log.error(f"AI Fund tick error: {exc}", exc_info=True)
            self.emit("error", {"msg": str(exc)})

    # ── dashboard payload ──────────────────────────────────────────

    def _build_update(self, prices, candles_by_key, equity):
        # Collect per-agent info
        agent_info = {}
        reasoning_feed = []
        for aid, agent in self.agents.items():
            latest = agent.get_latest_analysis()
            agent_info[aid] = {
                "id": aid,
                "personality": agent.personality,
                "focus": agent.focus,
                "bias": latest.get("bias", "neutral"),
                "conviction": latest.get("conviction", 0),
                "reasoning": latest.get("reasoning", "Analysing…"),
                "action": latest.get("action", "hold"),
                "pnl": round(agent.total_pnl, 2),
            }
            reasoning_feed.extend(agent.get_reasoning_log())

        reasoning_feed.sort(key=lambda r: r["time"], reverse=True)

        # Instrument prices
        instruments = []
        for inv in self._book:
            instruments.append({
                "symbol": inv["symbol"],
                "timeframe": inv["timeframe"],
                "asset_class": inv.get("asset_class", ""),
                "price": prices.get(inv["symbol"], 0),
            })

        primary = self._book[0] if self._book else cfg.INSTRUMENTS[0]
        primary_key = f"{primary['symbol']}::{primary['timeframe']}"
        primary_candles = candles_by_key.get(primary_key, [])
        research = self.desk.snapshot()

        return {
            "tick": self._tick_count,
            "timestamp": time.time(),
            "equity": round(equity, 2),
            "instruments": instruments,
            "agents": agent_info,
            "reasoning_feed": reasoning_feed[:30],
            "allocator_weights": self.allocator.get_weights(),
            "engine": self.engine.get_state(),
            "markers": self.markers,
            "ai_calls": self.ai_client.call_count if self.ai_client else 0,
            "ai_errors": self.ai_client.error_count if self.ai_client else 0,
            "news_searches": self.news_search.search_count if self.news_search else 0,
            "research": research,
            "candles": [
                {"time": int(c[0] / 1000), "open": c[1], "high": c[2],
                 "low": c[3], "close": c[4]}
                for c in primary_candles
            ],
            "primary_symbol": primary["symbol"],
        }

    # ── lifecycle ──────────────────────────────────────────────────

    def get_latest_update(self):
        return self._latest_update

    def run(self):
        self.running = True
        log.info(f"AI Fund engine started | {len(cfg.INSTRUMENTS)} instruments | "
                 f"{len(self.agents)} agents | interval {cfg.UPDATE_INTERVAL}s")
        while self.running:
            self.tick()
            time.sleep(cfg.UPDATE_INTERVAL)

    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=10)
