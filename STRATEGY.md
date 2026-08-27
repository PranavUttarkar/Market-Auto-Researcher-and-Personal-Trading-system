# Crypto Paper Trading Bot — Strategy & Architecture

## Realistic Expectations

**This is directional speculation, not hedging.** Real hedging requires offsetting
positions (e.g., spot + futures). This bot takes long or short positions on a single
asset based on technical signals.

**Most retail algo traders do not beat buy-and-hold.** Technical edge, if it exists,
is often small and regime-dependent. Costs (slippage ~0.03%, exchange fees ~0.52%
round-trip) consume much of the edge, especially on shorter timeframes.

**Expect small returns, if any.** Do not trade real money until backtests show
positive EV after all costs, and only with capital you can afford to lose.

---

## How to Run

```
pip install -r requirements.txt
python main.py
```

Open **http://127.0.0.1:5000** in your browser.

That's it. No API keys needed for paper trading. The bot fetches live market data
from Kraken's public API and simulates trades locally.

---

## Project Structure

```
crypto-trader/
  main.py           Entry point — starts trader + dashboard server
  config.py         All settings in one place
  indicators.py     Technical indicators (EMA, RSI, Bollinger Bands, ATR)
  exchange.py       Exchange connection via ccxt (market data fetcher)
  paper_engine.py   Paper trading engine (simulates order execution)
  strategy.py       Trading strategy (signal generation)
  trader.py         Main loop (ties strategy, engine, and dashboard together)
  backtest.py       Backtest + Monte Carlo validation (run before enabling score scaling)
  templates/
    dashboard.html  Real-time web dashboard
  static/
    lightweight-charts.js  Charting library (TradingView)
```

---

## The Trading Strategy

### Philosophy

The strategy is **regime-aware** and combines **trend following** with **mean reversion**
based on market conditions (research: Bitcoin 2020–2025, Bollinger mean reversion
outperforms momentum in sideways markets).

- **Ranging market** (ADX < 25): Pure mean reversion — z-score + RSI, TP at BB mid.
- **Trending market** (ADX ≥ 25): Momentum scoring — EMA + RSI + BB + volume.
- **Volatility filter**: Don't trade when ATR% is below 50% of its 50-bar average.
  In dead markets, buy-and-hold often beats active trading.

### The Four Signals

Each signal contributes **1 point** to a score. A trade fires when the
score reaches the minimum threshold (default: 2 for paper, 3 for real).

#### 1. Trend Direction — EMA Crossover (9/21)

- **What:** Compares the 9-period Exponential Moving Average to the 21-period EMA
- **Long signal:** Fast EMA (9) is above Slow EMA (21) → uptrend confirmed
- **Short signal:** Fast EMA (9) is below Slow EMA (21) → downtrend confirmed
- **Why it works:** EMA crossovers are one of the most battle-tested trend
  indicators. The 9/21 combination is fast enough to catch momentum shifts
  while filtering out noise

#### 2. Momentum — RSI (14-period)

- **What:** Relative Strength Index measures the speed and magnitude of price changes
- **Long signal:** RSI is below 35 (oversold) OR RSI is below 50 and rising
- **Short signal:** RSI is above 65 (overbought) OR RSI is above 50 and falling
- **Why it works:** RSI catches momentum exhaustion. When RSI hits oversold in
  an uptrend, it's a high-probability dip buy. The "rising/falling" check
  catches momentum shifts before they reach extreme levels

#### 3. Volatility / Mean Reversion — Bollinger Bands (20-period, 2 std)

- **What:** Bollinger Bands plot a moving average with upper/lower bands at 2
  standard deviations
- **Long signal:** Price is in the bottom 30% of the lower band zone
  (near the lower band → price is stretched, likely to snap back)
- **Short signal:** Price is in the top 30% of the upper band zone
  (near the upper band → price is overextended)
- **Why it works:** Prices tend to revert to the mean. Entering near the
  bands gives excellent risk/reward because you're buying low or selling high
  relative to recent volatility

#### 4. Volume Confirmation

- **What:** Compares current candle volume to the 20-period average volume
- **Signal (both sides):** Current volume is > 110% of average volume
- **Why it works:** Volume confirms conviction. A move on high volume is
  more likely to follow through than a move on thin volume. This filters
  out low-conviction noise

### Signal Scoring

