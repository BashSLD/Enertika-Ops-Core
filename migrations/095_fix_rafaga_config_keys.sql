-- Migración 095: corregir claves de ráfaga en tb_configuracion_global
-- metrics_service.py lee UMBRAL_RAFAGA_USUARIO_OPS y VENTANA_RAFAGA_USUARIO_MIN;
-- la BD tenía RAFAGA_USUARIO_MAX (nunca leída). Se renombra y se agrega la ventana.

-- 1. Renombrar RAFAGA_USUARIO_MAX → UMBRAL_RAFAGA_USUARIO_OPS (idempotente)
UPDATE tb_configuracion_global
SET clave       = 'UMBRAL_RAFAGA_USUARIO_OPS',
    descripcion = 'Máximo de oportunidades distintas que un usuario puede registrar en la ventana de ráfaga antes de marcar como ráfaga'
WHERE clave = 'RAFAGA_USUARIO_MAX'
  AND NOT EXISTS (
      SELECT 1 FROM tb_configuracion_global WHERE clave = 'UMBRAL_RAFAGA_USUARIO_OPS'
  );

-- 2. Insertar ventana temporal de ráfaga por usuario (idempotente)
INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'VENTANA_RAFAGA_USUARIO_MIN', '10',
       'Ventana en minutos para detectar ráfaga de registros por usuario', 'integer'
WHERE NOT EXISTS (
    SELECT 1 FROM tb_configuracion_global WHERE clave = 'VENTANA_RAFAGA_USUARIO_MIN'
);
