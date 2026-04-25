import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from sqlalchemy import (
    UUID, Boolean, Integer, Numeric, String, Text, TIMESTAMP, ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.connection import Base


class SubscriptionTier(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"


class CustomerApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CALLED = "CALLED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    IN_PRODUCTION = "IN_PRODUCTION"
    QC_REVIEW = "QC_REVIEW"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    ESCALATED = "ESCALATED"
    RETRY = "RETRY"
    CANCELLED = "CANCELLED"
    READY_FOR_REVIEW_CALL = "READY_FOR_REVIEW_CALL"


# Valid state transitions: current_state -> set of allowed next states
VALID_TRANSITIONS: dict[CustomerApplicationStatus, set[CustomerApplicationStatus]] = {
    CustomerApplicationStatus.APPLIED: {CustomerApplicationStatus.UNDER_REVIEW, CustomerApplicationStatus.REJECTED},
    CustomerApplicationStatus.UNDER_REVIEW: {CustomerApplicationStatus.APPROVED, CustomerApplicationStatus.REJECTED},
    CustomerApplicationStatus.APPROVED: {CustomerApplicationStatus.CALLED},
    # CALLED → AWAITING_PAYMENT (normal flow) or APPROVED (Calendly cancellation)
    CustomerApplicationStatus.CALLED: {CustomerApplicationStatus.AWAITING_PAYMENT, CustomerApplicationStatus.APPROVED},
    CustomerApplicationStatus.AWAITING_PAYMENT: {CustomerApplicationStatus.PAID},
    CustomerApplicationStatus.PAID: {CustomerApplicationStatus.IN_PRODUCTION},
    CustomerApplicationStatus.IN_PRODUCTION: {CustomerApplicationStatus.QC_REVIEW},
    CustomerApplicationStatus.QC_REVIEW: {CustomerApplicationStatus.QC_PASSED, CustomerApplicationStatus.QC_FAILED},
    CustomerApplicationStatus.QC_PASSED: {CustomerApplicationStatus.READY_FOR_REVIEW_CALL},
    # QC_FAILED: auto-retry (< 3 failures) goes back to IN_PRODUCTION;
    # after 3 failures, system escalates (ESCALATED). Managed by qc_result endpoint.
    CustomerApplicationStatus.QC_FAILED: {CustomerApplicationStatus.IN_PRODUCTION, CustomerApplicationStatus.ESCALATED},
    # ESCALATED: Dennis makes manual correction → RETRY (back into IN_PRODUCTION cycle)
    CustomerApplicationStatus.ESCALATED: {CustomerApplicationStatus.RETRY},
    CustomerApplicationStatus.RETRY: {CustomerApplicationStatus.IN_PRODUCTION},
    CustomerApplicationStatus.READY_FOR_REVIEW_CALL: set(),
    CustomerApplicationStatus.CANCELLED: set(),
    CustomerApplicationStatus.REJECTED: set(),
}


class ScoreAlert(Base):
    __tablename__ = "score_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    score_before: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    score_after: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # Optional monthly revenue estimate (DKK) used to convert score changes into revenue impact
    monthly_revenue_estimate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    provider_configs: Mapped[list["TenantProviderConfig"]] = relationship(back_populates="tenant")
    llm_responses: Mapped[list["LLMResponse"]] = relationship(back_populates="tenant")


class TenantProviderConfig(Base):
    __tablename__ = "tenant_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(Text)
    extra_config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship(back_populates="provider_configs")


class LLMResponse(Base):
    __tablename__ = "llm_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    response_text: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    # Structured AIScore dimensions stored as JSON for queryability without schema migration per dimension
    score_dimensions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    cached: Mapped[bool] = mapped_column(Boolean, default=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="llm_responses")


class PromptRequest(Base):
    __tablename__ = "prompt_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


class CustomerApplication(Base):
    __tablename__ = "customer_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firmanavn: Mapped[str] = mapped_column(String, nullable=False)
    website: Mapped[str] = mapped_column(String, nullable=False)
    kontaktperson: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    telefon: Mapped[str] = mapped_column(String, nullable=False)
    virksomhedsinfo: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CustomerApplicationStatus] = mapped_column(
        SAEnum(CustomerApplicationStatus, name="customer_application_status"),
        nullable=False,
        default=CustomerApplicationStatus.APPLIED,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Payment link fields (populated when payment link is generated)
    stripe_session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payment_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # QC loop tracking: counts failures in the current cycle; resets after manual correction
    qc_failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # True after the first escalation (manual correction round); next 3 failures → CANCELLED
    has_been_escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Calendly booking URI — set when invitee.created fires, cleared on cancellation
    calendly_event_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    state_logs: Mapped[list["CustomerApplicationStateLog"]] = relationship(
        back_populates="application", order_by="CustomerApplicationStateLog.changed_at"
    )


class CustomerApplicationStateLog(Base):
    __tablename__ = "customer_application_state_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_applications.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[Optional[CustomerApplicationStatus]] = mapped_column(
        SAEnum(CustomerApplicationStatus, name="customer_application_status"), nullable=True
    )
    to_status: Mapped[CustomerApplicationStatus] = mapped_column(
        SAEnum(CustomerApplicationStatus, name="customer_application_status"), nullable=False
    )
    changed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)

    application: Mapped["CustomerApplication"] = relationship(back_populates="state_logs")


class AISelectSubscription(Base):
    __tablename__ = "aiselect_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String, nullable=False)

    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)

    tier: Mapped[SubscriptionTier] = mapped_column(
        SAEnum(SubscriptionTier, name="subscription_tier"),
        nullable=False,
        default=SubscriptionTier.FREE,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus, name="subscription_status"),
        nullable=False,
        default=SubscriptionStatus.INCOMPLETE,
    )

    current_period_start: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
