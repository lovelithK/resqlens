"""Simulation lifecycle orchestration (create -> start -> tick/pause/resume ->
propagated/stopped -> reset) and analysis read-models."""
from __future__ import annotations

from ..database import dumps, loads, utcnow
from ..domain.enums import ACTIVE_SIMULATION_STATES, ComponentStatus, FailureType, SimulationStatus
from ..domain.failures import FAILURE_CLASSES, create_failure
from ..engine.events import EventType
from ..engine.impact import ImpactAnalyzer
from ..engine.propagation import FailurePropagationEngine, PropagationResult
from ..engine.root_cause import RootCauseAnalyzer
from ..errors import conflict, invalid
from ..repositories import load_architecture
from .commands import CommandInvoker, InjectFailureCommand, ResetSimulationCommand, StartSimulationCommand
from .context import ServiceContext


class SimulationService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.invoker = CommandInvoker(ctx)

    # -- creation -------------------------------------------------------------
    def create(self, project: dict, data: dict) -> dict:
        failures = data["failures"]
        if not failures:
            raise invalid("Add at least one failure", code="NO_FAILURES")
        seen = set()
        for f in failures:
            key = (f["component_id"], f["failure_type"])
            if key in seen:
                raise invalid("The same failure type is configured twice on one component", code="DUPLICATE_FAILURE")
            seen.add(key)
        ftype = failures[0]["failure_type"] if len(failures) == 1 else FailureType.MULTIPLE_SIMULTANEOUS.value
        sim_id = self.ctx.simulations.create({
            "project_id": project["id"], "user_id": self.ctx.user_id,
            "name": data.get("name") or f"Simulation {utcnow()[:16].replace('T', ' ')}",
            "description": data.get("description", ""), "failure_type": ftype, "status": "CREATED",
            "propagation_policy": project["propagation_policy"],
            "duration_minutes": data.get("duration_minutes", 30)})
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        for f in failures:
            self.invoker.run(InjectFailureCommand(self.ctx, project, simulation=sim, **f))
        self.ctx.publish(EventType.SIMULATION_CREATED, f"Simulation '{sim['name']}' created with "
                         f"{len(failures)} failure(s)", project["id"], sim_id)
        return self.detail(sim_id)

    # -- helpers --------------------------------------------------------------
    def _project(self, sim: dict) -> dict:
        return self.ctx.projects.get_owned(sim["project_id"], self.ctx.user_id)

    def failure_objects(self, sim_id: int) -> list:
        return [create_failure(f["failure_type"], f["component_id"], f["severity"], f["description"])
                for f in self.ctx.simulations.failures(sim_id) if f["component_id"] is not None]

    def rebuild(self, sim: dict):
        """Deterministically recompute the propagation for an active simulation."""
        project = self._project(sim)
        arch = load_architecture(self.ctx.conn, {**project, "propagation_policy": sim["propagation_policy"]})
        failures = self.failure_objects(sim["id"])
        result = FailurePropagationEngine(arch).propagate(failures)
        return project, arch, failures, result

    def _require(self, sim: dict, allowed: set[str], action: str):
        if sim["status"] not in allowed:
            raise conflict(f"Cannot {action} a simulation that is {sim['status']}", code="INVALID_STATE")

    # -- lifecycle --------------------------------------------------------------
    def start(self, sim_id: int, instant: bool = False) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        project = self._project(sim)
        self.invoker.run(StartSimulationCommand(self.ctx, project, simulation=sim))
        _, arch, failures, result = self.rebuild(sim)
        self.ctx.simulations.save_results(sim_id, [o.to_dict() for o in result.outcomes.values()])
        self.ctx.simulations.update(sim_id, max_tick=result.max_tick)
        self.ctx.publish(EventType.SIMULATION_STARTED,
                         f"Simulation '{sim['name']}' started ({len(failures)} failure(s), "
                         f"{sim['propagation_policy']} policy)", project["id"], sim_id)
        self._reveal(sim_id, project, result, 0)
        if instant:
            while self._advance(sim_id, project, result):
                pass
        return self.detail(sim_id)

    def tick(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        self._require(sim, {"RUNNING"}, "advance")
        project, _, _, result = self.rebuild(sim)
        self._advance(sim_id, project, result)
        return self.detail(sim_id)

    def _advance(self, sim_id: int, project: dict, result: PropagationResult) -> bool:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if sim["status"] != "RUNNING":
            return False
        nxt = sim["current_tick"] + 1
        if nxt > sim["max_tick"]:
            self._finalise(sim_id, project, result)
            return False
        self._reveal(sim_id, project, result, nxt)
        return True

    def _reveal(self, sim_id: int, project: dict, result: PropagationResult, tick: int) -> None:
        arch_names = {cid: o.name for cid, o in result.outcomes.items()}
        for o in sorted(result.outcomes.values(), key=lambda x: x.name):
            if not o.affected or o.tick != tick:
                continue
            if tick == 0:
                etype, msg = EventType.FAILURE_INJECTED, f"Failure injected: {o.reason}"
            elif tick == 1:
                etype = EventType.DEPENDENCY_AFFECTED
                msg = f"{o.name} affected directly ({o.status.value}): {o.reason}"
            else:
                etype = EventType.FAILURE_PROPAGATED
                msg = f"Failure propagated to {o.name} ({o.status.value}) via " + " -> ".join(
                    arch_names[c] for c in o.path)
            self.ctx.publish(EventType.COMPONENT_STATUS_CHANGED, f"{o.name} -> {o.status.value}", project["id"],
                             sim_id, o.component_id, {"status": o.status.value, "health": o.health, "tick": tick})
            self.ctx.publish(etype, msg, project["id"], sim_id, o.component_id,
                             {"tick": tick, "status": o.status.value, "impact_type": o.impact_type.value,
                              "causes": [arch_names.get(c) for c in o.causes]})
        self.ctx.simulations.update(sim_id, current_tick=tick)
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if tick >= sim["max_tick"]:
            self._finalise(sim_id, project, result)

    def _finalise(self, sim_id: int, project: dict, result: PropagationResult,
                  status: SimulationStatus = SimulationStatus.PROPAGATED) -> None:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if sim["status"] not in ("RUNNING", "PAUSED"):
            return
        _, arch, failures, _ = self.rebuild(sim)
        up_to = None if status == SimulationStatus.PROPAGATED else sim["current_tick"]
        impact = ImpactAnalyzer(arch).analyze(result, failures, sim["duration_minutes"], up_to_tick=up_to)
        rca = RootCauseAnalyzer(arch).analyze(result.statuses(up_to), self._verified(sim_id))
        self.ctx.simulations.update(sim_id, status=status.value, propagated_at=utcnow(),
                                    impact_score=impact["impact_score"], severity_class=impact["severity_class"],
                                    impact_json=dumps(impact), root_cause_json=dumps(rca))
        self.ctx.publish(EventType.PROPAGATION_COMPLETED,
                         f"Propagation {'completed' if up_to is None else 'stopped'}: {impact['total_affected']} "
                         f"component(s) affected, impact {impact['impact_score']} ({impact['severity_class']})",
                         project["id"], sim_id, details={"impact_score": impact["impact_score"]})
        roots = ", ".join(v["component_name"] for v in rca["verified_causes"])
        self.ctx.publish(EventType.ROOT_CAUSE_IDENTIFIED, f"Root cause identified: {roots} (verified simulated "
                         "failure source)", project["id"], sim_id,
                         details={"inferred": [c["name"] for c in rca["inferred_candidates"]]})
        from .analytics import AnalyticsService
        AnalyticsService(self.ctx).snapshot_resilience(project, sim_id, "PROPAGATION")

    def _verified(self, sim_id: int) -> list[dict]:
        return [{"component_id": f["component_id"], "component_name": f["component_name"],
                 "failure_type": f["failure_type"], "failure_label": FAILURE_CLASSES[f["failure_type"]].label,
                 "severity": f["severity"], "description": f["description"]}
                for f in self.ctx.simulations.failures(sim_id)]

    def pause(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        self._require(sim, {"RUNNING"}, "pause")
        self.ctx.simulations.update(sim_id, status="PAUSED")
        self.ctx.publish(EventType.SIMULATION_PAUSED, f"Simulation paused at propagation step {sim['current_tick']}",
                         sim["project_id"], sim_id)
        return self.detail(sim_id)

    def resume(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        self._require(sim, {"PAUSED"}, "resume")
        self.ctx.simulations.update(sim_id, status="RUNNING")
        self.ctx.publish(EventType.SIMULATION_RESUMED, "Simulation resumed", sim["project_id"], sim_id)
        return self.detail(sim_id)

    def stop(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        self._require(sim, {"RUNNING", "PAUSED"}, "stop")
        project, _, _, result = self.rebuild(sim)
        self.ctx.publish(EventType.SIMULATION_STOPPED,
                         f"Simulation stopped at propagation step {sim['current_tick']} of {sim['max_tick']}",
                         project["id"], sim_id)
        self._finalise(sim_id, project, result, SimulationStatus.STOPPED)
        return self.detail(sim_id)

    def reset(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        project = self._project(sim)
        if sim["status"] == "CREATED":
            self.ctx.simulations.update(sim_id, status="RESET", completed_at=utcnow())
            return self.detail(sim_id)
        self.invoker.run(ResetSimulationCommand(self.ctx, project, simulation=sim))
        return self.detail(sim_id)

    def delete(self, sim_id: int) -> None:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if sim["status"] in {s.value for s in ACTIVE_SIMULATION_STATES}:
            raise conflict("Reset the simulation before deleting it", code="SIMULATION_ACTIVE")
        self.ctx.simulations.delete(sim_id)

    # -- read models ------------------------------------------------------------
    def detail(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        results = self.ctx.simulations.results(sim_id)
        tick = sim["current_tick"]
        revealed = [r for r in results if r["impact_type"] != "UNAFFECTED" and r["tick"] is not None
                    and r["tick"] <= tick]
        steps = sorted(revealed, key=lambda r: (r["tick"], r["component_name"]))
        plans = self.ctx.recovery.plans_for_simulation(sim_id)
        return {
            **{k: v for k, v in sim.items() if k not in ("impact_json", "root_cause_json")},
            "is_active": sim["status"] in {s.value for s in ACTIVE_SIMULATION_STATES},
            "failures": [{**f, "failure_label": FAILURE_CLASSES[f["failure_type"]].label}
                         for f in self.ctx.simulations.failures(sim_id)],
            "results": results,
            "revealed_component_ids": [r["component_id"] for r in revealed],
            "propagation_steps": [{"tick": r["tick"], "component_id": r["component_id"], "name": r["component_name"],
                                   "status": r["status"], "impact_type": r["impact_type"], "reason": r["reason"],
                                   "path": r["path"]} for r in steps],
            "progress": 1.0 if sim["max_tick"] == 0 and tick >= 0 else
                        (max(0, tick) / sim["max_tick"] if sim["max_tick"] else 0),
            "recovery_plans": [{"id": p["id"], "strategy_key": p["strategy_key"], "strategy_name": p["strategy_name"],
                                "status": p["status"], "is_selected": bool(p["is_selected"])} for p in plans],
            "notifications": self.ctx.notifications.items,
        }

    def analysis_state(self, sim_id: int):
        """Return (sim, arch, failures, result, up_to_tick) for analysis endpoints."""
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if sim["status"] == "CREATED":
            raise conflict("Start the simulation to analyse it", code="NOT_STARTED")
        project, arch, failures, result = self.rebuild(sim)
        return sim, arch, failures, result, revealed_tick(sim)

    def impact(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if sim["status"] in ("RESET", "RECOVERED") and sim["impact_json"]:
            return {**loads(sim["impact_json"]), "source": "stored", "simulation_status": sim["status"]}
        sim, arch, failures, result, up_to = self.analysis_state(sim_id)
        report = ImpactAnalyzer(arch).analyze(result, failures, sim["duration_minutes"], up_to_tick=up_to)
        report["propagation_edges"] = [e for e in result.propagation_edges
                                       if up_to is None or (result.outcomes[e["to"]].tick or 0) <= up_to]
        report["source"] = "live"
        report["simulation_status"] = sim["status"]
        return report

    def root_cause(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if sim["status"] in ("RESET", "RECOVERED") and sim["root_cause_json"]:
            return {**loads(sim["root_cause_json"]), "source": "stored"}
        sim, arch, failures, result, up_to = self.analysis_state(sim_id)
        rca = RootCauseAnalyzer(arch).analyze(result.statuses(up_to), self._verified(sim_id))
        rca["source"] = "live"
        return rca

    def timeline(self, sim_id: int) -> list[dict]:
        self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        return [e for e in self.ctx.events.for_simulation(sim_id) if e["category"] == "TIMELINE"]


def revealed_tick(sim: dict) -> int | None:
    """None = the whole cascade has been revealed; otherwise the last revealed step."""
    return None if sim["current_tick"] >= sim["max_tick"] else sim["current_tick"]


def statuses_from_rows(rows: list[dict]) -> dict[int, ComponentStatus]:
    return {r["component_id"]: ComponentStatus(r["status"]) for r in rows if r["component_id"] is not None}
