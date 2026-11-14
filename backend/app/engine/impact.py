"""Failure Impact Analyzer – documented weighted scoring model.

Impact score (0-100) = 100 * sum(w_i * f_i) / sum(w_i) over the factors below.
All factors are normalised to [0, 1] and derived only from the propagation
result and configured architecture values – never from random numbers.

| Factor | Weight | Definition |
|---|---|---|
| C  Component impact      | 0.35 | sum(crit_w * status_w) over affected / sum(crit_w) over all components |
| F  Functional impact     | 0.30 | sum(func_w * func_state_w) / sum(func_w); func_w = 2 if critical else 1 |
| P  Propagation reach     | 0.15 | (direct + indirect affected) / (components - sources) |
| S  Failure severity      | 0.15 | max injected severity / 10 |
| D  Outage duration       | 0.05 | min(1, simulated duration / 240 min) |

crit_w: LOW 1, MEDIUM 2, HIGH 3, CRITICAL 4.  status_w: FAILED 1.0, BLOCKED 0.9,
DEGRADED 0.4.  func_state_w: UNAVAILABLE 1.0, DEGRADED 0.4, AVAILABLE 0.
If the architecture defines no functionalities, F is excluded and the
remaining weights are renormalised.

Severity class: score < 25 LOW, < 50 MODERATE, < 75 HIGH, otherwise CRITICAL.
Floor rule: if any *critical* functionality is unavailable the class is at
least MODERATE.
"""
from __future__ import annotations

from ..domain.enums import CRITICALITY_WEIGHT, ComponentStatus, ImpactType, SeverityClass
from ..domain.failures import FailureEvent
from ..domain.models import SystemArchitecture
from .propagation import PropagationResult, all_propagation_paths

STATUS_WEIGHT = {ComponentStatus.FAILED: 1.0, ComponentStatus.BLOCKED: 0.9, ComponentStatus.DEGRADED: 0.4,
                 ComponentStatus.RECOVERING: 0.9}
FUNC_STATE_WEIGHT = {"UNAVAILABLE": 1.0, "DEGRADED": 0.4, "AVAILABLE": 0.0}
FACTOR_WEIGHTS = {"C": 0.35, "F": 0.30, "P": 0.15, "S": 0.15, "D": 0.05}


def classify(score: float) -> SeverityClass:
    if score < 25:
        return SeverityClass.LOW
    if score < 50:
        return SeverityClass.MODERATE
    if score < 75:
        return SeverityClass.HIGH
    return SeverityClass.CRITICAL


