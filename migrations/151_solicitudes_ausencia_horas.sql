-- Columnas opcionales hora_llegada/hora_salida en tb_solicitudes_ausencia para permisos horarios
-- (llegar tarde / salir temprano). Nulas por defecto, sin backfill; la obligatoriedad condicional
-- por tipo de catálogo se valida en modules/vacaciones/service.py, no aquí.

ALTER TABLE tb_solicitudes_ausencia ADD COLUMN IF NOT EXISTS hora_llegada time;
ALTER TABLE tb_solicitudes_ausencia ADD COLUMN IF NOT EXISTS hora_salida time;

DO $$ BEGIN
  ALTER TABLE tb_solicitudes_ausencia
    ADD CONSTRAINT ck_solicitudes_horas_excluyentes
    CHECK (NOT (hora_llegada IS NOT NULL AND hora_salida IS NOT NULL));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
