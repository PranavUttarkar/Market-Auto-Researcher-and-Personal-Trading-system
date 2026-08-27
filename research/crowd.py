"""
Crowd pull: Reddit WSB / DD / value boards.

Public JSON first (no OAuth). Tavily `site:reddit.com` as fallback when
Reddit 403s datacenter IPs. Tickers are extracted, not assumed.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

SUBREDDITS = (
    "wallstreetbets",
    "stocks",
    "investing",
    "SecurityAnalysis",
    "ValueInvesting",
    "StockMarket",
)

# Common English / WSB slang that is not a ticker.
STOP = {
    "A", "I", "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN",
    "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "HIS", "HOW", "ITS", "MAY",
    "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID", "GET", "HIM",
    "LET", "PUT", "SAY", "SHE", "TOO", "USE", "CEO", "CFO", "IPO", "ETF",
    "ATH", "ATL", "IMO", "IMO", "TBH", "IMO", "WSB", "DD", "YOLO", "HODL",
    "FOMO", "FUD", "ATH", "EOD", "EOW", "YTD", "EPS", "PE", "PS", "ROI",
    "USA", "USD", "GDP", "CPI", "FED", "SEC", "FDA", "AI", "GPU", "CPU",
    "LLM", "API", "PDF", "HTTP", "JSON", "OPEN", "HIGH", "LOW", "CLOSE",
    "LONG", "SHORT", "CALL", "PUTS", "PUT", "CALLS", "BULL", "BEAR",
    "MOON", "DUMP", "PUMP", "HOLD", "SELL", "BUY", "TRIM", "ADD", "RIDE",
    "THIS", "THAT", "WITH", "FROM", "HAVE", "BEEN", "WILL", "JUST", "LIKE",
    "WHAT", "WHEN", "YOUR", "THEY", "THEM", "THAN", "THEN", "ALSO", "VERY",
    "INTO", "OVER", "ONLY", "SOME", "MORE", "MOST", "SUCH", "WEEK", "YEAR",
    "TODAY", "NEXT", "LAST", "GOOD", "BEST", "HUGE", "BIG", "REAL", "TRUE",
    "PR", "IR", "Q1", "Q2", "Q3", "Q4", "FY", "PT", "AH", "PM", "AM",
    "EDIT", "TLDR", "ELI5", "OP", "MOD", "BOT", "LINK", "HTTP", "WWW",
    "OR", "IF", "ON", "IN", "TO", "OF", "IT", "IS", "BE", "AS", "AT", "BY",
    "NO", "SO", "UP", "DO", "AN", "MY", "WE", "ME", "HE",
}

TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b|(?<![A-Z])\b([A-Z]{2,5})\b")


@dataclass
class CrowdHit:
    ticker: str
    mentions: int
    sources: list[str] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)


class CrowdScanner:
    def __init__(self, tavily=None, timeout: float = 12.0):
        self.tavily = tavily
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "crypto-trader-research/1.0 (paper; name-id only)",
            "Accept": "application/json",
        })

    def scan(self) -> list[CrowdHit]:
        counts: Counter[str] = Counter()
        sources: dict[str, list[str]] = {}
        snippets: dict[str, list[str]] = {}

        for sub in SUBREDDITS:
            posts = self._hot(sub) + self._dd_search(sub)
            for post in posts:
                title = post.get("title", "")
                body = post.get("selftext", "")[:1500]
                permalink = post.get("permalink", "")
                url = f"https://reddit.com{permalink}" if permalink else ""
                text = f"{title}\n{body}"
                for tk in extract_tickers(text):
                    counts[tk] += 1
                    sources.setdefault(tk, [])
                    if url and url not in sources[tk]:
                        sources[tk].append(url)
                    snippets.setdefault(tk, [])
                    if title and title not in snippets[tk]:
                        snippets[tk].append(title[:180])

            time.sleep(0.8)

        if not counts and self.tavily:
            self._tavily_fallback(counts, sources, snippets)

        hits = []
        for tk, n in counts.most_common(40):
            hits.append(CrowdHit(
                ticker=tk,
                mentions=n,
                sources=sources.get(tk, [])[:5],
                snippets=snippets.get(tk, [])[:3],
            ))
        log.info(f"Crowd scan | {len(hits)} tickers | top={hits[:8]}")
        return hits

    def _hot(self, sub: str) -> list[dict]:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=40"
        return self._listing(url)

    def _dd_search(self, sub: str) -> list[dict]:
        if sub not in ("wallstreetbets", "SecurityAnalysis", "ValueInvesting"):
            return []
        url = (
            f"https://www.reddit.com/r/{sub}/search.json"
            f"?q=flair%3ADD&restrict_sr=1&sort=new&limit=20"
        )
        return self._listing(url)

    def _listing(self, url: str) -> list[dict]:
        try:
            r = self._session.get(url, timeout=self.timeout)
            if r.status_code != 200:
                log.debug(f"Reddit {r.status_code} {url}")
                return []
            children = r.json().get("data", {}).get("children", [])
            return [c.get("data", {}) for c in children if isinstance(c, dict)]
        except Exception as exc:
            log.debug(f"Reddit fetch failed: {exc}")
            return []

    def _tavily_fallback(self, counts, sources, snippets):
        queries = [
            "site:reddit.com/r/wallstreetbets due diligence stock ticker",
            "site:reddit.com/r/SecurityAnalysis undervalued stock DD",
            "site:reddit.com/r/ValueInvesting DCF thesis",
        ]
        for q in queries:
            try:
                result = self.tavily.search_raw(q, max_results=5)
            except Exception:
                continue
            for row in result:
                text = f"{row.get('title','')} {row.get('content','')}"
                url = row.get("url", "")
                for tk in extract_tickers(text):
                    counts[tk] += 1
                    sources.setdefault(tk, [])
                    if url:
                        sources[tk].append(url)
                    snippets.setdefault(tk, []).append(row.get("title", "")[:180])


def extract_tickers(text: str) -> list[str]:
    found = []
    for m in TICKER_RE.finditer(text.upper()):
        tk = m.group(1) or m.group(2)
        if not tk or tk in STOP or not tk.isalpha():
            continue
        found.append(tk)
    return found
