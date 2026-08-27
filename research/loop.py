"""
Co-Scientist / Deep Research / STORM / AI Scientist loop, mapped onto
equity *name identification*.

Cycle (one pass, then persist to the notebook):

  1. GENERATE  — Co-Scientist Generation agent. Conditioned on the archive
                 (Sakana AI Scientist). STORM: emit retrieval *questions*
                 per thesis, not a ticker list.
  2. RETRIEVE  — Gemini Deep Research: plan → multi-source search → read.
                 Tavily + Reddit/DD + yfinance. Citations stored as Evidence.
  3. REFLECT   — Co-Scientist Reflection agent = virtual peer reviewer.
                 Verdict open | supported | refuted. Written into notebook.
  4. RANK      — Co-Scientist Ranking agent: pairwise scientific debate,
                 Elo update (same tournament math as the paper).
  5. EVOLVE    — Co-Scientist Evolution agent: mutate / combine top Elo
                 hypotheses into a child generation (archive grows).
  6. PROMOTE   — Tickers on supported, high-Elo claims become the book.
                 DCF is the empirical check (AI Scientist "run the experiment").

Without an LLM key the generate/reflect/rank/evolve steps degrade to
crowd + DCF heuristics so the desk still produces a universe.
"""

from __future__ import annotations

import logging
import time

from .crowd import CrowdScanner, CrowdHit
from .dcf import dcf, DCFResult
from .memory import MemoryStream
from .notebook import (
    STATUS_OPEN, STATUS_REFUTED, STATUS_SUPPORTED,
    Hypothesis, ResearchNotebook,
)
from .skills import SkillLibrary

log = logging.getLogger(__name__)

# Research *goals* (Co-Scientist input). Seeds are search hints, not the book.
THESES = [
    {
        "id": "autonomous_trucking",
        "goal": "Which listed names are real expressions of autonomous trucking / Aurora-class autonomy over a 3–7y horizon?",
        "search": "Aurora AUR autonomous trucking robotaxi freight 2026 due diligence",
        "seeds": ["AUR", "TSLA", "UBER"],
    },
    {
        "id": "ai_memory",
        "goal": "Who captures AI memory / HBM tightness (suppliers, not just NVDA)?",
        "search": "HBM high bandwidth memory shortage MU SK hynix Samsung AMD AI 2026",
        "seeds": ["MU", "AMD", "AVGO", "TSM"],
    },
    {
        "id": "oil",
        "goal": "Oil / OPEC / spare-capacity regime — which operators or beta vehicles?",
        "search": "OPEC crude oil supply demand energy stocks 2026 XOM COP",
        "seeds": ["XOM", "CVX", "COP", "XLE", "USO"],
    },
    {
        "id": "ai_power",
        "goal": "AI datacenter power, uranium, copper, utilities as a multi-year constraint.",
        "search": "AI datacenter power uranium copper utilities CEG VST CCJ 2026",
        "seeds": ["CEG", "VST", "CCJ", "FCX"],
    },
    {
        "id": "crowd_dd",
        "goal": "What names is WSB / SA / ValueInvesting actually writing DD on, not memeing?",
        "search": "reddit wallstreetbets due diligence undervalued",
        "seeds": [],
    },
]


