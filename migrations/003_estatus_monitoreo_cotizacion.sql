-- Migración 003: Nuevo estatus "Monitoreo de Cotización" para el módulo Simulación
-- Ejecutar ANTES de desplegar el código que depende de este cambio.
-- Idempotente: el INSERT solo ocurre si el estatus no existe aún.

INSERT INTO tb_cat_estatus_oportunidades
    (nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final)
SELECT
    'Monitoreo de Cotización',
    'Simulación entregada al equipo comercial; cotización en seguimiento activo con el cliente.',
    '#8B5CF6',
    true,
    'SIMULACION',
    false,
    false
WHERE NOT EXISTS (
    SELECT 1 FROM tb_cat_estatus_oportunidades
    WHERE LOWER(nombre) = 'monitoreo de cotización'
      AND modulo_aplicable = 'SIMULACION'
);
