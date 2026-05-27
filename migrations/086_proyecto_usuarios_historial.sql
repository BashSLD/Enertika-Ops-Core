-- Permite historial de asignaciones de equipo y mantiene unicidad solo para asignaciones activas.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tb_proyecto_usuarios
        WHERE activo = TRUE
        GROUP BY id_proyecto, rol_proyecto, area
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Existen asignaciones activas duplicadas por proyecto, rol y area en tb_proyecto_usuarios';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_proyecto_usuarios
        WHERE activo = TRUE
        GROUP BY id_proyecto, id_usuario, area
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Existen asignaciones activas duplicadas por proyecto, usuario y area en tb_proyecto_usuarios';
    END IF;
END $$;

ALTER TABLE tb_proyecto_usuarios
DROP CONSTRAINT IF EXISTS uq_proyecto_usuario_area;

DROP INDEX IF EXISTS uq_proyecto_usuario_area;

CREATE UNIQUE INDEX IF NOT EXISTS uq_proyecto_usuario_area_activo
ON tb_proyecto_usuarios (id_proyecto, id_usuario, area)
WHERE activo = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_proyecto_rol_area_activo
ON tb_proyecto_usuarios (id_proyecto, rol_proyecto, area)
WHERE activo = TRUE;
