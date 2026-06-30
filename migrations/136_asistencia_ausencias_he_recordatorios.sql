-- Agrega justificacion de asistencia por ausencia aprobada y control anti-spam de horas extra.

ALTER TABLE tb_cat_tipos_ausencia
    ADD COLUMN IF NOT EXISTS justifica_asistencia_dia BOOLEAN NOT NULL DEFAULT false;

UPDATE tb_cat_tipos_ausencia
SET justifica_asistencia_dia = true,
    updated_at = now()
WHERE slug IN (
    'vacaciones',
    'extraordinaria',
    'home_office',
    'incapacidad',
    'permiso_con_goce',
    'permiso_sin_goce'
)
  AND justifica_asistencia_dia IS DISTINCT FROM true;

UPDATE tb_cat_tipos_ausencia
SET justifica_asistencia_dia = false,
    updated_at = now()
WHERE slug IN ('permiso_llegar_tarde', 'permiso_salir_temprano')
  AND justifica_asistencia_dia IS DISTINCT FROM false;

ALTER TABLE tb_asistencia_diaria
    ADD COLUMN IF NOT EXISTS tiene_ausencia_justificada BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS horas_extra_solicitada_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS horas_extra_ultimo_recordatorio_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS horas_extra_recordatorios_enviados INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS horas_extra_resumen_rh_at TIMESTAMPTZ;

ALTER TABLE tb_asistencia_diaria
    DROP CONSTRAINT IF EXISTS ck_asistencia_estado;

ALTER TABLE tb_asistencia_diaria
    ADD CONSTRAINT ck_asistencia_estado CHECK (
        estado IN (
            'asistencia',
            'vacaciones',
            'ausencia',
            'sin_registro',
            'falta',
            'incompleto',
            'en_curso',
            'descanso',
            'feriado',
            'checada_en_vacaciones',
            'checada_en_ausencia',
            'sin_horario'
        )
    );

ALTER TABLE tb_asistencia_diaria
    DROP CONSTRAINT IF EXISTS ck_he_recordatorios_no_negativos;

ALTER TABLE tb_asistencia_diaria
    ADD CONSTRAINT ck_he_recordatorios_no_negativos
    CHECK (horas_extra_recordatorios_enviados >= 0);

WITH ausencias_aprobadas AS (
    SELECT
        ad.id AS asistencia_id,
        sa.id AS solicitud_id,
        ta.slug AS tipo_slug,
        ta.nombre AS tipo_nombre,
        (ad.primera_entrada IS NOT NULL OR ad.ultima_salida IS NOT NULL) AS tiene_checada
    FROM tb_asistencia_diaria ad
    JOIN tb_solicitudes_ausencia sa
        ON sa.usuario_id = ad.usuario_id
       AND ad.fecha_laboral BETWEEN sa.fecha_inicio AND sa.fecha_fin
    JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
    WHERE sa.estado = 'aprobado'
      AND COALESCE(sa.es_migracion, false) = false
      AND COALESCE(ta.justifica_asistencia_dia, false) = true
)
UPDATE tb_asistencia_diaria ad
SET tiene_ausencia_justificada = true,
    tiene_vacaciones = (aa.tipo_slug = 'vacaciones'),
    solicitud_ausencia_id = aa.solicitud_id,
    estado = CASE
        WHEN aa.tipo_slug = 'vacaciones' AND aa.tiene_checada THEN 'checada_en_vacaciones'
        WHEN aa.tipo_slug = 'vacaciones' THEN 'vacaciones'
        WHEN aa.tiene_checada THEN 'checada_en_ausencia'
        ELSE 'ausencia'
    END,
    minutos_extra = 0,
    observaciones = CASE
        WHEN aa.tipo_slug = 'vacaciones' AND NOT aa.tiene_checada THEN ad.observaciones
        WHEN aa.tipo_slug = 'vacaciones' THEN 'Tiene vacaciones aprobadas y tambien registro checadas'
        WHEN aa.tiene_checada THEN 'Tiene ausencia aprobada (' || aa.tipo_nombre || ') y tambien registro checadas'
        ELSE 'Ausencia aprobada: ' || aa.tipo_nombre
    END,
    updated_at = now()
FROM ausencias_aprobadas aa
WHERE ad.id = aa.asistencia_id
  AND (
      ad.tiene_ausencia_justificada IS DISTINCT FROM true
      OR ad.tiene_vacaciones IS DISTINCT FROM (aa.tipo_slug = 'vacaciones')
      OR ad.solicitud_ausencia_id IS DISTINCT FROM aa.solicitud_id
      OR ad.estado IS DISTINCT FROM CASE
          WHEN aa.tipo_slug = 'vacaciones' AND aa.tiene_checada THEN 'checada_en_vacaciones'
          WHEN aa.tipo_slug = 'vacaciones' THEN 'vacaciones'
          WHEN aa.tiene_checada THEN 'checada_en_ausencia'
          ELSE 'ausencia'
      END
      OR ad.minutos_extra IS DISTINCT FROM 0
      OR ad.observaciones IS DISTINCT FROM CASE
          WHEN aa.tipo_slug = 'vacaciones' AND NOT aa.tiene_checada THEN ad.observaciones
          WHEN aa.tipo_slug = 'vacaciones' THEN 'Tiene vacaciones aprobadas y tambien registro checadas'
          WHEN aa.tiene_checada THEN 'Tiene ausencia aprobada (' || aa.tipo_nombre || ') y tambien registro checadas'
          ELSE 'Ausencia aprobada: ' || aa.tipo_nombre
      END
  );

CREATE INDEX IF NOT EXISTS idx_asistencia_he_recordatorios
    ON tb_asistencia_diaria (
        horas_extra_estado,
        horas_extra_solicitada_at,
        horas_extra_ultimo_recordatorio_at
    )
    WHERE minutos_extra > 0 AND horas_extra_estado = 'solicitado';

CREATE INDEX IF NOT EXISTS idx_asistencia_ausencia_justificada
    ON tb_asistencia_diaria (fecha_laboral, tiene_ausencia_justificada)
    WHERE tiene_ausencia_justificada = true;

CREATE INDEX IF NOT EXISTS idx_asistencia_solicitud_ausencia
    ON tb_asistencia_diaria (solicitud_ausencia_id)
    WHERE solicitud_ausencia_id IS NOT NULL;

COMMENT ON COLUMN tb_cat_tipos_ausencia.justifica_asistencia_dia IS
    'Indica si una solicitud aprobada de este tipo justifica el dia completo en asistencia sin modificar saldo.';

COMMENT ON COLUMN tb_asistencia_diaria.tiene_ausencia_justificada IS
    'Verdadero cuando el dia queda cubierto por una solicitud de ausencia aprobada que justifica asistencia.';

COMMENT ON COLUMN tb_asistencia_diaria.horas_extra_solicitada_at IS
    'Fecha/hora en que el empleado solicito aprobacion de horas extra.';

COMMENT ON COLUMN tb_asistencia_diaria.horas_extra_ultimo_recordatorio_at IS
    'Ultimo recordatorio enviado al responsable de aprobar horas extra.';

COMMENT ON COLUMN tb_asistencia_diaria.horas_extra_recordatorios_enviados IS
    'Cantidad de recordatorios enviados al responsable de horas extra.';

COMMENT ON COLUMN tb_asistencia_diaria.horas_extra_resumen_rh_at IS
    'Ultima fecha en que RH recibio resumen de horas extra solicitadas aun sin resolver.';
