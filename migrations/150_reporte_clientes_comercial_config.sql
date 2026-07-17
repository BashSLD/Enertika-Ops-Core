-- Limites de guardrail para el reporte de clientes/empresas de Comercial (Excel/PDF, general y por cliente).
INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES
    ('comercial.reporte_clientes_max_solicitudes', '10000', 'integer', 'Maximo de oportunidades filtradas antes de exigir acotar fechas/estatus/cliente en el reporte de clientes'),
    ('comercial.reporte_clientes_max_clientes_excel', '10000', 'integer', 'Maximo de filas de resumen (clientes canonicos + grupos legacy) permitidas en el Excel general del reporte de clientes'),
    ('comercial.reporte_clientes_max_filas_detalle', '10000', 'integer', 'Maximo de filas de detalle (sitio/proyecto) permitidas en el modo enfocado por cliente del reporte de clientes'),
    ('comercial.reporte_clientes_max_clientes_pdf', '1000', 'integer', 'Maximo de filas de resumen permitidas en el PDF general del reporte de clientes'),
    ('comercial.reporte_clientes_max_filas_detalle_pdf', '1000', 'integer', 'Maximo de filas de detalle permitidas en el PDF enfocado por cliente del reporte de clientes')
ON CONFLICT (clave) DO NOTHING;
