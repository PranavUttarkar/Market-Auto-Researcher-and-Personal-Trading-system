"""
Research desk: crowd + co-scientist loop + DCF → tradable universe.

The fund's instrument list is *this* output, not a hardcoded mega-cap book.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .crowd import CrowdScanner
from .dcf import DCFResult
from .loop import THESES, CoScientistLoop, apply_dcf_reviews
from .memory import MemoryStream
from .notebook import STATUS_SUPPORTED, ResearchNotebook
from .skills import SkillLibrary

log = logging.getLogger(__name__)

CRYPTO_CORE = [
    {"symbol": "BTC/USDT", "timeframe": "1d", "asset_class": "crypto"},
    {"symbol": "ETH/USDT", "timeframe": "1d", "asset_class": "crypto"},
    {"symbol": "BTC/USDT", "timeframe": "4h", "asset_class": "crypto"},
]

ETF_CLASS = {"GLD": "gold", "IAU": "gold", "USO": "stock", "XLE": "stock"}


@dataclass
class Candidate:
    symbol: str
    timeframe: str
    asset_class: str
    source: str
    thesis_ids: list[str] = field(default_factory=list)
    crowd_mentions: int = 0
    mos: float | None = None
    elo: float = 1000.0
    note: str = ""

    def as_instrument(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "asset_class": self.asset_class,
        }


class ResearchDesk:
    def __init__(self, notebook_path: str | Path, ai_client=None,
                 news_search=None, max_names: int = 16,
                 refresh_s: int = 21600):
        root = Path(notebook_path).parent
        self.nb = ResearchNotebook(notebook_path)
        self.memory = MemoryStream()
        self.skills = SkillLibrary(root / "research_skills.json")
        self.news = news_search
        self.crowd = CrowdScanner(tavily=news_search)
        self.loop = CoScientistLoop(
            notebook=self.nb, ai_client=ai_client,
            news_search=news_search, crowd=self.crowd,
            memory=self.memory, skills=self.skills,
        )
        self.max_names = max_names
        self.refresh_s = refresh_s
        self._last_run = 0.0
        self.candidates: list[Candidate] = []
        self.dcf_results: dict[str, DCFResult] = {}
        self.last_crowd: list[dict] = []

    def maybe_refresh(self, force: bool = False) -> bool:
        now = time.time()
        if not force and self._last_run and (now - self._last_run) < self.refresh_s:
            if not self.candidates:
                self.candidates = self._promote()
            return False
        log.info("Research desk refresh")
        try:
            self.loop.run_cycle()
        except Exception as exc:
            log.warning(f"Research cycle error (continuing): {exc}", exc_info=True)
        tickers = sorted({tk for h in self.nb.all() for tk in h.tickers})
        try:
            self.dcf_results = apply_dcf_reviews(self.nb, tickers)
            self.skills.mark_use("dcf_or_qualitative", win=any(
                r.ok and (r.mos or 0) >= 0.15 for r in self.dcf_results.values()
            ))
        except Exception as exc:
            log.warning(f"DCF pass failed: {exc}")
        for hyp in self.nb.supported():
            self.skills.distill(
                f"thesis_{hyp.thesis_id}_{hyp.id[:4]}",
                hyp.claim[:200],
                [f"tickers={hyp.tickers}", f"elo={hyp.elo:.0f}"],
            )
            self.memory.add(
                f"Supported {hyp.id}: {hyp.claim} {hyp.tickers}",
                kind="supported", importance=8, tags=hyp.tickers[:4],
            )
        self.last_crowd = [
            {"ticker": h.ticker, "mentions": h.mentions}
            for h in getattr(self.loop, "last_crowd", [])
        ]
        self.candidates = self._promote()
        self._last_run = now
        log.info(f"Desk universe: {[c.symbol for c in self.candidates]}")
        return True

    def instruments(self) -> list[dict]:
        if not self.candidates:
            self.candidates = self._promote()
        seen = set()
        out = []
        for row in CRYPTO_CORE + [c.as_instrument() for c in self.candidates]:
            key = f"{row['symbol']}::{row['timeframe']}"
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    def agent_universe(self) -> dict[str, list[str]]:
        """Dynamic AGENT_INSTRUMENTS. Crypto stays with satoshi/quant."""
        eq = [c.symbol for c in self.candidates]
        crypto = [r["symbol"] for r in CRYPTO_CORE]
        macro_ids = {"oil", "ai_power", "autonomous_trucking", "ai_memory"}
        macro = [c.symbol for c in self.candidates
                 if set(c.thesis_ids) & macro_ids or c.symbol in ("GLD", "USO", "XLE")]
        if "GLD" not in macro:
            macro.append("GLD")
        warren = [s for s in eq if "/" not in s]
        return {
            "warren": warren or eq,
            "quant": crypto + eq[:8],
            "macro": macro or ["GLD"],
            "satoshi": crypto,
        }

    def candidate_for(self, symbol: str) -> Candidate | None:
        for c in self.candidates:
            if c.symbol == symbol:
                return c
        return None

    def snapshot(self) -> dict:
        return {
            "cycle": self.nb.cycle,
            "n_hypotheses": len(self.nb.hypotheses),
            "notebook": self.nb.snapshot(16),
            "universe": [c.symbol for c in self.candidates],
            "dcf": {k: v.as_dict() for k, v in list(self.dcf_results.items())[:20]},
            "crowd": self.last_crowd[:12],
            "skills": self.skills.snapshot()[:10],
            "memories": [
                {"kind": m.kind, "text": m.text[:180]}
                for m in self.memory.items[-8:]
            ],
        }

    def _promote(self) -> list[Candidate]:
        """Name identification: supported high-Elo tickers + DCF MOS + crowd."""
        scores: dict[str, Candidate] = {}

        def bump(sym, **kw):
            if "/" in sym:
                return
            c = scores.get(sym) or Candidate(
                symbol=sym, timeframe="1d",
                asset_class=ETF_CLASS.get(sym, "stock"),
                source=kw.get("source", "research"),
            )
            if kw.get("thesis"):
                if kw["thesis"] not in c.thesis_ids:
                    c.thesis_ids.append(kw["thesis"])
            if kw.get("mentions"):
                c.crowd_mentions += int(kw["mentions"])
            if kw.get("mos") is not None:
                c.mos = kw["mos"]
            if kw.get("elo"):
                c.elo = max(c.elo, float(kw["elo"]))
            if kw.get("note"):
                c.note = kw["note"]
            c.source = kw.get("source", c.source)
            scores[sym] = c

        for h in self.nb.ranked(status=STATUS_SUPPORTED) + self.nb.ranked(status=None):
            if h.status == "refuted":
                continue
            for tk in h.tickers:
                bump(tk, thesis=h.thesis_id, elo=h.elo, source="hypothesis")

        for tk, res in self.dcf_results.items():
            if res.ok and res.mos is not None and res.mos >= 0.10:
                bump(tk, mos=res.mos, source="dcf", note=res.note)
            elif res.ok and res.mos is not None:
                bump(tk, mos=res.mos, note=res.note)

        # Always allow GLD as macro hedge vehicle
        bump("GLD", thesis="oil", source="macro_vehicle")

        ranked = sorted(
            scores.values(),
            key=lambda c: (
                (c.mos or 0) * 2
                + (c.elo - 1000) / 400
                + min(c.crowd_mentions, 8) * 0.05
                + (0.3 if c.thesis_ids else 0)
            ),
            reverse=True,
        )
        return ranked[: self.max_names]
