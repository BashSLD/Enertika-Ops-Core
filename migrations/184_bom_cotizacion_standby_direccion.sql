-- 184: Standby de Direccion + confirmacion de vigencia por Compras sobre
-- tb_bom_cotizacion_aprobaciones (plan _Planes_Activos/PLAN_STANDBY_DIRECCION_VIGENCIA_COMPRAS_BOM.md).
-- Agrega los estados EN_STANDBY / PENDIENTE_VIGENCIA_COMPRAS, sus columnas de soporte,
-- y extiende el indice unico de aprobacion activa para que los cuente.

ALTER TABLE tb_bom_cotizacion_aprobaciones
    DROP CONSTRAINT IF EXISTS ck_bom_cot_aprob_estatus;

ALTER TABLE tb_bom_cotizacion_aprobaciones
    ADD CONSTRAINT ck_bom_cot_aprob_estatus CHECK (estatus IN (
        'PENDIENTE_DIRECCION',
        'APROBADA',
        'RECHAZADA',
        'REEMPLAZADA',
        'CANCELADA_PROVEEDOR',
        'EN_STANDBY',
        'PENDIENTE_VIGENCIA_COMPRAS'
    ));

ALTER TABLE tb_bom_cotizacion_aprobaciones
    ADD COLUMN IF NOT EXISTS fecha_recordatorio DATE,
    ADD COLUMN IF NOT EXISTS motivo_standby TEXT,
    ADD COLUMN IF NOT EXISTS recordatorio_enviado_at TIMESTAMPTZ;

DROP INDEX IF EXISTS uq_bom_cot_aprob_activa;

-- Maximo una aprobacion activa (pendiente, en standby, o aprobada) por cotizacion;
-- las historicas (RECHAZADA/REEMPLAZADA/CANCELADA_PROVEEDOR) no cuentan.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_cot_aprob_activa
    ON tb_bom_cotizacion_aprobaciones (cotizacion_id)
    WHERE estatus IN (
        'PENDIENTE_DIRECCION',
        'APROBADA',
        'EN_STANDBY',
        'PENDIENTE_VIGENCIA_COMPRAS'
    );
