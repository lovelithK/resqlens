"""Unit tests for the core algorithms (pure domain + engine, no database)."""
from __future__ import annotations

import pytest

from app.domain.enums import ComponentStatus, DependencyType, ImpactType
from app.domain.failures import (
    ApiTimeout, CompleteServiceFailure, DatabaseFailure, HighLatency, ResourceExhaustion, create_failure,
)
from app.domain.models import (
    Component, Dependency, DomainError, Functionality, InvalidStateTransition, SystemArchitecture,
)
from app.engine.dependency_manager import DependencyManager
from app.engine.events import DomainEvent, EventBus, EventType, RecordingObserver
from app.engine.execution import RecoveryExecutor
from app.engine.impact import ImpactAnalyzer, classify
from app.engine.propagation import BlockingPolicy, FailFastPolicy, FailurePropagationEngine, all_propagation_paths
from app.engine.recovery import STRATEGIES, RecoveryPlanner, get_strategy
from app.engine.resilience import OperationalResilienceModel, SPOFDetector
from app.engine.root_cause import RootCauseAnalyzer

M, O = DependencyType.MANDATORY, DependencyType.OPTIONAL
S = ComponentStatus


def comp(i, name, ctype="BACKEND", crit="MEDIUM", rule="STANDARD", minutes=10, cost=10):
    return Component(i, name, ctype, crit, operating_rule=rule, estimated_recovery_minutes=minutes,
                     recovery_cost=cost)


def arch(components, deps, funcs=(), policy="BLOCKING"):
    edges = [Dependency(i + 1, s, t, typ, fb) for i, (s, t, typ, fb) in enumerate(deps)]
    return SystemArchitecture(components, edges, funcs, propagation_policy=policy)


@pytest.fixture
def exam():
    """FE -> GW -> (Auth M, Exam O); Exam -> QDB M; Sub -> Exam M, Sub -> Store M; Res -> Sub M; Lonely."""
    comps = [comp(1, "Frontend", "FRONTEND", "HIGH"), comp(2, "Gateway", "API_GATEWAY", "CRITICAL"),
             comp(3, "Auth", "AUTH", "CRITICAL"), comp(4, "Exam", crit="CRITICAL"),
             comp(5, "QDB", "DATABASE", "CRITICAL", minutes=25, cost=30), comp(6, "Submission", crit="CRITICAL"),
             comp(7, "Storage", "STORAGE", "HIGH"), comp(8, "Results", crit="HIGH"), comp(9, "Lonely", minutes=2)]
    deps = [(1, 2, M, None), (2, 3, M, None), (2, 4, O, None), (4, 5, M, None), (4, 3, M, None),
            (6, 4, M, None), (6, 7, M, None), (8, 6, M, None)]
    funcs = [Functionality(1, "Login", True, [1, 2, 3]), Functionality(2, "Take exam", True, [1, 2, 4]),
             Functionality(3, "Results", False, [1, 2, 8])]
    return arch(comps, deps, funcs)


# ------------------------------------------------------------------ domain
def test_component_state_machine_is_encapsulated():
    c = comp(1, "A")
    c.transition_to(S.FAILED)
    assert c.health == 0
    with pytest.raises(InvalidStateTransition):
        c.transition_to(S.HEALTHY)          # must pass through RECOVERING
    c.transition_to(S.RECOVERING)
    c.transition_to(S.HEALTHY)
    assert c.health == 100 and c.is_available
    with pytest.raises(DomainError):
        comp(2, "B").transition_to(S.DEGRADED, health=150)


def test_failure_types_are_polymorphic():
    assert ApiTimeout(1, 4).resulting_status() == S.DEGRADED
    assert ApiTimeout(1, 5).resulting_status() == S.FAILED
    assert ResourceExhaustion(1, 6).resulting_status() == S.DEGRADED
    assert ResourceExhaustion(1, 7).resulting_status() == S.FAILED
    assert HighLatency(1, 9).resulting_status() == S.DEGRADED
    assert DatabaseFailure(1, 5).recovery_action().value == "RESTORE_DATABASE"
    with pytest.raises(DomainError):
        DatabaseFailure(1, 5).validate_target(comp(1, "svc", "BACKEND"))
    with pytest.raises(DomainError):
        create_failure("NOT_A_TYPE", 1, 5)
    with pytest.raises(DomainError):
        CompleteServiceFailure(1, 11)


