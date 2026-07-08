-- Agrega el evento APROBACION_HORAS_EXTRA al catalogo de eventos configurables
-- (para que aparezca en Admin > Reglas de correo) y siembra el placeholder
-- {EMPLEADO} como TO por defecto, preservando el comportamiento actual (el
-- empleado siempre recibe la notificacion de aprobacion) sin logica
-- hardcodeada por fuera del mecanismo de configuracion de RH.

WITH nuevos(evento) AS (
    VALUES
        ('{"label": "Aprobacion de horas extra", "value": "APROBACION_HORAS_EXTRA"}'::jsonb)
),
actual AS (
    SELECT clave, valor::jsonb AS eventos
    FROM public.tb_configuracion_global
    WHERE clave = 'EVENTOS_SISTEMA'
),
faltantes AS (
    SELECT jsonb_agg(n.evento) AS eventos
    FROM nuevos n
    CROSS JOIN actual a
    WHERE NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements(a.eventos) e
        WHERE e->>'value' = n.evento->>'value'
    )
)
UPDATE public.tb_configuracion_global cfg
SET valor = (
        SELECT jsonb_pretty(a.eventos || COALESCE(f.eventos, '[]'::jsonb))
        FROM actual a
        CROSS JOIN faltantes f
    )
WHERE cfg.clave = 'EVENTOS_SISTEMA';

INSERT INTO public.tb_config_emails (modulo, trigger_field, trigger_value, email_to_add, type, descripcion)
SELECT
    'ASISTENCIA',
    'EVENTO',
    'APROBACION_HORAS_EXTRA',
    '{EMPLEADO}',
    'TO',
    'Placeholder dinamico: se resuelve al email del empleado cuya solicitud de horas extra fue aprobada'
WHERE NOT EXISTS (
    SELECT 1 FROM public.tb_config_emails
    WHERE trigger_field = 'EVENTO'
      AND trigger_value = 'APROBACION_HORAS_EXTRA'
      AND type = 'TO'
      AND email_to_add = '{EMPLEADO}'
);
