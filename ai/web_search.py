"""
Web search module powered by Tavily.
Fetches real-time market news and sentiment for trading agents.
"""

import time
import logging
from typing import Optional

log = logging.getLogger(__name__)


class MarketNewsSearch:
    """Searches the web for latest market news using Tavily API."""

    def __init__(self, api_key: str, search_interval: int = 1800):
        from tavily import TavilyClient
        self.client = TavilyClient(api_key=api_key)
        self.search_interval = search_interval   # seconds between searches
        self._cache: dict[str, str] = {}
        self._cache_ts: dict[str, float] = {}
        self._search_count = 0
        log.info("Tavily news search ready")

    # ── Asset → search query mapping ──────────────────────────────

    def search_raw(self, query: str, max_results: int = 5) -> list[dict]:
        """Untargeted retrieval for the research loop (Deep Research step)."""
        result = self.client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=True,
        )
        self._search_count += 1
        rows = []
        for r in result.get("results", []) or []:
            rows.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "") or r.get("snippet", ""),
            })
        return rows

    def get_news(self, symbol: str) -> str:
        """Get latest news summary for a symbol (cached)."""
        now = time.time()
        if symbol in self._cache:
            age = now - self._cache_ts.get(symbol, 0)
            if age < self.search_interval:
                return self._cache[symbol]

        query = f"{symbol} stock OR crypto price analysis today filings news"
        try:
            result = self.client.search(
                query=query,
                search_depth="basic",
                max_results=5,
                include_answer=True,
            )
            self._search_count += 1

            # Build concise summary
            answer = result.get("answer", "")
            headlines = []
            for r in result.get("results", [])[:3]:
                title = r.get("title", "")
                if title:
                    headlines.append(title)

            summary_parts = []
            if answer:
                summary_parts.append(answer[:400])
            if headlines:
                summary_parts.append("Headlines: " + " | ".join(headlines))

            summary = "\n".join(summary_parts) if summary_parts else "No recent news."

            self._cache[symbol] = summary
            self._cache_ts[symbol] = now
            log.info(f"News fetched for {symbol} ({len(summary)} chars)")
            return summary

        except Exception as exc:
            log.warning(f"News search failed for {symbol}: {exc}")
            return self._cache.get(symbol, "News unavailable.")

    @property
    def search_count(self) -> int:
        return self._search_count
