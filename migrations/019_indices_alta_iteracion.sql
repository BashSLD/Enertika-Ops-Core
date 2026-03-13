-- Migración 019: Índices para consulta de clientes con alta iteración de actualizaciones
-- Optimiza la query de alta_iteracion en reportes de simulación.
-- Sin estos índices, la query hace full scan de tb_oportunidades dos veces.

-- Índice para filtrar/unir por cliente
CREATE INDEX IF NOT EXISTS idx_oportunidades_cliente_id
    ON tb_oportunidades(cliente_id)
    WHERE cliente_id IS NOT NULL;

-- Índice compuesto para el patrón exacto: cliente + tipo de solicitud
CREATE INDEX IF NOT EXISTS idx_oportunidades_cliente_tipo
    ON tb_oportunidades(cliente_id, id_tipo_solicitud)
    WHERE cliente_id IS NOT NULL;
