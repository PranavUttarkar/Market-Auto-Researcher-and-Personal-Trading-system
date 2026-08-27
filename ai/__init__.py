"""AI module — LLM client and web search for autonomous trading agents."""
from .client import AIClient
from .web_search import MarketNewsSearch

__all__ = ["AIClient", "MarketNewsSearch"]
