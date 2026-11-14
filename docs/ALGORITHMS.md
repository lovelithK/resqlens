# Algorithms

All analysis in ResQLens is deterministic and rule-based. Source files are referenced for each algorithm.

Terminology: an edge **A → B** means *A depends on B*. Failures travel **against** edge direction, from a dependency to its dependents.

---

## 1. Directed-graph processing & validation (`engine/dependency_manager.py`)

| Task | Algorithm |
|---|---|
| Cycle detection (validation) | `networkx.simple_cycles` (Johnson's algorithm), reported as `CIRCULAR_DEPENDENCY` errors |
| Cycle prevention (new edge A → B) | rejected if B can already reach A (`nx.has_path`); the API responds 409 with the would-be cycle |
| Other validation | missing component reference, duplicate connection, self dependency (also a DB `CHECK`), backup equal to source or target, a backup that itself depends on the primary (no real redundancy), isolated components, functionalities without components |
| Layering / depth | longest path to a sink on the DAG (cycles are condensed first, so it also works on invalid graphs) |

A simulation cannot start on an invalid architecture. Cycles can only enter through a JSON import, and validation reports them.

## 2. Failure propagation (`engine/propagation.py`)

**Inputs:** the architecture (components, dependencies, configured backups), the injected `FailureEvent`s and the `PropagationPolicy`.

1. **Source application.** Each failure class defines the resulting status and health (e.g. `ApiTimeout` → FAILED if severity ≥ 5, else DEGRADED). When a component is hit more than once, the most severe result wins.
2. **Candidate discovery (BFS).** A breadth-first search from all sources over *reverse* edges collects every component that could be influenced. Dependents of a backup are included, because losing the backup can remove a failover. A `visited` set guarantees termination on cyclic graphs.
3. **Joint evaluation (monotone fixed point).** Each candidate is evaluated against **all** of its dependencies at once:

   | Situation | Result |
   |---|---|
   | a mandatory dependency is unavailable (FAILED/BLOCKED) and no configured backup is available | `BLOCKED` (Blocking policy) or `FAILED` (Fail-fast policy) |
   | an optional dependency is unavailable | `STRICT` rule → DEGRADED; otherwise operational (noted) |
   | a mandatory dependency is DEGRADED | DEGRADED unless the rule is `TOLERANT` |
   | an optional dependency is DEGRADED | DEGRADED only under `STRICT` |
   | target unavailable but its configured backup is available | dependency satisfied (failover noted) |

   Statuses only escalate (HEALTHY < DEGRADED < BLOCKED < FAILED) and the evaluation is monotone, so iterating to a fixed point terminates within |V| rounds, including on cyclic graphs.
4. **Chronology (second BFS).** Starting at the sources and walking only through *affected* components along edges that actually caused the effect, it assigns each affected component:
   - its **depth/tick** (0 = source, 1 = **direct**, ≥2 = **indirect**),
   - its causes,
   - the propagation edges,
   - a shortest propagation path.

   The UI reveals one tick per step, which gives the chronological propagation display.

Complexity: O(V + E) per BFS and O(V·(V+E)) worst case for the fixed point, which is trivial for architecture-sized graphs.

`all_propagation_paths` enumerates every source → leaf path through the propagation edges (capped at 60).

## 3. Impact score (`engine/impact.py`)

Impact = 100 × Σ wᵢ·fᵢ / Σ wᵢ, where every factor fᵢ ∈ [0, 1]:

| Factor | w | Definition |
|---|---|---|
| C – component impact | 0.35 | Σ(crit_w × status_w) over affected ÷ Σ crit_w over all components |
| F – functional impact | 0.30 | Σ(func_w × state_w) ÷ Σ func_w (func_w = 2 if critical, else 1) |
| P – propagation reach | 0.15 | (direct + indirect) ÷ (components − sources) |
| S – failure severity | 0.15 | max injected severity ÷ 10 |
| D – outage duration | 0.05 | min(1, duration ÷ 240 min) |

- crit_w: LOW 1, MEDIUM 2, HIGH 3, CRITICAL 4
- status_w: FAILED 1.0, BLOCKED 0.9, DEGRADED 0.4
- state_w: UNAVAILABLE 1.0, DEGRADED 0.4, AVAILABLE 0

If the architecture has no functionalities, F is excluded and the other weights are renormalised. Classification: **< 25 LOW, < 50 MODERATE, < 75 HIGH, ≥ 75 CRITICAL**. Floor rule: if a critical functionality is unavailable, the class is at least MODERATE.

Mandatory vs optional dependencies enter through the propagation rules (optional losses usually do not make components unavailable), and the counts of mandatory and optional propagation edges are reported.

Worked example (Scenario 1): C = 0.339, F = 0.556, P = 0.214, S = 0.8, D = 0.1875 → 0.35·0.339 + 0.30·0.556 + 0.15·0.214 + 0.15·0.8 + 0.05·0.1875 = 0.447 → **44.7, MODERATE**.

## 4. Root cause analysis (`engine/root_cause.py`)

- **VERIFIED** causes are the injected failure events: facts of the simulated scenario.
- **INFERRED** candidates use only observed statuses and the graph:
  - **R1.** An unhealthy component is a *primary candidate* if none of its explaining dependencies are unhealthy. Explaining dependencies are mandatory ones, or optional ones under the STRICT rule; dependencies covered by an available backup are ignored.
  - **R2.** Every other unhealthy component is a *secondary effect*, traced upstream to the primary candidate(s) along a dependency chain.
  - **R3.** Coverage = the share of unhealthy components lying downstream of a candidate.
  - **R4.** Common upstream dependencies are the unhealthy components shared by the upstream closure of every secondary effect.

  The result reports whether inference is consistent with the verified causes. When a source is masked by an upstream source, the report says so explicitly.
- **Symptom diagnosis (no simulation).** For a set of observed unavailable components, every component on a mandatory dependency path is scored by coverage. Each hypothesis is then **checked** by propagating a severity-10 complete failure of that component and comparing the predicted outage with the observations (Jaccard similarity = *consistency*). When several candidates explain every symptom, the *deepest common dependency* is highlighted together with a hint on how to discriminate between them.

## 5. Recovery planning (`engine/recovery.py`)

**Action derivation.** One action per component that is worse than its baseline:

| Component | Action | Duration / cost factor |
|---|---|---|
| injected source | the failure class's action (Restore Database, Restore Network, Clear Resource Exhaustion, Restore Service Configuration, Restart Service) | failure-specific, e.g. 0.5 + severity/10 |
| BLOCKED | Reconnect Dependency | 0.3 |
| FAILED (fail-fast) | Restart Service | 1.0 |
| DEGRADED | Validate Service Health | 0.15 |

Duration = configured recovery minutes × factor (minimum 1 min); cost = configured cost × factor.

**Prerequisites.** These are the affected targets of the component's mandatory dependencies (plus optional ones under STRICT). A dependency whose configured backup is healthy is not a prerequisite.

**Scheduling (Strategy pattern).** Every strategy runs the same **Kahn topological list scheduler**: an action is *ready* only when its prerequisites are done. Strategies only choose among ready actions, so every plan is dependency-valid.

| Strategy | Selection rule among ready actions | Guarantee |
|---|---|---|
| A Dependency-First | lowest propagation depth (most upstream), then most dependents, then criticality | valid topological order; no optimisation claim |
| B Criticality-First | highest *effective* criticality (priority inheritance from waiting dependents), then own criticality, recovery priority, dependents | greedy heuristic |
| C Maximum Functionality | greatest immediate weighted functionality gain (critical = 2); tie: largest still-blocked functionality it unblocks; then shortest | greedy heuristic, not globally optimal |
| D Minimum Cost | lowest configured cost, then shortest time (SPT rule) | SPT is optimal for mean completion only without precedence constraints; here it is a heuristic |

**Comparison metrics.** Execution is sequential, so total time and cost are equal for all complete plans. Strategies are compared on:
- functionality downtime (Σ restore minute over affected functionalities),
- critical-functionality restore time,
- weighted component downtime,
- mean component restore minute.

**Manual sequences** are validated (`PREREQUISITE_ORDER`, `MISSING_ACTION`, `DUPLICATE_ACTION`, `UNKNOWN_ACTION`). An invalid order is rejected unless explicitly allowed, in which case execution-time validation decides.

**Explanations** for every action are generated from rules: *what, why, influencing dependencies (with their step numbers), consequences if skipped (downstream components and functionalities), expected benefit (functionality restored, components unblocked), and the strategy's order rationale.*

## 6. Recovery execution (`engine/execution.py`, `services/recovery.py`)

For each step:
1. The component transitions to RECOVERING (the state machine is enforced).
2. The dependency check re-evaluates the component with the propagation policy against **live** states.
3. If successful → baseline status and health, taking the estimated duration. If not → previous status, taking 25 % of the duration (minimum 0.5 min) as diagnosis time, and the action is **re-queued once** at the end of the plan. A second failure is permanent.
4. When nothing is pending, a summary is produced (health before and after, functionality availability, still-unhealthy components). The plan becomes COMPLETED or COMPLETED_WITH_FAILURES, and the simulation RECOVERED or PARTIALLY_RECOVERED. A partially recovered simulation can receive a follow-up plan covering only the remaining components.

## 7. Single points of failure & resilience score (`engine/resilience.py`)

**SPOF.** For each component, a what-if complete failure (severity 10) is propagated. The component is a SPOF if a *critical* functionality becomes unavailable. Blast radius is the share of other components affected. Mitigations are type-specific and name the uncovered mandatory dependents.

**Resilience score.** `OPERATIONAL` model:

| Factor | Weight | 0–100 value |
|---|---|---|
| SPOF exposure | 0.25 | 100 × (1 − SPOFs / components) |
| Blast-radius containment | 0.25 | 100 × (1 − mean blast radius) |
| Redundancy coverage | 0.15 | 100 × mandatory deps with a backup / mandatory deps |
| Current health | 0.15 | criticality-weighted mean of live component health |
| Recovery efficiency | 0.20 | 100 × success rate × min(1, estimated / actual) of the latest executed plan |

Factors without data are excluded and the weights renormalised. The `DESIGN` model uses only the three structural factors (0.4 / 0.4 / 0.2). Grade: A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40, F below.

## 8. Auto-layout (`frontend/src/lib/layout.ts`)

A simplified Sugiyama layout:
1. longest-path layering,
2. components without dependencies are lifted to sit directly below their lowest dependent,
3. six barycenter sweeps to reduce crossings,
4. even spacing.

Configured backups are treated as edges so replicas sit next to their primaries.
