"""Report generation: structured report model, PDF (ReportLab) and CSV (pandas)."""
from __future__ import annotations

import io

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ..database import loads, utcnow
from ..domain.enums import COMPONENT_TYPE_LABELS
from ..engine.dependency_manager import DependencyManager
from ..repositories import load_architecture
from .analytics import AnalyticsService
from .context import ServiceContext
from .recovery import RecoveryService
from .simulation import SimulationService

NAVY = colors.HexColor("#0f1b2d")
ACCENT = colors.HexColor("#2f7df6")
MUTED = colors.HexColor("#5b6b82")
GRID = colors.HexColor("#d5dce6")
STATUS_COLORS = {"HEALTHY": "#16a34a", "DEGRADED": "#d97706", "FAILED": "#dc2626", "BLOCKED": "#b91c1c",
                 "RECOVERING": "#2563eb"}


class ReportService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    # -- model ------------------------------------------------------------------
    def build(self, sim_id: int) -> dict:
        sims = SimulationService(self.ctx)
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        project = self.ctx.projects.get_owned(sim["project_id"], self.ctx.user_id)
        arch = load_architecture(self.ctx.conn, project)
        stats = DependencyManager(arch).stats()
        detail = sims.detail(sim_id)
        impact = sims.impact(sim_id) if sim["status"] != "CREATED" else None
        rca = sims.root_cause(sim_id) if sim["status"] != "CREATED" else None
        plans = RecoveryService(self.ctx).list_plans(sim_id)["plans"]
        executed = next((p for p in plans if p["status"] in ("COMPLETED", "COMPLETED_WITH_FAILURES", "EXECUTING",
                                                              "PAUSED", "SUPERSEDED") and p["started_at"]), None)
        selected = executed or next((p for p in plans if p["is_selected"]), None) or (plans[0] if plans else None)
        resilience = AnalyticsService(self.ctx).resilience(project)
        return {
            "generated_at": utcnow(),
            "project": {"id": project["id"], "name": project["name"], "description": project["description"],
                        "propagation_policy": project["propagation_policy"]},
            "architecture": {**stats, "components": [
                {"name": c.name, "type": COMPONENT_TYPE_LABELS[c.component_type.value], "criticality": c.criticality.value,
                 "recovery_minutes": c.estimated_recovery_minutes, "status": c.status.value, "health": c.health}
                for c in arch.components.values()]},
            "simulation": {k: detail[k] for k in ("id", "name", "description", "status", "failure_type",
                                                  "duration_minutes", "created_at", "started_at", "completed_at",
                                                  "impact_score", "severity_class", "propagation_policy")},
            "failures": detail["failures"],
            "propagation_steps": detail["propagation_steps"],
            "impact": impact,
            "root_cause": rca,
            "recovery_plan": selected,
            "compared_plans": [{"strategy": p["strategy"]["name"], **{k: p["metrics"].get(k) for k in (
                "estimated_minutes", "total_cost", "functionality_downtime_minutes",
                "critical_functionality_restored_at")}} for p in plans if p["status"] != "SUPERSEDED"],
            "final_health": {"weighted_health": resilience.get("weighted_health"),
                             "distribution": resilience.get("health_distribution")},
            "resilience": {k: resilience.get(k) for k in ("score", "grade", "breakdown", "single_points_of_failure")},
            "timeline": sims.timeline(sim_id),
        }

    # -- PDF ----------------------------------------------------------------------
    def pdf(self, sim_id: int) -> bytes:
        r = self.build(sim_id)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                                bottomMargin=16 * mm, title=f"ResQLens report – {r['simulation']['name']}",
                                author="ResQLens")
        ss = getSampleStyleSheet()
        h1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=18, spaceAfter=4)
        h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=12.5, spaceBefore=10, spaceAfter=5)
        body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12.5, alignment=TA_LEFT)
        small = ParagraphStyle("s", parent=body, fontSize=8, textColor=MUTED, leading=10.5)
        cell = ParagraphStyle("c", parent=body, fontSize=8, leading=10)
        story = []

        def p(text, style=body):
            return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                             .replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"), style)

        def table(rows, widths, header=True):
            data = [[p(c, cell) for c in row] for row in rows]
            t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
            style = [("GRID", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                     ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
            if header:
                style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3fb"))]
            t.setStyle(TableStyle(style))
            return t

        sim = r["simulation"]
        story.append(p("ResQLens – Failure Simulation &amp; Recovery Report".replace("&amp;", "&"), h1))
        story.append(p(f"Project <b>{r['project']['name']}</b> · Simulation <b>{sim['name']}</b> · generated "
                       f"{r['generated_at'][:16].replace('T', ' ')} UTC", small))
        story.append(p("All values in this report come from ResQLens' deterministic, rule-based simulation of the "
                       "modelled architecture. They are not measurements of a production incident.", small))
        story.append(Spacer(1, 6))
        imp = r["impact"] or {}
        kpis = [["Impact score", "Severity", "Affected components", "Unavailable functionality", "Status"],
                [str(imp.get("impact_score", "-")), imp.get("severity_class", "-"), str(imp.get("total_affected", "-")),
                 f"{imp.get('unavailable_functionality_count', '-')}/{imp.get('functionality_count', '-')}", sim["status"]]]
        story.append(table(kpis, [36 * mm] * 5))

        # 1 architecture
        a = r["architecture"]
        story.append(p("1. System architecture summary", h2))
        story.append(p(f"{a['component_count']} components, {a['dependency_count']} dependencies "
                       f"({a['mandatory_dependency_count']} mandatory, {a['optional_dependency_count']} optional, "
                       f"{a['fallback_count']} with configured backup), {a['functionality_count']} user-facing "
                       f"functionalities, maximum dependency depth {a['max_depth']}. Propagation policy: "
                       f"{r['project']['propagation_policy']}."))
        story.append(Spacer(1, 4))
        story.append(table([["Component", "Type", "Criticality", "Recovery time (min)"]] +
                           [[c["name"], c["type"], c["criticality"], f"{c['recovery_minutes']:g}"]
                            for c in a["components"]], [62 * mm, 45 * mm, 30 * mm, 41 * mm]))

        # 2 scenario
        story.append(p("2. Failure scenario", h2))
        story.append(p(f"Failure type: {sim['failure_type'].replace('_', ' ').title()}; simulated duration "
                       f"{sim['duration_minutes']:g} min. {sim.get('description') or ''}"))
        story.append(Spacer(1, 4))
        story.append(table([["Component", "Failure", "Severity", "Resulting status", "Note"]] +
                           [[f["component_name"], f["failure_label"], f"{f['severity']}/10", f["resulting_status"],
                             f["description"] or "-"] for f in r["failures"]],
                           [40 * mm, 42 * mm, 18 * mm, 30 * mm, 48 * mm]))

        # 3 root cause
        rca = r["root_cause"] or {}
        story.append(p("3. Root cause", h2))
        for v in rca.get("verified_causes", []):
            story.append(p(f"<b>VERIFIED</b> – {v['explanation']}"))
        for c in rca.get("inferred_candidates", []):
            story.append(p(f"<b>INFERRED</b> – {c['name']} (coverage {c['coverage'] * 100:.0f}%): {c['explanation']}"))
        if rca.get("common_upstream_dependencies"):
            story.append(p("Common upstream dependencies of all secondary effects: " +
                           ", ".join(c["name"] for c in rca["common_upstream_dependencies"])))

        # 4 affected components
        story.append(p("4. Affected components", h2))
        rows = [["Step", "Component", "Status", "Impact", "Reason"]]
        rows += [[str(s["tick"]), s["name"], s["status"], s["impact_type"], s["reason"]] for s in r["propagation_steps"]]
        story.append(table(rows, [12 * mm, 38 * mm, 22 * mm, 22 * mm, 84 * mm]))

        # 5 impact analysis
        story.append(p("5. Impact analysis", h2))
        if imp:
            story.append(p(imp["explanation"]))
            story.append(Spacer(1, 4))
            story.append(table([["Factor", "Weight", "Value", "Contribution"]] +
                               [[f["label"], f"{f['effective_weight']:.3f}", "-" if f["value"] is None else f"{f['value']:.3f}",
                                 f"{f['contribution']:.1f}"] for f in imp["factors"]],
                               [70 * mm, 30 * mm, 30 * mm, 48 * mm]))
            story.append(Spacer(1, 4))
            story.append(table([["Functionality", "Critical", "Status", "Blocked by"]] +
                               [[f["name"], "yes" if f["is_critical"] else "no", f["status"],
                                 ", ".join(f["blocking_components"]) or "-"] for f in imp["functionalities"]],
                               [55 * mm, 18 * mm, 30 * mm, 75 * mm]))
            if imp.get("propagation_paths"):
                story.append(Spacer(1, 4))
                story.append(p("Propagation paths: " + "; ".join(" → ".join(pp["names"]) for pp in imp["propagation_paths"][:12]), small))

        # 6 recovery recommendation
        plan = r["recovery_plan"]
        story.append(p("6. Recovery recommendation", h2))
        if plan:
            story.append(p(f"Strategy: <b>{plan['strategy']['name']}</b>{' (manually modified)' if plan['is_manual'] else ''}. "
                           f"{plan['strategy']['description']} Guarantee: {plan['strategy']['guarantee']}"))
            story.append(Spacer(1, 4))
            story.append(table([["#", "Action", "Component", "Est. min", "Why"]] +
                               [[str(i + 1), x["action_label"], x["component_name"], f"{x['estimated_minutes']:g}",
                                 x["explanation"].get("why", "")] for i, x in enumerate(sorted(plan["actions"], key=lambda y: y["order_index"]))],
                               [8 * mm, 36 * mm, 36 * mm, 16 * mm, 82 * mm]))
            if r["compared_plans"]:
                story.append(Spacer(1, 4))
                story.append(table([["Strategy", "Total min", "Cost", "Functionality downtime", "Critical restored at"]] +
                                   [[c["strategy"], f"{c['estimated_minutes']:g}", f"{c['total_cost']:g}",
                                     f"{c['functionality_downtime_minutes']:g}", f"{c['critical_functionality_restored_at']:g}"]
                                    for c in r["compared_plans"]], [52 * mm, 22 * mm, 22 * mm, 42 * mm, 40 * mm]))
        else:
            story.append(p("No recovery plan has been generated for this simulation."))

        # 7 execution results
        story.append(p("7. Recovery execution results", h2))
        summary = plan.get("summary") if plan else None
        if plan and plan.get("started_at") and summary and "actions_total" in summary:
            story.append(p(f"Plan status {plan['status']}: {summary['actions_completed']}/{summary['actions_total']} actions "
                           f"completed, {summary['actions_failed']} failed, {summary['retried_actions']} retried. Estimated "
                           f"{summary['estimated_minutes']:g} min, actual simulated {summary['actual_minutes']:g} min."))
            for fa in summary.get("failed_actions", []):
                story.append(p(f"Failed: {fa['component']} – {fa['reason']}", small))
        else:
            story.append(p("Recovery has not been executed."))

        # 8 final health
        fh = r["final_health"]
        story.append(p("8. Final system health", h2))
        dist = fh.get("distribution") or {}
        story.append(p(f"Criticality-weighted health: {fh.get('weighted_health')}%. Component states: " +
                       ", ".join(f"{k.title()} {v}" for k, v in dist.items())))

        # 9 resilience
        res = r["resilience"]
        story.append(p("9. Resilience assessment", h2))
        story.append(p(f"Resilience score <b>{res.get('score')}</b> (grade {res.get('grade')})."))
        if res.get("breakdown"):
            story.append(table([["Factor", "Weight", "Value (0-100)", "Detail"]] +
                               [[b["label"], f"{b['effective_weight']:.3f}", "-" if b["value"] is None else f"{b['value']:.1f}",
                                 b["detail"]] for b in res["breakdown"]], [42 * mm, 20 * mm, 24 * mm, 92 * mm]))
        spofs = res.get("single_points_of_failure") or []
        if spofs:
            story.append(Spacer(1, 4))
            story.append(table([["Single point of failure", "Dependents", "Critical functionality lost", "Mitigation"]] +
                               [[s["name"], str(s["dependent_count"]), ", ".join(s["affected_critical_functionalities"]),
                                 s["suggested_mitigation"]] for s in spofs], [36 * mm, 20 * mm, 40 * mm, 82 * mm]))

        def footer(canvas, doc_):
            canvas.saveState()
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(16 * mm, 9 * mm, "ResQLens · simulated analysis – not a production incident record")
            canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {doc_.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return buf.getvalue()

    # -- CSV ----------------------------------------------------------------------
    def simulation_csv(self, sim_id: int) -> str:
        sim = self.ctx.simulations.get_owned(sim_id, self.ctx.user_id)
        rows = self.ctx.simulations.results(sim_id)
        plans = self.ctx.recovery.plans_for_simulation(sim_id)
        plan = next((p for p in plans if p["is_selected"]), None)
        action_by_comp = {a["component_id"]: a for a in self.ctx.recovery.actions(plan["id"])} if plan else {}
        records = []
        for r in rows:
            a = action_by_comp.get(r["component_id"], {})
            records.append({
                "simulation_id": sim_id, "simulation_name": sim["name"], "project_id": sim["project_id"],
                "component": r["component_name"], "criticality": r["criticality"], "status": r["status"],
                "impact_type": r["impact_type"], "propagation_step": r["tick"], "health": r["health"],
                "reason": r["reason"], "recovery_order": (a.get("order_index", -1) + 1) if a else None,
                "recovery_action": a.get("action_type"), "recovery_status": a.get("status"),
                "estimated_minutes": a.get("estimated_minutes"), "sim_end_minute": a.get("sim_end_minute"),
                "impact_score": sim["impact_score"], "severity_class": sim["severity_class"],
                "strategy": plan["strategy_name"] if plan else None,
            })
        return pd.DataFrame.from_records(records).to_csv(index=False)

    def history_csv(self, filters: dict) -> str:
        rows = self.ctx.simulations.search(self.ctx.user_id, **filters)
        cols = ["id", "project_id", "project_name", "name", "failure_type", "failure_sources", "status",
                "impact_score", "severity_class", "affected_count", "selected_strategy", "duration_minutes",
                "created_at", "completed_at"]
        df = pd.DataFrame.from_records([{c: r.get(c) for c in cols} for r in rows], columns=cols)
        return df.to_csv(index=False)
