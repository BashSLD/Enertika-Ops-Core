-- Migration 063: Mini almacén (Gap 9)
-- Tabla de inventario gestionada por Compras.
-- Permite consultar stock desde el BOM.
-- Idempotente: CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS tb_inventario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_material UUID REFERENCES tb_materiales_historial(id),
    descripcion TEXT NOT NULL,
    cantidad_disponible NUMERIC(14,4) NOT NULL DEFAULT 0,
    unidad_medida VARCHAR(50),
    ubicacion VARCHAR(100),
    id_proveedor UUID REFERENCES tb_proveedores(id_proveedor),
    fecha_ingreso DATE DEFAULT CURRENT_DATE,
    id_bom_item_ref UUID REFERENCES tb_bom_items(id_item) ON DELETE SET NULL,
    notas TEXT,
    activo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventario_activo ON tb_inventario(activo);
CREATE INDEX IF NOT EXISTS idx_inventario_material ON tb_inventario(id_material);
