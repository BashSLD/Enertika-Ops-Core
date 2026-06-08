-- Backfill idempotente de solicitado_por_id para oportunidades legacy con solicitante guardado como texto.

WITH usuarios_norm AS (
    SELECT
        id_usuario,
        lower(regexp_replace(trim(nombre), '\s+', ' ', 'g')) AS nombre_norm,
        count(*) OVER (
            PARTITION BY lower(regexp_replace(trim(nombre), '\s+', ' ', 'g'))
        ) AS usuarios_con_mismo_nombre
    FROM tb_usuarios
    WHERE nombre IS NOT NULL
      AND trim(nombre) <> ''
),
matches_unicos AS (
    SELECT
        o.id_oportunidad,
        u.id_usuario
    FROM tb_oportunidades o
    JOIN usuarios_norm u
      ON lower(regexp_replace(trim(o.solicitado_por), '\s+', ' ', 'g')) = u.nombre_norm
    WHERE o.email_enviado = true
      AND o.solicitado_por_id IS NULL
      AND o.solicitado_por IS NOT NULL
      AND trim(o.solicitado_por) <> ''
      AND u.usuarios_con_mismo_nombre = 1
)
UPDATE tb_oportunidades o
SET solicitado_por_id = m.id_usuario
FROM matches_unicos m
WHERE o.id_oportunidad = m.id_oportunidad
  AND o.solicitado_por_id IS NULL;
