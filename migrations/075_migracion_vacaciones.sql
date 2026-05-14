-- Agrega soporte para registros historicos de vacaciones cargados por RH.

ALTER TABLE tb_solicitudes_ausencia
    ADD COLUMN IF NOT EXISTS es_migracion BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tb_solicitudes_ausencia
    ADD COLUMN IF NOT EXISTS migrado_por UUID;

DO $$
BEGIN
    ALTER TABLE tb_solicitudes_ausencia
        ADD CONSTRAINT fk_solicitudes_migrado_por
        FOREIGN KEY (migrado_por) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_solicitudes_ausencia_migracion
    ON tb_solicitudes_ausencia (usuario_id, es_migracion)
    WHERE es_migracion = TRUE;

CREATE INDEX IF NOT EXISTS idx_solicitudes_ausencia_migrado_por
    ON tb_solicitudes_ausencia (migrado_por)
    WHERE migrado_por IS NOT NULL;

COMMENT ON COLUMN tb_solicitudes_ausencia.es_migracion IS
    'TRUE = registro historico cargado por RH antes del sistema';

COMMENT ON COLUMN tb_solicitudes_ausencia.migrado_por IS
    'Usuario RH que cargo o confirmo el registro historico';
