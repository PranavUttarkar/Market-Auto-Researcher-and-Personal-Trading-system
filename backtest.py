"""
Backtest & Monte Carlo Validation.

Measures realized EV in R-units (after slippage) by score bucket.
Compares flat vs score-scaled configs on the same historical data.
Only enable score scaling if this tool says it's safe.

Usage:
    python backtest.py              # 7-day backtest + Monte Carlo
    python backtest.py --days 14    # Longer lookback
    python backtest.py --mc 10000   # More Monte Carlo iterations
"""

import sys
import time
import logging
import argparse
from collections import defaultdict

import numpy as np

import config
from exchange import create_exchange
from strategy import Strategy

log = logging.getLogger(__name__)


# ─── Config override context manager ─────────────────────────────────

class ConfigOverride:
    """Temporarily override config values for a backtest run."""

    def __init__(self, **overrides):
        self._overrides = overrides
        self._originals = {}

    def __enter__(self):
        for key, val in self._overrides.items():
            self._originals[key] = getattr(config, key)
            setattr(config, key, val)
        return self

    def __exit__(self, *args):
        for key, val in self._originals.items():
            setattr(config, key, val)


# ─── Lightweight backtest engine ─────────────────────────────────────

class BacktestEngine:
    """Minimal engine for fast backtesting with R-tracking.

    Uses plain dicts instead of dataclasses for speed.
    Same logic as PaperEngine but stripped of logging/dashboard overhead.
    """

    def __init__(self, initial_balance):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = []
        self.trades = []
        self._id = 0

    def _next_id(self):
        self._id += 1
        return f"BT-{self._id:04d}"

    def get_equity(self, price):
        """Compute equity = cash + position value + unrealized PnL."""
        equity = self.balance
        for p in self.positions:
            equity += p["entry_price"] * p["size"]  # capital in position
            if p["side"] == "long":
                equity += (price - p["entry_price"]) * p["size"]
            else:
                equity += (p["entry_price"] - price) * p["size"]
        return equity

    def open_position(self, side, price, size, stop_loss, take_profit,
                      trailing_stop_dist, score, risk_distance):
        # Slippage on entry
        if config.SLIPPAGE_PCT > 0:
            if side == "long":
                price *= (1 + config.SLIPPAGE_PCT)
            else:
                price *= (1 - config.SLIPPAGE_PCT)

        cost = price * size
        entry_fee = cost * getattr(config, "FEE_PCT", 0.0)
        total_cost = cost + entry_fee
        if total_cost > self.balance:
            return None
        if cost > self.balance * config.MAX_POSITION_PCT:
            size = (self.balance * config.MAX_POSITION_PCT) / price
            cost = price * size
            entry_fee = cost * getattr(config, "FEE_PCT", 0.0)
            total_cost = cost + entry_fee

        pos = {
            "id": self._next_id(),
            "side": side,
            "entry_price": price,
            "size": size,
            "initial_size": size,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop_dist": trailing_stop_dist,
            "trailing_stop": stop_loss,
            "score": score,
            "risk_distance": risk_distance,
            "partial_closed": False,
            "realized_partial_pnl": 0.0,
            "entry_fee_paid": entry_fee,
        }
        self.balance -= total_cost
        self.positions.append(pos)
        return pos

    def close_position(self, pos, price, reason):
        # Slippage on exit
        if config.SLIPPAGE_PCT > 0:
            if pos["side"] == "long":
                price *= (1 - config.SLIPPAGE_PCT)
            else:
                price *= (1 + config.SLIPPAGE_PCT)

        if pos["side"] == "long":
            gross_pnl = (price - pos["entry_price"]) * pos["size"]
        else:
            gross_pnl = (pos["entry_price"] - price) * pos["size"]
        exit_fee = price * pos["size"] * getattr(config, "FEE_PCT", 0.0)
        pnl = gross_pnl - exit_fee
        total_pnl = pnl + pos["realized_partial_pnl"] - pos.get("entry_fee_paid", 0)
        self.balance += pos["entry_price"] * pos["size"] + total_pnl

        # Compute realized PnL in R-units — this is ground truth
        init_size = pos["initial_size"]
        pnl_in_r = 0.0
        if pos["risk_distance"] > 0 and init_size > 0:
            pnl_in_r = total_pnl / (pos["risk_distance"] * init_size)

        trade = {
            "score": pos["score"],
            "pnl": total_pnl,
            "pnl_in_r": pnl_in_r,
            "reason": reason,
            "risk_distance": pos["risk_distance"],
            "side": pos["side"],
        }
        self.trades.append(trade)
        self.positions.remove(pos)
        return trade

    def update_positions(self, price):
        """Check partial close, TP, trailing stop, hard stop."""
        closed = []

        for pos in list(self.positions):
            # Partial close (scale-out hedge)
            if (not pos["partial_closed"] and config.PARTIAL_CLOSE_ENABLED
                    and pos["risk_distance"] > 0):
                if pos["side"] == "long":
                    profit_r = (price - pos["entry_price"]) / pos["risk_distance"]
                else:
                    profit_r = (pos["entry_price"] - price) / pos["risk_distance"]

                if profit_r >= config.PARTIAL_CLOSE_AT_R:
                    close_size = pos["initial_size"] * config.PARTIAL_CLOSE_PCT
                    if 0 < close_size < pos["size"]:
                        if pos["side"] == "long":
                            partial_pnl = (price - pos["entry_price"]) * close_size
                        else:
                            partial_pnl = (pos["entry_price"] - price) * close_size
                        if config.SLIPPAGE_PCT > 0:
                            partial_pnl -= price * config.SLIPPAGE_PCT * close_size
                        partial_pnl -= price * close_size * getattr(config, "FEE_PCT", 0.0)
                        self.balance += pos["entry_price"] * close_size + partial_pnl
                        pos["realized_partial_pnl"] += partial_pnl
                        pos["size"] -= close_size
                        pos["partial_closed"] = True
                        if config.MOVE_STOP_TO_BE:
                            pos["stop_loss"] = pos["entry_price"]

            # Take profit
            if pos["side"] == "long" and price >= pos["take_profit"]:
                closed.append(self.close_position(pos, pos["take_profit"], "take_profit"))
                continue
            elif pos["side"] == "short" and price <= pos["take_profit"]:
                closed.append(self.close_position(pos, pos["take_profit"], "take_profit"))
                continue

            # Trailing stop
            if pos["side"] == "long":
                new_trail = price - pos["trailing_stop_dist"]
                if new_trail > pos["trailing_stop"]:
                    pos["trailing_stop"] = new_trail
                if price <= pos["trailing_stop"] and pos["trailing_stop"] > pos["stop_loss"]:
                    closed.append(self.close_position(pos, pos["trailing_stop"], "trailing_stop"))
                    continue
                if price <= pos["stop_loss"]:
                    closed.append(self.close_position(pos, pos["stop_loss"], "stop_loss"))
                    continue
            else:
                new_trail = price + pos["trailing_stop_dist"]
                if new_trail < pos["trailing_stop"]:
                    pos["trailing_stop"] = new_trail
                if price >= pos["trailing_stop"] and pos["trailing_stop"] < pos["stop_loss"]:
                    closed.append(self.close_position(pos, pos["trailing_stop"], "trailing_stop"))
                    continue
                if price >= pos["stop_loss"]:
                    closed.append(self.close_position(pos, pos["stop_loss"], "stop_loss"))
                    continue

        return closed


