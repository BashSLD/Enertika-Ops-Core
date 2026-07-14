-- Persiste si RRHH decidio explicitamente que un empleado requiere aprobador exclusivo de horas
-- extra, distinguiendo "nunca decidido" (NULL, sigue sugiriendo el default por departamento
-- Construccion) de "decidido explicitamente que no aplica" (false, nunca mas sugerir el default).
-- true = decidido que si requiere (cubre tanto accion 'asignar' como 'conservar_inactivo').
ALTER TABLE tb_empleados_datos
  ADD COLUMN IF NOT EXISTS requiere_aprobador_he BOOLEAN;
