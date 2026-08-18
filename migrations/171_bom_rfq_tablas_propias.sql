-- Doc 35: RFQ en tablas propias (no reusa tb_bom_cotizaciones/es_rfq, 0 filas verificado DEV+PROD)
-- + tb_config_empresa (membrete PDF RFQ + validacion RFC receptor en conciliacion XML de Compras)

CREATE TABLE IF NOT EXISTS tb_config_empresa (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    razon_social TEXT NOT NULL,
    rfc TEXT NOT NULL,
    direccion TEXT,
    telefono TEXT,
    email_contacto TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO tb_config_empresa (id, razon_social, rfc, direccion, telefono, email_contacto)
VALUES (1, 'Enertika', 'PENDIENTE_CONFIGURAR', NULL, NULL, NULL)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS tb_bom_rfq (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bom_id UUID NOT NULL REFERENCES tb_bom(id_bom),
    creado_por UUID NOT NULL REFERENCES tb_usuarios(id_usuario),
    notas TEXT,
    lock_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bom_rfq_bom_id ON tb_bom_rfq(bom_id);

CREATE TABLE IF NOT EXISTS tb_bom_rfq_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rfq_id UUID NOT NULL REFERENCES tb_bom_rfq(id) ON DELETE CASCADE,
    bom_item_id UUID NOT NULL REFERENCES tb_bom_items(id_item),
    cantidad NUMERIC(14, 3) NOT NULL,
    unidad_override VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (rfq_id, bom_item_id)
);

CREATE INDEX IF NOT EXISTS idx_bom_rfq_items_rfq_id ON tb_bom_rfq_items(rfq_id);

CREATE TABLE IF NOT EXISTS tb_bom_rfq_historial (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rfq_id UUID NOT NULL REFERENCES tb_bom_rfq(id) ON DELETE CASCADE,
    usuario_id UUID NOT NULL REFERENCES tb_usuarios(id_usuario),
    accion VARCHAR(30) NOT NULL,
    detalle JSONB,
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bom_rfq_historial_rfq_id ON tb_bom_rfq_historial(rfq_id);

-- es_rfq nunca se uso en produccion (0 filas verificado en DEV y PROD 2026-08-16/17) -- sin backfill
ALTER TABLE tb_bom_cotizaciones DROP CONSTRAINT IF EXISTS fk_bom_cotizacion_rfq_bom;
ALTER TABLE tb_bom_cotizaciones DROP COLUMN IF EXISTS es_rfq;
ALTER TABLE tb_bom_cotizaciones DROP COLUMN IF EXISTS rfq_origen_id;
ALTER TABLE tb_bom_cotizaciones ADD COLUMN IF NOT EXISTS rfq_id UUID REFERENCES tb_bom_rfq(id);
CREATE INDEX IF NOT EXISTS idx_bom_cotizaciones_rfq_id ON tb_bom_cotizaciones(rfq_id);
