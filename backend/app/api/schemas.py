"""Pydantic request schemas – all incoming payloads are validated here."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ComponentTypeL = Literal["FRONTEND", "BACKEND", "API_GATEWAY", "AUTH", "DATABASE", "CACHE", "MESSAGE_QUEUE",
                         "EXTERNAL_API", "STORAGE", "CUSTOM"]
CriticalityL = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RuleL = Literal["STRICT", "STANDARD", "TOLERANT"]
PolicyL = Literal["BLOCKING", "FAIL_FAST"]
DepTypeL = Literal["MANDATORY", "OPTIONAL"]
BaselineL = Literal["HEALTHY", "DEGRADED"]
FailureTypeL = Literal["COMPLETE_SERVICE_FAILURE", "DATABASE_FAILURE", "NETWORK_FAILURE", "API_TIMEOUT",
                       "HIGH_LATENCY", "RESOURCE_EXHAUSTION", "PARTIAL_DEGRADATION"]
StrategyL = Literal["DEPENDENCY_FIRST", "CRITICALITY_FIRST", "MAX_FUNCTIONALITY", "MIN_COST"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


try:  # EmailStr needs the optional email-validator package
    import email_validator  # noqa: F401
    EmailType = EmailStr
except ImportError:  # pragma: no cover - fallback validator
    EmailType = str


class RegisterIn(Strict):
    email: EmailType = Field(max_length=200)
    full_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    include_demo_project: bool = True

    @field_validator("email")
    @classmethod
    def email_shape(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("Enter a valid email address")
        return v.lower()

    @field_validator("password")
    @classmethod
    def strong(cls, v: str) -> str:
        if not any(c.isdigit() for c in v) or not any(c.isalpha() for c in v):
            raise ValueError("Password must contain letters and at least one digit")
        return v


class LoginIn(Strict):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class ProfileIn(Strict):
    full_name: str = Field(min_length=2, max_length=100)


class PasswordChangeIn(Strict):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ProjectIn(Strict):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=1000)
    propagation_policy: PolicyL = "BLOCKING"


class ProjectUpdate(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    propagation_policy: PolicyL | None = None


class ComponentIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    component_type: ComponentTypeL
    description: str = Field(default="", max_length=1000)
    criticality: CriticalityL = "MEDIUM"
    recovery_priority: int = Field(default=3, ge=1, le=5)
    estimated_recovery_minutes: float = Field(default=10, gt=0, le=10000)
    recovery_cost: float = Field(default=10, ge=0, le=1_000_000)
    operating_rule: RuleL = "STANDARD"
    baseline_status: BaselineL = "HEALTHY"
    baseline_health: float = Field(default=100, ge=0, le=100)
    pos_x: float | None = None
    pos_y: float | None = None


class ComponentUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    component_type: ComponentTypeL | None = None
    description: str | None = Field(default=None, max_length=1000)
    criticality: CriticalityL | None = None
    recovery_priority: int | None = Field(default=None, ge=1, le=5)
    estimated_recovery_minutes: float | None = Field(default=None, gt=0, le=10000)
    recovery_cost: float | None = Field(default=None, ge=0, le=1_000_000)
    operating_rule: RuleL | None = None
    baseline_status: BaselineL | None = None
    baseline_health: float | None = Field(default=None, ge=0, le=100)


class LayoutIn(Strict):
    positions: list[dict] = Field(max_length=500)

    @field_validator("positions")
    @classmethod
    def shape(cls, v):
        for p in v:
            if not {"id", "x", "y"} <= set(p):
                raise ValueError("Each position needs id, x and y")
        return v


class DependencyIn(Strict):
    project_id: int
    source_id: int
    target_id: int
    dependency_type: DepTypeL = "MANDATORY"
    fallback_id: int | None = None
    description: str = Field(default="", max_length=500)


class DependencyUpdate(Strict):
    dependency_type: DepTypeL | None = None
    fallback_component_id: int | None = None
    clear_fallback: bool = False
    description: str | None = Field(default=None, max_length=500)


class FunctionalityIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    is_critical: bool = False
    component_ids: list[int] = Field(min_length=1, max_length=100)


class FunctionalityUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    is_critical: bool | None = None
    component_ids: list[int] | None = Field(default=None, min_length=1, max_length=100)


class FailureIn(Strict):
    component_id: int
    failure_type: FailureTypeL
    severity: int = Field(ge=1, le=10)
    description: str = Field(default="", max_length=500)


class SimulationIn(Strict):
    project_id: int
    name: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=1000)
    duration_minutes: float = Field(default=30, gt=0, le=10080)
    failures: list[FailureIn] = Field(min_length=1, max_length=20)


class StartIn(Strict):
    instant: bool = False


class ScenarioIn(Strict):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    duration_minutes: float = Field(default=30, gt=0, le=10080)
    failures: list[FailureIn] = Field(min_length=1, max_length=20)


class WhatIfScenario(Strict):
    name: str = Field(min_length=1, max_length=100)
    duration_minutes: float = Field(default=30, gt=0, le=10080)
    failures: list[FailureIn] = Field(min_length=1, max_length=20)


class WhatIfIn(Strict):
    scenarios: list[WhatIfScenario] = Field(min_length=1, max_length=8)


class DiagnoseIn(Strict):
    observed_component_ids: list[int] = Field(min_length=1, max_length=100)


class PlanGenerateIn(Strict):
    strategies: list[StrategyL] | None = None


class SequenceIn(Strict):
    component_order: list[int] = Field(min_length=1, max_length=500)
    allow_invalid: bool = False


class ExecuteIn(Strict):
    run_to_completion: bool = False


class ImportIn(Strict):
    data: dict
    name: str | None = Field(default=None, max_length=80)
