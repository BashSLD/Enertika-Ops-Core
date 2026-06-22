-- Estampa quien crea/edita cada material del catalogo interno (auditoria de autoria).
-- Necesario ahora que la edicion del catalogo interno la comparten compras e ingenieria.

ALTER TABLE tb_cat_materiales
    ADD COLUMN IF NOT EXISTS creado_por uuid REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;

ALTER TABLE tb_cat_materiales
    ADD COLUMN IF NOT EXISTS actualizado_por uuid REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_cat_materiales_creado_por ON tb_cat_materiales(creado_por);
