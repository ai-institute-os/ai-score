"""Unit tests for the Phase 2 scoring pipeline."""

import uuid
import pytest
from datetime import datetime

from src.llm.providers.base import LLMResult
from src.scoring.calculator import AIScore, ScoreCalculator
from src.scoring.alert_emailer import render_alert_email


def _make_result(
    response_text: str | None = None,
    error: str | None = None,
    provider: str = "openai",
    model: str = "gpt-4o",
) -> LLMResult:
    return LLMResult(
        provider=provider,
        model=model,
        prompt="Which company should I use for AI scoring?",
        response_text=response_text,
        error=error,
        latency_ms=200,
        tokens_used=100,
        prompt_tokens=20,
        completion_tokens=80,
    )


class TestAIScoreDataclass:
    def test_zero_factory(self):
        score = AIScore.zero()
        assert score.total == 0.0
        assert score.naevnt == 0.0
        assert score.valgt == 0.0
        assert score.valgbarhed == 0.0
        assert score.konkurrenceposition == 0.0

    def test_as_dict_has_all_fields(self):
        score = AIScore(naevnt=30.0, valgt=15.0, valgbarhed=20.0, konkurrenceposition=7.5, total=72.5)
        d = score.as_dict()
        assert set(d.keys()) == {"naevnt", "valgt", "valgbarhed", "konkurrenceposition", "total"}

    def test_total_roundtrip(self):
        score = AIScore(naevnt=30.0, valgt=30.0, valgbarhed=25.0, konkurrenceposition=15.0, total=100.0)
        d = score.as_dict()
        restored = AIScore(**d)
        assert restored.total == 100.0


class TestScoreCalculatorErrors:
    def test_error_result_scores_zero(self):
        calc = ScoreCalculator()
        result = _make_result(error="timeout", response_text=None)
        score = calc.calculate(result)
        assert score.total == 0.0
        assert isinstance(score, AIScore)

    def test_empty_response_scores_zero(self):
        calc = ScoreCalculator()
        result = _make_result(response_text=None)
        score = calc.calculate(result)
        assert score.total == 0.0

    def test_keyword_not_in_response_scores_zero(self):
        calc = ScoreCalculator()
        result = _make_result(response_text="This response talks about other companies entirely.")
        score = calc.calculate(result, keyword="AcmeCorp")
        assert score.total == 0.0


class TestScoreCalculatorGenericQuality:
    def test_short_response_scores_low(self):
        calc = ScoreCalculator()
        result = _make_result(response_text="Hi.")
        score = calc.calculate(result, keyword=None)
        assert score.total == 20.0

    def test_medium_response_scores_mid(self):
        calc = ScoreCalculator()
        result = _make_result(response_text="x" * 100)
        score = calc.calculate(result, keyword=None)
        assert score.total == 40.0

    def test_long_response_scores_high(self):
        calc = ScoreCalculator()
        result = _make_result(response_text="x" * 500)
        score = calc.calculate(result, keyword=None)
        assert score.total == 60.0

    def test_generic_quality_has_zero_dimensions(self):
        calc = ScoreCalculator()
        result = _make_result(response_text="x" * 500)
        score = calc.calculate(result, keyword=None)
        assert score.naevnt == 0.0
        assert score.valgt == 0.0
        assert score.valgbarhed == 0.0
        assert score.konkurrenceposition == 0.0


class TestScoreCalculatorDimensions:
    def test_naevnt_earns_base_points(self):
        calc = ScoreCalculator()
        result = _make_result(
            response_text="You should consider AcmeCorp for your needs." + " filler " * 50
        )
        score = calc.calculate(result, keyword="AcmeCorp")
        assert score.naevnt == 30.0

    def test_valgt_higher_when_recommended(self):
        calc = ScoreCalculator()
        bare = "AcmeCorp exists in this market alongside others."
        selected = "We strongly recommend AcmeCorp as the best choice for your needs."
        bare_score = calc.calculate(_make_result(response_text=bare), keyword="AcmeCorp")
        sel_score = calc.calculate(_make_result(response_text=selected), keyword="AcmeCorp")
        assert sel_score.valgt > bare_score.valgt

    def test_valgbarhed_higher_for_early_mention(self):
        calc = ScoreCalculator()
        early_text = "AcmeCorp is a company. " + "Other stuff. " * 20
        late_text = "Other stuff. " * 20 + "AcmeCorp is mentioned here."
        early_score = calc.calculate(_make_result(response_text=early_text), keyword="AcmeCorp")
        late_score = calc.calculate(_make_result(response_text=late_text), keyword="AcmeCorp")
        assert early_score.valgbarhed > late_score.valgbarhed

    def test_konkurrenceposition_present(self):
        calc = ScoreCalculator()
        result = _make_result(response_text="AcmeCorp is excellent and reliable.")
        score = calc.calculate(result, keyword="AcmeCorp")
        assert score.konkurrenceposition > 0.0

    def test_total_bounded_0_to_100(self):
        calc = ScoreCalculator()
        text = (
            "AcmeCorp is the best leading recommended top excellent reliable "
            "powerful innovative pioneer trusted quality solid robust proven "
            "great good advanced efficient fast standout go-to first choice."
        )
        result = _make_result(response_text=text)
        score = calc.calculate(result, keyword="AcmeCorp")
        assert 0.0 <= score.total <= 100.0

    def test_case_insensitive_matching(self):
        calc = ScoreCalculator()
        result = _make_result(response_text="ACMECORP is highly recommended.")
        score = calc.calculate(result, keyword="AcmeCorp")
        assert score.total > 0


