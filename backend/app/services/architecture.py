"""Project & architecture management. All architecture edits go through the
Command pattern (validated, logged and undoable)."""
from __future__ import annotations

from ..database import utcnow
from ..domain.enums import COMPONENT_TYPE_LABELS
from ..domain.failures import failure_catalog
from ..engine.dependency_manager import DependencyManager
from ..engine.events import EventType
from ..engine.propagation import POLICIES
from ..errors import conflict, invalid
from ..repositories import load_architecture
from .commands import (
    AddComponentCommand, CommandInvoker, ConnectComponentsCommand, DisconnectComponentsCommand,
    RemoveComponentCommand, UpdateComponentCommand, UpdateDependencyCommand,
)
from .context import ServiceContext


class ArchitectureService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.invoker = CommandInvoker(ctx)

    # -- projects ----------------------------------------------------------------
    def list_projects(self) -> list[dict]:
        return self.ctx.projects.list_for_user(self.ctx.user_id)

    def create_project(self, data: dict) -> dict:
        if self.ctx.projects.name_taken(self.ctx.user_id, data["name"]):
            raise conflict(f"You already have a project named '{data['name']}'", code="DUPLICATE_NAME")
        pid = self.ctx.projects.create(self.ctx.user_id, data["name"], data.get("description", ""),
                                       data.get("propagation_policy", "BLOCKING"))
        self.ctx.publish(EventType.PROJECT_CREATED, f"Project '{data['name']}' created", pid, category="PROJECT")
        return self.ctx.projects.get_owned(pid, self.ctx.user_id)

    def update_project(self, project: dict, data: dict) -> dict:
        if "name" in data and self.ctx.projects.name_taken(self.ctx.user_id, data["name"], project["id"]):
            raise conflict(f"You already have a project named '{data['name']}'", code="DUPLICATE_NAME")
        if "propagation_policy" in data and self.ctx.simulations.active_for_project(project["id"]):
            raise conflict("Reset the active simulation before changing the propagation policy",
                           code="SIMULATION_ACTIVE")
        self.ctx.projects.update(project["id"], **data)
        return self.ctx.projects.get_owned(project["id"], self.ctx.user_id)

    def delete_project(self, project: dict) -> None:
        self.ctx.projects.delete(project["id"])

    # -- architecture -----------------------------------------------------------
    def architecture(self, project: dict) -> dict:
        arch = load_architecture(self.ctx.conn, project)
        dm = DependencyManager(arch)
        layers = dm.layers() if arch.components else {}
        components = self.ctx.components.list(project["id"])
        dependents = {c["id"]: 0 for c in components}
        for d in arch.dependencies:
            dependents[d.target_id] = dependents.get(d.target_id, 0) + 1
        for c in components:
            c["layer"] = layers.get(c["id"], 0)
            c["type_label"] = COMPONENT_TYPE_LABELS[c["component_type"]]
            c["dependency_ids"] = [d.target_id for d in arch.dependencies_of(c["id"])]
            c["dependent_count"] = dependents.get(c["id"], 0)
            c["functionalities"] = [f.name for f in arch.functionalities_using(c["id"])]
        active = self.ctx.simulations.active_for_project(project["id"])
        return {
            "project": project,
            "components": components,
            "dependencies": self.ctx.dependencies.list(project["id"]),
            "functionalities": self.ctx.functionalities.list(project["id"]),
            "validation": dm.validate(),
            "stats": dm.stats(),
            "active_simulation": ({k: active[k] for k in ("id", "name", "status", "current_tick", "max_tick")}
                                  if active else None),
            "can_undo": self.ctx.commands.last_undoable(project["id"]) is not None,
        }

    def validate(self, project: dict) -> dict:
        return DependencyManager(load_architecture(self.ctx.conn, project)).validate()

    # -- components ---------------------------------------------------------------
    def add_component(self, project: dict, data: dict) -> dict:
        cid = self.invoker.run(AddComponentCommand(self.ctx, project, **data))
        return self.ctx.components.get(cid)

    def update_component(self, project: dict, component_id: int, changes: dict) -> dict:
        if not changes:
            raise invalid("No changes supplied")
        self.invoker.run(UpdateComponentCommand(self.ctx, project, component_id=component_id, changes=changes))
        return self.ctx.components.get(component_id)

    def delete_component(self, project: dict, component_id: int) -> None:
        self.invoker.run(RemoveComponentCommand(self.ctx, project, component_id=component_id))

    def save_layout(self, project: dict, positions: list[dict]) -> None:
        """Node positions are presentation data: persisted directly (not undoable)."""
        for pos in positions:
            self.ctx.conn.execute("UPDATE system_components SET pos_x = ?, pos_y = ? WHERE id = ? AND project_id = ?",
                                  (pos["x"], pos["y"], pos["id"], project["id"]))

    # -- dependencies -------------------------------------------------------------
    def connect(self, project: dict, data: dict) -> dict:
        dep_id = self.invoker.run(ConnectComponentsCommand(self.ctx, project, **data))
        return self.ctx.conn.one("SELECT * FROM dependencies WHERE id = ?", (dep_id,))

    def update_dependency(self, project: dict, dep_id: int, changes: dict) -> dict:
        self.invoker.run(UpdateDependencyCommand(self.ctx, project, dependency_id=dep_id, changes=changes))
        return self.ctx.conn.one("SELECT * FROM dependencies WHERE id = ?", (dep_id,))

    def disconnect(self, project: dict, dep_id: int) -> None:
        self.invoker.run(DisconnectComponentsCommand(self.ctx, project, dependency_id=dep_id))

    def undo(self, project: dict) -> dict:
        return self.invoker.undo_last(project)

    # -- functionalities ------------------------------------------------------------
    def _check_components(self, project: dict, ids: list[int]) -> None:
        valid = {c["id"] for c in self.ctx.components.list(project["id"])}
        bad = [i for i in ids if i not in valid]
        if bad:
            raise invalid(f"Components {bad} do not belong to this project", code="MISSING_COMPONENT")

    def create_functionality(self, project: dict, data: dict) -> dict:
        self._check_components(project, data["component_ids"])
        if any(f["name"].lower() == data["name"].lower() for f in self.ctx.functionalities.list(project["id"])):
            raise conflict(f"Functionality '{data['name']}' already exists", code="DUPLICATE_NAME")
        self._ensure_editable(project)
        fid = self.ctx.functionalities.create(project["id"], data["name"], data.get("description", ""),
                                              data.get("is_critical", False), data["component_ids"])
        self.ctx.publish(EventType.ARCHITECTURE_CHANGED, f"Functionality '{data['name']}' added", project["id"],
                         category="ARCHITECTURE")
        return next(f for f in self.ctx.functionalities.list(project["id"]) if f["id"] == fid)

    def update_functionality(self, project: dict, func_id: int, data: dict) -> dict:
        if "component_ids" in data:
            self._check_components(project, data["component_ids"])
        self._ensure_editable(project)
        self.ctx.functionalities.update(func_id, dict(data))
        return next(f for f in self.ctx.functionalities.list(project["id"]) if f["id"] == func_id)

    def delete_functionality(self, project: dict, func_id: int) -> None:
        self._ensure_editable(project)
        self.ctx.functionalities.delete(func_id)

    def _ensure_editable(self, project: dict) -> None:
        if self.ctx.simulations.active_for_project(project["id"]):
            raise conflict("Reset the active simulation before editing the architecture", code="SIMULATION_ACTIVE")

    # -- scenarios ---------------------------------------------------------------------
    def create_scenario(self, project: dict, data: dict) -> dict:
        self._check_components(project, [f["component_id"] for f in data["failures"]])
        if any(s["name"].lower() == data["name"].lower() for s in self.ctx.scenarios.list(project["id"])):
            raise conflict(f"Scenario '{data['name']}' already exists", code="DUPLICATE_NAME")
        sid = self.ctx.scenarios.create(project["id"], data["name"], data.get("description", ""), data["failures"],
                                        data.get("duration_minutes", 30))
        return next(s for s in self.ctx.scenarios.list(project["id"]) if s["id"] == sid)

    # -- import / export --------------------------------------------------------------
    def export(self, project: dict) -> dict:
        comps = self.ctx.components.list(project["id"])
        name = {c["id"]: c["name"] for c in comps}
        return {
            "format": "resqlens-architecture/1",
            "exported_at": utcnow(),
            "project": {"name": project["name"], "description": project["description"],
                        "propagation_policy": project["propagation_policy"]},
            "components": [{k: c[k] for k in ("name", "component_type", "description", "criticality",
                                              "recovery_priority", "estimated_recovery_minutes", "recovery_cost",
                                              "operating_rule", "baseline_status", "baseline_health", "pos_x", "pos_y")}
                           for c in comps],
            "dependencies": [{"source": name[d["source_component_id"]], "target": name[d["target_component_id"]],
                              "dependency_type": d["dependency_type"],
                              "fallback": name.get(d["fallback_component_id"]) if d["fallback_component_id"] else None,
                              "description": d["description"]} for d in self.ctx.dependencies.list(project["id"])],
            "functionalities": [{"name": f["name"], "description": f["description"], "is_critical": f["is_critical"],
                                 "components": [name[c] for c in f["component_ids"]]}
                                for f in self.ctx.functionalities.list(project["id"])],
            "scenarios": [{"name": s["name"], "description": s["description"], "duration_minutes": s["duration_minutes"],
                           "failures": [{**{k: v for k, v in f.items() if k != "component_id"},
                                         "component": name.get(f["component_id"])} for f in s["failures"]]}
                          for s in self.ctx.scenarios.list(project["id"])],
        }

    def import_project(self, data: dict, name_override: str | None = None) -> dict:
        pdata = data.get("project", {})
        base = name_override or pdata.get("name") or "Imported architecture"
        name, i = base, 2
        while self.ctx.projects.name_taken(self.ctx.user_id, name):
            name, i = f"{base} ({i})", i + 1
        project = self.create_project({"name": name, "description": pdata.get("description", ""),
                                       "propagation_policy": pdata.get("propagation_policy", "BLOCKING")})
        ids: dict[str, int] = {}
        for c in data.get("components", []):
            ids[c["name"]] = self.ctx.components.create(project["id"], c)
        dm_errors = []
        for d in data.get("dependencies", []):
            try:
                self.ctx.dependencies.create(project["id"], ids[d["source"]], ids[d["target"]],
                                             d.get("dependency_type", "MANDATORY"),
                                             ids.get(d.get("fallback")) if d.get("fallback") else None,
                                             d.get("description", ""))
            except KeyError as e:
                dm_errors.append(f"Dependency references unknown component {e}")
        for f in data.get("functionalities", []):
            self.ctx.functionalities.create(project["id"], f["name"], f.get("description", ""),
                                            f.get("is_critical", False), [ids[c] for c in f.get("components", []) if c in ids])
        for s in data.get("scenarios", []):
            fails = [{**{k: v for k, v in f.items() if k != "component"}, "component_id": ids[f["component"]]}
                     for f in s.get("failures", []) if f.get("component") in ids]
            if fails:
                self.ctx.scenarios.create(project["id"], s["name"], s.get("description", ""), fails,
                                          s.get("duration_minutes", 30))
        if dm_errors:
            raise invalid("Import failed", code="INVALID_IMPORT", details=dm_errors)
        return project


def catalog() -> dict:
    return {
        "component_types": [{"value": k, "label": v} for k, v in COMPONENT_TYPE_LABELS.items()],
        "failure_types": failure_catalog(),
        "propagation_policies": [{"key": k, "name": cls.name, "description": cls.description}
                                 for k, cls in POLICIES.items()],
        "operating_rules": [
            {"value": "STRICT", "description": "Degraded mandatory or lost/degraded optional dependency -> DEGRADED"},
            {"value": "STANDARD", "description": "Degraded mandatory dependency -> DEGRADED; optional loss tolerated"},
            {"value": "TOLERANT", "description": "Ignores degraded and optional dependencies"},
        ],
        "criticality_levels": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    }
