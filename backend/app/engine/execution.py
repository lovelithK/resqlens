"""Recovery Execution Simulator (affects only the simulated environment).

``RecoveryExecutor.execute`` performs exactly one recovery action against the
*live* simulated component states:

1. The component enters RECOVERING (validated state transition).
2. Dependency availability is validated with the same propagation policy used
   for the cascade: if any dependency that the component needs is still
   unavailable (and no configured backup covers it), the action fails.
3. On success the component returns to its baseline status and health; on
   failure it returns to the status it had before the attempt.

Durations are deterministic: a successful action takes its estimated time; a
failed attempt costs 25 % of it (diagnosis time), minimum 0.5 simulated min.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.enums import STATUS_SEVERITY, ComponentStatus
from ..domain.models import SystemArchitecture
from .propagation import PropagationPolicy, get_policy


@dataclass
class ExecutionOutcome:
    success: bool
    component_id: int
    previous_status: ComponentStatus
    final_status: ComponentStatus
    duration: float
    reason: str
    transitions: list[tuple[str, str]] = field(default_factory=list)


class RecoveryExecutor:
    def __init__(self, architecture: SystemArchitecture, policy: PropagationPolicy | None = None):
        self.arch = architecture
        self.policy = policy or get_policy(architecture.propagation_policy)

    def check_dependencies(self, component_id: int) -> tuple[bool, str]:
        comp = self.arch.component(component_id)
        live = self.arch.current_statuses()
        status, reason, causes, _ = self.policy.evaluate(self.arch, comp, live)
        if STATUS_SEVERITY[status] > STATUS_SEVERITY[comp.baseline_status]:
            return False, f"Dependency check failed – {reason}"
        return True, "All required dependencies are available"

    def execute(self, component_id: int, estimated_minutes: float) -> ExecutionOutcome:
        comp = self.arch.component(component_id)
        previous = comp.status
        transitions: list[tuple[str, str]] = []
        if previous == comp.baseline_status:
            return ExecutionOutcome(True, component_id, previous, previous, 0.0,
                                    "Component already at its baseline state; nothing to do")
        comp.transition_to(ComponentStatus.RECOVERING)
        transitions.append((previous.value, ComponentStatus.RECOVERING.value))
        ok, reason = self.check_dependencies(component_id)
        if ok:
            comp.transition_to(comp.baseline_status, comp.baseline_health)
            transitions.append((ComponentStatus.RECOVERING.value, comp.baseline_status.value))
            return ExecutionOutcome(True, component_id, previous, comp.status, float(estimated_minutes),
                                    reason, transitions)
        comp.transition_to(previous, 0.0 if previous != ComponentStatus.DEGRADED else None)
        transitions.append((ComponentStatus.RECOVERING.value, previous.value))
        return ExecutionOutcome(False, component_id, previous, comp.status,
                                round(max(0.5, 0.25 * float(estimated_minutes)), 1), reason, transitions)
