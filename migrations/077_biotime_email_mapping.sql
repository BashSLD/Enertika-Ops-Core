-- Agrega metadatos para mapear empleados BioTime contra usuarios ECO por correo.

ALTER TABLE tb_biotime_empleado_map
    ADD COLUMN IF NOT EXISTS biotime_email VARCHAR(255);

ALTER TABLE tb_biotime_empleado_map
    ADD COLUMN IF NOT EXISTS match_source VARCHAR(30);

ALTER TABLE tb_biotime_empleado_map
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

DO $$
BEGIN
    ALTER TABLE tb_biotime_empleado_map
        ADD CONSTRAINT ck_biotime_map_match_source
        CHECK (match_source IS NULL OR match_source IN ('email'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_biotime_map_email_active
    ON tb_biotime_empleado_map (LOWER(biotime_email))
    WHERE activo = true AND biotime_email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_biotime_checks_unmapped_emp_time
    ON tb_biotime_checks (biotime_emp_code, check_time)
    WHERE usuario_id IS NULL;
