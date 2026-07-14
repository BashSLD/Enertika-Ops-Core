-- Motivo de rechazo cuando RRHH/jefe descarta ("omite") una solicitud de horas extra desde
-- "Horas extra pendientes de aprobacion". Distinto de motivo_solicitud, que es el motivo que
-- da el EMPLEADO al pedir la hora extra, no el motivo del rechazo.
ALTER TABLE tb_asistencia_diaria
  ADD COLUMN IF NOT EXISTS horas_extra_motivo_rechazo TEXT;
