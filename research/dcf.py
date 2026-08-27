"""
Two-stage FCFF DCF from yfinance statements.

This is the empirical check in the research loop (AI Scientist: run an
experiment against the claim). Pre-FCF names (e.g. AUR) are tagged
qualitative — we do not invent a DCF.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

RF = 0.043          # nominal 10y proxy
ERP = 0.050
G_TERM = 0.025
STAGE_YEARS = 5
WACC_LO, WACC_HI = 0.06, 0.16
G_LO, G_HI = -0.05, 0.22


@dataclass
class DCFResult:
    ticker: str
    price: float
    value_ps: float | None
    mos: float | None          # (value - price) / price
    wacc: float | None
    fcf0: float | None
    g_stage: float | None
    shares: float | None
    ok: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "value_ps": self.value_ps,
            "mos": None if self.mos is None else round(self.mos, 4),
            "wacc": self.wacc,
            "fcf0": self.fcf0,
            "g_stage": self.g_stage,
            "ok": self.ok,
            "note": self.note,
        }


def dcf(ticker: str) -> DCFResult:
    t = ticker.upper().strip()
    fail = lambda note, price=0.0: DCFResult(
        ticker=t, price=price, value_ps=None, mos=None,
        wacc=None, fcf0=None, g_stage=None, shares=None,
        ok=False, note=note,
    )
    try:
        import yfinance as yf
        obj = yf.Ticker(t)
        info = obj.info or {}
        price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        shares = float(info.get("sharesOutstanding") or 0)
        if price <= 0 or shares <= 0:
            return fail("no price/shares", price)

        fcf_hist = _fcf_history(obj, info)
        if len(fcf_hist) < 1 or fcf_hist[0] <= 0:
            return fail("pre-FCF / negative FCF — qualitative only", price)

        fcf0 = fcf_hist[0]
        g = _cagr(fcf_hist)
        g = min(G_HI, max(G_LO, g))
        beta = float(info.get("beta") or 1.0)
        beta = min(2.2, max(0.4, beta))
        wacc = min(WACC_HI, max(WACC_LO, RF + beta * ERP))
        if g >= wacc - 0.005:
            g = wacc - 0.01

        pv = 0.0
        fcf = fcf0
        for yr in range(1, STAGE_YEARS + 1):
            fcf *= (1 + g)
            pv += fcf / ((1 + wacc) ** yr)
        fcf_term = fcf * (1 + G_TERM)
        tv = fcf_term / (wacc - G_TERM)
        pv += tv / ((1 + wacc) ** STAGE_YEARS)

        value_ps = pv / shares
        mos = (value_ps - price) / price
        return DCFResult(
            ticker=t, price=price, value_ps=value_ps, mos=mos,
            wacc=wacc, fcf0=fcf0, g_stage=g, shares=shares,
            ok=True,
            note=f"2-stage {STAGE_YEARS}y g={g:.1%} wacc={wacc:.1%} MOS={mos:.0%}",
        )
    except Exception as exc:
        log.debug(f"DCF {t} failed: {exc}")
        return fail(str(exc)[:160])


def _fcf_history(ticker_obj, info: dict) -> list[float]:
    """Most-recent-first free cash flow."""
    series = []
    try:
        cf = ticker_obj.cashflow
        if cf is not None and not cf.empty:
            row = None
            for name in ("Free Cash Flow", "FreeCashFlow"):
                if name in cf.index:
                    row = cf.loc[name]
                    break
            if row is None:
                ocf = capex = None
                for name in ("Operating Cash Flow", "Total Cash From Operating Activities"):
                    if name in cf.index:
                        ocf = cf.loc[name]
                        break
                for name in ("Capital Expenditure", "Capital Expenditures"):
                    if name in cf.index:
                        capex = cf.loc[name]
                        break
                if ocf is not None and capex is not None:
                    row = ocf + capex  # capex is typically negative
            if row is not None:
                series = [float(x) for x in row.dropna().tolist() if float(x) == float(x)]
    except Exception:
        pass
    if not series:
        live = info.get("freeCashflow")
        if live:
            series = [float(live)]
    return series


def _cagr(fcf_hist: list[float]) -> float:
    if len(fcf_hist) < 2 or fcf_hist[-1] <= 0 or fcf_hist[0] <= 0:
        return 0.06
    n = len(fcf_hist) - 1
    return (fcf_hist[0] / fcf_hist[-1]) ** (1 / n) - 1
