# REST API reference

Base path `/api`. JSON in and out. All endpoints except `register`, `login` and `health` require `Authorization: Bearer <token>`. Errors have the shape:

```json
{ "error": { "code": "CIRCULAR_DEPENDENCY", "message": "Connection rejected: …", "details": { "cycle": [3, 1, 2, 3] } } }
```

Status codes:

| Code | Meaning |
|---|---|
| 400 | bad JSON or request |
| 401 | not authenticated or session revoked |
| 404 | not found **or not owned** |
| 409 | conflict: duplicate, cycle, active simulation, duplicate execution |
| 422 | validation error, including invalid architecture or invalid recovery sequence |

## Authentication
| Method | Path | Body / notes |
|---|---|---|
| POST | `/auth/register` | `{email, full_name, password, include_demo_project}` → `{token, user}` (201) |
| POST | `/auth/login` | `{email, password}` → `{token, expires_at, user}` |
| POST | `/auth/logout` | revokes the session |
| GET / PUT | `/auth/me` | profile / `{full_name}` |
| POST | `/auth/change-password` | `{current_password, new_password}` |

## Meta & dashboard
`GET /health` · `GET /catalog` (component types, failure types, policies, rules, strategies) · `GET /dashboard` · `GET /activity?project_id=&limit=`

## Projects & architecture
| Method | Path | Notes |
|---|---|---|
| GET / POST | `/projects` | list (with counts) / create `{name, description, propagation_policy}` |
| POST | `/projects/import` | `{data: <export JSON>, name?}` |
| GET / PUT / DELETE | `/projects/{id}` | full architecture / update / delete |
| GET | `/projects/{id}/architecture` | components (+layer, dependents, functionalities), dependencies, functionalities, validation, stats, active simulation, `can_undo` |
| POST | `/projects/{id}/validate` | validation report |
| PUT | `/projects/{id}/layout` | `{positions:[{id,x,y}]}` |
| POST | `/projects/{id}/undo` | undo the last architecture command |
| GET | `/projects/{id}/commands` | command history |
| GET | `/projects/{id}/export` | portable architecture JSON |

## Components, dependencies, functionalities, scenarios
| Method | Path |
|---|---|
| GET / POST | `/projects/{id}/components` |
| GET / PUT / DELETE | `/components/{id}` |
| POST | `/dependencies`: `{project_id, source_id, target_id, dependency_type, fallback_id?}` (source depends on target) |
| PUT / DELETE | `/dependencies/{id}`: `{dependency_type?, fallback_component_id?, clear_fallback?}` |
| GET / POST | `/projects/{id}/functionalities` |
| PUT / DELETE | `/functionalities/{id}` |
| GET / POST | `/projects/{id}/scenarios` · DELETE `/scenarios/{id}` |

## Simulation
| Method | Path | Notes |
|---|---|---|
| GET | `/simulations?project_id=&severity=&status=&date_from=&date_to=` | history |
| GET | `/simulations/export.csv?…` | history CSV |
| GET | `/simulations/compare?ids=1,2,3` | 2–6 simulations side by side |
| POST | `/simulations` | `{project_id, name?, description, duration_minutes, failures:[{component_id, failure_type, severity, description}]}` |
| GET / DELETE | `/simulations/{id}` | detail (results, revealed steps, plans, notifications) / delete when inactive |
| POST | `/simulations/{id}/start` | `{instant?}` – 409 `DUPLICATE_EXECUTION` / `SIMULATION_ACTIVE`, 422 `INVALID_ARCHITECTURE` |
| POST | `/simulations/{id}/tick` · `/pause` · `/resume` · `/stop` · `/reset` | lifecycle |
| GET | `/simulations/{id}/timeline` | chronological timeline events |

## Analysis
| Method | Path |
|---|---|
| GET | `/simulations/{id}/impact` |
| GET | `/simulations/{id}/root-cause` |
| GET | `/simulations/{id}/single-points-of-failure` · `/projects/{id}/single-points-of-failure` |
| POST | `/projects/{id}/diagnose`: `{observed_component_ids:[…]}` |
| POST | `/projects/{id}/what-if`: `{scenarios:[{name, duration_minutes, failures:[…]}]}` (dry run, nothing stored) |
| GET | `/projects/{id}/resilience?model=OPERATIONAL\|DESIGN` · `/projects/{id}/resilience/history` |

## Recovery
| Method | Path | Notes |
|---|---|---|
| GET | `/recovery-strategies` | |
| GET / POST | `/simulations/{id}/recovery-plans` | list / generate `{strategies?: [...]}` (all four by default) |
| GET | `/recovery-plans/{id}` | plan with actions and explanations |
| POST | `/recovery-plans/{id}/select` | choose a strategy |
| PUT | `/recovery-plans/{id}/sequence` | `{component_order:[…], allow_invalid?}` – 422 `INVALID_RECOVERY_SEQUENCE` with violations |
| POST | `/recovery-plans/{id}/execute` | `{run_to_completion?}` – 409 `DUPLICATE_EXECUTION` |
| POST | `/recovery-plans/{id}/step` · `/pause` · `/resume` | step-wise execution |

## Reports
`GET /simulations/{id}/report` (JSON, 9 sections + timeline) · `GET /simulations/{id}/report.pdf` · `GET /simulations/{id}/export` (CSV)

The endpoint list follows the structure proposed in the brief. Additions (tick, stop, select, sequence, step, resume, diagnose, what-if, compare, import/export, undo) were needed for a coherent API.
