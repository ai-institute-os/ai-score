"""
ScoreCalculator — scores LLM responses 0–100 for company keyword visibility.

Score dimensions (mapped to the AIScore output format):
  naevnt           (30 pts) — keyword present in response (nævnt)
  valgt            (30 pts) — keyword appears in a recommended/chosen context (valgt)
  valgbarhed       (25 pts) — how early/prominently mentioned (valgbarhed)
  konkurrenceposition (15 pts) — sentiment around the keyword (konkurrenceposition)
"""

import dataclasses
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


@dataclasses.dataclass
class AIScore:
    """Structured AIScore with named dimensions for InsideAI positioning analytics."""

    naevnt: float            # Was brand mentioned? (0–30)
    valgt: float             # Was brand recommended/chosen? (0–30)
    valgbarhed: float        # How prominently placed? (0–25)
    konkurrenceposition: float  # Sentiment around brand (0–15)
    total: float             # Aggregated score (0–100)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def zero(cls) -> "AIScore":
        return cls(naevnt=0.0, valgt=0.0, valgbarhed=0.0, konkurrenceposition=0.0, total=0.0)


class ScoreCalculator:
    """Score LLM responses (0–100) for a company keyword's visibility."""

    def calculate(self, result: LLMResult, keyword: Optional[str] = None) -> AIScore:
        """
        Returns an AIScore in [0, 100].
        If the result has an error or no text, returns AIScore.zero().
        If no keyword is provided, returns a generic quality score with total only.
        """
        if result.error or not result.response_text:
            return AIScore.zero()

        text = result.response_text.lower()

        if keyword is None:
            generic = self._generic_quality_score(text)
            return AIScore(
                naevnt=0.0,
                valgt=0.0,
                valgbarhed=0.0,
                konkurrenceposition=0.0,
                total=generic,
            )

        kw = keyword.lower()
        if kw not in text:
            return AIScore.zero()

        naevnt = self._naevnt_score()
        valgt = self._valgt_score(text, kw)
        valgbarhed = self._valgbarhed_score(text, kw)
        konkurrenceposition = self._konkurrenceposition_score(text, kw)
        total = min(100.0, max(0.0, naevnt + valgt + valgbarhed + konkurrenceposition))

        return AIScore(
            naevnt=naevnt,
            valgt=valgt,
            valgbarhed=valgbarhed,
            konkurrenceposition=konkurrenceposition,
            total=total,
        )

    # ── Dimension scoring ────────────────────────────────────────────────────

    def _generic_quality_score(self, text: str) -> float:
        length = len(text)
        if length < 50:
            return 20.0
        if length < 300:
            return 40.0
        return 60.0

    def _naevnt_score(self) -> float:
        """Brand is present in response — flat 30 pts."""
        return 30.0

    def _valgt_score(self, text: str, kw: str) -> float:
        """Brand appears near recommendation/selection phrases."""
        pos = text.find(kw)
        window = text[max(0, pos - 250):pos + 250]
        hits = sum(1 for phrase in _SELECTION_PHRASES if phrase in window)
        if hits >= 2:
            return 30.0
        if hits == 1:
            return 15.0
        return 0.0

    def _valgbarhed_score(self, text: str, kw: str) -> float:
        """How early in the response the brand appears (earlier = more selectable)."""
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

    def _konkurrenceposition_score(self, text: str, kw: str) -> float:
        """Sentiment language near the brand keyword."""
        pos = text.find(kw)
        window = text[max(0, pos - 150):pos + 150]
        pos_count = sum(1 for w in _POSITIVE_WORDS if w in window)
        neg_count = sum(1 for w in _NEGATIVE_WORDS if w in window)
        raw = 7.5 + (pos_count - neg_count) * 2.5
        return max(0.0, min(15.0, raw))
