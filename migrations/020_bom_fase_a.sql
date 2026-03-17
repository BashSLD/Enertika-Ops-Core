-- Migration 020: BOM Fase A — Flujo 4 aprobadores
-- Agrega EN_REVISION_OBRA, renombra APROBADO→APROBADO_CONST,
-- corrige constraints que faltaban (EN_REVISION_FINAL, APROBADO_FINAL, tipos FINAL).
-- Idempotente: DROP IF EXISTS + ADD.

-- 1. Reemplazar CHECK de tb_bom.estatus con todos los valores correctos
ALTER TABLE tb_bom DROP CONSTRAINT IF EXISTS tb_bom_estatus_check;
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_estatus_check
    CHECK (estatus = ANY (ARRAY[
        'BORRADOR',
        'EN_REVISION_ING', 'APROBADO_ING',
        'EN_REVISION_OBRA',
        'EN_REVISION_CONST', 'APROBADO_CONST',
        'EN_REVISION_FINAL', 'APROBADO_FINAL',
        'CANCELADO'
    ]));

-- 2. Reemplazar CHECK de tb_bom_aprobaciones.tipo con todos los valores
ALTER TABLE tb_bom_aprobaciones DROP CONSTRAINT IF EXISTS tb_bom_aprobaciones_tipo_check;
ALTER TABLE tb_bom_aprobaciones ADD CONSTRAINT tb_bom_aprobaciones_tipo_check
    CHECK (tipo = ANY (ARRAY[
        'ENVIO_REVISION_ING',  'APROBACION_ING',  'RECHAZO_ING',
        'ENVIO_REVISION_OBRA', 'APROBACION_OBRA', 'RECHAZO_OBRA',
        'ENVIO_REVISION_CONST','APROBACION_CONST','RECHAZO_CONST',
        'DEVOLUCION_BORRADOR', 'CANCELACION',
        'SOLICITUD_MODIFICACION', 'APROBACION_MODIFICACION',
        'ENVIO_REVISION_FINAL', 'APROBACION_FINAL', 'RECHAZO_FINAL'
    ]));

-- 3. Nuevas columnas de fecha en tb_bom
ALTER TABLE tb_bom
    ADD COLUMN IF NOT EXISTS fecha_envio_obra       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS fecha_aprobacion_obra  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS fecha_envio_final      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS fecha_aprobacion_final TIMESTAMPTZ;
