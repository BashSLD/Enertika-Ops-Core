-- Migración 009: Conversión diferida unisitio → multisitio
-- Permite almacenar los datos de conversión pendiente en el seguimiento
-- hasta que el correo sea enviado (Paso 3).

ALTER TABLE tb_oportunidades
ADD COLUMN IF NOT EXISTS conversion_pendiente BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS sitios_json_pendiente TEXT;

COMMENT ON COLUMN tb_oportunidades.conversion_pendiente IS 'Indica si hay una conversión unisitio→multisitio pendiente de ejecutar al enviar el correo';
COMMENT ON COLUMN tb_oportunidades.sitios_json_pendiente IS 'JSON temporal con los sitios a agregar al parent cuando se confirme el envío del correo';
