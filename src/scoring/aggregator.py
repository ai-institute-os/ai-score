"""
Cross-provider AIScore aggregator.

Combines AIScore results from multiple LLM providers into a single
weighted aggregate that represents the company's overall AI positioning.

Provider weights reflect relative market reach and query volume:
  openai      30%  — highest volume, GPT models dominant in enterprise tools
  perplexity  30%  — search-adjacent AI with high purchase-intent context
  gemini      25%  — growing Google ecosystem reach
  copilot     15%  — Microsoft enterprise niche
"""

import dataclasses
from typing import Optional

from src.scoring.calculator import AIScore

_PROVIDER_WEIGHTS: dict[str, float] = {
    "openai": 0.30,
    "perplexity": 0.30,
    "gemini": 0.25,
    "copilot": 0.15,
}

_DEFAULT_WEIGHT = 0.25  # fallback for unknown providers


@dataclasses.dataclass
class AggregatedAIScore:
    """Weighted aggregate of AIScore across all providers."""

    providers: dict[str, AIScore]
    naevnt: float
    valgt: float
    valgbarhed: float
    konkurrenceposition: float
    total: float

    def as_dict(self) -> dict:
        return {
            "naevnt": self.naevnt,
            "valgt": self.valgt,
            "valgbarhed": self.valgbarhed,
            "konkurrenceposition": self.konkurrenceposition,
            "total": self.total,
            "providers": {k: v.as_dict() for k, v in self.providers.items()},
        }


def aggregate_scores(provider_scores: dict[str, AIScore]) -> Optional[AggregatedAIScore]:
    """
    Compute a weighted average AIScore across providers.

    Providers with zero total score are excluded from aggregation so that
    missing API keys or errors don't drag the aggregate down artificially.
    Returns None if no scored providers remain after filtering.
    """
    scored = {p: s for p, s in provider_scores.items() if s.total > 0}
    if not scored:
        return None

    raw_weights = {p: _PROVIDER_WEIGHTS.get(p, _DEFAULT_WEIGHT) for p in scored}
    total_weight = sum(raw_weights.values())
    weights = {p: w / total_weight for p, w in raw_weights.items()}

    def _wavg(field: str) -> float:
        return sum(getattr(score, field) * weights[p] for p, score in scored.items())

    return AggregatedAIScore(
        providers=provider_scores,
        naevnt=round(_wavg("naevnt"), 2),
        valgt=round(_wavg("valgt"), 2),
        valgbarhed=round(_wavg("valgbarhed"), 2),
        konkurrenceposition=round(_wavg("konkurrenceposition"), 2),
        total=round(_wavg("total"), 2),
    )
