-- Migration 013: Final approver config + new BOM statuses
-- Idempotent

-- Add final approver config (if not exists)
INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES ('bom_aprobador_final_id', '', 'string', 'UUID del usuario aprobador final del BOM')
ON CONFLICT (clave) DO NOTHING;

-- Add new statuses to the enum if it exists as an enum type
-- If estatus is a plain TEXT/VARCHAR this block is a no-op
DO $$ BEGIN
    ALTER TYPE estatus_bom ADD VALUE IF NOT EXISTS 'EN_REVISION_FINAL';
    ALTER TYPE estatus_bom ADD VALUE IF NOT EXISTS 'APROBADO_FINAL';
EXCEPTION WHEN undefined_object THEN NULL;
END $$;
