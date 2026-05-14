-- Registra el módulo RRHH en el catálogo de módulos del sistema

INSERT INTO tb_cat_modulos (nombre, slug, ruta, icono, descripcion, is_active, orden)
VALUES (
    'RRHH',
    'rrhh',
    '/rrhh/ui',
    'bi-people-fill',
    'Gestión de recursos humanos, vacaciones y perfil de empleados',
    true,
    12
)
ON CONFLICT (slug) DO NOTHING;
