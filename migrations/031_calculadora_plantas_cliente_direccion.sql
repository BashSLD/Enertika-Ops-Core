-- Migración 031: Agregar cliente y direccion a tb_calculadora_plantas
-- Campos opcionales para personalizar la propuesta PDF de póliza O&M.

ALTER TABLE tb_calculadora_plantas
    ADD COLUMN IF NOT EXISTS cliente   TEXT,
    ADD COLUMN IF NOT EXISTS direccion TEXT;
