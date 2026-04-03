-- Migración 029: Módulo Calculadora Pólizas
-- Sub-herramienta de O&M. Hereda permisos del módulo oym.
-- No se registra en tb_cat_modulos.

-- ============================================================
-- 1. CATÁLOGO DE PLANTAS
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_calculadora_plantas (
    id              TEXT PRIMARY KEY,           -- MX-01, MX-03, etc.
    nombre          TEXT NOT NULL,
    zona            TEXT NOT NULL,
    potencia_kw     NUMERIC(10,2),
    num_paneles     INTEGER,
    activa          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 2. PRECIOS POR ZONA (Mtto Preventivo de Paneles)
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_calculadora_precios_zona (
    zona                    TEXT PRIMARY KEY,
    precio_por_panel_mxp    NUMERIC(10,2) NOT NULL,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO tb_calculadora_precios_zona (zona, precio_por_panel_mxp) VALUES
    ('Querétaro',    30),
    ('Veracruz',     35),
    ('SLP',          42),
    ('BCsur',        60),
    ('Jalisco',      60),
    ('Guanajuato',   60),
    ('Michoacán',    50),
    ('Sonora',       60),
    ('Hidalgo',      50),
    ('CDMX',         60),
    ('Colima',       60),
    ('Tabasco',     100),
    ('Campeche',     80),
    ('Nuevo León',  130),
    ('Quintana Roo', 60),
    ('Puebla',       38)
ON CONFLICT (zona) DO NOTHING;

-- ============================================================
-- 3. PRECIOS WATTABIT (SAS Monitoreo por rangos de kWp)
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_calculadora_wattabit (
    id                  SERIAL PRIMARY KEY,
    nombre              TEXT NOT NULL,
    rango_min_kwp       NUMERIC(10,2) NOT NULL,
    rango_max_kwp       NUMERIC(10,2) NOT NULL,
    precio_anual_mxp    NUMERIC(10,2) NOT NULL,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO tb_calculadora_wattabit (nombre, rango_min_kwp, rango_max_kwp, precio_anual_mxp) VALUES
    ('Fv Home',    0,      10,    405),
    ('Fv Basic',   10.01, 100,  1350),
    ('Fv Advance', 100.01, 500,  2430),
    ('FV Pro',     500.01, 1500, 4050)
ON CONFLICT DO NOTHING;

-- ============================================================
-- 4. COSTOS FIJOS (editables por Manager)
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_calculadora_costos_fijos (
    concepto    TEXT PRIMARY KEY,
    valor       NUMERIC(14,4) NOT NULL,
    notas       TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO tb_calculadora_costos_fijos (concepto, valor, notas) VALUES
    ('mtto_correctivo',                13200,  'Personal 3,200 + Extras 2,000 + Viáticos 8,000 MXP'),
    ('mtto_diagnostico_estandar',      10000,  'Póliza Estándar — visita diagnóstico'),
    ('internet_anual',                  6000,  '500 MXP/mes × 12'),
    ('gestion_energetica_por_panel',      20,  'Acordado con Guillermo'),
    ('iva',                             0.16,  'IVA vigente'),
    ('utilidad_default',                0.30,  'Default editable por usuario en cada cálculo'),
    ('incremento_anual',                0.03,  'Proyección inflación años 1-5')
ON CONFLICT (concepto) DO NOTHING;

-- ============================================================
-- 5. COTIZACIONES (historial de cálculos)
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_calculadora_cotizaciones (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planta_id          TEXT,                        -- referencia soft (sin FK — compatibilidad Supabase TEXT PK)
    nombre_planta      TEXT NOT NULL,               -- snapshot en caso de que la planta se elimine
    tipo_poliza        TEXT NOT NULL CHECK (tipo_poliza IN ('premium', 'estandar')),
    utilidad           NUMERIC(5,4) NOT NULL,
    sub_total          NUMERIC(12,2) NOT NULL,
    sub_total_utilidad NUMERIC(12,2) NOT NULL,
    total_final        NUMERIC(12,2) NOT NULL,
    resultado_json     JSONB NOT NULL,              -- snapshot completo del cálculo
    creado_por         UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cotizaciones_creado_por ON tb_calculadora_cotizaciones(creado_por);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_created_at ON tb_calculadora_cotizaciones(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_planta ON tb_calculadora_cotizaciones(planta_id);
