"""
Persistent research notebook.

Co-Scientist (Gottweis et al., Nature 2026) keeps a "persistent context
memory" of hypotheses that survive across generate / reflect / rank / evolve
cycles. Sakana's AI Scientist grows an *archive* of ideas with review scores.
This file is that memory: JSON on disk, not a one-shot prompt.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Co-Scientist statuses after the Reflection agent (virtual peer review).
STATUS_OPEN = "open"
STATUS_SUPPORTED = "supported"
STATUS_REFUTED = "refuted"


@dataclass
class Evidence:
    source: str          # "tavily" | "reddit" | "yfinance" | "dcf" | "critique"
    snippet: str
    url: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class Review:
    """Reflection-agent (peer-review) record, AI Scientist style."""
    verdict: str         # open | supported | refuted
    critique: str
    confidence: int = 5
    ts: float = field(default_factory=time.time)


@dataclass
class Hypothesis:
    """One research claim. Tickers are *outputs*, not inputs."""
    id: str
    claim: str
    tickers: list[str]
    thesis_id: str = ""
    status: str = STATUS_OPEN
    elo: float = 1000.0
    generation: int = 0
    questions: list[str] = field(default_factory=list)   # STORM follow-ups
    evidence: list[Evidence] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    parent_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def citations(self) -> list[str]:
        return [e.url for e in self.evidence if e.url]


class ResearchNotebook:
    """Disk-backed hypothesis archive. Survives process restarts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hypotheses: dict[str, Hypothesis] = {}
        self.cycle: int = 0
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.cycle = int(raw.get("cycle", 0))
            for h in raw.get("hypotheses", []):
                ev = [Evidence(**e) for e in h.pop("evidence", [])]
                rv = [Review(**r) for r in h.pop("reviews", [])]
                hyp = Hypothesis(**h, evidence=ev, reviews=rv)
                self.hypotheses[hyp.id] = hyp
            log.info(f"Notebook loaded | {len(self.hypotheses)} hypotheses | cycle {self.cycle}")
        except Exception as exc:
            log.warning(f"Notebook load failed: {exc}")

    def save(self):
        payload = {
            "cycle": self.cycle,
            "updated_at": time.time(),
            "hypotheses": [
                {
                    **{k: v for k, v in asdict(h).items()
                       if k not in ("evidence", "reviews")},
                    "evidence": [asdict(e) for e in h.evidence[-20:]],
                    "reviews": [asdict(r) for r in h.reviews[-8:]],
                }
                for h in self.hypotheses.values()
            ],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def new_id(self) -> str:
        return uuid.uuid4().hex[:10]

    def add(self, claim: str, tickers: list[str], thesis_id: str = "",
            questions: list[str] | None = None,
            parent_ids: list[str] | None = None,
            generation: int = 0) -> Hypothesis:
        hyp = Hypothesis(
            id=self.new_id(),
            claim=claim.strip(),
            tickers=_uniq_tickers(tickers),
            thesis_id=thesis_id,
            questions=questions or [],
            parent_ids=parent_ids or [],
            generation=generation,
        )
        self.hypotheses[hyp.id] = hyp
        self.save()
        return hyp

    def get(self, hid: str) -> Hypothesis | None:
        return self.hypotheses.get(hid)

    def all(self) -> list[Hypothesis]:
        return list(self.hypotheses.values())

    def open_ones(self) -> list[Hypothesis]:
        return [h for h in self.all() if h.status == STATUS_OPEN]

    def supported(self) -> list[Hypothesis]:
        return [h for h in self.all() if h.status == STATUS_SUPPORTED]

    def add_evidence(self, hid: str, source: str, snippet: str, url: str = ""):
        h = self.hypotheses.get(hid)
        if not h:
            return
        h.evidence.append(Evidence(source=source, snippet=snippet[:800], url=url))
        h.updated_at = time.time()
        if len(h.evidence) > 30:
            h.evidence = h.evidence[-30:]
        self.save()

    def add_review(self, hid: str, verdict: str, critique: str, confidence: int = 5):
        h = self.hypotheses.get(hid)
        if not h:
            return
        if verdict not in (STATUS_OPEN, STATUS_SUPPORTED, STATUS_REFUTED):
            verdict = STATUS_OPEN
        h.reviews.append(Review(verdict=verdict, critique=critique[:1200],
                                confidence=int(confidence)))
        h.status = verdict
        h.updated_at = time.time()
        self.save()

    def elo_update(self, winner_id: str, loser_id: str, k: float = 32.0):
        """Co-Scientist ranking agent: pairwise tournament → Elo."""
        w = self.hypotheses.get(winner_id)
        l = self.hypotheses.get(loser_id)
        if not w or not l or w.id == l.id:
            return
        expected = 1.0 / (1.0 + 10 ** ((l.elo - w.elo) / 400.0))
        w.elo += k * (1.0 - expected)
        l.elo += k * (0.0 - (1.0 - expected))
        w.updated_at = l.updated_at = time.time()
        self.save()

    def ranked(self, status: str | None = STATUS_SUPPORTED) -> list[Hypothesis]:
        hs = self.all() if status is None else [h for h in self.all() if h.status == status]
        return sorted(hs, key=lambda h: h.elo, reverse=True)

    def snapshot(self, limit: int = 20) -> list[dict]:
        """Dashboard payload."""
        rows = []
        for h in sorted(self.all(), key=lambda x: x.updated_at, reverse=True)[:limit]:
            rows.append({
                "id": h.id,
                "claim": h.claim,
                "tickers": h.tickers,
                "thesis_id": h.thesis_id,
                "status": h.status,
                "elo": round(h.elo, 1),
                "generation": h.generation,
                "citations": h.citations()[:5],
                "n_evidence": len(h.evidence),
                "last_critique": h.reviews[-1].critique if h.reviews else "",
            })
        return rows


def _uniq_tickers(tickers: list[str]) -> list[str]:
    out, seen = [], set()
    for t in tickers:
        s = str(t).upper().strip().replace("$", "")
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out
