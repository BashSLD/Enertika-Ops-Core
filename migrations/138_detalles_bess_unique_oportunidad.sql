-- Agrega UNIQUE sobre tb_detalles_bess.id_oportunidad: hoy la tabla solo tiene
-- PK en id + FK simple a tb_oportunidades, sin garantizar 1:1. create_bess_details
-- hace INSERT plano sin ON CONFLICT; sin este constraint una futura doble inserción
-- duplicaría la fila y rompería la paginacion de get_oportunidades_filtradas
-- (LEFT JOIN tb_detalles_bess + COUNT(*) OVER()). Ver memory/simulacion_reportes_sum_distinct_bug.md
-- (auditoria SQL modulo simulacion, 2026-07-07).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_detalles_bess_oportunidad'
          AND conrelid = 'tb_detalles_bess'::regclass
    ) THEN
        ALTER TABLE tb_detalles_bess
            ADD CONSTRAINT uq_detalles_bess_oportunidad UNIQUE (id_oportunidad);
    END IF;
END $$;
