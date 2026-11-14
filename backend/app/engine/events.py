"""Observer pattern – domain event bus.

``EventBus`` is the *subject*. Business services publish ``DomainEvent``s
(component status changed, failure injected, recovery step done, ...).
Observers subscribe for the event types they care about and update their own
representation – the persisted graph state, the event log, the dashboard
metrics or the user notification list. Publishers never know who listens.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventType(str, Enum):
    SIMULATION_CREATED = "SIMULATION_CREATED"
    SIMULATION_STARTED = "SIMULATION_STARTED"
    SIMULATION_PAUSED = "SIMULATION_PAUSED"
    SIMULATION_RESUMED = "SIMULATION_RESUMED"
    SIMULATION_STOPPED = "SIMULATION_STOPPED"
    SIMULATION_RESET = "SIMULATION_RESET"
    FAILURE_INJECTED = "FAILURE_INJECTED"
    DEPENDENCY_AFFECTED = "DEPENDENCY_AFFECTED"
    FAILURE_PROPAGATED = "FAILURE_PROPAGATED"
    PROPAGATION_COMPLETED = "PROPAGATION_COMPLETED"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    COMPONENT_STATUS_CHANGED = "COMPONENT_STATUS_CHANGED"
    RECOVERY_PLAN_GENERATED = "RECOVERY_PLAN_GENERATED"
    RECOVERY_PLAN_SELECTED = "RECOVERY_PLAN_SELECTED"
    RECOVERY_INITIATED = "RECOVERY_INITIATED"
    RECOVERY_PAUSED = "RECOVERY_PAUSED"
    RECOVERY_RESUMED = "RECOVERY_RESUMED"
    RECOVERY_ACTION_STARTED = "RECOVERY_ACTION_STARTED"
    COMPONENT_RESTORED = "COMPONENT_RESTORED"
    RECOVERY_ACTION_FAILED = "RECOVERY_ACTION_FAILED"
    SYSTEM_RECOVERED = "SYSTEM_RECOVERED"
    RECOVERY_INCOMPLETE = "RECOVERY_INCOMPLETE"
    ARCHITECTURE_CHANGED = "ARCHITECTURE_CHANGED"
    PROJECT_CREATED = "PROJECT_CREATED"


# Events that are part of the simulation timeline (Module 3.4)
TIMELINE_EVENTS = {
    EventType.SIMULATION_STARTED, EventType.SIMULATION_PAUSED, EventType.SIMULATION_RESUMED,
    EventType.SIMULATION_STOPPED, EventType.FAILURE_INJECTED, EventType.DEPENDENCY_AFFECTED,
    EventType.FAILURE_PROPAGATED, EventType.PROPAGATION_COMPLETED, EventType.ROOT_CAUSE_IDENTIFIED,
    EventType.RECOVERY_PLAN_GENERATED, EventType.RECOVERY_PLAN_SELECTED, EventType.RECOVERY_INITIATED,
    EventType.RECOVERY_PAUSED, EventType.RECOVERY_RESUMED, EventType.COMPONENT_RESTORED,
    EventType.RECOVERY_ACTION_FAILED, EventType.SYSTEM_RECOVERED, EventType.RECOVERY_INCOMPLETE,
    EventType.SIMULATION_RESET,
}


@dataclass
class DomainEvent:
    type: EventType
    message: str
    project_id: int
    simulation_id: int | None = None
    component_id: int | None = None
    details: dict = field(default_factory=dict)
    category: str = "SIMULATION"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class EventObserver(ABC):
    @abstractmethod
    def notify(self, event: DomainEvent) -> None:
        ...


class EventBus:
    """Subject. Observers can subscribe to all events or a subset of types."""

    def __init__(self):
        self._subscriptions: list[tuple[EventObserver, frozenset[EventType] | None]] = []

    def subscribe(self, observer: EventObserver, event_types: set[EventType] | None = None) -> None:
        self._subscriptions.append((observer, frozenset(event_types) if event_types else None))

    def unsubscribe(self, observer: EventObserver) -> None:
        self._subscriptions = [(o, t) for o, t in self._subscriptions if o is not observer]

    @property
    def observers(self) -> list[EventObserver]:
        return [o for o, _ in self._subscriptions]

    def publish(self, event: DomainEvent) -> None:
        for observer, types in list(self._subscriptions):
            if types is None or event.type in types:
                observer.notify(event)


class RecordingObserver(EventObserver):
    """In-memory observer (used in tests and for collecting events of one request)."""

    def __init__(self):
        self.events: list[DomainEvent] = []

    def notify(self, event: DomainEvent) -> None:
        self.events.append(event)
