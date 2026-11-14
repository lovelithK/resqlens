"""Integration tests: a real uvicorn server on a temporary database, exercised
over HTTP exactly like the frontend does."""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

os.environ.setdefault("RESQ_SECRET_KEY", "integration-test-secret-key-0123456789abcdef")

from app.main import create_app  # noqa: E402
from tests.client import Client, LiveServer  # noqa: E402


def _test_database():
    """SQLite temp file by default. Set TEST_DB_ENGINE=mysql to run the same tests
    against a dedicated MySQL database (TEST_DB_NAME, default resqlens_test), which
    is emptied first. Credentials come from DB_HOST/DB_PORT/DB_USER/DB_PASSWORD."""
    if os.environ.get("TEST_DB_ENGINE", "sqlite").lower() != "mysql":
        return os.path.join(tempfile.mkdtemp(), "test.db")
    from app.config import get_settings
    from app.database import Database, DatabaseConfig
    base = get_settings().database
    cfg = DatabaseConfig(engine="mysql", host=base.host, port=base.port, user=base.user, password=base.password,
                         name=os.environ.get("TEST_DB_NAME", "resqlens_test"))
    assert cfg.name != base.name or os.environ.get("TEST_DB_ALLOW_MAIN") == "1", \
        "Refusing to wipe the main database; use a separate TEST_DB_NAME"
    with Database(cfg).transaction() as conn:
        conn.execute("SET FOREIGN_KEY_CHECKS = 0")
        for row in conn.all("SELECT table_name AS t FROM information_schema.tables WHERE table_schema = ?", (cfg.name,)):
            conn.execute(f"DROP TABLE IF EXISTS `{row['t']}`")
        conn.execute("SET FOREIGN_KEY_CHECKS = 1")
    return cfg


@pytest.fixture(scope="module")
def base_url():
    with LiveServer(create_app(_test_database(), seed_demo=False)) as base:
        yield base


def new_user(base, demo=True) -> Client:
    c = Client(base)
    status, body = c.post("/api/auth/register", {"email": f"u{uuid.uuid4().hex[:8]}@example.com",
                                                 "full_name": "Test User", "password": "Passw0rd!",
                                                 "include_demo_project": demo})
    assert status == 201, body
    c.token = body["token"]
    return c


def demo_project(c: Client) -> dict:
    status, projects = c.get("/api/projects")
    assert status == 200
    status, arch = c.get(f"/api/projects/{projects[0]['id']}/architecture")
    return arch


def ids(arch: dict) -> dict[str, int]:
    return {x["name"]: x["id"] for x in arch["components"]}


def run_scenario(c: Client, pid: int, scenario_idx: int = 0, instant=True) -> dict:
    _, scenarios = c.get(f"/api/projects/{pid}/scenarios")
    sc = scenarios[scenario_idx]
    status, sim = c.post("/api/simulations", {"project_id": pid, "name": sc["name"], "failures": sc["failures"]})
    assert status == 201, sim
    status, sim = c.post(f"/api/simulations/{sim['id']}/start", {"instant": instant})
    assert status == 200, sim
    return sim


# ----------------------------------------------------------------- auth
def test_auth_flow_and_session_revocation(base_url):
    c = new_user(base_url)
    assert c.get("/api/auth/me")[0] == 200
    assert c.post("/api/auth/logout")[0] == 200
    status, body = c.get("/api/auth/me")
    assert status == 401 and body["error"]["code"] == "SESSION_REVOKED"


def test_unauthenticated_and_bad_credentials(base_url):
    anon = Client(base_url)
    assert anon.get("/api/projects")[0] == 401
    assert anon.post("/api/auth/login", {"email": "nobody@example.com", "password": "x"})[0] == 401
    status, body = anon.post("/api/auth/register", {"email": "bad", "full_name": "X Y", "password": "short"})
    assert status == 422 and body["error"]["code"] == "VALIDATION_ERROR"


def test_users_cannot_access_each_others_projects(base_url):
    a, b = new_user(base_url), new_user(base_url)
    pid = demo_project(a)["project"]["id"]
    assert b.get(f"/api/projects/{pid}")[0] == 404
    assert b.post("/api/simulations", {"project_id": pid, "failures": [
        {"component_id": 1, "failure_type": "NETWORK_FAILURE", "severity": 5}]})[0] == 404
    comp_id = demo_project(a)["components"][0]["id"]
    assert b.delete(f"/api/components/{comp_id}")[0] == 404


