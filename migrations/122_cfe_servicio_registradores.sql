-- 122_cfe_servicio_registradores.sql
-- Visibilidad por usuario de servicios CFE en el perfil simulacion (muchos-a-uno).
-- Cada fila = un usuario que registro un servicio en un modulo. oym no usa esta tabla.

CREATE TABLE IF NOT EXISTS tb_cfe_servicio_registradores (
    servicio_id   UUID        NOT NULL REFERENCES tb_cfe_servicios(id) ON DELETE CASCADE,
    usuario_id    UUID        NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    modulo        TEXT        NOT NULL,
    registrado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (servicio_id, usuario_id, modulo)
);

-- Filtro de listado: servicios visibles para (usuario, modulo).
CREATE INDEX IF NOT EXISTS idx_cfe_registradores_usuario_modulo
    ON tb_cfe_servicio_registradores (usuario_id, modulo);

-- Backfill: el creador original conserva visibilidad en simulacion.
INSERT INTO tb_cfe_servicio_registradores (servicio_id, usuario_id, modulo)
SELECT s.id, s.creado_por, 'simulacion'
FROM tb_cfe_servicios s
WHERE 'simulacion' = ANY(s.modulos)
  AND s.creado_por IS NOT NULL
ON CONFLICT DO NOTHING;
