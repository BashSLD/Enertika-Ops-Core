-- Fallback de seccion BOM para historicos sin tb_bom_item_grupos.
-- La fuente principal del Resumen de compra es tb_bom_item_grupos (AC/DC/CM/OC/TE).

ALTER TABLE tb_cat_categorias_compra
    ADD COLUMN IF NOT EXISTS seccion_bom VARCHAR;

UPDATE tb_cat_categorias_compra
SET seccion_bom = NULL;

-- Respaldo DC. Inversores se clasifica en DC por decision de negocio.
UPDATE tb_cat_categorias_compra
SET seccion_bom = 'DC'
WHERE id IN (11, 12, 2, 4, 6, 13);

-- Respaldo AC.
UPDATE tb_cat_categorias_compra
SET seccion_bom = 'AC'
WHERE id IN (1, 3, 5, 7, 14);

-- Respaldo CM.
UPDATE tb_cat_categorias_compra
SET seccion_bom = 'CM'
WHERE id IN (10);

-- Miscelaneos y accesorios quedan sin respaldo: deben clasificarse por grupo del item.
