-- 143_cfe_servicio_ocultos.sql
-- Preferencia personal: servicios CFE que un usuario decidio ocultar de su propia
-- vista (no es un borrado — el servicio sigue registrado en CFE y conserva su
-- historial de descargas; "mostrar de nuevo" es solo borrar esta fila). Aplica
-- igual a oym y simulacion, independiente del mecanismo de visibilidad de cada
-- modulo (zona / registradores).

CREATE TABLE IF NOT EXISTS tb_cfe_servicio_ocultos (
    servicio_id UUID        NOT NULL REFERENCES tb_cfe_servicios(id) ON DELETE CASCADE,
    usuario_id  UUID        NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    modulo      TEXT        NOT NULL,
    ocultado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (servicio_id, usuario_id, modulo)
);

-- Filtro de listado: servicios ocultos para (usuario, modulo).
CREATE INDEX IF NOT EXISTS idx_cfe_ocultos_usuario_modulo
    ON tb_cfe_servicio_ocultos (usuario_id, modulo);
