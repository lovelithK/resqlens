-- ResQLens relational schema.
-- Written for SQLite but kept PostgreSQL-compatible in structure:
--   * INTEGER PRIMARY KEY AUTOINCREMENT  ->  BIGSERIAL PRIMARY KEY (PostgreSQL)
--   * TEXT timestamps (ISO-8601 UTC)     ->  TIMESTAMPTZ
--   * INTEGER booleans (0/1)             ->  BOOLEAN
--   * TEXT JSON columns                  ->  JSONB
-- All foreign keys, unique constraints, checks and indexes map 1:1.

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    jti             TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON user_sessions(user_id);

CREATE TABLE IF NOT EXISTS projects (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    propagation_policy  TEXT NOT NULL DEFAULT 'BLOCKING'
                        CHECK (propagation_policy IN ('BLOCKING','FAIL_FAST')),
    current_health      REAL NOT NULL DEFAULT 100,
    last_activity_at    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (owner_id, name)
);
CREATE INDEX IF NOT EXISTS ix_projects_owner ON projects(owner_id);

CREATE TABLE IF NOT EXISTS system_components (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id                  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                        TEXT NOT NULL,
    component_type              TEXT NOT NULL,
    description                 TEXT NOT NULL DEFAULT '',
    status                      TEXT NOT NULL DEFAULT 'HEALTHY',
    health                      REAL NOT NULL DEFAULT 100 CHECK (health >= 0 AND health <= 100),
    baseline_status             TEXT NOT NULL DEFAULT 'HEALTHY',
    baseline_health             REAL NOT NULL DEFAULT 100 CHECK (baseline_health >= 0 AND baseline_health <= 100),
    criticality                 TEXT NOT NULL DEFAULT 'MEDIUM',
    recovery_priority           INTEGER NOT NULL DEFAULT 3 CHECK (recovery_priority BETWEEN 1 AND 5),
    estimated_recovery_minutes  REAL NOT NULL DEFAULT 10 CHECK (estimated_recovery_minutes > 0),
    recovery_cost               REAL NOT NULL DEFAULT 10 CHECK (recovery_cost >= 0),
    operating_rule              TEXT NOT NULL DEFAULT 'STANDARD',
    pos_x                       REAL,
    pos_y                       REAL,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    UNIQUE (project_id, name)
);
CREATE INDEX IF NOT EXISTS ix_components_project ON system_components(project_id);

-- source_component_id DEPENDS ON target_component_id
CREATE TABLE IF NOT EXISTS dependencies (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id              INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_component_id     INTEGER NOT NULL REFERENCES system_components(id) ON DELETE CASCADE,
    target_component_id     INTEGER NOT NULL REFERENCES system_components(id) ON DELETE CASCADE,
    dependency_type         TEXT NOT NULL DEFAULT 'MANDATORY'
                            CHECK (dependency_type IN ('MANDATORY','OPTIONAL')),
    fallback_component_id   INTEGER REFERENCES system_components(id) ON DELETE SET NULL,
    description             TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL,
    UNIQUE (source_component_id, target_component_id),
    CHECK (source_component_id <> target_component_id)
);
CREATE INDEX IF NOT EXISTS ix_dependencies_project ON dependencies(project_id);
CREATE INDEX IF NOT EXISTS ix_dependencies_target ON dependencies(target_component_id);

CREATE TABLE IF NOT EXISTS functionalities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    is_critical     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS functionality_components (
    functionality_id    INTEGER NOT NULL REFERENCES functionalities(id) ON DELETE CASCADE,
    component_id        INTEGER NOT NULL REFERENCES system_components(id) ON DELETE CASCADE,
    PRIMARY KEY (functionality_id, component_id)
);

CREATE TABLE IF NOT EXISTS scenarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    failures_json   TEXT NOT NULL,
    duration_minutes REAL NOT NULL DEFAULT 30,
    created_at      TEXT NOT NULL,
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS simulations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    failure_type        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'CREATED',
    propagation_policy  TEXT NOT NULL,
    duration_minutes    REAL NOT NULL DEFAULT 30 CHECK (duration_minutes > 0),
    current_tick        INTEGER NOT NULL DEFAULT -1,
    max_tick            INTEGER NOT NULL DEFAULT 0,
    impact_score        REAL,
    severity_class      TEXT,
    impact_json         TEXT,
    root_cause_json     TEXT,
    created_at          TEXT NOT NULL,
    started_at          TEXT,
    propagated_at       TEXT,
    completed_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_simulations_project ON simulations(project_id, created_at);
