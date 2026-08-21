-- schema.sql — Postgres schema zastępujący Google Sheets jako magazyn danych.
-- Uruchom: psql "$DATABASE_URL" -f db/schema.sql   (albo db.init_schema() z db.py)

-- ── KONTA (logowanie na stronę — Igor + znajomi) ─────────────────────────────
CREATE TABLE IF NOT EXISTS app_users (
    id            SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── OSOBY ŚLEDZONE PRZEZ GARMINA ─────────────────────────────────────────────
-- is_owner=TRUE: Igor, jedyna osoba z pełnym logowaniem Garmin (Dziennik + Aktywności).
-- is_owner=FALSE: znajomi z listy "connections" — dane tylko z newsfeedu Garmina,
-- widoczne w tabeli `activities` (source='connection_feed').
CREATE TABLE IF NOT EXISTS garmin_people (
    id                SERIAL PRIMARY KEY,
    garmin_profile_id TEXT UNIQUE NOT NULL,
    full_name         TEXT NOT NULL,
    is_owner          BOOLEAN NOT NULL DEFAULT FALSE,
    app_user_id       INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── DZIENNIK (kroki, sen, kalorie, HR — tylko właściciel) ────────────────────
CREATE TABLE IF NOT EXISTS daily_summary (
    person_id        INTEGER NOT NULL REFERENCES garmin_people(id) ON DELETE CASCADE,
    date             DATE NOT NULL,
    steps            NUMERIC,
    distance_km      NUMERIC,
    calories_active  NUMERIC,
    calories_total   NUMERIC,
    sleep_h          NUMERIC,
    sleep_quality    NUMERIC,
    resting_hr       NUMERIC,
    avg_stress       NUMERIC,
    vigorous_minutes NUMERIC,
    weight_kg        NUMERIC,
    PRIMARY KEY (person_id, date)
);

-- ── AKTYWNOŚCI (własne + znajomych z newsfeedu) ──────────────────────────────
CREATE TABLE IF NOT EXISTS activities (
    id                     BIGINT PRIMARY KEY,        -- Garmin activity id
    person_id              INTEGER NOT NULL REFERENCES garmin_people(id) ON DELETE CASCADE,
    source                 TEXT NOT NULL DEFAULT 'own',  -- 'own' | 'connection_feed'
    started_at             TIMESTAMP,
    name                   TEXT,
    sport                  TEXT,
    distance_km            NUMERIC,
    duration               TEXT,          -- sformatowane "H:MM:SS" (jak w Sheets)
    moving_duration        TEXT,
    calories               NUMERIC,
    avg_hr                 NUMERIC,
    max_hr                 NUMERIC,
    elevation_gain_m       NUMERIC,
    elevation_loss_m       NUMERIC,
    avg_temperature        NUMERIC,
    avg_pace               TEXT,
    gap_pace               TEXT,
    best_pace              TEXT,
    avg_power_w            NUMERIC,
    max_power_w            NUMERIC,
    power_per_kg           NUMERIC,
    avg_cadence_spm        NUMERIC,
    max_cadence_spm        NUMERIC,
    stride_length_m        NUMERIC,
    ground_contact_ms      NUMERIC,
    gct_balance_pct        NUMERIC,
    vertical_oscillation_cm NUMERIC,
    vertical_ratio_pct     NUMERIC,
    aerobic_effect         NUMERIC,
    anaerobic_effect       NUMERIC,
    training_load          NUMERIC,
    stamina_start_pct      NUMERIC,
    stamina_end_pct        NUMERIC,
    vo2max                 NUMERIC,
    body_battery_change    NUMERIC,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activities_person_date ON activities (person_id, started_at);

-- ── OKRĄŻENIA (km-splity biegów) ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activity_laps (
    activity_id             BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    lap_number              INTEGER NOT NULL,
    distance_km             NUMERIC,
    duration                TEXT,
    avg_pace                TEXT,
    gap_pace                TEXT,
    avg_hr                  NUMERIC,
    max_hr                  NUMERIC,
    avg_power_w             NUMERIC,
    max_power_w             NUMERIC,
    power_per_kg            NUMERIC,
    avg_cadence_spm         NUMERIC,
    ground_contact_ms       NUMERIC,
    gct_balance_pct         NUMERIC,
    stride_length_m         NUMERIC,
    vertical_oscillation_cm NUMERIC,
    vertical_ratio_pct      NUMERIC,
    elevation_gain_m        NUMERIC,
    elevation_loss_m        NUMERIC,
    PRIMARY KEY (activity_id, lap_number)
);

-- ── TRASY GPS ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gps_tracks (
    activity_id BIGINT PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
    sport       TEXT,
    points      JSONB NOT NULL   -- lista [[lat, lon], ...]
);

-- ── FITATU: dzienne makro ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fitatu_daily (
    person_id  INTEGER NOT NULL REFERENCES garmin_people(id) ON DELETE CASCADE,
    date       DATE NOT NULL,
    kcal       NUMERIC,
    protein_g  NUMERIC,
    fat_g      NUMERIC,
    carbs_g    NUMERIC,
    PRIMARY KEY (person_id, date)
);

-- ── FITATU: produkty per dzień ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fitatu_products (
    id         SERIAL PRIMARY KEY,
    person_id  INTEGER NOT NULL REFERENCES garmin_people(id) ON DELETE CASCADE,
    date       DATE NOT NULL,
    product    TEXT NOT NULL,
    grams      NUMERIC,
    kcal       NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_fitatu_products_person_date ON fitatu_products (person_id, date);

-- ── HEVY: serie siłowe (1 wiersz = 1 seria) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS hevy_sets (
    person_id       INTEGER NOT NULL REFERENCES garmin_people(id) ON DELETE CASCADE,
    workout_id      TEXT NOT NULL,
    exercise_order  INTEGER NOT NULL,   -- kolejność ćwiczenia w treningu (0-indexed)
    set_number      INTEGER NOT NULL,
    started_at      TEXT,
    ended_at        TEXT,
    duration        TEXT,
    workout_title   TEXT,
    workout_notes   TEXT,
    exercise_name   TEXT,
    exercise_notes  TEXT,
    superset_id     TEXT,
    set_type        TEXT,
    weight_kg       NUMERIC,
    reps            NUMERIC,
    distance_m      NUMERIC,
    duration_s      NUMERIC,
    rpe             NUMERIC,
    PRIMARY KEY (workout_id, exercise_order, set_number)
);
CREATE INDEX IF NOT EXISTS idx_hevy_sets_person ON hevy_sets (person_id, workout_id);

-- ── DANE RĘCZNE (waga, wzrost — zastępuje General!E2) ─────────────────────────
CREATE TABLE IF NOT EXISTS manual_metrics (
    person_id  INTEGER NOT NULL REFERENCES garmin_people(id) ON DELETE CASCADE,
    date       DATE NOT NULL,
    weight_kg  NUMERIC,
    height_cm  NUMERIC,
    PRIMARY KEY (person_id, date)
);

-- ── SOCIAL: polubienia / komentarze z newsfeedu znajomych ────────────────────
CREATE TABLE IF NOT EXISTS activity_likes (
    activity_id BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    liker_name  TEXT NOT NULL,
    PRIMARY KEY (activity_id, liker_name)
);

CREATE TABLE IF NOT EXISTS activity_comments (
    id           SERIAL PRIMARY KEY,
    activity_id  BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    author_name  TEXT NOT NULL,
    body         TEXT NOT NULL,
    commented_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
