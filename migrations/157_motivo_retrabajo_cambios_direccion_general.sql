-- Migration 157: Nuevo motivo de retrabajo "Cambios Direccion General"
-- Idempotente

INSERT INTO tb_cat_motivos_retrabajo (codigo, nombre, descripcion, orden)
VALUES (
    'CAMBIO_DIRECCION_GENERAL',
    'Cambios Direccion General',
    'Cambios solicitados por Direccion General',
    8
)
ON CONFLICT (codigo) DO NOTHING;
