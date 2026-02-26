-- =============================================================
-- Migración 002: Responsable de levantamiento
-- Fecha: 2026-02-25
-- Descripción: Agrega columna es_responsable a tb_levantamiento_asignaciones
--              y constraint UNIQUE requerido para upsert de responsable.
--
-- Ejecutar ANTES de desplegar código que use:
--   - assign_modal (radio responsable)
--   - get_responsable_asignado / update_responsable en db_service.py
--   - auto-asignación al reagendar
-- =============================================================

-- 1. Columna es_responsable
ALTER TABLE tb_levantamiento_asignaciones
ADD COLUMN IF NOT EXISTS es_responsable BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. UNIQUE constraint requerido por ON CONFLICT en update_responsable
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'tb_levantamiento_asignaciones'::regclass
          AND conname  = 'uq_lev_asig_lev_tecnico'
    ) THEN
        ALTER TABLE tb_levantamiento_asignaciones
        ADD CONSTRAINT uq_lev_asig_lev_tecnico UNIQUE (id_levantamiento, tecnico_id);
    END IF;
END $$;
