"""
ScoreCalculator — scores LLM responses 0–100 based on company keyword visibility.

Score components:
  Mention    (30 pts) — keyword present in response
  Placement  (25 pts) — how early in the response (earlier = higher score)
  Selection  (30 pts) — keyword appears in a "chosen / recommended" context
  Sentiment  (15 pts) — positive/negative language near the keyword
"""

from typing import Optional
from src.llm.providers.base import LLMResult

_SELECTION_PHRASES = [
    # English
    "recommend", "best", "top", "leading", "choose", "prefer",
    "suggest", "ideal", "excellent", "outstanding", "number one",
    "#1", "first choice", "go-to", "standout",
    # Danish
    "anbefal", "bedste", "vælg", "foretrækker", "foreslår",
    "fremragende", "foretrukne", "primære", "første valg",
]

_POSITIVE_WORDS = [
    # English
    "great", "good", "excellent", "powerful", "innovative", "advanced",
    "reliable", "fast", "efficient", "quality", "trusted", "strong",
    "robust", "solid", "proven", "leader", "pioneer",
    # Danish
    "god", "fremragende", "pålidelig", "effektiv", "stærk",
    "solid", "betroet", "hurtig",
]

_NEGATIVE_WORDS = [
    # English
    "bad", "poor", "slow", "expensive", "limited", "outdated",
    "weak", "fails", "problem", "issue", "inferior",
    # Danish
    "dårlig", "langsom", "dyr", "begrænset", "svag", "forældet",
]


class ScoreCalculator:
    """Score LLM responses (0–100) for a company keyword's visibility."""

    def calculate(self, result: LLMResult, keyword: Optional[str] = None) -> float:
        """
        Returns a score in [0, 100].
        If the result has an error or no text, returns 0.
        If no keyword is provided, returns a generic quality score.
        """
        if result.error or not result.response_text:
            return 0.0

        text = result.response_text.lower()

        if keyword is None:
            return self._generic_quality_score(text)

        kw = keyword.lower()
        if kw not in text:
            return 0.0

        score = (
            self._mention_score()
            + self._placement_score(text, kw)
            + self._selection_score(text, kw)
            + self._sentiment_score(text, kw)
        )
        return min(100.0, max(0.0, score))

    # ── Component scoring ────────────────────────────────────────────────────

    def _generic_quality_score(self, text: str) -> float:
        length = len(text)
        if length < 50:
            return 20.0
        if length < 300:
            return 40.0
        return 60.0

    def _mention_score(self) -> float:
        return 30.0

    def _placement_score(self, text: str, kw: str) -> float:
        pos = text.find(kw)
        ratio = pos / len(text) if len(text) > 0 else 1.0
        if ratio < 0.10:
            return 25.0
        if ratio < 0.25:
            return 20.0
        if ratio < 0.50:
            return 15.0
        if ratio < 0.75:
            return 10.0
        return 5.0

    def _selection_score(self, text: str, kw: str) -> float:
        pos = text.find(kw)
        window = text[max(0, pos - 250):pos + 250]
        hits = sum(1 for phrase in _SELECTION_PHRASES if phrase in window)
        if hits >= 2:
            return 30.0
        if hits == 1:
            return 15.0
        return 0.0

    def _sentiment_score(self, text: str, kw: str) -> float:
        pos = text.find(kw)
        window = text[max(0, pos - 150):pos + 150]
        pos_count = sum(1 for w in _POSITIVE_WORDS if w in window)
        neg_count = sum(1 for w in _NEGATIVE_WORDS if w in window)
        raw = 7.5 + (pos_count - neg_count) * 2.5
        return max(0.0, min(15.0, raw))