```
LONG example:
  EMA uptrend         → +1
  RSI oversold (32)   → +1
  Near lower BB       → +1
  Volume surge        → +1
  ────────────────────────
  Score: 4 (>= 2 threshold) → OPEN LONG

SHORT example:
  EMA downtrend       → +1
  RSI overbought (71) → +1
  Near upper BB       → +1
  Volume normal       → +0
  ────────────────────────
  Score: 3 (>= 2 threshold) → OPEN SHORT
```

If both long and short scores meet the threshold, the **higher score wins**.
If they're equal, no trade is taken (conflicting signals = stay out).

### Cooldown

After a signal fires, the strategy waits at least `SIGNAL_COOLDOWN` ticks
(default: 2) before generating another signal. This prevents rapid-fire
entries on the same setup.

### Volatility Filter (config: `VOLATILITY_FILTER_ENABLED`, `MIN_ATR_PCT_RATIO`)

When enabled, the strategy does **not open new positions** when:
```
ATR% (current) < MIN_ATR_PCT_RATIO × ATR% (50-bar average)
```
Example: With `MIN_ATR_PCT_RATIO = 0.5`, trading is paused when current
volatility is below half of its recent average. This avoids churning in
dead markets where buy-and-hold outperforms.

### Regime Detection (ADX, config: `REGIME_AWARE_STRATEGY`, `ADX_RANGING_THRESHOLD`)

- **ADX < 25** (ranging): Use **mean reversion** — long when z-score ≤ -2 and
  RSI oversold; short when z-score ≥ 2 and RSI overbought. Take profit at BB mid.
- **ADX ≥ 25** (trending): Use **momentum scoring** — original EMA + RSI + BB + volume logic.

### Mean Reversion Entries (z-score + RSI)

- **Long**: `z_score ≤ Z_SCORE_ENTRY_LONG` (-2) AND `RSI < RSI_OVERSOLD` (35)
- **Short**: `z_score ≥ Z_SCORE_ENTRY_SHORT` (2) AND `RSI > RSI_OVERBOUGHT` (65)
- **TP**: BB mid-band (natural mean-reversion target)

---

## Risk Management

Every trade has **five layers of protection**. No exceptions.

### 1. Stop Loss (ATR-based)

- **Distance:** 1.5 × ATR (14-period Average True Range) by default
- **Long:** Stop = Entry Price - 1.5 × ATR
- **Short:** Stop = Entry Price + 1.5 × ATR
- **Why ATR:** Adapts to current volatility automatically
- **Critical:** With slippage, actual losses **exceed -1R**:

```
loss_R ≈ -(1 + 2 × price × slippage / risk_distance)

BTC $100K, 0.015% slippage, 1.5× ATR ($105) stop:
  Actual loss = -1.29R (not -1R)

With tighter 1.0× ATR ($70) stop:
  Actual loss = -1.43R  ← 11% worse per R
```

Tighter stops amplify slippage damage because the fixed dollar slippage
cost is a larger fraction of the smaller risk distance. Whether tighter
stops are net positive depends on whether win rate improves enough to
compensate — this is an **empirical question**, not an analytical one.

### 2. Take Profit (2:1 Reward-to-Risk)

- **Distance:** 2 × the risk distance
- **Slippage-adjusted actual win:** ≈ +1.71R (not +2R)
- **Effective R:R after slippage:** ~1.33:1 (breakeven win rate = 43%)

### 3. Partial Close — Scale-Out Hedge

- **Trigger:** When position reaches 1R profit
- **Action:** Close 40% of position, move stop to breakeven
- **Effect:** Locks in profit on the partial. Remaining 60% has zero
  downside (worst case = breakeven + the locked partial profit)

### 4. Trailing Stop (ATR-based)

- **Distance:** 2 × ATR from the current price
- **How it works:** Ratchets up (longs) or down (shorts), never backward
- **Why:** Lets winners run while protecting accumulated gains

### 5. Slippage Simulation

- **Rate:** 0.015% per side (1.5 bps), applied on both entry and exit
- **Why it matters:** On 1-minute candles where ATR ≈ $70, $30 round-trip
  slippage is 14–29% of the reward/risk. Ignoring this produces fantasy
  results. Every trade records its realized PnL in R-units (after slippage)
  for honest performance tracking

### Position Sizing

