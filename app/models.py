from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Route = Literal["rule", "heuristic", "llm", "confirm"]
PlanType = Literal["prepaid", "postpaid"]


class IntentPlan(BaseModel):
    intent: str
    slots: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    confirm: bool = False
    source: Route = "rule"


class Trace(BaseModel):
    route: Route
    intent: str
    matched_code: str | None = None
    confirm_required: bool = False
    forbidden: bool = False
    tools: list[str] = Field(default_factory=list)
    rag_hits: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    fallback_reason: str | None = None
    sms_encoding: str = "ucs2"
    sms_parts: int = 1


class TurnResult(BaseModel):
    replies: list[str]
    trace: Trace
    session_state: str
