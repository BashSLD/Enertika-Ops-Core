-- 083_horas_extra_solicitud.sql
-- Idempotente: safe to run multiple times

-- Ampliar estados: pendiente -> solicitado -> aprobado | omitido
ALTER TABLE tb_asistencia_diaria
  DROP CONSTRAINT IF EXISTS ck_horas_extra_estado;

ALTER TABLE tb_asistencia_diaria
  ADD CONSTRAINT ck_horas_extra_estado
  CHECK (horas_extra_estado IN ('pendiente', 'solicitado', 'aprobado', 'omitido'));

-- Motivo que el empleado escribe al solicitar aprobacion
ALTER TABLE tb_asistencia_diaria
  ADD COLUMN IF NOT EXISTS motivo_solicitud TEXT;
