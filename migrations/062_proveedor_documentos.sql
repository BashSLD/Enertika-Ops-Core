-- Migration 062: Documentación de proveedores (Gap 8)
-- Tabla para expediente documental por proveedor.
-- Compras: CRUD + upload a SharePoint. Finanzas: solo consulta.
-- Idempotente: CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS tb_proveedor_documentos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_proveedor UUID NOT NULL REFERENCES tb_proveedores(id_proveedor),
    tipo_documento VARCHAR(50) NOT NULL,
    tipo_persona VARCHAR(20) NOT NULL DEFAULT 'MORAL',
    sharepoint_url TEXT NOT NULL,
    fecha_documento DATE,
    fecha_vencimiento DATE,
    vigente BOOLEAN DEFAULT TRUE,
    subido_por UUID REFERENCES tb_usuarios(id_usuario),
    notas TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prov_docs_proveedor ON tb_proveedor_documentos(id_proveedor);
CREATE INDEX IF NOT EXISTS idx_prov_docs_vigente ON tb_proveedor_documentos(vigente);
