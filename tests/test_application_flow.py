"""
Tests for the new public application flow:
  POST /api/v1/applications           → APPLIED → UNDER_REVIEW (auto)
  POST /api/v1/admin/applications/:id/approve → APPROVED
  POST /api/v1/admin/applications/:id/reject  → REJECTED
"""
import pytest
from unittest.mock import AsyncMock, patch
from src.api.schemas import ApplicationCreatePublic, ApplicationRejectRequest
from src.db.models import CustomerApplicationStatus


def test_application_create_public_schema_validates_required_fields():
    """ApplicationCreatePublic must accept all required fields."""
    body = ApplicationCreatePublic(
        company_name="Test ApS",
        contact_name="Jane Doe",
        contact_email="jane@example.com",
        website="https://example.com",
        country="Denmark",
        industry="SaaS",
        business_description="We build software for enterprises worldwide.",
    )
    assert body.company_name == "Test ApS"
    assert body.competitors is None
    assert body.application_goal is None


def test_application_create_public_schema_optional_fields():
    """Optional fields competitors and application_goal are accepted."""
    body = ApplicationCreatePublic(
        company_name="Test ApS",
        contact_name="Jane Doe",
        contact_email="jane@example.com",
        website="https://example.com",
        country="Denmark",
        industry="SaaS",
        business_description="We build software for enterprises worldwide.",
        competitors="CompetitorA, CompetitorB",
        application_goal="Improve AI visibility",
    )
    assert body.competitors == "CompetitorA, CompetitorB"
    assert body.application_goal == "Improve AI visibility"


def test_application_create_public_schema_rejects_missing_required():
    """Missing required fields raise ValidationError."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ApplicationCreatePublic(
            company_name="Test ApS",
            # contact_name missing
            contact_email="jane@example.com",
            website="https://example.com",
            country="Denmark",
            industry="SaaS",
            business_description="We build software for enterprises worldwide.",
        )


def test_application_reject_request_allows_empty_reason():
    """ApplicationRejectRequest accepts no reason."""
    body = ApplicationRejectRequest()
    assert body.rejection_reason is None


def test_valid_transitions_include_review():
    """UNDER_REVIEW → APPROVED and UNDER_REVIEW → REJECTED are valid."""
    from src.db.models import VALID_TRANSITIONS
    allowed = VALID_TRANSITIONS[CustomerApplicationStatus.UNDER_REVIEW]
    assert CustomerApplicationStatus.APPROVED in allowed
    assert CustomerApplicationStatus.REJECTED in allowed
