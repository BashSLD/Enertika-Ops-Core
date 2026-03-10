-- Migration 011: BOM category groups (AC/DC/CM/OC/TE) + item assignment
-- Idempotent

CREATE TABLE IF NOT EXISTS tb_cat_grupos_bom (
    id     SERIAL PRIMARY KEY,
    codigo VARCHAR(5)   NOT NULL UNIQUE,
    nombre VARCHAR(100) NOT NULL,
    orden  INT          NOT NULL DEFAULT 0,
    activo BOOLEAN      NOT NULL DEFAULT TRUE
);

INSERT INTO tb_cat_grupos_bom (codigo, nombre, orden) VALUES
    ('AC', 'Corriente Alterna',   1),
    ('DC', 'Corriente Directa',   2),
    ('CM', 'Comunicacion',        3),
    ('OC', 'Obra Civil',          4),
    ('TE', 'Trabajo Especifico',  5)
ON CONFLICT (codigo) DO NOTHING;

CREATE TABLE IF NOT EXISTS tb_bom_item_grupos (
    id_item  UUID NOT NULL REFERENCES tb_bom_items(id_item) ON DELETE CASCADE,
    id_grupo INT  NOT NULL REFERENCES tb_cat_grupos_bom(id) ON DELETE CASCADE,
    PRIMARY KEY (id_item, id_grupo)
);

CREATE INDEX IF NOT EXISTS idx_bom_item_grupos_item  ON tb_bom_item_grupos (id_item);
CREATE INDEX IF NOT EXISTS idx_bom_item_grupos_grupo ON tb_bom_item_grupos (id_grupo);
