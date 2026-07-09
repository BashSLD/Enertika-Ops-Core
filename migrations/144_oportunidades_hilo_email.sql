-- Agrega trazabilidad de hilo de correo y fecha real de envio para oportunidades.

ALTER TABLE tb_oportunidades
    ADD COLUMN IF NOT EXISTS hilo_search_key TEXT;

ALTER TABLE tb_oportunidades
    ADD COLUMN IF NOT EXISTS fecha_envio_email TIMESTAMPTZ;

COMMENT ON COLUMN tb_oportunidades.hilo_search_key IS
    'Titulo del eslabon usado para buscar el hilo de correo al enviar un seguimiento.';

COMMENT ON COLUMN tb_oportunidades.fecha_envio_email IS
    'Fecha/hora en que se confirmo el envio real del correo asociado a la oportunidad.';

UPDATE tb_oportunidades
SET fecha_envio_email = COALESCE(fecha_solicitud, fecha_creacion)
WHERE email_enviado = TRUE
  AND fecha_envio_email IS NULL;

CREATE INDEX IF NOT EXISTS idx_oportunidades_parent_id
    ON tb_oportunidades(parent_id)
    WHERE parent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_oportunidades_email_anchor
    ON tb_oportunidades(email_enviado, fecha_envio_email DESC)
    WHERE email_enviado = TRUE;
