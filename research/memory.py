"""
Memory stream with retrieval.

Each observation (evidence, critique, crowd hit, DCF) is appended.
Retrieve scores recency × relevance × importance and returns the top-k
into later generate/critique steps — the loop conditions on what it
remembers, not a fresh empty prompt.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field


_TOKEN = re.compile(r"[A-Z]{2,10}|[a-z]{3,}")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "")}


@dataclass
class Memory:
    text: str
    kind: str
    importance: float = 5.0
    ts: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)


class MemoryStream:
    def __init__(self, decay_hours: float = 72.0, cap: int = 400):
        self.decay_hours = decay_hours
        self.cap = cap
        self.items: list[Memory] = []

    def add(self, text: str, kind: str, importance: float = 5.0,
            tags: list[str] | None = None):
        if not text:
            return
        self.items.append(Memory(
            text=text[:600], kind=kind,
            importance=float(min(10.0, max(1.0, importance))),
            tags=tags or [],
        ))
        if len(self.items) > self.cap:
            self.items = self.items[-self.cap:]

    def retrieve(self, query: str, k: int = 8) -> list[Memory]:
        q = _tokens(query)
        now = time.time()
        scored = []
        for m in self.items:
            recency = math.exp(-(now - m.last_access) / (self.decay_hours * 3600.0))
            mt = _tokens(m.text) | {t.lower() for t in m.tags}
            if not q or not mt:
                rel = 0.15
            else:
                rel = len(q & mt) / max(1, len(q))
            score = recency * (0.2 + 0.8 * rel) * (m.importance / 10.0)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, m in scored[:k]:
            if score <= 0:
                continue
            m.last_access = now
            out.append(m)
        return out

    def format(self, query: str, k: int = 8) -> str:
        hits = self.retrieve(query, k=k)
        if not hits:
            return "(no retrieved memories)"
        lines = [f"[{m.kind}] {m.text}" for m in hits]
        return "\n".join(lines)
