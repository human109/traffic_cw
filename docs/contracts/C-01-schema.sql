-- C-01 DB 스키마 v1 (frozen). database/schema.sql 은 이 파일과 내용이 같아야 한다.
-- 근거: SPEC 5장, 20.6 / 변경: C-01-db-schema.md 변경 이력 참조

CREATE TABLE IF NOT EXISTS road_segment (
    segment_id     TEXT PRIMARY KEY,
    road_name      TEXT NOT NULL,
    start_node     TEXT NOT NULL,
    end_node       TEXT NOT NULL,
    direction      TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    distance_m     REAL,
    is_target      INTEGER NOT NULL DEFAULT 1,
    is_active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS segment_link (
    id             INTEGER PRIMARY KEY,
    segment_id     TEXT NOT NULL REFERENCES road_segment(segment_id),
    link_id        TEXT NOT NULL,
    source         TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    link_length_m  REAL,
    is_mainline    INTEGER NOT NULL DEFAULT 1,
    nodelink_ver   TEXT,
    valid_from     TEXT NOT NULL,
    valid_to       TEXT,
    UNIQUE (source, link_id, valid_from)
);

CREATE TABLE IF NOT EXISTS traffic_observation (
    id               INTEGER PRIMARY KEY,
    source           TEXT NOT NULL,
    link_id          TEXT NOT NULL,
    source_timestamp TEXT NOT NULL,
    collected_at     TEXT NOT NULL,
    speed            REAL,
    travel_time      REAL,
    volume           INTEGER,
    congestion_code  TEXT,
    quality_flag     TEXT NOT NULL DEFAULT 'ok',
    raw_file         TEXT,
    UNIQUE (source, link_id, source_timestamp)
);
CREATE INDEX IF NOT EXISTS ix_obs_link_time ON traffic_observation (link_id, source_timestamp);

CREATE TABLE IF NOT EXISTS segment_traffic_5min (
    segment_id        TEXT NOT NULL REFERENCES road_segment(segment_id),
    bin_time          TEXT NOT NULL,
    available_at      TEXT NOT NULL,
    speed             REAL,
    speed_side        REAL,
    volume            REAL,
    n_links_expected  INTEGER NOT NULL,
    n_links_observed  INTEGER NOT NULL,
    is_imputed        INTEGER NOT NULL DEFAULT 0,
    quality_flag      TEXT NOT NULL,
    processed_at      TEXT NOT NULL,
    PRIMARY KEY (segment_id, bin_time)
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_version   TEXT PRIMARY KEY,
    model_type      TEXT NOT NULL,
    target_var      TEXT NOT NULL,
    horizon         INTEGER NOT NULL,
    train_start     TEXT,
    train_end       TEXT,
    features        TEXT,
    hyperparams     TEXT,
    artifact_path   TEXT,
    trained_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS traffic_prediction (
    id               INTEGER PRIMARY KEY,
    segment_id       TEXT NOT NULL REFERENCES road_segment(segment_id),
    base_time        TEXT NOT NULL,
    executed_at      TEXT NOT NULL,
    horizon          INTEGER NOT NULL,
    target_time      TEXT NOT NULL,
    target_var       TEXT NOT NULL,
    predicted_value  REAL,
    model_version    TEXT NOT NULL REFERENCES model_registry(model_version),
    input_quality    TEXT NOT NULL,
    actual_value     REAL,
    abs_error        REAL,
    UNIQUE (segment_id, base_time, horizon, target_var, model_version)
);

CREATE TABLE IF NOT EXISTS model_evaluation (
    id              INTEGER PRIMARY KEY,
    model_version   TEXT NOT NULL REFERENCES model_registry(model_version),
    eval_type       TEXT NOT NULL,
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    segment_id      TEXT,
    regime          TEXT,
    n_samples       INTEGER NOT NULL,
    mae             REAL,
    rmse            REAL,
    wape            REAL,
    grade_accuracy  REAL,
    evaluated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_log (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,
    http_status     INTEGER,
    links_expected  INTEGER,
    links_received  INTEGER,
    record_count    INTEGER,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS calendar_info (
    date                   TEXT PRIMARY KEY,
    is_holiday             INTEGER NOT NULL,
    holiday_name           TEXT,
    is_school_vacation     INTEGER,
    is_industrial_vacation INTEGER,
    is_holiday_adjacent    INTEGER
);

CREATE TABLE IF NOT EXISTS publish_log (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    base_time     TEXT,
    status        TEXT NOT NULL,
    public_status TEXT,
    bytes         INTEGER,
    error_message TEXT
);
