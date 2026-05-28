-- 089: saneamiento unidades historial
-- Agrega aliases SAT que no estaban en el seed (087) y puebla
-- unidad_homologada / id_unidad_medida en registros históricos existentes.

-- 1. Nuevos aliases SAT faltantes
INSERT INTO tb_cat_unidad_aliases (alias, unidad_id, origen) VALUES
    ('EA',  (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'pza'),      'SAT'),
    ('XUN', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'pza'),      'SAT'),
    ('E48', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'servicio'), 'SAT'),
    ('ACT', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'global'),   'SAT'),
    ('XRO', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'lote'),     'SAT'),
    ('XPK', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'lote'),     'SAT')
ON CONFLICT (alias) DO NOTHING;

-- 2. Nuevos aliases de texto libre no cubiertos
INSERT INTO tb_cat_unidad_aliases (alias, unidad_id, origen) VALUES
    ('UNIDAD',   (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'pza'),      'XML'),
    ('UNIDADES', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'pza'),      'XML'),
    ('SERVICIO', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'servicio'), 'XML')
ON CONFLICT (alias) DO NOTHING;

-- 2b. Aliases residuales (PR, GLL, X4G, XKI — 8 registros no resueltos en paso inicial)
INSERT INTO tb_cat_unidad_aliases (alias, unidad_id, origen) VALUES
    ('PR',  (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'pza'),  'SAT'),
    ('GLL', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'l'),    'SAT'),
    ('X4G', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'lote'), 'SAT'),
    ('XKI', (SELECT id FROM tb_cat_unidades_medida WHERE codigo = 'lote'), 'SAT')
ON CONFLICT (alias) DO NOTHING;

-- 3. Poblar via clave SAT (fuente más confiable)
UPDATE tb_materiales_historial m
SET id_unidad_medida  = a.unidad_id,
    unidad_homologada = u.codigo
FROM tb_cat_unidad_aliases a
JOIN tb_cat_unidades_medida u ON u.id = a.unidad_id
WHERE UPPER(TRIM(m.clave_unidad)) = a.alias
  AND m.id_unidad_medida IS NULL;

-- 4. Poblar via texto de unidad como fallback (clave vacía o no reconocida)
UPDATE tb_materiales_historial m
SET id_unidad_medida  = a.unidad_id,
    unidad_homologada = u.codigo
FROM tb_cat_unidad_aliases a
JOIN tb_cat_unidades_medida u ON u.id = a.unidad_id
WHERE UPPER(TRIM(m.unidad)) = a.alias
  AND m.id_unidad_medida IS NULL;
