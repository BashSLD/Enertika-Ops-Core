-- Catalogo de modelos de panel FV y captura de cantidad/modelo usado por proyecto
-- (dato de proyecto, no de version de BOM: ver _Planes_Activos/2026-07-21-bom-captura-paneles-fv.md)

CREATE TABLE IF NOT EXISTS tb_cat_paneles_fv (
    id SERIAL PRIMARY KEY,
    marca VARCHAR NOT NULL,
    modelo VARCHAR NOT NULL,
    potencia_w NUMERIC(10, 2) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (marca, modelo)
);

COMMENT ON TABLE tb_cat_paneles_fv IS 'Catalogo administrable de modelos de panel FV disponibles para captura por proyecto';

INSERT INTO tb_cat_paneles_fv (marca, modelo, potencia_w) VALUES
    ('AE Solar', 'AE585CMD-144', 585),
    ('Canadian Solar', 'CS6W-545MS', 545),
    ('Canadian Solar', 'CS6W-555MS', 555),
    ('Canadian Solar', 'CS7N-665MS', 665),
    ('JA Solar', 'JAM78S10-445/MR', 445),
    ('JA Solar', 'JAM78S10-450/MR', 450),
    ('JA Solar', 'JAM72D40-595/LB', 595),
    ('JA Solar', 'JAM72D42-635/LB', 635),
    ('JA Solar', 'JAM72D42-640/LB', 640),
    ('JA Solar', 'JAM66D46-710/LB', 710),
    ('Longi Solar', 'LR7-72HTHF-615M', 615),
    ('ReneSola', 'RS5J-605NBG-E1', 605),
    ('Risen', 'RSM 110-8-545BMDG', 545),
    ('Risen', 'RSM132-8-655M', 655),
    ('Trina Solar', 'TSM-DE17M(II)-445', 445),
    ('Trina Solar', 'TSM-DE18M(II)-500', 500),
    ('Trina Solar', 'TSM-DE18M(II)-505', 505),
    ('Trina Solar', 'TSM-DE19-550', 550),
    ('Trina Solar', 'TSM-NEG19RC.20-595', 595),
    ('Trina Solar', 'TSM-DE19R-575', 575),
    ('Trina Solar', 'TSM-NE19R-605', 605),
    ('Trina Solar', 'TSM-NE19R-615', 615),
    ('TW Solar', 'TWMNH-66HS615W', 615)
ON CONFLICT (marca, modelo) DO NOTHING;

CREATE TABLE IF NOT EXISTS tb_proyecto_paneles (
    id_proyecto UUID NOT NULL REFERENCES tb_proyectos_gate(id_proyecto) ON DELETE CASCADE,
    id_panel INTEGER NOT NULL REFERENCES tb_cat_paneles_fv(id),
    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    creado_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    actualizado_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id_proyecto, id_panel)
);

COMMENT ON TABLE tb_proyecto_paneles IS 'Modelo(s) de panel FV y cantidad capturados a nivel proyecto, compartidos por todas las versiones del BOM';

CREATE INDEX IF NOT EXISTS idx_proyecto_paneles_id_proyecto ON tb_proyecto_paneles (id_proyecto);
CREATE INDEX IF NOT EXISTS idx_proyecto_paneles_id_panel ON tb_proyecto_paneles (id_panel);
