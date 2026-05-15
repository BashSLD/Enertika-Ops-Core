-- 078_vacaciones_anticipo_semestral.sql
-- Configuracion para vacaciones anticipadas con liberacion semestral.
-- Permite a RH habilitar anticipos y configurar el porcentaje y limite de dias negativos.

INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES
    (
        'VACACIONES_ANTICIPO_HABILITADO',
        'true',
        'bool',
        'Habilita solicitudes de vacaciones anticipadas (antes del aniversario o antes del semestre)'
    ),
    (
        'VACACIONES_ANTICIPO_MESES_SEMESTRE',
        '6',
        'int',
        'Meses desde el ultimo aniversario para liberar el porcentaje de dias del siguiente periodo'
    ),
    (
        'VACACIONES_ANTICIPO_PORCENTAJE_LIBERACION',
        '50',
        'int',
        'Porcentaje de los dias del siguiente periodo que se liberan al cumplir el semestre (0-100)'
    ),
    (
        'VACACIONES_ANTICIPO_MAXIMO_DIAS',
        '7',
        'int',
        'Maximo de dias negativos permitidos por anticipacion de vacaciones'
    )
ON CONFLICT (clave) DO NOTHING;
