-- Integra checadas BioTime con asistencia diaria, sucursales, horarios y vacaciones.

CREATE TABLE IF NOT EXISTS tb_cat_sucursales (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    codigo VARCHAR(30) NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    activa BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_cat_sucursales_codigo UNIQUE (codigo)
);

DO $$
BEGIN
    ALTER TABLE tb_cat_sucursales
        ADD CONSTRAINT fk_sucursales_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_cat_sucursales_activa
    ON tb_cat_sucursales (activa, nombre);

ALTER TABLE tb_empleados_datos
    ADD COLUMN IF NOT EXISTS sucursal_id UUID;

ALTER TABLE tb_empleados_datos
    ADD COLUMN IF NOT EXISTS biotime_emp_code VARCHAR(50);

DO $$
BEGIN
    ALTER TABLE tb_empleados_datos
        ADD CONSTRAINT fk_empleados_sucursal
        FOREIGN KEY (sucursal_id) REFERENCES tb_cat_sucursales(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_empleados_datos_sucursal
    ON tb_empleados_datos (sucursal_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_empleados_datos_biotime_emp_code
    ON tb_empleados_datos (biotime_emp_code)
    WHERE biotime_emp_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS tb_horarios_sucursal (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    sucursal_id UUID NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    margen_entrada_antes_min INTEGER NOT NULL DEFAULT 120,
    margen_salida_despues_min INTEGER NOT NULL DEFAULT 360,
    tolerancia_extra_min INTEGER NOT NULL DEFAULT 0,
    descuento_comida_min INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID,
    PRIMARY KEY (id),
    CONSTRAINT fk_horarios_sucursal FOREIGN KEY (sucursal_id)
        REFERENCES tb_cat_sucursales(id) ON DELETE CASCADE,
    CONSTRAINT ck_horarios_margenes CHECK (
        margen_entrada_antes_min >= 0
        AND margen_salida_despues_min >= 0
        AND tolerancia_extra_min >= 0
        AND descuento_comida_min >= 0
    )
);

DO $$
BEGIN
    ALTER TABLE tb_horarios_sucursal
        ADD CONSTRAINT fk_horarios_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_horarios_sucursal_activo
    ON tb_horarios_sucursal (sucursal_id, activo);

CREATE TABLE IF NOT EXISTS tb_horarios_sucursal_dias (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    horario_sucursal_id UUID NOT NULL,
    dia_semana SMALLINT NOT NULL,
    hora_entrada TIME,
    hora_salida TIME,
    minutos_programados INTEGER NOT NULL DEFAULT 0,
    cruza_medianoche BOOLEAN NOT NULL DEFAULT false,
    es_laboral BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (id),
    CONSTRAINT fk_horarios_dias_horario FOREIGN KEY (horario_sucursal_id)
        REFERENCES tb_horarios_sucursal(id) ON DELETE CASCADE,
    CONSTRAINT uq_horarios_dias UNIQUE (horario_sucursal_id, dia_semana),
    CONSTRAINT ck_horarios_dia_semana CHECK (dia_semana BETWEEN 0 AND 6),
    CONSTRAINT ck_horarios_minutos CHECK (minutos_programados >= 0),
    CONSTRAINT ck_horarios_horas_laboral CHECK (
        es_laboral = false OR (hora_entrada IS NOT NULL AND hora_salida IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS tb_biotime_empleado_map (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL,
    empleado_datos_id UUID,
    biotime_emp_id INTEGER,
    biotime_emp_code VARCHAR(50) NOT NULL,
    biotime_pin VARCHAR(50),
    biotime_deptnumber VARCHAR(50),
    biotime_deptname VARCHAR(120),
    sucursal_id UUID,
    activo BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID,
    PRIMARY KEY (id),
    CONSTRAINT fk_biotime_map_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_biotime_map_empleado_datos FOREIGN KEY (empleado_datos_id)
        REFERENCES tb_empleados_datos(id) ON DELETE SET NULL,
    CONSTRAINT fk_biotime_map_sucursal FOREIGN KEY (sucursal_id)
        REFERENCES tb_cat_sucursales(id) ON DELETE SET NULL
);

DO $$
BEGIN
    ALTER TABLE tb_biotime_empleado_map
        ADD CONSTRAINT fk_biotime_map_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_biotime_map_usuario_activo
    ON tb_biotime_empleado_map (usuario_id)
    WHERE activo = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_biotime_map_emp_code_activo
    ON tb_biotime_empleado_map (biotime_emp_code)
    WHERE activo = true;

CREATE INDEX IF NOT EXISTS idx_biotime_map_sucursal
    ON tb_biotime_empleado_map (sucursal_id, activo);

CREATE TABLE IF NOT EXISTS tb_biotime_checks (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    biotime_transaction_id BIGINT,
    biotime_emp_code VARCHAR(50) NOT NULL,
    usuario_id UUID,
    check_time TIMESTAMPTZ NOT NULL,
    punch_state VARCHAR(20),
    verify_type VARCHAR(50),
    terminal_sn VARCHAR(80),
    terminal_alias VARCHAR(120),
    deptnumber VARCHAR(50),
    deptname VARCHAR(120),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT fk_biotime_checks_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_biotime_checks_transaction_id
    ON tb_biotime_checks (biotime_transaction_id)
    WHERE biotime_transaction_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_biotime_checks_emp_time_no_tx
    ON tb_biotime_checks (biotime_emp_code, check_time)
    WHERE biotime_transaction_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_biotime_checks_usuario_time
    ON tb_biotime_checks (usuario_id, check_time);

CREATE INDEX IF NOT EXISTS idx_biotime_checks_emp_time
    ON tb_biotime_checks (biotime_emp_code, check_time);

CREATE TABLE IF NOT EXISTS tb_asistencia_diaria (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL,
    sucursal_id UUID,
    fecha_laboral DATE NOT NULL,
    primera_entrada TIMESTAMPTZ,
    ultima_salida TIMESTAMPTZ,
    minutos_trabajados INTEGER NOT NULL DEFAULT 0,
    minutos_programados INTEGER NOT NULL DEFAULT 0,
    minutos_extra INTEGER NOT NULL DEFAULT 0,
    estado VARCHAR(40) NOT NULL,
    tiene_vacaciones BOOLEAN NOT NULL DEFAULT false,
    solicitud_ausencia_id UUID,
    observaciones TEXT,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_asistencia_usuario_fecha UNIQUE (usuario_id, fecha_laboral),
    CONSTRAINT fk_asistencia_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_asistencia_sucursal FOREIGN KEY (sucursal_id)
        REFERENCES tb_cat_sucursales(id) ON DELETE SET NULL,
    CONSTRAINT fk_asistencia_solicitud FOREIGN KEY (solicitud_ausencia_id)
        REFERENCES tb_solicitudes_ausencia(id) ON DELETE SET NULL,
    CONSTRAINT ck_asistencia_minutos CHECK (
        minutos_trabajados >= 0 AND minutos_programados >= 0 AND minutos_extra >= 0
    ),
    CONSTRAINT ck_asistencia_estado CHECK (
        estado IN (
            'asistencia',
            'vacaciones',
            'sin_registro',
            'falta',
            'incompleto',
            'descanso',
            'feriado',
            'checada_en_vacaciones',
            'sin_horario'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_asistencia_fecha_sucursal
    ON tb_asistencia_diaria (fecha_laboral, sucursal_id);

CREATE INDEX IF NOT EXISTS idx_asistencia_estado_fecha
    ON tb_asistencia_diaria (estado, fecha_laboral);

CREATE TABLE IF NOT EXISTS tb_asistencia_sync_runs (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    from_transaction_id BIGINT,
    to_transaction_id BIGINT,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    records_read INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    records_skipped INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    PRIMARY KEY (id),
    CONSTRAINT ck_asistencia_sync_status CHECK (status IN ('running', 'success', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_asistencia_sync_status_started
    ON tb_asistencia_sync_runs (status, started_at DESC);

INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES
    ('BIOTIME_SYNC_ACTIVO', 'false', 'bool', 'Activa la sincronizacion periodica con BioTime'),
    ('BIOTIME_BASE_URL', '', 'string', 'URL base del servidor BioTime, sin slash final'),
    ('BIOTIME_ACCESS_KEY', '', 'string', 'Llave de acceso API BioTime'),
    ('BIOTIME_SYNC_INTERVAL_SEG', '900', 'int', 'Intervalo del worker BioTime en segundos'),
    ('BIOTIME_SYNC_PAGE_SIZE', '1000', 'int', 'Registros maximos por solicitud BioTime'),
    ('BIOTIME_SYNC_LOOKBACK_HRS', '48', 'int', 'Horas hacia atras cuando no hay ultimo id'),
    ('BIOTIME_SYNC_TIMEOUT_SEG', '30', 'int', 'Timeout HTTP para BioTime en segundos'),
    ('ASISTENCIA_RECALC_DIAS', '7', 'int', 'Dias recientes a recalcular tras cada sync BioTime')
ON CONFLICT (clave) DO NOTHING;
