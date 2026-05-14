-- 066_vacaciones_rrhh_base.sql
-- Tablas base para módulo vacaciones y RRHH: empleados, ausencias, firmas digitales.
-- NOTA: se usa tb_cat_tipos_ausencia (no tb_cat_tipos_solicitud, que ya existe en el módulo comercial).

-- ─────────────────────────────────────────────
-- 1. Nueva columna en tb_usuarios
-- ─────────────────────────────────────────────
ALTER TABLE tb_usuarios ADD COLUMN IF NOT EXISTS es_rh BOOLEAN DEFAULT false;

-- ─────────────────────────────────────────────
-- 2. Catálogo: días por antigüedad (LFT + 3, 11 niveles)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_cat_dias_vacaciones (
    id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
    antiguedad_anios    INTEGER     NOT NULL,
    antiguedad_anios_fin INTEGER,
    dias_lft            INTEGER     NOT NULL,
    dias_enertika       INTEGER     NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_cat_dias UNIQUE (antiguedad_anios)
);

INSERT INTO tb_cat_dias_vacaciones (antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika)
VALUES
    (1,   1,    12, 15),
    (2,   2,    14, 17),
    (3,   3,    16, 19),
    (4,   4,    18, 21),
    (5,   5,    20, 23),
    (6,   10,   22, 25),
    (11,  15,   24, 27),
    (16,  20,   26, 29),
    (21,  25,   28, 31),
    (26,  30,   30, 33),
    (31,  NULL, 32, 35)
ON CONFLICT (antiguedad_anios) DO NOTHING;

-- ─────────────────────────────────────────────
-- 3. Catálogo: tipos de ausencia (vacaciones, HO, incapacidades, permisos)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_cat_tipos_ausencia (
    id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
    nombre              VARCHAR(50) NOT NULL,
    slug                VARCHAR(30) NOT NULL,
    abreviatura         VARCHAR(5)  NOT NULL,
    afecta_saldo        BOOLEAN     DEFAULT true,
    requiere_aprobacion BOOLEAN     DEFAULT true,
    is_active           BOOLEAN     DEFAULT true,
    orden               INTEGER     DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT uq_tipos_ausencia_slug UNIQUE (slug)
);

INSERT INTO tb_cat_tipos_ausencia (nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion, orden)
VALUES
    ('Vacaciones',                   'vacaciones',             'VAC', true,  true,  1),
    ('Extraordinaria / Urgencia',    'extraordinaria',         'EXT', true,  true,  2),
    ('Home Office',                  'home_office',            'HO',  false, true,  3),
    ('Incapacidad',                  'incapacidad',            'INC', false, false, 4),
    ('Permiso con goce',             'permiso_con_goce',       'PCG', false, true,  5),
    ('Permiso para llegar tarde',    'permiso_llegar_tarde',   'PLT', false, true,  6),
    ('Permiso para salir temprano',  'permiso_salir_temprano', 'PST', false, true,  7),
    ('Permiso sin goce',             'permiso_sin_goce',       'PSG', false, true,  8)
ON CONFLICT (slug) DO NOTHING;

-- ─────────────────────────────────────────────
-- 4. Catálogo: días festivos oficiales (administrado por RH)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_cat_festivos (
    id          UUID         NOT NULL DEFAULT gen_random_uuid(),
    fecha       DATE         NOT NULL,
    descripcion VARCHAR(100) NOT NULL,
    es_oficial  BOOLEAN      DEFAULT true,
    created_at  TIMESTAMPTZ  DEFAULT now(),
    created_by  UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_festivos_fecha UNIQUE (fecha),
    CONSTRAINT fk_festivos_created_by FOREIGN KEY (created_by)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL
);

INSERT INTO tb_cat_festivos (fecha, descripcion, es_oficial)
VALUES
    ('2026-01-01', 'Año Nuevo',                 true),
    ('2026-02-02', 'Día de la Constitución',     true),
    ('2026-03-16', 'Natalicio de Benito Juárez', true),
    ('2026-05-01', 'Día del Trabajo',            true),
    ('2026-09-16', 'Día de la Independencia',    true),
    ('2026-11-16', 'Revolución Mexicana',        true),
    ('2026-12-25', 'Navidad',                    true)
ON CONFLICT (fecha) DO NOTHING;

