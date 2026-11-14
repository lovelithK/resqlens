"""Dependency Manager: graph validation, cycle detection and structural queries.

Algorithms
----------
* Cycle detection   – ``networkx.simple_cycles`` (Johnson's algorithm) on the
  directed dependency graph; reported during architecture validation.
* Cycle prevention  – before a new edge A->B is stored we check whether B can
  already reach A (``nx.has_path``); if so the edge would close a cycle.
* Layering          – longest-path layering on the DAG (used for auto-layout and
  "dependency depth").
"""
from __future__ import annotations

import networkx as nx

from ..domain.models import SystemArchitecture


class DependencyManager:
    def __init__(self, architecture: SystemArchitecture):
        self.arch = architecture

    # -- cycles ----------------------------------------------------------------
    def find_cycles(self, limit: int = 20) -> list[list[int]]:
        cycles: list[list[int]] = []
        for cycle in nx.simple_cycles(self.arch.graph):
            cycles.append(cycle)
            if len(cycles) >= limit:
                break
        return cycles

    def would_create_cycle(self, source_id: int, target_id: int) -> list[int] | None:
        """Return the cycle path if adding ``source -> target`` would create one."""
        g = self.arch.graph
        if source_id == target_id:
            return [source_id, source_id]
        if target_id in g and source_id in g and nx.has_path(g, target_id, source_id):
            path = nx.shortest_path(g, target_id, source_id)
            return [source_id, *path]
        return None

    # -- validation ------------------------------------------------------------
    def validate(self) -> dict:
        arch = self.arch
        issues: list[dict] = []
        name = arch.name_of

        for cycle in self.find_cycles():
            names = [name(c) for c in cycle] + [name(cycle[0])]
            issues.append({"level": "ERROR", "code": "CIRCULAR_DEPENDENCY",
                           "message": "Circular dependency: " + " -> ".join(names),
                           "component_ids": cycle})

        seen_pairs: set[tuple[int, int]] = set()
        for dep in arch.dependencies:
            if dep.source_id not in arch.components or dep.target_id not in arch.components:
                issues.append({"level": "ERROR", "code": "MISSING_DEPENDENCY",
                               "message": f"Dependency #{dep.id} references a component that does not exist",
                               "component_ids": [dep.source_id, dep.target_id]})
                continue
            pair = (dep.source_id, dep.target_id)
            if pair in seen_pairs:
                issues.append({"level": "ERROR", "code": "DUPLICATE_CONNECTION",
                               "message": f"Duplicate connection {name(dep.source_id)} -> {name(dep.target_id)}",
                               "component_ids": list(pair)})
            seen_pairs.add(pair)
            if dep.fallback_id is not None:
                if dep.fallback_id not in arch.components:
                    issues.append({"level": "ERROR", "code": "MISSING_FALLBACK",
                                   "message": f"Fallback of {name(dep.source_id)} -> {name(dep.target_id)} does not exist",
                                   "component_ids": list(pair)})
                elif dep.fallback_id in (dep.source_id, dep.target_id):
                    issues.append({"level": "ERROR", "code": "INVALID_FALLBACK",
                                   "message": f"Fallback for {name(dep.source_id)} -> {name(dep.target_id)} "
                                              "must be a different component",
                                   "component_ids": list(pair)})
                elif dep.target_id in arch.upstream_closure(dep.fallback_id, mandatory_only=True):
                    issues.append({"level": "WARNING", "code": "FALLBACK_SHARES_FAILURE_DOMAIN",
                                   "message": f"Backup {name(dep.fallback_id)} itself depends on "
                                              f"{name(dep.target_id)}, so it cannot cover that failure",
                                   "component_ids": [dep.fallback_id, dep.target_id]})

        for cid, comp in arch.components.items():
            if not arch.dependencies_of(cid) and not arch.dependents_of(cid) and len(arch.components) > 1:
                issues.append({"level": "INFO", "code": "ISOLATED_COMPONENT",
                               "message": f"{comp.name} has no connections (independent component)",
                               "component_ids": [cid]})

        for func in arch.functionalities:
            if not func.component_ids:
                issues.append({"level": "WARNING", "code": "EMPTY_FUNCTIONALITY",
                               "message": f"Functionality '{func.name}' is not mapped to any component",
                               "component_ids": []})

        errors = [i for i in issues if i["level"] == "ERROR"]
        return {"valid": not errors, "error_count": len(errors),
                "warning_count": sum(1 for i in issues if i["level"] == "WARNING"),
                "issues": issues}

    # -- structure ---------------------------------------------------------------
    def layers(self) -> dict[int, int]:
        """Longest-path layer per component (0 = no dependencies / bottom)."""
        g = self.arch.graph
        if not nx.is_directed_acyclic_graph(g):
            # Condense cycles so layering still works on invalid graphs.
            cond = nx.condensation(g)
            layer_c: dict[int, int] = {}
            for node in reversed(list(nx.topological_sort(cond))):
                succ = list(cond.successors(node))
                layer_c[node] = 0 if not succ else 1 + max(layer_c[s] for s in succ)
            return {n: layer_c[cond.graph["mapping"][n]] for n in g.nodes}
        layer: dict[int, int] = {}
        for node in reversed(list(nx.topological_sort(g))):
            succ = list(g.successors(node))
            layer[node] = 0 if not succ else 1 + max(layer[s] for s in succ)
        return layer

    def stats(self) -> dict:
        arch = self.arch
        mandatory = sum(1 for d in arch.dependencies if d.is_mandatory)
        with_fallback = sum(1 for d in arch.dependencies if d.fallback_id is not None)
        critical_deps = sum(1 for d in arch.dependencies if d.is_mandatory and d.target_id in arch.components
                            and arch.components[d.target_id].criticality.value in ("HIGH", "CRITICAL"))
        layers = self.layers() if arch.components else {}
        return {
            "component_count": len(arch.components),
            "dependency_count": len(arch.dependencies),
            "mandatory_dependency_count": mandatory,
            "optional_dependency_count": len(arch.dependencies) - mandatory,
            "fallback_count": with_fallback,
            "critical_dependency_count": critical_deps,
            "max_depth": max(layers.values()) if layers else 0,
            "functionality_count": len(arch.functionalities),
        }
