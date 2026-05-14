-- 074: Agregar puesto a tb_usuarios y sembrar tb_cat_sucursales desde tb_cat_zonas_compra

ALTER TABLE tb_usuarios ADD COLUMN IF NOT EXISTS puesto VARCHAR(150);

INSERT INTO tb_cat_sucursales (id, codigo, nombre, activa)
SELECT
    gen_random_uuid(),
    UPPER(REGEXP_REPLACE(TRIM(z.nombre), '\s+', '_', 'g')),
    TRIM(z.nombre),
    z.activo
FROM tb_cat_zonas_compra z
WHERE NOT EXISTS (
    SELECT 1 FROM tb_cat_sucursales s WHERE LOWER(s.nombre) = LOWER(TRIM(z.nombre))
);
