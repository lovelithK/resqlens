"""Rule-based Root Cause Analysis.

Two clearly separated kinds of output:

* **VERIFIED** causes – the failure events that were actually injected into the
  simulation. They are known facts of the simulated scenario.
* **INFERRED** causes – produced *only* from observed component statuses and the
  dependency graph, as an operator would have to do without knowing the
  injection. Rules:

  R1  An unhealthy component is a *primary candidate* if none of the
      dependencies that explain its state (mandatory deps, or optional deps
      under a STRICT rule) are themselves unhealthy.
  R2  Every other unhealthy component is a *secondary effect*; it is traced
      upstream through unhealthy dependencies to the primary candidate(s).
  R3  A primary candidate's *coverage* is the share of unhealthy components
      that lie downstream of it (plus itself).
  R4  *Common upstream dependencies* are unhealthy components that lie on the
      upstream dependency closure of every secondary effect.

Symptom-based diagnosis (``diagnose``) works on a user-supplied list of
observed unavailable components without any simulation: each upstream
component is ranked by how many symptoms it explains through mandatory
dependency paths (R3), and each hypothesis is then *checked* by running the
deterministic propagation engine with that component failed and comparing
the predicted outage with the observations (Jaccard similarity).
"""
from __future__ import annotations

from ..domain.enums import AVAILABLE, ComponentStatus, OperatingRule
from ..domain.failures import CompleteServiceFailure
from ..domain.models import DomainError, SystemArchitecture
from .propagation import FailurePropagationEngine

UNHEALTHY = {ComponentStatus.FAILED, ComponentStatus.BLOCKED, ComponentStatus.DEGRADED}


