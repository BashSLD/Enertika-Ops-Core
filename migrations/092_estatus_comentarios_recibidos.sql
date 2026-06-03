-- Migración 092: nuevo estatus 'Comentarios Recibidos' + columna orden + parámetros enforcement de flujo

-- 1. Columna orden en catálogo de estatus
ALTER TABLE tb_cat_estatus_oportunidades ADD COLUMN IF NOT EXISTS orden INTEGER;

-- 2. Nuevo estatus intermedio de revisión
INSERT INTO tb_cat_estatus_oportunidades
    (nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final)
SELECT
    'Comentarios Recibidos',
    'Dirección devolvió comentarios por correo; Simulación retrabaja antes de entregar',
    '#F97316',
    true,
    'SIMULACION',
    false,
    false
WHERE NOT EXISTS (
    SELECT 1 FROM tb_cat_estatus_oportunidades WHERE nombre = 'Comentarios Recibidos'
);

-- 3. Backfill de orden para todos los estatus (idempotente — UPDATE SET)
UPDATE tb_cat_estatus_oportunidades
SET orden = CASE nombre
    WHEN 'Pendiente'              THEN 1
    WHEN 'En Proceso'             THEN 2
    WHEN 'En Revisión'            THEN 3
    WHEN 'Comentarios Recibidos'  THEN 4
    WHEN 'Entregado'              THEN 5
    WHEN 'Monitoreo de Cotización' THEN 6
    WHEN 'Ganada'                 THEN 7
    WHEN 'Cancelado'              THEN 8
    WHEN 'Perdido'                THEN 9
    ELSE orden
END;

-- 4. Parámetros de configuración del enforcement de flujo (idempotentes)
INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'MIN_MINUTOS_ENTRE_ESTATUS', '1',
       'Gap mínimo en minutos entre cambios de estatus consecutivos', 'integer'
WHERE NOT EXISTS (SELECT 1 FROM tb_configuracion_global WHERE clave = 'MIN_MINUTOS_ENTRE_ESTATUS');

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'DESCONTAR_TIEMPO_REVISION_SLA', 'false',
       'Si true, descuenta tiempo en En Revisión del KPI de entrega (activar cuando Dirección use el sistema)', 'boolean'
WHERE NOT EXISTS (SELECT 1 FROM tb_configuracion_global WHERE clave = 'DESCONTAR_TIEMPO_REVISION_SLA');

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'UMBRAL_LAG_NOTIFICACION', '1440',
       'Minutos máximos entre fecha_cambio_real y fecha_creacion para enviar correo (24h = 1440)', 'integer'
WHERE NOT EXISTS (SELECT 1 FROM tb_configuracion_global WHERE clave = 'UMBRAL_LAG_NOTIFICACION');

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'VENTANA_BLOQUE_REGISTRO_MIN', '2',
       'Ventana en minutos para detectar registro en bloque por oportunidad', 'integer'
WHERE NOT EXISTS (SELECT 1 FROM tb_configuracion_global WHERE clave = 'VENTANA_BLOQUE_REGISTRO_MIN');

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'RAFAGA_USUARIO_MAX', '10',
       'Máximo de oportunidades que un usuario puede registrar en 10 minutos antes de marcar como ráfaga', 'integer'
WHERE NOT EXISTS (SELECT 1 FROM tb_configuracion_global WHERE clave = 'RAFAGA_USUARIO_MAX');

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'ESTATUS_HITO_CORREO', 'Entregado',
       'Estatus que disparan correo de notificación (separados por coma si son varios)', 'string'
WHERE NOT EXISTS (SELECT 1 FROM tb_configuracion_global WHERE clave = 'ESTATUS_HITO_CORREO');