class CoScientistLoop:
    def __init__(self, notebook: ResearchNotebook, ai_client=None,
                 news_search=None, crowd: CrowdScanner | None = None,
                 memory: MemoryStream | None = None,
                 skills: SkillLibrary | None = None):
        self.nb = notebook
        self.ai = ai_client
        self.news = news_search
        self.crowd = crowd or CrowdScanner(tavily=news_search)
        self.memory = memory or MemoryStream()
        self.skills = skills
        self.last_crowd: list = []

    def run_cycle(self) -> dict:
        """One generate-critique-revise pass. Cheap: a few LLM calls."""
        self.nb.cycle += 1
        cycle = self.nb.cycle
        log.info(f"Research cycle {cycle} start")

        crowd = self.crowd.scan()
        self.last_crowd = crowd
        for h in crowd[:12]:
            self.memory.add(
                f"{h.ticker} mentioned {h.mentions}x. " + "; ".join(h.snippets[:2]),
                kind="crowd", importance=min(9, 3 + h.mentions),
                tags=[h.ticker, "reddit"],
            )
        generated = self._generate(crowd)
        self._retrieve(generated, crowd)
        self._reflect()
        self._tournament()
        evolved = self._evolve()
        if evolved:
            self._retrieve(evolved, crowd)
            self._reflect()
        self.nb.save()
        log.info(f"Research cycle {cycle} done | n={len(self.nb.hypotheses)}")
        return {"cycle": cycle, "n": len(self.nb.hypotheses)}

    # ── 1. Generation ──────────────────────────────────────────────

    def _generate(self, crowd: list[CrowdHit]) -> list[Hypothesis]:
        created = []
        archive_txt = self._archive_digest()
        crowd_txt = ", ".join(f"{h.ticker}×{h.mentions}" for h in crowd[:15]) or "(none)"
        playbook = self.skills.playbook_text() if self.skills else ""
        if self.skills:
            self.skills.mark_use("storm_questions")
            self.skills.mark_use("crowd_dd_filter")

        if self.ai:
            for thesis in THESES:
                existing = [h for h in self.nb.all() if h.thesis_id == thesis["id"]]
                if len(existing) >= 4:
                    continue
                memories = self.memory.format(thesis["goal"] + " " + " ".join(thesis["seeds"]), k=8)
                prompt = (
                    f"Research goal: {thesis['goal']}\n"
                    f"Thesis id: {thesis['id']}\n"
                    f"Crowd tickers (mentions): {crowd_txt}\n"
                    f"Retrieved memories (recency×relevance×importance):\n{memories}\n"
                    f"Playbook (use these procedures):\n{playbook}\n"
                    f"Existing archive (extend or contradict, do not copy):\n{archive_txt}\n\n"
                    "First write 3 retrieval questions a sceptical analyst would ask.\n"
                    "Then propose 1–2 falsifiable hypotheses. Each MUST name listed "
                    "tickers that express the thesis. Do not default to AAPL/MSFT/GOOGL "
                    "unless the retrieved evidence is specifically about them.\n"
                    "Respond JSON:\n"
                    '{"hypotheses":[{"claim":"...","tickers":["MU"],'
                    '"questions":["..."]}]}'
                )
                result = self.ai.analyze(_GEN_SYS, prompt, temperature=0.5)
                if not result:
                    continue
                for item in (result.get("hypotheses") or [])[:2]:
                    tickers = item.get("tickers") or []
                    claim = item.get("claim") or ""
                    questions = item.get("questions") or []
                    if not claim:
                        continue
                    hyp = self.nb.add(
                        claim=claim, tickers=tickers, thesis_id=thesis["id"],
                        questions=list(questions)[:4],
                        generation=self.nb.cycle,
                    )
                    created.append(hyp)
                    self.memory.add(
                        f"Generated {hyp.id}: {claim} → {tickers}",
                        kind="hypothesis", importance=6,
                        tags=[thesis["id"], *tickers[:4]],
                    )
                    log.info(f"GEN {hyp.id} [{thesis['id']}] {hyp.tickers} {claim[:80]}")
        else:
            created.extend(self._heuristic_generate(crowd))
        return created

    def _heuristic_generate(self, crowd: list[CrowdHit]) -> list[Hypothesis]:
        """No-LLM path: crowd names + thesis seeds become open claims."""
        created = []
        top = [h.ticker for h in crowd[:8]]
        if top and not any(h.thesis_id == "crowd_dd" for h in self.nb.open_ones()):
            created.append(self.nb.add(
                claim=f"Retail DD is concentrating in {', '.join(top[:5])}; "
                      "screen for those with a DCF MOS rather than meme flow.",
                tickers=top[:8],
                thesis_id="crowd_dd",
                questions=["Which of these have positive FCF?",
                           "Which posts are actual DD vs YOLO captions?"],
                generation=self.nb.cycle,
            ))
        for thesis in THESES:
            if thesis["id"] == "crowd_dd":
                continue
            if any(h.thesis_id == thesis["id"] for h in self.nb.all()):
                continue
            created.append(self.nb.add(
                claim=thesis["goal"],
                tickers=list(thesis["seeds"]),
                thesis_id=thesis["id"],
                questions=[thesis["search"]],
                generation=self.nb.cycle,
            ))
        return created

    # ── 2. Retrieve (Deep Research multi-source) ───────────────────

    def _retrieve(self, hyps: list[Hypothesis], crowd: list[CrowdHit]):
        crowd_map = {h.ticker: h for h in crowd}
        for hyp in hyps:
            queries = list(hyp.questions) or [hyp.claim[:180]]
            thesis = next((t for t in THESES if t["id"] == hyp.thesis_id), None)
            if thesis:
                queries.append(thesis["search"])
            for q in queries[:3]:
                self._search_into(hyp.id, q)
            for tk in hyp.tickers[:6]:
                hit = crowd_map.get(tk)
                if hit:
                    snip = "; ".join(hit.snippets[:2]) or f"{hit.mentions} mentions"
                    url = hit.sources[0] if hit.sources else ""
                    self.nb.add_evidence(hyp.id, "reddit", f"{tk}: {snip}", url)
                    self.memory.add(
                        f"Reddit {tk}: {snip}", kind="reddit",
                        importance=min(8, 3 + hit.mentions), tags=[tk],
                    )
                if self.news:
                    news = self.news.get_news(tk)
                    if news:
                        self.nb.add_evidence(hyp.id, "tavily", f"{tk}: {news[:400]}")

    def _search_into(self, hid: str, query: str):
        if not self.news or not hasattr(self.news, "search_raw"):
            return
        try:
            rows = self.news.search_raw(query, max_results=4)
        except Exception as exc:
            log.debug(f"retrieve failed: {exc}")
            return
        for row in rows:
            snip = (row.get("content") or row.get("title") or "")[:500]
            url = row.get("url") or ""
            if snip:
                self.nb.add_evidence(hid, "tavily", snip, url)
                self.memory.add(snip, kind="web", importance=5, tags=[])

    # ── 3. Reflection (virtual peer review) ────────────────────────

    def _reflect(self):
        for hyp in list(self.nb.open_ones())[:6]:
            evidence_txt = "\n".join(
                f"- [{e.source}] {e.snippet[:240]} ({e.url})"
                for e in hyp.evidence[-8:]
            ) or "(no evidence yet)"
            memories = self.memory.format(hyp.claim + " " + " ".join(hyp.tickers), k=6)
            if self.ai:
                prompt = (
                    f"Claim: {hyp.claim}\nTickers: {hyp.tickers}\n"
                    f"Thesis: {hyp.thesis_id}\nEvidence:\n{evidence_txt}\n"
                    f"Retrieved memories:\n{memories}\n\n"
                    "Peer-review as a sell-side sceptic. Verdict supported, "
                    "refuted, or still open? Do the tickers express the thesis?\n"
                    'JSON: {"verdict":"supported"|"refuted"|"open",'
                    '"critique":"...","confidence":1-10}'
                )
                result = self.ai.analyze(_REFLECT_SYS, prompt, temperature=0.2)
                if result:
                    self.nb.add_review(
                        hyp.id,
                        str(result.get("verdict", STATUS_OPEN)).lower(),
                        str(result.get("critique", "")),
                        int(result.get("confidence", 5) or 5),
                    )
                    self.memory.add(
                        f"Critique {hyp.id}: {result.get('verdict')} {result.get('critique','')[:200]}",
                        kind="critique", importance=7, tags=hyp.tickers[:4],
                    )
                    continue
            # Heuristic fallback
            n_ev = len(hyp.evidence)
            if n_ev >= 3:
                self.nb.add_review(hyp.id, STATUS_OPEN,
                                   f"{n_ev} evidence items, awaiting DCF.", 4)
            else:
                self.nb.add_review(hyp.id, STATUS_OPEN,
                                   "Thin evidence; keep open.", 3)

    # ── 4. Ranking tournament ──────────────────────────────────────

    def _tournament(self):
        pool = [h for h in self.nb.all() if h.status != STATUS_REFUTED]
        pool = sorted(pool, key=lambda h: h.updated_at, reverse=True)[:8]
        if len(pool) < 2:
            return
        pairs = list(zip(pool[::2], pool[1::2]))[:3]
        for a, b in pairs:
            winner = self._debate(a, b)
            if winner is None:
                continue
            loser = b if winner.id == a.id else a
            self.nb.elo_update(winner.id, loser.id)
            log.info(f"ELO {winner.id} beat {loser.id} → {winner.elo:.0f}/{loser.elo:.0f}")

    def _debate(self, a: Hypothesis, b: Hypothesis) -> Hypothesis | None:
        if self.ai:
            prompt = (
                f"Hypothesis A ({a.id}, elo {a.elo:.0f}, {a.status}): {a.claim} "
                f"tickers={a.tickers}\n"
                f"Hypothesis B ({b.id}, elo {b.elo:.0f}, {b.status}): {b.claim} "
                f"tickers={b.tickers}\n"
                "Scientific debate: which is the better *name-identification* "
                "research claim for a 1–5y book? Prefer specific, falsifiable, "
                "non-mega-cap-default claims with evidence.\n"
                'JSON: {"winner":"A"|"B","reason":"..."}'
            )
            result = self.ai.analyze(_RANK_SYS, prompt, temperature=0.2)
            if result:
                w = str(result.get("winner", "A")).upper()
                return a if w != "B" else b
        # Fallback: more evidence + not refuted wins
        sa = (len(a.evidence), a.elo)
        sb = (len(b.evidence), b.elo)
        return a if sa >= sb else b

    # ── 5. Evolution ───────────────────────────────────────────────

    def _evolve(self) -> list[Hypothesis]:
        top = self.nb.ranked(status=None)[:3]
        top = [h for h in top if h.status != STATUS_REFUTED]
        if len(top) < 2 or not self.ai:
            return []
        a, b = top[0], top[1]
        prompt = (
            f"Combine/refine these top-Elo hypotheses into ONE tighter claim "
            f"with a cleaner ticker set.\n"
            f"A: {a.claim} {a.tickers}\nB: {b.claim} {b.tickers}\n"
            'JSON: {"claim":"...","tickers":["..."],"thesis_id":"..."}'
        )
        result = self.ai.analyze(_EVOLVE_SYS, prompt, temperature=0.4)
        if not result or not result.get("claim"):
            return []
        child = self.nb.add(
            claim=result["claim"],
            tickers=result.get("tickers") or [],
            thesis_id=str(result.get("thesis_id") or a.thesis_id),
            parent_ids=[a.id, b.id],
            generation=self.nb.cycle,
            questions=["What would refute this combined claim in 90 days?"],
        )
        log.info(f"EVOLVE {child.id} from {a.id}+{b.id}")
        return [child]

    def _archive_digest(self) -> str:
        rows = []
        for h in sorted(self.nb.all(), key=lambda x: x.elo, reverse=True)[:12]:
            rows.append(
                f"- [{h.status} elo={h.elo:.0f} {h.thesis_id}] {h.claim[:140]} "
                f"→ {h.tickers}"
            )
        return "\n".join(rows) or "(empty archive)"