- **Risk per trade:** 2% of equity (equal for all scores by default)
- **Calculation:** `size = (equity × 0.02) / risk_per_unit`
- **Max position:** Capped at 50% of balance per trade
- **Score scaling:** **Disabled by default.** The infra exists in `config.py`
  (`SCORE_RISK_MULT`, `SCORE_RR`, `SCORE_ATR_STOP`) but all values are flat.
  Run `python backtest.py` to validate before enabling non-flat values.
  See "Expected Value: Measure, Don't Assume" below.

### Exposure-Aware Hedging

- **What:** When net directional exposure is >10% of equity and a new signal
  fires in the same direction, position size is reduced
- **Formula:** `hedge_factor = max(0.5, 1.0 - exposure_ratio)`
- **Opposite direction:** No reduction — opposite trades ARE the hedge

### Over-Trading Protection

- **Max 4 concurrent positions**
- **Signal cooldown** — minimum 2 ticks between new signals
- **Score threshold** — requires multiple indicators to agree
- **Exposure throttle** — reduces size when directionally overweight

---

## How a Trade Flows

```
1. TICK (every 2.5 seconds)
   │
   ├── Fetch 100 candles from exchange (Kraken)
   │
   ├── Update all open positions
   │   ├── Recalculate unrealized PnL
   │   ├── Check: partial close trigger (1R profit)? → HEDGE (scale out 40%)
   │   ├── Check: hit take profit? → CLOSE (take_profit)
   │   ├── Check: trailing stop moved? → Update trail level
   │   ├── Check: hit trailing stop? → CLOSE (trailing_stop)
   │   └── Check: hit hard stop loss? → CLOSE (stop_loss)
   │
   ├── Run strategy on candle data
   │   ├── Compute indicators (EMA, RSI, BB, ATR, Volume)
   │   ├── Score long signals (0-4)
   │   ├── Score short signals (0-4)
   │   └── If score >= threshold → generate signal
   │
   ├── If signal AND positions < max (4)
   │   ├── Calculate position size (risk-based, exposure-adjusted)
   │   ├── Set stop loss (ATR-based)
   │   ├── Set take profit (R:R-based)
   │   ├── Set trailing stop distance (2 × ATR)
   │   ├── Apply slippage to entry fill
   │   └── OPEN position (with R-tracking metadata)
   │
   └── Emit update to dashboard
       ├── Current price + candles
       ├── Indicator values + chart overlays
       ├── All positions + trade history
       └── Entry/exit markers for chart
```

---

## Expected Value: Measure, Don't Assume

### Why Analytical EV Estimates Are Dangerous

Theoretical EV requires knowing win rates by score level. But win rates
depend on market regime, indicator interactions at this specific timeframe,
and microstructure effects. **We cannot assume them.**

Worse: slippage makes every "-1R" loss actually exceed -1R, and the damage
scales inversely with stop distance:

```
Actual loss at stop (long):
  entry slipped up:   price × (1 + slip)
  exit slipped down:  stop × (1 - slip)

  loss_R ≈ -(1 + 2 × price × slip / risk_distance)

  1.5× ATR stop ($105):  loss_R = -(1 + 30/105) = -1.29R
  1.25× ATR stop ($87):  loss_R = -(1 + 30/87)  = -1.34R
  1.0× ATR stop ($70):   loss_R = -(1 + 30/70)  = -1.43R
```

Tighter stops amplify slippage per-R by up to 11%. A tighter stop + higher
R:R **might** improve net EV if the win rate increases enough to compensate,
or it might **destroy** it if it doesn't. You cannot infer this from rules
alone. You must measure realized EV in R after slippage by score bucket.

### What Is Valid Without Measurement

These structural improvements hold regardless of score-level win rates:

- **Slippage simulation** — makes paper trading honest, not optimistic
- **Partial close (scale-out hedge)** — reduces variance, locks in profit
- **Exposure-aware sizing** — prevents directional overconcentration
- **R-tracking on every trade** — enables the validation below

### What Requires Measurement

Score-dependent parameters are **hypotheses, not facts**:

- Does score 3 actually win more often than score 2 after slippage?
- Does a tighter stop produce better R-adjusted returns, or does slippage
  amplification destroy the edge?
- Does a wider R:R improve EV, or just reduce win rate?
- Is EV even positive at all on 1-minute candles with slippage?

### Validation Protocol

Score scaling is **disabled by default** (`config.py` sets all scores equal).

