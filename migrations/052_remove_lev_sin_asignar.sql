-- Migración 052: Elimina el evento LEV_SIN_ASIGNAR del catálogo de eventos del sistema.
-- El recordatorio de levantamientos sin asignar ahora se envía directamente al jefe_area_id
-- del levantamiento, sin depender de tb_config_emails.

-- 1. Remover LEV_SIN_ASIGNAR del JSON EVENTOS_SISTEMA (idempotente)
UPDATE tb_configuracion_global
SET valor = (
    SELECT jsonb_agg(elem)::text
    FROM jsonb_array_elements(valor::jsonb) AS elem
    WHERE elem->>'value' != 'LEV_SIN_ASIGNAR'
)
WHERE clave = 'EVENTOS_SISTEMA'
  AND valor::jsonb @> '[{"value": "LEV_SIN_ASIGNAR"}]';

-- 2. Eliminar reglas de correo que apuntaban a este evento (limpieza)
DELETE FROM tb_config_emails
WHERE trigger_value = 'LEV_SIN_ASIGNAR';
