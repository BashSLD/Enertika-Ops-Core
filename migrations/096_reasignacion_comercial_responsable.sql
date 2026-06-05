-- Separar autoría (creado_por_id) de responsabilidad operativa (responsable_comercial_id) en oportunidades comerciales

-- 1. Nuevo campo en tb_oportunidades
ALTER TABLE tb_oportunidades
    ADD COLUMN IF NOT EXISTS responsable_comercial_id UUID NULL;

-- 2. FK hacia tb_usuarios
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'tb_oportunidades_responsable_comercial_id_fkey'
          AND table_name = 'tb_oportunidades'
    ) THEN
        ALTER TABLE tb_oportunidades
            ADD CONSTRAINT tb_oportunidades_responsable_comercial_id_fkey
            FOREIGN KEY (responsable_comercial_id)
            REFERENCES tb_usuarios(id_usuario);
    END IF;
END $$;

-- 3. Inicializar con el autor original (sólo registros sin valor)
UPDATE tb_oportunidades
SET responsable_comercial_id = creado_por_id
WHERE responsable_comercial_id IS NULL;

-- 4. Índice para filtros y listados por responsable comercial
CREATE INDEX IF NOT EXISTS idx_oportunidades_responsable_comercial
    ON tb_oportunidades(responsable_comercial_id, fecha_solicitud DESC);

-- 5. Tabla de auditoría de transferencias
CREATE TABLE IF NOT EXISTS tb_oportunidades_transferencias (
    id_transferencia        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_oportunidad          UUID NOT NULL
        REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE,
    responsable_anterior_id UUID
        REFERENCES tb_usuarios(id_usuario),
    responsable_nuevo_id    UUID NOT NULL
        REFERENCES tb_usuarios(id_usuario),
    transferido_por_id      UUID NOT NULL
        REFERENCES tb_usuarios(id_usuario),
    motivo                  TEXT,
    fecha_transferencia     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Índice de auditoría por oportunidad y fecha
CREATE INDEX IF NOT EXISTS idx_transferencias_oportunidad_fecha
    ON tb_oportunidades_transferencias(id_oportunidad, fecha_transferencia DESC);
