-- Punto 6.6 (doc 37/41): agrega el rol "Responsable Compras" al equipo del proyecto,
-- replicando el patron organizacional RC/RI (responsable con auto-asignacion via rol_jefe).
-- No se remueve 'encargado' (O&M) de ningun CHECK: 0 filas lo usan hoy en PROD/DEV, se deja
-- para no requerir otra migracion cuando O&M se reintroduzca (backlog aparte).

-- 'comprador_asignado' es el rol operativo de Compras (analogo a ingeniero_asignado/
-- coordinador_obra: dispara la auto-asignacion de 'responsable_compras'). No se reutiliza
-- 'encargado' porque ROL_PROYECTO_LABELS mapea por rol_proyecto unicamente (sin area) y dos
-- entradas con el mismo rol para areas distintas (OYM/COMPRAS) se pisarian el label.
ALTER TABLE tb_proyecto_usuarios DROP CONSTRAINT IF EXISTS chk_rol_proyecto_valido;
ALTER TABLE tb_proyecto_usuarios ADD CONSTRAINT chk_rol_proyecto_valido
    CHECK (rol_proyecto IN (
        'ingeniero_asignado',
        'coordinador_obra',
        'encargado',
        'responsable_ingenieria',
        'responsable_construccion',
        'comprador_asignado',
        'responsable_compras'
    ));

ALTER TABLE tb_usuarios DROP CONSTRAINT IF EXISTS chk_rol_organizacional_valido;
ALTER TABLE tb_usuarios ADD CONSTRAINT chk_rol_organizacional_valido
    CHECK (rol_organizacional IS NULL OR rol_organizacional IN (
        '',
        'jefe_comercial',
        'jefe_ingenieria',
        'jefe_construccion',
        'jefe_compras',
        'director'
    ));
