-- Aprobador exclusivo de horas extra: reemplaza jefe/aprobador de vacaciones para autorizar HE/compensatorio de un empleado especifico
ALTER TABLE tb_empleados_datos ADD COLUMN IF NOT EXISTS id_aprobador_horas_extra UUID NULL;

COMMENT ON COLUMN tb_empleados_datos.id_aprobador_horas_extra IS 'Si no es NULL, unico usuario autorizado para aprobar/omitir/recuperar HE y aprobar/rechazar compensatorio de este empleado; reemplaza jefe directo y aprobador de vacaciones solo para esas acciones';

DO $$ BEGIN
  ALTER TABLE tb_empleados_datos
    ADD CONSTRAINT fk_empleados_aprobador_horas_extra
    FOREIGN KEY (id_aprobador_horas_extra) REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE tb_empleados_datos
    ADD CONSTRAINT chk_empleados_aprobador_horas_extra_no_self
    CHECK (id_aprobador_horas_extra IS DISTINCT FROM usuario_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_empleados_aprobador_horas_extra
  ON tb_empleados_datos (id_aprobador_horas_extra)
  WHERE id_aprobador_horas_extra IS NOT NULL;
