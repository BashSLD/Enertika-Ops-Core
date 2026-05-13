-- Bitacora anti-duplicados para notificaciones periodicas de vacaciones.

CREATE TABLE IF NOT EXISTS tb_vacaciones_notificaciones_worker (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    clave VARCHAR(120) NOT NULL,
    tipo VARCHAR(40) NOT NULL,
    usuario_id UUID,
    solicitud_id UUID,
    num_periodo INTEGER,
    fecha_objetivo DATE NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_vacaciones_notificaciones_worker_clave UNIQUE (clave),
    CONSTRAINT fk_vac_notif_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_vac_notif_solicitud FOREIGN KEY (solicitud_id)
        REFERENCES tb_solicitudes_ausencia(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_vac_notif_worker_tipo_fecha
    ON tb_vacaciones_notificaciones_worker (tipo, fecha_objetivo);

CREATE INDEX IF NOT EXISTS idx_vac_notif_worker_usuario
    ON tb_vacaciones_notificaciones_worker (usuario_id, tipo);

CREATE INDEX IF NOT EXISTS idx_vac_notif_worker_solicitud
    ON tb_vacaciones_notificaciones_worker (solicitud_id, tipo);