# ─── Historical data ─────────────────────────────────────────────────

def fetch_historical(exchange, symbol, timeframe, days):
    """Fetch historical OHLCV candles in chunks."""
    all_candles = []
    since = int((time.time() - days * 86400) * 1000)
    limit = 500

    while True:
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as e:
            log.warning(f"Fetch error: {e}, retrying...")
            time.sleep(2)
            continue

        if not candles:
            break
        all_candles.extend(candles)
        since = candles[-1][0] + 1
        if len(candles) < limit:
            break
        time.sleep(exchange.rateLimit / 1000)

    return all_candles


# ─── Backtest runner ─────────────────────────────────────────────────

def run_backtest(candles):
    """Run backtest over candles using current config. Returns (trades, final_balance)."""
    engine = BacktestEngine(config.INITIAL_BALANCE)
    strategy = Strategy()

    window = max(config.EMA_SLOW + 5, 100)

    for i in range(window, len(candles)):
        chunk = candles[i - window:i + 1]
        price = float(chunk[-1][4])

        # Update positions (partial close, stops, TP)
        engine.update_positions(price)

        # Run strategy
        signal = strategy.analyze(chunk)

        if signal and len(engine.positions) < config.MAX_OPEN_POSITIONS:
            entry = signal["entry"]
            stop = signal["stop_loss"]
            risk_per_unit = abs(entry - stop)
            score = signal["score"]

            if risk_per_unit > 0:
                equity = engine.get_equity(price)
                if equity <= 0:
                    continue

                # Score-based risk (reads from config — flat or scaled)
                risk_mult = config.SCORE_RISK_MULT.get(score, 1.0)
                risk_amount = equity * config.RISK_PER_TRADE * risk_mult
                size = risk_amount / risk_per_unit

                # Exposure-based hedge
                long_cost = sum(
                    p["entry_price"] * p["size"]
                    for p in engine.positions if p["side"] == "long"
                )
                short_cost = sum(
                    p["entry_price"] * p["size"]
                    for p in engine.positions if p["side"] == "short"
                )
                net_exposure = long_cost - short_cost
                exposure_ratio = abs(net_exposure) / equity if equity > 0 else 0
                same_dir = (
                    (signal["side"] == "long" and net_exposure > 0) or
                    (signal["side"] == "short" and net_exposure < 0)
                )
                if same_dir and exposure_ratio > 0.1:
                    size *= max(0.5, 1.0 - exposure_ratio)

                # Cap at max position
                max_size = (equity * config.MAX_POSITION_PCT) / entry
                size = min(size, max_size)

                if size * entry >= 10:
                    trailing_dist = signal["atr"] * config.TRAILING_STOP_ATR
                    risk_distance = signal.get("risk_distance", risk_per_unit)

                    engine.open_position(
                        side=signal["side"],
                        price=entry,
                        size=size,
                        stop_loss=signal["stop_loss"],
                        take_profit=signal["take_profit"],
                        trailing_stop_dist=trailing_dist,
                        score=score,
                        risk_distance=risk_distance,
                    )

    # Force close remaining positions at last price
    if candles:
        last_price = float(candles[-1][4])
        for pos in list(engine.positions):
            engine.close_position(pos, last_price, "backtest_end")

    return engine.trades, engine.balance


