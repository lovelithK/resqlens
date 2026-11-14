"""Command pattern.

Every state-changing operation on an architecture or simulation is an object
with ``validate()``, ``execute()`` and – for architecture editing – ``undo()``.
``CommandInvoker`` runs commands uniformly: validate -> execute -> log to the
``command_log`` table -> publish an event. Undo data is persisted so that the
last architecture edit can be undone in a later HTTP request.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..database import utcnow
from ..domain.enums import ACTIVE_SIMULATION_STATES, SimulationStatus
from ..domain.failures import create_failure
from ..domain.models import DomainError
from ..engine.dependency_manager import DependencyManager
from ..engine.events import EventType
from ..errors import AppError, conflict, invalid
from ..repositories import load_architecture
from .context import ServiceContext


class Command(ABC):
    name: str = "Command"
    undoable: bool = False

    def __init__(self, ctx: ServiceContext, project: dict, **payload: Any):
        self.ctx = ctx
        self.project = project
        self.payload = payload
        self.undo_data: dict | None = None
        self.result: Any = None

    @abstractmethod
    def validate(self) -> None: ...

    @abstractmethod
    def execute(self) -> Any: ...

    def undo(self) -> None:
        raise AppError(400, "NOT_UNDOABLE", f"{self.name} cannot be undone")

    @abstractmethod
    def describe(self) -> str: ...

    @classmethod
    def from_log(cls, ctx: ServiceContext, project: dict, payload: dict, undo_data: dict) -> "Command":
        cmd = cls(ctx, project, **payload)
        cmd.undo_data = undo_data
        return cmd


class CommandInvoker:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def run(self, command: Command) -> Any:
        command.validate()
        result = command.execute()
        self.ctx.commands.add(command.project["id"], self.ctx.user_id, command.name, command.describe(),
                              {k: v for k, v in command.payload.items() if _jsonable(v)},
                              command.undo_data, command.undoable)
        if isinstance(command, ArchitectureCommand):
            self.ctx.publish(EventType.ARCHITECTURE_CHANGED, command.describe(), command.project["id"],
                             category="ARCHITECTURE")
        return result

    def undo_last(self, project: dict) -> dict:
        row = self.ctx.commands.last_undoable(project["id"])
        if not row:
            raise AppError(400, "NOTHING_TO_UNDO", "There is no architecture change to undo")
        cls = COMMAND_REGISTRY[row["command_name"]]
        command = cls.from_log(self.ctx, project, row["payload"], row["undo"])
        if isinstance(command, ArchitectureCommand):
            command.ensure_editable()
        command.undo()
        self.ctx.commands.mark_undone(row["id"])
        message = f"Undo: {row['description']}"
        self.ctx.publish(EventType.ARCHITECTURE_CHANGED, message, project["id"], category="ARCHITECTURE")
        return {"undone": row["command_name"], "description": row["description"]}


def _jsonable(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool, list, dict, type(None)))


# ---------------------------------------------------------------------------
# Architecture editing commands (undoable)
# ---------------------------------------------------------------------------
class ArchitectureCommand(Command):
    undoable = True

    def ensure_editable(self) -> None:
        active = self.ctx.simulations.active_for_project(self.project["id"])
        if active:
            raise conflict(f"Simulation '{active['name']}' is active ({active['status']}). Reset it before editing "
                           "the architecture.", code="SIMULATION_ACTIVE")

    def _component_in_project(self, component_id: int | None, label: str) -> dict | None:
        if component_id is None:
            return None
        row = self.ctx.conn.one("SELECT * FROM system_components WHERE id = ? AND project_id = ?",
                                (component_id, self.project["id"]))
        if not row:
            raise invalid(f"{label} component {component_id} does not belong to this project",
                          code="MISSING_DEPENDENCY")
        return row


class AddComponentCommand(ArchitectureCommand):
    name = "AddComponentCommand"

    def validate(self):
        self.ensure_editable()
        if self.ctx.components.name_taken(self.project["id"], self.payload["name"]):
            raise conflict(f"A component named '{self.payload['name']}' already exists", code="DUPLICATE_NAME")

    def execute(self):
        cid = self.ctx.components.create(self.project["id"], self.payload)
        self.undo_data = {"component_id": cid}
        self.result = cid
        return cid

    def undo(self):
        self.ctx.components.delete(self.undo_data["component_id"])

    def describe(self):
        return f"Added component '{self.payload['name']}'"


class UpdateComponentCommand(ArchitectureCommand):
    name = "UpdateComponentCommand"

    def validate(self):
        self.ensure_editable()
        self.before = self._component_in_project(self.payload["component_id"], "Component")
        new_name = self.payload["changes"].get("name")
        if new_name and self.ctx.components.name_taken(self.project["id"], new_name, self.payload["component_id"]):
            raise conflict(f"A component named '{new_name}' already exists", code="DUPLICATE_NAME")

    def execute(self):
        changes = dict(self.payload["changes"])
        # baseline edits also update the live state (architecture is not in a simulation)
        if "baseline_status" in changes:
            changes["status"] = changes["baseline_status"]
        if "baseline_health" in changes:
            changes["health"] = changes["baseline_health"]
        self.undo_data = {"component_id": self.before["id"],
                          "previous": {k: self.before[k] for k in changes if k in self.before}}
        self.ctx.components.update(self.before["id"], changes)
        return self.before["id"]

    def undo(self):
        self.ctx.components.update(self.undo_data["component_id"], self.undo_data["previous"])

    def describe(self):
        name = self.payload["changes"].get("name") or (getattr(self, "before", None) or {}).get("name", "")
        return f"Updated component '{name}' ({', '.join(self.payload['changes'])})"


class RemoveComponentCommand(ArchitectureCommand):
    name = "RemoveComponentCommand"

    def validate(self):
        self.ensure_editable()
        self.row = self._component_in_project(self.payload["component_id"], "Component")

    def execute(self):
        cid = self.row["id"]
        self.undo_data = {
            "component": self.row,
            "dependencies": self.ctx.dependencies.for_component(cid),
            "functionalities": self.ctx.functionalities.links_for_component(cid),
        }
        self.ctx.components.delete(cid)
        return cid

    def undo(self):
        comp = self.undo_data["component"]
        self.ctx.components.create(self.project["id"], comp, component_id=comp["id"])
        for d in self.undo_data["dependencies"]:
            self.ctx.dependencies.create(self.project["id"], d["source_component_id"], d["target_component_id"],
                                         d["dependency_type"], d["fallback_component_id"], d["description"],
                                         dependency_id=d["id"])
        for fid in self.undo_data["functionalities"]:
            self.ctx.conn.insert("functionality_components", {"functionality_id": fid, "component_id": comp["id"]})

    def describe(self):
        return f"Removed component '{(getattr(self, 'row', None) or self.undo_data['component'])['name']}'"


class ConnectComponentsCommand(ArchitectureCommand):
    """source depends on target."""
    name = "ConnectComponentsCommand"

    def validate(self):
        self.ensure_editable()
        p = self.payload
        if p["source_id"] == p["target_id"]:
            raise invalid("A component cannot depend on itself", code="SELF_DEPENDENCY")
        self.source = self._component_in_project(p["source_id"], "Source")
        self.target = self._component_in_project(p["target_id"], "Target")
        if self.ctx.dependencies.find(p["source_id"], p["target_id"]):
            raise conflict(f"{self.source['name']} already depends on {self.target['name']}",
                           code="DUPLICATE_CONNECTION")
        fb = p.get("fallback_id")
        if fb is not None:
            self._component_in_project(fb, "Backup")
            if fb in (p["source_id"], p["target_id"]):
                raise invalid("The backup must be a different component", code="INVALID_FALLBACK")
        arch = load_architecture(self.ctx.conn, self.project)
        cycle = DependencyManager(arch).would_create_cycle(p["source_id"], p["target_id"])
        if cycle:
            names = " -> ".join(arch.name_of(c) for c in cycle)
            raise conflict(f"Connection rejected: it would create a circular dependency ({names})",
                           code="CIRCULAR_DEPENDENCY", details={"cycle": cycle})

    def execute(self):
        p = self.payload
        dep_id = self.ctx.dependencies.create(self.project["id"], p["source_id"], p["target_id"],
                                              p.get("dependency_type", "MANDATORY"), p.get("fallback_id"),
                                              p.get("description", ""))
        self.undo_data = {"dependency_id": dep_id}
        return dep_id

    def undo(self):
        self.ctx.dependencies.delete(self.undo_data["dependency_id"])

    def describe(self):
        s = getattr(self, "source", None)
        t = getattr(self, "target", None)
        if s and t:
            return f"Connected {s['name']} -> {t['name']} ({self.payload.get('dependency_type', 'MANDATORY')})"
        return "Connected components"


class UpdateDependencyCommand(ArchitectureCommand):
    name = "UpdateDependencyCommand"

    def validate(self):
        self.ensure_editable()
        self.before = self.ctx.conn.one("SELECT * FROM dependencies WHERE id = ? AND project_id = ?",
                                        (self.payload["dependency_id"], self.project["id"]))
        if not self.before:
            raise AppError(404, "NOT_FOUND", "Dependency not found")
        fb = self.payload["changes"].get("fallback_component_id")
        if fb is not None:
            self._component_in_project(fb, "Backup")
            if fb in (self.before["source_component_id"], self.before["target_component_id"]):
                raise invalid("The backup must be a different component", code="INVALID_FALLBACK")

    def execute(self):
        changes = self.payload["changes"]
        self.undo_data = {"dependency_id": self.before["id"],
                          "previous": {k: self.before[k] for k in changes}}
        self.ctx.dependencies.update(self.before["id"], changes)
        return self.before["id"]

    def undo(self):
        self.ctx.dependencies.update(self.undo_data["dependency_id"], self.undo_data["previous"])

    def describe(self):
        return f"Updated dependency #{self.payload['dependency_id']} ({', '.join(self.payload['changes'])})"


class DisconnectComponentsCommand(ArchitectureCommand):
    name = "DisconnectComponentsCommand"

    def validate(self):
        self.ensure_editable()
        self.row = self.ctx.conn.one("SELECT * FROM dependencies WHERE id = ? AND project_id = ?",
                                     (self.payload["dependency_id"], self.project["id"]))
        if not self.row:
            raise AppError(404, "NOT_FOUND", "Dependency not found")

    def execute(self):
        self.undo_data = {"dependency": self.row}
        self.ctx.dependencies.delete(self.row["id"])
        return self.row["id"]

    def undo(self):
        d = self.undo_data["dependency"]
        self.ctx.dependencies.create(self.project["id"], d["source_component_id"], d["target_component_id"],
                                     d["dependency_type"], d["fallback_component_id"], d["description"],
                                     dependency_id=d["id"])

    def describe(self):
        return f"Removed dependency #{self.payload['dependency_id']}"


# ---------------------------------------------------------------------------
# Simulation commands (not undoable – they are recorded in the timeline)
# ---------------------------------------------------------------------------
class InjectFailureCommand(Command):
    name = "InjectFailureCommand"

    def __init__(self, ctx, project, simulation: dict | None = None, **payload):
        super().__init__(ctx, project, **payload)
        self.simulation = simulation

    def validate(self):
        if self.simulation["status"] != SimulationStatus.CREATED.value:
            raise conflict("Failures can only be injected before the simulation starts", code="INVALID_STATE")
        self.component = self.ctx.conn.one("SELECT * FROM system_components WHERE id = ? AND project_id = ?",
                                           (self.payload["component_id"], self.project["id"]))
        if not self.component:
            raise invalid("The failure target does not belong to this project", code="MISSING_COMPONENT")
        try:
            self.failure = create_failure(self.payload["failure_type"], self.component["id"], self.payload["severity"])
            arch = load_architecture(self.ctx.conn, self.project)
            self.failure.validate_target(arch.components[self.component["id"]])
        except DomainError as e:
            raise invalid(e.message, code=e.code)

    def execute(self):
        return self.ctx.simulations.add_failure(
            self.simulation["id"], self.component, self.payload["failure_type"], self.payload["severity"],
            self.payload.get("description", ""), self.failure.resulting_status().value)

    def describe(self):
        return (f"Configured {self.failure.label} on {self.component['name']} "
                f"(severity {self.payload['severity']})")


class StartSimulationCommand(Command):
    name = "StartSimulationCommand"

    def __init__(self, ctx, project, simulation: dict | None = None, **payload):
        super().__init__(ctx, project, **payload)
        self.simulation = simulation

    def validate(self):
        sim = self.simulation
        if sim["status"] in {s.value for s in ACTIVE_SIMULATION_STATES}:
            raise conflict("This simulation is already running – duplicate execution rejected",
                           code="DUPLICATE_EXECUTION")
        if sim["status"] != SimulationStatus.CREATED.value:
            raise conflict(f"Simulation is {sim['status']} and cannot be started again; create a new one",
                           code="INVALID_STATE")
        active = self.ctx.simulations.active_for_project(self.project["id"])
        if active and active["id"] != sim["id"]:
            raise conflict(f"Simulation '{active['name']}' is still active on this project. Reset it first.",
                           code="SIMULATION_ACTIVE")
        if not self.ctx.simulations.failures(sim["id"]):
            raise invalid("Inject at least one failure before starting", code="NO_FAILURES")
        arch = load_architecture(self.ctx.conn, self.project)
        report = DependencyManager(arch).validate()
        if not report["valid"]:
            raise invalid("Architecture validation failed – fix the errors before simulating",
                          code="INVALID_ARCHITECTURE", details=report["issues"])

    def execute(self):
        self.ctx.simulations.update(self.simulation["id"], status=SimulationStatus.RUNNING.value,
                                    started_at=utcnow(), current_tick=-1)
        return self.simulation["id"]

    def describe(self):
        return f"Started simulation '{self.simulation['name']}'"


class RestoreComponentCommand(Command):
    name = "RestoreComponentCommand"

    def __init__(self, ctx, project, executor=None, action: dict | None = None, **payload):
        super().__init__(ctx, project, **payload)
        self.executor = executor
        self.action = action

    def validate(self):
        if self.action["status"] != "PENDING":
            raise conflict("Recovery action already processed", code="INVALID_STATE")
        if self.action["component_id"] not in self.executor.arch.components:
            raise invalid("Component of this action no longer exists", code="MISSING_COMPONENT")

    def execute(self):
        return self.executor.execute(self.action["component_id"], self.action["estimated_minutes"])

    def describe(self):
        return f"Recovery action {self.action['action_type']} on {self.action['component_name']}"


class ResetSimulationCommand(Command):
    name = "ResetSimulationCommand"

    def __init__(self, ctx, project, simulation: dict | None = None, **payload):
        super().__init__(ctx, project, **payload)
        self.simulation = simulation

    def validate(self):
        if self.simulation["status"] == SimulationStatus.RESET.value:
            raise conflict("Simulation has already been reset", code="INVALID_STATE")

    def execute(self):
        sim = self.simulation
        self.ctx.conn.execute("UPDATE recovery_plans SET status = 'SUPERSEDED' WHERE simulation_id = ? "
                              "AND status IN ('EXECUTING','PAUSED')", (sim["id"],))
        values = {"status": SimulationStatus.RESET.value}
        if not sim.get("completed_at"):
            values["completed_at"] = utcnow()
        self.ctx.simulations.update(sim["id"], **values)
        self.ctx.publish(EventType.SIMULATION_RESET,
                         f"Architecture reset to its original state after '{sim['name']}'",
                         self.project["id"], sim["id"])
        return sim["id"]

    def describe(self):
        return f"Reset simulation '{self.simulation['name']}'"


COMMAND_REGISTRY: dict[str, type[Command]] = {
    cls.name: cls for cls in (AddComponentCommand, UpdateComponentCommand, RemoveComponentCommand,
                              ConnectComponentsCommand, UpdateDependencyCommand, DisconnectComponentsCommand,
                              InjectFailureCommand, StartSimulationCommand, RestoreComponentCommand,
                              ResetSimulationCommand)
}
