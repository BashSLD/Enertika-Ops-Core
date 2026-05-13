-- GAP 1: Insertar configuracion de meses de expiracion de periodos de vacaciones
-- El valor es usado por calcular_periodos() en modules/vacaciones/logic.py via ConfigService
INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES (
    'VACACIONES_MESES_EXPIRACION',
    '18',
    'int',
    'Meses hasta que expira un periodo de vacaciones no utilizado (contados desde el aniversario)'
)
ON CONFLICT (clave) DO NOTHING;
