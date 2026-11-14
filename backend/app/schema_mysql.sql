-- ResQLens schema for MySQL 8.0.16+ (InnoDB, utf8mb4).
-- Mirrors schema.sql (SQLite) table-for-table. Applied idempotently at start-up
-- (CREATE TABLE IF NOT EXISTS), so it never drops or alters existing data.
-- Differences from the SQLite version:
--   * VARCHAR with lengths where a column is UNIQUE / indexed; TEXT for long JSON.
--   * Indexes declared inline (MySQL has no CREATE INDEX IF NOT EXISTS).
--   * The "source <> target" check on dependencies is enforced by the application
--     (MySQL forbids CHECK constraints on columns used by ON DELETE CASCADE).

CREATE TABLE IF NOT EXISTS users (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    full_name       VARCHAR(100) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    created_at      VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_sessions (
    jti             VARCHAR(64) PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    created_at      VARCHAR(40) NOT NULL,
    expires_at      VARCHAR(40) NOT NULL,
    INDEX ix_sessions_user (user_id),
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS projects (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    owner_id            BIGINT NOT NULL,
    name                VARCHAR(120) NOT NULL,
    description         VARCHAR(2000) NOT NULL DEFAULT '',
    propagation_policy  VARCHAR(20) NOT NULL DEFAULT 'BLOCKING',
    current_health      DOUBLE NOT NULL DEFAULT 100,
    last_activity_at    VARCHAR(40) NULL,
    created_at          VARCHAR(40) NOT NULL,
    updated_at          VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_project_owner_name (owner_id, name),
    INDEX ix_projects_owner (owner_id),
    CONSTRAINT ck_projects_policy CHECK (propagation_policy IN ('BLOCKING','FAIL_FAST')),
    CONSTRAINT fk_projects_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS system_components (
    id                          BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id                  BIGINT NOT NULL,
    name                        VARCHAR(120) NOT NULL,
    component_type              VARCHAR(30) NOT NULL,
    description                 VARCHAR(2000) NOT NULL DEFAULT '',
    status                      VARCHAR(20) NOT NULL DEFAULT 'HEALTHY',
    health                      DOUBLE NOT NULL DEFAULT 100,
    baseline_status             VARCHAR(20) NOT NULL DEFAULT 'HEALTHY',
    baseline_health             DOUBLE NOT NULL DEFAULT 100,
    criticality                 VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    recovery_priority           INT NOT NULL DEFAULT 3,
    estimated_recovery_minutes  DOUBLE NOT NULL DEFAULT 10,
    recovery_cost               DOUBLE NOT NULL DEFAULT 10,
    operating_rule              VARCHAR(20) NOT NULL DEFAULT 'STANDARD',
    pos_x                       DOUBLE NULL,
    pos_y                       DOUBLE NULL,
    created_at                  VARCHAR(40) NOT NULL,
    updated_at                  VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_component_name (project_id, name),
    INDEX ix_components_project (project_id),
    CONSTRAINT ck_comp_health CHECK (health >= 0 AND health <= 100),
    CONSTRAINT ck_comp_baseline CHECK (baseline_health >= 0 AND baseline_health <= 100),
    CONSTRAINT ck_comp_priority CHECK (recovery_priority BETWEEN 1 AND 5),
    CONSTRAINT ck_comp_minutes CHECK (estimated_recovery_minutes > 0),
    CONSTRAINT ck_comp_cost CHECK (recovery_cost >= 0),
    CONSTRAINT fk_components_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS dependencies (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id              BIGINT NOT NULL,
    source_component_id     BIGINT NOT NULL,
    target_component_id     BIGINT NOT NULL,
    dependency_type         VARCHAR(20) NOT NULL DEFAULT 'MANDATORY',
    fallback_component_id   BIGINT NULL,
    description             VARCHAR(1000) NOT NULL DEFAULT '',
    created_at              VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_dependency_pair (source_component_id, target_component_id),
    INDEX ix_dependencies_project (project_id),
    INDEX ix_dependencies_target (target_component_id),
    CONSTRAINT ck_dep_type CHECK (dependency_type IN ('MANDATORY','OPTIONAL')),
    CONSTRAINT fk_dep_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_dep_source FOREIGN KEY (source_component_id) REFERENCES system_components(id) ON DELETE CASCADE,
    CONSTRAINT fk_dep_target FOREIGN KEY (target_component_id) REFERENCES system_components(id) ON DELETE CASCADE,
    CONSTRAINT fk_dep_fallback FOREIGN KEY (fallback_component_id) REFERENCES system_components(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS functionalities (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id      BIGINT NOT NULL,
    name            VARCHAR(120) NOT NULL,
    description     VARCHAR(1000) NOT NULL DEFAULT '',
    is_critical     TINYINT(1) NOT NULL DEFAULT 0,
    created_at      VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_functionality_name (project_id, name),
    CONSTRAINT fk_func_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS functionality_components (
    functionality_id    BIGINT NOT NULL,
    component_id        BIGINT NOT NULL,
    PRIMARY KEY (functionality_id, component_id),
    CONSTRAINT fk_fc_func FOREIGN KEY (functionality_id) REFERENCES functionalities(id) ON DELETE CASCADE,
    CONSTRAINT fk_fc_comp FOREIGN KEY (component_id) REFERENCES system_components(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS scenarios (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id          BIGINT NOT NULL,
    name                VARCHAR(150) NOT NULL,
    description         VARCHAR(2000) NOT NULL DEFAULT '',
    failures_json       TEXT NOT NULL,
    duration_minutes    DOUBLE NOT NULL DEFAULT 30,
    created_at          VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_scenario_name (project_id, name),
    CONSTRAINT fk_scen_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS simulations (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id          BIGINT NOT NULL,
    user_id             BIGINT NOT NULL,
    name                VARCHAR(150) NOT NULL,
    description         VARCHAR(2000) NOT NULL DEFAULT '',
    failure_type        VARCHAR(40) NOT NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'CREATED',
    propagation_policy  VARCHAR(20) NOT NULL,
    duration_minutes    DOUBLE NOT NULL DEFAULT 30,
    current_tick        INT NOT NULL DEFAULT -1,
    max_tick            INT NOT NULL DEFAULT 0,
    impact_score        DOUBLE NULL,
    severity_class      VARCHAR(20) NULL,
    impact_json         LONGTEXT NULL,
    root_cause_json     LONGTEXT NULL,
    created_at          VARCHAR(40) NOT NULL,
    started_at          VARCHAR(40) NULL,
    propagated_at       VARCHAR(40) NULL,
    completed_at        VARCHAR(40) NULL,
    INDEX ix_simulations_project (project_id, created_at),
    INDEX ix_simulations_status (status),
    CONSTRAINT ck_sim_duration CHECK (duration_minutes > 0),
    CONSTRAINT fk_sim_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_sim_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS failure_events (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    simulation_id       BIGINT NOT NULL,
    component_id        BIGINT NULL,
    component_name      VARCHAR(120) NOT NULL,
    failure_type        VARCHAR(40) NOT NULL,
    severity            INT NOT NULL,
    description         VARCHAR(1000) NOT NULL DEFAULT '',
    resulting_status    VARCHAR(20) NOT NULL,
    created_at          VARCHAR(40) NOT NULL,
    INDEX ix_failure_events_sim (simulation_id),
    CONSTRAINT ck_fe_severity CHECK (severity BETWEEN 1 AND 10),
    CONSTRAINT fk_fe_sim FOREIGN KEY (simulation_id) REFERENCES simulations(id) ON DELETE CASCADE,
    CONSTRAINT fk_fe_comp FOREIGN KEY (component_id) REFERENCES system_components(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS simulation_results (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    simulation_id       BIGINT NOT NULL,
    component_id        BIGINT NULL,
    component_name      VARCHAR(120) NOT NULL,
    criticality         VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL,
    health              DOUBLE NOT NULL,
    impact_type         VARCHAR(20) NOT NULL,
    depth               INT NULL,
    tick                INT NULL,
    reason              TEXT NOT NULL,
    causes_json         TEXT NOT NULL,
    path_json           TEXT NOT NULL,
    notes_json          TEXT NOT NULL,
    UNIQUE KEY uq_sim_result (simulation_id, component_id),
    INDEX ix_sim_results_sim (simulation_id),
    CONSTRAINT fk_sr_sim FOREIGN KEY (simulation_id) REFERENCES simulations(id) ON DELETE CASCADE,
    CONSTRAINT fk_sr_comp FOREIGN KEY (component_id) REFERENCES system_components(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recovery_strategies (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    `key`           VARCHAR(40) NOT NULL UNIQUE,
    name            VARCHAR(120) NOT NULL,
    description     VARCHAR(2000) NOT NULL,
    guarantee       VARCHAR(2000) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recovery_plans (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    simulation_id       BIGINT NOT NULL,
    strategy_id         BIGINT NOT NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    is_selected         TINYINT(1) NOT NULL DEFAULT 0,
    is_manual           TINYINT(1) NOT NULL DEFAULT 0,
    is_valid            TINYINT(1) NOT NULL DEFAULT 1,
    estimated_minutes   DOUBLE NOT NULL DEFAULT 0,
    total_cost          DOUBLE NOT NULL DEFAULT 0,
    metrics_json        LONGTEXT NOT NULL,
    actual_minutes      DOUBLE NULL,
    sim_clock           DOUBLE NOT NULL DEFAULT 0,
    summary_json        LONGTEXT NULL,
    created_at          VARCHAR(40) NOT NULL,
    started_at          VARCHAR(40) NULL,
    completed_at        VARCHAR(40) NULL,
    INDEX ix_recovery_plans_sim (simulation_id),
    CONSTRAINT fk_rp_sim FOREIGN KEY (simulation_id) REFERENCES simulations(id) ON DELETE CASCADE,
    CONSTRAINT fk_rp_strategy FOREIGN KEY (strategy_id) REFERENCES recovery_strategies(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recovery_actions (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    plan_id             BIGINT NOT NULL,
    component_id        BIGINT NULL,
    component_name      VARCHAR(120) NOT NULL,
    order_index         INT NOT NULL,
    action_type         VARCHAR(40) NOT NULL,
    estimated_minutes   DOUBLE NOT NULL,
    cost                DOUBLE NOT NULL,
    prerequisites_json  TEXT NOT NULL,
    explanation_json    LONGTEXT NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    attempts            INT NOT NULL DEFAULT 0,
    failure_reason      TEXT NULL,
    sim_start_minute    DOUBLE NULL,
    sim_end_minute      DOUBLE NULL,
    started_at          VARCHAR(40) NULL,
    completed_at        VARCHAR(40) NULL,
    INDEX ix_recovery_actions_plan (plan_id, order_index),
    CONSTRAINT fk_ra_plan FOREIGN KEY (plan_id) REFERENCES recovery_plans(id) ON DELETE CASCADE,
    CONSTRAINT fk_ra_comp FOREIGN KEY (component_id) REFERENCES system_components(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS event_logs (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id          BIGINT NOT NULL,
    simulation_id       BIGINT NULL,
    component_id        BIGINT NULL,
    event_type          VARCHAR(40) NOT NULL,
    category            VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    message             TEXT NOT NULL,
    details_json        LONGTEXT NOT NULL,
    created_at          VARCHAR(40) NOT NULL,
    INDEX ix_event_logs_project (project_id, created_at),
    INDEX ix_event_logs_sim (simulation_id),
    CONSTRAINT fk_el_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_el_sim FOREIGN KEY (simulation_id) REFERENCES simulations(id) ON DELETE CASCADE,
    CONSTRAINT fk_el_comp FOREIGN KEY (component_id) REFERENCES system_components(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS resilience_reports (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id          BIGINT NOT NULL,
    simulation_id       BIGINT NULL,
    `trigger`           VARCHAR(30) NOT NULL,
    score               DOUBLE NOT NULL,
    grade               VARCHAR(2) NOT NULL,
    breakdown_json      LONGTEXT NOT NULL,
    created_at          VARCHAR(40) NOT NULL,
    INDEX ix_resilience_project (project_id, created_at),
    CONSTRAINT fk_rr_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_rr_sim FOREIGN KEY (simulation_id) REFERENCES simulations(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS command_log (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id      BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    command_name    VARCHAR(60) NOT NULL,
    description     VARCHAR(1000) NOT NULL,
    payload_json    LONGTEXT NOT NULL,
    undo_json       LONGTEXT NULL,
    undoable        TINYINT(1) NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'EXECUTED',
    created_at      VARCHAR(40) NOT NULL,
    INDEX ix_command_log_project (project_id, id),
    CONSTRAINT ck_cmd_status CHECK (status IN ('EXECUTED','UNDONE')),
    CONSTRAINT fk_cmd_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_cmd_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
