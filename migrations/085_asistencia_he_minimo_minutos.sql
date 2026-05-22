-- Umbral minimo de minutos extra para que sean contabilizadas y solicitables por el empleado.
-- Si minutos_extra calculados < este umbral, se almacenan como 0 (no aparece boton "Solicitar").
-- Configurable desde Admin RRHH > Parametros de asistencia.
INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
VALUES (
    'ASISTENCIA_HE_MINIMO_MINUTOS',
    '30',
    'int',
    'Minutos minimos de exceso sobre el horario programado para contabilizar como horas extra'
)
ON CONFLICT (clave) DO NOTHING;
