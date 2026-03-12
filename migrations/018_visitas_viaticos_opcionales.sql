-- 018_visitas_viaticos_opcionales.sql
-- Agrega columna para marcar visitas sin viáticos de viaje
-- (visitas locales, misma jornada, etc.)

ALTER TABLE tb_visitas_campo
    ADD COLUMN IF NOT EXISTS viaticos_opcionales BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN tb_visitas_campo.viaticos_opcionales IS
    'Cuando es TRUE, la visita no genera viáticos de viaje. '
    'El correo se envía sin tabla de viáticos ni prorrateo.';