CREATE INDEX IF NOT EXISTS ix_simulations_status ON simulations(status);

CREATE TABLE IF NOT EXISTS failure_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id       INTEGER NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    component_id        INTEGER REFERENCES system_components(id) ON DELETE SET NULL,
    component_name      TEXT NOT NULL,
    failure_type        TEXT NOT NULL,
    severity            INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 10),
    description         TEXT NOT NULL DEFAULT '',
    resulting_status    TEXT NOT NULL,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_failure_events_sim ON failure_events(simulation_id);

CREATE TABLE IF NOT EXISTS simulation_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id       INTEGER NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    component_id        INTEGER REFERENCES system_components(id) ON DELETE SET NULL,
    component_name      TEXT NOT NULL,
    criticality         TEXT NOT NULL,
    status              TEXT NOT NULL,
    health              REAL NOT NULL,
    impact_type         TEXT NOT NULL,
    depth               INTEGER,
    tick                INTEGER,
    reason              TEXT NOT NULL DEFAULT '',
    causes_json         TEXT NOT NULL DEFAULT '[]',
    path_json           TEXT NOT NULL DEFAULT '[]',
    notes_json          TEXT NOT NULL DEFAULT '[]',
    UNIQUE (simulation_id, component_id)
);
CREATE INDEX IF NOT EXISTS ix_sim_results_sim ON simulation_results(simulation_id);

CREATE TABLE IF NOT EXISTS recovery_strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    guarantee       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recovery_plans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id       INTEGER NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    strategy_id         INTEGER NOT NULL REFERENCES recovery_strategies(id),
    status              TEXT NOT NULL DEFAULT 'DRAFT',
    is_selected         INTEGER NOT NULL DEFAULT 0,
    is_manual           INTEGER NOT NULL DEFAULT 0,
    is_valid            INTEGER NOT NULL DEFAULT 1,
    estimated_minutes   REAL NOT NULL DEFAULT 0,
    total_cost          REAL NOT NULL DEFAULT 0,
    metrics_json        TEXT NOT NULL DEFAULT '{}',
    actual_minutes      REAL,
    sim_clock           REAL NOT NULL DEFAULT 0,
    summary_json        TEXT,
    created_at          TEXT NOT NULL,
    started_at          TEXT,
    completed_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_recovery_plans_sim ON recovery_plans(simulation_id);

CREATE TABLE IF NOT EXISTS recovery_actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id             INTEGER NOT NULL REFERENCES recovery_plans(id) ON DELETE CASCADE,
    component_id        INTEGER REFERENCES system_components(id) ON DELETE SET NULL,
    component_name      TEXT NOT NULL,
    order_index         INTEGER NOT NULL,
    action_type         TEXT NOT NULL,
    estimated_minutes   REAL NOT NULL,
    cost                REAL NOT NULL,
    prerequisites_json  TEXT NOT NULL DEFAULT '[]',
    explanation_json    TEXT NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'PENDING',
    attempts            INTEGER NOT NULL DEFAULT 0,
    failure_reason      TEXT,
    sim_start_minute    REAL,
    sim_end_minute      REAL,
    started_at          TEXT,
    completed_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_recovery_actions_plan ON recovery_actions(plan_id, order_index);

CREATE TABLE IF NOT EXISTS event_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    simulation_id       INTEGER REFERENCES simulations(id) ON DELETE CASCADE,
    component_id        INTEGER REFERENCES system_components(id) ON DELETE SET NULL,
    event_type          TEXT NOT NULL,
    category            TEXT NOT NULL DEFAULT 'SYSTEM',
    message             TEXT NOT NULL,
    details_json        TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_event_logs_project ON event_logs(project_id, created_at);
CREATE INDEX IF NOT EXISTS ix_event_logs_sim ON event_logs(simulation_id);

CREATE TABLE IF NOT EXISTS resilience_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    simulation_id       INTEGER REFERENCES simulations(id) ON DELETE SET NULL,
    trigger             TEXT NOT NULL,
    score               REAL NOT NULL,
    grade               TEXT NOT NULL,
    breakdown_json      TEXT NOT NULL,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resilience_project ON resilience_reports(project_id, created_at);

-- Command pattern history (validation + execution + undo support)
CREATE TABLE IF NOT EXISTS command_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    command_name    TEXT NOT NULL,
    description     TEXT NOT NULL,
    payload_json    TEXT NOT NULL DEFAULT '{}',
    undo_json       TEXT,
    undoable        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'EXECUTED' CHECK (status IN ('EXECUTED','UNDONE')),
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_command_log_project ON command_log(project_id, id);
