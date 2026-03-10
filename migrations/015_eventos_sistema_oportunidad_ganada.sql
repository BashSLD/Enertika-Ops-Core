-- Migración 015: Agrega evento OPORTUNIDAD_GANADA al catálogo de eventos del sistema
-- Actualiza el JSON en tb_configuracion_global preservando los eventos existentes

UPDATE tb_configuracion_global
SET valor = '[
  {"label": "Solicitud Extraordinaria", "value": "EXTRAORDINARIA"},
  {"label": "Nuevo Comentario", "value": "NUEVO_COMENTARIO"},
  {"label": "Cambio de Estatus", "value": "CAMBIO_ESTATUS"},
  {"label": "Asignación", "value": "ASIGNACION"},
  {"label": "Solicitud de viaticos", "value": "SOLICITUD_VIATICOS"},
  {"label": "Recordatorio Levantamientos", "value": "LEV_SIN_ASIGNAR"},
  {"label": "Oportunidad Ganada", "value": "OPORTUNIDAD_GANADA"}
]'
WHERE clave = 'EVENTOS_SISTEMA';
