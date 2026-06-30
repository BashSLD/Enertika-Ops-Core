-- Solicitudes manuales de asistencia para cubrir huecos de entrada/salida BioTime.

CREATE TABLE IF NOT EXISTS tb_asistencia_solicitudes_manuales (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id          UUID NOT NULL REFERENCES tb_usuarios(id_usuario),
    fecha_laboral       DATE NOT NULL,
    solicita_entrada    BOOLEAN NOT NULL DEFAULT false,
    solicita_salida     BOOLEAN NOT NULL DEFAULT false,
    entrada_tiempo      TIMESTAMPTZ,
    salida_tiempo       TIMESTAMPTZ,
    motivo              TEXT NOT NULL,
    estado              VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    revisado_por        UUID REFERENCES tb_usuarios(id_usuario),
    comentario_revision TEXT,
    check_entrada_id    UUID,
    check_salida_id     UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_solicitud_manual_estado
        CHECK (estado IN ('pendiente', 'aprobado', 'rechazado')),
    CONSTRAINT chk_solicitud_manual_al_menos_un_check
        CHECK (solicita_entrada OR solicita_salida),
    CONSTRAINT chk_solicitud_manual_entrada_consistente
        CHECK (
            (solicita_entrada AND entrada_tiempo IS NOT NULL)
            OR (NOT solicita_entrada AND entrada_tiempo IS NULL)
        ),
    CONSTRAINT chk_solicitud_manual_salida_consistente
        CHECK (
            (solicita_salida AND salida_tiempo IS NOT NULL)
            OR (NOT solicita_salida AND salida_tiempo IS NULL)
        ),
    CONSTRAINT chk_solicitud_manual_tiempos
        CHECK (
            entrada_tiempo IS NULL
            OR salida_tiempo IS NULL
            OR salida_tiempo > entrada_tiempo
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_solicitud_manual_pendiente
    ON tb_asistencia_solicitudes_manuales (usuario_id, fecha_laboral)
    WHERE estado = 'pendiente';

CREATE UNIQUE INDEX IF NOT EXISTS uq_solicitud_manual_aprobada
    ON tb_asistencia_solicitudes_manuales (usuario_id, fecha_laboral)
    WHERE estado = 'aprobado';

CREATE INDEX IF NOT EXISTS idx_solicitud_manual_usuario_estado
    ON tb_asistencia_solicitudes_manuales (usuario_id, estado, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_solicitud_manual_estado_fecha
    ON tb_asistencia_solicitudes_manuales (estado, fecha_laboral DESC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_solicitud_manual_revisado_por
    ON tb_asistencia_solicitudes_manuales (revisado_por);

CREATE INDEX IF NOT EXISTS idx_solicitud_manual_check_entrada
    ON tb_asistencia_solicitudes_manuales (check_entrada_id)
    WHERE check_entrada_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_solicitud_manual_check_salida
    ON tb_asistencia_solicitudes_manuales (check_salida_id)
    WHERE check_salida_id IS NOT NULL;

ALTER TABLE tb_biotime_checks
    ADD COLUMN IF NOT EXISTS es_manual BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS solicitud_manual_id UUID;

CREATE INDEX IF NOT EXISTS idx_biotime_checks_solicitud_manual
    ON tb_biotime_checks (solicitud_manual_id)
    WHERE solicitud_manual_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_biotime_checks_solicitud_manual'
          AND conrelid = 'tb_biotime_checks'::regclass
    ) THEN
        ALTER TABLE tb_biotime_checks
            ADD CONSTRAINT fk_biotime_checks_solicitud_manual
            FOREIGN KEY (solicitud_manual_id)
            REFERENCES tb_asistencia_solicitudes_manuales(id)
            ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_solicitud_manual_check_entrada'
          AND conrelid = 'tb_asistencia_solicitudes_manuales'::regclass
    ) THEN
        ALTER TABLE tb_asistencia_solicitudes_manuales
            ADD CONSTRAINT fk_solicitud_manual_check_entrada
            FOREIGN KEY (check_entrada_id)
            REFERENCES tb_biotime_checks(id)
            ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_solicitud_manual_check_salida'
          AND conrelid = 'tb_asistencia_solicitudes_manuales'::regclass
    ) THEN
        ALTER TABLE tb_asistencia_solicitudes_manuales
            ADD CONSTRAINT fk_solicitud_manual_check_salida
            FOREIGN KEY (check_salida_id)
            REFERENCES tb_biotime_checks(id)
            ON DELETE SET NULL;
    END IF;
END $$;

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
VALUES
    ('ASISTENCIA_MANUAL_DIAS_RETROACTIVO', '7', 'Dias maximos para solicitud retroactiva de asistencia manual', 'integer'),
    ('ASISTENCIA_MANUAL_MAX_HORAS', '16', 'Duracion maxima permitida para una solicitud manual de asistencia', 'integer')
ON CONFLICT (clave) DO NOTHING;
