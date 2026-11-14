"""Resilience scorecard, SPOF detection, what-if comparison, symptom diagnosis
and dashboard aggregation – all computed from persisted application data."""
from __future__ import annotations

from ..database import loads
from ..domain.enums import ACTIVE_SIMULATION_STATES, ComponentStatus
from ..domain.failures import create_failure
from ..domain.models import DomainError
from ..engine.dependency_manager import DependencyManager
from ..engine.impact import ImpactAnalyzer
from ..engine.propagation import FailurePropagationEngine
from ..engine.recovery import DependencyFirstStrategy, RecoveryPlanner
from ..engine.resilience import SPOFDetector, get_scoring_model, health_distribution, weighted_health
from ..engine.root_cause import RootCauseAnalyzer
from ..errors import invalid
from ..repositories import load_architecture
from .context import ServiceContext


class AnalyticsService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    # -- resilience ---------------------------------------------------------------
    def _recovery_stats(self, project_id: int) -> dict | None:
        plan = self.ctx.recovery.latest_executed_plan(project_id)
        if not plan:
            return None
        actions = self.ctx.recovery.actions(plan["id"])
        attempted = len(actions)
        successful = sum(1 for a in actions if a["status"] == "COMPLETED")
        return {"plan_id": plan["id"], "attempted": attempted, "successful": successful,
                "estimated_minutes": plan["estimated_minutes"], "actual_minutes": plan["actual_minutes"] or 0}

    def resilience(self, project: dict, model: str = "OPERATIONAL") -> dict:
        arch = load_architecture(self.ctx.conn, project)
        if not arch.components:
            return {"empty": True, "score": None, "grade": "-", "breakdown": [], "spof": [],
                    "message": "Add components to compute a resilience score."}
        dm = DependencyManager(arch)
        validation = dm.validate()
        try:
            spof = SPOFDetector(arch).analyze()
        except DomainError:
            spof = []
        stats = self._recovery_stats(project["id"])
        try:
            scoring = get_scoring_model(model)
        except DomainError as e:
            raise invalid(e.message, code=e.code)
        report = scoring.score(arch, spof, stats)

        sims = self.ctx.conn.all("SELECT severity_class, COUNT(*) AS n FROM simulations WHERE project_id = ? "
                                 "AND severity_class IS NOT NULL GROUP BY severity_class", (project["id"],))
        impact_dist = {k: 0 for k in ("LOW", "MODERATE", "HIGH", "CRITICAL")}
        for r in sims:
            impact_dist[r["severity_class"]] = r["n"]
        latest = self.ctx.recovery.latest_executed_plan(project["id"])
        return {
            **report,
            "project_id": project["id"],
            "health_distribution": health_distribution(arch),
            "weighted_health": weighted_health(arch),
            "architecture": dm.stats(),
            "critical_dependency_count": dm.stats()["critical_dependency_count"],
            "single_points_of_failure": [r for r in spof if r["is_spof"]],
            "spof": spof,
            "impact_distribution": impact_dist,
            "recovery": {
                "efficiency": next((b["value"] for b in report["breakdown"] if b["key"] == "recovery"), None),
                "estimated_minutes": latest["estimated_minutes"] if latest else None,
                "actual_minutes": latest["actual_minutes"] if latest else None,
                "successful_operations": self.ctx.recovery.completed_action_count(project["id"]),
                "executed_plans": self.ctx.conn.scalar(
                    """SELECT COUNT(*) FROM recovery_plans rp JOIN simulations s ON s.id = rp.simulation_id
                       WHERE s.project_id = ? AND rp.status IN ('COMPLETED','COMPLETED_WITH_FAILURES')""",
                    (project["id"],)),
            },
            "validation": validation,
            "history": self.ctx.resilience.history(project["id"]),
        }

    def snapshot_resilience(self, project: dict, simulation_id: int | None, trigger: str) -> None:
        report = self.resilience(project)
        if report.get("score") is not None:
            slim = {k: report[k] for k in ("score", "grade", "breakdown", "model", "weighted_health")}
            self.ctx.resilience.add(project["id"], simulation_id, trigger, slim)

    def spof(self, project: dict) -> list[dict]:
        return SPOFDetector(load_architecture(self.ctx.conn, project)).analyze()

    # -- what-if ------------------------------------------------------------------
    def what_if(self, project: dict, scenarios: list[dict]) -> list[dict]:
        arch = load_architecture(self.ctx.conn, project)
        report = DependencyManager(arch).validate()
        if not report["valid"]:
            raise invalid("Architecture validation failed", code="INVALID_ARCHITECTURE", details=report["issues"])
        engine = FailurePropagationEngine(arch)
        out = []
        for sc in scenarios:
            try:
                failures = [create_failure(f["failure_type"], f["component_id"], f["severity"]) for f in sc["failures"]]
                for f in failures:
                    if f.component_id not in arch.components:
                        raise DomainError("Scenario references a component outside this project", code="NOT_FOUND")
                result = engine.propagate(failures)
            except DomainError as e:
                raise invalid(f"Scenario '{sc['name']}': {e.message}", code=e.code)
            impact = ImpactAnalyzer(arch).analyze(result, failures, sc.get("duration_minutes", 30))
            crit = [f for f in impact["functionalities"] if f["is_critical"]]
            plan_metrics = {"estimated_minutes": 0, "total_cost": 0, "critical_functionality_restored_at": 0,
                            "functionality_downtime_minutes": 0}
            try:
                plan = RecoveryPlanner(arch, result, failures).generate(DependencyFirstStrategy())
                plan_metrics = plan["metrics"]
            except DomainError:
                pass
            out.append({
                "name": sc["name"],
                "failures": [{"component": arch.name_of(f.component_id), "failure_type": f.failure_type.value,
                              "label": f.label, "severity": f.severity} for f in failures],
                "affected_components": impact["total_affected"],
                "direct": impact["direct_count"], "indirect": impact["indirect_count"],
                "impact_score": impact["impact_score"], "severity_class": impact["severity_class"],
                "critical_functionality_available": sum(1 for f in crit if f["status"] == "AVAILABLE"),
                "critical_functionality_total": len(crit),
                "unavailable_functionalities": [f["name"] for f in impact["functionalities"] if f["status"] == "UNAVAILABLE"],
                "recovery_minutes": plan_metrics["estimated_minutes"],
                "recovery_cost": plan_metrics["total_cost"],
                "critical_restored_at": plan_metrics["critical_functionality_restored_at"],
                "affected_names": [c["name"] for c in impact["components"]],
            })
        return out

    def diagnose(self, project: dict, observed: list[int]) -> dict:
        arch = load_architecture(self.ctx.conn, project)
        try:
            return RootCauseAnalyzer(arch).diagnose(observed)
        except DomainError as e:
            raise invalid(e.message, code=e.code)

    # -- dashboard ---------------------------------------------------------------
    def dashboard(self) -> dict:
        uid = self.ctx.user_id
        projects = self.ctx.projects.list_for_user(uid)
        comp_rows = self.ctx.conn.all("""SELECT sc.status FROM system_components sc JOIN projects p ON p.id = sc.project_id
                                         WHERE p.owner_id = ?""", (uid,))
        dist = {s.value: 0 for s in ComponentStatus}
        for r in comp_rows:
            dist[r["status"]] += 1
        active_states = tuple(s.value for s in ACTIVE_SIMULATION_STATES)
        active = self.ctx.conn.scalar(
            f"""SELECT COUNT(*) FROM simulations s JOIN projects p ON p.id = s.project_id WHERE p.owner_id = ?
                AND s.status IN ({','.join('?' for _ in active_states)})""", (uid, *active_states))
        recovery_ops = self.ctx.conn.one(
            """SELECT COUNT(*) AS plans,
                 SUM(CASE WHEN rp.status = 'COMPLETED' THEN 1 ELSE 0 END) AS successful,
                 (SELECT COUNT(*) FROM recovery_actions a JOIN recovery_plans rp2 ON rp2.id = a.plan_id
                    JOIN simulations s2 ON s2.id = rp2.simulation_id JOIN projects p2 ON p2.id = s2.project_id
                    WHERE p2.owner_id = ? AND a.status = 'COMPLETED') AS actions
               FROM recovery_plans rp JOIN simulations s ON s.id = rp.simulation_id JOIN projects p ON p.id = s.project_id
               WHERE p.owner_id = ? AND rp.status IN ('COMPLETED','COMPLETED_WITH_FAILURES','EXECUTING','PAUSED')""",
            (uid, uid))
        scores = []
        overview = []
        for p in projects:
            res = self.resilience(p) if p["component_count"] else None
            if res and res.get("score") is not None:
                scores.append(res["score"])
            overview.append({"id": p["id"], "name": p["name"], "component_count": p["component_count"],
                             "failed_count": p["failed_count"], "current_health": p["current_health"],
                             "resilience_score": res["score"] if res else None,
                             "resilience_grade": res["grade"] if res else None,
                             "spof_count": len(res["single_points_of_failure"]) if res else 0,
                             "active_simulation": (self.ctx.simulations.active_for_project(p["id"]) or {}).get("name")})
        recent = self.ctx.simulations.search(uid, limit=6)
        return {
            "totals": {
                "projects": len(projects), "components": len(comp_rows),
                "active_incidents": active or 0,
                "failed_components": dist["FAILED"] + dist["BLOCKED"],
                "degraded_components": dist["DEGRADED"] + dist["RECOVERING"],
                "healthy_components": dist["HEALTHY"],
                "recovery_operations": (recovery_ops or {}).get("plans") or 0,
                "successful_recoveries": (recovery_ops or {}).get("successful") or 0,
                "recovery_actions_completed": (recovery_ops or {}).get("actions") or 0,
                "resilience_score": round(sum(scores) / len(scores), 1) if scores else None,
                "simulations": self.ctx.conn.scalar("""SELECT COUNT(*) FROM simulations s JOIN projects p
                                                       ON p.id = s.project_id WHERE p.owner_id = ?""", (uid,)),
            },
            "status_distribution": dist,
            "projects": overview,
            "recent_simulations": [{k: r[k] for k in ("id", "name", "project_id", "project_name", "status",
                                                      "failure_type", "impact_score", "severity_class", "created_at",
                                                      "affected_count", "failure_sources")} for r in recent],
            "recent_activity": self.ctx.events.recent_for_user(uid, limit=12),
        }

    # -- history comparison ---------------------------------------------------------
    def compare_simulations(self, sim_ids: list[int]) -> list[dict]:
        out = []
        for sid in sim_ids:
            sim = self.ctx.simulations.get_owned(sid, self.ctx.user_id)
            impact = loads(sim["impact_json"], {}) or {}
            plans = self.ctx.recovery.plans_for_simulation(sid)
            executed = next((p for p in plans if p["status"] in ("COMPLETED", "COMPLETED_WITH_FAILURES")), None)
            selected = executed or next((p for p in plans if p["is_selected"]), None)
            crit = [f for f in impact.get("functionalities", []) if f["is_critical"]]
            out.append({
                "id": sid, "name": sim["name"], "status": sim["status"], "failure_type": sim["failure_type"],
                "sources": [f["component_name"] for f in self.ctx.simulations.failures(sid)],
                "impact_score": sim["impact_score"], "severity_class": sim["severity_class"],
                "affected_components": impact.get("total_affected"),
                "critical_functionality_available": sum(1 for f in crit if f["status"] == "AVAILABLE"),
                "critical_functionality_total": len(crit),
                "strategy": selected["strategy_name"] if selected else None,
                "estimated_minutes": selected["estimated_minutes"] if selected else None,
                "actual_minutes": executed["actual_minutes"] if executed else None,
                "recovery_cost": selected["total_cost"] if selected else None,
                "created_at": sim["created_at"],
            })
        return out