# ─── Statistics ──────────────────────────────────────────────────────

def compute_stats(trades):
    """Compute per-score-bucket statistics from realized R values."""
    buckets = defaultdict(list)
    for t in trades:
        buckets[t["score"]].append(t)

    stats = {}
    for score in sorted(buckets.keys()):
        rs = [t["pnl_in_r"] for t in buckets[score]]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]

        stats[score] = {
            "n": len(rs),
            "win_rate": len(wins) / len(rs) if rs else 0,
            "avg_win_r": float(np.mean(wins)) if wins else 0.0,
            "avg_loss_r": float(np.mean(losses)) if losses else 0.0,
            "ev_r": float(np.mean(rs)) if rs else 0.0,
            "max_loss_r": float(min(rs)) if rs else 0.0,
            "std_r": float(np.std(rs)) if rs else 0.0,
        }

    return stats


def compute_aggregate(trades):
    """Compute aggregate stats across all scores."""
    if not trades:
        return {}
    rs = [t["pnl_in_r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    return {
        "n": len(rs),
        "win_rate": len(wins) / len(rs),
        "avg_win_r": float(np.mean(wins)) if wins else 0.0,
        "avg_loss_r": float(np.mean(losses)) if losses else 0.0,
        "ev_r": float(np.mean(rs)),
        "max_loss_r": float(min(rs)),
        "std_r": float(np.std(rs)),
    }


def run_monte_carlo(trades, n_sims=5000, n_trades_per_sim=200):
    """Monte Carlo: resample trades to estimate drawdown & return distributions.

    Each simulation:
      1. Sample n_trades_per_sim trades with replacement
      2. Simulate equity evolution: equity *= (1 + risk% × R_outcome)
      3. Track max drawdown and final return
    """
    if len(trades) < 5:
        return None

    pnl_rs = np.array([t["pnl_in_r"] for t in trades])
    risk_pcts = np.array([
        config.RISK_PER_TRADE * config.SCORE_RISK_MULT.get(t["score"], 1.0)
        for t in trades
    ])
    n = len(trades)

    max_drawdowns = []
    final_returns = []
    ruin_count = 0

    for _ in range(n_sims):
        idx = np.random.randint(0, n, size=n_trades_per_sim)
        equity = 1.0
        peak = 1.0
        max_dd = 0.0

        for i in idx:
            equity_change = risk_pcts[i] * pnl_rs[i]
            equity *= (1 + equity_change)

            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

            if equity < 0.5:
                ruin_count += 1
                break

        max_drawdowns.append(max_dd)
        final_returns.append(equity - 1)

    return {
        "median_dd": float(np.median(max_drawdowns)),
        "p95_dd": float(np.percentile(max_drawdowns, 95)),
        "p99_dd": float(np.percentile(max_drawdowns, 99)),
        "median_ret": float(np.median(final_returns)),
        "p5_ret": float(np.percentile(final_returns, 5)),
        "p95_ret": float(np.percentile(final_returns, 95)),
        "prob_ruin": ruin_count / n_sims,
    }


def check_monotonic_ev(stats):
    """Check if EV-per-R monotonically increases with score.

    Returns (is_monotonic, scores, evs).
    is_monotonic is None if insufficient data.
    """
    scores = sorted(stats.keys())
    if len(scores) < 2:
        return None, scores, []
    evs = [stats[s]["ev_r"] for s in scores]
    mono = all(evs[i] <= evs[i + 1] for i in range(len(evs) - 1))
    return mono, scores, evs


# ─── Display ─────────────────────────────────────────────────────────

def print_results(label, trades, balance, stats, mc):
    """Print formatted results for one backtest run."""
    print(f"\n{'-' * 72}")
    print(f"  {label}")
    print(f"{'-' * 72}")

    agg = compute_aggregate(trades)
    ret = (balance / config.INITIAL_BALANCE - 1) * 100
    print(f"  Trades: {len(trades)}  |  "
          f"Final: ${balance:,.2f} ({ret:+.2f}%)  |  "
          f"Aggregate EV/R: {agg.get('ev_r', 0):.4f}")

    if stats:
        print(f"\n  {'Score':<7}{'N':<6}{'Win%':<8}"
              f"{'AvgWin(R)':<11}{'AvgLoss(R)':<12}"
              f"{'MaxLoss(R)':<12}{'EV/trade(R)':<12}")
        print(f"  {'-' * 66}")
        for score in sorted(stats.keys()):
            s = stats[score]
            print(f"  {score:<7}{s['n']:<6}{s['win_rate']*100:<8.1f}"
                  f"{s['avg_win_r']:<11.3f}{s['avg_loss_r']:<12.3f}"
                  f"{s['max_loss_r']:<12.3f}{s['ev_r']:<12.4f}")

    if mc:
        print(f"\n  Monte Carlo ({n_mc_label(trades)} trades resampled):")
        print(f"    Median max drawdown: {mc['median_dd']*100:.1f}%")
        print(f"    P95 max drawdown:    {mc['p95_dd']*100:.1f}%")
        print(f"    P99 max drawdown:    {mc['p99_dd']*100:.1f}%")
        print(f"    Median return:       {mc['median_ret']*100:+.1f}%")
        print(f"    P5-P95 return:        "
              f"{mc['p5_ret']*100:+.1f}% to {mc['p95_ret']*100:+.1f}%")
        print(f"    Prob of ruin (<50%): {mc['prob_ruin']*100:.2f}%")


def n_mc_label(trades):
    return len(trades)


# ─── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Backtest & Monte Carlo validation for score-based risk scaling"
    )
    parser.add_argument("--days", type=int, default=7,
                        help="Lookback period in days (default: 7)")
    parser.add_argument("--mc", type=int, default=5000,
                        help="Monte Carlo simulations (default: 5000)")
    parser.add_argument("--holdout", type=float, default=0.0,
                        help="Out-of-sample holdout fraction (e.g. 0.2 = last 20%); 0 = disabled")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    print("=" * 72)
    print("  BACKTEST & MONTE CARLO VALIDATION")
    print("  Measures realized EV in R-units after slippage, by score bucket.")
    print("  Compares flat config (control) vs score-scaled config (test).")
    print("=" * 72)

    # ── Fetch historical data ─────────────────────────────────────────
    print(f"\n  Fetching {args.days} days of "
          f"{config.SYMBOL} {config.TIMEFRAME} data...")
    exchange = create_exchange()
    candles = fetch_historical(
        exchange, config.SYMBOL, config.TIMEFRAME, args.days
    )
    print(f"  Got {len(candles)} candles "
          f"({len(candles) / 60:.0f} hours)")

    if len(candles) < 200:
        print("\n  ERROR: Not enough data for meaningful backtest.")
        print("  Need at least 200 candles. Try increasing --days.")
        sys.exit(1)

    # ── Optional: In-sample vs Out-of-sample split ────────────────────
    use_holdout = args.holdout > 0 and args.holdout < 1
    in_candles = candles
    oos_candles = None
    if use_holdout:
        split_idx = int(len(candles) * (1 - args.holdout))
        if split_idx < 100 or len(candles) - split_idx < 100:
            print(f"\n  WARNING: Holdout {args.holdout*100:.0f}% too small, disabling.")
            use_holdout = False
        else:
            window = max(config.EMA_SLOW + 5, 55)
            in_candles = candles[:split_idx]
            oos_candles = candles[split_idx - window:]  # Warmup from in-sample
            print(f"\n  Holdout: In-sample {len(in_candles)} bars, "
                  f"Out-of-sample {len(oos_candles) - window} bars (last {args.holdout*100:.0f}%)")

    # ── Test 1: Flat config (control) ─────────────────────────────────
    flat = dict(
        SCORE_RISK_MULT={2: 1.0, 3: 1.0, 4: 1.0},
        SCORE_RR={2: 2.0, 3: 2.0, 4: 2.0},
        SCORE_ATR_STOP={2: 2.0, 3: 2.0, 4: 2.0},
    )
    with ConfigOverride(**flat):
        flat_trades, flat_bal = run_backtest(in_candles)
        flat_stats = compute_stats(flat_trades)
        flat_mc = run_monte_carlo(flat_trades, args.mc)

    print_results(
        "FLAT CONFIG (control - all scores treated equally)",
        flat_trades, flat_bal, flat_stats, flat_mc
    )

    # ── Optional: Out-of-sample run ───────────────────────────────────
    if use_holdout and oos_candles:
        with ConfigOverride(**flat):
            oos_trades, oos_bal = run_backtest(oos_candles)
            oos_stats = compute_stats(oos_trades)
        oos_ret = (oos_bal / config.INITIAL_BALANCE - 1) * 100
        is_ret = (flat_bal / config.INITIAL_BALANCE - 1) * 100
        oos_agg = compute_aggregate(oos_trades)
        print(f"\n  {'-' * 72}")
        print(f"  OUT-OF-SAMPLE (holdout {args.holdout*100:.0f}%)")
        print(f"  Trades: {len(oos_trades)}  |  Return: {oos_ret:+.2f}%  |  EV/R: {oos_agg.get('ev_r', 0):.4f}")
        print(f"  In-sample return: {is_ret:+.2f}%  |  OOS vs IS: {oos_ret - is_ret:+.2f}%")
        if oos_ret < is_ret - 5:
            print(f"  WARNING: OOS much worse than IS - possible overfitting.")

    # ── Test 2: Aggressive score-scaled config ────────────────────────
    aggressive = dict(
        SCORE_RISK_MULT={2: 1.0, 3: 1.75, 4: 2.5},
        SCORE_RR={2: 2.0, 3: 2.5, 4: 3.0},
        SCORE_ATR_STOP={2: 1.5, 3: 1.25, 4: 1.0},
    )
    with ConfigOverride(**aggressive):
        agg_trades, agg_bal = run_backtest(in_candles)
        agg_stats = compute_stats(agg_trades)
        agg_mc = run_monte_carlo(agg_trades, args.mc)

    print_results(
        "SCORE-SCALED CONFIG (aggressive — tighter stops, wider R:R)",
        agg_trades, agg_bal, agg_stats, agg_mc
    )

    # ── Verdict ───────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print("  VALIDATION VERDICT")
    print(f"{'=' * 72}")

    mono_flat, f_scores, f_evs = check_monotonic_ev(flat_stats)
    mono_agg, a_scores, a_evs = check_monotonic_ev(agg_stats)

    if f_evs:
        ev_dict = {s: f"{e:.4f}" for s, e in zip(f_scores, f_evs)}
        print(f"\n  Flat EV by score:    {ev_dict}")
        if mono_flat is not None:
            print(f"  Flat monotonic:      {'YES' if mono_flat else 'NO'}")

    if a_evs:
        ev_dict = {s: f"{e:.4f}" for s, e in zip(a_scores, a_evs)}
        print(f"  Scaled EV by score:  {ev_dict}")
        if mono_agg is not None:
            print(f"  Scaled monotonic:    {'YES' if mono_agg else 'NO'}")

    flat_ret = (flat_bal / config.INITIAL_BALANCE - 1) * 100
    agg_ret = (agg_bal / config.INITIAL_BALANCE - 1) * 100

    # Buy-and-hold benchmark
    if in_candles:
        first_price = float(in_candles[0][4])
        last_price = float(in_candles[-1][4])
        bh_ret = (last_price / first_price - 1) * 100
        print(f"\n  Buy-and-hold:        {bh_ret:+.2f}% (benchmark)")
    print(f"  Flat return:         {flat_ret:+.2f}%")
    print(f"  Scaled return:       {agg_ret:+.2f}%")

    if flat_mc:
        print(f"  Flat P95 drawdown:   {flat_mc['p95_dd']*100:.1f}%")
    if agg_mc:
        print(f"  Scaled P95 drawdown: {agg_mc['p95_dd']*100:.1f}%")

    # Decision
    problems = []

    if mono_agg is not None and not mono_agg:
        problems.append(
            "EV does NOT monotonically increase with score — "
            "higher scores are not reliably better after slippage"
        )
    if agg_mc and agg_mc["p95_dd"] > 0.30:
        problems.append(
            f"P95 max drawdown too high "
            f"({agg_mc['p95_dd']*100:.1f}% > 30% threshold)"
        )
    if agg_mc and agg_mc["prob_ruin"] > 0.01:
        problems.append(
            f"Ruin probability too high "
            f"({agg_mc['prob_ruin']*100:.1f}% > 1% threshold)"
        )
    if agg_ret <= flat_ret:
        problems.append(
            f"Scaled config did not outperform flat "
            f"({agg_ret:+.2f}% vs {flat_ret:+.2f}%)"
        )

    # Check if flat config itself is negative EV
    flat_agg = compute_aggregate(flat_trades)
    if flat_agg and flat_agg["ev_r"] < 0:
        print(f"\n  WARNING: Flat config has NEGATIVE EV ({flat_agg['ev_r']:.4f}R).")
        print(f"  The base strategy may not be profitable after slippage")
        print(f"  on {config.TIMEFRAME} candles. Consider wider timeframes.")

    if problems:
        print(f"\n  RESULT: DO NOT ENABLE SCORE SCALING")
        for p in problems:
            print(f"    - {p}")
        print(f"\n  Keep config.py with flat values (all scores equal).")
        print(f"  If flat EV is also negative, consider wider timeframes")
        print(f"  (5m, 15m) where slippage is a smaller fraction of ATR.")
    else:
        print(f"\n  RESULT: Score scaling PASSED validation")
        print(f"    - EV monotonically increases with score")
        print(f"    - Return improved: {flat_ret:+.2f}% -> {agg_ret:+.2f}%")
        if agg_mc:
            print(f"    - P95 drawdown: {agg_mc['p95_dd']*100:.1f}%")
            print(f"    - Ruin probability: {agg_mc['prob_ruin']*100:.2f}%")
        print(f"\n  You may uncomment aggressive values in config.py.")
        print(f"  Re-validate monthly — market regimes change.")

    print()


if __name__ == "__main__":
    main()
