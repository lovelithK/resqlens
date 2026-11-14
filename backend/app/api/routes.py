"""REST endpoints. Every handler: authorise (ownership via repositories),
delegate to a service, return JSON."""
from __future__ import annotations

from datetime import datetime, timezone

from starlette.responses import Response


from ..errors import AppError, invalid
from ..security import create_token, hash_password, verify_password
from ..services.analytics import AnalyticsService
from ..services.architecture import ArchitectureService, catalog
from ..services.recovery import RecoveryService, strategy_rows
from ..services.reports import ReportService
from ..services.simulation import SimulationService
from . import schemas as S
from .routing import Api, RequestContext, created


def register(api: Api, settings_getter) -> None:
    r = api.route

    # ------------------------------------------------------------------ auth
    def _issue(c: RequestContext, user: dict) -> dict:
        s = settings_getter()
        token, jti, expires = create_token(user["id"], s.secret_key, s.token_ttl_minutes)
        c.svc.users.add_session(jti, user["id"], expires.isoformat())
        return {"token": token, "expires_at": expires.isoformat(),
                "user": {k: user[k] for k in ("id", "email", "full_name", "created_at")}}

    @r("/api/auth/register", ["POST"], auth=False, schema=S.RegisterIn)
    @created
    def register_user(c: RequestContext):
        b = c.body
        if c.svc.users.by_email(b.email):
            raise AppError(409, "EMAIL_TAKEN", "An account with this email already exists")
        uid = c.svc.users.create(b.email, b.full_name, hash_password(b.password))
        c.svc.user = c.svc.users.get(uid)
        if b.include_demo_project:
            from ..seed import create_demo_project
            create_demo_project(c.svc, uid)
        return _issue(c, c.svc.user)

    @r("/api/auth/login", ["POST"], auth=False, schema=S.LoginIn)
    def login(c: RequestContext):
        user = c.svc.users.by_email(c.body.email)
        if not user or not verify_password(c.body.password, user["password_hash"]):
            raise AppError(401, "INVALID_CREDENTIALS", "Incorrect email or password")
        return _issue(c, user)

    @r("/api/auth/logout", ["POST"])
    def logout(c: RequestContext):
        c.svc.users.delete_session(c.claims["jti"])
        return {"ok": True}

    @r("/api/auth/me", ["GET"])
    def me(c: RequestContext):
        return c.svc.user

    @r("/api/auth/me", ["PUT"], schema=S.ProfileIn)
    def update_me(c: RequestContext):
        c.svc.users.update(c.svc.user_id, full_name=c.body.full_name)
        return c.svc.users.get(c.svc.user_id)

    @r("/api/auth/change-password", ["POST"], schema=S.PasswordChangeIn)
    def change_password(c: RequestContext):
        if not verify_password(c.body.current_password, c.svc.users.password_hash(c.svc.user_id)):
            raise AppError(400, "INVALID_CREDENTIALS", "Current password is incorrect")
        S.RegisterIn.strong(c.body.new_password)
        c.svc.users.update(c.svc.user_id, password_hash=hash_password(c.body.new_password))
        return {"ok": True}

    # --------------------------------------------------------------- meta
    @r("/api/health", ["GET"], auth=False)
    def health(c: RequestContext):
        """Liveness + database connectivity check (used by scripts and deployments)."""
        conn = c.svc.conn
        version = conn.scalar("SELECT VERSION()" if conn.dialect == "mysql" else "SELECT sqlite_version()")
        return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(),
                "database": {"engine": conn.dialect, "version": version,
                             "users": conn.scalar("SELECT COUNT(*) FROM users")}}

    @r("/api/catalog", ["GET"])
    def get_catalog(c: RequestContext):
        return {**catalog(), "recovery_strategies": strategy_rows()}

    @r("/api/dashboard", ["GET"])
    def dashboard(c: RequestContext):
        return AnalyticsService(c.svc).dashboard()

    @r("/api/activity", ["GET"], query=["project_id", "limit"])
    def activity(c: RequestContext):
        pid = c.query.get("project_id")
        return c.svc.events.recent_for_user(c.svc.user_id, int(pid) if pid else None,
                                            limit=min(200, int(c.query.get("limit", 50))))

    # ------------------------------------------------------------ projects
    def project(c: RequestContext, name: str = "id") -> dict:
        return c.svc.projects.get_owned(c.int_param(name), c.svc.user_id)

    @r("/api/projects", ["GET"])
    def list_projects(c):
        return ArchitectureService(c.svc).list_projects()

    @r("/api/projects", ["POST"], schema=S.ProjectIn)
    @created
    def create_project(c):
        return ArchitectureService(c.svc).create_project(c.body.model_dump())

    @r("/api/projects/import", ["POST"], schema=S.ImportIn)
    @created
    def import_project(c):
        return ArchitectureService(c.svc).import_project(c.body.data, c.body.name)

    @r("/api/projects/{id:int}", ["GET"])
    def get_project(c):
        return ArchitectureService(c.svc).architecture(project(c))

    @r("/api/projects/{id:int}", ["PUT"], schema=S.ProjectUpdate)
    def update_project(c):
        return ArchitectureService(c.svc).update_project(project(c), c.body.model_dump(exclude_none=True))

    @r("/api/projects/{id:int}", ["DELETE"])
    def delete_project(c):
        ArchitectureService(c.svc).delete_project(project(c))

    @r("/api/projects/{id:int}/architecture", ["GET"])
    def get_architecture(c):
        return ArchitectureService(c.svc).architecture(project(c))

    @r("/api/projects/{id:int}/validate", ["POST"])
    def validate(c):
        return ArchitectureService(c.svc).validate(project(c))

    @r("/api/projects/{id:int}/layout", ["PUT"], schema=S.LayoutIn)
    def layout(c):
        ArchitectureService(c.svc).save_layout(project(c), c.body.positions)
        return {"ok": True}

    @r("/api/projects/{id:int}/undo", ["POST"])
    def undo(c):
        return ArchitectureService(c.svc).undo(project(c))

    @r("/api/projects/{id:int}/commands", ["GET"])
    def command_history(c):
        return c.svc.commands.history(project(c)["id"])

    @r("/api/projects/{id:int}/export", ["GET"])
    def export_architecture(c):
        return ArchitectureService(c.svc).export(project(c))

    # ---------------------------------------------------------- components
    @r("/api/projects/{id:int}/components", ["GET"])
    def list_components(c):
        return c.svc.components.list(project(c)["id"])

    @r("/api/projects/{id:int}/components", ["POST"], schema=S.ComponentIn)
    @created
    def add_component(c):
        return ArchitectureService(c.svc).add_component(project(c), c.body.model_dump())

    def component_project(c) -> tuple[dict, dict]:
        comp = c.svc.components.get_owned(c.int_param("id"), c.svc.user_id)
        return comp, c.svc.projects.get_owned(comp["project_id"], c.svc.user_id)

    @r("/api/components/{id:int}", ["GET"])
    def get_component(c):
        return component_project(c)[0]

    @r("/api/components/{id:int}", ["PUT"], schema=S.ComponentUpdate)
    def update_component(c):
        comp, proj = component_project(c)
        return ArchitectureService(c.svc).update_component(proj, comp["id"], c.body.model_dump(exclude_none=True))

    @r("/api/components/{id:int}", ["DELETE"])
    def delete_component(c):
        comp, proj = component_project(c)
        ArchitectureService(c.svc).delete_component(proj, comp["id"])

    # -------------------------------------------------------- dependencies
    @r("/api/dependencies", ["POST"], schema=S.DependencyIn)
    @created
    def connect(c):
        proj = c.svc.projects.get_owned(c.body.project_id, c.svc.user_id)
        data = c.body.model_dump(exclude={"project_id"})
        return ArchitectureService(c.svc).connect(proj, data)

    def dep_project(c) -> tuple[dict, dict]:
        dep = c.svc.dependencies.get_owned(c.int_param("id"), c.svc.user_id)
        return dep, c.svc.projects.get_owned(dep["project_id"], c.svc.user_id)

    @r("/api/dependencies/{id:int}", ["PUT"], schema=S.DependencyUpdate)
    def update_dependency(c):
        dep, proj = dep_project(c)
        changes = c.body.model_dump(exclude_none=True, exclude={"clear_fallback"})
        if c.body.clear_fallback:
            changes["fallback_component_id"] = None
        if not changes:
            raise invalid("No changes supplied")
        return ArchitectureService(c.svc).update_dependency(proj, dep["id"], changes)

    @r("/api/dependencies/{id:int}", ["DELETE"])
    def delete_dependency(c):
        dep, proj = dep_project(c)
        ArchitectureService(c.svc).disconnect(proj, dep["id"])

    # ------------------------------------------------------ functionalities
    @r("/api/projects/{id:int}/functionalities", ["GET"])
    def list_functionalities(c):
        return c.svc.functionalities.list(project(c)["id"])

    @r("/api/projects/{id:int}/functionalities", ["POST"], schema=S.FunctionalityIn)
    @created
    def add_functionality(c):
        return ArchitectureService(c.svc).create_functionality(project(c), c.body.model_dump())

    def func_project(c):
        f = c.svc.functionalities.get_owned(c.int_param("id"), c.svc.user_id)
        return f, c.svc.projects.get_owned(f["project_id"], c.svc.user_id)

    @r("/api/functionalities/{id:int}", ["PUT"], schema=S.FunctionalityUpdate)
    def update_functionality(c):
        f, proj = func_project(c)
        return ArchitectureService(c.svc).update_functionality(proj, f["id"], c.body.model_dump(exclude_none=True))

    @r("/api/functionalities/{id:int}", ["DELETE"])
    def delete_functionality(c):
        f, proj = func_project(c)
        ArchitectureService(c.svc).delete_functionality(proj, f["id"])

    # ------------------------------------------------------------ scenarios
    @r("/api/projects/{id:int}/scenarios", ["GET"])
    def list_scenarios(c):
        return c.svc.scenarios.list(project(c)["id"])

    @r("/api/projects/{id:int}/scenarios", ["POST"], schema=S.ScenarioIn)
    @created
    def add_scenario(c):
        return ArchitectureService(c.svc).create_scenario(project(c), c.body.model_dump())

    @r("/api/scenarios/{id:int}", ["DELETE"])
    def delete_scenario(c):
        sc = c.svc.scenarios.get_owned(c.int_param("id"), c.svc.user_id)
        c.svc.scenarios.delete(sc["id"])

    @r("/api/projects/{id:int}/what-if", ["POST"], schema=S.WhatIfIn)
    def what_if(c):
        return AnalyticsService(c.svc).what_if(project(c), [s.model_dump() for s in c.body.scenarios])

    @r("/api/projects/{id:int}/diagnose", ["POST"], schema=S.DiagnoseIn)
    def diagnose(c):
        return AnalyticsService(c.svc).diagnose(project(c), c.body.observed_component_ids)

    @r("/api/projects/{id:int}/single-points-of-failure", ["GET"])
    def project_spof(c):
        return AnalyticsService(c.svc).spof(project(c))

    @r("/api/projects/{id:int}/resilience", ["GET"], query=["model"])
    def resilience(c):
        return AnalyticsService(c.svc).resilience(project(c), c.query.get("model", "OPERATIONAL"))

    # ---------------------------------------------------------- simulations
    def history_filters(c) -> dict:
        q = c.query
        return {k: v for k, v in {
            "project_id": int(q["project_id"]) if q.get("project_id") else None,
            "severity": q.get("severity") or None, "status": q.get("status") or None,
            "date_from": q.get("date_from") or None, "date_to": q.get("date_to") or None}.items() if v}

    @r("/api/simulations", ["GET"], query=["project_id", "severity", "status", "date_from", "date_to"])
    def list_simulations(c):
        return c.svc.simulations.search(c.svc.user_id, **history_filters(c))

    @r("/api/simulations/export.csv", ["GET"], query=["project_id", "severity", "status", "date_from", "date_to"])
    def export_history(c):
        csv = ReportService(c.svc).history_csv(history_filters(c))
        return Response(csv, media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="resqlens-simulation-history.csv"'})

    @r("/api/simulations/compare", ["GET"], query=["ids"])
    def compare(c):
        try:
            ids = [int(x) for x in c.query.get("ids", "").split(",") if x.strip()]
        except ValueError:
            raise invalid("ids must be a comma-separated list of simulation ids")
        if not 2 <= len(ids) <= 6:
            raise invalid("Select between 2 and 6 simulations to compare")
        return AnalyticsService(c.svc).compare_simulations(ids)

    @r("/api/simulations", ["POST"], schema=S.SimulationIn)
    @created
    def create_simulation(c):
        proj = c.svc.projects.get_owned(c.body.project_id, c.svc.user_id)
        return SimulationService(c.svc).create(proj, c.body.model_dump())

    sim_id = lambda c: c.int_param("id")  # noqa: E731

    @r("/api/simulations/{id:int}", ["GET"])
    def get_simulation(c):
        return SimulationService(c.svc).detail(sim_id(c))

    @r("/api/simulations/{id:int}", ["DELETE"])
    def delete_simulation(c):
        SimulationService(c.svc).delete(sim_id(c))

    @r("/api/simulations/{id:int}/start", ["POST"], schema=S.StartIn)
    def start(c):
        return SimulationService(c.svc).start(sim_id(c), c.body.instant)

    @r("/api/simulations/{id:int}/tick", ["POST"])
    def tick(c):
        return SimulationService(c.svc).tick(sim_id(c))

    @r("/api/simulations/{id:int}/pause", ["POST"])
    def pause(c):
        return SimulationService(c.svc).pause(sim_id(c))

    @r("/api/simulations/{id:int}/resume", ["POST"])
    def resume(c):
        return SimulationService(c.svc).resume(sim_id(c))

    @r("/api/simulations/{id:int}/stop", ["POST"])
    def stop(c):
        return SimulationService(c.svc).stop(sim_id(c))

    @r("/api/simulations/{id:int}/reset", ["POST"])
    def reset(c):
        return SimulationService(c.svc).reset(sim_id(c))

    @r("/api/simulations/{id:int}/timeline", ["GET"])
    def timeline(c):
        return SimulationService(c.svc).timeline(sim_id(c))

    @r("/api/simulations/{id:int}/impact", ["GET"])
    def impact(c):
        return SimulationService(c.svc).impact(sim_id(c))

    @r("/api/simulations/{id:int}/root-cause", ["GET"])
    def root_cause(c):
        return SimulationService(c.svc).root_cause(sim_id(c))

    @r("/api/simulations/{id:int}/single-points-of-failure", ["GET"])
    def sim_spof(c):
        sim = c.svc.simulations.get_owned(sim_id(c), c.svc.user_id)
        return AnalyticsService(c.svc).spof(c.svc.projects.get_owned(sim["project_id"], c.svc.user_id))

    # ------------------------------------------------------------- recovery
    @r("/api/recovery-strategies", ["GET"])
    def strategies(c):
        return strategy_rows()

    @r("/api/simulations/{id:int}/recovery-plans", ["GET"])
    def list_plans(c):
        return RecoveryService(c.svc).list_plans(sim_id(c))

    @r("/api/simulations/{id:int}/recovery-plans", ["POST"], schema=S.PlanGenerateIn)
    @created
    def generate_plans(c):
        return RecoveryService(c.svc).generate(sim_id(c), c.body.strategies)

    plan_id = lambda c: c.int_param("id")  # noqa: E731

    @r("/api/recovery-plans/{id:int}", ["GET"])
    def get_plan(c):
        return RecoveryService(c.svc).get(plan_id(c))

    @r("/api/recovery-plans/{id:int}/select", ["POST"])
    def select_plan(c):
        return RecoveryService(c.svc).select(plan_id(c))

    @r("/api/recovery-plans/{id:int}/sequence", ["PUT"], schema=S.SequenceIn)
    def reorder(c):
        return RecoveryService(c.svc).reorder(plan_id(c), c.body.component_order, c.body.allow_invalid)

    @r("/api/recovery-plans/{id:int}/execute", ["POST"], schema=S.ExecuteIn)
    def execute(c):
        return RecoveryService(c.svc).execute(plan_id(c), c.body.run_to_completion)

    @r("/api/recovery-plans/{id:int}/step", ["POST"])
    def step(c):
        return RecoveryService(c.svc).step(plan_id(c))

    @r("/api/recovery-plans/{id:int}/pause", ["POST"])
    def pause_plan(c):
        return RecoveryService(c.svc).pause(plan_id(c))

    @r("/api/recovery-plans/{id:int}/resume", ["POST"])
    def resume_plan(c):
        return RecoveryService(c.svc).resume(plan_id(c))

    # -------------------------------------------------------------- reports
    @r("/api/simulations/{id:int}/report", ["GET"])
    def report(c):
        return ReportService(c.svc).build(sim_id(c))

    @r("/api/simulations/{id:int}/report.pdf", ["GET"])
    def report_pdf(c):
        sim = c.svc.simulations.get_owned(sim_id(c), c.svc.user_id)
        pdf = ReportService(c.svc).pdf(sim["id"])
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="resqlens-simulation-{sim["id"]}.pdf"'})

    @r("/api/simulations/{id:int}/export", ["GET"])
    def export_sim(c):
        sim = c.svc.simulations.get_owned(sim_id(c), c.svc.user_id)
        csv = ReportService(c.svc).simulation_csv(sim["id"])
        return Response(csv, media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="resqlens-simulation-{sim["id"]}.csv"'})

    @r("/api/projects/{id:int}/resilience/history", ["GET"])
    def resilience_history(c):
        return c.svc.resilience.history(project(c)["id"], limit=50)

