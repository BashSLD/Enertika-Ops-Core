-- Migración 022: Ampliar tipo de columna estatus en tb_comprobantes_pago
-- El campo estatus era VARCHAR(20) pero PARCIALMENTE_FACTURADO tiene 22 caracteres.
-- Se amplía a VARCHAR(30) para dar holgura.

ALTER TABLE tb_comprobantes_pago
    ALTER COLUMN estatus TYPE VARCHAR(30);