_GEN_SYS = (
    "You are the Generation agent in a Co-Scientist-style research loop for "
    "a paper-trading fund. Output JSON only. Names are the deliverable."
)
_REFLECT_SYS = (
    "You are the Reflection agent (virtual peer reviewer). Be sceptical. "
    "JSON only."
)
_RANK_SYS = (
    "You are the Ranking agent running a pairwise scientific debate. JSON only."
)
_EVOLVE_SYS = (
    "You are the Evolution agent. Improve quality by combining. JSON only."
)


def apply_dcf_reviews(notebook: ResearchNotebook, tickers: list[str]) -> dict[str, DCFResult]:
    """Empirical check: DCF MOS pushes related hypotheses toward supported/refuted."""
    results: dict[str, DCFResult] = {}
    for tk in tickers:
        if "/" in tk or tk in ("GLD", "USO", "XLE", "IAU"):
            continue
        results[tk] = dcf(tk)
        time.sleep(0.15)
    for hyp in notebook.all():
        mos_list = [results[t].mos for t in hyp.tickers
                    if t in results and results[t].ok and results[t].mos is not None]
        if not mos_list:
            for t in hyp.tickers:
                if t in results and not results[t].ok:
                    notebook.add_evidence(
                        hyp.id, "dcf",
                        f"{t}: {results[t].note}",
                    )
            continue
        avg = sum(mos_list) / len(mos_list)
        notebook.add_evidence(
            hyp.id, "dcf",
            f"avg MOS={avg:.0%} across {[t for t in hyp.tickers if t in results]}",
        )
        if avg >= 0.15 and hyp.status != STATUS_REFUTED:
            notebook.add_review(hyp.id, STATUS_SUPPORTED,
                                f"DCF average MOS {avg:.0%} supports the claim.", 7)
        elif avg <= -0.35 and hyp.status != STATUS_SUPPORTED:
            notebook.add_review(hyp.id, STATUS_REFUTED,
                                f"DCF average MOS {avg:.0%} — overvalued vs model.", 6)
    return results
