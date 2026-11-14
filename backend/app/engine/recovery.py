"""Recovery Recommendation Engine.

Every strategy runs the same *precedence-constrained list scheduler* (Kahn's
topological-sort algorithm): an action becomes "ready" only when all of its
prerequisite actions (recovery of unhealthy mandatory dependencies) are done.
Strategies (Strategy pattern) only decide *which ready action goes next*, so
every generated plan is dependency-valid by construction.

Actions execute sequentially (one recovery team), so the *total* time and
cost of every complete plan are identical; strategies differ in how quickly
functionality and critical components come back. Comparison metrics:

* functionality_downtime_minutes – sum over affected functionalities of the
  minute at which each becomes available again (lower is better)
* critical_functionality_restored_at – minute at which the last critical
  functionality is available again
* weighted_component_downtime – sum(criticality weight x restore minute)
* mean_component_restore_minute

No strategy is claimed to be globally optimal: B, C and D are greedy
heuristics; A is a plain dependency-layer ordering.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..domain.enums import (
    ACTION_LABELS, AVAILABLE, CRITICALITY_WEIGHT, ComponentStatus, ImpactType, OperatingRule,
    RecoveryActionType,
)
from ..domain.failures import FailureEvent
from ..domain.models import DomainError, SystemArchitecture
from .propagation import PropagationResult


@dataclass
class PlannedAction:
    component_id: int
    component_name: str
    action_type: RecoveryActionType
    estimated_minutes: float
    cost: float
    prerequisites: list[int]
    status_before: ComponentStatus
    impact_type: ImpactType
    reason: str
    explanation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"component_id": self.component_id, "component_name": self.component_name,
                "action_type": self.action_type.value, "action_label": ACTION_LABELS[self.action_type.value],
                "estimated_minutes": self.estimated_minutes, "cost": self.cost,
                "prerequisites": self.prerequisites, "status_before": self.status_before.value,
                "impact_type": self.impact_type.value, "explanation": self.explanation}


@dataclass
class RecoveryContext:
    arch: SystemArchitecture
    actions: dict[int, PlannedAction]
    statuses: dict[int, ComponentStatus]
    required_by: dict[int, set[int]]          # transitive dependents (within the plan)
    effective_criticality: dict[int, int]
    depth: dict[int, int]

    def statuses_after(self, completed: set[int]) -> dict[int, ComponentStatus]:
        s = dict(self.statuses)
        for cid in completed:
            s[cid] = self.arch.components[cid].baseline_status
        return s

    def available_functionalities(self, completed: set[int]) -> set[int]:
        funcs = self.arch.functionality_status(self.statuses_after(completed))
        return {f["id"] for f in funcs if f["status"] == "AVAILABLE"}


# ---------------------------------------------------------------------------
# Strategy pattern
# ---------------------------------------------------------------------------
class RecoveryStrategy(ABC):
    key: str
    name: str
    description: str
    guarantee: str

    @abstractmethod
    def select(self, ready: list[PlannedAction], ctx: RecoveryContext, completed: set[int]) -> PlannedAction:
        """Choose the next action among the dependency-ready ones."""

    @abstractmethod
    def rationale(self, action: PlannedAction, ctx: RecoveryContext, ready: list[PlannedAction]) -> str:
        """Rule-based sentence explaining why the action was chosen at this point."""

    def build_order(self, ctx: RecoveryContext) -> list[PlannedAction]:
        remaining = dict(ctx.actions)
        completed: set[int] = set()
        order: list[PlannedAction] = []
        while remaining:
            ready = [a for a in remaining.values() if all(p in completed for p in a.prerequisites)]
            if not ready:  # only possible with cyclic prerequisites
                ready = sorted(remaining.values(), key=lambda a: a.component_name)[:1]
            ready.sort(key=lambda a: a.component_name)  # deterministic tie-breaking base
            chosen = self.select(ready, ctx, completed)
            chosen.explanation["strategy_rationale"] = self.rationale(chosen, ctx, ready)
            order.append(chosen)
            completed.add(chosen.component_id)
            del remaining[chosen.component_id]
        return order


class DependencyFirstStrategy(RecoveryStrategy):
    key = "DEPENDENCY_FIRST"
    name = "Dependency-First Recovery"
    description = ("Restores the most upstream failures first (propagation depth ascending), then the "
                   "components that depend on them, layer by layer.")
    guarantee = ("Dependency-valid topological order. Follows the cascade backwards; it does not optimise "
                 "functionality or criticality.")

    def _key(self, a, ctx):
        return (ctx.depth.get(a.component_id, 0), -len(ctx.required_by[a.component_id]),
                -CRITICALITY_WEIGHT[ctx.arch.components[a.component_id].criticality.value])

    def select(self, ready, ctx, completed):
        return min(ready, key=lambda a: self._key(a, ctx))

    def rationale(self, action, ctx, ready):
        d = ctx.depth.get(action.component_id, 0)
        n = len(ctx.required_by[action.component_id])
        return (f"Most upstream ready action (propagation depth {d}); {n} affected component(s) depend on it.")


class CriticalityFirstStrategy(RecoveryStrategy):
    key = "CRITICALITY_FIRST"
    name = "Criticality-First Recovery"
    description = ("Prioritises components by criticality. An upstream dependency inherits the highest "
                   "criticality of the components waiting on it (priority inheritance), so critical services "
                   "are unblocked as early as dependencies allow.")
    guarantee = ("Dependency-valid. Greedy priority rule; ties broken by recovery priority then dependents. "
                 "Not globally optimal.")

    def _key(self, a, ctx):
        comp = ctx.arch.components[a.component_id]
        return (-ctx.effective_criticality[a.component_id], -CRITICALITY_WEIGHT[comp.criticality.value],
                comp.recovery_priority, -len(ctx.required_by[a.component_id]))

    def select(self, ready, ctx, completed):
        return min(ready, key=lambda a: self._key(a, ctx))

    def rationale(self, action, ctx, ready):
        comp = ctx.arch.components[action.component_id]
        eff = ctx.effective_criticality[action.component_id]
        label = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}[eff]
        inherited = eff > CRITICALITY_WEIGHT[comp.criticality.value]
        return (f"Highest effective criticality among {len(ready)} ready action(s): {label}"
                + (f" (inherited from dependents; own criticality {comp.criticality.value})" if inherited else "")
                + f", recovery priority {comp.recovery_priority}.")


class MaximumFunctionalityStrategy(RecoveryStrategy):
    key = "MAX_FUNCTIONALITY"
    name = "Maximum Functionality Recovery"
    description = ("Greedy: at each step picks the ready action that immediately restores the most user-facing "
                   "functionality (critical functionality counts double); otherwise the one that unblocks the "
                   "most still-unavailable functionality.")
    guarantee = "Dependency-valid greedy heuristic. Not guaranteed to be globally optimal."

    def _gain(self, a, ctx, completed, before):
        after = ctx.available_functionalities(completed | {a.component_id})
        gained = after - before
        weights = {f.id: (2 if f.is_critical else 1) for f in ctx.arch.functionalities}
        return sum(weights[f] for f in gained), gained

    def _potential(self, a, ctx, completed, before):
        involved = {a.component_id} | ctx.required_by[a.component_id]
        return sum((2 if f.is_critical else 1) for f in ctx.arch.functionalities
                   if f.id not in before and involved & set(f.component_ids))

    def select(self, ready, ctx, completed):
        before = ctx.available_functionalities(completed)
        return min(ready, key=lambda a: (-self._gain(a, ctx, completed, before)[0],
                                         -self._potential(a, ctx, completed, before), a.estimated_minutes))

    def rationale(self, action, ctx, ready):
        return ("Chosen because it restores or unblocks the largest weighted number of unavailable "
                f"functionalities among {len(ready)} ready action(s).")


class MinimumCostStrategy(RecoveryStrategy):
    key = "MIN_COST"
    name = "Minimum Recovery Cost"
    description = ("Shortest/cheapest-first: among ready actions picks the lowest configured recovery cost, "
                   "then the shortest estimated time (SPT rule), producing quick early wins.")
    guarantee = ("Dependency-valid. SPT minimises mean completion time only without precedence constraints; "
                 "here it is a heuristic. Total plan cost is the same for every complete plan.")

    def select(self, ready, ctx, completed):
        return min(ready, key=lambda a: (a.cost, a.estimated_minutes))

    def rationale(self, action, ctx, ready):
        return (f"Cheapest ready action (cost {action.cost:g}, {action.estimated_minutes:g} min) among "
                f"{len(ready)} ready action(s).")


STRATEGIES: dict[str, type[RecoveryStrategy]] = {
    cls.key: cls for cls in (DependencyFirstStrategy, CriticalityFirstStrategy,
                             MaximumFunctionalityStrategy, MinimumCostStrategy)
}


def get_strategy(key: str) -> RecoveryStrategy:
    try:
        return STRATEGIES[key]()
    except KeyError:
        raise DomainError(f"Unknown recovery strategy '{key}'", code="INVALID_STRATEGY")


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------
class RecoveryPlanner:
    def __init__(self, arch: SystemArchitecture, result: PropagationResult,
                 failures: list[FailureEvent], statuses: dict[int, ComponentStatus] | None = None):
        self.arch = arch
        self.result = result
        self.failures = failures
        self.statuses = statuses or result.statuses()

    # -- action derivation ----------------------------------------------------
    def required_prerequisites(self, cid: int, plan_ids: set[int]) -> list[int]:
        comp = self.arch.components[cid]
        prereqs = []
        for dep in self.arch.dependencies_of(cid):
            if dep.target_id not in plan_ids:
                continue
            if not dep.is_mandatory and comp.operating_rule != OperatingRule.STRICT:
                continue
            if dep.fallback_id is not None and dep.fallback_id not in plan_ids \
                    and self.statuses.get(dep.fallback_id) in AVAILABLE:
                continue  # configured backup is healthy -> not a hard prerequisite
            prereqs.append(dep.target_id)
        return sorted(prereqs)

    def build_actions(self) -> dict[int, PlannedAction]:
        arch = self.arch
        failures_by_comp: dict[int, list[FailureEvent]] = {}
        for f in self.failures:
            failures_by_comp.setdefault(f.component_id, []).append(f)
        plan_ids = {cid for cid, s in self.statuses.items()
                    if cid in arch.components and s != arch.components[cid].baseline_status
                    and s in (ComponentStatus.FAILED, ComponentStatus.BLOCKED, ComponentStatus.DEGRADED)}
        if not plan_ids:
            raise DomainError("No affected components require recovery", code="NOTHING_TO_RECOVER")
        actions: dict[int, PlannedAction] = {}
        for cid in plan_ids:
            comp = arch.components[cid]
            outcome = self.result.outcomes[cid]
            status = self.statuses[cid]
            if cid in failures_by_comp:
                f = max(failures_by_comp[cid], key=lambda x: x.severity)
                atype = f.recovery_action()
                factor = max(x.recovery_time_factor() for x in failures_by_comp[cid])
            elif status == ComponentStatus.BLOCKED:
                atype, factor = RecoveryActionType.RECONNECT_DEPENDENCY, 0.3
            elif status == ComponentStatus.FAILED:
                atype, factor = RecoveryActionType.RESTART_SERVICE, 1.0
            else:
                atype, factor = RecoveryActionType.VALIDATE_SERVICE_HEALTH, 0.15
            actions[cid] = PlannedAction(
                component_id=cid, component_name=comp.name, action_type=atype,
                estimated_minutes=round(max(1.0, comp.estimated_recovery_minutes * factor), 1),
                cost=round(comp.recovery_cost * factor, 1),
                prerequisites=self.required_prerequisites(cid, plan_ids),
                status_before=status, impact_type=outcome.impact_type, reason=outcome.reason)
        return actions

    def context(self, actions: dict[int, PlannedAction]) -> RecoveryContext:
        dependents: dict[int, set[int]] = {cid: set() for cid in actions}
        for a in actions.values():
            for p in a.prerequisites:
                dependents[p].add(a.component_id)
        required_by: dict[int, set[int]] = {}
        for cid in actions:
            seen, stack = set(), [cid]
            while stack:
                cur = stack.pop()
                for d in dependents[cur]:
                    if d not in seen:
                        seen.add(d)
                        stack.append(d)
            required_by[cid] = seen
        eff = {cid: max([CRITICALITY_WEIGHT[self.arch.components[x].criticality.value]
                         for x in ({cid} | required_by[cid])]) for cid in actions}
        depth = {cid: (self.result.outcomes[cid].depth or 0) for cid in actions}
        return RecoveryContext(self.arch, actions, self.statuses, required_by, eff, depth)

    # -- plan generation -----------------------------------------------------
    def generate(self, strategy: RecoveryStrategy) -> dict:
        actions = self.build_actions()
        ctx = self.context(actions)
        order = strategy.build_order(ctx)
        return self._finalise(strategy, ctx, order)

    def evaluate_order(self, strategy_key: str, component_order: list[int]) -> dict:
        actions = self.build_actions()
        ctx = self.context(actions)
        validation = self.validate_sequence(component_order, actions)
        order = [actions[c] for c in component_order if c in actions]
        for a in order:
            a.explanation["strategy_rationale"] = "Position set manually by the user."
        plan = self._finalise(get_strategy(strategy_key), ctx, order)
        plan["validation"] = validation
        plan["is_valid"] = validation["valid"]
        return plan

    def compare(self) -> list[dict]:
        return [self.generate(cls()) for cls in STRATEGIES.values()]

    # -- validation ------------------------------------------------------------
    def validate_sequence(self, component_order: list[int], actions: dict[int, PlannedAction] | None = None) -> dict:
        actions = actions or self.build_actions()
        n = self.arch.name_of
        violations = []
        position = {}
        for idx, cid in enumerate(component_order):
            if cid in position:
                violations.append({"code": "DUPLICATE_ACTION", "component_id": cid,
                                   "message": f"{n(cid)} appears more than once in the sequence"})
            position.setdefault(cid, idx)
        for cid in component_order:
            if cid not in actions:
                violations.append({"code": "UNKNOWN_ACTION", "component_id": cid,
                                   "message": f"{n(cid)} does not require recovery in this simulation"})
        missing = [cid for cid in actions if cid not in position]
        for cid in missing:
            violations.append({"code": "MISSING_ACTION", "component_id": cid,
                               "message": f"Recovery of {n(cid)} is missing from the sequence"})
        for cid, idx in position.items():
            if cid not in actions:
                continue
            for p in actions[cid].prerequisites:
                if p in position and position[p] > idx:
                    violations.append({
                        "code": "PREREQUISITE_ORDER", "component_id": cid, "prerequisite_id": p,
                        "message": (f"{n(cid)} (step {idx + 1}) is scheduled before its mandatory dependency "
                                    f"{n(p)} (step {position[p] + 1}); it cannot be restored while {n(p)} "
                                    "is unavailable")})
        return {"valid": not violations, "violations": violations}

    # -- metrics + explanations -----------------------------------------------
    def _finalise(self, strategy: RecoveryStrategy, ctx: RecoveryContext, order: list[PlannedAction]) -> dict:
        arch, n = self.arch, self.arch.name_of
        funcs_before = arch.functionality_status(ctx.statuses)
        affected_funcs = {f["id"] for f in funcs_before if f["status"] != "AVAILABLE"}
        critical_ids = {f.id for f in arch.functionalities if f.is_critical}
        func_names = {f.id: f.name for f in arch.functionalities}
        completed: set[int] = set()
        clock = 0.0
        restored_at: dict[int, float] = {}
        timeline = [{"minute": 0, "available_functionalities": len(arch.functionalities) - len(affected_funcs),
                     "healthy_components": sum(1 for s in ctx.statuses.values() if s == ComponentStatus.HEALTHY)}]
        prev_available = ctx.available_functionalities(completed)
        steps = []
        position = {a.component_id: i for i, a in enumerate(order)}
        for idx, a in enumerate(order):
            start = clock
            clock = round(clock + a.estimated_minutes, 1)
            completed.add(a.component_id)
            now_available = ctx.available_functionalities(completed)
            gained = sorted(now_available - prev_available)
            for fid in gained:
                restored_at.setdefault(fid, clock)
            prev_available = now_available
            unblocked = sorted(n(d) for d in ctx.actions if a.component_id in ctx.actions[d].prerequisites
                               and all(p in completed for p in ctx.actions[d].prerequisites)
                               and d not in completed)
            downstream = sorted(n(d) for d in ctx.required_by[a.component_id])
            funcs_blocked_if_skipped = sorted(
                func_names[f.id] for f in arch.functionalities
                if f.id in affected_funcs and ({a.component_id} | ctx.required_by[a.component_id]) & set(f.component_ids))
            prereq_text = [f"{n(p)} (step {position[p] + 1})" if p in position else n(p) for p in a.prerequisites]
            source_failures = [f for f in self.failures if f.component_id == a.component_id]
            if source_failures:
                why = (f"{a.component_name} is the injected failure source "
                       f"({', '.join(f.label for f in source_failures)}); it is {a.status_before.value} and must be "
                       f"repaired with '{ACTION_LABELS[a.action_type.value]}'.")
            else:
                why = f"{a.component_name} is {a.status_before.value} ({a.impact_type.value.lower()} impact): {a.reason}."
            a.explanation.update({
                "what": f"{ACTION_LABELS[a.action_type.value]} on {a.component_name}",
                "why": why,
                "dependencies": (f"Requires prior recovery of: {', '.join(prereq_text)}." if prereq_text
                                 else "No unhealthy mandatory dependencies; it can be recovered immediately."),
                "if_skipped": (f"{a.component_name} stays {a.status_before.value}"
                               + (f"; dependent components remain unavailable: {', '.join(downstream)}" if downstream else "")
                               + (f"; functionality not restored: {', '.join(funcs_blocked_if_skipped)}"
                                  if funcs_blocked_if_skipped else "") + "."),
                "benefit": ((f"Restores functionality: {', '.join(func_names[g] for g in gained)}. " if gained else "")
                            + (f"Unblocks: {', '.join(unblocked)}. " if unblocked else "")
                            + f"Component health returns to {arch.components[a.component_id].baseline_health:g}%."),
            })
            steps.append({**a.to_dict(), "step": idx + 1, "start_minute": start, "end_minute": clock,
                          "restores_functionalities": [func_names[g] for g in gained],
                          "unblocks": unblocked})
            timeline.append({"minute": clock, "available_functionalities": len(now_available),
                             "healthy_components": sum(1 for s in ctx.statuses_after(completed).values()
                                                       if s == ComponentStatus.HEALTHY)})

        total_minutes = clock
        func_downtime = sum(restored_at.get(f, total_minutes) for f in affected_funcs)
        crit_affected = affected_funcs & critical_ids
        crit_restored = max((restored_at.get(f, total_minutes) for f in crit_affected), default=0.0)
        end_times = {s["component_id"]: s["end_minute"] for s in steps}
        weighted_downtime = sum(CRITICALITY_WEIGHT[arch.components[c].criticality.value] * t for c, t in end_times.items())
        return {
            "strategy": {"key": strategy.key, "name": strategy.name, "description": strategy.description,
                         "guarantee": strategy.guarantee},
            "actions": steps,
            "component_order": [a.component_id for a in order],
            "metrics": {
                "action_count": len(order),
                "estimated_minutes": total_minutes,
                "total_cost": round(sum(a.cost for a in order), 1),
                "functionality_downtime_minutes": round(func_downtime, 1),
                "critical_functionality_restored_at": round(crit_restored, 1),
                "weighted_component_downtime": round(weighted_downtime, 1),
                "mean_component_restore_minute": round(sum(end_times.values()) / len(end_times), 1) if end_times else 0,
                "affected_functionalities": len(affected_funcs),
                "timeline": timeline,
            },
            "is_valid": True,
            "validation": {"valid": True, "violations": []},
        }
