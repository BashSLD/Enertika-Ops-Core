-- Agrega 'checada_en_compensatorio' al CHECK de tb_asistencia_diaria.estado.
-- Nuevo estado: dia con tiempo compensatorio aprobado (tb_he_solicitudes_compensatorio)
-- en el que el empleado tambien registro checadas -- antes el permiso se descartaba en
-- silencio (solo se aplicaba he_compensatorio cuando NO habia checadas ese dia).

ALTER TABLE tb_asistencia_diaria DROP CONSTRAINT IF EXISTS ck_asistencia_estado;
ALTER TABLE tb_asistencia_diaria
    ADD CONSTRAINT ck_asistencia_estado
    CHECK (
        estado IN (
            'asistencia',
            'vacaciones',
            'ausencia',
            'sin_registro',
            'falta',
            'incompleto',
            'en_curso',
            'descanso',
            'feriado',
            'checada_en_vacaciones',
            'checada_en_ausencia',
            'checada_en_compensatorio',
            'sin_horario',
            'he_compensatorio'
        )
    );
