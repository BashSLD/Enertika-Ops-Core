-- Agrega columna para persistir contenido XML en staging (base64)
-- Los registros existentes quedarán con NULL (modo legacy)
ALTER TABLE tb_xml_staging ADD COLUMN IF NOT EXISTS xml_content_b64 TEXT;