```
python backtest.py                # 7-day backtest + Monte Carlo (includes fees)
python backtest.py --days 14      # Longer lookback
python backtest.py --mc 10000     # More Monte Carlo samples
python backtest.py --holdout 0.2   # Out-of-sample validation (last 20% held back)
```

Backtest includes exchange fees (config `FEE_PCT`) for realistic results.

The backtester:
1. Fetches historical candles and replays them through the strategy
2. Records every trade's realized PnL in R-units (after slippage)
3. Buckets results by signal score (2, 3, 4)
4. Runs both flat and aggressive configs on the same data
5. Runs Monte Carlo (5000 resamples) to estimate drawdown distributions
6. Checks whether score scaling passes all safety criteria

**Only enable score scaling if ALL of these hold:**

| Criterion | Threshold | Why |
|-----------|-----------|-----|
| EV monotonically increases with score | score 2 < score 3 < score 4 | Higher scores must actually be better |
| Aggressive outperforms flat on return | agg_return > flat_return | Scaling must help, not hurt |
| P95 max drawdown | < 30% | Tail risk must be bounded |
| Probability of ruin (equity < 50%) | < 1% | Must not blow up |

If any condition fails: **keep flat config. Do not scale by score.**

If flat config itself has negative EV: the base strategy may not be
profitable after slippage on 1-minute candles. Consider wider timeframes
(5m, 15m) where ATR is proportionally larger and slippage is a smaller
fraction of each R.

### Aggressive Config (Disabled by Default)

If `backtest.py` passes all checks, uncomment in `config.py`:

```python
SCORE_RISK_MULT = {2: 1.0, 3: 1.75, 4: 2.5}   # Risk multiplier
SCORE_RR = {2: 2.0, 3: 2.5, 4: 3.0}            # R:R ratio
SCORE_ATR_STOP = {2: 1.5, 3: 1.25, 4: 1.0}     # Stop tightness
```

**Re-validate monthly.** Market regimes change. What passed last month
may fail this month.

---

## Switching to Real Money

**Prerequisites:**
1. Run `python backtest.py --days 14` and verify positive EV
2. If flat EV is negative, do NOT trade real money on this timeframe

Edit `config.py`:

```python
# 1. Flip the switch
PAPER_TRADING = False

# 2. Add your exchange credentials
API_KEY = "your-api-key"
API_SECRET = "your-api-secret"

# 3. Start conservative
RISK_PER_TRADE = 0.01         # 1% instead of 2%

# 4. Require stronger signals
MIN_SIGNAL_SCORE = 3          # 3 instead of 2

# 5. Keep score scaling FLAT (do not scale until backtest validates)
# SCORE_RISK_MULT, SCORE_RR, SCORE_ATR_STOP — leave at defaults

# 6. Increase slippage estimate for safety
SLIPPAGE_PCT = 0.0003         # 0.03% per side (conservative)

# 7. Change exchange if needed
EXCHANGE_ID = "kraken"        # or "binance", "coinbase", etc.
```

The `PaperEngine` and a real exchange engine share the same interface,
so the strategy and trader code stays identical.

**Start with the minimum possible amount and monitor closely.**

---

## Dashboard

The web dashboard at `http://127.0.0.1:5000` shows:

- **Live price** — updated every 2.5 seconds from the exchange
- **Candlestick chart** — with EMA lines (blue/purple) and Bollinger Bands (yellow)
- **Entry/exit markers** — green arrows for entries, red/blue circles for exits
- **Stats cards** — balance, equity, unrealized PnL, realized PnL, return %, win rate
- **Open positions** — with entry price, stop loss, take profit, trailing stop, live PnL
- **Trade history** — completed trades with entry/exit prices, PnL, and exit reason

Data flows via both REST polling (`/api/state` every 3s) and WebSocket for
low-latency updates.

---

## Technical Indicators Reference

| Indicator | Period | Purpose |
|---|---|---|
| EMA Fast | 9 | Short-term trend |
| EMA Slow | 21 | Medium-term trend |
| RSI | 14 | Momentum / overbought-oversold |
| Bollinger Bands | 20, 2σ | Volatility / mean reversion |
| ATR | 14 | Volatility (for stop/TP sizing) |
| ADX | 14 | Regime: < 25 ranging, ≥ 25 trending |
| Z-Score | 20 | Price dislocation from mean (BB period) |

All indicators are computed from scratch using numpy. No external indicator
libraries — the math is in `indicators.py` and is easy to verify.
