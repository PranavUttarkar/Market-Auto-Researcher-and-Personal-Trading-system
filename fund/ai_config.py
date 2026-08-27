"""
AI fund config. Equity names are *not* listed here — the research desk
promotes them. Crypto is 1d/4h trend-following only.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://chat-api.tamu.ai/api")
AI_MODEL = os.environ.get("AI_MODEL", "protected.gemini-2.5-flash-lite")
AI_ANALYSIS_INTERVAL = 3600

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
NEWS_SEARCH_INTERVAL = 21600

# Seed only. Desk replaces INSTRUMENTS after the first research cycle.
INSTRUMENTS = [
    {"symbol": "BTC/USDT", "timeframe": "1d", "asset_class": "crypto"},
    {"symbol": "ETH/USDT", "timeframe": "1d", "asset_class": "crypto"},
    {"symbol": "BTC/USDT", "timeframe": "4h", "asset_class": "crypto"},
    {"symbol": "GLD", "timeframe": "1d", "asset_class": "gold"},
]

AGENT_WEIGHTS = {
    "warren": 0.30,
    "quant": 0.25,
    "macro": 0.20,
    "satoshi": 0.25,
}

# Overwritten at runtime by ResearchDesk.agent_universe()
AGENT_INSTRUMENTS = {
    "warren": [],
    "quant": ["BTC/USDT", "ETH/USDT"],
    "macro": ["GLD"],
    "satoshi": ["BTC/USDT", "ETH/USDT"],
}

INITIAL_BALANCE = 300.0
MAX_OPEN_POSITIONS_TOTAL = 10
MAX_POSITIONS_PER_AGENT = 3
MAX_POSITIONS_PER_INSTRUMENT = 1

RISK_PER_TRADE = 0.02
MAX_POSITION_PCT = 0.20
MAX_DRAWDOWN_CIRCUIT_BREAKER = 0.12
MAX_CORRELATED_EXPOSURE = 0.55

SLIPPAGE_PCT = 0.0002
FEE_PCT = 0.001

EXCHANGE_ID = "kraken"
API_KEY = ""
API_SECRET = ""

DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5002
UPDATE_INTERVAL = 60.0

MIN_AGENT_WEIGHT = 0.10
ALLOCATION_LOOKBACK_TRADES = 50

RESEARCH_REFRESH_S = 21600
RESEARCH_MAX_NAMES = 16
NOTEBOOK_PATH = str(Path(__file__).resolve().parents[1] / "data" / "research_notebook.json")
