-- 079_horas_extra_aprobacion.sql
-- Idempotente: safe to run multiple times

-- Columna de estado en asistencia diaria
ALTER TABLE tb_asistencia_diaria
  ADD COLUMN IF NOT EXISTS horas_extra_estado VARCHAR(20) NOT NULL DEFAULT 'pendiente';

-- Constraint idempotente: DROP antes de ADD para soportar re-runs
ALTER TABLE tb_asistencia_diaria
  DROP CONSTRAINT IF EXISTS ck_horas_extra_estado;

ALTER TABLE tb_asistencia_diaria
  ADD CONSTRAINT ck_horas_extra_estado
  CHECK (horas_extra_estado IN ('pendiente', 'aprobado'));

-- Tabla de aprobaciones
CREATE TABLE IF NOT EXISTS tb_horas_extra_aprobaciones (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asistencia_id     UUID NOT NULL REFERENCES tb_asistencia_diaria(id) ON DELETE CASCADE,
    aprobador_id      UUID NOT NULL REFERENCES tb_usuarios(id_usuario),
    minutos_aprobados INTEGER NOT NULL,
    comentario        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_he_min_aprobados CHECK (minutos_aprobados >= 30),
    CONSTRAINT uq_he_aprobacion_asistencia UNIQUE (asistencia_id)
);

CREATE INDEX IF NOT EXISTS idx_he_aprobaciones_aprobador
    ON tb_horas_extra_aprobaciones (aprobador_id);
