-- Registra adendas, reemplazos e items fuera de alcance sin mutar la linea base del BOM.

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS tipo_origen_item VARCHAR(20) NOT NULL DEFAULT 'BASE';

UPDATE tb_bom_items
SET tipo_origen_item = 'BASE'
WHERE tipo_origen_item IS NULL;

ALTER TABLE tb_bom_items
    ALTER COLUMN tipo_origen_item SET DEFAULT 'BASE',
    ALTER COLUMN tipo_origen_item SET NOT NULL;

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS id_item_reemplazado UUID;

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS motivo_adenda TEXT;

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS creado_en_adenda UUID;

ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS tb_bom_items_tipo_origen_item_check;
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_tipo_origen_item_check
    CHECK (tipo_origen_item IN ('BASE', 'REEMPLAZO', 'FUERA_SCOPE'));

DO $$ BEGIN
    ALTER TABLE tb_bom_items
        ADD CONSTRAINT fk_bom_items_reemplazado
        FOREIGN KEY (id_item_reemplazado) REFERENCES tb_bom_items(id_item) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS tb_bom_adendas (
    id_adenda UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_bom_base UUID NOT NULL REFERENCES tb_bom(id_bom) ON DELETE CASCADE,
    tipo_adenda VARCHAR(30) NOT NULL,
    motivo TEXT NOT NULL,
    estatus VARCHAR(30) NOT NULL DEFAULT 'REGISTRADA',
    creado_por UUID REFERENCES tb_usuarios(id_usuario),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_adendas_tipo_check
        CHECK (tipo_adenda IN ('REEMPLAZO', 'FUERA_SCOPE', 'NO_ADQUIRIDO')),
    CONSTRAINT tb_bom_adendas_estatus_check
        CHECK (estatus IN ('REGISTRADA', 'CERRADA', 'CANCELADA'))
);

CREATE TABLE IF NOT EXISTS tb_bom_adenda_items (
    id_adenda_item UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_adenda UUID NOT NULL REFERENCES tb_bom_adendas(id_adenda) ON DELETE CASCADE,
    id_item_origen UUID REFERENCES tb_bom_items(id_item),
    id_item_bom UUID REFERENCES tb_bom_items(id_item),
    tipo_linea VARCHAR(30) NOT NULL,
    motivo TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_adenda_items_tipo_check
        CHECK (tipo_linea IN ('REEMPLAZO', 'FUERA_SCOPE', 'NO_ADQUIRIDO')),
    CONSTRAINT tb_bom_adenda_items_relacion_check
        CHECK (
            (tipo_linea = 'REEMPLAZO' AND id_item_origen IS NOT NULL AND id_item_bom IS NOT NULL)
            OR (tipo_linea = 'FUERA_SCOPE' AND id_item_origen IS NULL AND id_item_bom IS NOT NULL)
            OR (tipo_linea = 'NO_ADQUIRIDO' AND id_item_origen IS NOT NULL AND id_item_bom IS NULL)
        )
);

DO $$ BEGIN
    ALTER TABLE tb_bom_items
        ADD CONSTRAINT fk_bom_items_creado_en_adenda
        FOREIGN KEY (creado_en_adenda) REFERENCES tb_bom_adendas(id_adenda) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_items_tipo_origen
    ON tb_bom_items(id_bom, tipo_origen_item)
    WHERE activo = TRUE;

CREATE INDEX IF NOT EXISTS idx_bom_items_reemplazado
    ON tb_bom_items(id_item_reemplazado)
    WHERE id_item_reemplazado IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_items_creado_en_adenda
    ON tb_bom_items(creado_en_adenda)
    WHERE creado_en_adenda IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_adendas_bom
    ON tb_bom_adendas(id_bom_base, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bom_adenda_items_adenda
    ON tb_bom_adenda_items(id_adenda);

CREATE INDEX IF NOT EXISTS idx_bom_adenda_items_origen
    ON tb_bom_adenda_items(id_item_origen)
    WHERE id_item_origen IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_adenda_items_item_bom
    ON tb_bom_adenda_items(id_item_bom)
    WHERE id_item_bom IS NOT NULL;
