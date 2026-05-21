-- Prórrogas individuales de períodos de vacaciones vencidos, otorgadas por RRHH por empleado/período

CREATE TABLE IF NOT EXISTS tb_vacaciones_prorrogas (
    id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id                UUID         NOT NULL REFERENCES tb_usuarios(id_usuario),
    num_periodo               INTEGER      NOT NULL,
    fecha_aniversario_periodo DATE         NOT NULL,
    fecha_expiracion_original DATE         NOT NULL,
    fecha_expiracion_prorroga DATE         NOT NULL,
    dias_prorrogados          INTEGER      NOT NULL,
    motivo                    TEXT         NOT NULL,
    estado                    VARCHAR(20)  NOT NULL DEFAULT 'activa',
    created_by                UUID         NOT NULL REFERENCES tb_usuarios(id_usuario),
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
    cancelled_by              UUID         REFERENCES tb_usuarios(id_usuario),
    cancelled_at              TIMESTAMPTZ,
    motivo_cancelacion        TEXT,

    CONSTRAINT chk_prorrogas_dias_positivos
        CHECK (dias_prorrogados > 0),
    CONSTRAINT chk_prorrogas_fecha_mayor
        CHECK (fecha_expiracion_prorroga > fecha_expiracion_original),
    CONSTRAINT chk_prorrogas_estado
        CHECK (estado IN ('activa', 'cancelada'))
);

CREATE INDEX IF NOT EXISTS idx_vacaciones_prorrogas_usuario_estado
    ON tb_vacaciones_prorrogas (usuario_id, estado);

CREATE INDEX IF NOT EXISTS idx_vacaciones_prorrogas_usuario_periodo
    ON tb_vacaciones_prorrogas (usuario_id, num_periodo, fecha_aniversario_periodo);

-- Garantiza una sola prórroga activa por empleado/período
CREATE UNIQUE INDEX IF NOT EXISTS uq_vacaciones_prorrogas_activa_por_periodo
    ON tb_vacaciones_prorrogas (usuario_id, num_periodo, fecha_aniversario_periodo)
    WHERE estado = 'activa';
