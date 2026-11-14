"""Single-point-of-failure detection and the transparent resilience score.

SPOF rule
---------
For every component a deterministic what-if *Complete Service Failure*
(severity 10) is propagated through the baseline architecture. A component is
a **single point of failure** if that single failure makes at least one
*critical* functionality unavailable. Its *blast radius* is the share of other
components that become failed, blocked or degraded.

Resilience score (Strategy pattern: ``ResilienceScoringModel``)
---------------------------------------------------------------
``OPERATIONAL`` (default) – weighted mean of five 0-100 factors:

| Factor | Weight | Definition |
|---|---|---|
| SPOF exposure        | 0.25 | 100 x (1 - SPOFs / components) |
| Blast-radius containment | 0.25 | 100 x (1 - mean blast radius of single failures) |
| Redundancy coverage  | 0.15 | 100 x mandatory deps with a configured backup / mandatory deps |
| Current health       | 0.15 | criticality-weighted mean of live component health |
| Recovery efficiency  | 0.20 | 100 x success rate x min(1, estimated / actual simulated time) of the latest executed plan |

A factor without data (e.g. no recovery executed yet) is excluded and the
remaining weights are renormalised. ``DESIGN`` uses only the three structural
factors. Grade: A >= 85, B >= 70, C >= 55, D >= 40, otherwise F.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.enums import AVAILABLE, CRITICALITY_WEIGHT, ComponentStatus, ComponentType
from ..domain.failures import CompleteServiceFailure
from ..domain.models import DomainError, SystemArchitecture
from .propagation import FailurePropagationEngine

MITIGATIONS = {
    ComponentType.DATABASE: "Add a standby/read replica and configure it as the backup on dependents' mandatory dependency; schedule automated backups.",
    ComponentType.API_GATEWAY: "Run at least two gateway instances behind a load balancer and configure a secondary gateway as backup.",
    ComponentType.AUTH: "Deploy redundant authentication instances; allow services to verify signed tokens locally to ride out short outages.",
    ComponentType.CACHE: "Treat the cache as OPTIONAL with read-through fallback to the primary data store.",
    ComponentType.MESSAGE_QUEUE: "Use a clustered broker and make producers tolerate queue loss (outbox pattern / optional dependency).",
    ComponentType.EXTERNAL_API: "Wrap the provider in a circuit breaker, make the dependency OPTIONAL and configure a secondary provider.",
    ComponentType.STORAGE: "Replicate storage across zones and configure a secondary bucket/volume as backup.",
    ComponentType.FRONTEND: "Serve the frontend from multiple instances or a CDN with a static fallback page.",
    ComponentType.BACKEND: "Scale horizontally (>= 2 instances with health-checked failover) and review whether dependents can treat it as OPTIONAL.",
    ComponentType.CUSTOM: "Add redundancy (>= 2 instances) and configure a backup component on its mandatory incoming dependencies.",
}


class SPOFDetector:
    def __init__(self, architecture: SystemArchitecture):
        self.arch = architecture

    def analyze(self) -> list[dict]:
        arch = self.arch
        engine = FailurePropagationEngine(arch)
        n_other = max(1, len(arch.components) - 1)
        rows = []
        for cid, comp in arch.components.items():
            result = engine.propagate([CompleteServiceFailure(cid, 10)])
            statuses = result.statuses()
            affected = [o for o in result.outcomes.values() if o.affected and o.component_id != cid]
            funcs = arch.functionality_status(statuses)
            lost = [f for f in funcs if f["status"] == "UNAVAILABLE"]
            lost_critical = [f for f in lost if f["is_critical"]]
            mandatory_in = [d for d in arch.dependents_of(cid) if d.is_mandatory]
            covered = [d for d in mandatory_in if d.fallback_id is not None]
            mitigation = MITIGATIONS[comp.component_type]
            if mandatory_in and len(covered) < len(mandatory_in):
                names = ", ".join(sorted(arch.name_of(d.source_id) for d in mandatory_in if d.fallback_id is None))
                mitigation += f" Uncovered mandatory dependents: {names}."
            rows.append({
                "component_id": cid, "name": comp.name, "component_type": comp.component_type.value,
                "criticality": comp.criticality.value,
                "is_spof": bool(lost_critical),
                "dependent_count": len(arch.downstream_closure(cid)),
                "direct_dependents": len(arch.dependents_of(cid)),
                "affected_count": len(affected),
                "blast_radius": round(len(affected) / n_other, 3),
                "affected_functionalities": [f["name"] for f in lost],
                "affected_critical_functionalities": [f["name"] for f in lost_critical],
                "fallback_coverage": f"{len(covered)}/{len(mandatory_in)}",
                "suggested_mitigation": mitigation,
            })
        rows.sort(key=lambda r: (not r["is_spof"], -len(r["affected_critical_functionalities"]),
                                 -r["affected_count"], r["name"]))
        return rows


def grade(score: float) -> str:
    return "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "F"


class ResilienceScoringModel(ABC):
    key: str
    name: str
    weights: dict[str, float]

    def score(self, arch: SystemArchitecture, spof_rows: list[dict], recovery_stats: dict | None) -> dict:
        factors = self.factors(arch, spof_rows, recovery_stats)
        active = {k: self.weights[k] for k, f in factors.items() if f["value"] is not None and k in self.weights}
        wsum = sum(active.values()) or 1
        total = round(sum(active[k] * factors[k]["value"] for k in active) / wsum, 1)
        breakdown = []
        for k, w in self.weights.items():
            f = factors[k]
            included = k in active
            breakdown.append({**f, "key": k, "weight": w,
                              "effective_weight": round(w / wsum, 3) if included else 0,
                              "contribution": round(w * f["value"] / wsum, 1) if included else 0,
                              "included": included})
        return {"model": self.key, "model_name": self.name, "score": total, "grade": grade(total),
                "breakdown": breakdown,
                "formula": "score = Σ(effective_weight × factor) where effective weights are renormalised over "
                           "factors that have data"}

    @abstractmethod
    def factors(self, arch, spof_rows, recovery_stats) -> dict[str, dict]:
        ...


def _structural_factors(arch: SystemArchitecture, spof_rows: list[dict]) -> dict[str, dict]:
    n = len(arch.components)
    spofs = [r for r in spof_rows if r["is_spof"]]
    mandatory = [d for d in arch.dependencies if d.is_mandatory]
    covered = [d for d in mandatory if d.fallback_id is not None]
    mean_blast = sum(r["blast_radius"] for r in spof_rows) / len(spof_rows) if spof_rows else 0
    return {
        "spof": {"label": "SPOF exposure", "value": round(100 * (1 - len(spofs) / n), 1) if n else None,
                 "detail": f"{len(spofs)} of {n} components are single points of failure"},
        "blast": {"label": "Blast-radius containment", "value": round(100 * (1 - mean_blast), 1) if n else None,
                  "detail": f"A single failure affects {mean_blast * 100:.1f}% of other components on average"},
        "redundancy": {"label": "Redundancy coverage",
                       "value": round(100 * len(covered) / len(mandatory), 1) if mandatory else (100.0 if n else None),
                       "detail": f"{len(covered)} of {len(mandatory)} mandatory dependencies have a configured backup"},
    }


class OperationalResilienceModel(ResilienceScoringModel):
    key = "OPERATIONAL"
    name = "Operational resilience (structure + live state + recovery)"
    weights = {"spof": 0.25, "blast": 0.25, "redundancy": 0.15, "health": 0.15, "recovery": 0.20}

    def factors(self, arch, spof_rows, recovery_stats):
        f = _structural_factors(arch, spof_rows)
        total_w = sum(c.criticality_weight for c in arch.components.values())
        health = (sum(c.criticality_weight * c.health for c in arch.components.values()) / total_w) if total_w else None
        f["health"] = {"label": "Current health", "value": round(health, 1) if health is not None else None,
                       "detail": "Criticality-weighted mean health of the live (simulated) component states"}
        if recovery_stats and recovery_stats.get("actual_minutes"):
            rate = recovery_stats["successful"] / max(1, recovery_stats["attempted"])
            eff = min(1.0, recovery_stats["estimated_minutes"] / recovery_stats["actual_minutes"])
            value = round(100 * rate * eff, 1)
            detail = (f"Latest plan: {recovery_stats['successful']}/{recovery_stats['attempted']} actions succeeded; "
                      f"estimated {recovery_stats['estimated_minutes']:g} min vs actual {recovery_stats['actual_minutes']:g} min")
        else:
            value, detail = None, "No recovery has been executed yet – factor excluded"
        f["recovery"] = {"label": "Recovery efficiency", "value": value, "detail": detail}
        return f


class DesignResilienceModel(ResilienceScoringModel):
    key = "DESIGN"
    name = "Design-time resilience (structure only)"
    weights = {"spof": 0.40, "blast": 0.40, "redundancy": 0.20}

    def factors(self, arch, spof_rows, recovery_stats):
        return _structural_factors(arch, spof_rows)


SCORING_MODELS = {m.key: m for m in (OperationalResilienceModel, DesignResilienceModel)}


def get_scoring_model(key: str) -> ResilienceScoringModel:
    try:
        return SCORING_MODELS[key]()
    except KeyError:
        raise DomainError(f"Unknown scoring model '{key}'", code="INVALID_MODEL")


def health_distribution(arch: SystemArchitecture) -> dict:
    dist = {s.value: 0 for s in ComponentStatus}
    for c in arch.components.values():
        dist[c.status.value] += 1
    return dist


def weighted_health(arch: SystemArchitecture) -> float:
    total = sum(CRITICALITY_WEIGHT[c.criticality.value] for c in arch.components.values())
    if not total:
        return 100.0
    return round(sum(CRITICALITY_WEIGHT[c.criticality.value] * c.health for c in arch.components.values()) / total, 1)


def available(status: ComponentStatus) -> bool:
    return status in AVAILABLE
