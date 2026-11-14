"""Demonstration data: University Examination Management System.

All values are explicitly *simulated* example values chosen to be realistic.

Run ``python -m app.seed`` to (re)create the demo account
(demo@resqlens.dev / Demo@2026) with the demo project.
"""
from __future__ import annotations

from .config import get_settings
from .database import Database
from .security import hash_password
from .services.context import ServiceContext
from .engine.events import EventType

DEMO_EMAIL = "demo@resqlens.dev"
DEMO_PASSWORD = "Demo@2026"
DEMO_NAME = "University Examination Management System"

# name, type, criticality, recovery minutes, cost, priority, rule, description
COMPONENTS = [
    ("Student Frontend", "FRONTEND", "HIGH", 5, 4, 2, "STANDARD", "Web portal students use to sign in, take exams and view results."),
    ("API Gateway", "API_GATEWAY", "CRITICAL", 8, 8, 1, "STANDARD", "Single entry point; routes requests to backend services and validates sessions."),
    ("Authentication Service", "AUTH", "CRITICAL", 10, 12, 1, "STANDARD", "Issues and validates student sessions / tokens."),
    ("Session Cache", "CACHE", "MEDIUM", 3, 2, 4, "STANDARD", "Caches active sessions to speed up token validation."),
    ("Student Records Database", "DATABASE", "HIGH", 20, 25, 2, "STANDARD", "Primary store for student accounts and profiles."),
    ("Student Records Replica", "DATABASE", "MEDIUM", 15, 15, 3, "STANDARD", "Read replica configured as backup for the student records database."),
    ("Student Profile Service", "BACKEND", "MEDIUM", 6, 6, 3, "STANDARD", "Profile data, enrolments and exam eligibility."),
    ("Examination Service", "BACKEND", "CRITICAL", 12, 14, 1, "STANDARD", "Schedules exams and loads question papers for students."),
    ("Question Database", "DATABASE", "CRITICAL", 25, 30, 1, "STANDARD", "Stores the question bank and exam papers."),
    ("Submission Service", "BACKEND", "CRITICAL", 10, 12, 1, "STANDARD", "Receives and stores students' answer submissions."),
    ("Submission Storage", "STORAGE", "HIGH", 20, 18, 2, "STANDARD", "Durable object storage for submitted answer sheets."),
    ("Results Service", "BACKEND", "HIGH", 8, 8, 2, "STANDARD", "Computes and publishes results from submissions."),
    ("Notification Service", "BACKEND", "LOW", 4, 3, 5, "STANDARD", "Sends exam reminders and result notifications."),
    ("Notification Queue", "MESSAGE_QUEUE", "LOW", 5, 4, 4, "STANDARD", "Buffers notification jobs between services."),
    ("Email Provider", "EXTERNAL_API", "LOW", 15, 5, 5, "STANDARD", "Third-party email delivery API (simulated)."),
]

# dependent, dependency, type, fallback
DEPENDENCIES = [
    ("Student Frontend", "API Gateway", "MANDATORY", None),
    ("API Gateway", "Authentication Service", "MANDATORY", None),
    ("API Gateway", "Student Profile Service", "OPTIONAL", None),
    ("API Gateway", "Examination Service", "OPTIONAL", None),
    ("API Gateway", "Submission Service", "OPTIONAL", None),
    ("API Gateway", "Results Service", "OPTIONAL", None),
    ("Authentication Service", "Student Records Database", "MANDATORY", "Student Records Replica"),
    ("Authentication Service", "Session Cache", "OPTIONAL", None),
    ("Student Profile Service", "Authentication Service", "MANDATORY", None),
    ("Student Profile Service", "Student Records Database", "MANDATORY", "Student Records Replica"),
    ("Examination Service", "Authentication Service", "MANDATORY", None),
    ("Examination Service", "Question Database", "MANDATORY", None),
    ("Submission Service", "Examination Service", "MANDATORY", None),
    ("Submission Service", "Submission Storage", "MANDATORY", None),
    ("Submission Service", "Notification Queue", "OPTIONAL", None),
    ("Results Service", "Submission Service", "MANDATORY", None),
    ("Results Service", "Authentication Service", "MANDATORY", None),
    ("Notification Service", "Notification Queue", "MANDATORY", None),
    ("Notification Service", "Email Provider", "MANDATORY", None),
    ("Notification Service", "Student Profile Service", "OPTIONAL", None),
]

