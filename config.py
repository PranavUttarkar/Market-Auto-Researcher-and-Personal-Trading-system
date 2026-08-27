"""
Configuration for the Crypto Paper Trading Bot.

All settings in one place. See "HOW TO SWITCH TO REAL TRADING" below.
"""

# ─── HOW TO SWITCH TO REAL TRADING ──────────────────────────────────────
# 1. Set PAPER_TRADING = False
# 2. Fill in API_KEY and API_SECRET from your exchange
# 3. Reduce RISK_PER_TRADE to 0.005 (0.5%) to start small
# 4. Increase MIN_SIGNAL_SCORE to 3 for higher quality trades
# 5. Test with minimal amounts first!
# ────────────────────────────────────────────────────────────────────────

# ─── Mode ───────────────────────────────────────────────────────────────
PAPER_TRADING = True

# ─── Exchange ───────────────────────────────────────────────────────────
EXCHANGE_ID = "kraken"          # Reliable from US. Use "binance" outside the US
API_KEY = ""          # Required for real trading only
API_SECRET = ""       # Required for real trading only

# ─── Trading ────────────────────────────────────────────────────────────
SYMBOL = "BTC/USDT"
TIMEFRAME = "1d"              # trend following — not 5m
INITIAL_BALANCE = 300.0       # Starting paper balance (USDT)

# ─── Strategy ───────────────────────────────────────────────────────────
DONCHIAN_ENTRY = 20
MOMENTUM_LOOKBACK = 60
ADX_TREND_MIN = 18
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
BB_PERIOD = 20
BB_STD = 2.0
MIN_SIGNAL_SCORE = 3
SIGNAL_COOLDOWN = 2

# ─── Risk Management ───────────────────────────────────────────────────
RISK_PER_TRADE = 0.02
MAX_OPEN_POSITIONS = 4
STOP_LOSS_ATR_MULT = 3.0      # trend: wide ATR stop
TAKE_PROFIT_RR = 20.0         # trail is the real exit
TRAILING_STOP_ATR = 3.0
MAX_POSITION_PCT = 0.50

# ─── Score-Based Risk Scaling ──────────────────────────────────────────
# FLAT by default (all scores treated equally).  These are HYPOTHESES
# that tighter stops and wider R:R improve EV at higher scores.
# Tighter stops amplify slippage per-R: losses exceed -1R.
# Run `python backtest.py` to validate before enabling non-flat values.
SCORE_RISK_MULT = {2: 1.0, 3: 1.0, 4: 1.0}     # Flat until validated
SCORE_RR = {2: 2.0, 3: 2.0, 4: 2.0}             # Flat until validated
SCORE_ATR_STOP = {2: 3.0, 3: 3.0, 4: 3.0}       # Flat, matches STOP_LOSS_ATR_MULT
# ── Aggressive (ONLY enable after backtest.py passes all checks) ──
# SCORE_RISK_MULT = {2: 1.0, 3: 1.75, 4: 2.5}
# SCORE_RR = {2: 2.0, 3: 2.5, 4: 3.0}
# SCORE_ATR_STOP = {2: 1.5, 3: 1.25, 4: 1.0}

# ─── Volatility & Regime Filters (research-backed) ───────────────────────
# Don't trade in dead markets: when ATR% is below X% of its 50-bar average.
# In sideways/low-vol regimes, buy-and-hold often beats active trading.
VOLATILITY_FILTER_ENABLED = True
MIN_ATR_PCT_RATIO = 0.5        # Only trade when ATR% >= 50% of 50-bar avg
# ADX < 25 = ranging → use mean reversion; ADX >= 25 = trending → use momentum.
REGIME_AWARE_STRATEGY = True
ADX_RANGING_THRESHOLD = 18
Z_SCORE_ENTRY_LONG = -2.0      # Long when price z-score below this (stretched down)
Z_SCORE_ENTRY_SHORT = 2.0      # Short when price z-score above this

# ─── Hedging: Scale-Out (Partial Close) ────────────────────────────────
# At 1R profit, close 40% to lock in gains and move stop to breakeven.
# Remaining 60% rides with trailing stop — worst case is +0.4R (hedged).
PARTIAL_CLOSE_ENABLED = False
PARTIAL_CLOSE_AT_R = 1.0      # Trigger partial close at 1R profit
PARTIAL_CLOSE_PCT = 0.40      # Close 40% of position
MOVE_STOP_TO_BE = True        # Move stop to breakeven after partial

# ─── Slippage & Exchange Fees ──────────────────────────────────────────
# Slippage: 1.5 bps per side, conservative for BTC/USDT.
# Exchange fees: Kraken taker ~0.26%. MUST include for realistic backtests.
SLIPPAGE_PCT = 0.00015        # 0.015% per side
FEE_PCT = 0.0026              # 0.26% per side (Kraken taker); ~0.52% round-trip

# ─── Dashboard ──────────────────────────────────────────────────────────
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5000
UPDATE_INTERVAL = 60.0         # Seconds between trading ticks
