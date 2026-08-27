"""
OpenAI-compatible LLM client for AI trading agents.
Works with TAMU AI Chat API, DeepSeek, OpenAI, and any compatible endpoint.
"""

import json
import time
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


class AIClient:
    """Thin wrapper around an OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str,
                 base_url: str = "https://chat-api.tamu.ai/api",
                 model: str = "protected.gemini-2.5-flash-lite"):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30.0,          # 30s request timeout
            max_retries=2,
        )
        self.model = model
        self._call_count = 0
        self._last_call = 0.0
        self._min_interval = 1.0          # seconds between API calls
        self._errors = 0
        log.info(f"AI client ready | model={model} | base={base_url}")

    # ── public API ────────────────────────────────────────────────

    def analyze(self, system_prompt: str, user_prompt: str,
                temperature: float = 0.3) -> Optional[dict]:
        """Send analysis request and return parsed JSON, or None on failure."""
        self._rate_limit()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=1200,
                stream=False,
            )
            self._call_count += 1
            self._last_call = time.time()

            content = response.choices[0].message.content
            result = self._parse_json(content)
            if result is None:
                log.warning(f"Could not parse AI response as JSON: {content[:200]}")
                self._errors += 1
            return result

        except json.JSONDecodeError as exc:
            log.warning(f"AI JSON decode error: {exc}")
            self._errors += 1
            return None
        except Exception as exc:
            log.error(f"AI API error: {exc}")
            self._errors += 1
            return None

    # ── helpers ────────────────────────────────────────────────────

    def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Try to extract JSON from LLM text (handles markdown fences)."""
        if not text:
            return None
        text = text.strip()
        # Direct JSON
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        # Markdown code fence
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # Last resort: find first { ... }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def error_count(self) -> int:
        return self._errors
