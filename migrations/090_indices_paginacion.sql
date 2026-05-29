-- migrations/090_indices_paginacion.sql
-- Índices para mejorar performance de LEFT JOINs en listados comercial/simulación

CREATE INDEX IF NOT EXISTS idx_levantamientos_id_oportunidad
    ON tb_levantamientos (id_oportunidad);

CREATE INDEX IF NOT EXISTS idx_proyectos_gate_id_oportunidad
    ON tb_proyectos_gate (id_oportunidad);

CREATE INDEX IF NOT EXISTS idx_proyectos_gate_created_at
    ON tb_proyectos_gate (id_oportunidad, created_at DESC NULLS LAST);