# ----------------------------------------------------------- architecture
def test_architecture_commands_validation_and_undo(base_url):
    c = new_user(base_url, demo=False)
    status, proj = c.post("/api/projects", {"name": "Shop", "description": "test"})
    assert status == 201
    pid = proj["id"]
    mk = lambda n, t="BACKEND": c.post(f"/api/projects/{pid}/components", {"name": n, "component_type": t})[1]["id"]  # noqa
    web, api, db = mk("Web", "FRONTEND"), mk("API"), mk("DB", "DATABASE")
    assert c.post(f"/api/projects/{pid}/components", {"name": "web", "component_type": "CACHE"})[0] == 409
    assert c.post("/api/dependencies", {"project_id": pid, "source_id": web, "target_id": api})[0] == 201
    assert c.post("/api/dependencies", {"project_id": pid, "source_id": api, "target_id": db})[0] == 201
    status, body = c.post("/api/dependencies", {"project_id": pid, "source_id": api, "target_id": db})
    assert status == 409 and body["error"]["code"] == "DUPLICATE_CONNECTION"
    status, body = c.post("/api/dependencies", {"project_id": pid, "source_id": db, "target_id": web})
    assert status == 409 and body["error"]["code"] == "CIRCULAR_DEPENDENCY"
    assert c.post("/api/dependencies", {"project_id": pid, "source_id": db, "target_id": db})[0] == 422
    # undo the last connection, then the removal of a component restores its edges
    assert c.post(f"/api/projects/{pid}/undo")[0] == 200
    assert len(c.get(f"/api/projects/{pid}/architecture")[1]["dependencies"]) == 1
    assert c.delete(f"/api/components/{api}")[0] == 204
    assert len(c.get(f"/api/projects/{pid}/architecture")[1]["dependencies"]) == 0
    assert c.post(f"/api/projects/{pid}/undo")[0] == 200
    arch = c.get(f"/api/projects/{pid}/architecture")[1]
    assert {x["name"] for x in arch["components"]} == {"Web", "API", "DB"} and len(arch["dependencies"]) == 1
    hist = c.get(f"/api/projects/{pid}/commands")[1]
    assert sum(1 for h in hist if h["status"] == "UNDONE") == 2
    assert hist[0]["command_name"] == "RemoveComponentCommand"


def test_import_with_cycle_is_reported_and_blocks_simulation(base_url):
    c = new_user(base_url, demo=False)
    data = {"project": {"name": "Cyclic"}, "components": [
        {"name": "A", "component_type": "BACKEND"}, {"name": "B", "component_type": "BACKEND"}],
        "dependencies": [{"source": "A", "target": "B"}, {"source": "B", "target": "A"}]}
    status, proj = c.post("/api/projects/import", {"data": data})
    assert status == 201
    v = c.post(f"/api/projects/{proj['id']}/validate")[1]
    assert not v["valid"] and v["issues"][0]["code"] == "CIRCULAR_DEPENDENCY"
    comp = c.get(f"/api/projects/{proj['id']}/components")[1][0]
    _, sim = c.post("/api/simulations", {"project_id": proj["id"], "failures": [
        {"component_id": comp["id"], "failure_type": "COMPLETE_SERVICE_FAILURE", "severity": 5}]})
    status, body = c.post(f"/api/simulations/{sim['id']}/start", {})
    assert status == 422 and body["error"]["code"] == "INVALID_ARCHITECTURE"


# ------------------------------------------------------------- simulation
def test_stepwise_simulation_lifecycle(base_url):
    c = new_user(base_url)
    arch = demo_project(c)
    pid, n = arch["project"]["id"], ids(arch)
    sim = run_scenario(c, pid, 0, instant=False)
    sid = sim["id"]
    assert sim["status"] == "RUNNING" and sim["current_tick"] == 0
    assert c.post(f"/api/simulations/{sid}/start", {})[1]["error"]["code"] == "DUPLICATE_EXECUTION"
    assert c.post(f"/api/simulations/{sid}/pause")[1]["status"] == "PAUSED"
    assert c.post(f"/api/simulations/{sid}/tick")[0] == 409            # paused -> no progress
    assert c.post(f"/api/simulations/{sid}/resume")[1]["status"] == "RUNNING"
    # live component state follows the revealed ticks (Observer -> graph state)
    comps = {x["name"]: x for x in c.get(f"/api/projects/{pid}/components")[1]}
    assert comps["Question Database"]["status"] == "FAILED" and comps["Examination Service"]["status"] == "HEALTHY"
    sim = c.post(f"/api/simulations/{sid}/tick")[1]
    assert sim["current_tick"] == 1
    comps = {x["name"]: x for x in c.get(f"/api/projects/{pid}/components")[1]}
    assert comps["Examination Service"]["status"] == "BLOCKED"
    # editing during an active simulation is rejected
    status, body = c.put(f"/api/components/{n['Results Service']}", {"criticality": "LOW"})
    assert status == 409 and body["error"]["code"] == "SIMULATION_ACTIVE"
    sim = c.post(f"/api/simulations/{sid}/stop")[1]
    assert sim["status"] == "STOPPED"
    impact = c.get(f"/api/simulations/{sid}/impact")[1]
    assert impact["total_affected"] == 2                                  # only revealed ticks count
    assert c.post(f"/api/simulations/{sid}/reset")[1]["status"] == "RESET"
    comps = c.get(f"/api/projects/{pid}/components")[1]
    assert all(x["status"] == "HEALTHY" for x in comps)


