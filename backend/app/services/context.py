"""Per-request service context: DB connection, repositories, current user and
an event bus wired with the four concrete observers (Observer pattern)."""
from __future__ import annotations

from ..database import Connection, utcnow
from ..domain.enums import CRITICALITY_WEIGHT
from ..engine.events import DomainEvent, EventBus, EventObserver, EventType, TIMELINE_EVENTS
from ..repositories import (
    CommandLogRepository, ComponentRepository, DependencyRepository, EventLogRepository,
    FunctionalityRepository, ProjectRepository, RecoveryRepository, ResilienceRepository,
    ScenarioRepository, SimulationRepository, UserRepository,
)


class ArchitectureGraphObserver(EventObserver):
    """Keeps the persisted component states – which the architecture graph in
    the UI renders – in sync with simulation / recovery events."""

    def __init__(self, components: ComponentRepository):
        self.components = components

    def notify(self, event: DomainEvent) -> None:
        if event.type == EventType.COMPONENT_STATUS_CHANGED and event.component_id:
            self.components.set_state(event.component_id, event.details["status"], event.details["health"])
        elif event.type == EventType.SIMULATION_RESET:
            self.components.reset_project(event.project_id)


class EventLogObserver(EventObserver):
    """Persists every published event to ``event_logs`` (audit trail + timeline)."""

    def __init__(self, logs: EventLogRepository):
        self.logs = logs

    def notify(self, event: DomainEvent) -> None:
        category = "TIMELINE" if event.type in TIMELINE_EVENTS else event.category
        self.logs.add(event.project_id, event.type.value, event.message, event.simulation_id,
                      event.component_id, event.details, category, event.timestamp)


class DashboardMetricsObserver(EventObserver):
    """Maintains the project's aggregated health snapshot and last-activity time
    shown on the dashboard's system-health overview."""

    WATCHED = {EventType.COMPONENT_STATUS_CHANGED, EventType.SIMULATION_RESET, EventType.ARCHITECTURE_CHANGED,
               EventType.SYSTEM_RECOVERED, EventType.RECOVERY_INCOMPLETE, EventType.PROPAGATION_COMPLETED,
               EventType.SIMULATION_STARTED, EventType.PROJECT_CREATED}

    def __init__(self, conn: Connection):
        self.conn = conn
        self.updates = 0

    def notify(self, event: DomainEvent) -> None:
        rows = self.conn.all("SELECT criticality, health FROM system_components WHERE project_id = ?",
                             (event.project_id,))
        total = sum(CRITICALITY_WEIGHT[r["criticality"]] for r in rows)
        health = round(sum(CRITICALITY_WEIGHT[r["criticality"]] * r["health"] for r in rows) / total, 1) if total else 100
        self.conn.execute("UPDATE projects SET current_health = ?, last_activity_at = ? WHERE id = ?",
                          (health, utcnow(), event.project_id))
        self.updates += 1


class NotificationObserver(EventObserver):
    """Collects user-facing notifications that the API returns to the UI (toasts)."""

    LEVELS = {
        EventType.FAILURE_INJECTED: "error", EventType.PROPAGATION_COMPLETED: "warning",
        EventType.ROOT_CAUSE_IDENTIFIED: "info", EventType.RECOVERY_INITIATED: "info",
        EventType.COMPONENT_RESTORED: "success", EventType.RECOVERY_ACTION_FAILED: "error",
        EventType.SYSTEM_RECOVERED: "success", EventType.RECOVERY_INCOMPLETE: "warning",
        EventType.SIMULATION_RESET: "info",
    }

    def __init__(self):
        self.items: list[dict] = []

    def notify(self, event: DomainEvent) -> None:
        level = self.LEVELS.get(event.type)
        if level:
            self.items.append({"level": level, "type": event.type.value, "message": event.message})


class ServiceContext:
    def __init__(self, conn: Connection, user: dict | None = None):
        self.conn = conn
        self.user = user
        self.users = UserRepository(conn)
        self.projects = ProjectRepository(conn)
        self.components = ComponentRepository(conn)
        self.dependencies = DependencyRepository(conn)
        self.functionalities = FunctionalityRepository(conn)
        self.scenarios = ScenarioRepository(conn)
        self.simulations = SimulationRepository(conn)
        self.recovery = RecoveryRepository(conn)
        self.events = EventLogRepository(conn)
        self.resilience = ResilienceRepository(conn)
        self.commands = CommandLogRepository(conn)

        self.bus = EventBus()
        self.notifications = NotificationObserver()
        # Order matters: the graph state is updated before dashboard aggregates are recomputed.
        self.bus.subscribe(ArchitectureGraphObserver(self.components),
                           {EventType.COMPONENT_STATUS_CHANGED, EventType.SIMULATION_RESET})
        self.bus.subscribe(EventLogObserver(self.events))
        self.bus.subscribe(DashboardMetricsObserver(conn), DashboardMetricsObserver.WATCHED)
        self.bus.subscribe(self.notifications)

    @property
    def user_id(self) -> int:
        return self.user["id"]

    def publish(self, type_: EventType, message: str, project_id: int, simulation_id: int | None = None,
                component_id: int | None = None, details: dict | None = None, category: str = "SIMULATION"):
        self.bus.publish(DomainEvent(type_, message, project_id, simulation_id, component_id, details or {},
                                     category))
