-- Migracion 044: Alta de modulo Finanzas en catalogo
-- Nota: no asigna permisos a usuarios. La asignacion se hace desde Admin.

INSERT INTO tb_cat_modulos (
    id,
    nombre,
    slug,
    ruta,
    icono,
    descripcion,
    is_active,
    orden,
    created_at
)
VALUES (
    gen_random_uuid(),
    'Finanzas',
    'finanzas',
    '/finanzas/ui',
    'bi-cash-coin',
    'Gestion de pagos BOM autorizados',
    TRUE,
    65,
    NOW()
)
ON CONFLICT (slug) DO NOTHING;