# ---------------------------------------------------------- propagation
def test_cascade_direct_and_indirect(exam):
    r = FailurePropagationEngine(exam).propagate([DatabaseFailure(5, 8)])
    o = r.outcomes
    assert o[5].impact_type == ImpactType.SOURCE and o[5].status == S.FAILED
    assert o[4].impact_type == ImpactType.DIRECT and o[4].status == S.BLOCKED
    assert o[6].impact_type == ImpactType.INDIRECT and o[6].depth == 2
    assert o[8].impact_type == ImpactType.INDIRECT and o[8].depth == 3
    assert o[8].path == [5, 4, 6, 8]
    assert r.max_tick == 3


def test_optional_dependency_keeps_component_operational(exam):
    r = FailurePropagationEngine(exam).propagate([DatabaseFailure(5, 8)])
    assert r.outcomes[2].status == S.HEALTHY
    assert r.outcomes[2].impact_type == ImpactType.UNAFFECTED
    assert any("optional" in n.lower() for n in r.outcomes[2].notes)


def test_strict_rule_degrades_on_optional_loss():
    a = arch([comp(1, "A", rule="STRICT"), comp(2, "B")], [(1, 2, O, None)])
    r = FailurePropagationEngine(a).propagate([CompleteServiceFailure(2, 5)])
    assert r.outcomes[1].status == S.DEGRADED


def test_degraded_dependency_respects_operating_rule():
    a = arch([comp(1, "Std"), comp(2, "Tol", rule="TOLERANT"), comp(3, "Dep")],
             [(1, 3, M, None), (2, 3, M, None)])
    r = FailurePropagationEngine(a).propagate([HighLatency(3, 6)])
    assert r.outcomes[3].status == S.DEGRADED
    assert r.outcomes[1].status == S.DEGRADED
    assert r.outcomes[2].status == S.HEALTHY


def test_independent_components_unaffected(exam):
    r = FailurePropagationEngine(exam).propagate([CompleteServiceFailure(3, 9)])
    assert r.outcomes[9].impact_type == ImpactType.UNAFFECTED
    assert r.outcomes[7].impact_type == ImpactType.UNAFFECTED


def test_failure_of_component_without_dependents(exam):
    r = FailurePropagationEngine(exam).propagate([CompleteServiceFailure(9, 5)])
    affected = [x for x in r.outcomes.values() if x.affected]
    assert [x.component_id for x in affected] == [9]
    assert r.max_tick == 0


def test_multiple_paths_reach_component_once():
    # D depends on B and C, both depend on A (diamond)
    a = arch([comp(1, "A"), comp(2, "B"), comp(3, "C"), comp(4, "D")],
             [(2, 1, M, None), (3, 1, M, None), (4, 2, M, None), (4, 3, M, None)])
    r = FailurePropagationEngine(a).propagate([CompleteServiceFailure(1, 5)])
    assert r.outcomes[4].depth == 2
    assert sorted(r.outcomes[4].causes) == [2, 3]
    assert len([s for s in r.steps if s["component_id"] == 4]) == 1
    paths = all_propagation_paths(r)
    assert [1, 2, 4] in paths and [1, 3, 4] in paths


def test_multiple_simultaneous_failures_evaluated_together():
    # C needs A (mandatory) and B (optional); A degraded + B failed -> C degraded only via A
    a = arch([comp(1, "A"), comp(2, "B"), comp(3, "C")], [(3, 1, M, None), (3, 2, O, None)])
    r = FailurePropagationEngine(a).propagate([HighLatency(1, 5), CompleteServiceFailure(2, 5)])
    assert r.outcomes[3].status == S.DEGRADED
    assert {s["component_id"] for s in r.steps if s["tick"] == 0} == {1, 2}


def test_fail_fast_policy():
    a = arch([comp(1, "A"), comp(2, "B")], [(1, 2, M, None)], policy="FAIL_FAST")
    r = FailurePropagationEngine(a).propagate([CompleteServiceFailure(2, 5)])
    assert r.outcomes[1].status == S.FAILED
    assert FailurePropagationEngine(a, BlockingPolicy()).propagate([CompleteServiceFailure(2, 5)]).outcomes[1].status == S.BLOCKED
    assert isinstance(FailFastPolicy().mandatory_loss_status(), S)


