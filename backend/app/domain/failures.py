"""Failure-event hierarchy.

``FailureEvent`` is an abstract base class; each concrete failure type *is a*
failure event with its own deterministic effect on the failed component and
its own default recovery action. This is a genuine is-a relationship and lets
the simulation engine treat every failure polymorphically.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .enums import ComponentStatus, ComponentType, FailureType, RecoveryActionType
from .models import Component, DomainError


class FailureEvent(ABC):
    failure_type: FailureType
    label: str
    description: str
    applicable_types: frozenset[ComponentType] | None = None  # None = any component

    def __init__(self, component_id: int, severity: int, note: str = ""):
        if not 1 <= int(severity) <= 10:
            raise DomainError("Failure severity must be between 1 and 10", code="INVALID_SEVERITY")
        self.component_id = component_id
        self.severity = int(severity)
        self.note = note

    # -- behaviour that subclasses specialise ------------------------------
    @abstractmethod
    def resulting_status(self) -> ComponentStatus:
        """Status the directly failed component enters."""

    @abstractmethod
    def recovery_action(self) -> RecoveryActionType:
        """Default action needed to repair this failure."""

    def resulting_health(self) -> float:
        if self.resulting_status() in (ComponentStatus.FAILED, ComponentStatus.BLOCKED):
            return 0.0
        return float(max(10, 100 - 7 * self.severity))

    def recovery_time_factor(self) -> float:
        """Multiplier applied to the component's configured recovery time.
        Severity 5 -> 1.0x, severity 10 -> 1.5x, severity 1 -> 0.6x."""
        return round(0.5 + self.severity / 10, 2)

    def validate_target(self, component: Component) -> None:
        if self.applicable_types and component.component_type not in self.applicable_types:
            allowed = ", ".join(sorted(t.value for t in self.applicable_types))
            raise DomainError(
                f"{self.label} cannot be injected into '{component.name}' "
                f"({component.component_type.value}); allowed types: {allowed}",
                code="INVALID_FAILURE_TARGET")

    def describe(self, component_name: str) -> str:
        return (f"{self.label} injected into {component_name} (severity {self.severity}/10) "
                f"-> {self.resulting_status().value}")


class CompleteServiceFailure(FailureEvent):
    failure_type = FailureType.COMPLETE_SERVICE_FAILURE
    label = "Complete Service Failure"
    description = "The service process is down and does not respond at all."

    def resulting_status(self) -> ComponentStatus:
        return ComponentStatus.FAILED

    def recovery_action(self) -> RecoveryActionType:
        return RecoveryActionType.RESTART_SERVICE


class DatabaseFailure(FailureEvent):
    failure_type = FailureType.DATABASE_FAILURE
    label = "Database Failure"
    description = "The data store is unavailable or corrupted and must be restored."
    applicable_types = frozenset({ComponentType.DATABASE, ComponentType.CACHE, ComponentType.STORAGE})

    def resulting_status(self) -> ComponentStatus:
        return ComponentStatus.FAILED

    def recovery_action(self) -> RecoveryActionType:
        return RecoveryActionType.RESTORE_DATABASE

    def recovery_time_factor(self) -> float:
        # Data restoration scales more steeply with severity (data volume / integrity checks).
        return round(0.6 + self.severity / 8, 2)


class NetworkFailure(FailureEvent):
    failure_type = FailureType.NETWORK_FAILURE
    label = "Network Failure"
    description = "The component is running but unreachable over the network."

    def resulting_status(self) -> ComponentStatus:
        return ComponentStatus.FAILED

    def recovery_action(self) -> RecoveryActionType:
        return RecoveryActionType.RESTORE_NETWORK

    def recovery_time_factor(self) -> float:
        return round(0.4 + self.severity / 20, 2)


class ApiTimeout(FailureEvent):
    failure_type = FailureType.API_TIMEOUT
    label = "API Timeout"
    description = "Requests to the component time out. Severity >= 5 makes it unusable for callers."

    def resulting_status(self) -> ComponentStatus:
        return ComponentStatus.FAILED if self.severity >= 5 else ComponentStatus.DEGRADED

    def recovery_action(self) -> RecoveryActionType:
        return RecoveryActionType.RESTORE_SERVICE_CONFIGURATION


class HighLatency(FailureEvent):
    failure_type = FailureType.HIGH_LATENCY
    label = "High Latency"
    description = "The component responds, but slowly. It stays available in a degraded state."

    def resulting_status(self) -> ComponentStatus:
        return ComponentStatus.DEGRADED

    def recovery_action(self) -> RecoveryActionType:
        return RecoveryActionType.RESTORE_SERVICE_CONFIGURATION


class ResourceExhaustion(FailureEvent):
    failure_type = FailureType.RESOURCE_EXHAUSTION
    label = "Resource Exhaustion"
    description = "CPU / memory / connection pool exhausted. Severity >= 7 makes it fail outright."

    def resulting_status(self) -> ComponentStatus:
        return ComponentStatus.FAILED if self.severity >= 7 else ComponentStatus.DEGRADED

    def recovery_action(self) -> RecoveryActionType:
        return RecoveryActionType.CLEAR_RESOURCE_EXHAUSTION


class PartialDegradation(FailureEvent):
    failure_type = FailureType.PARTIAL_DEGRADATION
    label = "Partial Service Degradation"
    description = "Some instances or features of the service are failing; it remains partially available."

    def resulting_status(self) -> ComponentStatus:
        return ComponentStatus.DEGRADED

    def resulting_health(self) -> float:
        return float(max(15, 100 - 6 * self.severity))

    def recovery_action(self) -> RecoveryActionType:
        return RecoveryActionType.RESTART_SERVICE


FAILURE_CLASSES: dict[str, type[FailureEvent]] = {
    cls.failure_type.value: cls for cls in (
        CompleteServiceFailure, DatabaseFailure, NetworkFailure, ApiTimeout,
        HighLatency, ResourceExhaustion, PartialDegradation,
    )
}


def create_failure(failure_type: str, component_id: int, severity: int, note: str = "") -> FailureEvent:
    """Factory used by the simulation engine."""
    try:
        cls = FAILURE_CLASSES[failure_type]
    except KeyError:
        raise DomainError(f"Unknown failure type '{failure_type}'", code="INVALID_FAILURE_TYPE")
    return cls(component_id, severity, note)


def failure_catalog() -> list[dict]:
    return [{
        "type": key, "label": cls.label, "description": cls.description,
        "applicable_types": sorted(t.value for t in cls.applicable_types) if cls.applicable_types else None,
    } for key, cls in FAILURE_CLASSES.items()]
