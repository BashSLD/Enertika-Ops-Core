-- Optimización de rendimiento para consultas del módulo comercial
-- Crea índices funcionales para mejorar la velocidad de filtrado por pestañas

-- 1. Índice para status_global (usado en TODAS las pestañas)
-- Permite búsqueda rápida con LOWER(status_global)
CREATE INDEX IF NOT EXISTS idx_oportunidades_status_lower 
ON tb_oportunidades(LOWER(status_global));

-- 2. Índice para tipo_solicitud (usado en pestaña Activos y Levantamientos)
-- Permite búsqueda rápida con LOWER(tipo_solicitud)
CREATE INDEX IF NOT EXISTS idx_oportunidades_tipo_solicitud_lower 
ON tb_oportunidades(LOWER(tipo_solicitud));

-- 3. Índice para la columna de fecha (usado en ORDER BY)
CREATE INDEX IF NOT EXISTS idx_oportunidades_fecha_solicitud 
ON tb_oportunidades(fecha_solicitud DESC);

-- 4. Índices para las columnas de JOIN (si no existen)
-- Acelera los LEFT JOIN con tb_usuarios
CREATE INDEX IF NOT EXISTS idx_oportunidades_responsable_sim 
ON tb_oportunidades(responsable_simulacion_id);

CREATE INDEX IF NOT EXISTS idx_oportunidades_creado_por 
ON tb_oportunidades(creado_por_id);

-- 5. Índice compuesto para la pestaña de Levantamientos
-- Optimiza la query que filtra por tipo_solicitud Y status_global
CREATE INDEX IF NOT EXISTS idx_levantamientos_status 
ON tb_oportunidades(LOWER(tipo_solicitud), LOWER(status_global))
WHERE LOWER(tipo_solicitud) = 'solicitud de levantamiento';

-- Verificar índices creados
SELECT 
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'tb_oportunidades'
ORDER BY indexname;