-- ─────────────────────────────────────────────
-- 5. Datos laborales del empleado (extiende tb_usuarios 1:1)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_empleados_datos (
    id                        UUID         NOT NULL DEFAULT gen_random_uuid(),
    usuario_id                UUID         NOT NULL,
    numero_empleado           VARCHAR(20),
    fecha_contratacion        DATE,
    puesto                    VARCHAR(100),
    departamento              VARCHAR(50),
    id_aprobador_vacaciones   UUID,
    dias_vacaciones_ajuste    INTEGER      DEFAULT 0,
    created_at                TIMESTAMPTZ  DEFAULT now(),
    updated_at                TIMESTAMPTZ  DEFAULT now(),
    updated_by                UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_empleados_datos_usuario UNIQUE (usuario_id),
    CONSTRAINT fk_empleados_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_empleados_aprobador FOREIGN KEY (id_aprobador_vacaciones)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    CONSTRAINT fk_empleados_updated_by FOREIGN KEY (updated_by)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_empleados_aprobador
    ON tb_empleados_datos(id_aprobador_vacaciones);

-- ─────────────────────────────────────────────
-- 6. Relación muchos-a-muchos empleado-jefe
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_empleados_jefes (
    id          UUID        NOT NULL DEFAULT gen_random_uuid(),
    empleado_id UUID        NOT NULL,
    jefe_id     UUID        NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_empleado_jefe UNIQUE (empleado_id, jefe_id),
    CONSTRAINT fk_ej_empleado FOREIGN KEY (empleado_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_ej_jefe FOREIGN KEY (jefe_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_empleados_jefes_jefe
    ON tb_empleados_jefes(jefe_id);
CREATE INDEX IF NOT EXISTS idx_empleados_jefes_empleado
    ON tb_empleados_jefes(empleado_id);

-- ─────────────────────────────────────────────
-- 7. Firma digital precargada del usuario (BYTEA, nunca filesystem)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_usuarios_firmas (
    usuario_id  UUID        NOT NULL,
    firma_data  BYTEA       NOT NULL,
    tipo_firma  VARCHAR(20) DEFAULT 'subida',
    fecha_carga TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (usuario_id),
    CONSTRAINT fk_usuarios_firmas FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT ck_tipo_firma CHECK (tipo_firma IN ('subida', 'dibujada'))
);

-- ─────────────────────────────────────────────
-- 8. Solicitudes de ausencia
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_solicitudes_ausencia (
    id                              UUID        NOT NULL DEFAULT gen_random_uuid(),
    usuario_id                      UUID        NOT NULL,
    tipo_ausencia_id                UUID        NOT NULL,
    fecha_inicio                    DATE        NOT NULL,
    fecha_fin                       DATE        NOT NULL,
    dias_solicitados                INTEGER     NOT NULL,
    fecha_presentarse               DATE        NOT NULL,
    observaciones                   TEXT,
    estado                          VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    aprobado_por                    UUID,
    motivo_rechazo                  TEXT,
    fecha_solicitud                 TIMESTAMPTZ DEFAULT now(),
    fecha_resolucion                TIMESTAMPTZ,
    ultima_notificacion_aprobador   TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ DEFAULT now(),
    updated_at                      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT fk_solicitudes_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_solicitudes_tipo FOREIGN KEY (tipo_ausencia_id)
        REFERENCES tb_cat_tipos_ausencia(id) ON DELETE RESTRICT,
    CONSTRAINT fk_solicitudes_aprobador FOREIGN KEY (aprobado_por)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    CONSTRAINT ck_solicitudes_estado CHECK (
        estado IN ('pendiente', 'aprobado', 'rechazado', 'cancelado')
    ),
    CONSTRAINT ck_solicitudes_fechas CHECK (fecha_fin >= fecha_inicio)
);

CREATE INDEX IF NOT EXISTS idx_solicitudes_usuario_estado
    ON tb_solicitudes_ausencia(usuario_id, estado);
CREATE INDEX IF NOT EXISTS idx_solicitudes_pendientes
    ON tb_solicitudes_ausencia(estado) WHERE estado = 'pendiente';
CREATE INDEX IF NOT EXISTS idx_solicitudes_fechas
    ON tb_solicitudes_ausencia(fecha_inicio, fecha_fin);
CREATE INDEX IF NOT EXISTS idx_solicitudes_aprobador
    ON tb_solicitudes_ausencia(aprobado_por);
CREATE INDEX IF NOT EXISTS idx_solicitudes_usuario_created
    ON tb_solicitudes_ausencia(usuario_id, created_at DESC);

-- ─────────────────────────────────────────────
-- 9. Consumo FIFO de períodos de vacaciones
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_vacaciones_consumo (
    id                       UUID        NOT NULL DEFAULT gen_random_uuid(),
    solicitud_id             UUID        NOT NULL,
    num_periodo              INTEGER     NOT NULL,
    dias_consumidos          INTEGER     NOT NULL,
    fecha_aniversario_periodo DATE       NOT NULL,
    created_at               TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT fk_consumo_solicitud FOREIGN KEY (solicitud_id)
        REFERENCES tb_solicitudes_ausencia(id) ON DELETE CASCADE,
    CONSTRAINT ck_consumo_num_periodo CHECK (num_periodo > 0)
);

CREATE INDEX IF NOT EXISTS idx_consumo_solicitud
    ON tb_vacaciones_consumo(solicitud_id);

-- ─────────────────────────────────────────────
-- 10. Registro de firmas por solicitud
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tb_solicitudes_firmas (
    id           UUID        NOT NULL DEFAULT gen_random_uuid(),
    solicitud_id UUID        NOT NULL,
    firmante_id  UUID        NOT NULL,
    rol_firma    VARCHAR(20) NOT NULL,
    fecha_firma  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT fk_firmas_solicitud FOREIGN KEY (solicitud_id)
        REFERENCES tb_solicitudes_ausencia(id) ON DELETE CASCADE,
    CONSTRAINT fk_firmas_usuario FOREIGN KEY (firmante_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT ck_firmas_rol CHECK (rol_firma IN ('solicitante', 'aprobador')),
    CONSTRAINT uq_firmas_solicitud_rol UNIQUE (solicitud_id, rol_firma)
);
