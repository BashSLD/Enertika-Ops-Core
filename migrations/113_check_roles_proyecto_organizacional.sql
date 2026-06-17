-- Migracion 113: CHECK constraints para rol_proyecto y rol_organizacional
-- Defensa en BD contra valores invalidos que no pasen por el service (scripts, SQL directo).
-- 2026-06-17

DO $$ BEGIN
    ALTER TABLE tb_proyecto_usuarios
        ADD CONSTRAINT chk_rol_proyecto_valido
        CHECK (rol_proyecto IN (
            'ingeniero_asignado',
            'coordinador_obra',
            'encargado',
            'responsable_ingenieria',
            'responsable_construccion'
        ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE tb_usuarios
        ADD CONSTRAINT chk_rol_organizacional_valido
        CHECK (rol_organizacional IS NULL OR rol_organizacional IN (
            '',
            'jefe_comercial',
            'jefe_ingenieria',
            'jefe_construccion',
            'director'
        ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
