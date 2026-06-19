-- Persiste timestamp del último recordatorio enviado por tipo.
-- Reemplaza el dict en memoria del worker (no sobrevivía redeploysen).
ALTER TABLE tb_levantamientos
  ADD COLUMN IF NOT EXISTS recordatorio_pendiente_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recordatorio_agendado_at  TIMESTAMPTZ;
