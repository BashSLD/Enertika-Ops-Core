-- Agrega el evento HORAS_EXTRA_ESCALACION_DIRECTOR al catalogo de eventos configurables
-- (para que aparezca en Admin > Reglas de correo) y siembra CC/CCO con el estado actual
-- del fallback hardcodeado (RH editor/admin -> CC, ADMIN global -> CCO) que hoy aplica
-- resolver_destinatarios_he_puro cuando la cadena de jefes de horas extra/compensatorio
-- incluye a un director. A partir de esta migracion RH ajusta la lista desde el panel;
-- deja de auto-seguir el rol.

WITH nuevos(evento) AS (
    VALUES
        ('{"label": "Horas extra / compensatorio - escalada a director", "value": "HORAS_EXTRA_ESCALACION_DIRECTOR"}'::jsonb)
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
    'HORAS_EXTRA_ESCALACION_DIRECTOR',
    u.email,
    'CC',
    'Semilla inicial: RH editor/admin activo con correo (estado al migrar)'
FROM public.tb_usuarios u
JOIN public.tb_permisos_modulos pm
    ON pm.usuario_id = u.id_usuario
   AND pm.modulo_slug = 'rrhh'
   AND pm.rol_modulo IN ('editor', 'admin')
WHERE u.is_active = true
  AND u.email IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM public.tb_config_emails
      WHERE trigger_field = 'EVENTO'
        AND trigger_value = 'HORAS_EXTRA_ESCALACION_DIRECTOR'
        AND type = 'CC'
        AND email_to_add = u.email
  );

INSERT INTO public.tb_config_emails (modulo, trigger_field, trigger_value, email_to_add, type, descripcion)
SELECT
    'ASISTENCIA',
    'EVENTO',
    'HORAS_EXTRA_ESCALACION_DIRECTOR',
    u.email,
    'CCO',
    'Semilla inicial: ADMIN global activo con correo (estado al migrar)'
FROM public.tb_usuarios u
WHERE u.rol_sistema = 'ADMIN'
  AND u.is_active = true
  AND u.email IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM public.tb_config_emails
      WHERE trigger_field = 'EVENTO'
        AND trigger_value = 'HORAS_EXTRA_ESCALACION_DIRECTOR'
        AND type = 'CCO'
        AND email_to_add = u.email
  );
