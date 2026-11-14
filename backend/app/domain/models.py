"""Core domain objects. They are pure Python (no database, no HTTP) so the
business logic can be unit-tested and reused independently of the frontend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import networkx as nx

from .enums import (
    AVAILABLE, CRITICALITY_WEIGHT, ComponentStatus, ComponentType, Criticality,
    DependencyType, OperatingRule,
)


class DomainError(Exception):
    """Raised when a business rule is violated."""

    def __init__(self, message: str, code: str = "DOMAIN_ERROR", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class InvalidStateTransition(DomainError):
    def __init__(self, component: str, current: str, target: str):
        super().__init__(
            f"Invalid status transition for '{component}': {current} -> {target}",
            code="INVALID_STATE_TRANSITION",
            details={"component": component, "from": current, "to": target},
        )


class Component:
    """A system component with *encapsulated* operational state.

    ``status`` and ``health`` can only be changed through ``transition_to`` /
    ``reset_to_baseline`` which enforce the allowed state machine below.
    """

    ALLOWED_TRANSITIONS: dict[ComponentStatus, set[ComponentStatus]] = {
        ComponentStatus.HEALTHY: {ComponentStatus.DEGRADED, ComponentStatus.BLOCKED, ComponentStatus.FAILED},
        ComponentStatus.DEGRADED: {ComponentStatus.HEALTHY, ComponentStatus.BLOCKED, ComponentStatus.FAILED,
                                   ComponentStatus.RECOVERING},
        ComponentStatus.BLOCKED: {ComponentStatus.FAILED, ComponentStatus.RECOVERING, ComponentStatus.DEGRADED},
        ComponentStatus.FAILED: {ComponentStatus.RECOVERING},
        ComponentStatus.RECOVERING: {ComponentStatus.HEALTHY, ComponentStatus.DEGRADED,
                                     ComponentStatus.FAILED, ComponentStatus.BLOCKED},
    }

    def __init__(
        self, id: int, name: str, component_type: str, criticality: str = "MEDIUM",
        description: str = "", status: str = "HEALTHY", health: float = 100.0,
        baseline_status: str = "HEALTHY", baseline_health: float = 100.0,
        recovery_priority: int = 3, estimated_recovery_minutes: float = 10.0,
        recovery_cost: float = 10.0, operating_rule: str = "STANDARD",
        created_at: str | None = None,
    ):
        self.id = id
        self.name = name
        self.component_type = ComponentType(component_type)
        self.criticality = Criticality(criticality)
        self.description = description
        self.baseline_status = ComponentStatus(baseline_status)
        self.baseline_health = float(baseline_health)
        self.recovery_priority = int(recovery_priority)
        self.estimated_recovery_minutes = float(estimated_recovery_minutes)
        self.recovery_cost = float(recovery_cost)
        self.operating_rule = OperatingRule(operating_rule)
        self.created_at = created_at
        self._status = ComponentStatus(status)
        self._health = self._validate_health(health)

    # -- encapsulated state ------------------------------------------------
    @staticmethod
    def _validate_health(value: float) -> float:
        value = float(value)
        if not 0 <= value <= 100:
            raise DomainError("Health must be between 0 and 100", code="INVALID_HEALTH")
        return round(value, 1)

    @property
    def status(self) -> ComponentStatus:
        return self._status

    @property
    def health(self) -> float:
        return self._health

    @property
    def criticality_weight(self) -> int:
        return CRITICALITY_WEIGHT[self.criticality.value]

    @property
    def is_available(self) -> bool:
        return self._status in AVAILABLE

    def can_transition_to(self, target: ComponentStatus) -> bool:
        return target == self._status or target in self.ALLOWED_TRANSITIONS[self._status]

    def transition_to(self, target: ComponentStatus | str, health: float | None = None) -> ComponentStatus:
        target = ComponentStatus(target)
        if not self.can_transition_to(target):
            raise InvalidStateTransition(self.name, self._status.value, target.value)
        previous = self._status
        self._status = target
        if health is not None:
            self._health = self._validate_health(health)
        elif target in (ComponentStatus.FAILED, ComponentStatus.BLOCKED):
            self._health = 0.0
        elif target == ComponentStatus.HEALTHY:
            self._health = self.baseline_health
        return previous

    def reset_to_baseline(self) -> None:
        self._status = self.baseline_status
        self._health = self.baseline_health

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "component_type": self.component_type.value,
            "criticality": self.criticality.value, "status": self._status.value, "health": self._health,
            "recovery_priority": self.recovery_priority,
            "estimated_recovery_minutes": self.estimated_recovery_minutes,
            "recovery_cost": self.recovery_cost, "operating_rule": self.operating_rule.value,
        }


@dataclass(frozen=True)
class Dependency:
    """``source_id`` depends on ``target_id``."""
    id: int
    source_id: int
    target_id: int
    dependency_type: DependencyType = DependencyType.MANDATORY
    fallback_id: int | None = None

    @property
    def is_mandatory(self) -> bool:
        return self.dependency_type == DependencyType.MANDATORY


@dataclass
class Functionality:
    id: int
    name: str
    is_critical: bool
    component_ids: list[int] = field(default_factory=list)
    description: str = ""


class SystemArchitecture:
    """An aggregate of components, dependencies and user-facing functionalities.

    Edges in the internal graph point from the *dependent* to its *dependency*
    (A -> B means "A depends on B"); failures therefore propagate against the
    edge direction.
    """

    def __init__(self, components: Iterable[Component], dependencies: Iterable[Dependency],
                 functionalities: Iterable[Functionality] = (), propagation_policy: str = "BLOCKING",
                 project_id: int | None = None, name: str = ""):
        self.project_id = project_id
        self.name = name
        self.propagation_policy = propagation_policy
        self.components: dict[int, Component] = {c.id: c for c in components}
        self.dependencies: list[Dependency] = list(dependencies)
        self.functionalities: list[Functionality] = list(functionalities)
        self._outgoing: dict[int, list[Dependency]] = {cid: [] for cid in self.components}
        self._incoming: dict[int, list[Dependency]] = {cid: [] for cid in self.components}
        for dep in self.dependencies:
            if dep.source_id in self._outgoing:
                self._outgoing[dep.source_id].append(dep)
            if dep.target_id in self._incoming:
                self._incoming[dep.target_id].append(dep)
        self._graph: nx.DiGraph | None = None

    # -- graph helpers ---------------------------------------------------
    @property
    def graph(self) -> nx.DiGraph:
        if self._graph is None:
            g = nx.DiGraph()
            for cid, comp in self.components.items():
                g.add_node(cid, name=comp.name)
            for dep in self.dependencies:
                if dep.source_id in self.components and dep.target_id in self.components:
                    g.add_edge(dep.source_id, dep.target_id, id=dep.id,
                               mandatory=dep.is_mandatory, fallback=dep.fallback_id)
            self._graph = g
        return self._graph

    def dependencies_of(self, component_id: int) -> list[Dependency]:
        return self._outgoing.get(component_id, [])

    def dependents_of(self, component_id: int) -> list[Dependency]:
        return self._incoming.get(component_id, [])

    def component(self, component_id: int) -> Component:
        try:
            return self.components[component_id]
        except KeyError:
            raise DomainError(f"Component {component_id} does not exist", code="NOT_FOUND")

    def name_of(self, component_id: int | None) -> str:
        if component_id is None:
            return "-"
        comp = self.components.get(component_id)
        return comp.name if comp else f"#{component_id}"

    def downstream_closure(self, component_id: int) -> set[int]:
        """All components that (transitively) depend on ``component_id``."""
        return set(nx.ancestors(self.graph, component_id)) if component_id in self.graph else set()

    def upstream_closure(self, component_id: int, mandatory_only: bool = False,
                         skip_covered: bool = False) -> set[int]:
        """All components that ``component_id`` (transitively) depends on.
        ``skip_covered`` ignores dependencies protected by a configured backup."""
        if not mandatory_only:
            return set(nx.descendants(self.graph, component_id)) if component_id in self.graph else set()
        seen: set[int] = set()
        stack = [component_id]
        while stack:
            current = stack.pop()
            for dep in self.dependencies_of(current):
                if skip_covered and dep.fallback_id is not None:
                    continue
                if dep.is_mandatory and dep.target_id not in seen:
                    seen.add(dep.target_id)
                    stack.append(dep.target_id)
        return seen

    def functionality_status(self, statuses: dict[int, ComponentStatus]) -> list[dict]:
        """Availability of each user-facing functionality for a status map."""
        result = []
        for func in self.functionalities:
            comp_states = [statuses.get(cid, ComponentStatus.HEALTHY) for cid in func.component_ids
                           if cid in self.components]
            if any(s not in AVAILABLE for s in comp_states):
                state = "UNAVAILABLE"
            elif any(s == ComponentStatus.DEGRADED for s in comp_states):
                state = "DEGRADED"
            else:
                state = "AVAILABLE"
            blocking = [self.name_of(cid) for cid in func.component_ids
                        if statuses.get(cid, ComponentStatus.HEALTHY) not in AVAILABLE]
            result.append({"id": func.id, "name": func.name, "is_critical": func.is_critical,
                           "status": state, "blocking_components": blocking,
                           "components": [self.name_of(c) for c in func.component_ids]})
        return result

    def functionalities_using(self, component_id: int) -> list[Functionality]:
        return [f for f in self.functionalities if component_id in f.component_ids]

    def current_statuses(self) -> dict[int, ComponentStatus]:
        return {cid: c.status for cid, c in self.components.items()}

    def baseline_statuses(self) -> dict[int, ComponentStatus]:
        return {cid: c.baseline_status for cid, c in self.components.items()}