def test_analysis_endpoints_for_question_database_scenario(base_url):
    c = new_user(base_url)
    pid = demo_project(c)["project"]["id"]
    sim = run_scenario(c, pid, 0)
    assert sim["status"] == "PROPAGATED"
    impact = c.get(f"/api/simulations/{sim['id']}/impact")[1]
    names = {x["name"]: x["impact_type"] for x in impact["components"]}
    assert names == {"Question Database": "SOURCE", "Examination Service": "DIRECT",
                     "Submission Service": "INDIRECT", "Results Service": "INDIRECT"}
    rca = c.get(f"/api/simulations/{sim['id']}/root-cause")[1]
    assert [v["component_name"] for v in rca["verified_causes"]] == ["Question Database"]
    assert [x["name"] for x in rca["inferred_candidates"]] == ["Question Database"]
    assert len(c.get(f"/api/simulations/{sim['id']}/timeline")[1]) >= 6
    spof = c.get(f"/api/projects/{pid}/single-points-of-failure")[1]
    assert any(r["name"] == "API Gateway" and r["is_spof"] for r in spof)


def test_recovery_valid_plan_and_reports(base_url):
    c = new_user(base_url)
    pid = demo_project(c)["project"]["id"]
    sim = run_scenario(c, pid, 2)                                          # authentication failure
    status, plans = c.post(f"/api/simulations/{sim['id']}/recovery-plans", {})
    assert status == 201 and len(plans["plans"]) == 4
    plan = plans["plans"][0]
    assert c.post(f"/api/recovery-plans/{plan['id']}/select")[1]["is_selected"]
    p = c.post(f"/api/recovery-plans/{plan['id']}/execute", {})[1]
    assert p["status"] == "EXECUTING"
    assert c.post(f"/api/recovery-plans/{plan['id']}/execute", {})[1]["error"]["code"] == "DUPLICATE_EXECUTION"
    assert c.post(f"/api/recovery-plans/{plan['id']}/pause")[1]["status"] == "PAUSED"
    assert c.post(f"/api/recovery-plans/{plan['id']}/step")[0] == 409
    c.post(f"/api/recovery-plans/{plan['id']}/resume")
    while p["status"] == "EXECUTING":
        p = c.post(f"/api/recovery-plans/{plan['id']}/step")[1]
    assert p["status"] == "COMPLETED" and p["summary"]["actions_failed"] == 0
    assert c.get(f"/api/simulations/{sim['id']}")[1]["status"] == "RECOVERED"
    assert all(x["status"] == "HEALTHY" for x in c.get(f"/api/projects/{pid}/components")[1])
    res = c.get(f"/api/projects/{pid}/resilience")[1]
    assert next(b for b in res["breakdown"] if b["key"] == "recovery")["included"]
    status, pdf = c.get(f"/api/simulations/{sim['id']}/report.pdf", raw=True)
    assert status == 200 and pdf.startswith(b"%PDF")
    status, csv = c.get(f"/api/simulations/{sim['id']}/export", raw=True)
    assert status == 200 and b"Authentication Service" in csv
    hist = c.get("/api/simulations?severity=" + sim["severity_class"])[1]
    assert any(h["id"] == sim["id"] for h in hist)
    assert c.get("/api/simulations?severity=LOW&date_from=2099-01-01")[1] == []
    dash = c.get("/api/dashboard")[1]
    assert dash["totals"]["recovery_operations"] == 1 and dash["totals"]["simulations"] == 1


