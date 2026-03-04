-- Migración 007: Simulaciones Adicionales por Oportunidad
-- Permite registrar N simulaciones extra realizadas para una misma oportunidad.
-- Cada simulación adicional es un ticket de trabajo independiente para efectos de KPIs.
-- La simulación principal (#1) sigue almacenada en tb_oportunidades.

CREATE TABLE IF NOT EXISTS tb_simulaciones_adicionales (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_oportunidad            UUID NOT NULL REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE,
    numero                    INTEGER NOT NULL,                -- 2, 3, 4... (la principal es siempre #1)
    potencia_cierre_fv_kwp    NUMERIC,                         -- opcional si tecnología es BESS puro
    capacidad_cierre_bess_kwh NUMERIC,                         -- requerida si tecnología es BESS
    monto_cierre_usd          NUMERIC,                         -- opcional
    kpi_status_interno        VARCHAR(30),                     -- heredado del padre al momento del cierre
    kpi_status_compromiso     VARCHAR(30),                     -- heredado del padre al momento del cierre
    fecha_entrega             TIMESTAMPTZ,                     -- igual que fecha_entrega_simulacion del padre
    creado_en                 TIMESTAMPTZ DEFAULT now(),
    UNIQUE (id_oportunidad, numero)
);

CREATE INDEX IF NOT EXISTS idx_sim_adicionales_op
    ON tb_simulaciones_adicionales(id_oportunidad);
