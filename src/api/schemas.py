from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


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
    latency_ms: Optional[int]
    tokens_used: Optional[int]
    timestamp: datetime
    cached: bool

    class Config:
        from_attributes = True


class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
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
    timestamp: datetime

    class Config:
        from_attributes = True


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
