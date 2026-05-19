-- Validacion anual de festivos RRHH para auditar el cierre operativo del calendario.

CREATE TABLE IF NOT EXISTS tb_rrhh_festivos_validacion (
    id          UUID        NOT NULL DEFAULT gen_random_uuid(),
    anio        INTEGER     NOT NULL,
    estado      VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    notas       TEXT,
    validado_at TIMESTAMPTZ,
    validado_by UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_rrhh_festivos_validacion_anio UNIQUE (anio),
    CONSTRAINT ck_rrhh_festivos_validacion_estado
        CHECK (estado IN ('pendiente', 'validado')),
    CONSTRAINT fk_rrhh_festivos_validacion_validado_by
        FOREIGN KEY (validado_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    CONSTRAINT fk_rrhh_festivos_validacion_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_rrhh_festivos_validacion_estado
    ON tb_rrhh_festivos_validacion (estado);
