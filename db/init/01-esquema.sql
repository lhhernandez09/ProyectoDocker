-- =====================================================================
-- Esquema de la base de datos "nba"
-- Se ejecuta automáticamente SOLO la primera vez que arranca PostgreSQL
-- (cuando el volumen de datos está vacío).
-- =====================================================================

-- Catálogos ------------------------------------------------------------

CREATE TABLE conferencias (
    conferencia_id SMALLINT PRIMARY KEY,            -- id de ESPN (5 = Este, 6 = Oeste)
    nombre         VARCHAR(60) NOT NULL,
    abreviatura    VARCHAR(10) NOT NULL
);

CREATE TABLE divisiones (
    division_id    SMALLINT PRIMARY KEY,            -- id de ESPN
    conferencia_id SMALLINT NOT NULL REFERENCES conferencias (conferencia_id),
    nombre         VARCHAR(60) NOT NULL,
    abreviatura    VARCHAR(10) NOT NULL
);

CREATE TABLE tipos_temporada (
    tipo_id SMALLINT PRIMARY KEY,                   -- valor "season.type" de ESPN
    nombre  VARCHAR(40) NOT NULL
);

INSERT INTO tipos_temporada (tipo_id, nombre) VALUES
    (1, 'Pretemporada'),
    (2, 'Temporada regular'),
    (3, 'Playoffs'),
    (4, 'Fuera de temporada'),
    (5, 'Play-In');

CREATE TABLE equipos (
    equipo_id        INTEGER PRIMARY KEY,           -- id de ESPN
    abreviatura      VARCHAR(10)  NOT NULL,
    nombre           VARCHAR(100) NOT NULL,         -- "Boston Celtics"
    nombre_corto     VARCHAR(60),                   -- "Celtics"
    ciudad           VARCHAR(60),
    color_primario   CHAR(6),
    color_secundario CHAR(6),
    logo_url         TEXT,
    division_id      SMALLINT REFERENCES divisiones (division_id),
    -- FALSE para rivales de exhibición (equipos internacionales, All-Star, etc.)
    es_nba           BOOLEAN NOT NULL DEFAULT FALSE,
    actualizado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hechos ---------------------------------------------------------------

CREATE TABLE partidos (
    partido_id          BIGINT PRIMARY KEY,         -- id del evento en ESPN
    temporada           SMALLINT NOT NULL,          -- año en que termina: 2026 = 2025-26
    tipo_temporada      SMALLINT NOT NULL REFERENCES tipos_temporada (tipo_id),
    fecha               DATE NOT NULL,              -- fecha del partido (calendario de EE. UU.)
    inicio              TIMESTAMPTZ NOT NULL,       -- hora de inicio (UTC)
    tipo_partido        VARCHAR(10),                -- STD normal, CC final de la NBA Cup, ...
    nota                VARCHAR(120),               -- "NBA Finals - Game 2", "NBA Cup Championship"
    estado              VARCHAR(30) NOT NULL,       -- STATUS_FINAL, STATUS_SCHEDULED, ...
    completado          BOOLEAN NOT NULL DEFAULT FALSE,
    equipo_local_id     INTEGER NOT NULL REFERENCES equipos (equipo_id),
    equipo_visitante_id INTEGER NOT NULL REFERENCES equipos (equipo_id),
    puntos_local        SMALLINT,
    puntos_visitante    SMALLINT,
    periodos            SMALLINT,                   -- 4 = tiempo regular, >4 = hubo prórroga
    sede                VARCHAR(120),
    ciudad              VARCHAR(80),
    asistencia          INTEGER,
    sitio_neutral       BOOLEAN NOT NULL DEFAULT FALSE,
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (equipo_local_id <> equipo_visitante_id)
);

CREATE INDEX idx_partidos_temporada ON partidos (temporada, tipo_temporada, fecha);
CREATE INDEX idx_partidos_local     ON partidos (equipo_local_id);
CREATE INDEX idx_partidos_visitante ON partidos (equipo_visitante_id);

-- Relación N:M entre partidos y equipos con el box score de cada equipo.
CREATE TABLE estadisticas_equipo_partido (
    partido_id              BIGINT  NOT NULL REFERENCES partidos (partido_id) ON DELETE CASCADE,
    equipo_id               INTEGER NOT NULL REFERENCES equipos (equipo_id),
    rebotes                 SMALLINT,
    asistencias             SMALLINT,
    tiros_campo_anotados    SMALLINT,
    tiros_campo_intentados  SMALLINT,
    triples_anotados        SMALLINT,
    triples_intentados      SMALLINT,
    tiros_libres_anotados   SMALLINT,
    tiros_libres_intentados SMALLINT,
    PRIMARY KEY (partido_id, equipo_id)
);

-- Puntos de cada equipo por cuarto (y prórrogas: periodo 5, 6, ...).
CREATE TABLE puntos_periodo (
    partido_id BIGINT   NOT NULL,
    equipo_id  INTEGER  NOT NULL,
    periodo    SMALLINT NOT NULL CHECK (periodo >= 1),
    puntos     SMALLINT NOT NULL,
    PRIMARY KEY (partido_id, equipo_id, periodo),
    FOREIGN KEY (partido_id, equipo_id)
        REFERENCES estadisticas_equipo_partido (partido_id, equipo_id) ON DELETE CASCADE
);

-- Bitácora del proceso de obtención de datos (ETL) ----------------------

CREATE TABLE ingestas (
    ingesta_id          SERIAL PRIMARY KEY,
    tipo                VARCHAR(20) NOT NULL,       -- equipos | partidos | temporada | automatica
    parametros          JSONB NOT NULL DEFAULT '{}',
    estado              VARCHAR(20) NOT NULL DEFAULT 'en_proceso'
                        CHECK (estado IN ('en_proceso', 'completada', 'error')),
    dias_total          INTEGER NOT NULL DEFAULT 0,
    dias_procesados     INTEGER NOT NULL DEFAULT 0,
    solicitudes_api     INTEGER NOT NULL DEFAULT 0,
    registros_guardados INTEGER NOT NULL DEFAULT 0,
    mensaje             TEXT,
    iniciada_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizada_en       TIMESTAMPTZ
);
