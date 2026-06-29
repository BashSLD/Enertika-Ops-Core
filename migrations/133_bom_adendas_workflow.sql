-- Endurece adendas BOM con workflow, comentarios, grupos operativos y auditoria de rechazos.

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS requiere_aprobacion_ingenieria BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS enviado_construccion_por UUID REFERENCES tb_usuarios(id_usuario);

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS fecha_envio_construccion TIMESTAMPTZ;

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS aprobado_construccion_por UUID REFERENCES tb_usuarios(id_usuario);

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS fecha_aprobacion_construccion TIMESTAMPTZ;

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS aprobado_ingenieria_por UUID REFERENCES tb_usuarios(id_usuario);

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS fecha_aprobacion_ingenieria TIMESTAMPTZ;

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS rechazado_por UUID REFERENCES tb_usuarios(id_usuario);

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS fecha_rechazo TIMESTAMPTZ;

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS motivo_rechazo TEXT;

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS cancelado_por UUID REFERENCES tb_usuarios(id_usuario);

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS fecha_cancelacion TIMESTAMPTZ;

ALTER TABLE tb_bom_adendas DROP CONSTRAINT IF EXISTS tb_bom_adendas_estatus_check;

UPDATE tb_bom_adendas
SET estatus = CASE
        WHEN estatus IN ('REGISTRADA', 'CERRADA') THEN 'APROBADA'
        ELSE estatus
    END,
    fecha_envio_construccion = COALESCE(fecha_envio_construccion, created_at),
    fecha_aprobacion_construccion = COALESCE(fecha_aprobacion_construccion, created_at),
    aprobado_construccion_por = COALESCE(aprobado_construccion_por, creado_por),
    updated_at = NOW()
WHERE estatus IN ('REGISTRADA', 'CERRADA');

ALTER TABLE tb_bom_adendas ADD CONSTRAINT tb_bom_adendas_estatus_check
    CHECK (estatus IN (
        'BORRADOR',
        'PENDIENTE_CONSTRUCCION',
        'PENDIENTE_INGENIERIA',
        'APROBADA',
        'RECHAZADA',
        'CANCELADA'
    ));

ALTER TABLE tb_bom_adenda_items
    ADD COLUMN IF NOT EXISTS datos_item JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE tb_bom_adenda_items
    ADD COLUMN IF NOT EXISTS grupo_ids INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[];

ALTER TABLE tb_bom_adenda_items
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE tb_bom_adenda_items DROP CONSTRAINT IF EXISTS tb_bom_adenda_items_relacion_check;
ALTER TABLE tb_bom_adenda_items ADD CONSTRAINT tb_bom_adenda_items_relacion_check
    CHECK (
        (tipo_linea = 'REEMPLAZO' AND id_item_origen IS NOT NULL)
        OR (tipo_linea = 'FUERA_SCOPE' AND id_item_origen IS NULL)
        OR (tipo_linea = 'NO_ADQUIRIDO' AND id_item_origen IS NOT NULL AND id_item_bom IS NULL)
    );

CREATE TABLE IF NOT EXISTS tb_bom_adenda_comentarios (
    id_comentario UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_adenda UUID NOT NULL REFERENCES tb_bom_adendas(id_adenda) ON DELETE CASCADE,
    comentario TEXT NOT NULL,
    creado_por UUID REFERENCES tb_usuarios(id_usuario),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bom_adenda_comentarios_adenda
    ON tb_bom_adenda_comentarios(id_adenda, created_at);

CREATE TABLE IF NOT EXISTS tb_bom_item_grupos_operativos (
    id_item UUID NOT NULL REFERENCES tb_bom_items(id_item) ON DELETE CASCADE,
    id_grupo INTEGER NOT NULL REFERENCES tb_cat_grupos_bom(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES tb_usuarios(id_usuario),
    PRIMARY KEY (id_item, id_grupo)
);

CREATE INDEX IF NOT EXISTS idx_bom_item_grupos_operativos_grupo
    ON tb_bom_item_grupos_operativos(id_grupo);

ALTER TABLE tb_bom_aprobaciones
    ADD COLUMN IF NOT EXISTS destino_rechazo VARCHAR(20);

ALTER TABLE tb_bom_aprobaciones DROP CONSTRAINT IF EXISTS tb_bom_aprobaciones_destino_rechazo_check;
ALTER TABLE tb_bom_aprobaciones ADD CONSTRAINT tb_bom_aprobaciones_destino_rechazo_check
    CHECK (destino_rechazo IS NULL OR destino_rechazo IN ('obra', 'ingenieria'));

CREATE TABLE IF NOT EXISTS tb_bom_propuestas_cambio (
    id_propuesta UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_bom UUID NOT NULL REFERENCES tb_bom(id_bom) ON DELETE CASCADE,
    tipo_solicitante VARCHAR(30) NOT NULL,
    estatus VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE_INGENIERIA',
    motivo TEXT NOT NULL,
    lineas JSONB NOT NULL DEFAULT '[]'::jsonb,
    creado_por UUID REFERENCES tb_usuarios(id_usuario),
    revisado_por UUID REFERENCES tb_usuarios(id_usuario),
    fecha_revision TIMESTAMPTZ,
    comentario_revision TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_propuestas_tipo_solicitante_check
        CHECK (tipo_solicitante IN ('OBRA', 'CONSTRUCCION')),
    CONSTRAINT tb_bom_propuestas_estatus_check
        CHECK (estatus IN (
            'PENDIENTE_INGENIERIA',
            'APROBADA',
            'RECHAZADA',
            'APLICADA'
        ))
);

CREATE INDEX IF NOT EXISTS idx_bom_propuestas_cambio_bom
    ON tb_bom_propuestas_cambio(id_bom, estatus, created_at DESC);
