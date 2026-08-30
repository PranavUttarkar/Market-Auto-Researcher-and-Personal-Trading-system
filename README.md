# Personal Trading + Market + Macro conditions Auto-Researcher

Autonomous paper-trading trial system with data and cost-modeling and continuous research system that ran unattended on a DigitalOcean droplet **26 Feb 2026 → July 2026** (~5 months) under `systemd` (`Restart=always`).



```
research cycle (hours)
  crowd pulling market sentiment from forums (WSB/DD) + macro theses research across industries like (trucking / HBM / oil / power)
       → generate hypotheses (conditioned on retrieved memories)
       → retrieve (Tavily, Reddit, filings/news)
       → independent critique → Elo debate → evolve children
       → Discounted Cash Flow checks which find and promote tickers into the book
       → write successful procedures back into the playbook
```

trading tick (60s)
  1d / 4h OHLCV → Donchian + TS momentum (crypto / quant)
               → DCF/thesis longs ("warren" agent) / thematic (macro)

           → risk check → PaperEngine Trade (slip + fee + R)
---

## Research desk

`python ai_hedge_fund.py` → to view moves open http://127.0.0.1:5002 on your machine

Persistent state will be stored in: `data/research_notebook.json` (hypotheses, evidence, citations, Elo, status open/supported/refuted) and `data/research_skills.json` (playbook grows as u keep the agent running).

Each cycle in `research/loop.py`:

1. **Generate** — research goals are theses (autonomous trucking / Aurora, AI memory/HBM, oil, datacenter power, crowd DD). The model must emit retrieval *questions* and named tickers. Prompt is stuffed with `MemoryStream.retrieve` (recency × relevance × importance) and the current playbook, not a blank chat.
2. **Retrieve** — those questions go to Tavily + Reddit hot/DD JSON (`research/crowd.py`). Evidence rows store URL + snippet on the hypothesis.
3. **Reflect** — a separate critic prompt, also memory-conditioned, writes `supported | open | refuted`.
4. **Rank** — pairwise debate, Elo update on the notebook.
5. **Evolve** — top-Elo pair is combined into a child hypothesis (`parent_ids` set).
6. **DCF** — `research/dcf.py` 2-stage FCFF from yfinance. MOS ≥ 15% can promote; pre-FCF names stay qualitative (no fake value). Supported claims distill a new playbook skill.

Without API keys only these  objects will run: crowd + thesis seeds + DCF heuristics.

Warren only longs desk-promoted names (Top of S&P). Macro is restricted to oil/trucking/memory/power/GLD. Quant and Satoshi do not LLM-pick 15m RSI; they run `TrendFollowAgent`.

---

## Crypto trend tracker

`python main.py` → http://127.0.0.1:5000 — BTC/USDT **1d**.

`strategy.py` / `fund/agents/trend.py`:

- Skip if ADX < 18 or ATR% is dead vs its 50-bar mean
- Long if close breaks the *prior* 20-bar Donchian high **and** 20-bar and 60-bar returns are positive
- Short is the mirror
- Stop = 3×ATR. Take-profit is 20R so the **trailing 3×ATR stop** is the exit

Same sleeve on the fund: BTC/ETH 1d and BTC 4h.

---

## Fills

```
size = (equity × 0.02 × weight) / |entry − stop|
fill is adverse 1.5–2 bps/side; fees on; pnl_in_r = net / (risk × size)
```

Risk officer: drawdown breaker, per-agent / per-name caps, net exposure cap.

---

## Run

```bash
pip install -r requirements.txt
python main.py                 # :5000  BTC 1d trend
python fund/main_fund.py       # :5001  systematic 1d/4h
cp .env.example .env           # optional LLM + Tavily
python ai_hedge_fund.py        # :5002  research desk + book
python backtest.py --days 120 --mc 5000 --holdout 0.2
```

`PAPER_TRADING` is True.

Signal math historically used on the 5-month droplet (regime score, R after costs): [`STRATEGY.md`](STRATEGY.md). Live path is now the daily/4h trend + desk.