FUNCTIONALITIES = [
    ("Student Login", True, "Students sign in to the portal", ["Student Frontend", "API Gateway", "Authentication Service"]),
    ("Take Examination", True, "Load the exam paper and answer questions",
     ["Student Frontend", "API Gateway", "Examination Service"]),
    ("Submit Answers", True, "Submit and persist answer sheets", ["Student Frontend", "API Gateway", "Submission Service"]),
    ("View Results", False, "Students view published results", ["Student Frontend", "API Gateway", "Results Service"]),
    ("View Profile", False, "Students view profile and enrolments", ["Student Frontend", "API Gateway", "Student Profile Service"]),
    ("Exam Notifications", False, "Reminder and result e-mails", ["Notification Service"]),
]

SCENARIOS = [
    ("Scenario 1: Question Database Failure",
     "The question bank database crashes during an examination window.", 45,
     [("Question Database", "DATABASE_FAILURE", 8, "Primary DB node lost; storage volume unreadable")]),
    ("Scenario 2: API Gateway Failure",
     "The gateway process crashes after a faulty deployment.", 30,
     [("API Gateway", "COMPLETE_SERVICE_FAILURE", 9, "Gateway pods crash-looping")]),
    ("Scenario 3: Authentication Service Failure",
     "Authentication service runs out of memory under login load.", 30,
     [("Authentication Service", "RESOURCE_EXHAUSTION", 8, "Heap exhausted under peak login traffic")]),
    ("Scenario 4: Storage outage + slow cache",
     "Multiple simultaneous failures: submission storage outage while the session cache is slow.", 60,
     [("Submission Storage", "DATABASE_FAILURE", 7, "Object storage zone outage"),
      ("Session Cache", "HIGH_LATENCY", 6, "Cache nodes swapping")]),
]


def create_demo_project(ctx: ServiceContext, user_id: int) -> int:
    name, i = DEMO_NAME, 2
    while ctx.projects.name_taken(user_id, name):
        name, i = f"{DEMO_NAME} ({i})", i + 1
    pid = ctx.projects.create(user_id, name,
                              "Demonstration architecture of an online university examination platform. All values "
                              "are simulated.", "BLOCKING")
    ids: dict[str, int] = {}
    for (cname, ctype, crit, minutes, cost, prio, rule, desc) in COMPONENTS:
        ids[cname] = ctx.components.create(pid, {
            "name": cname, "component_type": ctype, "criticality": crit, "estimated_recovery_minutes": minutes,
            "recovery_cost": cost, "recovery_priority": prio, "operating_rule": rule, "description": desc})
    for src, tgt, dtype, fb in DEPENDENCIES:
        ctx.dependencies.create(pid, ids[src], ids[tgt], dtype, ids[fb] if fb else None)
    for fname, crit, desc, comps in FUNCTIONALITIES:
        ctx.functionalities.create(pid, fname, desc, crit, [ids[c] for c in comps])
    for sname, desc, duration, fails in SCENARIOS:
        ctx.scenarios.create(pid, sname, desc, [
            {"component_id": ids[c], "failure_type": t, "severity": s, "description": d} for c, t, s, d in fails],
            duration)
    ctx.publish(EventType.PROJECT_CREATED, f"Demo project '{name}' created", pid, category="PROJECT")
    return pid


def ensure_demo_user(db: Database) -> None:
    with db.transaction() as conn:
        ctx = ServiceContext(conn)
        if ctx.users.by_email(DEMO_EMAIL):
            return
        uid = ctx.users.create(DEMO_EMAIL, "Demo Engineer", hash_password(DEMO_PASSWORD))
        ctx.user = ctx.users.get(uid)
        create_demo_project(ctx, uid)


if __name__ == "__main__":  # pragma: no cover
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    from .main import ensure_reference_data
    ensure_reference_data(database)
    ensure_demo_user(database)
    print(f"Demo account ready: {DEMO_EMAIL} / {DEMO_PASSWORD}")
