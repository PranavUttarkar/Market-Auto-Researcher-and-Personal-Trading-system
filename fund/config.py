"""
AI-Native Hedge Fund — Configuration (Paper Trading).

Multi-agent, multi-instrument fund. All trading is simulated.
"""

# ─── Mode ───────────────────────────────────────────────────────────────
PAPER_TRADING = True  # Always True for this fund module

# ─── Instruments (Symbol, Timeframe) ────────────────────────────────────
# Diversification: multiple pairs and timeframes reduce correlation.
INSTRUMENTS = [
    {"symbol": "BTC/USDT", "timeframe": "1d"},
    {"symbol": "ETH/USDT", "timeframe": "1d"},
    {"symbol": "BTC/USDT", "timeframe": "4h"},
]

# ─── Fund Capital ───────────────────────────────────────────────────────
INITIAL_BALANCE = 300.0
MAX_OPEN_POSITIONS_TOTAL = 12       # Across all agents
MAX_POSITIONS_PER_AGENT = 2         # Per strategy agent
MAX_POSITIONS_PER_INSTRUMENT = 2    # Per symbol/timeframe combo

# ─── Risk ──────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.015              # 1.5% of allocated capital per trade
MAX_POSITION_PCT = 0.25             # Max 25% of equity per position
MAX_DRAWDOWN_CIRCUIT_BREAKER = 0.15 # Pause new trades if down 15% from peak
MAX_CORRELATED_EXPOSURE = 0.6       # Max net directional exposure / equity

# ─── Agent Allocation (initial weights; adapts over time) ─────────────────
# momentum, mean_reversion, volatility — must sum to 1.0
AGENT_WEIGHTS = {
    "momentum": 0.40,
    "mean_reversion": 0.35,
    "volatility": 0.25,
}
MIN_AGENT_WEIGHT = 0.10             # Floor for diversification
ALLOCATION_LOOKBACK_TRADES = 50     # Trades to compute rolling performance

# ─── Exchange (from main config) ─────────────────────────────────────────
EXCHANGE_ID = "kraken"
API_KEY = ""
API_SECRET = ""

# ─── Slippage & Fees ───────────────────────────────────────────────────
SLIPPAGE_PCT = 0.00015
FEE_PCT = 0.0026

# ─── Dashboard ─────────────────────────────────────────────────────────
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5001               # Different port from single-trader
UPDATE_INTERVAL = 60.0