class TestAlertEmailer:
    def test_render_returns_html(self):
        html = render_alert_email(
            company_name="TestCo",
            provider="openai",
            score_before=50.0,
            score_after=30.0,
            delta=-20.0,
            triggered_at=datetime(2026, 4, 22, 12, 0),
        )
        assert "<!DOCTYPE html>" in html

    def test_template_variables_substituted(self):
        html = render_alert_email(
            company_name="Acme A/S",
            provider="gemini",
            score_before=40.0,
            score_after=65.0,
            delta=25.0,
            triggered_at=datetime(2026, 4, 22, 9, 30),
            contact_url="https://example.com/dashboard",
            contact_email="test@example.com",
            unsubscribe_url="https://example.com/unsubscribe",
        )
        assert "Acme A/S" in html
        assert "Gemini" in html
        assert "https://example.com/dashboard" in html
        assert "test@example.com" in html
        assert "{{" not in html

    def test_no_raw_scores_in_alert_body(self):
        html = render_alert_email(
            company_name="Co",
            provider="openai",
            score_before=60.0,
            score_after=20.0,
            delta=-40.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        # Design rule: must NOT say "score fell from X to Y" — no raw score phrase
        assert "fra 60.0 til 20.0" not in html
        assert "60.0 til 20.0" not in html
        assert "scoren er faldet fra" not in html.lower()
        assert "score er faldet fra" not in html.lower()

    def test_consequence_formulation_in_alert(self):
        html = render_alert_email(
            company_name="Co",
            provider="openai",
            score_before=60.0,
            score_after=20.0,
            delta=-40.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        # Should use consequence language (vælges, synlighed, etc.) not raw scores
        assert "vælges" in html or "synlighed" in html or "anbefales" in html

    def test_urgency_hoj_for_large_delta(self):
        html = render_alert_email(
            company_name="Co",
            provider="openai",
            score_before=60.0,
            score_after=20.0,
            delta=-40.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        assert "HOJ" in html

    def test_urgency_middel_for_medium_delta(self):
        html = render_alert_email(
            company_name="Co",
            provider="openai",
            score_before=50.0,
            score_after=35.0,
            delta=-15.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        assert "MIDDEL" in html

    def test_urgency_badge_color_changes_per_urgency(self):
        hoj_html = render_alert_email(
            company_name="Co", provider="openai",
            score_before=60.0, score_after=20.0, delta=-40.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        middel_html = render_alert_email(
            company_name="Co", provider="openai",
            score_before=50.0, score_after=35.0, delta=-15.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        assert "#b91c1c" in hoj_html
        assert "#b45309" in middel_html

    def test_direction_fallen_for_negative_delta(self):
        html = render_alert_email(
            company_name="Co", provider="openai",
            score_before=50.0, score_after=30.0, delta=-20.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        assert "faldet" in html

    def test_direction_risen_for_positive_delta(self):
        html = render_alert_email(
            company_name="Co", provider="openai",
            score_before=30.0, score_after=50.0, delta=20.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
        )
        assert "steget" in html

    def test_revenue_impact_shown_when_configured(self):
        html = render_alert_email(
            company_name="BigCo",
            provider="openai",
            score_before=80.0,
            score_after=40.0,
            delta=-40.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
            monthly_revenue_estimate=500_000.0,
        )
        assert "kr." in html

    def test_no_revenue_impact_without_estimate(self):
        html = render_alert_email(
            company_name="Co",
            provider="openai",
            score_before=50.0,
            score_after=30.0,
            delta=-20.0,
            triggered_at=datetime(2026, 4, 22, 10, 0),
            monthly_revenue_estimate=None,
        )
        # Should still render without error
        assert "<!DOCTYPE html>" in html
