-- Configuracion administrable de vacaciones/RRHH: auditoria de catalogos, feriados generados y firma pendiente.

-- 1. Auditoria y origen para festivos administrables por RH
ALTER TABLE tb_cat_festivos
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

ALTER TABLE tb_cat_festivos
    ADD COLUMN IF NOT EXISTS updated_by UUID;

ALTER TABLE tb_cat_festivos
    ADD COLUMN IF NOT EXISTS origen VARCHAR(20) NOT NULL DEFAULT 'manual';

DO $$
BEGIN
    ALTER TABLE tb_cat_festivos
        ADD CONSTRAINT fk_festivos_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE tb_cat_festivos
        ADD CONSTRAINT ck_festivos_origen
        CHECK (origen IN ('automatico', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_festivos_fecha_anio
    ON tb_cat_festivos ((EXTRACT(YEAR FROM fecha)));

-- 2. Auditoria y proteccion basica para tipos de ausencia
ALTER TABLE tb_cat_tipos_ausencia
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

ALTER TABLE tb_cat_tipos_ausencia
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

ALTER TABLE tb_cat_tipos_ausencia
    ADD COLUMN IF NOT EXISTS updated_by UUID;

ALTER TABLE tb_cat_tipos_ausencia
    ADD COLUMN IF NOT EXISTS es_sistema BOOLEAN NOT NULL DEFAULT false;

DO $$
BEGIN
    ALTER TABLE tb_cat_tipos_ausencia
        ADD CONSTRAINT fk_tipos_ausencia_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

UPDATE tb_cat_tipos_ausencia
SET es_sistema = true
WHERE slug IN ('vacaciones', 'extraordinaria');

CREATE INDEX IF NOT EXISTS idx_tipos_ausencia_active_orden
    ON tb_cat_tipos_ausencia (is_active, orden);

-- 3. Auditoria y baja logica para catalogo de dias por antiguedad
ALTER TABLE tb_cat_dias_vacaciones
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

ALTER TABLE tb_cat_dias_vacaciones
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

ALTER TABLE tb_cat_dias_vacaciones
    ADD COLUMN IF NOT EXISTS updated_by UUID;

ALTER TABLE tb_cat_dias_vacaciones
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

DO $$
BEGIN
    ALTER TABLE tb_cat_dias_vacaciones
        ADD CONSTRAINT fk_dias_vacaciones_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_dias_vacaciones_active
    ON tb_cat_dias_vacaciones (is_active, antiguedad_anios);

-- 4. Solicitudes creadas sin firma: no se notifican ni pasan a aprobacion hasta completar firma
ALTER TABLE tb_solicitudes_ausencia
    ADD COLUMN IF NOT EXISTS firma_solicitante_pendiente BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_solicitudes_pendientes_aprobacion
    ON tb_solicitudes_ausencia (estado, firma_solicitante_pendiente, fecha_solicitud)
    WHERE estado = 'pendiente';