class RootCauseAnalyzer:
    def __init__(self, architecture: SystemArchitecture):
        self.arch = architecture

    def _explaining_deps(self, cid: int, statuses: dict[int, ComponentStatus]) -> list[int]:
        comp = self.arch.components[cid]
        out = []
        for dep in self.arch.dependencies_of(cid):
            if statuses.get(dep.target_id) not in UNHEALTHY:
                continue
            if dep.fallback_id is not None and statuses.get(dep.fallback_id) in AVAILABLE:
                continue  # covered by configured redundancy
            if dep.is_mandatory or comp.operating_rule == OperatingRule.STRICT:
                out.append(dep.target_id)
        return out

    def _upstream_unhealthy(self, cid: int, statuses) -> set[int]:
        seen, stack = set(), [cid]
        while stack:
            cur = stack.pop()
            for t in self._explaining_deps(cur, statuses):
                if t not in seen:
                    seen.add(t)
                    stack.append(t)
        return seen

    def analyze(self, statuses: dict[int, ComponentStatus], verified: list[dict] | None = None) -> dict:
        arch = self.arch
        n = arch.name_of
        unhealthy = [cid for cid, s in statuses.items() if s in UNHEALTHY
                     and s != arch.components[cid].baseline_status]
        verified = verified or []
        verified_ids = {v["component_id"] for v in verified}

        primaries = [cid for cid in unhealthy if not self._explaining_deps(cid, statuses)]
        upstream = {cid: self._upstream_unhealthy(cid, statuses) for cid in unhealthy}

        candidates = []
        for p in primaries:
            explained = [cid for cid in unhealthy if cid == p or p in upstream[cid]]
            coverage = len(explained) / len(unhealthy) if unhealthy else 0
            dependents_unhealthy = [n(c) for c in explained if c != p]
            explanation = (
                f"{n(p)} is {statuses[p].value} while none of the dependencies it relies on are unhealthy, "
                f"so its state cannot be explained by an upstream component (rule R1). "
                + (f"It explains {len(dependents_unhealthy)} downstream symptom(s): {', '.join(dependents_unhealthy)}."
                   if dependents_unhealthy else "No other component is affected through it.")
            )
            candidates.append({
                "component_id": p, "name": n(p), "status": statuses[p].value,
                "classification": "INFERRED", "coverage": round(coverage, 3),
                "explained_components": [n(c) for c in explained],
                "matches_verified": p in verified_ids, "explanation": explanation,
            })
        candidates.sort(key=lambda c: (-c["coverage"], c["name"]))

        secondary = []
        for cid in unhealthy:
            if cid in primaries:
                continue
            roots = sorted(r for r in upstream[cid] if r in primaries)
            chain = self._chain(cid, statuses)
            secondary.append({
                "component_id": cid, "name": n(cid), "status": statuses[cid].value,
                "traced_to": [n(r) for r in roots], "trace": [n(c) for c in chain],
                "is_verified_source": cid in verified_ids,
                "explanation": (f"{n(cid)} is {statuses[cid].value} because its dependency chain "
                                f"{' -> '.join(n(c) for c in chain)} contains an unhealthy component "
                                "(secondary effect, rule R2)."),
            })
        secondary.sort(key=lambda s: (len(s["trace"]), s["name"]))

        common = []
        sec_ids = [s["component_id"] for s in secondary]
        if sec_ids:
            shared = set.intersection(*(upstream[c] for c in sec_ids))
            common = [{"component_id": c, "name": n(c), "status": statuses[c].value} for c in sorted(shared)]

        verified_out = []
        for v in verified:
            cid = v["component_id"]
            masked = cid is not None and cid not in primaries and cid in statuses and statuses[cid] in UNHEALTHY
            verified_out.append({
                **v, "classification": "VERIFIED",
                "explanation": (f"{v['failure_label']} was injected into {v['component_name']} "
                                f"(severity {v['severity']}/10). This is the simulated root failure."
                                + (" Note: its symptoms are also explained by an upstream unhealthy "
                                   "component, so status-only inference cannot isolate it." if masked else "")),
            })

        consistent = {c["component_id"] for c in candidates} == verified_ids if verified else None
        return {
            "verified_causes": verified_out,
            "inferred_candidates": candidates,
            "secondary_effects": secondary,
            "common_upstream_dependencies": common,
            "unhealthy_count": len(unhealthy),
            "inference_consistent_with_simulation": consistent,
            "method": ("Verified causes come from the simulation's injected failure events. Inferred "
                       "candidates are derived only from observed statuses and dependency rules R1-R4."),
        }

    def _chain(self, cid: int, statuses) -> list[int]:
        chain, cur, guard = [cid], cid, set([cid])
        while True:
            nxt = [t for t in self._explaining_deps(cur, statuses) if t not in guard]
            if not nxt:
                return chain
            nxt.sort(key=lambda t: -len(self._upstream_unhealthy(t, statuses)))
            cur = nxt[0]
            guard.add(cur)
            chain.append(cur)

    # ------------------------------------------------------------------
    def diagnose(self, observed_ids: list[int]) -> dict:
        arch = self.arch
        n = arch.name_of
        observed = [o for o in dict.fromkeys(observed_ids)]
        for o in observed:
            if o not in arch.components:
                raise DomainError(f"Component {o} does not belong to this project", code="NOT_FOUND")
        if not observed:
            raise DomainError("Select at least one observed symptom", code="NO_SYMPTOMS")

        closures = {o: arch.upstream_closure(o, mandatory_only=True, skip_covered=True) | {o} for o in observed}
        candidate_ids = set().union(*closures.values())
        engine = FailurePropagationEngine(arch)
        results = []
        for cand in candidate_ids:
            explains = [o for o in observed if cand in closures[o]]
            sim = engine.propagate([CompleteServiceFailure(cand, 10)])
            predicted = {cid for cid, oc in sim.outcomes.items() if oc.status not in AVAILABLE}
            obs = set(observed)
            jaccard = len(predicted & obs) / len(predicted | obs) if predicted | obs else 0
            unexplained_predicted = sorted(n(c) for c in predicted - obs)
            results.append({
                "component_id": cand, "name": n(cand), "classification": "INFERRED",
                "coverage": round(len(explains) / len(observed), 3),
                "explains": [n(o) for o in explains],
                "consistency": round(jaccard, 3),
                "predicted_unavailable": sorted(n(c) for c in predicted),
                "additional_predicted": unexplained_predicted,
                "criticality": arch.components[cand].criticality.value,
                "explanation": (
                    f"{n(cand)} lies on a mandatory dependency path of {len(explains)}/{len(observed)} observed "
                    f"symptom(s). A deterministic what-if failure of {n(cand)} predicts "
                    f"{len(predicted)} unavailable component(s); overlap with the observations "
                    f"(Jaccard) = {jaccard:.2f}."
                    + (f" It would additionally take down: {', '.join(unexplained_predicted)}."
                       if unexplained_predicted else "")),
            })
        results.sort(key=lambda r: (-r["coverage"], -r["consistency"], r["name"]))
        full = [r["component_id"] for r in results if r["coverage"] == 1.0]
        common = [n(c) for c in full]
        # deepest common upstream: explains everything and has no fully-explaining dependency of its own
        deepest = [c for c in full if not (arch.upstream_closure(c, mandatory_only=True, skip_covered=True) & set(full))]
        for r in results:
            r["is_deepest_common_dependency"] = r["component_id"] in deepest
        hint = None
        if len(full) > 1:
            hint = (f"{len(full)} components explain every symptom ({', '.join(common)}). The deepest shared "
                    f"dependency is {', '.join(n(c) for c in deepest)}; checking its health discriminates "
                    "between these hypotheses.")
        return {
            "observed": [n(o) for o in observed],
            "candidates": results[:10],
            "common_upstream_dependencies": common,
            "deepest_common_dependencies": [n(c) for c in deepest],
            "discrimination_hint": hint,
            "note": ("These are INFERRED potential causes ranked by coverage and simulated consistency. They "
                     "are hypotheses about the modelled architecture, not verified incident causes."),
        }
