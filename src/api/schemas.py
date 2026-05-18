from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class AIScoreDimensions(BaseModel):
    """Structured AIScore dimensions for a single provider response."""

    naevnt: float = Field(description="Brand mentioned in response (0–30)")
    valgt: float = Field(description="Brand in selection/recommendation context (0–30)")
    valgbarhed: float = Field(description="How early/prominently the brand appears (0–25)")
    konkurrenceposition: float = Field(description="Sentiment around the brand (0–15)")
    total: float = Field(description="Aggregated AIScore (0–100)")


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=32_000)
    providers: Optional[list[str]] = Field(
        default=None,
        description="Subset of providers to query. Omit to query all active providers.",
        examples=[["openai", "gemini"]],
    )


class LLMResultSchema(BaseModel):
    provider: str
    model: str
    response_text: Optional[str]
    error: Optional[str]
    latency_ms: int
    tokens_used: Optional[int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    cached: bool
    request_id: uuid.UUID


class PromptResponse(BaseModel):
    request_id: uuid.UUID
    tenant_id: uuid.UUID
    prompt: str
    results: list[LLMResultSchema]
    status: str  # complete | partial | error


class LLMResponseRecord(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: str
    model: str
    prompt: str
    response_text: Optional[str]
    error: Optional[str]
    score: Optional[Decimal]
    score_dimensions: Optional[AIScoreDimensions] = None
    latency_ms: Optional[int]
    tokens_used: Optional[int]
    timestamp: datetime
    cached: bool

    class Config:
        from_attributes = True


class TenantCreate(BaseModel):
    name: str
    slug: str
    monthly_revenue_estimate: Optional[Decimal] = Field(
        default=None,
        description="Monthly revenue estimate in DKK — used to convert score changes into revenue impact in alerts",
    )


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    monthly_revenue_estimate: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProviderConfigCreate(BaseModel):
    provider: str
    api_key: Optional[str] = None
    extra_config: dict = Field(default_factory=dict)
    is_active: bool = True


class ProviderConfigResponse(BaseModel):
    id: uuid.UUID
    provider: str
    is_active: bool
    extra_config: dict

    class Config:
        from_attributes = True


class ProviderScore(BaseModel):
    provider: str
    model: Optional[str]
    score: Optional[Decimal]
    score_dimensions: Optional[AIScoreDimensions] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class AggregatedAIScoreResponse(BaseModel):
    """Cross-provider weighted AIScore aggregate for a tenant."""

    naevnt: float
    valgt: float
    valgbarhed: float
    konkurrenceposition: float
    total: float
    providers: dict[str, AIScoreDimensions]


class AlertRecord(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: str
    score_before: Decimal
    score_after: Decimal
    delta: Decimal
    triggered_at: datetime

    class Config:
        from_attributes = True


class RecalculateResponse(BaseModel):
    updated: int
    message: str


# ─────────────────────────────────────────────
# Customer application (pre-qualification gate)
# ─────────────────────────────────────────────

class ApplicationCreate(BaseModel):
    firmanavn: str = Field(..., min_length=1, max_length=255, description="Virksomhedens navn")
    website: str = Field(..., min_length=1, max_length=500, description="Virksomhedens website")
    kontaktperson: str = Field(..., min_length=1, max_length=255, description="Kontaktpersonens fulde navn")
    email: EmailStr = Field(..., description="Kontakt-e-mail")
    telefon: str = Field(..., min_length=1, max_length=50, description="Telefonnummer")
    virksomhedsinfo: str = Field(..., min_length=10, max_length=5000, description="Kort beskrivelse af virksomheden og dens behov")


class ApplicationCreatePublic(BaseModel):
    """Schema for the new public /api/v1/applications endpoint (English field names)."""
    company_name: str = Field(..., min_length=1, max_length=255)
    contact_name: str = Field(..., min_length=1, max_length=255)
    contact_email: EmailStr
    website: str = Field(..., min_length=1, max_length=500)
    country: str = Field(..., min_length=1, max_length=100)
    industry: str = Field(..., min_length=1, max_length=255)
    business_description: str = Field(..., min_length=10, max_length=5000)
    competitors: Optional[str] = Field(default=None, max_length=2000)
    application_goal: str = Field(..., min_length=1, max_length=2000)


class ApplicationRejectRequest(BaseModel):
    rejection_reason: Optional[str] = Field(default=None, max_length=2000)


class StateLogEntry(BaseModel):
    id: uuid.UUID
    from_status: Optional[str]
    to_status: str
    changed_by: Optional[str]
    note: Optional[str]
    changed_at: datetime

    class Config:
        from_attributes = True


class GeneratedQuestion(BaseModel):
    id: str
    question: str
    category: str


class ApplicationResponse(BaseModel):
    id: uuid.UUID
    firmanavn: str
    website: str
    kontaktperson: str
    email: str
    telefon: Optional[str] = None
    virksomhedsinfo: str
    status: str
    notes: Optional[str]
    # New fields from public application endpoint
    country: Optional[str] = None
    industry: Optional[str] = None
    business_description: Optional[str] = None
    competitors: Optional[str] = None
    application_goal: Optional[str] = None
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    rejected_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    # Payment
    payment_url: Optional[str] = None
    stripe_session_id: Optional[str] = None
    # QC loop
    qc_failure_count: int = 0
    has_been_escalated: bool = False
    # Auto-generated questions
    detected_company_type: Optional[str] = None
    company_type_confidence: Optional[float] = None
    generated_questions: Optional[list] = None
    questions_status: str = "pending"
    # Report questions (scoring criteria generated from answered interview)
    report_questions: Optional[list] = None
    report_questions_status: str = "not_started"
    # Scoring data (persisted after IN_PRODUCTION run)
    overall_score: Optional[int] = None
    queries_run: Optional[int] = None
    rank: Optional[int] = None
    # Agent research
    agent_research_status: str = "PENDING"
    agent_website_summary: Optional[str] = None
    agent_business_summary: Optional[str] = None
    agent_target_audience: Optional[str] = None
    agent_products_services: Optional[str] = None
    agent_market_context: Optional[str] = None
    agent_competitor_notes: Optional[str] = None
    agent_fit_recommendation: Optional[str] = None
    agent_fit_reason: Optional[str] = None
    agent_missing_information: Optional[str] = None
    agent_interview_questions: Optional[list] = None
    agent_question_categories: Optional[list] = None
    agent_prompt_directions: Optional[list] = None
    agent_research_summary: Optional[str] = None
    agent_researched_at: Optional[datetime] = None
    agent_research_error: Optional[str] = None
    questions_generated_at: Optional[datetime] = None
    # Per-field AI verification
    agent_verification_status: str = "PENDING"
    agent_verification_results: Optional[dict] = None
    agent_verified_at: Optional[datetime] = None
    # Call transcript (persisted after Whisper + LLM processing in Called stage)
    call_transcript: Optional[str] = None
    call_extracted_data: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    state_logs: list[StateLogEntry] = []

    class Config:
        from_attributes = True


class ApplicationStatusUpdate(BaseModel):
    status: str = Field(..., description="New CRM status for the application")
    note: Optional[str] = Field(default=None, description="Optional note explaining the transition")


class GeneratePaymentLinkRequest(BaseModel):
    amount_dkk: int = Field(..., gt=0, le=500000, description="Amount in DKK to charge (e.g. 4995 for 4.995 kr., max 500000 DKK)")
    send_email: bool = Field(default=True, description="Whether to send the payment link to the customer's email")


class PaymentLinkResponse(BaseModel):
    application_id: uuid.UUID
    payment_url: str
    stripe_session_id: str
    amount_dkk: int
    email_sent: bool


class QCResultSubmit(BaseModel):
    passed: bool = Field(..., description="True if QC passed, False if it failed")
    notes: Optional[str] = Field(default=None, description="QC reviewer notes (required on failure)")


class ManualCorrectionRequest(BaseModel):
    note: Optional[str] = Field(default=None, description="Dennis' note on what was corrected")


class ScoringDataUpdate(BaseModel):
    overall_score: int = Field(..., ge=0, le=100, description="Weighted aggregate AIScore (0–100)")
    queries_run: int = Field(..., ge=0, description="Total LLM queries run for this analysis")
    rank: int = Field(..., ge=1, description="Brand position in LLM responses")


# ─────────────────────────────────────────────
# AISelect password reset
# ─────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address registered with AISelect")


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, description="Reset token from the email link")
    new_password: str = Field(..., min_length=8, max_length=128, description="New password (min 8 characters)")


class PasswordResetResponse(BaseModel):
    message: str
