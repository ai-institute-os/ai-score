"""Unit tests for the cross-provider AIScore aggregator."""

import pytest
from src.scoring.calculator import AIScore
from src.scoring.aggregator import aggregate_scores, AggregatedAIScore, _PROVIDER_WEIGHTS


def _score(naevnt=30.0, valgt=15.0, valgbarhed=20.0, konkurrenceposition=7.5, total=72.5) -> AIScore:
    return AIScore(naevnt=naevnt, valgt=valgt, valgbarhed=valgbarhed,
                   konkurrenceposition=konkurrenceposition, total=total)


class TestAggregateScores:
    def test_returns_none_for_empty_input(self):
        assert aggregate_scores({}) is None

    def test_returns_none_when_all_scores_zero(self):
        scores = {
            "openai": AIScore.zero(),
            "gemini": AIScore.zero(),
        }
        assert aggregate_scores(scores) is None

    def test_single_provider_returns_its_score(self):
        s = _score(total=72.5)
        result = aggregate_scores({"openai": s})
        assert result is not None
        assert result.total == 72.5

    def test_all_known_providers_weighted_correctly(self):
        # All providers same score → aggregate should equal that score
        uniform = _score(naevnt=30.0, valgt=30.0, valgbarhed=25.0, konkurrenceposition=15.0, total=100.0)
        scores = {p: uniform for p in _PROVIDER_WEIGHTS}
        result = aggregate_scores(scores)
        assert result is not None
        assert abs(result.total - 100.0) < 0.01

    def test_weights_sum_to_one_after_normalization(self):
        # Only two providers present; their relative weights should be used
        scores = {
            "openai": _score(total=100.0),
            "gemini": AIScore.zero(),  # excluded
        }
        result = aggregate_scores(scores)
        assert result is not None
        assert result.total == 100.0  # only openai contributed

    def test_higher_weight_provider_dominates(self):
        # openai weight (0.30) > claude weight (0.15)
        scores = {
            "openai": _score(total=100.0),
            "claude": _score(total=0.1),  # effectively zero contribution
        }
        result = aggregate_scores(scores)
        assert result is not None
        # openai has higher weight so result should be closer to 100 than 50
        assert result.total > 60.0

    def test_result_contains_all_provider_scores(self):
        scores = {
            "openai": _score(total=80.0),
            "gemini": _score(total=60.0),
        }
        result = aggregate_scores(scores)
        assert result is not None
        # providers dict includes zero-score entries from original input
        assert "openai" in result.providers
        assert "gemini" in result.providers

    def test_unknown_provider_uses_default_weight(self):
        scores = {
            "custom_provider": _score(total=50.0),
        }
        result = aggregate_scores(scores)
        assert result is not None
        assert result.total == 50.0

    def test_dimensions_are_weighted_averages(self):
        s1 = AIScore(naevnt=30.0, valgt=30.0, valgbarhed=25.0, konkurrenceposition=15.0, total=100.0)
        s2 = AIScore(naevnt=0.0, valgt=0.0, valgbarhed=0.0, konkurrenceposition=0.0, total=0.0)
        # s2 excluded (total=0), so all dimensions should come from s1
        result = aggregate_scores({"openai": s1, "gemini": s2})
        assert result is not None
        assert result.naevnt == 30.0
        assert result.valgt == 30.0

    def test_as_dict_serialization(self):
        scores = {"openai": _score(total=75.0)}
        result = aggregate_scores(scores)
        assert result is not None
        d = result.as_dict()
        assert "total" in d
        assert "providers" in d
        assert "naevnt" in d
