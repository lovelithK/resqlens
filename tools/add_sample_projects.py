"""Add four sample architectures to ResQLens and run two failure simulations.

Uses the running API (http://127.0.0.1:8000, or the URL in RESQLENS_API) as the demo account, exactly as the
web app would. Safe to re-run: projects that already exist are skipped, and a
simulation is only run if its project has none yet.

All values are simulated example data.
Writes a summary to logs/sample_data_report.txt.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("RESQLENS_API", "http://127.0.0.1:8000").rstrip("/")  # e.g. the live Render URL
DEMO_EMAIL = "demo@resqlens.dev"
DEMO_PASSWORD = "Demo@2026"  # public demo account created by app.seed, not a real secret


def comp(name, ctype, crit, minutes, cost, priority, desc):
    return {"name": name, "component_type": ctype, "criticality": crit, "estimated_recovery_minutes": minutes,
            "recovery_cost": cost, "recovery_priority": priority, "operating_rule": "STANDARD",
            "baseline_status": "HEALTHY", "baseline_health": 100, "description": desc}


def dep(source, target, kind="MANDATORY", fallback=None):
    d = {"source": source, "target": target, "dependency_type": kind}
    if fallback:
        d["fallback"] = fallback
    return d


def func(name, critical, desc, components):
    return {"name": name, "is_critical": critical, "description": desc, "components": components}


def scen(name, desc, minutes, failures):
    return {"name": name, "description": desc, "duration_minutes": minutes,
            "failures": [{"component": c, "failure_type": t, "severity": s, "description": d} for c, t, s, d in failures]}


PROJECTS = [
    {
        "project": {"name": "E-Commerce Checkout Platform", "propagation_policy": "BLOCKING",
                    "description": "Online store: browsing, cart, checkout and payment for a mid-size retailer."},
        "components": [
            comp("Storefront Web App", "FRONTEND", "HIGH", 5, 4, 2, "Customer-facing shop website."),
            comp("API Gateway", "API_GATEWAY", "CRITICAL", 8, 8, 1, "Routes all customer requests."),
            comp("Customer Auth", "AUTH", "HIGH", 10, 10, 2, "Sign-in and guest checkout tokens."),
            comp("Product Catalog Service", "BACKEND", "HIGH", 6, 6, 2, "Product listings, prices and search."),
            comp("Cart Service", "BACKEND", "CRITICAL", 6, 6, 1, "Keeps each customer's basket."),
            comp("Checkout Service", "BACKEND", "CRITICAL", 10, 12, 1, "Builds and confirms orders."),
            comp("Payment Gateway", "EXTERNAL_API", "CRITICAL", 20, 15, 1, "Third-party card processor (simulated)."),
            comp("Inventory Service", "BACKEND", "HIGH", 8, 8, 2, "Reserves stock for orders."),
            comp("Orders Database", "DATABASE", "CRITICAL", 25, 30, 1, "Primary store for orders and stock."),
            comp("Orders Database Replica", "DATABASE", "MEDIUM", 15, 15, 3, "Standby replica of the orders database."),
            comp("Product Cache", "CACHE", "MEDIUM", 3, 2, 4, "Caches catalog pages."),
            comp("Order Events Queue", "MESSAGE_QUEUE", "MEDIUM", 5, 4, 3, "Publishes order-placed events."),
            comp("Email Service", "EXTERNAL_API", "LOW", 10, 3, 5, "Order confirmation e-mails (simulated)."),
        ],
        "dependencies": [
            dep("Storefront Web App", "API Gateway"),
            dep("API Gateway", "Customer Auth"),
            dep("API Gateway", "Product Catalog Service", "OPTIONAL"),
            dep("API Gateway", "Cart Service", "OPTIONAL"),
            dep("API Gateway", "Checkout Service", "OPTIONAL"),
            dep("Product Catalog Service", "Product Cache", "OPTIONAL"),
            dep("Product Catalog Service", "Orders Database", "MANDATORY", "Orders Database Replica"),
            dep("Cart Service", "Customer Auth"),
            dep("Cart Service", "Product Catalog Service"),
            dep("Checkout Service", "Cart Service"),
            dep("Checkout Service", "Payment Gateway"),
            dep("Checkout Service", "Inventory Service"),
            dep("Checkout Service", "Order Events Queue", "OPTIONAL"),
            dep("Inventory Service", "Orders Database", "MANDATORY", "Orders Database Replica"),
            dep("Email Service", "Order Events Queue"),
        ],
        "functionalities": [
            func("Browse Products", False, "Customers search and view products",
                 ["Storefront Web App", "API Gateway", "Product Catalog Service"]),
            func("Manage Cart", True, "Add and remove items", ["Storefront Web App", "API Gateway", "Cart Service"]),
            func("Place Order", True, "Pay and confirm an order",
                 ["Storefront Web App", "API Gateway", "Checkout Service"]),
            func("Order Emails", False, "Confirmation e-mails", ["Email Service"]),
        ],
        "scenarios": [
            scen("Payment provider timeout", "The card processor stops answering during a sale.", 40,
                 [("Payment Gateway", "API_TIMEOUT", 7, "Processor responses exceed 30 s")]),
            scen("Orders database outage", "The primary orders database goes down.", 60,
                 [("Orders Database", "DATABASE_FAILURE", 9, "Primary node unreachable")]),
        ],
    },
    {
        "project": {"name": "Hospital Patient Records System", "propagation_policy": "BLOCKING",
                    "description": "Clinical records, appointments, lab results and pharmacy orders for a hospital."},
        "components": [
            comp("Clinician Portal", "FRONTEND", "CRITICAL", 5, 5, 1, "Web app used by doctors and nurses."),
            comp("Patient App", "FRONTEND", "MEDIUM", 5, 4, 3, "Mobile app for patients."),
            comp("Integration Gateway", "API_GATEWAY", "CRITICAL", 8, 10, 1, "Single entry point for all clients."),
            comp("Staff Identity Service", "AUTH", "CRITICAL", 10, 12, 1, "Staff sign-in and role checks."),
            comp("Patient Records Service", "BACKEND", "CRITICAL", 12, 14, 1, "Medical histories and notes."),
            comp("Appointment Service", "BACKEND", "HIGH", 8, 8, 2, "Bookings and clinic schedules."),
            comp("Lab Results Service", "BACKEND", "HIGH", 10, 10, 2, "Receives results from lab machines."),
            comp("Pharmacy Service", "BACKEND", "HIGH", 10, 10, 2, "Prescriptions and dispensing."),
            comp("Clinical Database", "DATABASE", "CRITICAL", 30, 35, 1, "Primary patient data store."),
            comp("Clinical Database Standby", "DATABASE", "HIGH", 20, 20, 2, "Hot standby of the clinical database."),
            comp("Medical Imaging Storage", "STORAGE", "HIGH", 25, 20, 2, "Scans and X-ray images."),
            comp("HL7 Message Bus", "MESSAGE_QUEUE", "HIGH", 8, 6, 2, "Carries messages between hospital systems."),
        ],
        "dependencies": [
            dep("Clinician Portal", "Integration Gateway"),
            dep("Patient App", "Integration Gateway"),
            dep("Integration Gateway", "Staff Identity Service"),
            dep("Integration Gateway", "Patient Records Service", "OPTIONAL"),
            dep("Integration Gateway", "Appointment Service", "OPTIONAL"),
            dep("Integration Gateway", "Pharmacy Service", "OPTIONAL"),
            dep("Patient Records Service", "Clinical Database", "MANDATORY", "Clinical Database Standby"),
            dep("Patient Records Service", "Medical Imaging Storage", "OPTIONAL"),
            dep("Patient Records Service", "Lab Results Service", "OPTIONAL"),
            dep("Appointment Service", "Clinical Database", "MANDATORY", "Clinical Database Standby"),
            dep("Lab Results Service", "HL7 Message Bus"),
            dep("Lab Results Service", "Clinical Database", "MANDATORY", "Clinical Database Standby"),
            dep("Pharmacy Service", "Patient Records Service"),
            dep("Pharmacy Service", "HL7 Message Bus", "OPTIONAL"),
        ],
        "functionalities": [
            func("View Patient Chart", True, "Clinicians open a patient's record",
                 ["Clinician Portal", "Integration Gateway", "Patient Records Service"]),
            func("Book Appointment", False, "Patients and staff book visits",
                 ["Patient App", "Integration Gateway", "Appointment Service"]),
            func("Review Lab Results", True, "Clinicians see new results", ["Clinician Portal", "Lab Results Service"]),
            func("Issue Prescription", True, "Send prescriptions to the pharmacy",
                 ["Clinician Portal", "Integration Gateway", "Pharmacy Service"]),
        ],
        "scenarios": [
            scen("Staff sign-in outage", "The identity service fails at shift change.", 30,
                 [("Staff Identity Service", "COMPLETE_SERVICE_FAILURE", 9, "Identity pods crash-looping")]),
            scen("Message bus overload", "The HL7 bus runs out of memory.", 45,
                 [("HL7 Message Bus", "RESOURCE_EXHAUSTION", 7, "Queue memory exhausted")]),
        ],
    },
    {
        "project": {"name": "Food Delivery App", "propagation_policy": "FAIL_FAST",
                    "description": "Restaurant ordering, rider dispatch and live tracking for a city delivery service."},
        "components": [
            comp("Customer Mobile App", "FRONTEND", "HIGH", 5, 4, 2, "App customers use to order food."),
            comp("Rider App", "FRONTEND", "HIGH", 5, 4, 2, "App riders use to accept deliveries."),
            comp("Edge Gateway", "API_GATEWAY", "CRITICAL", 8, 8, 1, "Routes mobile traffic."),
            comp("User Accounts", "AUTH", "HIGH", 8, 8, 2, "Customer and rider sign-in."),
            comp("Restaurant Menu Service", "BACKEND", "HIGH", 6, 6, 2, "Menus and availability."),
            comp("Order Service", "BACKEND", "CRITICAL", 10, 12, 1, "Creates and tracks orders."),
            comp("Dispatch Service", "BACKEND", "CRITICAL", 10, 10, 1, "Matches orders to riders."),
            comp("Live Tracking Service", "BACKEND", "MEDIUM", 6, 5, 3, "Rider location updates."),
            comp("Maps API", "EXTERNAL_API", "HIGH", 15, 8, 2, "Routing and ETAs (simulated)."),
            comp("Payments Provider", "EXTERNAL_API", "CRITICAL", 20, 15, 1, "Card and wallet payments (simulated)."),
            comp("Orders Store", "DATABASE", "CRITICAL", 25, 25, 1, "Orders, riders and restaurants."),
            comp("Location Cache", "CACHE", "MEDIUM", 3, 2, 4, "Latest rider positions."),
        ],
        "dependencies": [
            dep("Customer Mobile App", "Edge Gateway"),
            dep("Rider App", "Edge Gateway"),
            dep("Edge Gateway", "User Accounts"),
            dep("Edge Gateway", "Restaurant Menu Service", "OPTIONAL"),
            dep("Edge Gateway", "Order Service", "OPTIONAL"),
            dep("Edge Gateway", "Live Tracking Service", "OPTIONAL"),
            dep("Restaurant Menu Service", "Orders Store"),
            dep("Order Service", "Payments Provider"),
            dep("Order Service", "Orders Store"),
            dep("Order Service", "Dispatch Service", "OPTIONAL"),
            dep("Dispatch Service", "Maps API"),
            dep("Dispatch Service", "Orders Store"),
            dep("Live Tracking Service", "Location Cache"),
            dep("Live Tracking Service", "Maps API", "OPTIONAL"),
        ],
        "functionalities": [
            func("Browse Restaurants", False, "See menus nearby",
                 ["Customer Mobile App", "Edge Gateway", "Restaurant Menu Service"]),
            func("Place Food Order", True, "Order and pay", ["Customer Mobile App", "Edge Gateway", "Order Service"]),
            func("Assign Rider", True, "Dispatch a rider to the order", ["Dispatch Service"]),
            func("Track Delivery", False, "Follow the rider live",
                 ["Customer Mobile App", "Edge Gateway", "Live Tracking Service"]),
        ],
        "scenarios": [
            scen("Maps provider slowdown", "Routing calls become very slow at dinner time.", 30,
                 [("Maps API", "HIGH_LATENCY", 6, "ETA requests take 8-10 s")]),
            scen("Payments outage", "The payments provider rejects all requests.", 25,
                 [("Payments Provider", "COMPLETE_SERVICE_FAILURE", 9, "Provider returns HTTP 503")]),
        ],
    },
    {
        "project": {"name": "Online Banking Portal", "propagation_policy": "BLOCKING",
                    "description": "Retail internet banking: accounts, transfers, bill payments and alerts."},
        "components": [
            comp("Banking Web App", "FRONTEND", "CRITICAL", 5, 5, 1, "Customer internet banking site."),
            comp("Banking Mobile App", "FRONTEND", "HIGH", 5, 5, 2, "Customer mobile banking app."),
            comp("Secure API Gateway", "API_GATEWAY", "CRITICAL", 10, 12, 1, "Rate-limited entry point with TLS."),
            comp("Login and OTP Service", "AUTH", "CRITICAL", 12, 14, 1, "Passwords and one-time codes."),
            comp("Accounts Service", "BACKEND", "CRITICAL", 10, 12, 1, "Balances and statements."),
            comp("Transfers Service", "BACKEND", "CRITICAL", 12, 15, 1, "Moves money between accounts."),
            comp("Bill Payments Service", "BACKEND", "HIGH", 10, 10, 2, "Pays utility and card bills."),
            comp("Fraud Check Service", "BACKEND", "HIGH", 8, 10, 2, "Scores each transfer for fraud."),
            comp("Core Banking Database", "DATABASE", "CRITICAL", 40, 50, 1, "Ledger and account data."),
            comp("Core Banking DR Site", "DATABASE", "HIGH", 30, 40, 2, "Disaster-recovery copy of the ledger."),
            comp("SMS Gateway", "EXTERNAL_API", "HIGH", 10, 5, 2, "Sends OTP and alert texts (simulated)."),
            comp("Alerts Queue", "MESSAGE_QUEUE", "LOW", 5, 3, 4, "Buffers customer alerts."),
        ],
        "dependencies": [
            dep("Banking Web App", "Secure API Gateway"),
            dep("Banking Mobile App", "Secure API Gateway"),
            dep("Secure API Gateway", "Login and OTP Service"),
            dep("Secure API Gateway", "Accounts Service", "OPTIONAL"),
            dep("Secure API Gateway", "Transfers Service", "OPTIONAL"),
            dep("Secure API Gateway", "Bill Payments Service", "OPTIONAL"),
            dep("Login and OTP Service", "SMS Gateway"),
            dep("Login and OTP Service", "Core Banking Database", "MANDATORY", "Core Banking DR Site"),
            dep("Accounts Service", "Core Banking Database", "MANDATORY", "Core Banking DR Site"),
            dep("Transfers Service", "Accounts Service"),
            dep("Transfers Service", "Fraud Check Service"),
            dep("Transfers Service", "Alerts Queue", "OPTIONAL"),
            dep("Bill Payments Service", "Accounts Service"),
            dep("Fraud Check Service", "Core Banking Database", "MANDATORY", "Core Banking DR Site"),
        ],
        "functionalities": [
            func("Sign In", True, "Customers sign in with password and OTP",
                 ["Banking Web App", "Secure API Gateway", "Login and OTP Service"]),
            func("View Balance", True, "See balances and statements",
                 ["Banking Web App", "Secure API Gateway", "Accounts Service"]),
            func("Transfer Money", True, "Send money to another account",
                 ["Banking Web App", "Secure API Gateway", "Transfers Service"]),
            func("Pay Bills", False, "Pay utility bills", ["Banking Web App", "Secure API Gateway", "Bill Payments Service"]),
        ],
        "scenarios": [
            scen("SMS provider failure", "One-time codes stop arriving.", 35,
                 [("SMS Gateway", "NETWORK_FAILURE", 8, "Provider unreachable from the data centre")]),
            scen("Fraud engine degradation", "Fraud scoring partially fails after an update.", 30,
                 [("Fraud Check Service", "PARTIAL_DEGRADATION", 5, "Model server returns errors for 40% of calls")]),
        ],
    },
]

# Two simulations to run: (project name, scenario name)
SIMULATIONS = [
    ("E-Commerce Checkout Platform", "Payment provider timeout"),
    ("Hospital Patient Records System", "Staff sign-in outage"),
]


class Api:
    def __init__(self):
        self.token = None

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:400]}") from None


def unwrap(x):
    return x.get("data", x) if isinstance(x, dict) else x


def main() -> int:
    log: list[str] = []
    say = lambda s="": (print(s), log.append(s))  # noqa: E731
    api = Api()
    try:
        unwrap(api.call("GET", "/api/health"))
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] Backend not reachable on {API}: {e}")
        return 1
    login = unwrap(api.call("POST", "/api/auth/login", {"email": DEMO_EMAIL, "password": DEMO_PASSWORD}))
    api.token = login.get("token") or login.get("access_token")
    if not api.token:
        print("[ERROR] Login response had no token:", list(login))
        return 1
    say("ResQLens sample data report (all values simulated)")
    say("Signed in as the demo account")
    say()

    existing = {p["name"]: p for p in unwrap(api.call("GET", "/api/projects"))}
    ids = {}
    say("== Projects ==")
    for spec in PROJECTS:
        name = spec["project"]["name"]
        if name in existing:
            ids[name] = existing[name]["id"]
            say(f"[SKIP] {name} already exists (id {ids[name]})")
            continue
        p = unwrap(api.call("POST", "/api/projects/import", {"data": spec}))
        ids[name] = p["id"]
        val = unwrap(api.call("POST", f"/api/projects/{p['id']}/validate"))
        ok = val.get("valid", val.get("is_valid", True)) if isinstance(val, dict) else True
        say(f"[OK] {name} created (id {p['id']}): {len(spec['components'])} components, "
            f"{len(spec['dependencies'])} dependencies, {len(spec['functionalities'])} functionalities, "
            f"{len(spec['scenarios'])} scenarios; validation {'passed' if ok else 'has warnings'}")
    say()

    say("== Simulations ==")
    for pname, sname in SIMULATIONS:
        pid = ids[pname]
        prior = unwrap(api.call("GET", f"/api/simulations?project_id={pid}"))
        if prior:
            say(f"[SKIP] {pname} already has {len(prior)} simulation(s)")
            continue
        scenarios = unwrap(api.call("GET", f"/api/projects/{pid}/scenarios"))
        sc = next(s for s in scenarios if s["name"] == sname)
        failures = [{k: f[k] for k in ("component_id", "failure_type", "severity", "description") if k in f}
                    for f in sc["failures"]]
        sim = unwrap(api.call("POST", "/api/simulations", {
            "project_id": pid, "name": sname, "description": sc.get("description", ""),
            "duration_minutes": sc.get("duration_minutes", 30), "failures": failures}))
        api.call("POST", f"/api/simulations/{sim['id']}/start", {"instant": True})
        imp = unwrap(api.call("GET", f"/api/simulations/{sim['id']}/impact"))
        rc = unwrap(api.call("GET", f"/api/simulations/{sim['id']}/root-cause"))
        causes = ", ".join(c["component_name"] for c in rc.get("verified_causes", [])) or "none"
        say(f"[OK] {pname} - '{sname}' (simulation id {sim['id']}): impact {imp['impact_score']} "
            f"({imp['severity_class']}), {imp['total_affected']} of {imp['component_count']} components affected, "
            f"{imp['unavailable_functionality_count']} functionality(ies) unavailable, verified root cause: {causes}")
    say()
    say("Open http://localhost:5173 and pick the projects from the project switcher.")

    out = Path(__file__).resolve().parent.parent / "logs"
    out.mkdir(exist_ok=True)
    (out / "sample_data_report.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
