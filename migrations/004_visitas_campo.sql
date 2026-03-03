-- ==============================================================
-- migrations/004_visitas_campo.sql
-- Módulo Visita de Campo: Viáticos Centralizados con Prorrateo
--
-- Crea 4 tablas nuevas + índices, todas idempotentes.
-- Ejecutar ANTES del despliegue del código que las consume.
-- ==============================================================

-- 1. Entidad principal de la visita
CREATE TABLE IF NOT EXISTS tb_visitas_campo (
    id_visita    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre       TEXT,
    fecha_inicio TIMESTAMP WITH TIME ZONE NOT NULL,
    fecha_fin    TIMESTAMP WITH TIME ZONE NOT NULL,
    creado_por_id UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at   TIMESTAMP WITH TIME ZONE DEFAULT now()
);

COMMENT ON TABLE tb_visitas_campo IS
    'Agrupa N levantamientos de sitio visitados en un mismo viaje de campo.';

-- 2. Pivot levantamientos ↔ visita
CREATE TABLE IF NOT EXISTS tb_visita_campo_levantamientos (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_visita        UUID NOT NULL REFERENCES tb_visitas_campo(id_visita) ON DELETE CASCADE,
    id_levantamiento UUID NOT NULL REFERENCES tb_levantamientos(id_levantamiento) ON DELETE CASCADE,
    CONSTRAINT uq_visita_lev UNIQUE (id_visita, id_levantamiento)
);

-- 3. Viáticos centralizados de la visita
CREATE TABLE IF NOT EXISTS tb_visita_campo_viaticos (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_visita     UUID NOT NULL REFERENCES tb_visitas_campo(id_visita) ON DELETE CASCADE,
    usuario_id    UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    concepto      TEXT NOT NULL,
    monto         NUMERIC(12,2) NOT NULL CHECK (monto > 0),
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT now(),
    created_by_id UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL
);

-- 4. Historial de envíos de la visita
CREATE TABLE IF NOT EXISTS tb_visita_campo_envios (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_visita         UUID NOT NULL REFERENCES tb_visitas_campo(id_visita) ON DELETE CASCADE,
    enviado_por_id    UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    enviado_por_nombre TEXT NOT NULL,
    fecha_envio       TIMESTAMP WITH TIME ZONE DEFAULT now(),
    to_destinatarios  TEXT[],
    cc_destinatarios  TEXT[],
    snapshot          JSONB DEFAULT '{}',
    total_monto       NUMERIC(12,2) NOT NULL,
    estatus           VARCHAR(20) DEFAULT 'enviado' CHECK (estatus IN ('enviado', 'error')),
    error_detalle     TEXT
);

COMMENT ON COLUMN tb_visita_campo_envios.snapshot IS
    'JSON con {levantamientos:[], viaticos:[], prorrateo:{id_lev: monto}}';

-- Índices
CREATE INDEX IF NOT EXISTS idx_vcl_visita
    ON tb_visita_campo_levantamientos(id_visita);

CREATE INDEX IF NOT EXISTS idx_vcl_levantamiento
    ON tb_visita_campo_levantamientos(id_levantamiento);

CREATE INDEX IF NOT EXISTS idx_vcv_visita
    ON tb_visita_campo_viaticos(id_visita);

CREATE INDEX IF NOT EXISTS idx_vce_visita
    ON tb_visita_campo_envios(id_visita);
