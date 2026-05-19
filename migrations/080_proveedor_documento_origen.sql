-- Sembrar origen de adjuntos para documentacion de proveedores.

INSERT INTO tb_cat_origenes_adjuntos (slug, descripcion, activo)
VALUES ('proveedor_documento', 'Documentacion de proveedores', true)
ON CONFLICT (slug) DO UPDATE
SET descripcion = EXCLUDED.descripcion,
    activo = true;
