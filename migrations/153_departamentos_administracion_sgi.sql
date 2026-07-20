-- Alta de departamentos Administracion y SGI (Sistema de Gestion Integral) en el catalogo.

INSERT INTO tb_cat_departamentos (
    nombre,
    slug,
    descripcion,
    is_active
)
VALUES (
    'Administración',
    'administracion',
    'Departamento de administración',
    TRUE
)
ON CONFLICT (slug) DO UPDATE
SET nombre = EXCLUDED.nombre,
    descripcion = COALESCE(tb_cat_departamentos.descripcion, EXCLUDED.descripcion),
    is_active = TRUE;

INSERT INTO tb_cat_departamentos (
    nombre,
    slug,
    descripcion,
    is_active
)
VALUES (
    'SGI',
    'sgi',
    'Sistema de Gestión Integral',
    TRUE
)
ON CONFLICT (slug) DO UPDATE
SET nombre = EXCLUDED.nombre,
    descripcion = COALESCE(tb_cat_departamentos.descripcion, EXCLUDED.descripcion),
    is_active = TRUE;
