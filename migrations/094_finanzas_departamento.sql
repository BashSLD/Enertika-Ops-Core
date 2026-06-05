-- Alta del departamento Finanzas y su relacion con el modulo Finanzas.

INSERT INTO tb_cat_departamentos (
    nombre,
    slug,
    descripcion,
    is_active
)
VALUES (
    'Finanzas',
    'finanzas',
    'Departamento de finanzas y pagos',
    TRUE
)
ON CONFLICT (slug) DO UPDATE
SET nombre = EXCLUDED.nombre,
    descripcion = COALESCE(tb_cat_departamentos.descripcion, EXCLUDED.descripcion),
    is_active = TRUE;

INSERT INTO tb_departamento_modulos (
    departamento_slug,
    modulo_slug,
    rol_default
)
VALUES (
    'finanzas',
    'finanzas',
    'viewer'
)
ON CONFLICT (departamento_slug, modulo_slug) DO UPDATE
SET rol_default = COALESCE(tb_departamento_modulos.rol_default, EXCLUDED.rol_default);
