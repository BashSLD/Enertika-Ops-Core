-- 119_cat_materiales_nomenclatura.sql
-- Catalogo interno BOM: agrega 6 campos de nomenclatura estructurada (MATERIAL/TIPO/
-- ACABADO/MARCA/ADICIONAL/MEDIDA) + moneda a tb_cat_materiales, y fuerza la relacion 1:N
-- interno->compras con UNIQUE(id_material_xml) en el puente tb_materiales_interno_xml.
-- Aplicar en DEV, verificar, luego PROD. SIEMPRE antes de desplegar codigo que lo use.

-- 1) Campos de nomenclatura estructurada en el catalogo interno
ALTER TABLE tb_cat_materiales ADD COLUMN IF NOT EXISTS material  TEXT;
ALTER TABLE tb_cat_materiales ADD COLUMN IF NOT EXISTS tipo      TEXT;
ALTER TABLE tb_cat_materiales ADD COLUMN IF NOT EXISTS acabado   TEXT;
ALTER TABLE tb_cat_materiales ADD COLUMN IF NOT EXISTS marca     TEXT;
ALTER TABLE tb_cat_materiales ADD COLUMN IF NOT EXISTS adicional TEXT;
ALTER TABLE tb_cat_materiales ADD COLUMN IF NOT EXISTS medida    TEXT;

-- Moneda original del catalogo (el precio_referencia se carga ya normalizado a MXN)
ALTER TABLE tb_cat_materiales ADD COLUMN IF NOT EXISTS moneda VARCHAR(3) DEFAULT 'MXN';

-- 2) Relacion 1:N interno->compras: cada item de factura (XML) pertenece a UNA sola interna.
--    Validado en PROD: tb_materiales_interno_xml con 0 filas, 0 duplicados de id_material_xml.
DO $$ BEGIN
  ALTER TABLE tb_materiales_interno_xml
    ADD CONSTRAINT uq_interno_xml_xml UNIQUE (id_material_xml);
EXCEPTION
  WHEN duplicate_table THEN NULL;   -- constraint ya existe
  WHEN duplicate_object THEN NULL;  -- constraint ya existe
END $$;

-- 3) El indice no-unico previo queda redundante: el UNIQUE de arriba crea su propio
--    indice unico sobre la misma columna. Se elimina para no duplicar costo de escritura.
DROP INDEX IF EXISTS idx_interno_xml_xml;
