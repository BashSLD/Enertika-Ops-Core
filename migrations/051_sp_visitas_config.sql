-- Migración 051: Configuración SharePoint para Visitas a Obra
-- Site y Drive independientes del SharePoint general del sistema

INSERT INTO tb_configuracion_global (clave, valor, descripcion)
VALUES
    ('SP_VISITAS_SITE_ID', '', 'ID del sitio SharePoint para reportes de Visita a Obra'),
    ('SP_VISITAS_DRIVE_ID', '', 'ID del Drive en el sitio SharePoint de Visitas a Obra')
ON CONFLICT (clave) DO NOTHING;
