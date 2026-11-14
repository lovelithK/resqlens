# Design patterns: where and why

All three required patterns are implemented in running code and exercised by the tests.

## 1. Observer: domain events → independent representations

**Problem.** When a component changes status during a simulation or recovery, several parts of the system must react: the persisted graph state the UI renders, the audit and timeline log, dashboard aggregates and user notifications. Services should not know about all of them.

| Role | Class | File |
|---|---|---|
| Subject | `EventBus` (`subscribe` with optional event-type filter, `unsubscribe`, `publish`) | `backend/app/engine/events.py` |
| Event | `DomainEvent`, `EventType` | `backend/app/engine/events.py` |
| Observer interface | `EventObserver.notify(event)` | `backend/app/engine/events.py` |
| Concrete observers | `ArchitectureGraphObserver`: writes component status and health, resets on `SIMULATION_RESET` | `backend/app/services/context.py` |
| | `EventLogObserver`: persists every event; timeline events are tagged `TIMELINE` | |
| | `DashboardMetricsObserver`: recomputes the project's weighted health and last activity | |
| | `NotificationObserver`: collects user-facing notifications that the API returns (shown as toasts) | |
| | `RecordingObserver`: in-memory observer used in tests | `backend/app/engine/events.py` |

**Wiring.** `ServiceContext` builds a bus per request and subscribes the observers. Subscription order guarantees that the graph state is written before aggregates are computed.

**Publishers.**
- `SimulationService` publishes FAILURE_INJECTED, DEPENDENCY_AFFECTED, FAILURE_PROPAGATED, COMPONENT_STATUS_CHANGED, PROPAGATION_COMPLETED, ROOT_CAUSE_IDENTIFIED, etc.
- `RecoveryService` publishes RECOVERY_INITIATED, COMPONENT_RESTORED, RECOVERY_ACTION_FAILED and SYSTEM_RECOVERED.
- `CommandInvoker` publishes ARCHITECTURE_CHANGED.

**Evidence.** `test_event_bus_filters_by_type` (unit) and `test_stepwise_simulation_lifecycle` (the live component state follows revealed ticks purely through the observer).

## 2. Strategy: interchangeable algorithms behind common interfaces

| Family | Interface | Concrete strategies | Selected by |
|---|---|---|---|
| Recovery prioritisation | `RecoveryStrategy` (`select`, `rationale`; shared template `build_order`) | `DependencyFirstStrategy`, `CriticalityFirstStrategy`, `MaximumFunctionalityStrategy`, `MinimumCostStrategy` | `get_strategy(key)`; the user chooses in the Recovery Planner |
| Failure-propagation policy | `PropagationPolicy` (`mandatory_loss_status`; shared `assess`/`evaluate`) | `BlockingPolicy`, `FailFastPolicy` | project setting `propagation_policy` |
| Resilience scoring | `ResilienceScoringModel` (`factors`; shared `score`) | `OperationalResilienceModel`, `DesignResilienceModel` | `?model=` on `/resilience`; toggle in the UI |

Files: `engine/recovery.py`, `engine/propagation.py`, `engine/resilience.py`.

`RecoveryPlanner.generate(strategy)` and `FailurePropagationEngine(arch, policy)` contain no strategy-specific branches, so adding a new strategy means adding one class.

**Evidence.**
- `test_every_strategy_produces_dependency_valid_plan` and `test_strategies_differ_in_ordering` (recovery strategies)
- `test_fail_fast_policy` (propagation policies)
- `test_spof_and_resilience_breakdown` (scoring models)

## 3. Command: operations as validated, logged, undoable objects

| Role | Class | File |
|---|---|---|
| Command interface | `Command` (`validate`, `execute`, `undo`, `describe`, `from_log`) | `backend/app/services/commands.py` |
| Invoker | `CommandInvoker.run(cmd)`: validate → execute → persist to `command_log` → publish event. `undo_last(project)`: rebuild the command from the log and call `undo()` | |
| Architecture commands (undoable) | `AddComponentCommand`, `UpdateComponentCommand`, `RemoveComponentCommand` (restores component, dependencies and functionality links), `ConnectComponentsCommand` (rejects duplicates and cycles), `UpdateDependencyCommand`, `DisconnectComponentsCommand` | |
| Simulation commands (logged, not undoable) | `InjectFailureCommand`, `StartSimulationCommand` (rejects duplicate execution and invalid architectures), `RestoreComponentCommand` (wraps the executor), `ResetSimulationCommand` | |

Undo data is persisted as JSON, so undo works across HTTP requests. The Architecture Builder shows the command history and an **Undo** button.

**Evidence.** `test_architecture_commands_validation_and_undo`, `test_stepwise_simulation_lifecycle` (duplicate start → `DUPLICATE_EXECUTION`) and `test_import_with_cycle_is_reported_and_blocks_simulation`.

---

## OOP principles

- **Encapsulation.** `Component` keeps `_status` and `_health` private. They change only through `transition_to`, which enforces the state machine (e.g. FAILED → HEALTHY must pass through RECOVERING) and validates health in 0–100, or through `reset_to_baseline`.
- **Abstraction.** The abstract base classes `FailureEvent`, `PropagationPolicy`, `RecoveryStrategy`, `ResilienceScoringModel`, `EventObserver` and `Command` hide their implementations behind small interfaces.
- **Inheritance (genuine is-a only).** The seven concrete failure types *are* failure events, each with its own resulting status, health formula, recovery action, time factor and applicability (e.g. `DatabaseFailure` only for databases, caches and storage). No inheritance is used merely for show: components of different types are one class with a `component_type` attribute, because they do not behave differently.
- **Polymorphism.** The engine calls `failure.resulting_status()`, `policy.evaluate()`, `strategy.select()`, `model.factors()`, `observer.notify()` and `command.execute()` without knowing the concrete class.
