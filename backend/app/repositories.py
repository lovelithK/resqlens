"""Data-access layer: repository classes that encapsulate all SQL.

Repositories return plain dicts (rows). Mapping rows to domain objects is done
in ``services.architecture``. Every query is parameterised.
"""
from __future__ import annotations

from .database import Connection, dumps, loads, utcnow
from .domain.models import Component, Dependency, Functionality, SystemArchitecture
from .domain.enums import DependencyType


class NotFound(Exception):
    def __init__(self, what: str):
        super().__init__(f"{what} not found")
        self.what = what


class UserRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def by_email(self, email: str) -> dict | None:
        return self.c.one("SELECT * FROM users WHERE lower(email) = lower(?)", (email,))

    def get(self, user_id: int) -> dict | None:
        return self.c.one("SELECT id, email, full_name, created_at FROM users WHERE id = ?", (user_id,))

    def create(self, email: str, full_name: str, password_hash: str) -> int:
        return self.c.insert("users", {"email": email.lower(), "full_name": full_name,
                                       "password_hash": password_hash, "created_at": utcnow()})

    def update(self, user_id: int, **values) -> None:
        self.c.update("users", user_id, values)

    def password_hash(self, user_id: int) -> str:
        return self.c.scalar("SELECT password_hash FROM users WHERE id = ?", (user_id,))

    # sessions
    def add_session(self, jti: str, user_id: int, expires_at: str) -> None:
        self.c.insert("user_sessions", {"jti": jti, "user_id": user_id, "created_at": utcnow(),
                                        "expires_at": expires_at})

    def session_exists(self, jti: str) -> bool:
        return self.c.one("SELECT jti FROM user_sessions WHERE jti = ?", (jti,)) is not None

    def delete_session(self, jti: str) -> None:
        self.c.execute("DELETE FROM user_sessions WHERE jti = ?", (jti,))


class ProjectRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def list_for_user(self, user_id: int) -> list[dict]:
        return self.c.all("""
            SELECT p.*,
              (SELECT COUNT(*) FROM system_components sc WHERE sc.project_id = p.id) AS component_count,
              (SELECT COUNT(*) FROM dependencies d WHERE d.project_id = p.id) AS dependency_count,
              (SELECT COUNT(*) FROM simulations s WHERE s.project_id = p.id) AS simulation_count,
              (SELECT COUNT(*) FROM system_components sc WHERE sc.project_id = p.id AND sc.status IN ('FAILED','BLOCKED')) AS failed_count
            FROM projects p WHERE p.owner_id = ? ORDER BY COALESCE(p.last_activity_at, p.created_at) DESC""", (user_id,))

    def get_owned(self, project_id: int, user_id: int) -> dict:
        row = self.c.one("SELECT * FROM projects WHERE id = ? AND owner_id = ?", (project_id, user_id))
        if not row:
            raise NotFound("Project")
        return row

    def create(self, owner_id: int, name: str, description: str, policy: str) -> int:
        now = utcnow()
        return self.c.insert("projects", {"owner_id": owner_id, "name": name, "description": description,
                                          "propagation_policy": policy, "created_at": now, "updated_at": now,
                                          "last_activity_at": now})

    def update(self, project_id: int, **values) -> None:
        values["updated_at"] = utcnow()
        self.c.update("projects", project_id, values)

    def delete(self, project_id: int) -> None:
        self.c.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def name_taken(self, owner_id: int, name: str, exclude_id: int | None = None) -> bool:
        return self.c.one("SELECT id FROM projects WHERE owner_id = ? AND lower(name) = lower(?) AND id != ?",
                          (owner_id, name, exclude_id or -1)) is not None


