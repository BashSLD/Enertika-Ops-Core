-- Migración 025: BOM Fase D — Autorizaciones de compra
-- Fecha: 2026-03-20
--
-- Cambios:
-- 1. Tabla tb_bom_autorizaciones: flujo 3 pasos (Coordinador Obra → Dirección → Finanzas)
-- 2. Índices de búsqueda por BOM, proyecto y estatus

CREATE TABLE IF NOT EXISTS tb_bom_autorizaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Relaciones
    cotizacion_id UUID NOT NULL UNIQUE REFERENCES tb_bom_cotizaciones(id) ON DELETE CASCADE,
    bom_id        UUID NOT NULL REFERENCES tb_bom(id_bom) ON DELETE CASCADE,
    proyecto_id   UUID NOT NULL REFERENCES tb_proyectos_gate(id_proyecto),

    -- Montos
    monto_total          NUMERIC(14,2) NOT NULL,
    moneda               CHAR(3) NOT NULL DEFAULT 'MXN',
    tipo_cambio_snapshot NUMERIC(10,4),

    -- Estatus del flujo
    estatus VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE'
        CHECK (estatus IN (
            'PENDIENTE',
            'AUTORIZADO_OBRA',
            'AUTORIZADO_DIRECCION',
            'AUTORIZADO_FINANZAS',
            'RECHAZADO'
        )),

    -- Paso 1: Coordinador de Obra del proyecto
    aprobador_obra_id        UUID REFERENCES tb_usuarios(id_usuario),
    fecha_aprobacion_obra    TIMESTAMPTZ,
    nota_obra                TEXT,

    -- Paso 2: Director (rol_organizacional = 'director')
    aprobador_direccion_id        UUID REFERENCES tb_usuarios(id_usuario),
    fecha_aprobacion_direccion    TIMESTAMPTZ,
    nota_direccion                TEXT,

    -- Paso 3: Admin Finanzas (módulo finanzas, Fase E)
    aprobador_finanzas_id        UUID REFERENCES tb_usuarios(id_usuario),
    fecha_aprobacion_finanzas    TIMESTAMPTZ,
    nota_finanzas                TEXT,

    -- Rechazo (cualquier paso)
    rechazado_en_paso  VARCHAR(20),
    rechazado_por      UUID REFERENCES tb_usuarios(id_usuario),
    motivo_rechazo     TEXT,
    fecha_rechazo      TIMESTAMPTZ,

    -- Auditoría
    creado_por UUID REFERENCES tb_usuarios(id_usuario),
    creado_en  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_bom_autorizaciones_bom
    ON tb_bom_autorizaciones(bom_id);

CREATE INDEX IF NOT EXISTS idx_bom_autorizaciones_proyecto
    ON tb_bom_autorizaciones(proyecto_id);

CREATE INDEX IF NOT EXISTS idx_bom_autorizaciones_pendientes
    ON tb_bom_autorizaciones(estatus)
    WHERE estatus NOT IN ('AUTORIZADO_FINANZAS', 'RECHAZADO');
