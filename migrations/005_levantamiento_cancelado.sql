-- ============================================================
-- Migration 005: Estado "Cancelado" para Levantamientos
-- Descripcion: Agrega el estado "cancelado" al catalogo de
--              estatus de levantamientos con grupo_kanban propio
--              para excluirlo del Kanban y mostrarlo solo en
--              la vista lista (tab Cancelados).
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM tb_cat_estatus_levantamiento WHERE codigo = 'cancelado'
    ) THEN
        INSERT INTO tb_cat_estatus_levantamiento
            (nombre, codigo, descripcion, color_hex, orden_kanban, grupo_kanban, es_estatus_final, activo)
        VALUES
            ('Cancelado', 'cancelado',
             'El levantamiento fue cancelado. La oportunidad asociada tambien queda cancelada.',
             '#ef4444', 8, 'cancelado', true, true);

        RAISE NOTICE 'Estado cancelado creado en tb_cat_estatus_levantamiento';
    ELSE
        RAISE NOTICE 'Estado cancelado ya existe, se omite la insercion';
    END IF;
END
$$;
