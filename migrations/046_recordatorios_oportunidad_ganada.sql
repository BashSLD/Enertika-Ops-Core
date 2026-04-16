-- Migración 046: Recordatorios automáticos para oportunidades ganadas
--
-- Objetivo:
-- - Guardar estado y conteo de recordatorios fuera de tb_oportunidades.
-- - Permitir envío automático cada 48h hasta creación de proyecto.

CREATE TABLE IF NOT EXISTS tb_recordatorios_oportunidad_ganada (
    id_oportunidad UUID PRIMARY KEY REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE,
    recordatorios_enviados INTEGER NOT NULL DEFAULT 0,
    ultimo_recordatorio_at TIMESTAMPTZ NULL,
    proximo_recordatorio_at TIMESTAMPTZ NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_recordatorios_enviados_non_negative CHECK (recordatorios_enviados >= 0)
);

CREATE INDEX IF NOT EXISTS idx_recordatorios_op_ganada_activo_proximo
    ON tb_recordatorios_oportunidad_ganada (activo, proximo_recordatorio_at);

CREATE TABLE IF NOT EXISTS tb_recordatorios_oportunidad_ganada_log (
    id BIGSERIAL PRIMARY KEY,
    id_oportunidad UUID NOT NULL REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE,
    numero_recordatorio INTEGER NOT NULL,
    incluye_director BOOLEAN NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_recordatorios_log_numero_positive CHECK (numero_recordatorio > 0),
    CONSTRAINT chk_recordatorios_log_status CHECK (status IN ('ENVIADO', 'NO_ENVIADO'))
);

CREATE INDEX IF NOT EXISTS idx_recordatorios_op_ganada_log_oportunidad
    ON tb_recordatorios_oportunidad_ganada_log (id_oportunidad, created_at DESC);

-- Backfill inicial: oportunidades actualmente Ganadas, sin proyecto, con correo enviado.
INSERT INTO tb_recordatorios_oportunidad_ganada (
    id_oportunidad,
    recordatorios_enviados,
    ultimo_recordatorio_at,
    proximo_recordatorio_at,
    activo,
    created_at,
    updated_at
)
SELECT
    o.id_oportunidad,
    0,
    NULL,
    NOW() + INTERVAL '48 hours',
    TRUE,
    NOW(),
    NOW()
FROM tb_oportunidades o
LEFT JOIN tb_proyectos_gate p
    ON p.id_oportunidad = o.id_oportunidad
WHERE p.id_proyecto IS NULL
  AND o.email_enviado = TRUE
  AND o.id_estatus_global = (
      SELECT id
      FROM tb_cat_estatus_oportunidades
      WHERE LOWER(nombre) = 'ganada'
      LIMIT 1
  )
ON CONFLICT (id_oportunidad) DO NOTHING;
