-- Correo de contacto especifico para respuestas de proveedores en el PDF de RFQ (Compras/BOM),
-- independiente de email_contacto (usado para otros fines, ej. notificaciones de sistema).

ALTER TABLE tb_config_empresa ADD COLUMN IF NOT EXISTS email_rfq TEXT;

UPDATE tb_config_empresa SET email_rfq = 'compras@enertika.mx' WHERE id = 1 AND email_rfq IS NULL;
