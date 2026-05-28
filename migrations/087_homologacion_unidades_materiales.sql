-- Fase 1: Homologación de unidades y catálogo interno de materiales
-- Nuevas: tb_cat_unidades_medida, tb_cat_unidad_aliases, tb_cat_materiales, tb_materiales_interno_xml
-- Columnas: tb_materiales_historial.unidad_homologada/id_unidad_medida, tb_bom_items.id_material_interno

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 1. Catálogo canónico de unidades de medida
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_cat_unidades_medida (
    id         SERIAL PRIMARY KEY,
    codigo     VARCHAR(20)  UNIQUE NOT NULL,
    nombre     VARCHAR(100) NOT NULL,
    tipo       VARCHAR(20)  NOT NULL
               CHECK (tipo IN ('CONTABLE','PESO','LONGITUD','AREA','VOLUMEN','ENERGIA','TIEMPO','SERVICIO')),
    clave_sat  VARCHAR(10),
    orden      INTEGER DEFAULT 0,
    activo     BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO tb_cat_unidades_medida (codigo, nombre, tipo, clave_sat, orden) VALUES
    ('pza',      'Pieza',          'CONTABLE',  'H87',  1),
    ('lote',     'Lote',           'CONTABLE',   NULL,  2),
    ('servicio', 'Servicio',       'SERVICIO',   NULL,  3),
    ('hr',       'Hora',           'TIEMPO',    'HUR',  4),
    ('dia',      'Dia',            'TIEMPO',     NULL,  5),
    ('global',   'Global',         'SERVICIO',   NULL,  6),
    ('kg',       'Kilogramo',      'PESO',      'KGM',  7),
    ('ton',      'Tonelada',       'PESO',      'TNE',  8),
    ('m',        'Metro lineal',   'LONGITUD',  'MTR',  9),
    ('m2',       'Metro cuadrado', 'AREA',      'MTK', 10),
    ('m3',       'Metro cubico',   'VOLUMEN',   'MTQ', 11),
    ('l',        'Litro',          'VOLUMEN',   'LTR', 12),
    ('kW',       'Kilowatt',       'ENERGIA',    NULL, 13),
    ('kWh',      'Kilowatt hora',  'ENERGIA',    NULL, 14),
    ('kVA',      'Kilovoltampere', 'ENERGIA',    NULL, 15),
    ('MW',       'Megawatt',       'ENERGIA',    NULL, 16),
    ('MWh',      'Megawatt hora',  'ENERGIA',    NULL, 17)
ON CONFLICT (codigo) DO NOTHING;

-- ============================================================
-- 2. Aliases: texto crudo XML/SAT → unidad canónica
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_cat_unidad_aliases (
    id        SERIAL PRIMARY KEY,
    alias     VARCHAR(100) UNIQUE NOT NULL,
    unidad_id INTEGER NOT NULL REFERENCES tb_cat_unidades_medida(id),
    origen    VARCHAR(20) DEFAULT 'MANUAL'
              CHECK (origen IN ('XML','SAT','MANUAL')),
    activo    BOOLEAN DEFAULT TRUE
);

INSERT INTO tb_cat_unidad_aliases (alias, unidad_id, origen)
SELECT src.alias, u.id, src.origen
FROM (VALUES
    ('H87',            'pza', 'SAT'),
    ('PIEZA',          'pza', 'XML'),
    ('PIEZAS',         'pza', 'XML'),
    ('PZA',            'pza', 'XML'),
    ('PZAS',           'pza', 'XML'),
    ('PZ',             'pza', 'XML'),
    ('MTR',            'm',   'SAT'),
    ('MTS',            'm',   'XML'),
    ('MT',             'm',   'XML'),
    ('METRO',          'm',   'XML'),
    ('METROS',         'm',   'XML'),
    ('METRO LINEAL',   'm',   'XML'),
    ('KGM',            'kg',  'SAT'),
    ('KGS',            'kg',  'XML'),
    ('KILOGRAMO',      'kg',  'XML'),
    ('KILOGRAMOS',     'kg',  'XML'),
    ('MTK',            'm2',  'SAT'),
    ('M2',             'm2',  'XML'),
    ('METRO CUADRADO', 'm2',  'XML'),
    ('MTQ',            'm3',  'SAT'),
    ('M3',             'm3',  'XML'),
    ('LTR',            'l',   'SAT'),
    ('LT',             'l',   'XML'),
    ('LTS',            'l',   'XML'),
    ('LITRO',          'l',   'XML'),
    ('LITROS',         'l',   'XML'),
    ('TNE',            'ton', 'SAT'),
    ('TONELADA',       'ton', 'XML'),
    ('TONELADAS',      'ton', 'XML'),
    ('HUR',            'hr',  'SAT'),
    ('HORA',           'hr',  'XML'),
    ('HORAS',          'hr',  'XML'),
    ('HRS',            'hr',  'XML'),
    ('DIA',            'dia', 'XML'),
    ('DIAS',           'dia', 'XML')
) AS src(alias, codigo, origen)
JOIN tb_cat_unidades_medida u ON u.codigo = src.codigo
ON CONFLICT (alias) DO NOTHING;

-- ============================================================
-- 3. Catálogo interno de materiales
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_cat_materiales (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    descripcion_canonica TEXT NOT NULL,
    descripcion_norm     TEXT,
    id_unidad_medida     INTEGER REFERENCES tb_cat_unidades_medida(id),
    id_categoria         INTEGER REFERENCES tb_cat_categorias_compra(id),
    clave_prod_serv      VARCHAR(10),
    precio_referencia    NUMERIC(15,4),
    notas                TEXT,
    activo               BOOLEAN DEFAULT TRUE,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cat_materiales_norm
    ON tb_cat_materiales USING gin (descripcion_norm gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_cat_materiales_clave_sat
    ON tb_cat_materiales(clave_prod_serv);

-- ============================================================
-- 4. Tabla puente: catálogo interno ↔ registros XML (N:N)
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_materiales_interno_xml (
    id_material_interno UUID NOT NULL REFERENCES tb_cat_materiales(id) ON DELETE CASCADE,
    id_material_xml     UUID NOT NULL REFERENCES tb_materiales_historial(id) ON DELETE CASCADE,
    PRIMARY KEY (id_material_interno, id_material_xml),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interno_xml_xml
    ON tb_materiales_interno_xml(id_material_xml);

-- ============================================================
-- 5. Columnas nuevas en tablas existentes
-- ============================================================

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS unidad_homologada VARCHAR(20),
    ADD COLUMN IF NOT EXISTS id_unidad_medida  INTEGER REFERENCES tb_cat_unidades_medida(id);

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS id_material_interno UUID REFERENCES tb_cat_materiales(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_bom_items_interno
    ON tb_bom_items(id_material_interno);
