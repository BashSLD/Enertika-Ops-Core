-- Agrega comida por dia y estado en_curso para asistencia RRHH.

DO $$
DECLARE
    columna_comida_existe BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tb_horarios_sucursal_dias'
          AND column_name = 'descuento_comida_min'
    )
    INTO columna_comida_existe;

    IF NOT columna_comida_existe THEN
        ALTER TABLE tb_horarios_sucursal_dias
            ADD COLUMN descuento_comida_min INTEGER NOT NULL DEFAULT 0;

        UPDATE tb_horarios_sucursal_dias d
        SET descuento_comida_min = CASE
            WHEN d.es_laboral THEN h.descuento_comida_min
            ELSE 0
        END
        FROM tb_horarios_sucursal h
        WHERE d.horario_sucursal_id = h.id;
    END IF;
END $$;

DO $$
BEGIN
    ALTER TABLE tb_horarios_sucursal_dias
        ADD CONSTRAINT ck_horarios_dias_comida
        CHECK (descuento_comida_min >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE tb_asistencia_diaria
    DROP CONSTRAINT IF EXISTS ck_asistencia_estado;

ALTER TABLE tb_asistencia_diaria
    ADD CONSTRAINT ck_asistencia_estado CHECK (
        estado IN (
            'asistencia',
            'vacaciones',
            'sin_registro',
            'falta',
            'incompleto',
            'en_curso',
            'descanso',
            'feriado',
            'checada_en_vacaciones',
            'sin_horario'
        )
    );

COMMENT ON COLUMN tb_horarios_sucursal_dias.descuento_comida_min IS
    'Minutos de comida descontados para este dia especifico del horario';
