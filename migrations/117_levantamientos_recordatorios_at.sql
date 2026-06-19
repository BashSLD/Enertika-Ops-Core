-- Persiste timestamp del último recordatorio enviado por tipo.
-- Reemplaza los dicts en memoria del worker (no sobrevivían redeploysen).
ALTER TABLE tb_levantamientos
  ADD COLUMN IF NOT EXISTS recordatorio_pendiente_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recordatorio_agendado_at         TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recordatorio_en_proceso_at       TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recordatorio_completado_at       TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recordatorio_sin_asignar_at      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recordatorio_sin_asignar_jefe_id UUID;
