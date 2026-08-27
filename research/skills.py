"""
Accumulating research playbook.

Procedures are callable, not prompt flavor. Successful cycles write
new named steps back into the library so later ticks reuse them.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    description: str
    steps: list[str]
    uses: int = 0
    wins: int = 0
    created_at: float = field(default_factory=time.time)


class SkillLibrary:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.skills: dict[str, Skill] = {}
        self._fns: dict[str, Callable] = {}
        self._seed()
        self.load()

    def _seed(self):
        self.register(
            "storm_questions",
            "Ask 3 sceptical retrieval questions before naming tickers.",
            [
                "What listed entity actually captures the cash flows of the thesis?",
                "What would refute the thesis in 90 days?",
                "Is this a mega-cap default or an operator/supplier?",
            ],
        )
        self.register(
            "crowd_dd_filter",
            "Keep tickers with repeated DD mentions; drop one-off YOLO captions.",
            ["Require >=2 independent posts", "Prefer SA/ValueInvesting over caption-only WSB"],
        )
        self.register(
            "dcf_or_qualitative",
            "Run 2-stage DCF; if pre-FCF, keep as qualitative thesis size only.",
            ["Pull FCF history", "MOS >= 15% can promote", "Negative FCF → do not fake a value"],
        )
        self.register(
            "trend_timeframe",
            "Crypto entries only on 4h/1d Donchian + TS momentum, never 5m.",
            ["Need ADX>=18", "Break prior 20-bar channel", "20 and 60-bar momentum agree"],
        )

    def register(self, name: str, description: str, steps: list[str]):
        if name not in self.skills:
            self.skills[name] = Skill(name=name, description=description, steps=steps)

    def load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for s in raw.get("skills", []):
                sk = Skill(**s)
                self.skills[sk.name] = sk
        except Exception as exc:
            log.debug(f"skill load: {exc}")

    def save(self):
        payload = {"skills": [asdict(s) for s in self.skills.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def mark_use(self, name: str, win: bool = False):
        sk = self.skills.get(name)
        if not sk:
            return
        sk.uses += 1
        if win:
            sk.wins += 1
        self.save()

    def distill(self, name: str, description: str, steps: list[str]):
        """Write a new procedure after a supported hypothesis (library grows)."""
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name.lower())[:40]
        if not safe:
            return
        if safe in self.skills:
            self.mark_use(safe, win=True)
            return
        self.skills[safe] = Skill(name=safe, description=description[:240],
                                  steps=[str(s)[:200] for s in steps[:6]])
        log.info(f"Skill distilled: {safe}")
        self.save()

    def playbook_text(self, limit: int = 6) -> str:
        ranked = sorted(self.skills.values(),
                        key=lambda s: (s.wins, s.uses), reverse=True)
        lines = []
        for s in ranked[:limit]:
            lines.append(f"- {s.name}: {s.description} | steps: {'; '.join(s.steps[:3])}")
        return "\n".join(lines)

    def snapshot(self) -> list[dict]:
        return [asdict(s) for s in
                sorted(self.skills.values(), key=lambda s: s.uses, reverse=True)]
