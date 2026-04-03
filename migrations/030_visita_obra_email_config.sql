-- Migración 030: Campo de configuración de destinatarios para email de Visita a Obra
-- Agrega clave visita_obra_destinatarios a tb_configuracion_global

INSERT INTO tb_configuracion_global (clave, valor)
VALUES ('visita_obra_destinatarios', '')
ON CONFLICT (clave) DO NOTHING;
