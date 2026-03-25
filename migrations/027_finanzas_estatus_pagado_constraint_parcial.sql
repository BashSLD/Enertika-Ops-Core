-- Migración 027: Finanzas — estatus PAGADO + constraint parcial comprobantes
-- Agrega 'PAGADO' al CHECK de tb_bom_autorizaciones y convierte
-- uq_comprobante_duplicado en índice parcial que excluye origen BOM.

-- 1. Actualizar CHECK constraint de tb_bom_autorizaciones para incluir PAGADO
ALTER TABLE tb_bom_autorizaciones
    DROP CONSTRAINT tb_bom_autorizaciones_estatus_check;

ALTER TABLE tb_bom_autorizaciones
    ADD CONSTRAINT tb_bom_autorizaciones_estatus_check
    CHECK (estatus IN (
        'PENDIENTE',
        'AUTORIZADO_OBRA',
        'AUTORIZADO_DIRECCION',
        'AUTORIZADO_FINANZAS',
        'RECHAZADO',
        'PAGADO'
    ));

-- 2. Reemplazar unique constraint por índice parcial
--    Solo aplica a comprobantes de origen COMPRAS (id_bom_pago IS NULL).
--    Los comprobantes BOM pueden compartir fecha/beneficiario/monto sin conflicto.
ALTER TABLE tb_comprobantes_pago
    DROP CONSTRAINT uq_comprobante_duplicado;

CREATE UNIQUE INDEX uq_comprobante_duplicado_no_bom
    ON tb_comprobantes_pago (fecha_pago, beneficiario_orig, monto)
    WHERE id_bom_pago IS NULL;
