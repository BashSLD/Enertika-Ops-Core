-- Implementa bolsa de horas extra, compensatorios, evidencias y niveles HE.

CREATE TABLE IF NOT EXISTS tb_he_bolsa_movimientos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    tipo VARCHAR(20) NOT NULL,
    minutos INTEGER NOT NULL,
    concepto TEXT NOT NULL,
    fecha_referencia DATE NOT NULL,
    aprobacion_id UUID NULL REFERENCES tb_horas_extra_aprobaciones(id) ON DELETE SET NULL,
    solicitud_compensatorio_id UUID NULL,
    creado_por UUID NULL REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_he_bolsa_tipo CHECK (tipo IN ('CREDITO', 'DEBITO')),
    CONSTRAINT ck_he_bolsa_minutos CHECK (minutos > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_he_bolsa_aprobacion
    ON tb_he_bolsa_movimientos (aprobacion_id)
    WHERE aprobacion_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_he_bolsa_solicitud_compensatorio
    ON tb_he_bolsa_movimientos (solicitud_compensatorio_id)
    WHERE solicitud_compensatorio_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_he_bolsa_usuario_fecha
    ON tb_he_bolsa_movimientos (usuario_id, fecha_referencia, created_at, id);

CREATE INDEX IF NOT EXISTS idx_he_bolsa_usuario_tipo
    ON tb_he_bolsa_movimientos (usuario_id, tipo);

CREATE TABLE IF NOT EXISTS tb_he_solicitudes_compensatorio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    fecha_descanso DATE NOT NULL,
    minutos_solicitados INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    estatus VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    aprobador_id UUID NULL REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    comentario_aprobador TEXT NULL,
    movimiento_id UUID NULL REFERENCES tb_he_bolsa_movimientos(id) ON DELETE SET NULL,
    fecha_solicitud TIMESTAMPTZ NOT NULL DEFAULT now(),
    fecha_resolucion TIMESTAMPTZ NULL,
    ultimo_recordatorio_at TIMESTAMPTZ NULL,
    recordatorios_enviados INTEGER NOT NULL DEFAULT 0,
    resumen_rh_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_he_comp_estatus CHECK (estatus IN ('pendiente', 'aprobado', 'rechazado', 'cancelado')),
    CONSTRAINT ck_he_comp_minutos CHECK (minutos_solicitados > 0),
    CONSTRAINT ck_he_comp_recordatorios CHECK (recordatorios_enviados >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_he_comp_usuario_fecha_activa
    ON tb_he_solicitudes_compensatorio (usuario_id, fecha_descanso)
    WHERE estatus IN ('pendiente', 'aprobado');

CREATE INDEX IF NOT EXISTS idx_he_comp_usuario_estatus
    ON tb_he_solicitudes_compensatorio (usuario_id, estatus, fecha_descanso);

CREATE INDEX IF NOT EXISTS idx_he_comp_pendientes_recordatorios
    ON tb_he_solicitudes_compensatorio (estatus, fecha_solicitud, ultimo_recordatorio_at)
    WHERE estatus = 'pendiente';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_he_bolsa_solicitud_compensatorio'
    ) THEN
        ALTER TABLE tb_he_bolsa_movimientos
            ADD CONSTRAINT fk_he_bolsa_solicitud_compensatorio
            FOREIGN KEY (solicitud_compensatorio_id)
            REFERENCES tb_he_solicitudes_compensatorio(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS tb_he_saldo_inicial_confirmaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    minutos INTEGER NOT NULL,
    confirmado_por UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    movimiento_id UUID NULL REFERENCES tb_he_bolsa_movimientos(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_he_saldo_inicial_usuario UNIQUE (usuario_id),
    CONSTRAINT ck_he_saldo_inicial_minutos CHECK (minutos >= 0)
);

CREATE INDEX IF NOT EXISTS idx_he_saldo_inicial_confirmado_por
    ON tb_he_saldo_inicial_confirmaciones (confirmado_por);

CREATE TABLE IF NOT EXISTS tb_cat_he_niveles (
    nivel INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    umbral_horas INTEGER NOT NULL,
    color_hex VARCHAR(7) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cat_he_niveles_umbral UNIQUE (umbral_horas),
    CONSTRAINT ck_cat_he_niveles_umbral CHECK (umbral_horas >= 0),
    CONSTRAINT ck_cat_he_niveles_color CHECK (color_hex ~ '^#[0-9A-Fa-f]{6}$')
);

INSERT INTO tb_cat_he_niveles (nivel, nombre, umbral_horas, color_hex)
VALUES
    (1, 'Chispa', 0, '#6B7280'),
    (2, 'Voltio', 49, '#3B82F6'),
    (3, 'Amperio', 97, '#00BABB'),
    (4, 'Vatio', 145, '#8B5CF6'),
    (5, 'Kilowatt', 193, '#F59E0B'),
    (6, 'Megawatt', 241, '#EAB308')
ON CONFLICT (nivel) DO UPDATE SET
    nombre = EXCLUDED.nombre,
    umbral_horas = EXCLUDED.umbral_horas,
    color_hex = EXCLUDED.color_hex,
    activo = true;

ALTER TABLE tb_asistencia_diaria
    ADD COLUMN IF NOT EXISTS minutos_he_compensatorio INTEGER NOT NULL DEFAULT 0;

ALTER TABLE tb_asistencia_diaria
    ADD COLUMN IF NOT EXISTS he_compensatorio_solicitud_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_asistencia_he_comp_solicitud'
    ) THEN
        ALTER TABLE tb_asistencia_diaria
            ADD CONSTRAINT fk_asistencia_he_comp_solicitud
            FOREIGN KEY (he_compensatorio_solicitud_id)
            REFERENCES tb_he_solicitudes_compensatorio(id)
            ON DELETE SET NULL;
    END IF;
END $$;

ALTER TABLE tb_asistencia_diaria DROP CONSTRAINT IF EXISTS ck_horas_extra_estado;
ALTER TABLE tb_asistencia_diaria
    ADD CONSTRAINT ck_horas_extra_estado
    CHECK (horas_extra_estado IN ('pendiente', 'solicitado', 'aprobado', 'omitido', 'feriado'));

ALTER TABLE tb_asistencia_diaria DROP CONSTRAINT IF EXISTS ck_asistencia_estado;
ALTER TABLE tb_asistencia_diaria
    ADD CONSTRAINT ck_asistencia_estado
    CHECK (
        estado IN (
            'asistencia',
            'vacaciones',
            'ausencia',
            'sin_registro',
            'falta',
            'incompleto',
            'en_curso',
            'descanso',
            'feriado',
            'checada_en_vacaciones',
            'checada_en_ausencia',
            'sin_horario',
            'he_compensatorio'
        )
    );

ALTER TABLE tb_asistencia_diaria DROP CONSTRAINT IF EXISTS ck_asistencia_minutos;
ALTER TABLE tb_asistencia_diaria
    ADD CONSTRAINT ck_asistencia_minutos
    CHECK (
        minutos_trabajados >= 0
        AND minutos_programados >= 0
        AND minutos_extra >= 0
        AND minutos_he_compensatorio >= 0
    );

CREATE INDEX IF NOT EXISTS idx_asistencia_he_compensatorio
    ON tb_asistencia_diaria (he_compensatorio_solicitud_id)
    WHERE he_compensatorio_solicitud_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_asistencia_he_feriado
    ON tb_asistencia_diaria (fecha_laboral, usuario_id)
    WHERE horas_extra_estado = 'feriado' AND minutos_extra > 0;

INSERT INTO tb_cat_origenes_adjuntos (slug, descripcion, activo)
VALUES ('he_evidencia', 'Evidencia asociada a solicitud de horas extra', true)
ON CONFLICT (slug) DO UPDATE SET
    descripcion = EXCLUDED.descripcion,
    activo = true;

CREATE INDEX IF NOT EXISTS idx_attach_he_evidencia_asistencia
    ON tb_documentos_attachments ((metadata->>'id_asistencia'))
    WHERE origen_slug = 'he_evidencia';

CREATE INDEX IF NOT EXISTS idx_attach_he_evidencia_usuario
    ON tb_documentos_attachments ((metadata->>'usuario_id'))
    WHERE origen_slug = 'he_evidencia';

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
VALUES
    ('HE_EVIDENCIA_MAX_ARCHIVOS', '3', 'Maximo de evidencias permitidas por solicitud de horas extra.', 'int'),
    ('HE_EVIDENCIA_MAX_MB', '4', 'Tamano maximo por evidencia de horas extra en MB.', 'int'),
    ('HE_BOLSA_FECHA_CORTE', '2026-07-07', 'Fecha de corte para confirmacion de saldo inicial de bolsa HE.', 'date')
ON CONFLICT (clave) DO NOTHING;

UPDATE tb_asistencia_diaria ad
SET horas_extra_estado = 'feriado',
    horas_extra_resumen_rh_at = NULL,
    updated_at = now()
FROM tb_cat_festivos f
WHERE f.fecha = ad.fecha_laboral
  AND ad.minutos_extra > 0
  AND ad.horas_extra_estado IN ('pendiente', 'solicitado');

COMMENT ON TABLE tb_he_bolsa_movimientos IS
    'Log inmutable de creditos y debitos de bolsa de horas extra.';
COMMENT ON TABLE tb_he_solicitudes_compensatorio IS
    'Solicitudes de descanso compensatorio usando saldo de horas extra.';
COMMENT ON TABLE tb_he_saldo_inicial_confirmaciones IS
    'Confirmaciones obligatorias de saldo inicial de bolsa HE por empleado.';
COMMENT ON COLUMN tb_asistencia_diaria.minutos_he_compensatorio IS
    'Minutos autorizados de horas extra tomadas como compensatorio en la fecha.';
COMMENT ON COLUMN tb_asistencia_diaria.he_compensatorio_solicitud_id IS
    'Solicitud compensatoria aprobada que justifica minutos en esta fecha.';
