-- Habilita CCO en reglas inteligentes y agrega eventos de vacaciones al catalogo de eventos.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.tb_config_emails'::regclass
          AND conname = 'tb_config_emails_type_check'
    ) THEN
        ALTER TABLE public.tb_config_emails
            DROP CONSTRAINT tb_config_emails_type_check;
    END IF;
END $$;

ALTER TABLE public.tb_config_emails
    ADD CONSTRAINT tb_config_emails_type_check
    CHECK (type IN ('TO', 'CC', 'CCO'));

INSERT INTO public.tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES (
    'EVENTOS_SISTEMA',
    '[
      {"label": "Solicitud Extraordinaria", "value": "EXTRAORDINARIA"},
      {"label": "Nuevo Comentario", "value": "NUEVO_COMENTARIO"},
      {"label": "Cambio de Estatus", "value": "CAMBIO_ESTATUS"},
      {"label": "Asignacion", "value": "ASIGNACION"},
      {"label": "Solicitud de viaticos", "value": "SOLICITUD_VIATICOS"},
      {"label": "Oportunidad Ganada", "value": "OPORTUNIDAD_GANADA"},
      {"label": "Solicitud de vacaciones aprobada", "value": "VACACIONES_SOLICITUD_APROBADA"},
      {"label": "Solicitud de vacaciones rechazada", "value": "VACACIONES_SOLICITUD_RECHAZADA"}
    ]',
    'json',
    'Eventos disponibles para reglas inteligentes de correo'
)
ON CONFLICT (clave) DO NOTHING;

WITH nuevos(evento) AS (
    VALUES
        ('{"label": "Solicitud de vacaciones aprobada", "value": "VACACIONES_SOLICITUD_APROBADA"}'::jsonb),
        ('{"label": "Solicitud de vacaciones rechazada", "value": "VACACIONES_SOLICITUD_RECHAZADA"}'::jsonb)
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
    ),
    tipo_dato = 'json',
    descripcion = COALESCE(
        cfg.descripcion,
        'Eventos disponibles para reglas inteligentes de correo'
    )
WHERE cfg.clave = 'EVENTOS_SISTEMA';