def test_configured_backup_maintains_functionality():
    a = arch([comp(1, "Svc"), comp(2, "Primary", "DATABASE"), comp(3, "Replica", "DATABASE")], [(1, 2, M, 3)])
    r = FailurePropagationEngine(a).propagate([DatabaseFailure(2, 9)])
    assert r.outcomes[1].status == S.HEALTHY
    assert any("backup" in n for n in r.outcomes[1].notes)
    r2 = FailurePropagationEngine(a).propagate([DatabaseFailure(2, 9), DatabaseFailure(3, 9)])
    assert r2.outcomes[1].status == S.BLOCKED


def test_propagation_terminates_on_circular_graph():
    a = arch([comp(1, "A"), comp(2, "B"), comp(3, "C")], [(1, 2, M, None), (2, 3, M, None), (3, 1, M, None)])
    r = FailurePropagationEngine(a).propagate([CompleteServiceFailure(3, 5)])
    assert r.outcomes[2].status == S.BLOCKED and r.outcomes[1].status == S.BLOCKED
    assert r.cycles


# --------------------------------------------------------- validation
def test_cycle_detection_and_prevention():
    a = arch([comp(1, "A"), comp(2, "B"), comp(3, "C")], [(1, 2, M, None), (2, 3, M, None)])
    dm = DependencyManager(a)
    assert dm.would_create_cycle(3, 1) == [3, 1, 2, 3]
    assert dm.would_create_cycle(1, 3) is None
    cyc = arch([comp(1, "A"), comp(2, "B")], [(1, 2, M, None), (2, 1, M, None)])
    report = DependencyManager(cyc).validate()
    assert not report["valid"]
    assert report["issues"][0]["code"] == "CIRCULAR_DEPENDENCY"


def test_validation_reports_duplicates_and_bad_fallbacks():
    a = arch([comp(1, "A"), comp(2, "B"), comp(3, "Lonely")], [(1, 2, M, None), (1, 2, M, None), (1, 2, M, 1)])
    codes = {i["code"] for i in DependencyManager(a).validate()["issues"]}
    assert {"DUPLICATE_CONNECTION", "INVALID_FALLBACK", "ISOLATED_COMPONENT"} <= codes


# --------------------------------------------------------------- impact
def test_impact_score_is_deterministic_and_explained(exam):
    f = [DatabaseFailure(5, 8)]
    r = FailurePropagationEngine(exam).propagate(f)
    one = ImpactAnalyzer(exam).analyze(r, f, 30)
    two = ImpactAnalyzer(exam).analyze(FailurePropagationEngine(exam).propagate(f), f, 30)
    assert one["impact_score"] == two["impact_score"]
    assert one["direct_count"] == 1 and one["indirect_count"] == 2 and one["total_affected"] == 4
    assert abs(sum(x["contribution"] for x in one["factors"]) - one["impact_score"]) < 0.3
    assert one["unavailable_functionality_count"] == 2   # take exam + results
    assert {c["name"] for c in one["critical_components_affected"]} >= {"QDB", "Exam"}


def test_severity_classes():
    assert classify(10).value == "LOW"
    assert classify(30).value == "MODERATE"
    assert classify(60).value == "HIGH"
    assert classify(80).value == "CRITICAL"


def test_partial_reveal_only_counts_revealed(exam):
    f = [DatabaseFailure(5, 8)]
    r = FailurePropagationEngine(exam).propagate(f)
    partial = ImpactAnalyzer(exam).analyze(r, f, 30, up_to_tick=1)
    assert partial["total_affected"] == 2


# --------------------------------------------------------------- root cause
def test_root_cause_distinguishes_primary_from_secondary(exam):
    r = FailurePropagationEngine(exam).propagate([DatabaseFailure(5, 8)])
    rca = RootCauseAnalyzer(exam).analyze(r.statuses(), [{"component_id": 5, "component_name": "QDB",
                                                        "failure_label": "Database Failure", "severity": 8}])
    assert [c["name"] for c in rca["inferred_candidates"]] == ["QDB"]
    assert {s["name"] for s in rca["secondary_effects"]} == {"Exam", "Submission", "Results"}
    assert all(s["traced_to"] == ["QDB"] for s in rca["secondary_effects"])
    assert rca["inference_consistent_with_simulation"] is True
    assert rca["verified_causes"][0]["classification"] == "VERIFIED"


