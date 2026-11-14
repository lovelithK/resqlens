"""Recovery planning and step-wise execution orchestration."""
from __future__ import annotations

from ..database import dumps, loads, utcnow
from ..domain.enums import ACTION_LABELS, AVAILABLE, ComponentStatus
from ..domain.models import DomainError
from ..engine.events import EventType
from ..engine.execution import RecoveryExecutor
from ..engine.recovery import STRATEGIES, RecoveryPlanner, get_strategy
from ..engine.resilience import weighted_health
from ..errors import AppError, conflict, invalid
from ..repositories import load_architecture
from .commands import CommandInvoker, RestoreComponentCommand
from .context import ServiceContext
from .simulation import SimulationService, revealed_tick

PLANNABLE = {"PROPAGATED", "STOPPED", "PARTIALLY_RECOVERED"}


def strategy_rows() -> list[dict]:
    return [{"key": cls.key, "name": cls.name, "description": cls.description, "guarantee": cls.guarantee}
            for cls in STRATEGIES.values()]


class RecoveryService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.sims = SimulationService(ctx)

    # -- planning ---------------------------------------------------------------
    def _planner(self, sim: dict) -> RecoveryPlanner:
        project, arch, failures, result = self.sims.rebuild(sim)
        if sim["status"] == "PARTIALLY_RECOVERED":
            statuses = arch.current_statuses()  # plan from what is still broken after the last attempt
        else:
            statuses = result.statuses(revealed_tick(sim))
        return RecoveryPlanner(arch, result, failures, statuses)

    def generate(self, sim_id: int, strategy_keys: list[str] | None = None) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        if sim["status"] not in PLANNABLE:
            raise conflict(f"Recovery plans can be generated once propagation has completed or been stopped "
                           f"(simulation is {sim['status']})", code="INVALID_STATE")
        if any(p["status"] in ("EXECUTING", "PAUSED") for p in self.ctx.recovery.plans_for_simulation(sim_id)):
            raise conflict("A recovery plan is currently executing", code="RECOVERY_IN_PROGRESS")
        planner = self._planner(sim)
        keys = strategy_keys or list(STRATEGIES)
        self.ctx.conn.execute("DELETE FROM recovery_plans WHERE simulation_id = ? AND status = 'DRAFT'", (sim_id,))
        try:
            for key in keys:
                plan = planner.generate(get_strategy(key))
                self._persist(sim_id, key, plan, manual=False)
        except DomainError as e:
            raise invalid(e.message, code=e.code)
        self.ctx.publish(EventType.RECOVERY_PLAN_GENERATED,
                         f"Recovery plan(s) generated: {', '.join(STRATEGIES[k].name for k in keys)}",
                         sim["project_id"], sim_id)
        return self.list_plans(sim_id)

    def _persist(self, sim_id: int, key: str, plan: dict, manual: bool, plan_id: int | None = None) -> int:
        values = dict(strategy_id=self.ctx.recovery.strategy_id(key), status="DRAFT", is_manual=int(manual),
                      is_valid=int(plan["is_valid"]), estimated_minutes=plan["metrics"]["estimated_minutes"],
                      total_cost=plan["metrics"]["total_cost"],
                      metrics_json=dumps({**plan["metrics"], "validation": plan["validation"]}))
        if plan_id is None:
            plan_id = self.ctx.recovery.create_plan({"simulation_id": sim_id, **values})
        else:
            self.ctx.recovery.update_plan(plan_id, **values)
        actions = [{**a, "explanation": {**a["explanation"], "step_start_minute": a["start_minute"],
                                         "step_end_minute": a["end_minute"],
                                         "restores_functionalities": a["restores_functionalities"],
                                         "unblocks": a["unblocks"]}} for a in plan["actions"]]
        self.ctx.recovery.replace_actions(plan_id, actions)
        return plan_id

    def list_plans(self, sim_id: int) -> dict:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        plans = [self._plan_view(p) for p in self.ctx.recovery.plans_for_simulation(sim_id)]
        return {"simulation_id": sim_id, "simulation_status": sim["status"], "plans": plans,
                "strategies": strategy_rows(), "notifications": self.ctx.notifications.items}

    def _plan_view(self, p: dict) -> dict:
        actions = self.ctx.recovery.actions(p["id"])
        for a in actions:
            a["action_label"] = ACTION_LABELS[a["action_type"]]
        metrics = loads(p["metrics_json"], {})
        return {
            "id": p["id"], "simulation_id": p["simulation_id"], "status": p["status"],
            "strategy": {"key": p["strategy_key"], "name": p["strategy_name"],
                         "description": p["strategy_description"], "guarantee": p["strategy_guarantee"]},
            "is_selected": bool(p["is_selected"]), "is_manual": bool(p["is_manual"]),
            "is_valid": bool(p["is_valid"]), "estimated_minutes": p["estimated_minutes"],
            "total_cost": p["total_cost"], "actual_minutes": p["actual_minutes"], "sim_clock": p["sim_clock"],
            "metrics": metrics, "validation": metrics.get("validation", {"valid": True, "violations": []}),
            "summary": loads(p["summary_json"]), "actions": actions,
            "created_at": p["created_at"], "started_at": p["started_at"], "completed_at": p["completed_at"],
        }

    def get(self, plan_id: int) -> dict:
        p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
        view = self._plan_view(p)
        view["notifications"] = self.ctx.notifications.items
        return view

    def select(self, plan_id: int) -> dict:
        p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
        if p["status"] != "DRAFT":
            raise conflict("Only draft plans can be selected", code="INVALID_STATE")
        self.ctx.conn.execute("UPDATE recovery_plans SET is_selected = 0 WHERE simulation_id = ?", (p["simulation_id"],))
        self.ctx.recovery.update_plan(plan_id, is_selected=1)
        self.ctx.publish(EventType.RECOVERY_PLAN_SELECTED, f"Recovery strategy selected: {p['strategy_name']}",
                         p["project_id"], p["simulation_id"])
        return self.get(plan_id)

    def reorder(self, plan_id: int, order: list[int], allow_invalid: bool) -> dict:
        p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
        if p["status"] != "DRAFT":
            raise conflict("Only draft plans can be modified", code="INVALID_STATE")
        sim = self.ctx.simulations.get_owned(p["simulation_id"], self.ctx.user_id)
        planner = self._planner(sim)
        plan = planner.evaluate_order(p["strategy_key"], order)
        if not plan["is_valid"] and not allow_invalid:
            raise invalid("The recovery sequence violates dependency rules", code="INVALID_RECOVERY_SEQUENCE",
                          details=plan["validation"]["violations"])
        missing = [v for v in plan["validation"]["violations"] if v["code"] in ("MISSING_ACTION", "UNKNOWN_ACTION",
                                                                               "DUPLICATE_ACTION")]
        if missing:
            raise invalid("The sequence must contain every required action exactly once",
                          code="INVALID_RECOVERY_SEQUENCE", details=missing)
        self._persist(sim["id"], p["strategy_key"], plan, manual=True, plan_id=plan_id)
        return self.get(plan_id)

    # -- execution ----------------------------------------------------------------
    def execute(self, plan_id: int, run_to_completion: bool = False) -> dict:
        p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
        if p["status"] in ("EXECUTING",):
            raise conflict("This plan is already executing – duplicate execution rejected", code="DUPLICATE_EXECUTION")
        if p["status"] != "DRAFT":
            raise conflict(f"Plan is {p['status']} and cannot be executed", code="INVALID_STATE")
        sim = self.ctx.simulations.get_owned(p["simulation_id"], self.ctx.user_id)
        if sim["status"] not in PLANNABLE:
            raise conflict(f"Simulation is {sim['status']}; recovery cannot start", code="INVALID_STATE")
        others = [x for x in self.ctx.recovery.plans_for_simulation(sim["id"]) if x["status"] in ("EXECUTING", "PAUSED")]
        if others:
            raise conflict("Another recovery plan is executing", code="RECOVERY_IN_PROGRESS")
        self.ctx.conn.execute("UPDATE recovery_plans SET is_selected = 0 WHERE simulation_id = ?", (sim["id"],))
        self.ctx.recovery.update_plan(plan_id, status="EXECUTING", is_selected=1, started_at=utcnow(), sim_clock=0,
                                      summary_json=dumps({"health_before": self._health(sim)}))
        self.ctx.simulations.update(sim["id"], status="RECOVERING")
        self.ctx.publish(EventType.RECOVERY_INITIATED,
                         f"Recovery initiated using {p['strategy_name']}"
                         + (" (manually modified sequence)" if p["is_manual"] else ""), sim["project_id"], sim["id"])
        if run_to_completion:
            while self.get(plan_id)["status"] == "EXECUTING":
                self.step(plan_id)
        return self.get(plan_id)

    def _health(self, sim: dict) -> float:
        project = self.ctx.projects.get_owned(sim["project_id"], self.ctx.user_id)
        return weighted_health(load_architecture(self.ctx.conn, project))

    def pause(self, plan_id: int) -> dict:
        p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
        if p["status"] != "EXECUTING":
            raise conflict("Only an executing plan can be paused", code="INVALID_STATE")
        self.ctx.recovery.update_plan(plan_id, status="PAUSED")
        self.ctx.publish(EventType.RECOVERY_PAUSED, "Recovery paused", p["project_id"], p["simulation_id"])
        return self.get(plan_id)

    def resume(self, plan_id: int) -> dict:
        p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
        if p["status"] != "PAUSED":
            raise conflict("Only a paused plan can be resumed", code="INVALID_STATE")
        self.ctx.recovery.update_plan(plan_id, status="EXECUTING")
        self.ctx.publish(EventType.RECOVERY_RESUMED, "Recovery resumed", p["project_id"], p["simulation_id"])
        return self.get(plan_id)

    def step(self, plan_id: int) -> dict:
        p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
        if p["status"] != "EXECUTING":
            raise conflict(f"Plan is {p['status']}; start or resume it first", code="INVALID_STATE")
        sim = self.ctx.simulations.get_owned(p["simulation_id"], self.ctx.user_id)
        project = self.ctx.projects.get_owned(sim["project_id"], self.ctx.user_id)
        actions = self.ctx.recovery.actions(plan_id)
        pending = [a for a in actions if a["status"] == "PENDING"]
        if not pending:
            return self._complete(p, sim, project)
        action = pending[0]
        arch = load_architecture(self.ctx.conn, {**project, "propagation_policy": sim["propagation_policy"]})
        executor = RecoveryExecutor(arch)
        n = action["component_name"]
        self.ctx.publish(EventType.RECOVERY_ACTION_STARTED,
                         f"{ACTION_LABELS[action['action_type']]} started on {n}", project["id"], sim["id"],
                         action["component_id"], category="RECOVERY")
        outcome = CommandInvoker(self.ctx).run(RestoreComponentCommand(self.ctx, project, executor=executor, action=action))
        comp = arch.components[action["component_id"]]
        start = p["sim_clock"]
        end = round(start + outcome.duration, 1)
        self.ctx.publish(EventType.COMPONENT_STATUS_CHANGED, f"{n} -> {comp.status.value}", project["id"], sim["id"],
                         comp.id, {"status": comp.status.value, "health": comp.health, "recovery": True})
        if outcome.success:
            self.ctx.recovery.update_action(action["id"], status="COMPLETED", attempts=action["attempts"] + 1,
                                            sim_start_minute=start, sim_end_minute=end,
                                            started_at=utcnow(), completed_at=utcnow(), failure_reason=None)
            self.ctx.publish(EventType.COMPONENT_RESTORED,
                             f"{n} restored ({ACTION_LABELS[action['action_type']]}) at simulated minute {end:g}",
                             project["id"], sim["id"], comp.id, {"sim_minute": end, "action": action["action_type"]})
        else:
            if action["attempts"] == 0:
                max_idx = max(a["order_index"] for a in actions)
                self.ctx.recovery.update_action(action["id"], attempts=1, order_index=max_idx + 1,
                                                failure_reason=outcome.reason, sim_start_minute=start,
                                                sim_end_minute=end, started_at=utcnow())
                msg = f"{n} could not be restored: {outcome.reason}. Re-queued for one retry at the end of the plan."
            else:
                self.ctx.recovery.update_action(action["id"], status="FAILED", attempts=action["attempts"] + 1,
                                                failure_reason=outcome.reason, sim_start_minute=start,
                                                sim_end_minute=end, completed_at=utcnow())
                msg = f"{n} recovery failed permanently: {outcome.reason}"
            self.ctx.publish(EventType.RECOVERY_ACTION_FAILED, msg, project["id"], sim["id"], comp.id,
                             {"sim_minute": end, "reason": outcome.reason}, category="RECOVERY")
        self.ctx.recovery.update_plan(plan_id, sim_clock=end)
        if not [a for a in self.ctx.recovery.actions(plan_id) if a["status"] == "PENDING"]:
            p = self.ctx.recovery.get_owned(plan_id, self.ctx.user_id)
            return self._complete(p, sim, project)
        return self.get(plan_id)

    def _complete(self, p: dict, sim: dict, project: dict) -> dict:
        actions = self.ctx.recovery.actions(p["id"])
        arch = load_architecture(self.ctx.conn, project)
        failed = [a for a in actions if a["status"] == "FAILED"]
        completed = [a for a in actions if a["status"] == "COMPLETED"]
        funcs = arch.functionality_status(arch.current_statuses())
        unhealthy = [c.name for c in arch.components.values()
                     if c.status not in AVAILABLE or c.status != c.baseline_status]
        before = loads(p["summary_json"], {}) or {}
        summary = {
            "actions_total": len(actions), "actions_completed": len(completed), "actions_failed": len(failed),
            "failed_actions": [{"component": a["component_name"], "reason": a["failure_reason"]} for a in failed],
            "retried_actions": sum(1 for a in actions if a["attempts"] > 1),
            "estimated_minutes": p["estimated_minutes"], "actual_minutes": p["sim_clock"],
            "health_before": before.get("health_before"), "health_after": weighted_health(arch),
            "functionalities_available": sum(1 for f in funcs if f["status"] == "AVAILABLE"),
            "functionalities_total": len(funcs), "functionalities": funcs,
            "still_unhealthy": unhealthy,
        }
        status = "COMPLETED" if not failed and not unhealthy else "COMPLETED_WITH_FAILURES"
        self.ctx.recovery.update_plan(p["id"], status=status, completed_at=utcnow(), actual_minutes=p["sim_clock"],
                                      summary_json=dumps(summary))
        sim_status = "RECOVERED" if status == "COMPLETED" else "PARTIALLY_RECOVERED"
        self.ctx.simulations.update(sim["id"], status=sim_status, completed_at=utcnow())
        if status == "COMPLETED":
            self.ctx.publish(EventType.SYSTEM_RECOVERED,
                             f"System recovered: {len(completed)} action(s) in {p['sim_clock']:g} simulated minutes "
                             f"(estimated {p['estimated_minutes']:g})", project["id"], sim["id"], details=summary)
        else:
            self.ctx.publish(EventType.RECOVERY_INCOMPLETE,
                             f"Recovery finished with {len(failed)} failed action(s); still unhealthy: "
                             f"{', '.join(unhealthy) or '-'}", project["id"], sim["id"], details=summary)
        from .analytics import AnalyticsService
        AnalyticsService(self.ctx).snapshot_resilience(project, sim["id"], "RECOVERY")
        return self.get(p["id"])
