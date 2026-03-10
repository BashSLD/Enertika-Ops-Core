-- migrations/008_reporte_semanal_config.sql
-- Agrega configuración para el reporte semanal automatizado.
-- Idempotente: ON CONFLICT DO NOTHING

INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES (
    'reporte_semanal_destinatarios',
    '',
    'string',
    'Emails separados por coma que reciben el reporte semanal de actividad de ECO. Ejemplo: gerencia@empresa.mx,ventas@empresa.mx'
)
ON CONFLICT (clave) DO NOTHING;