class ComponentRepository:
    COLUMNS = ("name", "component_type", "description", "status", "health", "baseline_status", "baseline_health",
               "criticality", "recovery_priority", "estimated_recovery_minutes", "recovery_cost",
               "operating_rule", "pos_x", "pos_y")

    def __init__(self, conn: Connection):
        self.c = conn

    def list(self, project_id: int) -> list[dict]:
        return self.c.all("SELECT * FROM system_components WHERE project_id = ? ORDER BY id", (project_id,))

    def get(self, component_id: int) -> dict:
        row = self.c.one("SELECT * FROM system_components WHERE id = ?", (component_id,))
        if not row:
            raise NotFound("Component")
        return row

    def get_owned(self, component_id: int, user_id: int) -> dict:
        row = self.c.one("""SELECT sc.* FROM system_components sc JOIN projects p ON p.id = sc.project_id
                            WHERE sc.id = ? AND p.owner_id = ?""", (component_id, user_id))
        if not row:
            raise NotFound("Component")
        return row

    def create(self, project_id: int, values: dict, component_id: int | None = None) -> int:
        now = utcnow()
        row = {k: values[k] for k in self.COLUMNS if k in values}
        row.update({"project_id": project_id, "created_at": values.get("created_at", now), "updated_at": now})
        row.setdefault("status", row.get("baseline_status", "HEALTHY"))
        row.setdefault("health", row.get("baseline_health", 100))
        if component_id is not None:
            row["id"] = component_id
        return self.c.insert("system_components", row)

    def update(self, component_id: int, values: dict) -> None:
        row = {k: v for k, v in values.items() if k in self.COLUMNS}
        row["updated_at"] = utcnow()
        self.c.update("system_components", component_id, row)

    def set_state(self, component_id: int, status: str, health: float) -> None:
        self.c.execute("UPDATE system_components SET status = ?, health = ? WHERE id = ?",
                       (status, health, component_id))

    def reset_project(self, project_id: int) -> None:
        self.c.execute("UPDATE system_components SET status = baseline_status, health = baseline_health "
                       "WHERE project_id = ?", (project_id,))

    def delete(self, component_id: int) -> None:
        self.c.execute("DELETE FROM system_components WHERE id = ?", (component_id,))

    def name_taken(self, project_id: int, name: str, exclude_id: int | None = None) -> bool:
        return self.c.one("SELECT id FROM system_components WHERE project_id = ? AND lower(name) = lower(?) "
                          "AND id != ?", (project_id, name, exclude_id or -1)) is not None


class DependencyRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def list(self, project_id: int) -> list[dict]:
        return self.c.all("SELECT * FROM dependencies WHERE project_id = ? ORDER BY id", (project_id,))

    def get_owned(self, dependency_id: int, user_id: int) -> dict:
        row = self.c.one("""SELECT d.* FROM dependencies d JOIN projects p ON p.id = d.project_id
                            WHERE d.id = ? AND p.owner_id = ?""", (dependency_id, user_id))
        if not row:
            raise NotFound("Dependency")
        return row

    def find(self, source_id: int, target_id: int) -> dict | None:
        return self.c.one("SELECT * FROM dependencies WHERE source_component_id = ? AND target_component_id = ?",
                          (source_id, target_id))

    def for_component(self, component_id: int) -> list[dict]:
        return self.c.all("SELECT * FROM dependencies WHERE source_component_id = ? OR target_component_id = ? "
                          "OR fallback_component_id = ?", (component_id, component_id, component_id))

    def create(self, project_id: int, source: int, target: int, dep_type: str, fallback: int | None,
               description: str = "", dependency_id: int | None = None) -> int:
        row = {"project_id": project_id, "source_component_id": source, "target_component_id": target,
               "dependency_type": dep_type, "fallback_component_id": fallback, "description": description,
               "created_at": utcnow()}
        if dependency_id is not None:
            row["id"] = dependency_id
        return self.c.insert("dependencies", row)

    def update(self, dependency_id: int, values: dict) -> None:
        self.c.update("dependencies", dependency_id, values)

    def delete(self, dependency_id: int) -> None:
        self.c.execute("DELETE FROM dependencies WHERE id = ?", (dependency_id,))


class FunctionalityRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def list(self, project_id: int) -> list[dict]:
        rows = self.c.all("SELECT * FROM functionalities WHERE project_id = ? ORDER BY id", (project_id,))
        links = self.c.all("""SELECT fc.functionality_id, fc.component_id FROM functionality_components fc
                              JOIN functionalities f ON f.id = fc.functionality_id WHERE f.project_id = ?""",
                           (project_id,))
        by_func: dict[int, list[int]] = {}
        for link in links:
            by_func.setdefault(link["functionality_id"], []).append(link["component_id"])
        for r in rows:
            r["component_ids"] = sorted(by_func.get(r["id"], []))
            r["is_critical"] = bool(r["is_critical"])
        return rows

    def get_owned(self, func_id: int, user_id: int) -> dict:
        row = self.c.one("""SELECT f.* FROM functionalities f JOIN projects p ON p.id = f.project_id
                            WHERE f.id = ? AND p.owner_id = ?""", (func_id, user_id))
        if not row:
            raise NotFound("Functionality")
        return row

    def create(self, project_id: int, name: str, description: str, is_critical: bool, component_ids: list[int]) -> int:
        fid = self.c.insert("functionalities", {"project_id": project_id, "name": name, "description": description,
                                                "is_critical": int(is_critical), "created_at": utcnow()})
        self.set_components(fid, component_ids)
        return fid

    def update(self, func_id: int, values: dict) -> None:
        comp_ids = values.pop("component_ids", None)
        if "is_critical" in values:
            values["is_critical"] = int(values["is_critical"])
        self.c.update("functionalities", func_id, values)
        if comp_ids is not None:
            self.set_components(func_id, comp_ids)

    def set_components(self, func_id: int, component_ids: list[int]) -> None:
        self.c.execute("DELETE FROM functionality_components WHERE functionality_id = ?", (func_id,))
        for cid in dict.fromkeys(component_ids):
            self.c.insert("functionality_components", {"functionality_id": func_id, "component_id": cid})

    def links_for_component(self, component_id: int) -> list[int]:
        return [r["functionality_id"] for r in self.c.all(
            "SELECT functionality_id FROM functionality_components WHERE component_id = ?", (component_id,))]

    def delete(self, func_id: int) -> None:
        self.c.execute("DELETE FROM functionalities WHERE id = ?", (func_id,))


class ScenarioRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def list(self, project_id: int) -> list[dict]:
        rows = self.c.all("SELECT * FROM scenarios WHERE project_id = ? ORDER BY id", (project_id,))
        for r in rows:
            r["failures"] = loads(r.pop("failures_json"), [])
        return rows

    def get_owned(self, scenario_id: int, user_id: int) -> dict:
        row = self.c.one("""SELECT s.* FROM scenarios s JOIN projects p ON p.id = s.project_id
                            WHERE s.id = ? AND p.owner_id = ?""", (scenario_id, user_id))
        if not row:
            raise NotFound("Scenario")
        row["failures"] = loads(row.pop("failures_json"), [])
        return row

    def create(self, project_id: int, name: str, description: str, failures: list[dict], duration: float) -> int:
        return self.c.insert("scenarios", {"project_id": project_id, "name": name, "description": description,
                                           "failures_json": dumps(failures), "duration_minutes": duration,
                                           "created_at": utcnow()})

    def delete(self, scenario_id: int) -> None:
        self.c.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))


class SimulationRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def get_owned(self, sim_id: int, user_id: int) -> dict:
        row = self.c.one("""SELECT s.*, p.name AS project_name FROM simulations s JOIN projects p ON p.id = s.project_id
                            WHERE s.id = ? AND p.owner_id = ?""", (sim_id, user_id))
        if not row:
            raise NotFound("Simulation")
        return row

    def active_for_project(self, project_id: int) -> dict | None:
        return self.c.one("""SELECT * FROM simulations WHERE project_id = ? AND status IN
                             ('RUNNING','PAUSED','PROPAGATED','STOPPED','RECOVERING','PARTIALLY_RECOVERED')
                             ORDER BY id DESC LIMIT 1""", (project_id,))

    def create(self, values: dict) -> int:
        values = {**values, "created_at": utcnow()}
        return self.c.insert("simulations", values)

    def update(self, sim_id: int, **values) -> None:
        self.c.update("simulations", sim_id, values)

    def delete(self, sim_id: int) -> None:
        self.c.execute("DELETE FROM simulations WHERE id = ?", (sim_id,))

    def search(self, user_id: int, project_id: int | None = None, severity: str | None = None,
               date_from: str | None = None, date_to: str | None = None, status: str | None = None,
               limit: int = 200) -> list[dict]:
        sql = [f"""SELECT s.*, p.name AS project_name,
                    (SELECT COUNT(*) FROM simulation_results r WHERE r.simulation_id = s.id
                       AND r.impact_type != 'UNAFFECTED') AS affected_count,
                    (SELECT {self.c.group_concat('component_name')} FROM failure_events f WHERE f.simulation_id = s.id) AS failure_sources,
                    (SELECT rs.name FROM recovery_plans rp JOIN recovery_strategies rs ON rs.id = rp.strategy_id
                       WHERE rp.simulation_id = s.id AND rp.is_selected = 1 ORDER BY rp.id DESC LIMIT 1) AS selected_strategy
                  FROM simulations s JOIN projects p ON p.id = s.project_id WHERE p.owner_id = ?"""]
        params: list = [user_id]
        if project_id:
            sql.append("AND s.project_id = ?"); params.append(project_id)
        if severity:
            sql.append("AND s.severity_class = ?"); params.append(severity)
        if status:
            sql.append("AND s.status = ?"); params.append(status)
        if date_from:
            sql.append("AND s.created_at >= ?"); params.append(date_from)
        if date_to:
            sql.append("AND s.created_at <= ?"); params.append(date_to + "T23:59:59" if len(date_to) == 10 else date_to)
        sql.append("ORDER BY s.created_at DESC, s.id DESC LIMIT ?"); params.append(limit)
        return self.c.all(" ".join(sql), params)

    # failure events ---------------------------------------------------------
    def add_failure(self, sim_id: int, component: dict, failure_type: str, severity: int, description: str,
                    resulting_status: str) -> int:
        return self.c.insert("failure_events", {
            "simulation_id": sim_id, "component_id": component["id"], "component_name": component["name"],
            "failure_type": failure_type, "severity": severity, "description": description,
            "resulting_status": resulting_status, "created_at": utcnow()})

    def failures(self, sim_id: int) -> list[dict]:
        return self.c.all("SELECT * FROM failure_events WHERE simulation_id = ? ORDER BY id", (sim_id,))

    # results ------------------------------------------------------------------
    def save_results(self, sim_id: int, outcomes: list[dict]) -> None:
        self.c.execute("DELETE FROM simulation_results WHERE simulation_id = ?", (sim_id,))
        for o in outcomes:
            self.c.insert("simulation_results", {
                "simulation_id": sim_id, "component_id": o["component_id"], "component_name": o["name"],
                "criticality": o["criticality"], "status": o["status"], "health": o["health"],
                "impact_type": o["impact_type"], "depth": o["depth"], "tick": o["tick"], "reason": o["reason"],
                "causes_json": dumps(o["causes"]), "path_json": dumps(o["path"]), "notes_json": dumps(o["notes"])})

    def results(self, sim_id: int) -> list[dict]:
        rows = self.c.all("SELECT * FROM simulation_results WHERE simulation_id = ? ORDER BY COALESCE(tick, 999), component_name",
                          (sim_id,))
        for r in rows:
            r["causes"] = loads(r.pop("causes_json"), [])
            r["path"] = loads(r.pop("path_json"), [])
            r["notes"] = loads(r.pop("notes_json"), [])
        return rows


class RecoveryRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def strategies(self) -> list[dict]:
        return self.c.all("SELECT * FROM recovery_strategies ORDER BY id")

    def strategy_id(self, key: str) -> int:
        return self.c.scalar("SELECT id FROM recovery_strategies WHERE `key` = ?", (key,))

    def ensure_strategies(self, rows: list[dict]) -> None:
        for r in rows:
            existing = self.c.one("SELECT id FROM recovery_strategies WHERE `key` = ?", (r["key"],))
            if existing:
                self.c.update("recovery_strategies", existing["id"], {k: v for k, v in r.items() if k != "key"})
            else:
                self.c.insert("recovery_strategies", r)

    def plans_for_simulation(self, sim_id: int) -> list[dict]:
        return self.c.all("""SELECT rp.*, rs.`key` AS strategy_key, rs.name AS strategy_name,
                               rs.description AS strategy_description, rs.guarantee AS strategy_guarantee
                             FROM recovery_plans rp JOIN recovery_strategies rs ON rs.id = rp.strategy_id
                             WHERE rp.simulation_id = ? ORDER BY rp.id""", (sim_id,))

    def get_owned(self, plan_id: int, user_id: int) -> dict:
        row = self.c.one("""SELECT rp.*, rs.`key` AS strategy_key, rs.name AS strategy_name,
                               rs.description AS strategy_description, rs.guarantee AS strategy_guarantee,
                               s.project_id
                             FROM recovery_plans rp JOIN recovery_strategies rs ON rs.id = rp.strategy_id
                             JOIN simulations s ON s.id = rp.simulation_id JOIN projects p ON p.id = s.project_id
                             WHERE rp.id = ? AND p.owner_id = ?""", (plan_id, user_id))
        if not row:
            raise NotFound("Recovery plan")
        return row

    def create_plan(self, values: dict) -> int:
        return self.c.insert("recovery_plans", {**values, "created_at": utcnow()})

    def update_plan(self, plan_id: int, **values) -> None:
        self.c.update("recovery_plans", plan_id, values)

    def actions(self, plan_id: int) -> list[dict]:
        rows = self.c.all("SELECT * FROM recovery_actions WHERE plan_id = ? ORDER BY order_index", (plan_id,))
        for r in rows:
            r["prerequisites"] = loads(r.pop("prerequisites_json"), [])
            r["explanation"] = loads(r.pop("explanation_json"), {})
        return rows

    def replace_actions(self, plan_id: int, actions: list[dict]) -> None:
        self.c.execute("DELETE FROM recovery_actions WHERE plan_id = ?", (plan_id,))
        for idx, a in enumerate(actions):
            self.c.insert("recovery_actions", {
                "plan_id": plan_id, "component_id": a["component_id"], "component_name": a["component_name"],
                "order_index": idx, "action_type": a["action_type"], "estimated_minutes": a["estimated_minutes"],
                "cost": a["cost"], "prerequisites_json": dumps(a["prerequisites"]),
                "explanation_json": dumps(a["explanation"]), "status": "PENDING"})

    def update_action(self, action_id: int, **values) -> None:
        self.c.update("recovery_actions", action_id, values)

    def completed_action_count(self, project_id: int) -> int:
        return self.c.scalar("""SELECT COUNT(*) FROM recovery_actions a JOIN recovery_plans rp ON rp.id = a.plan_id
                                JOIN simulations s ON s.id = rp.simulation_id
                                WHERE s.project_id = ? AND a.status = 'COMPLETED'""", (project_id,)) or 0

    def latest_executed_plan(self, project_id: int) -> dict | None:
        return self.c.one("""SELECT rp.* FROM recovery_plans rp JOIN simulations s ON s.id = rp.simulation_id
                             WHERE s.project_id = ? AND rp.status IN ('COMPLETED','COMPLETED_WITH_FAILURES')
                             ORDER BY rp.completed_at DESC, rp.id DESC LIMIT 1""", (project_id,))


class EventLogRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def add(self, project_id: int, event_type: str, message: str, simulation_id: int | None = None,
            component_id: int | None = None, details: dict | None = None, category: str = "SYSTEM",
            created_at: str | None = None) -> int:
        return self.c.insert("event_logs", {
            "project_id": project_id, "simulation_id": simulation_id, "component_id": component_id,
            "event_type": event_type, "category": category, "message": message,
            "details_json": dumps(details or {}), "created_at": created_at or utcnow()})

    def for_simulation(self, sim_id: int) -> list[dict]:
        rows = self.c.all("SELECT * FROM event_logs WHERE simulation_id = ? ORDER BY id", (sim_id,))
        for r in rows:
            r["details"] = loads(r.pop("details_json"), {})
        return rows

    def recent_for_user(self, user_id: int, project_id: int | None = None, limit: int = 30,
                        exclude_types: tuple[str, ...] = ("COMPONENT_STATUS_CHANGED",)) -> list[dict]:
        sql = """SELECT e.*, p.name AS project_name FROM event_logs e JOIN projects p ON p.id = e.project_id
                 WHERE p.owner_id = ?"""
        params: list = [user_id]
        if project_id:
            sql += " AND e.project_id = ?"
            params.append(project_id)
        if exclude_types:
            sql += f" AND e.event_type NOT IN ({','.join('?' for _ in exclude_types)})"
            params.extend(exclude_types)
        sql += " ORDER BY e.id DESC LIMIT ?"
        params.append(limit)
        rows = self.c.all(sql, params)
        for r in rows:
            r["details"] = loads(r.pop("details_json"), {})
        return rows


class ResilienceRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def add(self, project_id: int, simulation_id: int | None, trigger: str, report: dict) -> int:
        return self.c.insert("resilience_reports", {
            "project_id": project_id, "simulation_id": simulation_id, "trigger": trigger,
            "score": report["score"], "grade": report["grade"], "breakdown_json": dumps(report),
            "created_at": utcnow()})

    def history(self, project_id: int, limit: int = 30) -> list[dict]:
        rows = self.c.all("""SELECT id, simulation_id, `trigger`, score, grade, created_at FROM resilience_reports
                             WHERE project_id = ? ORDER BY id DESC LIMIT ?""", (project_id, limit))
        return list(reversed(rows))

    def latest(self, project_id: int) -> dict | None:
        return self.c.one("SELECT * FROM resilience_reports WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,))


class CommandLogRepository:
    def __init__(self, conn: Connection):
        self.c = conn

    def add(self, project_id: int, user_id: int, name: str, description: str, payload: dict,
            undo: dict | None, undoable: bool) -> int:
        return self.c.insert("command_log", {
            "project_id": project_id, "user_id": user_id, "command_name": name, "description": description,
            "payload_json": dumps(payload), "undo_json": dumps(undo) if undo is not None else None,
            "undoable": int(undoable), "status": "EXECUTED", "created_at": utcnow()})

    def last_undoable(self, project_id: int) -> dict | None:
        row = self.c.one("""SELECT * FROM command_log WHERE project_id = ? AND undoable = 1 AND status = 'EXECUTED'
                            ORDER BY id DESC LIMIT 1""", (project_id,))
        if row:
            row["payload"] = loads(row["payload_json"], {})
            row["undo"] = loads(row["undo_json"], {})
        return row

    def mark_undone(self, command_id: int) -> None:
        self.c.execute("UPDATE command_log SET status = 'UNDONE' WHERE id = ?", (command_id,))

    def history(self, project_id: int, limit: int = 50) -> list[dict]:
        return self.c.all("""SELECT id, command_name, description, undoable, status, created_at FROM command_log
                             WHERE project_id = ? ORDER BY id DESC LIMIT ?""", (project_id, limit))


# ---------------------------------------------------------------------------
def load_architecture(conn: Connection, project: dict) -> SystemArchitecture:
    """Map persisted rows to the domain aggregate."""
    comps = [Component(
        id=r["id"], name=r["name"], component_type=r["component_type"], criticality=r["criticality"],
        description=r["description"], status=r["status"], health=r["health"],
        baseline_status=r["baseline_status"], baseline_health=r["baseline_health"],
        recovery_priority=r["recovery_priority"], estimated_recovery_minutes=r["estimated_recovery_minutes"],
        recovery_cost=r["recovery_cost"], operating_rule=r["operating_rule"], created_at=r["created_at"],
    ) for r in ComponentRepository(conn).list(project["id"])]
    deps = [Dependency(id=r["id"], source_id=r["source_component_id"], target_id=r["target_component_id"],
                       dependency_type=DependencyType(r["dependency_type"]), fallback_id=r["fallback_component_id"])
            for r in DependencyRepository(conn).list(project["id"])]
    funcs = [Functionality(id=r["id"], name=r["name"], is_critical=r["is_critical"],
                           component_ids=r["component_ids"], description=r["description"])
             for r in FunctionalityRepository(conn).list(project["id"])]
    return SystemArchitecture(comps, deps, funcs, propagation_policy=project["propagation_policy"],
                              project_id=project["id"], name=project["name"])
