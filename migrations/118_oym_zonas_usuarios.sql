-- migrations/118_oym_zonas_usuarios.sql
-- Asignacion de usuarios a zonas CFE dentro del modulo O&M

CREATE TABLE IF NOT EXISTS tb_oym_zonas_usuarios (
    usuario_id  UUID PRIMARY KEY REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    zona        TEXT NOT NULL CHECK (zona IN ('Zona 1', 'Zona 2')),
    asignado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oym_zonas_zona ON tb_oym_zonas_usuarios (zona);
