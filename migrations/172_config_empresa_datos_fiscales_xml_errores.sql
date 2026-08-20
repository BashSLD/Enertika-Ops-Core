-- Doc: validacion de datos fiscales en XML CFDI de Compras
-- Amplia tb_config_empresa con CP/regimen fiscal para validar contra el receptor del XML,
-- siembra los valores reales confirmados (muestreo 15 XML PROD), y crea tabla de auditoria
-- para facturas que fallan la validacion fiscal (RFC/razon social/CP/regimen/UsoCFDI/FormaPago).

ALTER TABLE tb_config_empresa ADD COLUMN IF NOT EXISTS codigo_postal TEXT;
ALTER TABLE tb_config_empresa ADD COLUMN IF NOT EXISTS regimen_fiscal TEXT;

UPDATE tb_config_empresa
SET razon_social = 'INGENIERIA Y SERVICIOS DE AHORRO ENERGETICO MEXICO',
    rfc = 'ISA150123IX5',
    codigo_postal = '11560',
    regimen_fiscal = '601',
    updated_at = NOW()
WHERE id = 1 AND rfc = 'PENDIENTE_CONFIGURAR';

CREATE TABLE IF NOT EXISTS tb_compras_xml_errores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    archivo TEXT NOT NULL,
    uuid_factura TEXT,
    emisor_rfc TEXT,
    emisor_nombre TEXT,
    tipo_error VARCHAR(200) NOT NULL,
    detalle TEXT NOT NULL,
    origen VARCHAR(20) NOT NULL CHECK (origen IN ('CARGA_MANUAL', 'BUZON_SAT')),
    uploaded_by_id UUID REFERENCES tb_usuarios(id_usuario),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_compras_xml_errores_created_at ON tb_compras_xml_errores(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_compras_xml_errores_uuid_factura ON tb_compras_xml_errores(uuid_factura);