def test_invalid_manual_sequence_records_failures_then_follow_up_plan_recovers(base_url):
    c = new_user(base_url)
    pid = demo_project(c)["project"]["id"]
    sim = run_scenario(c, pid, 0)                                          # QDB -> Exam -> Sub -> Results
    plan = c.post(f"/api/simulations/{sim['id']}/recovery-plans",
                  {"strategies": ["DEPENDENCY_FIRST"]})[1]["plans"][0]
    bad = [a["component_id"] for a in reversed(plan["actions"])]          # Results, Sub, Exam, QDB
    status, body = c.put(f"/api/recovery-plans/{plan['id']}/sequence", {"component_order": bad})
    assert status == 422 and body["error"]["code"] == "INVALID_RECOVERY_SEQUENCE"
    p = c.put(f"/api/recovery-plans/{plan['id']}/sequence", {"component_order": bad, "allow_invalid": True})[1]
    assert p["is_manual"] and not p["is_valid"]
    p = c.post(f"/api/recovery-plans/{plan['id']}/execute", {"run_to_completion": True})[1]
    # Each downstream action fails, is re-queued once; only Exam succeeds on retry (DB restored by then).
    acts = {a["component_name"]: a for a in p["actions"]}
    assert p["status"] == "COMPLETED_WITH_FAILURES"
    assert acts["Question Database"]["status"] == "COMPLETED" and acts["Examination Service"]["status"] == "COMPLETED"
    assert acts["Results Service"]["status"] == "FAILED" and acts["Submission Service"]["status"] == "FAILED"
    assert "Mandatory dependency unavailable" in acts["Results Service"]["failure_reason"]
    assert p["actual_minutes"] > 0
    assert c.get(f"/api/simulations/{sim['id']}")[1]["status"] == "PARTIALLY_RECOVERED"
    # a follow-up plan covers only what is still broken and restores the system
    plans = c.post(f"/api/simulations/{sim['id']}/recovery-plans", {"strategies": ["CRITICALITY_FIRST"]})[1]["plans"]
    follow = [x for x in plans if x["status"] == "DRAFT"][0]
    assert [a["component_name"] for a in follow["actions"]] == ["Submission Service", "Results Service"]
    p = c.post(f"/api/recovery-plans/{follow['id']}/execute", {"run_to_completion": True})[1]
    assert p["status"] == "COMPLETED"
    assert c.get(f"/api/simulations/{sim['id']}")[1]["status"] == "RECOVERED"


def test_multiple_simultaneous_failures(base_url):
    c = new_user(base_url)
    arch = demo_project(c)
    pid, n = arch["project"]["id"], ids(arch)
    _, sim = c.post("/api/simulations", {"project_id": pid, "failures": [
        {"component_id": n["Question Database"], "failure_type": "DATABASE_FAILURE", "severity": 6},
        {"component_id": n["Submission Storage"], "failure_type": "DATABASE_FAILURE", "severity": 6}]})
    assert sim["failure_type"] == "MULTIPLE_SIMULTANEOUS"
    sim = c.post(f"/api/simulations/{sim['id']}/start", {"instant": True})[1]
    sub = next(r for r in sim["results"] if r["component_name"] == "Submission Service")
    assert sub["status"] == "BLOCKED" and sorted(sub["causes"]) == sorted([n["Examination Service"], n["Submission Storage"]])
    rca = c.get(f"/api/simulations/{sim['id']}/root-cause")[1]
    assert {x["name"] for x in rca["inferred_candidates"]} == {"Question Database", "Submission Storage"}
    p = c.post(f"/api/simulations/{sim['id']}/recovery-plans", {"strategies": ["MAX_FUNCTIONALITY"]})[1]["plans"][0]
    p = c.post(f"/api/recovery-plans/{p['id']}/execute", {"run_to_completion": True})[1]
    assert p["status"] == "COMPLETED"


def test_what_if_and_compare(base_url):
    c = new_user(base_url)
    pid = demo_project(c)["project"]["id"]
    scenarios = c.get(f"/api/projects/{pid}/scenarios")[1][:3]
    out = c.post(f"/api/projects/{pid}/what-if", {"scenarios": [
        {"name": s["name"], "failures": s["failures"]} for s in scenarios]})[1]
    assert [o["affected_components"] for o in out] == [4, 2, 7]
    s1 = run_scenario(c, pid, 0)
    c.post(f"/api/simulations/{s1['id']}/reset")
    s2 = run_scenario(c, pid, 1)
    cmp = c.get(f"/api/simulations/compare?ids={s1['id']},{s2['id']}")[1]
    assert len(cmp) == 2 and cmp[0]["impact_score"] is not None
    assert c.get("/api/simulations/compare?ids=1")[0] == 422