def test_symptom_diagnosis_finds_common_upstream(exam):
    d = RootCauseAnalyzer(exam).diagnose([4, 6, 8])
    full = {c["name"] for c in d["candidates"] if c["coverage"] == 1.0}
    assert {"Exam", "QDB", "Auth"} <= full
    assert "QDB" in d["deepest_common_dependencies"]


# -------------------------------------------------------------- recovery
def _planner(a, failures):
    return RecoveryPlanner(a, FailurePropagationEngine(a).propagate(failures), failures)


def test_every_strategy_produces_dependency_valid_plan(exam):
    planner = _planner(exam, [CompleteServiceFailure(3, 8)])
    for key in STRATEGIES:
        plan = planner.generate(get_strategy(key))
        assert planner.validate_sequence(plan["component_order"])["valid"], key
        assert plan["component_order"][0] == 3                        # the source first
        for a in plan["actions"]:
            assert set(a["explanation"]) >= {"what", "why", "dependencies", "if_skipped", "benefit"}


def test_strategies_differ_in_ordering(exam):
    planner = _planner(exam, [CompleteServiceFailure(3, 8)])
    orders = {k: tuple(planner.generate(get_strategy(k))["component_order"]) for k in STRATEGIES}
    assert len(set(orders.values())) > 1
    totals = {planner.generate(get_strategy(k))["metrics"]["estimated_minutes"] for k in STRATEGIES}
    assert len(totals) == 1                                           # sequential: same total time


def test_invalid_sequence_is_detected(exam):
    planner = _planner(exam, [DatabaseFailure(5, 8)])
    v = planner.validate_sequence([4, 5, 6, 8])
    assert not v["valid"] and v["violations"][0]["code"] == "PREREQUISITE_ORDER"
    v2 = planner.validate_sequence([5, 4])
    assert any(x["code"] == "MISSING_ACTION" for x in v2["violations"])


def test_recovery_blocked_while_mandatory_dependency_unavailable(exam):
    failures = [DatabaseFailure(5, 8)]
    r = FailurePropagationEngine(exam).propagate(failures)
    for cid, o in r.outcomes.items():
        if o.affected:
            exam.components[cid].transition_to(o.status, o.health)
    ex = RecoveryExecutor(exam)
    out = ex.execute(4, 10)                         # Exam before its database
    assert not out.success and exam.components[4].status == S.BLOCKED
    assert "QDB" in out.reason
    assert ex.execute(5, 20).success                # restore database
    assert ex.execute(4, 10).success and exam.components[4].status == S.HEALTHY


# -------------------------------------------------------------- resilience
def test_spof_and_resilience_breakdown(exam):
    rows = SPOFDetector(exam).analyze()
    spof = {r["name"] for r in rows if r["is_spof"]}
    assert {"Auth", "Gateway", "Frontend", "QDB", "Exam"} <= spof
    assert "Lonely" not in spof
    report = OperationalResilienceModel().score(exam, rows, None)
    recovery = next(b for b in report["breakdown"] if b["key"] == "recovery")
    assert recovery["included"] is False                      # no data -> excluded, weights renormalised
    assert abs(sum(b["effective_weight"] for b in report["breakdown"]) - 1) < 0.01
    assert 0 <= report["score"] <= 100 and report["grade"] in "ABCDF"


# ----------------------------------------------------------------- observer
def test_event_bus_filters_by_type():
    bus, all_events, only_restored = EventBus(), RecordingObserver(), RecordingObserver()
    bus.subscribe(all_events)
    bus.subscribe(only_restored, {EventType.COMPONENT_RESTORED})
    bus.publish(DomainEvent(EventType.FAILURE_INJECTED, "x", 1))
    bus.publish(DomainEvent(EventType.COMPONENT_RESTORED, "y", 1))
    assert len(all_events.events) == 2 and len(only_restored.events) == 1
    bus.unsubscribe(all_events)
    bus.publish(DomainEvent(EventType.FAILURE_INJECTED, "z", 1))
    assert len(all_events.events) == 2
