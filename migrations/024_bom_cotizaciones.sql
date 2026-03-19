-- Migration 024: BOM Fase C — Cotizaciones
-- Agrega moneda/estatus_compra a items y crea tablas de cotizaciones

-- 1. Columnas nuevas en tb_bom_items
ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS moneda CHAR(3) DEFAULT 'MXN',
    ADD COLUMN IF NOT EXISTS estatus_compra VARCHAR(20) DEFAULT 'SIN_COTIZAR';

-- 2. Tabla de cotizaciones
CREATE TABLE IF NOT EXISTS tb_bom_cotizaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bom_id UUID NOT NULL REFERENCES tb_bom(id_bom) ON DELETE CASCADE,
    proveedor_id UUID REFERENCES tb_proveedores(id_proveedor),
    nombre_proveedor TEXT,
    moneda CHAR(3) NOT NULL DEFAULT 'MXN',
    subtotal NUMERIC(14,2),
    iva NUMERIC(14,2),
    total NUMERIC(14,2),
    estatus VARCHAR(20) NOT NULL DEFAULT 'BORRADOR'
        CHECK (estatus IN ('BORRADOR', 'RECIBIDA', 'SELECCIONADA', 'RECHAZADA')),
    pdf_url TEXT,
    notas TEXT,
    creado_por UUID REFERENCES tb_usuarios(id_usuario),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Items de cada cotización
CREATE TABLE IF NOT EXISTS tb_bom_cotizacion_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cotizacion_id UUID NOT NULL REFERENCES tb_bom_cotizaciones(id) ON DELETE CASCADE,
    bom_item_id UUID NOT NULL REFERENCES tb_bom_items(id_item),
    precio_unitario NUMERIC(12,4),
    cantidad NUMERIC(10,2),
    moneda CHAR(3) DEFAULT 'MXN',
    subtotal_linea NUMERIC(14,2),
    UNIQUE (cotizacion_id, bom_item_id)
);

-- 4. Índices
CREATE INDEX IF NOT EXISTS idx_bom_cotizaciones_bom_id ON tb_bom_cotizaciones(bom_id);
CREATE INDEX IF NOT EXISTS idx_bom_cotizacion_items_cotizacion ON tb_bom_cotizacion_items(cotizacion_id);
CREATE INDEX IF NOT EXISTS idx_bom_cotizacion_items_item ON tb_bom_cotizacion_items(bom_item_id);