class ImpactAnalyzer:
    def __init__(self, architecture: SystemArchitecture):
        self.arch = architecture

    def analyze(self, result: PropagationResult, failures: list[FailureEvent] | list[dict],
                duration_minutes: float, up_to_tick: int | None = None) -> dict:
        arch = self.arch
        statuses = result.statuses(up_to_tick)
        visible = {cid: o for cid, o in result.outcomes.items()
                   if o.affected and (up_to_tick is None or (o.tick is not None and o.tick <= up_to_tick))}

        sources = [o for o in visible.values() if o.impact_type == ImpactType.SOURCE]
        direct = [o for o in visible.values() if o.impact_type == ImpactType.DIRECT]
        indirect = [o for o in visible.values() if o.impact_type == ImpactType.INDIRECT]

        # --- factor C ---------------------------------------------------------
        total_crit = sum(CRITICALITY_WEIGHT[o.criticality] for o in result.outcomes.values()) or 1
        comp_impact = sum(CRITICALITY_WEIGHT[o.criticality] * STATUS_WEIGHT.get(statuses[o.component_id], 0)
                          for o in visible.values())
        f_c = comp_impact / total_crit

        # --- factor F ---------------------------------------------------------
        funcs = arch.functionality_status(statuses)
        f_weights = sum(2 if f["is_critical"] else 1 for f in funcs)
        f_f = (sum((2 if f["is_critical"] else 1) * FUNC_STATE_WEIGHT[f["status"]] for f in funcs) / f_weights
               if f_weights else None)

        # --- factor P ---------------------------------------------------------
        denom = max(1, len(result.outcomes) - len(sources))
        f_p = (len(direct) + len(indirect)) / denom

        # --- factor S / D -----------------------------------------------------
        severities = [f.severity if isinstance(f, FailureEvent) else int(f["severity"]) for f in failures]
        f_s = (max(severities) / 10) if severities else 0
        f_d = min(1.0, float(duration_minutes) / 240)

        values = {"C": f_c, "F": f_f, "P": f_p, "S": f_s, "D": f_d}
        active = {k: w for k, w in FACTOR_WEIGHTS.items() if values[k] is not None}
        wsum = sum(active.values())
        score = round(100 * sum(w * values[k] for k, w in active.items()) / wsum, 1)

        unavailable_funcs = [f for f in funcs if f["status"] == "UNAVAILABLE"]
        degraded_funcs = [f for f in funcs if f["status"] == "DEGRADED"]
        severity = classify(score)
        floor_applied = False
        if any(f["is_critical"] for f in unavailable_funcs) and severity == SeverityClass.LOW:
            severity, floor_applied = SeverityClass.MODERATE, True

        labels = {
            "C": ("Component impact", "Criticality-weighted share of components that are failed, blocked or degraded"),
            "F": ("Functional impact", "Weighted share of user-facing functionalities lost (critical counts double)"),
            "P": ("Propagation reach", "Share of non-source components reached by the cascade"),
            "S": ("Failure severity", "Highest injected failure severity on a 1-10 scale"),
            "D": ("Outage duration", "Simulated failure window relative to a 4-hour reference"),
        }
        factors = []
        for key, weight in FACTOR_WEIGHTS.items():
            v = values[key]
            factors.append({
                "key": key, "label": labels[key][0], "definition": labels[key][1],
                "weight": weight, "effective_weight": round(weight / wsum, 3) if v is not None else 0,
                "value": round(v, 3) if v is not None else None,
                "contribution": round(100 * weight * v / wsum, 1) if v is not None else 0,
                "included": v is not None,
            })

        critical_affected = [o for o in visible.values() if o.criticality in ("HIGH", "CRITICAL")]
        paths = all_propagation_paths(result)
        if up_to_tick is not None:
            paths = [[c for c in p if c in visible] for p in paths]
            paths = [p for p in paths if len(p) > 1]
            unique, seen = [], set()
            for p in paths:
                if tuple(p) not in seen:
                    seen.add(tuple(p))
                    unique.append(p)
            paths = unique
        mandatory_edges = sum(1 for e in result.propagation_edges if e["dependency_type"] == "MANDATORY")

        explanation = (
            f"Impact score {score} = "
            + " + ".join(f"{f['effective_weight']}×{f['value']}" for f in factors if f["included"])
            + f" (×100). {len(sources)} source(s), {len(direct)} direct and {len(indirect)} indirect "
              f"component(s) affected; {len(unavailable_funcs)} functionality(ies) unavailable."
            + (" Severity raised to MODERATE because a critical functionality is unavailable." if floor_applied else "")
        )

        def comp_row(o):
            return {"component_id": o.component_id, "name": o.name, "criticality": o.criticality,
                    "status": statuses[o.component_id].value, "impact_type": o.impact_type.value,
                    "depth": o.depth, "reason": o.reason, "path": [arch.name_of(c) for c in o.path],
                    "dependents": len(arch.dependents_of(o.component_id)),
                    "functionalities": [f.name for f in arch.functionalities_using(o.component_id)]}

        ordered = sorted(visible.values(), key=lambda o: (o.depth or 0, o.name))
        return {
            "impact_score": score,
            "severity_class": severity.value,
            "severity_floor_applied": floor_applied,
            "source_count": len(sources),
            "direct_count": len(direct),
            "indirect_count": len(indirect),
            "total_affected": len(visible),
            "unaffected_count": len(result.outcomes) - len(visible),
            "component_count": len(result.outcomes),
            "unavailable_functionality_count": len(unavailable_funcs),
            "degraded_functionality_count": len(degraded_funcs),
            "functionality_count": len(funcs),
            "critical_components_affected": [comp_row(o) for o in critical_affected],
            "dependency_depth": max((o.depth or 0 for o in visible.values()), default=0),
            "mandatory_propagation_edges": mandatory_edges,
            "optional_propagation_edges": len(result.propagation_edges) - mandatory_edges,
            "propagation_paths": [{"ids": p, "names": [arch.name_of(c) for c in p]} for p in paths],
            "functionalities": funcs,
            "factors": factors,
            "explanation": explanation,
            "components": [comp_row(o) for o in ordered],
            "unaffected_components": [{"component_id": o.component_id, "name": o.name, "notes": o.notes}
                                      for o in result.outcomes.values() if o.component_id not in visible],
        }
