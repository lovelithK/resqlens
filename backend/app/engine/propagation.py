"""Deterministic, rule-based failure propagation engine.

Algorithm (documented in docs/ALGORITHMS.md)
-------------------------------------------
1. **Source application** – every injected ``FailureEvent`` sets its component
   to the status/health defined by its failure class (most severe wins when a
   component is hit more than once).
2. **Candidate discovery (BFS)** – breadth-first search from all sources along
   *reverse* dependency edges (dependency -> dependent). A ``visited`` set
   guarantees termination even if the graph contains cycles.
3. **Joint evaluation (monotone fixed point)** – every candidate is evaluated
   against *all* of its dependencies at once using the configured
   ``PropagationPolicy`` (Strategy pattern) and the component's operating rule.
   Statuses only ever escalate (HEALTHY < DEGRADED < BLOCKED < FAILED), so the
   iteration reaches a fixed point in at most |V| rounds, also on cyclic graphs.
4. **Chronology (BFS over affected sub-graph)** – a second BFS starting at the
   sources but walking only through affected components assigns each affected
   component its propagation depth (= tick), its causes and a shortest
   propagation path. Depth 1 -> DIRECT impact, depth >= 2 -> INDIRECT impact.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field

from ..domain.enums import (
    AVAILABLE, STATUS_SEVERITY, ComponentStatus, ImpactType, OperatingRule, PropagationPolicyKey,
)
from ..domain.failures import FailureEvent
from ..domain.models import Component, Dependency, DomainError, SystemArchitecture

DERIVED_DEGRADED_HEALTH = 65.0


@dataclass
class DependencyAssessment:
    mandatory_lost: list[Dependency] = field(default_factory=list)
    mandatory_degraded: list[Dependency] = field(default_factory=list)
    optional_lost: list[Dependency] = field(default_factory=list)
    optional_degraded: list[Dependency] = field(default_factory=list)
    failovers: list[Dependency] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Strategy pattern: propagation policies
# ---------------------------------------------------------------------------
class PropagationPolicy(ABC):
    key: PropagationPolicyKey
    name: str
    description: str

    @abstractmethod
    def mandatory_loss_status(self) -> ComponentStatus:
        """Status of a component whose mandatory dependency is unavailable."""

    def assess(self, arch: SystemArchitecture, component_id: int,
               statuses: dict[int, ComponentStatus]) -> DependencyAssessment:
        result = DependencyAssessment()
        for dep in arch.dependencies_of(component_id):
            target_state = statuses.get(dep.target_id, ComponentStatus.HEALTHY)
            if target_state not in AVAILABLE and dep.fallback_id is not None:
                fb_state = statuses.get(dep.fallback_id, ComponentStatus.HEALTHY)
                if fb_state in AVAILABLE:
                    # Configured redundancy takes over: the dependency is served by the backup.
                    result.failovers.append(dep)
                    target_state = fb_state
            if target_state not in AVAILABLE:
                (result.mandatory_lost if dep.is_mandatory else result.optional_lost).append(dep)
            elif target_state == ComponentStatus.DEGRADED:
                (result.mandatory_degraded if dep.is_mandatory else result.optional_degraded).append(dep)
        return result

    def evaluate(self, arch: SystemArchitecture, component: Component,
                 statuses: dict[int, ComponentStatus]) -> tuple[ComponentStatus, str, list[int], list[str]]:
        """Return (status, reason, cause_ids, notes) for a non-source component."""
        a = self.assess(arch, component.id, statuses)
        n = arch.name_of
        notes = [f"Failover: {n(d.target_id)} unavailable, served by configured backup {n(d.fallback_id)}"
                 for d in a.failovers]
        rule = component.operating_rule
        if a.mandatory_lost:
            names = ", ".join(f"{n(d.target_id)} ({statuses[d.target_id].value})" for d in a.mandatory_lost)
            return (self.mandatory_loss_status(), f"Mandatory dependency unavailable: {names}",
                    [d.target_id for d in a.mandatory_lost], notes)
        if a.optional_lost:
            names = ", ".join(n(d.target_id) for d in a.optional_lost)
            if rule == OperatingRule.STRICT:
                return (ComponentStatus.DEGRADED, f"Optional dependency unavailable (STRICT rule): {names}",
                        [d.target_id for d in a.optional_lost], notes)
            notes.append(f"Operational without optional dependency: {names}")
        if a.mandatory_degraded and rule != OperatingRule.TOLERANT:
            names = ", ".join(n(d.target_id) for d in a.mandatory_degraded)
            return (ComponentStatus.DEGRADED, f"Mandatory dependency degraded: {names}",
                    [d.target_id for d in a.mandatory_degraded], notes)
        if a.optional_degraded and rule == OperatingRule.STRICT:
            names = ", ".join(n(d.target_id) for d in a.optional_degraded)
            return (ComponentStatus.DEGRADED, f"Optional dependency degraded (STRICT rule): {names}",
                    [d.target_id for d in a.optional_degraded], notes)
        return component.baseline_status, "", [], notes


class BlockingPolicy(PropagationPolicy):
    key = PropagationPolicyKey.BLOCKING
    name = "Blocking"
    description = ("A component that loses a mandatory dependency is BLOCKED: its own process is intact, "
                   "but it cannot serve requests until the dependency returns.")

    def mandatory_loss_status(self) -> ComponentStatus:
        return ComponentStatus.BLOCKED


class FailFastPolicy(PropagationPolicy):
    key = PropagationPolicyKey.FAIL_FAST
    name = "Fail-fast"
    description = ("A component that loses a mandatory dependency is treated as FAILED (crash/exit on "
                   "missing dependency) and needs a full restart.")

    def mandatory_loss_status(self) -> ComponentStatus:
        return ComponentStatus.FAILED


POLICIES: dict[str, type[PropagationPolicy]] = {
    PropagationPolicyKey.BLOCKING.value: BlockingPolicy,
    PropagationPolicyKey.FAIL_FAST.value: FailFastPolicy,
}


def get_policy(key: str) -> PropagationPolicy:
    try:
        return POLICIES[key]()
    except KeyError:
        raise DomainError(f"Unknown propagation policy '{key}'", code="INVALID_POLICY")


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------
@dataclass
class ComponentOutcome:
    component_id: int
    name: str
    criticality: str
    baseline_status: ComponentStatus
    status: ComponentStatus
    health: float
    impact_type: ImpactType = ImpactType.UNAFFECTED
    depth: int | None = None
    tick: int | None = None
    reason: str = ""
    causes: list[int] = field(default_factory=list)
    path: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def affected(self) -> bool:
        return self.impact_type != ImpactType.UNAFFECTED

    def to_dict(self) -> dict:
        return {"component_id": self.component_id, "name": self.name, "criticality": self.criticality,
                "status": self.status.value, "health": self.health, "impact_type": self.impact_type.value,
                "depth": self.depth, "tick": self.tick, "reason": self.reason, "causes": self.causes,
                "path": self.path, "notes": self.notes}


@dataclass
class PropagationResult:
    outcomes: dict[int, ComponentOutcome]
    steps: list[dict]
    propagation_edges: list[dict]
    max_tick: int
    cycles: list[list[int]]
    policy: str

    def statuses(self, up_to_tick: int | None = None) -> dict[int, ComponentStatus]:
        out = {}
        for cid, o in self.outcomes.items():
            if o.affected and up_to_tick is not None and (o.tick is None or o.tick > up_to_tick):
                out[cid] = o.baseline_status
            else:
                out[cid] = o.status
        return out

    def by_type(self, impact_type: ImpactType) -> list[ComponentOutcome]:
        return [o for o in self.outcomes.values() if o.impact_type == impact_type]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class FailurePropagationEngine:
    def __init__(self, architecture: SystemArchitecture, policy: PropagationPolicy | None = None):
        self.arch = architecture
        self.policy = policy or get_policy(architecture.propagation_policy)

    def propagate(self, failures: list[FailureEvent]) -> PropagationResult:
        arch = self.arch
        if not failures:
            raise DomainError("At least one failure must be injected", code="NO_FAILURES")

        statuses: dict[int, ComponentStatus] = arch.baseline_statuses()
        health: dict[int, float] = {cid: c.baseline_health for cid, c in arch.components.items()}
        source_reason: dict[int, str] = {}

        # 1. sources ---------------------------------------------------------
        sources: list[int] = []
        for f in failures:
            comp = arch.component(f.component_id)
            f.validate_target(comp)
            new_status = f.resulting_status()
            if f.component_id not in sources:
                sources.append(f.component_id)
            if STATUS_SEVERITY[new_status] >= STATUS_SEVERITY[statuses[comp.id]] or comp.id not in source_reason:
                if STATUS_SEVERITY[new_status] >= STATUS_SEVERITY[statuses[comp.id]]:
                    statuses[comp.id] = new_status
                    health[comp.id] = min(health[comp.id], f.resulting_health())
            source_reason[comp.id] = "; ".join(filter(None, [source_reason.get(comp.id), f.describe(comp.name)]))

        # 2. BFS candidate discovery over reverse edges -------------------------
        visited: set[int] = set(sources)
        order: list[int] = []
        queue = deque(sources)
        while queue:
            current = queue.popleft()
            for dep in arch.dependents_of(current):
                if dep.source_id not in visited:
                    visited.add(dep.source_id)
                    order.append(dep.source_id)
                    queue.append(dep.source_id)
            # a backup's dependents are also influenced (failover may disappear)
            for dep in arch.dependencies:
                if dep.fallback_id == current and dep.source_id not in visited:
                    visited.add(dep.source_id)
                    order.append(dep.source_id)
                    queue.append(dep.source_id)

        # 3. monotone fixed-point evaluation ------------------------------------
        reasons: dict[int, tuple[str, list[int], list[str]]] = {}
        source_set = set(sources)
        for _ in range(len(arch.components) + 1):
            changed = False
            for cid in order:
                if cid in source_set:
                    continue
                comp = arch.components[cid]
                new_status, reason, causes, notes = self.policy.evaluate(arch, comp, statuses)
                if STATUS_SEVERITY[new_status] > STATUS_SEVERITY[statuses[cid]]:
                    statuses[cid] = new_status
                    changed = True
                if STATUS_SEVERITY[new_status] >= STATUS_SEVERITY[statuses[cid]]:
                    reasons[cid] = (reason, causes, notes)
                elif cid not in reasons:
                    reasons[cid] = (reason, causes, notes)
            if not changed:
                break

        # 4. chronology over the affected sub-graph -------------------------------
        outcomes: dict[int, ComponentOutcome] = {}
        for cid, comp in arch.components.items():
            outcomes[cid] = ComponentOutcome(
                component_id=cid, name=comp.name, criticality=comp.criticality.value,
                baseline_status=comp.baseline_status, status=statuses[cid], health=health[cid])
        affected = {cid for cid in arch.components
                    if cid in source_set or STATUS_SEVERITY[statuses[cid]] > STATUS_SEVERITY[arch.components[cid].baseline_status]}

        for cid in sources:
            o = outcomes[cid]
            o.impact_type, o.depth, o.tick, o.path = ImpactType.SOURCE, 0, 0, [cid]
            o.reason = source_reason[cid]

        steps = [{"tick": 0, "component_id": cid, "name": arch.name_of(cid), "status": statuses[cid].value,
                  "impact_type": "SOURCE", "causes": [], "reason": source_reason[cid]} for cid in sources]
        edges: list[dict] = []
        queue = deque(sources)
        depth: dict[int, int] = {cid: 0 for cid in sources}
        while queue:
            current = queue.popleft()
            for dep in arch.dependents_of(current):
                nxt = dep.source_id
                if nxt not in affected or nxt in source_set:
                    continue
                reason, causes, notes = reasons.get(nxt, ("", [], []))
                if current not in causes:
                    continue
                edges.append({"from": current, "to": nxt, "dependency_id": dep.id,
                              "dependency_type": dep.dependency_type.value})
                if nxt in depth:
                    continue
                depth[nxt] = depth[current] + 1
                o = outcomes[nxt]
                o.depth = o.tick = depth[nxt]
                o.impact_type = ImpactType.DIRECT if depth[nxt] == 1 else ImpactType.INDIRECT
                o.reason, o.causes, o.notes = reason, causes, notes
                o.path = outcomes[current].path + [nxt]
                o.health = 0.0 if o.status not in AVAILABLE else min(o.health, DERIVED_DEGRADED_HEALTH)
                steps.append({"tick": o.tick, "component_id": nxt, "name": o.name, "status": o.status.value,
                              "impact_type": o.impact_type.value, "causes": causes, "reason": reason})
                queue.append(nxt)

        # Affected components whose cause chain does not start at an injected source
        # (e.g. a dependency that was already DEGRADED in the baseline) are placed
        # after their latest-known cause so the chronology remains complete.
        for cid in sorted(affected - set(depth), key=lambda c: arch.name_of(c)):
            reason, causes, notes = reasons.get(cid, ("", [], []))
            o = outcomes[cid]
            o.depth = o.tick = 1 + max((depth.get(c, 0) for c in causes), default=0)
            o.impact_type = ImpactType.DIRECT if o.depth == 1 else ImpactType.INDIRECT
            o.reason, o.causes, o.notes, o.path = reason, causes, notes, [cid]
            o.health = 0.0 if o.status not in AVAILABLE else min(o.health, DERIVED_DEGRADED_HEALTH)
            depth[cid] = o.depth
            steps.append({"tick": o.tick, "component_id": cid, "name": o.name, "status": o.status.value,
                          "impact_type": o.impact_type.value, "causes": causes, "reason": reason})

        # notes (failover / tolerated optional loss) for unaffected components
        for cid, (reason, causes, notes) in reasons.items():
            if not outcomes[cid].affected and notes:
                outcomes[cid].notes = notes

        cycles: list[list[int]] = []
        try:
            import networkx as nx
            cycles = [c for c, _ in zip(nx.simple_cycles(arch.graph), range(10))]
        except Exception:  # pragma: no cover
            cycles = []

        steps.sort(key=lambda s: (s["tick"], s["name"]))
        max_tick = max((s["tick"] for s in steps), default=0)
        return PropagationResult(outcomes=outcomes, steps=steps, propagation_edges=edges,
                                 max_tick=max_tick, cycles=cycles, policy=self.policy.key.value)


def all_propagation_paths(result: PropagationResult, limit: int = 60) -> list[list[int]]:
    """Enumerate source -> leaf paths through the propagation edges (bounded)."""
    children: dict[int, list[int]] = {}
    for e in result.propagation_edges:
        children.setdefault(e["from"], []).append(e["to"])
    paths: list[list[int]] = []
    sources = [o.component_id for o in result.by_type(ImpactType.SOURCE)]

    def walk(node: int, path: list[int]):
        if len(paths) >= limit:
            return
        nxt = [c for c in children.get(node, []) if c not in path]
        if not nxt:
            if len(path) > 1:
                paths.append(path)
            return
        for c in nxt:
            walk(c, path + [c])

    for s in sources:
        walk(s, [s])
    return paths
