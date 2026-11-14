from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


class ComponentType(StrEnum):
    FRONTEND = "FRONTEND"
    BACKEND = "BACKEND"
    API_GATEWAY = "API_GATEWAY"
    AUTH = "AUTH"
    DATABASE = "DATABASE"
    CACHE = "CACHE"
    MESSAGE_QUEUE = "MESSAGE_QUEUE"
    EXTERNAL_API = "EXTERNAL_API"
    STORAGE = "STORAGE"
    CUSTOM = "CUSTOM"


COMPONENT_TYPE_LABELS = {
    "FRONTEND": "Frontend Service", "BACKEND": "Backend Service", "API_GATEWAY": "API Gateway",
    "AUTH": "Authentication Service", "DATABASE": "Database", "CACHE": "Cache",
    "MESSAGE_QUEUE": "Message Queue", "EXTERNAL_API": "External API",
    "STORAGE": "Storage Service", "CUSTOM": "Custom Service",
}


class ComponentStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"


# Ordering used by the propagation engine (higher = worse). RECOVERING is a
# transient execution state and never produced by propagation.
STATUS_SEVERITY = {
    ComponentStatus.HEALTHY: 0,
    ComponentStatus.RECOVERING: 1,
    ComponentStatus.DEGRADED: 1,
    ComponentStatus.BLOCKED: 2,
    ComponentStatus.FAILED: 3,
}
UNAVAILABLE = {ComponentStatus.FAILED, ComponentStatus.BLOCKED, ComponentStatus.RECOVERING}
AVAILABLE = {ComponentStatus.HEALTHY, ComponentStatus.DEGRADED}


class Criticality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


CRITICALITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


class DependencyType(StrEnum):
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"


class OperatingRule(StrEnum):
    """How a component reacts to degraded/optional dependencies.

    STRICT   – degraded mandatory dep -> DEGRADED; optional dep lost -> DEGRADED
    STANDARD – degraded mandatory dep -> DEGRADED; optional dep lost -> stays operational
    TOLERANT – ignores degraded dependencies and optional losses
    (A lost *mandatory* dependency always makes the component unavailable.)
    """
    STRICT = "STRICT"
    STANDARD = "STANDARD"
    TOLERANT = "TOLERANT"


class PropagationPolicyKey(StrEnum):
    BLOCKING = "BLOCKING"
    FAIL_FAST = "FAIL_FAST"


class ImpactType(StrEnum):
    SOURCE = "SOURCE"
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    UNAFFECTED = "UNAFFECTED"


class FailureType(StrEnum):
    COMPLETE_SERVICE_FAILURE = "COMPLETE_SERVICE_FAILURE"
    DATABASE_FAILURE = "DATABASE_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    API_TIMEOUT = "API_TIMEOUT"
    HIGH_LATENCY = "HIGH_LATENCY"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    PARTIAL_DEGRADATION = "PARTIAL_DEGRADATION"
    # A simulation that contains more than one failure event is recorded with
    # this label; it is a scenario mode, not an individual failure class.
    MULTIPLE_SIMULTANEOUS = "MULTIPLE_SIMULTANEOUS"


class SimulationStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    PROPAGATED = "PROPAGATED"
    STOPPED = "STOPPED"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    RESET = "RESET"


# Simulations in these states "own" the project's live component state.
ACTIVE_SIMULATION_STATES = {
    SimulationStatus.RUNNING, SimulationStatus.PAUSED, SimulationStatus.PROPAGATED,
    SimulationStatus.STOPPED, SimulationStatus.RECOVERING, SimulationStatus.PARTIALLY_RECOVERED,
}
# RECOVERED simulations restored every component to baseline and therefore
# release the project (new simulations / architecture edits are allowed).


class RecoveryActionType(StrEnum):
    RESTART_SERVICE = "RESTART_SERVICE"
    RESTORE_DATABASE = "RESTORE_DATABASE"
    RECONNECT_DEPENDENCY = "RECONNECT_DEPENDENCY"
    RESTORE_NETWORK = "RESTORE_NETWORK"
    CLEAR_RESOURCE_EXHAUSTION = "CLEAR_RESOURCE_EXHAUSTION"
    RESTORE_SERVICE_CONFIGURATION = "RESTORE_SERVICE_CONFIGURATION"
    VALIDATE_SERVICE_HEALTH = "VALIDATE_SERVICE_HEALTH"


ACTION_LABELS = {
    "RESTART_SERVICE": "Restart Service",
    "RESTORE_DATABASE": "Restore Database",
    "RECONNECT_DEPENDENCY": "Reconnect Dependency",
    "RESTORE_NETWORK": "Restore Network",
    "CLEAR_RESOURCE_EXHAUSTION": "Clear Resource Exhaustion",
    "RESTORE_SERVICE_CONFIGURATION": "Restore Service Configuration",
    "VALIDATE_SERVICE_HEALTH": "Validate Service Health",
}


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    EXECUTING = "EXECUTING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FAILURES = "COMPLETED_WITH_FAILURES"
    SUPERSEDED = "SUPERSEDED"


class ActionStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class SeverityClass(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
