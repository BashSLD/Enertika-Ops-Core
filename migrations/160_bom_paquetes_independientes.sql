-- 160: Identidad logica de paquetes BOM, backfill legacy e invariantes de aislamiento.
--
-- La migracion es aditiva salvo por la unicidad historica (proyecto, version), que se
-- reemplaza por (paquete, version). No recrea IDs existentes ni aplica DDL remoto desde
-- la aplicacion. La flag nace apagada para conservar el comportamiento legacy.

-- -----------------------------------------------------------------------------
-- 1. Entidad logica y columnas de version
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tb_bom_paquetes (
    id_paquete UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_proyecto UUID NOT NULL REFERENCES tb_proyectos_gate(id_proyecto) ON DELETE RESTRICT,
    codigo VARCHAR(30) NOT NULL,
    nombre VARCHAR(160) NOT NULL,
    tipo_alcance VARCHAR(20) NOT NULL,
    descripcion_alcance TEXT,
    estado_paquete VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    lock_version INTEGER NOT NULL DEFAULT 0,
    creado_por UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    ingeniero_responsable_id UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    responsable_ing_id UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    coordinador_obra_id UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    jefe_construccion_id UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    clave_idempotencia VARCHAR(120),
    cabeza_trabajo_id UUID,
    cabeza_oficial_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_paquetes_tipo_alcance_check
        CHECK (tipo_alcance IN ('COMPLETO', 'PARCIAL', 'LEGACY')),
    CONSTRAINT tb_bom_paquetes_estado_check
        CHECK (estado_paquete IN ('ACTIVO', 'ARCHIVADO', 'CANCELADO')),
    CONSTRAINT tb_bom_paquetes_lock_version_check CHECK (lock_version >= 0),
    CONSTRAINT uq_bom_paquetes_proyecto_codigo UNIQUE (id_proyecto, codigo),
    CONSTRAINT uq_bom_paquetes_id_proyecto UNIQUE (id_paquete, id_proyecto),
    CONSTRAINT uq_bom_paquetes_proyecto_idempotencia
        UNIQUE (id_proyecto, clave_idempotencia)
);

ALTER TABLE tb_bom_paquetes
    ADD COLUMN IF NOT EXISTS clave_idempotencia VARCHAR(120);

ALTER TABLE tb_bom
    ADD COLUMN IF NOT EXISTS id_paquete UUID,
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ingeniero_responsable_id UUID,
    ADD COLUMN IF NOT EXISTS tipo_cambio_aprobacion NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS fecha_tipo_cambio_aprobacion DATE,
    ADD COLUMN IF NOT EXISTS subtotal_base_mxn_snapshot NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS subtotal_base_usd_snapshot NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS total_aprobado_mxn NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS modulos_fv_snapshot INTEGER,
    ADD COLUMN IF NOT EXISTS potencia_pico_kwp_snapshot NUMERIC(16,6);

ALTER TABLE tb_bom DROP CONSTRAINT IF EXISTS tb_bom_lock_version_check;
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_lock_version_check
    CHECK (lock_version >= 0);

ALTER TABLE tb_bom DROP CONSTRAINT IF EXISTS tb_bom_snapshots_fv_check;
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_snapshots_fv_check
    CHECK (
        (modulos_fv_snapshot IS NULL AND potencia_pico_kwp_snapshot IS NULL)
        OR (
            modulos_fv_snapshot > 0
            AND potencia_pico_kwp_snapshot > 0
        )
    );

ALTER TABLE tb_bom DROP CONSTRAINT IF EXISTS tb_bom_snapshot_moneda_check;
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_snapshot_moneda_check
    CHECK (
        (
            tipo_cambio_aprobacion IS NULL
            AND fecha_tipo_cambio_aprobacion IS NULL
            AND subtotal_base_mxn_snapshot IS NULL
            AND subtotal_base_usd_snapshot IS NULL
            AND total_aprobado_mxn IS NULL
        )
        OR (
            subtotal_base_mxn_snapshot >= 0
            AND subtotal_base_usd_snapshot >= 0
            AND total_aprobado_mxn >= 0
            AND (
                (
                    subtotal_base_usd_snapshot = 0
                    AND tipo_cambio_aprobacion IS NULL
                    AND fecha_tipo_cambio_aprobacion IS NULL
                )
                OR (
                    tipo_cambio_aprobacion > 0
                    AND fecha_tipo_cambio_aprobacion IS NOT NULL
                )
            )
            AND ABS(
                total_aprobado_mxn
                - subtotal_base_mxn_snapshot
                - subtotal_base_usd_snapshot * COALESCE(tipo_cambio_aprobacion, 0)
            ) <= 0.01
        )
    );

-- La unicidad historica de la migracion 086 impedia que el mismo usuario fuera
-- Ingeniero de Diseno y RI. Estos dos indices complementarios permiten solo esa
-- pareja; cualquier otra combinacion de roles activos en un area sigue violando
-- al menos uno de ellos, incluso si las inserciones compiten.
DROP INDEX IF EXISTS uq_proyecto_usuario_area_activo;
CREATE UNIQUE INDEX uq_proyecto_usuario_area_activo
    ON tb_proyecto_usuarios (id_proyecto, id_usuario, area)
    WHERE activo = TRUE
      AND NOT (
          area = 'INGENIERIA'
          AND rol_proyecto = 'responsable_ingenieria'
      );

DROP INDEX IF EXISTS uq_proyecto_usuario_area_activo_sin_ingeniero;
CREATE UNIQUE INDEX uq_proyecto_usuario_area_activo_sin_ingeniero
    ON tb_proyecto_usuarios (id_proyecto, id_usuario, area)
    WHERE activo = TRUE
      AND NOT (
          area = 'INGENIERIA'
          AND rol_proyecto = 'ingeniero_asignado'
      );

-- -----------------------------------------------------------------------------
-- 2. Auditoria previa y backfill legacy determinista
-- -----------------------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tb_bom
        WHERE id_paquete IS NULL
        GROUP BY id_proyecto, version
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: existen versiones duplicadas por proyecto';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom
        WHERE id_paquete IS NULL
          AND estatus NOT IN ('APROBADO_FINAL', 'CANCELADO')
        GROUP BY id_proyecto
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: existe mas de una version no terminal en un proyecto legacy';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom
        WHERE id_paquete IS NULL
        GROUP BY id_proyecto
        HAVING MIN(version) <> 1 OR COUNT(*) <> MAX(version)
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: existe una cadena de versiones legacy discontinua';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_items hijo
        JOIN tb_bom_items padre ON padre.id_item = hijo.id_item_origen
        JOIN tb_bom bom_hijo ON bom_hijo.id_bom = hijo.id_bom
        JOIN tb_bom bom_padre ON bom_padre.id_bom = padre.id_bom
        WHERE bom_hijo.id_proyecto <> bom_padre.id_proyecto
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: genealogia de items cruza proyectos';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_cotizacion_items linea
        JOIN tb_bom_cotizaciones cot ON cot.id = linea.cotizacion_id
        JOIN tb_bom_items item ON item.id_item = linea.bom_item_id
        WHERE cot.bom_id <> item.id_bom
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: una cotizacion contiene items de otro BOM';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_cotizaciones respuesta
        JOIN tb_bom_cotizaciones rfq ON rfq.id = respuesta.rfq_origen_id
        WHERE respuesta.bom_id <> rfq.bom_id
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: una respuesta de cotizacion pertenece a otro BOM que su RFQ';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_autorizaciones aut
        JOIN tb_bom_cotizaciones cot ON cot.id = aut.cotizacion_id
        JOIN tb_bom bom ON bom.id_bom = aut.bom_id
        WHERE aut.bom_id <> cot.bom_id OR aut.proyecto_id <> bom.id_proyecto
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: autorizaciones con BOM o proyecto incompatible';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_cotizacion_aprobaciones apr
        JOIN tb_bom_cotizaciones cot ON cot.id = apr.cotizacion_id
        JOIN tb_bom bom ON bom.id_bom = apr.bom_id
        WHERE apr.bom_id <> cot.bom_id OR apr.proyecto_id <> bom.id_proyecto
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: aprobaciones documentales incompatibles';
    END IF;
END $$;

WITH primer_bom AS (
    SELECT DISTINCT ON (id_proyecto)
        id_proyecto,
        elaborado_por,
        created_at
    FROM tb_bom
    WHERE id_paquete IS NULL
    ORDER BY id_proyecto, version ASC, created_at ASC, id_bom ASC
), estado_legacy AS (
    SELECT
        p.id_proyecto,
        p.elaborado_por,
        p.created_at,
        CASE
            WHEN EXISTS (
                SELECT 1 FROM tb_bom b
                WHERE b.id_proyecto = p.id_proyecto
                  AND b.estatus <> 'CANCELADO'
            ) THEN 'ACTIVO'
            ELSE 'CANCELADO'
        END AS estado_paquete
    FROM primer_bom p
)
INSERT INTO tb_bom_paquetes (
    id_proyecto,
    codigo,
    nombre,
    tipo_alcance,
    descripcion_alcance,
    estado_paquete,
    creado_por,
    ingeniero_responsable_id,
    created_at,
    updated_at
)
SELECT
    id_proyecto,
    'LEGACY',
    'BOM legado',
    'LEGACY',
    'Paquete creado automaticamente para preservar las versiones anteriores.',
    estado_paquete,
    elaborado_por,
    elaborado_por,
    COALESCE(created_at, NOW()),
    NOW()
FROM estado_legacy
ON CONFLICT (id_proyecto, codigo) DO NOTHING;

UPDATE tb_bom b
SET id_paquete = p.id_paquete,
    ingeniero_responsable_id = COALESCE(b.ingeniero_responsable_id, b.elaborado_por)
FROM tb_bom_paquetes p
WHERE p.id_proyecto = b.id_proyecto
  AND p.codigo = 'LEGACY'
  AND (
      b.id_paquete IS NULL
      OR b.ingeniero_responsable_id IS NULL
  );

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM tb_bom WHERE id_paquete IS NULL) THEN
        RAISE EXCEPTION 'BOM multi-paquete: el backfill dejo versiones sin paquete';
    END IF;
END $$;

ALTER TABLE tb_bom
    ALTER COLUMN id_paquete SET NOT NULL,
    ALTER COLUMN ingeniero_responsable_id SET NOT NULL;

ALTER TABLE tb_bom DROP CONSTRAINT IF EXISTS tb_bom_id_proyecto_version_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_paquete_version'
          AND conrelid = 'tb_bom'::regclass
    ) THEN
        ALTER TABLE tb_bom
            ADD CONSTRAINT uq_bom_paquete_version UNIQUE (id_paquete, version);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_id_paquete'
          AND conrelid = 'tb_bom'::regclass
    ) THEN
        ALTER TABLE tb_bom
            ADD CONSTRAINT uq_bom_id_paquete UNIQUE (id_bom, id_paquete);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_id_proyecto'
          AND conrelid = 'tb_bom'::regclass
    ) THEN
        ALTER TABLE tb_bom
            ADD CONSTRAINT uq_bom_id_proyecto UNIQUE (id_bom, id_proyecto);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_paquete_proyecto'
          AND conrelid = 'tb_bom'::regclass
    ) THEN
        ALTER TABLE tb_bom
            ADD CONSTRAINT fk_bom_paquete_proyecto
            FOREIGN KEY (id_paquete, id_proyecto)
            REFERENCES tb_bom_paquetes(id_paquete, id_proyecto)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_ingeniero_responsable'
          AND conrelid = 'tb_bom'::regclass
    ) THEN
        ALTER TABLE tb_bom
            ADD CONSTRAINT fk_bom_ingeniero_responsable
            FOREIGN KEY (ingeniero_responsable_id)
            REFERENCES tb_usuarios(id_usuario)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_paquete_no_terminal
    ON tb_bom(id_paquete)
    WHERE estatus NOT IN ('APROBADO_FINAL', 'CANCELADO');

CREATE INDEX IF NOT EXISTS idx_bom_paquete_version
    ON tb_bom(id_paquete, version DESC);

CREATE INDEX IF NOT EXISTS idx_bom_paquete_estatus
    ON tb_bom(id_paquete, estatus);

CREATE INDEX IF NOT EXISTS idx_bom_ingeniero_responsable
    ON tb_bom(ingeniero_responsable_id);

CREATE INDEX IF NOT EXISTS idx_bom_paquetes_creado_por
    ON tb_bom_paquetes(creado_por);

CREATE INDEX IF NOT EXISTS idx_bom_paquetes_ingeniero
    ON tb_bom_paquetes(ingeniero_responsable_id);

CREATE INDEX IF NOT EXISTS idx_bom_paquetes_responsable_ing
    ON tb_bom_paquetes(responsable_ing_id)
    WHERE responsable_ing_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_paquetes_coordinador_obra
    ON tb_bom_paquetes(coordinador_obra_id)
    WHERE coordinador_obra_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_paquetes_jefe_construccion
    ON tb_bom_paquetes(jefe_construccion_id)
    WHERE jefe_construccion_id IS NOT NULL;

WITH cabeza_trabajo AS (
    SELECT DISTINCT ON (id_paquete)
        id_paquete,
        id_bom
    FROM tb_bom
    WHERE estatus <> 'CANCELADO'
    ORDER BY id_paquete, version DESC, id_bom DESC
), cabeza_oficial AS (
    SELECT DISTINCT ON (id_paquete)
        id_paquete,
        id_bom
    FROM tb_bom
    WHERE estatus = 'APROBADO_FINAL'
    ORDER BY id_paquete, version DESC, id_bom DESC
)
UPDATE tb_bom_paquetes p
SET cabeza_trabajo_id = t.id_bom,
    cabeza_oficial_id = o.id_bom,
    updated_at = NOW()
FROM cabeza_trabajo t
LEFT JOIN cabeza_oficial o ON o.id_paquete = t.id_paquete
WHERE p.id_paquete = t.id_paquete
  AND (p.cabeza_trabajo_id IS DISTINCT FROM t.id_bom
       OR p.cabeza_oficial_id IS DISTINCT FROM o.id_bom);

UPDATE tb_bom_paquetes p
SET ingeniero_responsable_id = b.ingeniero_responsable_id,
    responsable_ing_id = b.responsable_ing,
    coordinador_obra_id = b.coordinador_obra,
    jefe_construccion_id = b.jefe_construccion,
    updated_at = NOW()
FROM tb_bom b
WHERE b.id_bom = p.cabeza_trabajo_id
  AND (p.ingeniero_responsable_id IS DISTINCT FROM b.ingeniero_responsable_id
       OR p.responsable_ing_id IS DISTINCT FROM b.responsable_ing
       OR p.coordinador_obra_id IS DISTINCT FROM b.coordinador_obra
       OR p.jefe_construccion_id IS DISTINCT FROM b.jefe_construccion);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_paquete_cabeza_trabajo'
          AND conrelid = 'tb_bom_paquetes'::regclass
    ) THEN
        ALTER TABLE tb_bom_paquetes
            ADD CONSTRAINT fk_bom_paquete_cabeza_trabajo
            FOREIGN KEY (cabeza_trabajo_id, id_paquete)
            REFERENCES tb_bom(id_bom, id_paquete)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_paquete_cabeza_oficial'
          AND conrelid = 'tb_bom_paquetes'::regclass
    ) THEN
        ALTER TABLE tb_bom_paquetes
            ADD CONSTRAINT fk_bom_paquete_cabeza_oficial
            FOREIGN KEY (cabeza_oficial_id, id_paquete)
            REFERENCES tb_bom(id_bom, id_paquete)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_paquetes_cabeza_trabajo
    ON tb_bom_paquetes(cabeza_trabajo_id, id_paquete)
    WHERE cabeza_trabajo_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_paquetes_cabeza_oficial
    ON tb_bom_paquetes(cabeza_oficial_id, id_paquete)
    WHERE cabeza_oficial_id IS NOT NULL;

CREATE OR REPLACE FUNCTION fn_validar_cabeza_trabajo_bom()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    paquete_actual tb_bom_paquetes%ROWTYPE;
    cabeza_trabajo_esperada UUID;
    cabeza_oficial_esperada UUID;
BEGIN
    SELECT * INTO paquete_actual
    FROM tb_bom_paquetes
    WHERE id_paquete = NEW.id_paquete;

    IF paquete_actual.estado_paquete = 'ACTIVO'
       AND paquete_actual.cabeza_trabajo_id IS NULL THEN
        RAISE EXCEPTION 'Un paquete BOM activo debe tener cabeza de trabajo';
    END IF;
    SELECT id_bom INTO cabeza_trabajo_esperada
    FROM tb_bom
    WHERE id_paquete = NEW.id_paquete AND estatus <> 'CANCELADO'
    ORDER BY version DESC, id_bom DESC
    LIMIT 1;
    SELECT id_bom INTO cabeza_oficial_esperada
    FROM tb_bom
    WHERE id_paquete = NEW.id_paquete AND estatus = 'APROBADO_FINAL'
    ORDER BY version DESC, id_bom DESC
    LIMIT 1;
    IF paquete_actual.cabeza_trabajo_id IS DISTINCT FROM cabeza_trabajo_esperada
       OR paquete_actual.cabeza_oficial_id IS DISTINCT FROM cabeza_oficial_esperada THEN
        RAISE EXCEPTION 'Las cabezas del paquete BOM no coinciden con sus versiones vigentes';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validar_cabeza_trabajo_bom ON tb_bom_paquetes;
CREATE CONSTRAINT TRIGGER trg_validar_cabeza_trabajo_bom
AFTER INSERT OR UPDATE OF estado_paquete, cabeza_trabajo_id, cabeza_oficial_id
ON tb_bom_paquetes
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION fn_validar_cabeza_trabajo_bom();

CREATE OR REPLACE FUNCTION fn_validar_cabezas_desde_version_bom()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    paquete_actual tb_bom_paquetes%ROWTYPE;
    cabeza_trabajo_esperada UUID;
    cabeza_oficial_esperada UUID;
BEGIN
    SELECT * INTO paquete_actual
    FROM tb_bom_paquetes
    WHERE id_paquete = NEW.id_paquete;
    SELECT id_bom INTO cabeza_trabajo_esperada
    FROM tb_bom
    WHERE id_paquete = NEW.id_paquete AND estatus <> 'CANCELADO'
    ORDER BY version DESC, id_bom DESC
    LIMIT 1;
    SELECT id_bom INTO cabeza_oficial_esperada
    FROM tb_bom
    WHERE id_paquete = NEW.id_paquete AND estatus = 'APROBADO_FINAL'
    ORDER BY version DESC, id_bom DESC
    LIMIT 1;
    IF paquete_actual.cabeza_trabajo_id IS DISTINCT FROM cabeza_trabajo_esperada
       OR paquete_actual.cabeza_oficial_id IS DISTINCT FROM cabeza_oficial_esperada THEN
        RAISE EXCEPTION 'Las cabezas del paquete BOM no coinciden con sus versiones vigentes';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validar_cabezas_desde_version_bom ON tb_bom;
CREATE CONSTRAINT TRIGGER trg_validar_cabezas_desde_version_bom
AFTER INSERT OR UPDATE OF estatus, id_paquete, version
ON tb_bom
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION fn_validar_cabezas_desde_version_bom();

-- -----------------------------------------------------------------------------
-- 3. Estado del conjunto BOM por proyecto
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tb_bom_proyecto_estado (
    id_proyecto UUID PRIMARY KEY REFERENCES tb_proyectos_gate(id_proyecto) ON DELETE RESTRICT,
    captura_cerrada BOOLEAN NOT NULL DEFAULT FALSE,
    cerrada_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    cerrada_en TIMESTAMPTZ,
    motivo TEXT,
    actualizado_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    cambio_estado_en TIMESTAMPTZ,
    modulos_fv_snapshot INTEGER,
    potencia_pico_kwp_snapshot NUMERIC(20,6),
    lock_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_proyecto_estado_lock_check CHECK (lock_version >= 0),
    CONSTRAINT tb_bom_proyecto_estado_cierre_check CHECK (
        (
            captura_cerrada = FALSE
            AND cerrada_por IS NULL
            AND cerrada_en IS NULL
            AND motivo IS NULL
            AND actualizado_por IS NULL
            AND cambio_estado_en IS NULL
        )
        OR (
            motivo IS NOT NULL
            AND actualizado_por IS NOT NULL
            AND cambio_estado_en IS NOT NULL
            AND (
                (
                    captura_cerrada = TRUE
                    AND cerrada_por IS NOT NULL
                    AND cerrada_en IS NOT NULL
                )
                OR (
                    captura_cerrada = FALSE
                    AND cerrada_por IS NULL
                    AND cerrada_en IS NULL
                )
            )
        )
    ),
    CONSTRAINT tb_bom_proyecto_estado_fv_check CHECK (
        (modulos_fv_snapshot IS NULL AND potencia_pico_kwp_snapshot IS NULL)
        OR (modulos_fv_snapshot > 0 AND potencia_pico_kwp_snapshot > 0)
    )
);

ALTER TABLE tb_bom_proyecto_estado
    ADD COLUMN IF NOT EXISTS actualizado_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS cambio_estado_en TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS modulos_fv_snapshot INTEGER,
    ADD COLUMN IF NOT EXISTS potencia_pico_kwp_snapshot NUMERIC(20,6);

INSERT INTO tb_bom_proyecto_estado (
    id_proyecto,
    captura_cerrada,
    cerrada_por,
    cerrada_en,
    motivo,
    actualizado_por,
    cambio_estado_en
)
SELECT
    p.id_proyecto,
    TRUE,
    p.creado_por,
    NOW(),
    'Cierre automatico del conjunto BOM legacy durante el backfill.',
    p.creado_por,
    NOW()
FROM tb_bom_paquetes p
WHERE p.tipo_alcance = 'LEGACY'
ON CONFLICT (id_proyecto) DO NOTHING;

-- No se reconstruyen snapshots FV historicos con la configuracion actual. Sin una
-- bitacora temporal que pruebe los paneles vigentes al cierre/aprobacion, deben
-- permanecer NULL y ser auditados como pendientes de reconciliacion manual.

-- Tampoco se reconstruyen snapshots monetarios de aprobaciones historicas a
-- partir de items vivos o de un TC actual. Los snapshots nuevos se generan en la
-- transaccion de aprobacion; los legacy quedan NULL hasta conciliacion manual.

-- -----------------------------------------------------------------------------
-- 4. Identidad estable de linea y genealogia por paquete
-- -----------------------------------------------------------------------------

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS id_paquete UUID,
    ADD COLUMN IF NOT EXISTS id_linea_bom UUID,
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

UPDATE tb_bom_items i
SET id_paquete = b.id_paquete
FROM tb_bom b
WHERE b.id_bom = i.id_bom
  AND i.id_paquete IS NULL;

ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS tb_bom_items_lock_version_check;
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_lock_version_check
    CHECK (lock_version >= 0);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM tb_bom_items
        WHERE moneda IS NULL OR moneda NOT IN ('MXN', 'USD')
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: existen items con moneda desconocida; reconciliar antes de migrar';
    END IF;
END $$;
ALTER TABLE tb_bom_items ALTER COLUMN moneda SET NOT NULL;
ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS tb_bom_items_importes_check;
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_importes_check
    CHECK (
        cantidad > 0
        AND (precio_unitario IS NULL OR precio_unitario >= 0)
        AND moneda IS NOT NULL
        AND moneda IN ('MXN', 'USD')
    );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tb_bom_items hijo
        JOIN tb_bom_items origen ON origen.id_item = hijo.id_item_origen
        JOIN tb_bom bh ON bh.id_bom = hijo.id_bom
        JOIN tb_bom bo ON bo.id_bom = origen.id_bom
        WHERE hijo.id_paquete <> origen.id_paquete
           OR bh.version <= bo.version
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: origen genealogico cruza paquete o no avanza de version';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_items nuevo
        JOIN tb_bom_items anterior ON anterior.id_item = nuevo.id_item_reemplazado
        WHERE nuevo.id_item = anterior.id_item
           OR nuevo.id_paquete <> anterior.id_paquete
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: reemplazo ciclico o cross-paquete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_items hijo
        JOIN tb_bom b ON b.id_bom = hijo.id_bom
        WHERE hijo.id_item_origen IS NOT NULL
        GROUP BY hijo.id_item_origen, b.version
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: una linea origen tiene multiples descendientes en la misma version';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS tb_bom_lineas (
    id_linea_bom UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_paquete UUID NOT NULL REFERENCES tb_bom_paquetes(id_paquete) ON DELETE RESTRICT,
    id_linea_reemplazada UUID,
    id_item_raiz_legacy UUID UNIQUE,
    creado_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bom_lineas_id_paquete UNIQUE (id_linea_bom, id_paquete),
    CONSTRAINT uq_bom_lineas_raiz_paquete UNIQUE (id_item_raiz_legacy, id_paquete)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_linea_reemplazada_paquete'
          AND conrelid = 'tb_bom_lineas'::regclass
    ) THEN
        ALTER TABLE tb_bom_lineas
            ADD CONSTRAINT fk_bom_linea_reemplazada_paquete
            FOREIGN KEY (id_linea_reemplazada, id_paquete)
            REFERENCES tb_bom_lineas(id_linea_bom, id_paquete)
            ON DELETE RESTRICT;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE alcanzables AS (
            SELECT i.id_item, ARRAY[i.id_item] AS camino
            FROM tb_bom_items i
            WHERE i.id_item_origen IS NULL
            UNION ALL
            SELECT hijo.id_item, padre.camino || hijo.id_item
            FROM alcanzables padre
            JOIN tb_bom_items hijo ON hijo.id_item_origen = padre.id_item
            WHERE NOT hijo.id_item = ANY(padre.camino)
        )
        SELECT 1
        FROM tb_bom_items i
        WHERE NOT EXISTS (
            SELECT 1 FROM alcanzables a WHERE a.id_item = i.id_item
        )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: genealogia ciclica o sin raiz en tb_bom_items';
    END IF;
END $$;

INSERT INTO tb_bom_lineas (
    id_paquete,
    id_item_raiz_legacy,
    creado_por,
    created_at
)
SELECT
    raiz.id_paquete,
    raiz.id_item,
    bom.elaborado_por,
    COALESCE(raiz.created_at, NOW())
FROM tb_bom_items raiz
JOIN tb_bom bom ON bom.id_bom = raiz.id_bom
WHERE raiz.id_item_origen IS NULL
  AND raiz.id_linea_bom IS NULL
ON CONFLICT (id_item_raiz_legacy) DO NOTHING;

WITH RECURSIVE genealogia AS (
    SELECT
        raiz.id_item,
        raiz.id_item AS id_raiz,
        raiz.id_paquete
    FROM tb_bom_items raiz
    WHERE raiz.id_item_origen IS NULL

    UNION ALL

    SELECT
        hijo.id_item,
        padre.id_raiz,
        hijo.id_paquete
    FROM genealogia padre
    JOIN tb_bom_items hijo ON hijo.id_item_origen = padre.id_item
)
UPDATE tb_bom_items item
SET id_linea_bom = linea.id_linea_bom
FROM genealogia g
JOIN tb_bom_lineas linea
  ON linea.id_item_raiz_legacy = g.id_raiz
 AND linea.id_paquete = g.id_paquete
WHERE item.id_item = g.id_item
  AND item.id_linea_bom IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT nuevo.id_linea_bom, nuevo.id_paquete
        FROM tb_bom_items nuevo
        JOIN tb_bom_items anterior
          ON anterior.id_item = nuevo.id_item_reemplazado
        WHERE nuevo.id_item_reemplazado IS NOT NULL
        GROUP BY nuevo.id_linea_bom, nuevo.id_paquete
        HAVING COUNT(DISTINCT anterior.id_linea_bom) > 1
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: una linea de reemplazo tiene origenes estables ambiguos';
    END IF;
END $$;

WITH reemplazos AS (
    SELECT DISTINCT
        nuevo.id_linea_bom,
        nuevo.id_paquete,
        anterior.id_linea_bom AS id_linea_reemplazada
    FROM tb_bom_items nuevo
    JOIN tb_bom_items anterior
      ON anterior.id_item = nuevo.id_item_reemplazado
    WHERE nuevo.id_item_reemplazado IS NOT NULL
)
UPDATE tb_bom_lineas linea
SET id_linea_reemplazada = reemplazos.id_linea_reemplazada
FROM reemplazos
WHERE linea.id_linea_bom = reemplazos.id_linea_bom
  AND linea.id_paquete = reemplazos.id_paquete
  AND linea.id_linea_reemplazada IS NULL;

DO $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE recorrido AS (
            SELECT linea.id_linea_bom AS inicio,
                   linea.id_linea_bom AS actual,
                   linea.id_linea_reemplazada AS siguiente,
                   ARRAY[linea.id_linea_bom] AS camino,
                   FALSE AS ciclo
            FROM tb_bom_lineas linea
            UNION ALL
            SELECT recorrido.inicio,
                   linea.id_linea_bom,
                   linea.id_linea_reemplazada,
                   recorrido.camino || linea.id_linea_bom,
                   linea.id_linea_bom = ANY(recorrido.camino)
            FROM recorrido
            JOIN tb_bom_lineas linea
              ON linea.id_linea_bom = recorrido.siguiente
            WHERE recorrido.siguiente IS NOT NULL AND NOT recorrido.ciclo
        )
        SELECT 1 FROM recorrido WHERE ciclo
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: ciclo detectado en lineas estables reemplazadas';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM tb_bom_items
        WHERE id_paquete IS NULL OR id_linea_bom IS NULL
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: el backfill dejo items sin paquete o linea estable';
    END IF;
END $$;

ALTER TABLE tb_bom_items
    ALTER COLUMN id_paquete SET NOT NULL,
    ALTER COLUMN id_linea_bom SET NOT NULL;

ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS fk_bom_items_origen;
ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS fk_bom_items_reemplazado;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_items_id_paquete'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT uq_bom_items_id_paquete UNIQUE (id_item, id_paquete);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_items_id_bom'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT uq_bom_items_id_bom UNIQUE (id_item, id_bom);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_items_bom_linea'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT uq_bom_items_bom_linea UNIQUE (id_bom, id_linea_bom);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_items_identidad_completa'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT uq_bom_items_identidad_completa
            UNIQUE (id_item, id_bom, id_paquete, id_linea_bom);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_items_bom_paquete'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT fk_bom_items_bom_paquete
            FOREIGN KEY (id_bom, id_paquete)
            REFERENCES tb_bom(id_bom, id_paquete)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_lineas_raiz_paquete'
          AND conrelid = 'tb_bom_lineas'::regclass
    ) THEN
        ALTER TABLE tb_bom_lineas
            ADD CONSTRAINT fk_bom_lineas_raiz_paquete
            FOREIGN KEY (id_item_raiz_legacy, id_paquete)
            REFERENCES tb_bom_items(id_item, id_paquete)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_items_linea_paquete'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT fk_bom_items_linea_paquete
            FOREIGN KEY (id_linea_bom, id_paquete)
            REFERENCES tb_bom_lineas(id_linea_bom, id_paquete)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_items_origen_paquete'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT fk_bom_items_origen_paquete
            FOREIGN KEY (id_item_origen, id_paquete)
            REFERENCES tb_bom_items(id_item, id_paquete)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_items_reemplazado_paquete'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT fk_bom_items_reemplazado_paquete
            FOREIGN KEY (id_item_reemplazado, id_paquete)
            REFERENCES tb_bom_items(id_item, id_paquete)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_items_paquete_linea
    ON tb_bom_items(id_paquete, id_linea_bom);

CREATE INDEX IF NOT EXISTS idx_bom_lineas_reemplazada_paquete
    ON tb_bom_lineas(id_linea_reemplazada, id_paquete)
    WHERE id_linea_reemplazada IS NOT NULL;

CREATE OR REPLACE FUNCTION fn_bom_validar_genealogia_item()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    version_nueva INTEGER;
    origen RECORD;
    reemplazada RECORD;
BEGIN
    SELECT version INTO version_nueva FROM tb_bom WHERE id_bom = NEW.id_bom;

    IF NEW.id_item_origen IS NOT NULL THEN
        SELECT item.id_paquete, item.id_linea_bom, bom.version
        INTO origen
        FROM tb_bom_items item
        JOIN tb_bom bom ON bom.id_bom = item.id_bom
        WHERE item.id_item = NEW.id_item_origen;
        IF NOT FOUND
           OR origen.id_paquete <> NEW.id_paquete
           OR origen.id_linea_bom <> NEW.id_linea_bom
           OR origen.version >= version_nueva THEN
            RAISE EXCEPTION 'BOM multi-paquete: origen genealogico invalido';
        END IF;
    END IF;

    IF NEW.id_item_reemplazado IS NOT NULL THEN
        SELECT item.id_paquete, item.id_linea_bom
        INTO reemplazada
        FROM tb_bom_items item
        WHERE item.id_item = NEW.id_item_reemplazado;
        IF NOT FOUND
           OR NEW.id_item = NEW.id_item_reemplazado
           OR reemplazada.id_paquete <> NEW.id_paquete
           OR reemplazada.id_linea_bom = NEW.id_linea_bom
           OR NOT EXISTS (
               SELECT 1
               FROM tb_bom_lineas linea
               WHERE linea.id_linea_bom = NEW.id_linea_bom
                 AND linea.id_paquete = NEW.id_paquete
                 AND linea.id_linea_reemplazada = reemplazada.id_linea_bom
           ) THEN
            RAISE EXCEPTION 'BOM multi-paquete: linea de reemplazo invalida';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_genealogia_item ON tb_bom_items;
CREATE TRIGGER trg_bom_validar_genealogia_item
BEFORE INSERT OR UPDATE OF id_bom, id_paquete, id_linea_bom,
    id_item_origen, id_item_reemplazado
ON tb_bom_items
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_genealogia_item();

ALTER TABLE tb_bom_historial
    ADD COLUMN IF NOT EXISTS id_paquete UUID,
    ADD COLUMN IF NOT EXISTS id_linea_bom UUID;

UPDATE tb_bom_historial historial
SET id_paquete = bom.id_paquete,
    id_linea_bom = (
        SELECT item.id_linea_bom
        FROM tb_bom_items item
        WHERE item.id_item = historial.id_item
          AND item.id_bom = historial.id_bom
    )
FROM tb_bom bom
WHERE bom.id_bom = historial.id_bom
  AND historial.id_paquete IS NULL;

ALTER TABLE tb_bom_historial ALTER COLUMN id_paquete SET NOT NULL;
ALTER TABLE tb_bom_historial
    DROP CONSTRAINT IF EXISTS tb_bom_historial_item_linea_check;
ALTER TABLE tb_bom_historial
    ADD CONSTRAINT tb_bom_historial_item_linea_check CHECK (
        id_item IS NULL OR id_linea_bom IS NOT NULL
    );

ALTER TABLE tb_bom_historial
    DROP CONSTRAINT IF EXISTS tb_bom_historial_id_bom_fkey;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_historial_bom_paquete'
          AND conrelid = 'tb_bom_historial'::regclass
    ) THEN
        ALTER TABLE tb_bom_historial
            ADD CONSTRAINT fk_bom_historial_bom_paquete
            FOREIGN KEY (id_bom, id_paquete)
            REFERENCES tb_bom(id_bom, id_paquete) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_historial_linea_paquete'
          AND conrelid = 'tb_bom_historial'::regclass
    ) THEN
        ALTER TABLE tb_bom_historial
            ADD CONSTRAINT fk_bom_historial_linea_paquete
            FOREIGN KEY (id_linea_bom, id_paquete)
            REFERENCES tb_bom_lineas(id_linea_bom, id_paquete) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_historial_item_identidad'
          AND conrelid = 'tb_bom_historial'::regclass
    ) THEN
        ALTER TABLE tb_bom_historial
            ADD CONSTRAINT fk_bom_historial_item_identidad
            FOREIGN KEY (id_item, id_bom, id_paquete, id_linea_bom)
            REFERENCES tb_bom_items(id_item, id_bom, id_paquete, id_linea_bom)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_historial_paquete_linea
    ON tb_bom_historial(id_paquete, id_linea_bom, created_at DESC);

-- -----------------------------------------------------------------------------
-- 5. Pertenencia compuesta en documentos downstream
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_bom_snapshot_distribucion_valido(snapshot JSONB)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    elementos INTEGER;
    grupos INTEGER;
    porcentaje_total NUMERIC;
BEGIN
    IF snapshot IS NULL OR JSONB_TYPEOF(snapshot) <> 'array' THEN
        RETURN FALSE;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM JSONB_ARRAY_ELEMENTS(snapshot) elemento(valor)
        WHERE JSONB_TYPEOF(valor) <> 'object'
           OR JSONB_TYPEOF(valor -> 'id_grupo') IS DISTINCT FROM 'number'
           OR (valor ->> 'id_grupo') !~ '^[1-9][0-9]*$'
           OR JSONB_TYPEOF(valor -> 'codigo') IS DISTINCT FROM 'string'
           OR BTRIM(valor ->> 'codigo') = ''
           OR JSONB_TYPEOF(valor -> 'nombre') IS DISTINCT FROM 'string'
           OR BTRIM(valor ->> 'nombre') = ''
           OR JSONB_TYPEOF(valor -> 'porcentaje') IS DISTINCT FROM 'number'
           OR (valor ->> 'porcentaje')::NUMERIC <= 0
    ) THEN
        RETURN FALSE;
    END IF;

    SELECT COUNT(*),
           COUNT(DISTINCT (valor ->> 'id_grupo')::INTEGER),
           SUM((valor ->> 'porcentaje')::NUMERIC)
    INTO elementos, grupos, porcentaje_total
    FROM JSONB_ARRAY_ELEMENTS(snapshot) elemento(valor);

    RETURN elementos = 0
        OR (
            grupos = elementos
            AND ABS(porcentaje_total - 1) <= 0.000001
        );
EXCEPTION
    WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RETURN FALSE;
END;
$$;

ALTER TABLE tb_bom_cotizacion_items
    ADD COLUMN IF NOT EXISTS bom_id UUID,
    ADD COLUMN IF NOT EXISTS grupo_ids_snapshot INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    ADD COLUMN IF NOT EXISTS grupo_distribucion_snapshot JSONB NOT NULL DEFAULT '[]'::JSONB;

ALTER TABLE tb_bom_cotizacion_items
    DROP CONSTRAINT IF EXISTS tb_bom_cot_items_grupo_snapshot_check;
ALTER TABLE tb_bom_cotizacion_items
    ADD CONSTRAINT tb_bom_cot_items_grupo_snapshot_check
    CHECK (fn_bom_snapshot_distribucion_valido(grupo_distribucion_snapshot));

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS grupo_ids_snapshot INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[];

UPDATE tb_bom_cotizacion_items linea
SET bom_id = cot.bom_id
FROM tb_bom_cotizaciones cot
WHERE cot.id = linea.cotizacion_id
  AND linea.bom_id IS NULL;

ALTER TABLE tb_bom_cotizacion_items
    ALTER COLUMN bom_id SET NOT NULL;

-- Los documentos legacy no tienen evidencia durable de la distribucion que
-- existia al crearlos. Sus snapshots permanecen vacios y se reportan como
-- pendientes en vez de inferirse desde membresias actuales.

ALTER TABLE tb_bom_adenda_items
    ADD COLUMN IF NOT EXISTS id_bom UUID;

UPDATE tb_bom_adenda_items linea
SET id_bom = adenda.id_bom_base
FROM tb_bom_adendas adenda
WHERE adenda.id_adenda = linea.id_adenda
  AND linea.id_bom IS NULL;

ALTER TABLE tb_bom_adenda_items
    ALTER COLUMN id_bom SET NOT NULL;

ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS fk_bom_items_creado_en_adenda;

ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS tb_bom_items_id_bom_fkey;
ALTER TABLE tb_bom_items
    ADD CONSTRAINT tb_bom_items_id_bom_fkey
    FOREIGN KEY (id_bom) REFERENCES tb_bom(id_bom) ON DELETE RESTRICT;

ALTER TABLE tb_bom_cotizaciones DROP CONSTRAINT IF EXISTS tb_bom_cotizaciones_bom_id_fkey;
ALTER TABLE tb_bom_cotizaciones
    ADD CONSTRAINT tb_bom_cotizaciones_bom_id_fkey
    FOREIGN KEY (bom_id) REFERENCES tb_bom(id_bom) ON DELETE RESTRICT;

ALTER TABLE tb_bom_cotizacion_items
    DROP CONSTRAINT IF EXISTS tb_bom_cotizacion_items_cotizacion_id_fkey;
ALTER TABLE tb_bom_cotizacion_items
    ADD CONSTRAINT tb_bom_cotizacion_items_cotizacion_id_fkey
    FOREIGN KEY (cotizacion_id) REFERENCES tb_bom_cotizaciones(id) ON DELETE RESTRICT;

ALTER TABLE tb_bom_autorizaciones
    DROP CONSTRAINT IF EXISTS tb_bom_autorizaciones_bom_id_fkey;
ALTER TABLE tb_bom_autorizaciones
    ADD CONSTRAINT tb_bom_autorizaciones_bom_id_fkey
    FOREIGN KEY (bom_id) REFERENCES tb_bom(id_bom) ON DELETE RESTRICT;

ALTER TABLE tb_bom_autorizaciones
    DROP CONSTRAINT IF EXISTS tb_bom_autorizaciones_cotizacion_id_fkey;
ALTER TABLE tb_bom_autorizaciones
    ADD CONSTRAINT tb_bom_autorizaciones_cotizacion_id_fkey
    FOREIGN KEY (cotizacion_id) REFERENCES tb_bom_cotizaciones(id) ON DELETE RESTRICT;

ALTER TABLE tb_bom_adendas DROP CONSTRAINT IF EXISTS tb_bom_adendas_id_bom_base_fkey;
ALTER TABLE tb_bom_adendas
    ADD CONSTRAINT tb_bom_adendas_id_bom_base_fkey
    FOREIGN KEY (id_bom_base) REFERENCES tb_bom(id_bom) ON DELETE RESTRICT;

ALTER TABLE tb_bom_adenda_items
    DROP CONSTRAINT IF EXISTS tb_bom_adenda_items_id_adenda_fkey;
ALTER TABLE tb_bom_adenda_items
    ADD CONSTRAINT tb_bom_adenda_items_id_adenda_fkey
    FOREIGN KEY (id_adenda) REFERENCES tb_bom_adendas(id_adenda) ON DELETE RESTRICT;

ALTER TABLE tb_bom_item_ejecucion
    DROP CONSTRAINT IF EXISTS tb_bom_item_ejecucion_id_item_fkey;
ALTER TABLE tb_bom_item_ejecucion
    ADD CONSTRAINT tb_bom_item_ejecucion_id_item_fkey
    FOREIGN KEY (id_item) REFERENCES tb_bom_items(id_item) ON DELETE RESTRICT;

ALTER TABLE tb_bom_item_grupos
    DROP CONSTRAINT IF EXISTS tb_bom_item_grupos_id_item_fkey;
ALTER TABLE tb_bom_item_grupos
    ADD CONSTRAINT tb_bom_item_grupos_id_item_fkey
    FOREIGN KEY (id_item) REFERENCES tb_bom_items(id_item) ON DELETE RESTRICT;

ALTER TABLE tb_bom_item_grupos
    DROP CONSTRAINT IF EXISTS tb_bom_item_grupos_id_grupo_fkey;
ALTER TABLE tb_bom_item_grupos
    ADD CONSTRAINT tb_bom_item_grupos_id_grupo_fkey
    FOREIGN KEY (id_grupo) REFERENCES tb_cat_grupos_bom(id) ON DELETE RESTRICT;

ALTER TABLE tb_bom_item_grupos_operativos
    DROP CONSTRAINT IF EXISTS tb_bom_item_grupos_operativos_id_item_fkey;
ALTER TABLE tb_bom_item_grupos_operativos
    ADD CONSTRAINT tb_bom_item_grupos_operativos_id_item_fkey
    FOREIGN KEY (id_item) REFERENCES tb_bom_items(id_item) ON DELETE RESTRICT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_cotizaciones_id_bom'
          AND conrelid = 'tb_bom_cotizaciones'::regclass
    ) THEN
        ALTER TABLE tb_bom_cotizaciones
            ADD CONSTRAINT uq_bom_cotizaciones_id_bom UNIQUE (id, bom_id);
    END IF;

    ALTER TABLE tb_bom_cotizaciones
        DROP CONSTRAINT IF EXISTS fk_cotizacion_rfq_origen;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_cotizacion_rfq_bom'
          AND conrelid = 'tb_bom_cotizaciones'::regclass
    ) THEN
        ALTER TABLE tb_bom_cotizaciones
            ADD CONSTRAINT fk_bom_cotizacion_rfq_bom
            FOREIGN KEY (rfq_origen_id, bom_id)
            REFERENCES tb_bom_cotizaciones(id, bom_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_cot_items_cotizacion_bom'
          AND conrelid = 'tb_bom_cotizacion_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_cotizacion_items
            ADD CONSTRAINT fk_bom_cot_items_cotizacion_bom
            FOREIGN KEY (cotizacion_id, bom_id)
            REFERENCES tb_bom_cotizaciones(id, bom_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_cot_items_item_bom'
          AND conrelid = 'tb_bom_cotizacion_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_cotizacion_items
            ADD CONSTRAINT fk_bom_cot_items_item_bom
            FOREIGN KEY (bom_item_id, bom_id)
            REFERENCES tb_bom_items(id_item, id_bom)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_autorizacion_cotizacion_bom'
          AND conrelid = 'tb_bom_autorizaciones'::regclass
    ) THEN
        ALTER TABLE tb_bom_autorizaciones
            ADD CONSTRAINT fk_bom_autorizacion_cotizacion_bom
            FOREIGN KEY (cotizacion_id, bom_id)
            REFERENCES tb_bom_cotizaciones(id, bom_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_autorizacion_proyecto_bom'
          AND conrelid = 'tb_bom_autorizaciones'::regclass
    ) THEN
        ALTER TABLE tb_bom_autorizaciones
            ADD CONSTRAINT fk_bom_autorizacion_proyecto_bom
            FOREIGN KEY (bom_id, proyecto_id)
            REFERENCES tb_bom(id_bom, id_proyecto)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_cot_aprob_cotizacion_bom'
          AND conrelid = 'tb_bom_cotizacion_aprobaciones'::regclass
    ) THEN
        ALTER TABLE tb_bom_cotizacion_aprobaciones
            ADD CONSTRAINT fk_bom_cot_aprob_cotizacion_bom
            FOREIGN KEY (cotizacion_id, bom_id)
            REFERENCES tb_bom_cotizaciones(id, bom_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_cot_aprob_proyecto_bom'
          AND conrelid = 'tb_bom_cotizacion_aprobaciones'::regclass
    ) THEN
        ALTER TABLE tb_bom_cotizacion_aprobaciones
            ADD CONSTRAINT fk_bom_cot_aprob_proyecto_bom
            FOREIGN KEY (bom_id, proyecto_id)
            REFERENCES tb_bom(id_bom, id_proyecto)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bom_adendas_id_bom'
          AND conrelid = 'tb_bom_adendas'::regclass
    ) THEN
        ALTER TABLE tb_bom_adendas
            ADD CONSTRAINT uq_bom_adendas_id_bom UNIQUE (id_adenda, id_bom_base);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_adenda_items_adenda_bom'
          AND conrelid = 'tb_bom_adenda_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_adenda_items
            ADD CONSTRAINT fk_bom_adenda_items_adenda_bom
            FOREIGN KEY (id_adenda, id_bom)
            REFERENCES tb_bom_adendas(id_adenda, id_bom_base)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_adenda_items_origen_bom'
          AND conrelid = 'tb_bom_adenda_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_adenda_items
            ADD CONSTRAINT fk_bom_adenda_items_origen_bom
            FOREIGN KEY (id_item_origen, id_bom)
            REFERENCES tb_bom_items(id_item, id_bom)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_adenda_items_item_bom'
          AND conrelid = 'tb_bom_adenda_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_adenda_items
            ADD CONSTRAINT fk_bom_adenda_items_item_bom
            FOREIGN KEY (id_item_bom, id_bom)
            REFERENCES tb_bom_items(id_item, id_bom)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_items_adenda_bom'
          AND conrelid = 'tb_bom_items'::regclass
    ) THEN
        ALTER TABLE tb_bom_items
            ADD CONSTRAINT fk_bom_items_adenda_bom
            FOREIGN KEY (creado_en_adenda, id_bom)
            REFERENCES tb_bom_adendas(id_adenda, id_bom_base)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_cot_items_bom
    ON tb_bom_cotizacion_items(bom_id, cotizacion_id);

CREATE INDEX IF NOT EXISTS idx_bom_cot_items_item_bom
    ON tb_bom_cotizacion_items(bom_item_id, bom_id);

CREATE INDEX IF NOT EXISTS idx_bom_cotizaciones_rfq_bom
    ON tb_bom_cotizaciones(rfq_origen_id, bom_id)
    WHERE rfq_origen_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_adenda_items_bom
    ON tb_bom_adenda_items(id_bom, id_adenda);

CREATE INDEX IF NOT EXISTS idx_bom_adenda_items_origen_bom
    ON tb_bom_adenda_items(id_item_origen, id_bom)
    WHERE id_item_origen IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_adenda_items_item_bom_compuesto
    ON tb_bom_adenda_items(id_item_bom, id_bom)
    WHERE id_item_bom IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bom_items_adenda_bom
    ON tb_bom_items(creado_en_adenda, id_bom)
    WHERE creado_en_adenda IS NOT NULL;

-- Identidad estable del concepto CFDI y asignaciones explicitas. La descripcion
-- nunca participa como identidad: dos renglones identicos del XML se conservan.
ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS id_concepto_cfdi UUID DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS numero_linea_cfdi INTEGER,
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

WITH numerados AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY uuid_factura
            ORDER BY created_at, id
        )::INTEGER AS numero_linea
    FROM tb_materiales_historial
    WHERE numero_linea_cfdi IS NULL
)
UPDATE tb_materiales_historial material
SET numero_linea_cfdi = numerados.numero_linea
FROM numerados
WHERE numerados.id = material.id;

ALTER TABLE tb_materiales_historial
    ALTER COLUMN id_concepto_cfdi SET NOT NULL,
    ALTER COLUMN numero_linea_cfdi SET NOT NULL;

ALTER TABLE tb_materiales_historial
    DROP CONSTRAINT IF EXISTS tb_materiales_historial_lock_check;
ALTER TABLE tb_materiales_historial
    ADD CONSTRAINT tb_materiales_historial_lock_check CHECK (lock_version >= 0);

ALTER TABLE tb_materiales_historial
    DROP CONSTRAINT IF EXISTS uq_material_historial;

CREATE UNIQUE INDEX IF NOT EXISTS uq_materiales_concepto_cfdi
    ON tb_materiales_historial(id_concepto_cfdi);
CREATE UNIQUE INDEX IF NOT EXISTS uq_materiales_factura_numero_linea
    ON tb_materiales_historial(uuid_factura, numero_linea_cfdi);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_materiales_id_concepto_cfdi'
          AND conrelid = 'tb_materiales_historial'::regclass
    ) THEN
        ALTER TABLE tb_materiales_historial
            ADD CONSTRAINT uq_materiales_id_concepto_cfdi
            UNIQUE (id, id_concepto_cfdi);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS tb_bom_concepto_asignaciones (
    id_asignacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_material UUID NOT NULL
        REFERENCES tb_materiales_historial(id) ON DELETE RESTRICT,
    id_concepto_cfdi UUID NOT NULL,
    id_paquete UUID NOT NULL,
    id_bom UUID NOT NULL,
    id_linea_bom UUID NOT NULL,
    id_bom_item UUID NOT NULL,
    importe_asignado NUMERIC(20,6) NOT NULL,
    moneda CHAR(3) NOT NULL,
    tipo_cfdi VARCHAR(30) NOT NULL DEFAULT 'NORMAL',
    asignacion_grupo_completa BOOLEAN NOT NULL DEFAULT FALSE,
    lock_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bom_concepto_asignacion_item
        UNIQUE (id_material, id_bom_item),
    CONSTRAINT fk_bom_concepto_asignacion_material
        FOREIGN KEY (id_material, id_concepto_cfdi)
        REFERENCES tb_materiales_historial(id, id_concepto_cfdi)
        ON DELETE RESTRICT,
    CONSTRAINT fk_bom_concepto_asignacion_item
        FOREIGN KEY (id_bom_item, id_bom, id_paquete, id_linea_bom)
        REFERENCES tb_bom_items(id_item, id_bom, id_paquete, id_linea_bom)
        ON DELETE RESTRICT,
    CONSTRAINT tb_bom_concepto_asignacion_moneda_check
        CHECK (moneda IS NOT NULL AND moneda IN ('MXN', 'USD')),
    CONSTRAINT tb_bom_concepto_asignacion_tipo_check
        CHECK (tipo_cfdi IN ('NORMAL', 'NOTA_CREDITO')),
    CONSTRAINT tb_bom_concepto_asignacion_signo_check CHECK (
        (tipo_cfdi = 'NOTA_CREDITO' AND importe_asignado <= 0)
        OR (tipo_cfdi <> 'NOTA_CREDITO' AND importe_asignado >= 0)
    ),
    CONSTRAINT tb_bom_concepto_asignacion_lock_check CHECK (lock_version >= 0)
);

DO $$
BEGIN
    IF EXISTS (
        SELECT cf.uuid_factura
        FROM tb_comprobante_facturas cf
        GROUP BY cf.uuid_factura
        HAVING COUNT(DISTINCT cf.moneda) <> 1
            OR COUNT(DISTINCT CASE
                WHEN cf.tipo = 'NOTA_CREDITO' THEN 'NOTA_CREDITO'
                ELSE 'NORMAL'
            END) <> 1
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: un CFDI tiene moneda o tipo contradictorio';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM tb_materiales_historial material
        WHERE material.id_bom_item IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM tb_comprobante_facturas factura
              WHERE factura.uuid_factura = material.uuid_factura::TEXT
                AND factura.moneda IN ('MXN', 'USD')
          )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: existe un concepto BOM sin moneda CFDI verificable';
    END IF;
END $$;

INSERT INTO tb_bom_concepto_asignaciones (
    id_material, id_concepto_cfdi, id_paquete, id_bom, id_linea_bom,
    id_bom_item, importe_asignado, moneda, tipo_cfdi
)
SELECT
    material.id,
    material.id_concepto_cfdi,
    item.id_paquete,
    item.id_bom,
    item.id_linea_bom,
    item.id_item,
    CASE WHEN factura.tipo_cfdi = 'NOTA_CREDITO'
         THEN -ABS(material.importe)
         ELSE ABS(material.importe)
    END,
    factura.moneda,
    factura.tipo_cfdi
FROM tb_materiales_historial material
JOIN tb_bom_items item ON item.id_item = material.id_bom_item
LEFT JOIN LATERAL (
    SELECT
        CASE WHEN MIN(cf.tipo) = 'NOTA_CREDITO'
             THEN 'NOTA_CREDITO' ELSE 'NORMAL' END AS tipo_cfdi,
        MIN(cf.moneda) AS moneda
    FROM tb_comprobante_facturas cf
    WHERE cf.uuid_factura = material.uuid_factura::TEXT
) factura ON TRUE
WHERE material.id_bom_item IS NOT NULL
  AND factura.moneda IN ('MXN', 'USD')
ON CONFLICT (id_material, id_bom_item) DO NOTHING;

CREATE TABLE IF NOT EXISTS tb_bom_hecho_grupo_asignaciones (
    id_asignacion_grupo UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_asignacion_concepto UUID NOT NULL
        REFERENCES tb_bom_concepto_asignaciones(id_asignacion) ON DELETE RESTRICT,
    id_grupo INTEGER NOT NULL REFERENCES tb_cat_grupos_bom(id) ON DELETE RESTRICT,
    grupo_codigo_snapshot VARCHAR(20) NOT NULL,
    grupo_nombre_snapshot VARCHAR(120) NOT NULL,
    importe_asignado NUMERIC(20,6) NOT NULL,
    moneda CHAR(3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bom_hecho_grupo UNIQUE (id_asignacion_concepto, id_grupo),
    CONSTRAINT tb_bom_hecho_grupo_moneda_check CHECK (moneda IN ('MXN', 'USD'))
);

INSERT INTO tb_bom_hecho_grupo_asignaciones (
    id_asignacion_concepto, id_grupo, grupo_codigo_snapshot,
    grupo_nombre_snapshot, importe_asignado, moneda
)
SELECT
    asignacion.id_asignacion,
    grupo.id,
    grupo.codigo,
    grupo.nombre,
    asignacion.importe_asignado,
    asignacion.moneda
FROM tb_bom_concepto_asignaciones asignacion
JOIN tb_materiales_historial material ON material.id = asignacion.id_material
JOIN tb_cat_grupos_bom grupo ON grupo.id = material.grupo_ids_snapshot[1]
WHERE CARDINALITY(material.grupo_ids_snapshot) = 1
ON CONFLICT (id_asignacion_concepto, id_grupo) DO NOTHING;

UPDATE tb_bom_concepto_asignaciones asignacion
SET asignacion_grupo_completa = TRUE
WHERE ABS((
    SELECT COALESCE(SUM(grupo.importe_asignado), 0)
    FROM tb_bom_hecho_grupo_asignaciones grupo
    WHERE grupo.id_asignacion_concepto = asignacion.id_asignacion
) - asignacion.importe_asignado) <= 0.000001
  AND NOT EXISTS (
      SELECT 1
      FROM tb_bom_hecho_grupo_asignaciones grupo
      WHERE grupo.id_asignacion_concepto = asignacion.id_asignacion
        AND grupo.moneda <> asignacion.moneda
  );

CREATE TABLE IF NOT EXISTS tb_bom_item_grupo_asignaciones (
    id_asignacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_bom_item UUID NOT NULL REFERENCES tb_bom_items(id_item) ON DELETE RESTRICT,
    id_grupo INTEGER NOT NULL REFERENCES tb_cat_grupos_bom(id) ON DELETE RESTRICT,
    grupo_codigo_snapshot VARCHAR(20) NOT NULL,
    grupo_nombre_snapshot VARCHAR(120) NOT NULL,
    porcentaje NUMERIC(9,6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bom_item_grupo_asignacion UNIQUE (id_bom_item, id_grupo),
    CONSTRAINT tb_bom_item_grupo_porcentaje_check
        CHECK (porcentaje > 0 AND porcentaje <= 1)
);

WITH grupos_efectivos AS (
    SELECT operativo.id_item, operativo.id_grupo
    FROM tb_bom_item_grupos_operativos operativo
    UNION ALL
    SELECT base.id_item, base.id_grupo
    FROM tb_bom_item_grupos base
    WHERE NOT EXISTS (
        SELECT 1
        FROM tb_bom_item_grupos_operativos operativo
        WHERE operativo.id_item = base.id_item
    )
), grupos_unicos AS (
    SELECT id_item, MIN(id_grupo) AS id_grupo
    FROM grupos_efectivos
    GROUP BY id_item
    HAVING COUNT(*) = 1
)
INSERT INTO tb_bom_item_grupo_asignaciones (
    id_bom_item, id_grupo, grupo_codigo_snapshot, grupo_nombre_snapshot, porcentaje
)
SELECT efectivo.id_item, grupo.id, grupo.codigo, grupo.nombre, 1
FROM grupos_unicos efectivo
JOIN tb_cat_grupos_bom grupo ON grupo.id = efectivo.id_grupo
ON CONFLICT (id_bom_item, id_grupo) DO NOTHING;

-- No se infieren hechos historicos multigrupo a partir de porcentajes capturados
-- despues del CFDI. Las nuevas conciliaciones los escriben atomicamente y los
-- conceptos legacy ambiguos permanecen pendientes.

CREATE INDEX IF NOT EXISTS idx_bom_concepto_asignaciones_linea
    ON tb_bom_concepto_asignaciones(id_linea_bom, id_paquete);
CREATE INDEX IF NOT EXISTS idx_bom_concepto_asignaciones_bom
    ON tb_bom_concepto_asignaciones(id_bom, id_bom_item);
CREATE INDEX IF NOT EXISTS idx_bom_hecho_grupo_asignacion
    ON tb_bom_hecho_grupo_asignaciones(id_asignacion_concepto);
CREATE INDEX IF NOT EXISTS idx_bom_item_grupo_asignacion
    ON tb_bom_item_grupo_asignaciones(id_bom_item);

CREATE OR REPLACE FUNCTION fn_bom_validar_asignacion_grupos_id(
    asignacion_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    asignacion RECORD;
    total_grupos NUMERIC(20,6);
BEGIN
    SELECT * INTO asignacion
    FROM tb_bom_concepto_asignaciones
    WHERE id_asignacion = asignacion_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM tb_bom_hecho_grupo_asignaciones grupo
        WHERE grupo.id_asignacion_concepto = asignacion_id
          AND grupo.moneda <> asignacion.moneda
    ) THEN
        RAISE EXCEPTION 'La moneda del grupo no coincide con el concepto CFDI';
    END IF;
    SELECT COALESCE(SUM(importe_asignado), 0)
    INTO total_grupos
    FROM tb_bom_hecho_grupo_asignaciones
    WHERE id_asignacion_concepto = asignacion_id;
    IF (asignacion.importe_asignado >= 0 AND total_grupos < 0)
       OR (asignacion.importe_asignado < 0 AND total_grupos > 0)
       OR ABS(total_grupos) > ABS(asignacion.importe_asignado) + 0.000001
       OR (
           asignacion.asignacion_grupo_completa
           AND ABS(total_grupos - asignacion.importe_asignado) > 0.000001
    ) THEN
        RAISE EXCEPTION 'La asignacion por grupos no reconcilia el concepto CFDI';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION fn_bom_validar_asignacion_grupos()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM fn_bom_validar_asignacion_grupos_id(NEW.id_asignacion_concepto);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM fn_bom_validar_asignacion_grupos_id(OLD.id_asignacion_concepto);
    ELSE
        PERFORM fn_bom_validar_asignacion_grupos_id(NEW.id_asignacion_concepto);
        IF OLD.id_asignacion_concepto IS DISTINCT FROM NEW.id_asignacion_concepto THEN
            PERFORM fn_bom_validar_asignacion_grupos_id(OLD.id_asignacion_concepto);
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_asignacion_grupos
    ON tb_bom_hecho_grupo_asignaciones;
CREATE CONSTRAINT TRIGGER trg_bom_validar_asignacion_grupos
AFTER INSERT OR UPDATE OR DELETE ON tb_bom_hecho_grupo_asignaciones
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_asignacion_grupos();

CREATE OR REPLACE FUNCTION fn_bom_validar_concepto_completo()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM fn_bom_validar_asignacion_grupos_id(NEW.id_asignacion);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_concepto_completo
    ON tb_bom_concepto_asignaciones;
CREATE CONSTRAINT TRIGGER trg_bom_validar_concepto_completo
AFTER INSERT OR UPDATE OF importe_asignado, moneda, asignacion_grupo_completa
ON tb_bom_concepto_asignaciones
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_concepto_completo();

CREATE OR REPLACE FUNCTION fn_bom_validar_total_asignado_material(
    material_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    importe_concepto NUMERIC(20,6);
    total_asignado NUMERIC(20,6);
    variantes INTEGER;
BEGIN
    SELECT ABS(material.importe) INTO importe_concepto
    FROM tb_materiales_historial material
    WHERE material.id = material_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT COALESCE(SUM(asignacion.importe_asignado), 0),
           COUNT(DISTINCT (asignacion.moneda, asignacion.tipo_cfdi))
    INTO total_asignado, variantes
    FROM tb_bom_concepto_asignaciones asignacion
    WHERE asignacion.id_material = material_id;

    IF ABS(total_asignado) > importe_concepto + 0.000001 THEN
        RAISE EXCEPTION 'Las asignaciones BOM exceden el importe del concepto CFDI';
    END IF;
    IF variantes > 1 THEN
        RAISE EXCEPTION 'Las asignaciones BOM de un concepto tienen moneda o tipo contradictorio';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION fn_bom_validar_total_asignado_concepto()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM fn_bom_validar_total_asignado_material(NEW.id_material);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM fn_bom_validar_total_asignado_material(OLD.id_material);
    ELSE
        PERFORM fn_bom_validar_total_asignado_material(NEW.id_material);
        IF OLD.id_material IS DISTINCT FROM NEW.id_material THEN
            PERFORM fn_bom_validar_total_asignado_material(OLD.id_material);
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_total_asignado_concepto
    ON tb_bom_concepto_asignaciones;
CREATE CONSTRAINT TRIGGER trg_bom_validar_total_asignado_concepto
AFTER INSERT OR UPDATE OR DELETE ON tb_bom_concepto_asignaciones
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_total_asignado_concepto();

CREATE OR REPLACE FUNCTION fn_bom_validar_porcentajes_item_grupo_id(item_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    total_porcentaje NUMERIC(9,6);
BEGIN
    IF item_id IS NULL THEN
        RETURN;
    END IF;
    SELECT COALESCE(SUM(porcentaje), 0)
    INTO total_porcentaje
    FROM tb_bom_item_grupo_asignaciones
    WHERE id_bom_item = item_id;
    IF EXISTS (
        SELECT 1
        FROM tb_bom_item_grupo_asignaciones asignacion
        WHERE asignacion.id_bom_item = item_id
          AND NOT EXISTS (
              SELECT 1 FROM tb_bom_item_grupos_operativos operativa
              WHERE operativa.id_item = asignacion.id_bom_item
                AND operativa.id_grupo = asignacion.id_grupo
          )
          AND (
              EXISTS (
                  SELECT 1 FROM tb_bom_item_grupos_operativos alguna
                  WHERE alguna.id_item = asignacion.id_bom_item
              )
              OR NOT EXISTS (
                  SELECT 1 FROM tb_bom_item_grupos base
                  WHERE base.id_item = asignacion.id_bom_item
                    AND base.id_grupo = asignacion.id_grupo
              )
          )
    ) THEN
        RAISE EXCEPTION 'La distribucion financiera usa un grupo ajeno al item BOM';
    END IF;
    IF total_porcentaje <> 0 AND ABS(total_porcentaje - 1) > 0.000001 THEN
        RAISE EXCEPTION 'Los porcentajes de grupo del item BOM deben sumar 1';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION fn_bom_validar_porcentajes_item_grupo()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM fn_bom_validar_porcentajes_item_grupo_id(NEW.id_bom_item);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM fn_bom_validar_porcentajes_item_grupo_id(OLD.id_bom_item);
    ELSE
        PERFORM fn_bom_validar_porcentajes_item_grupo_id(NEW.id_bom_item);
        IF OLD.id_bom_item IS DISTINCT FROM NEW.id_bom_item THEN
            PERFORM fn_bom_validar_porcentajes_item_grupo_id(OLD.id_bom_item);
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_porcentajes_item_grupo
    ON tb_bom_item_grupo_asignaciones;
CREATE CONSTRAINT TRIGGER trg_bom_validar_porcentajes_item_grupo
AFTER INSERT OR UPDATE OR DELETE ON tb_bom_item_grupo_asignaciones
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_porcentajes_item_grupo();

CREATE OR REPLACE FUNCTION fn_bom_revalidar_porcentajes_desde_membresia()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM fn_bom_validar_porcentajes_item_grupo_id(NEW.id_item);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM fn_bom_validar_porcentajes_item_grupo_id(OLD.id_item);
    ELSE
        PERFORM fn_bom_validar_porcentajes_item_grupo_id(NEW.id_item);
        IF OLD.id_item IS DISTINCT FROM NEW.id_item THEN
            PERFORM fn_bom_validar_porcentajes_item_grupo_id(OLD.id_item);
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_revalidar_porcentajes_grupo_base
    ON tb_bom_item_grupos;
CREATE CONSTRAINT TRIGGER trg_bom_revalidar_porcentajes_grupo_base
AFTER INSERT OR UPDATE OR DELETE ON tb_bom_item_grupos
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_revalidar_porcentajes_desde_membresia();

DROP TRIGGER IF EXISTS trg_bom_revalidar_porcentajes_grupo_operativo
    ON tb_bom_item_grupos_operativos;
CREATE CONSTRAINT TRIGGER trg_bom_revalidar_porcentajes_grupo_operativo
AFTER INSERT OR UPDATE OR DELETE ON tb_bom_item_grupos_operativos
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_revalidar_porcentajes_desde_membresia();

-- -----------------------------------------------------------------------------
-- 6. Locks documentales, snapshots de adenda y outbox idempotente
-- -----------------------------------------------------------------------------

ALTER TABLE tb_bom_cotizaciones
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

ALTER TABLE tb_bom_autorizaciones
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

ALTER TABLE tb_bom_cotizacion_aprobaciones
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

ALTER TABLE tb_bom_adendas
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tipo_cambio_aprobacion NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS fecha_tipo_cambio_aprobacion DATE,
    ADD COLUMN IF NOT EXISTS impacto_base_mxn_snapshot NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS impacto_base_usd_snapshot NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS impacto_aprobado_mxn NUMERIC(20,6);

ALTER TABLE tb_bom_adendas
    ALTER COLUMN impacto_base_mxn_snapshot TYPE NUMERIC(20,6),
    ALTER COLUMN impacto_base_usd_snapshot TYPE NUMERIC(20,6),
    ALTER COLUMN impacto_aprobado_mxn TYPE NUMERIC(20,6);

-- Las adendas historicas no se congelan con el estado vivo de sus items. Solo
-- las aprobaciones ejecutadas por el servicio nuevo generan este snapshot.

ALTER TABLE tb_bom_adendas DROP CONSTRAINT IF EXISTS tb_bom_adendas_snapshot_moneda_check;
ALTER TABLE tb_bom_adendas ADD CONSTRAINT tb_bom_adendas_snapshot_moneda_check
    CHECK (
        (
            tipo_cambio_aprobacion IS NULL
            AND fecha_tipo_cambio_aprobacion IS NULL
            AND impacto_base_mxn_snapshot IS NULL
            AND impacto_base_usd_snapshot IS NULL
            AND impacto_aprobado_mxn IS NULL
        )
        OR (
            impacto_base_mxn_snapshot IS NOT NULL
            AND impacto_base_usd_snapshot IS NOT NULL
            AND impacto_aprobado_mxn IS NOT NULL
            AND (
                (
                    impacto_base_usd_snapshot = 0
                    AND tipo_cambio_aprobacion IS NULL
                    AND fecha_tipo_cambio_aprobacion IS NULL
                )
                OR (
                    tipo_cambio_aprobacion > 0
                    AND fecha_tipo_cambio_aprobacion IS NOT NULL
                )
            )
            AND ABS(
                impacto_aprobado_mxn
                - impacto_base_mxn_snapshot
                - impacto_base_usd_snapshot * COALESCE(tipo_cambio_aprobacion, 0)
            ) <= 0.01
        )
    );

ALTER TABLE tb_bom_propuestas_cambio
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS id_paquete UUID;

UPDATE tb_bom_propuestas_cambio propuesta
SET id_paquete = bom.id_paquete
FROM tb_bom bom
WHERE bom.id_bom = propuesta.id_bom
  AND propuesta.id_paquete IS NULL;

ALTER TABLE tb_bom_propuestas_cambio ALTER COLUMN id_paquete SET NOT NULL;

ALTER TABLE tb_bom_propuestas_cambio
    DROP CONSTRAINT IF EXISTS tb_bom_propuestas_cambio_id_bom_fkey;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_propuesta_bom_paquete'
          AND conrelid = 'tb_bom_propuestas_cambio'::regclass
    ) THEN
        ALTER TABLE tb_bom_propuestas_cambio
            ADD CONSTRAINT fk_bom_propuesta_bom_paquete
            FOREIGN KEY (id_bom, id_paquete)
            REFERENCES tb_bom(id_bom, id_paquete) ON DELETE RESTRICT;
    END IF;
END $$;

ALTER TABLE tb_bom_suplencias
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tb_bom_suplencias DROP CONSTRAINT IF EXISTS tb_bom_suplencias_lock_check;
ALTER TABLE tb_bom_suplencias ADD CONSTRAINT tb_bom_suplencias_lock_check
    CHECK (lock_version >= 0);

WITH duplicadas AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY titular_id
               ORDER BY fecha_fin DESC, created_at DESC, id DESC
           ) AS orden
    FROM tb_bom_suplencias
    WHERE activo = TRUE
)
UPDATE tb_bom_suplencias suplencia
SET activo = FALSE,
    lock_version = lock_version + 1
FROM duplicadas
WHERE duplicadas.id = suplencia.id
  AND duplicadas.orden > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_suplencia_activa_titular
    ON tb_bom_suplencias(titular_id)
    WHERE activo = TRUE;

ALTER TABLE tb_bom_item_ejecucion
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

ALTER TABLE tb_bom_cotizaciones DROP CONSTRAINT IF EXISTS tb_bom_cotizaciones_lock_check;
ALTER TABLE tb_bom_cotizaciones ADD CONSTRAINT tb_bom_cotizaciones_lock_check
    CHECK (lock_version >= 0);

ALTER TABLE tb_bom_autorizaciones DROP CONSTRAINT IF EXISTS tb_bom_autorizaciones_lock_check;
ALTER TABLE tb_bom_autorizaciones ADD CONSTRAINT tb_bom_autorizaciones_lock_check
    CHECK (lock_version >= 0);

ALTER TABLE tb_bom_cotizacion_aprobaciones
    DROP CONSTRAINT IF EXISTS tb_bom_cot_aprob_lock_check;
ALTER TABLE tb_bom_cotizacion_aprobaciones ADD CONSTRAINT tb_bom_cot_aprob_lock_check
    CHECK (lock_version >= 0);

ALTER TABLE tb_bom_adendas DROP CONSTRAINT IF EXISTS tb_bom_adendas_lock_check;
ALTER TABLE tb_bom_adendas ADD CONSTRAINT tb_bom_adendas_lock_check
    CHECK (lock_version >= 0);

ALTER TABLE tb_bom_propuestas_cambio DROP CONSTRAINT IF EXISTS tb_bom_propuestas_lock_check;
ALTER TABLE tb_bom_propuestas_cambio ADD CONSTRAINT tb_bom_propuestas_lock_check
    CHECK (lock_version >= 0);

ALTER TABLE tb_bom_item_ejecucion DROP CONSTRAINT IF EXISTS tb_bom_item_ejecucion_lock_check;
ALTER TABLE tb_bom_item_ejecucion ADD CONSTRAINT tb_bom_item_ejecucion_lock_check
    CHECK (lock_version >= 0);

-- La moneda del encabezado es un dato historico del mismo documento y permite
-- completar lineas legacy sin inventar tipo de cambio ni importes.
UPDATE tb_bom_cotizacion_items linea
SET moneda = cotizacion.moneda
FROM tb_bom_cotizaciones cotizacion
WHERE cotizacion.id = linea.cotizacion_id
  AND linea.moneda IS NULL
  AND cotizacion.moneda IN ('MXN', 'USD');

-- Un TC en una autorizacion MXN nunca participa en la conversion. Se elimina el
-- dato redundante antes de imponer el contrato; los USD sin TC siguen fallando.
UPDATE tb_bom_autorizaciones
SET tipo_cambio_snapshot = NULL
WHERE moneda = 'MXN'
  AND tipo_cambio_snapshot IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tb_bom_cotizacion_items linea
        JOIN tb_bom_cotizaciones cotizacion ON cotizacion.id = linea.cotizacion_id
        WHERE linea.moneda IS NULL
           OR linea.moneda NOT IN ('MXN', 'USD')
           OR linea.moneda <> cotizacion.moneda
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: lineas de cotizacion con moneda incompatible';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM tb_bom_autorizaciones autorizacion
        JOIN tb_bom_cotizaciones cotizacion ON cotizacion.id = autorizacion.cotizacion_id
        WHERE autorizacion.moneda IS NULL
           OR autorizacion.moneda NOT IN ('MXN', 'USD')
           OR autorizacion.moneda <> cotizacion.moneda
           OR autorizacion.monto_total <= 0
           OR ABS(autorizacion.monto_total - cotizacion.total) > 0.01
           OR (autorizacion.moneda = 'USD'
               AND (autorizacion.tipo_cambio_snapshot IS NULL
                    OR autorizacion.tipo_cambio_snapshot <= 0))
           OR (autorizacion.moneda = 'MXN'
               AND autorizacion.tipo_cambio_snapshot IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: autorizacion incompatible con su cotizacion';
    END IF;
END $$;

ALTER TABLE tb_bom_cotizacion_items ALTER COLUMN moneda SET NOT NULL;
ALTER TABLE tb_bom_cotizacion_items
    DROP CONSTRAINT IF EXISTS tb_bom_cot_items_moneda_check;
ALTER TABLE tb_bom_cotizacion_items
    ADD CONSTRAINT tb_bom_cot_items_moneda_check
    CHECK (moneda IN ('MXN', 'USD'));

ALTER TABLE tb_bom_autorizaciones
    DROP CONSTRAINT IF EXISTS tb_bom_autorizaciones_importe_moneda_check;
ALTER TABLE tb_bom_autorizaciones
    ADD CONSTRAINT tb_bom_autorizaciones_importe_moneda_check CHECK (
        monto_total > 0
        AND moneda IN ('MXN', 'USD')
        AND (
            (moneda = 'MXN' AND tipo_cambio_snapshot IS NULL)
            OR (moneda = 'USD' AND tipo_cambio_snapshot > 0)
        )
    );

CREATE OR REPLACE FUNCTION fn_bom_validar_documento_cotizacion()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    cotizacion RECORD;
BEGIN
    SELECT * INTO cotizacion
    FROM tb_bom_cotizaciones
    WHERE id = NEW.cotizacion_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'tb_bom_cotizacion_items'
       AND (NEW.bom_id <> cotizacion.bom_id OR NEW.moneda <> cotizacion.moneda) THEN
        RAISE EXCEPTION 'La linea no coincide con el BOM o moneda de la cotizacion';
    END IF;
    IF TG_TABLE_NAME = 'tb_bom_autorizaciones'
       AND (NEW.bom_id <> cotizacion.bom_id
            OR NEW.moneda <> cotizacion.moneda
            OR ABS(NEW.monto_total - cotizacion.total) > 0.01) THEN
        RAISE EXCEPTION 'La autorizacion no coincide con su cotizacion';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_linea_cotizacion
    ON tb_bom_cotizacion_items;
CREATE CONSTRAINT TRIGGER trg_bom_validar_linea_cotizacion
AFTER INSERT OR UPDATE ON tb_bom_cotizacion_items
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_documento_cotizacion();

DROP TRIGGER IF EXISTS trg_bom_validar_autorizacion_cotizacion
    ON tb_bom_autorizaciones;
CREATE CONSTRAINT TRIGGER trg_bom_validar_autorizacion_cotizacion
AFTER INSERT OR UPDATE ON tb_bom_autorizaciones
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_documento_cotizacion();

ALTER TABLE tb_bom_autorizaciones
    DROP CONSTRAINT IF EXISTS tb_bom_autorizaciones_estatus_check;
ALTER TABLE tb_bom_autorizaciones
    ADD CONSTRAINT tb_bom_autorizaciones_estatus_check CHECK (
        estatus IN (
            'PENDIENTE', 'AUTORIZADO_OBRA', 'AUTORIZADO_DIRECCION',
            'AUTORIZADO_FINANZAS', 'PAGO_PARCIAL', 'RECHAZADO', 'PAGADO'
        )
    );

ALTER TABLE tb_bom_pagos
    DROP CONSTRAINT IF EXISTS tb_bom_pagos_autorizacion_unique;
ALTER TABLE tb_bom_pagos
    ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS clave_idempotencia VARCHAR(220);

UPDATE tb_bom_pagos
SET clave_idempotencia = 'legacy:' || id::TEXT
WHERE clave_idempotencia IS NULL;

ALTER TABLE tb_bom_pagos
    ALTER COLUMN clave_idempotencia SET NOT NULL;

ALTER TABLE tb_bom_pagos
    ALTER COLUMN monto_pagado TYPE NUMERIC(20,6),
    ALTER COLUMN tipo_cambio_usado TYPE NUMERIC(12,6);

ALTER TABLE tb_bom_pagos DROP CONSTRAINT IF EXISTS tb_bom_pagos_monto_check;
ALTER TABLE tb_bom_pagos ADD CONSTRAINT tb_bom_pagos_monto_check
    CHECK (monto_pagado > 0);
ALTER TABLE tb_bom_pagos DROP CONSTRAINT IF EXISTS tb_bom_pagos_tc_check;
ALTER TABLE tb_bom_pagos ADD CONSTRAINT tb_bom_pagos_tc_check CHECK (
    (moneda = 'MXN' AND tipo_cambio_usado IS NULL)
    OR (moneda = 'USD' AND tipo_cambio_usado > 0)
);
ALTER TABLE tb_bom_pagos DROP CONSTRAINT IF EXISTS tb_bom_pagos_lock_check;
ALTER TABLE tb_bom_pagos ADD CONSTRAINT tb_bom_pagos_lock_check
    CHECK (lock_version >= 0);

DROP INDEX IF EXISTS idx_bom_pagos_autorizacion;
CREATE INDEX IF NOT EXISTS idx_bom_pagos_autorizacion_fecha
    ON tb_bom_pagos(autorizacion_id, registrado_en, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_pagos_idempotencia
    ON tb_bom_pagos(clave_idempotencia);

CREATE OR REPLACE FUNCTION fn_bom_bloquear_autorizacion_pago()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM 1 FROM tb_bom_autorizaciones autorizacion
        WHERE autorizacion.id = NEW.autorizacion_id FOR UPDATE;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM 1 FROM tb_bom_autorizaciones autorizacion
        WHERE autorizacion.id = OLD.autorizacion_id FOR UPDATE;
    ELSE
        PERFORM 1
        FROM tb_bom_autorizaciones autorizacion
        WHERE autorizacion.id IN (OLD.autorizacion_id, NEW.autorizacion_id)
        ORDER BY autorizacion.id
        FOR UPDATE;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_bloquear_autorizacion_pago ON tb_bom_pagos;
CREATE TRIGGER trg_bom_bloquear_autorizacion_pago
BEFORE INSERT OR UPDATE OR DELETE ON tb_bom_pagos
FOR EACH ROW EXECUTE FUNCTION fn_bom_bloquear_autorizacion_pago();

CREATE OR REPLACE FUNCTION fn_bom_validar_saldo_autorizacion(
    autorizacion_id_validar UUID
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    autorizacion RECORD;
    total_pagado NUMERIC(20,6);
    tolerancia CONSTANT NUMERIC := 0.005;
BEGIN
    SELECT * INTO autorizacion
    FROM tb_bom_autorizaciones
    WHERE id = autorizacion_id_validar;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1 FROM tb_bom_pagos pago
        WHERE pago.autorizacion_id = autorizacion_id_validar
          AND pago.moneda <> autorizacion.moneda
    ) THEN
        RAISE EXCEPTION 'La moneda del pago debe coincidir con la autorizacion BOM';
    END IF;

    SELECT COALESCE(SUM(pago.monto_pagado), 0)
    INTO total_pagado
    FROM tb_bom_pagos pago
    WHERE pago.autorizacion_id = autorizacion_id_validar;

    IF total_pagado - autorizacion.monto_total > tolerancia THEN
        RAISE EXCEPTION 'Los pagos exceden el monto autorizado del BOM';
    END IF;
    IF total_pagado = 0
       AND autorizacion.estatus IN ('PAGO_PARCIAL', 'PAGADO') THEN
        RAISE EXCEPTION 'El estado de la autorizacion indica pagos inexistentes';
    END IF;
    IF total_pagado > 0 AND autorizacion.monto_total - total_pagado > tolerancia
       AND autorizacion.estatus <> 'PAGO_PARCIAL' THEN
        RAISE EXCEPTION 'El estado de la autorizacion no refleja el pago parcial';
    END IF;
    IF total_pagado > 0
       AND autorizacion.monto_total - total_pagado <= tolerancia
       AND autorizacion.estatus <> 'PAGADO' THEN
        RAISE EXCEPTION 'El estado de la autorizacion no refleja el pago completo';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION fn_bom_validar_saldo_pago()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM fn_bom_validar_saldo_autorizacion(NEW.autorizacion_id);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM fn_bom_validar_saldo_autorizacion(OLD.autorizacion_id);
    ELSE
        PERFORM fn_bom_validar_saldo_autorizacion(NEW.autorizacion_id);
        IF OLD.autorizacion_id IS DISTINCT FROM NEW.autorizacion_id THEN
            PERFORM fn_bom_validar_saldo_autorizacion(OLD.autorizacion_id);
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_saldo_pago ON tb_bom_pagos;
CREATE CONSTRAINT TRIGGER trg_bom_validar_saldo_pago
AFTER INSERT OR UPDATE OR DELETE ON tb_bom_pagos
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_saldo_pago();

CREATE OR REPLACE FUNCTION fn_bom_validar_saldo_desde_autorizacion()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM fn_bom_validar_saldo_autorizacion(NEW.id);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_validar_saldo_desde_autorizacion
    ON tb_bom_autorizaciones;
CREATE CONSTRAINT TRIGGER trg_bom_validar_saldo_desde_autorizacion
AFTER INSERT OR UPDATE OF estatus, monto_total, moneda
ON tb_bom_autorizaciones
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_bom_validar_saldo_desde_autorizacion();

ALTER TABLE tb_bom_aprobaciones
    ADD COLUMN IF NOT EXISTS ciclo INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS vigente BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS invalidada_en TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS invalidada_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT;

WITH secuencia AS (
    SELECT
        id,
        id_bom,
        created_at,
        1 + COUNT(*) FILTER (
            WHERE tipo IN (
                'RECHAZO_ING', 'RECHAZO_OBRA', 'RECHAZO_CONST',
                'RECHAZO_FINAL', 'DEVOLUCION_BORRADOR'
            )
        ) OVER (
            PARTITION BY id_bom
            ORDER BY created_at, id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS ciclo_calculado
    FROM tb_bom_aprobaciones
), invalidacion AS (
    SELECT
        s.id,
        s.ciclo_calculado,
        rechazo.usuario_id AS invalidada_por,
        rechazo.created_at AS invalidada_en
    FROM secuencia s
    LEFT JOIN LATERAL (
        SELECT a.usuario_id, a.created_at
        FROM tb_bom_aprobaciones a
        WHERE a.id_bom = s.id_bom
          AND a.tipo IN (
              'RECHAZO_ING', 'RECHAZO_OBRA', 'RECHAZO_CONST',
              'RECHAZO_FINAL', 'DEVOLUCION_BORRADOR'
          )
          AND (a.created_at, a.id) >= (s.created_at, s.id)
        ORDER BY a.created_at, a.id
        LIMIT 1
    ) rechazo ON TRUE
)
UPDATE tb_bom_aprobaciones aprobacion
SET ciclo = invalidacion.ciclo_calculado,
    vigente = invalidacion.invalidada_en IS NULL,
    invalidada_en = invalidacion.invalidada_en,
    invalidada_por = invalidacion.invalidada_por
FROM invalidacion
WHERE invalidacion.id = aprobacion.id;

ALTER TABLE tb_bom_aprobaciones
    DROP CONSTRAINT IF EXISTS tb_bom_aprobaciones_vigencia_check;
ALTER TABLE tb_bom_aprobaciones
    ADD CONSTRAINT tb_bom_aprobaciones_vigencia_check CHECK (
        (vigente = TRUE AND invalidada_en IS NULL AND invalidada_por IS NULL)
        OR (vigente = FALSE AND invalidada_en IS NOT NULL AND invalidada_por IS NOT NULL)
    );

CREATE INDEX IF NOT EXISTS idx_bom_aprobaciones_vigentes
    ON tb_bom_aprobaciones(id_bom, ciclo, created_at)
    WHERE vigente = TRUE;

ALTER TABLE tb_bom_aprobaciones
    ADD COLUMN IF NOT EXISTS id_paquete UUID;

UPDATE tb_bom_aprobaciones aprobacion
SET id_paquete = bom.id_paquete
FROM tb_bom bom
WHERE bom.id_bom = aprobacion.id_bom
  AND aprobacion.id_paquete IS NULL;

ALTER TABLE tb_bom_aprobaciones ALTER COLUMN id_paquete SET NOT NULL;

ALTER TABLE tb_bom_aprobaciones
    DROP CONSTRAINT IF EXISTS tb_bom_aprobaciones_id_bom_fkey;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_aprobaciones_bom_paquete'
          AND conrelid = 'tb_bom_aprobaciones'::regclass
    ) THEN
        ALTER TABLE tb_bom_aprobaciones
            ADD CONSTRAINT fk_bom_aprobaciones_bom_paquete
            FOREIGN KEY (id_bom, id_paquete)
            REFERENCES tb_bom(id_bom, id_paquete) ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_aprobaciones_paquete
    ON tb_bom_aprobaciones(id_paquete);

CREATE TABLE IF NOT EXISTS tb_bom_eventos_outbox (
    id_evento UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clave_idempotencia VARCHAR(220) NOT NULL UNIQUE,
    tipo_evento VARCHAR(80) NOT NULL,
    id_proyecto UUID NOT NULL REFERENCES tb_proyectos_gate(id_proyecto) ON DELETE RESTRICT,
    id_paquete UUID REFERENCES tb_bom_paquetes(id_paquete) ON DELETE RESTRICT,
    id_bom UUID REFERENCES tb_bom(id_bom) ON DELETE RESTRICT,
    id_item UUID REFERENCES tb_bom_items(id_item) ON DELETE RESTRICT,
    id_documento UUID,
    actor_id UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_version INTEGER NOT NULL DEFAULT 1,
    url_destino TEXT,
    estatus VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE',
    intentos INTEGER NOT NULL DEFAULT 0,
    disponible_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    procesado_en TIMESTAMPTZ,
    ultimo_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_eventos_outbox_estatus_check
        CHECK (estatus IN ('PENDIENTE', 'PROCESANDO', 'REINTENTO', 'ENVIADO', 'AGOTADO')),
    CONSTRAINT tb_bom_eventos_outbox_intentos_check CHECK (intentos >= 0)
);

ALTER TABLE tb_bom_eventos_outbox
    DROP CONSTRAINT IF EXISTS tb_bom_eventos_outbox_identidad_check;
ALTER TABLE tb_bom_eventos_outbox
    ADD CONSTRAINT tb_bom_eventos_outbox_identidad_check CHECK (
        (id_paquete IS NULL OR id_proyecto IS NOT NULL)
        AND (id_bom IS NULL OR id_paquete IS NOT NULL)
        AND (id_item IS NULL OR id_bom IS NOT NULL)
        AND payload_version > 0
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_outbox_paquete_proyecto'
          AND conrelid = 'tb_bom_eventos_outbox'::regclass
    ) THEN
        ALTER TABLE tb_bom_eventos_outbox
            ADD CONSTRAINT fk_bom_outbox_paquete_proyecto
            FOREIGN KEY (id_paquete, id_proyecto)
            REFERENCES tb_bom_paquetes(id_paquete, id_proyecto)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_outbox_bom_paquete'
          AND conrelid = 'tb_bom_eventos_outbox'::regclass
    ) THEN
        ALTER TABLE tb_bom_eventos_outbox
            ADD CONSTRAINT fk_bom_outbox_bom_paquete
            FOREIGN KEY (id_bom, id_paquete)
            REFERENCES tb_bom(id_bom, id_paquete)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_bom_outbox_item_bom'
          AND conrelid = 'tb_bom_eventos_outbox'::regclass
    ) THEN
        ALTER TABLE tb_bom_eventos_outbox
            ADD CONSTRAINT fk_bom_outbox_item_bom
            FOREIGN KEY (id_item, id_bom)
            REFERENCES tb_bom_items(id_item, id_bom)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_eventos_outbox_pendientes
    ON tb_bom_eventos_outbox(disponible_en, created_at)
    WHERE estatus IN ('PENDIENTE', 'REINTENTO');

CREATE INDEX IF NOT EXISTS idx_bom_eventos_outbox_bom
    ON tb_bom_eventos_outbox(id_bom, created_at DESC)
    WHERE id_bom IS NOT NULL;

CREATE TABLE IF NOT EXISTS tb_bom_evento_entregas (
    id_entrega UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_evento UUID NOT NULL
        REFERENCES tb_bom_eventos_outbox(id_evento) ON DELETE RESTRICT,
    canal VARCHAR(20) NOT NULL,
    destinatario_id UUID NOT NULL
        REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    titular_id UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    direccion_destino TEXT,
    clave_idempotencia VARCHAR(260) NOT NULL UNIQUE,
    estatus VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE',
    intentos INTEGER NOT NULL DEFAULT 0,
    disponible_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_hasta TIMESTAMPTZ,
    worker_id TEXT,
    enviado_en TIMESTAMPTZ,
    ultimo_error TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_version INTEGER NOT NULL DEFAULT 1,
    replay_count INTEGER NOT NULL DEFAULT 0,
    ultimo_replay_por UUID REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    ultimo_replay_en TIMESTAMPTZ,
    ultimo_replay_motivo TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_evento_entregas_canal_check
        CHECK (canal IN ('CORREO', 'INTERNA')),
    CONSTRAINT tb_bom_evento_entregas_estatus_check
        CHECK (estatus IN ('PENDIENTE', 'PROCESANDO', 'REINTENTO', 'ENVIADO', 'AGOTADO')),
    CONSTRAINT tb_bom_evento_entregas_intentos_check CHECK (intentos >= 0),
    CONSTRAINT tb_bom_evento_entregas_replay_check CHECK (
        replay_count >= 0
        AND (
            (ultimo_replay_por IS NULL AND ultimo_replay_en IS NULL
                AND ultimo_replay_motivo IS NULL)
            OR (ultimo_replay_por IS NOT NULL AND ultimo_replay_en IS NOT NULL
                AND ultimo_replay_motivo IS NOT NULL)
        )
    ),
    CONSTRAINT uq_bom_evento_entrega_destino
        UNIQUE (id_evento, canal, destinatario_id)
);

ALTER TABLE tb_bom_evento_entregas
    ADD COLUMN IF NOT EXISTS replay_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ultimo_replay_por UUID
        REFERENCES tb_usuarios(id_usuario) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS ultimo_replay_en TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ultimo_replay_motivo TEXT;

ALTER TABLE tb_bom_evento_entregas
    DROP CONSTRAINT IF EXISTS tb_bom_evento_entregas_replay_check;
ALTER TABLE tb_bom_evento_entregas
    ADD CONSTRAINT tb_bom_evento_entregas_replay_check CHECK (
        replay_count >= 0
        AND (
            (ultimo_replay_por IS NULL AND ultimo_replay_en IS NULL
                AND ultimo_replay_motivo IS NULL)
            OR (ultimo_replay_por IS NOT NULL AND ultimo_replay_en IS NOT NULL
                AND ultimo_replay_motivo IS NOT NULL)
        )
    );

ALTER TABLE tb_bom_evento_entregas
    DROP CONSTRAINT IF EXISTS tb_bom_evento_entregas_lease_estado_check;
ALTER TABLE tb_bom_evento_entregas
    ADD CONSTRAINT tb_bom_evento_entregas_lease_estado_check CHECK (
        (
            estatus = 'PROCESANDO'
            AND lease_hasta IS NOT NULL
            AND worker_id IS NOT NULL
            AND enviado_en IS NULL
        )
        OR (
            estatus <> 'PROCESANDO'
            AND lease_hasta IS NULL
            AND worker_id IS NULL
            AND ((estatus = 'ENVIADO') = (enviado_en IS NOT NULL))
        )
    );

CREATE INDEX IF NOT EXISTS idx_bom_evento_entregas_reclamo
    ON tb_bom_evento_entregas(disponible_en, id_entrega)
    WHERE estatus IN ('PENDIENTE', 'REINTENTO');

CREATE INDEX IF NOT EXISTS idx_bom_evento_entregas_lease
    ON tb_bom_evento_entregas(lease_hasta)
    WHERE estatus = 'PROCESANDO';

ALTER TABLE tb_notificaciones
    ADD COLUMN IF NOT EXISTS id_evento_bom UUID
        REFERENCES tb_bom_eventos_outbox(id_evento) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS modulo_origen VARCHAR(40),
    ADD COLUMN IF NOT EXISTS url_destino TEXT,
    ADD COLUMN IF NOT EXISTS id_proyecto_bom UUID
        REFERENCES tb_proyectos_gate(id_proyecto) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS id_paquete_bom UUID
        REFERENCES tb_bom_paquetes(id_paquete) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS id_bom UUID
        REFERENCES tb_bom(id_bom) ON DELETE RESTRICT;

ALTER TABLE tb_notificaciones
    DROP CONSTRAINT IF EXISTS tb_notificaciones_bom_identidad_check;
ALTER TABLE tb_notificaciones
    ADD CONSTRAINT tb_notificaciones_bom_identidad_check CHECK (
        (id_paquete_bom IS NULL OR id_proyecto_bom IS NOT NULL)
        AND (id_bom IS NULL OR id_paquete_bom IS NOT NULL)
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_notificacion_bom_paquete_proyecto'
          AND conrelid = 'tb_notificaciones'::regclass
    ) THEN
        ALTER TABLE tb_notificaciones
            ADD CONSTRAINT fk_notificacion_bom_paquete_proyecto
            FOREIGN KEY (id_paquete_bom, id_proyecto_bom)
            REFERENCES tb_bom_paquetes(id_paquete, id_proyecto)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_notificacion_bom_version_paquete'
          AND conrelid = 'tb_notificaciones'::regclass
    ) THEN
        ALTER TABLE tb_notificaciones
            ADD CONSTRAINT fk_notificacion_bom_version_paquete
            FOREIGN KEY (id_bom, id_paquete_bom)
            REFERENCES tb_bom(id_bom, id_paquete)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_notificacion_evento_bom_usuario
    ON tb_notificaciones(usuario_id, id_evento_bom)
    WHERE id_evento_bom IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notificacion_paquete_bom
    ON tb_notificaciones(id_paquete_bom, created_at DESC)
    WHERE id_paquete_bom IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 7. Proteccion contra borrado fisico y seguridad del acceso directo
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_bom_impedir_borrado_fisico()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'El borrado fisico de % no esta permitido; use cancelar o archivar', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_paquetes_impedir_borrado ON tb_bom_paquetes;
CREATE TRIGGER trg_bom_paquetes_impedir_borrado
BEFORE DELETE ON tb_bom_paquetes
FOR EACH ROW EXECUTE FUNCTION fn_bom_impedir_borrado_fisico();

DROP TRIGGER IF EXISTS trg_bom_impedir_borrado ON tb_bom;
CREATE TRIGGER trg_bom_impedir_borrado
BEFORE DELETE ON tb_bom
FOR EACH ROW EXECUTE FUNCTION fn_bom_impedir_borrado_fisico();

DROP TRIGGER IF EXISTS trg_bom_items_impedir_borrado ON tb_bom_items;
CREATE TRIGGER trg_bom_items_impedir_borrado
BEFORE DELETE ON tb_bom_items
FOR EACH ROW EXECUTE FUNCTION fn_bom_impedir_borrado_fisico();

ALTER TABLE tb_bom_paquetes ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_bom_proyecto_estado ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_bom_lineas ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_bom_eventos_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_bom_evento_entregas ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_bom_concepto_asignaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_bom_hecho_grupo_asignaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_bom_item_grupo_asignaciones ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE
    tb_bom_paquetes,
    tb_bom_proyecto_estado,
    tb_bom_lineas,
    tb_bom_eventos_outbox,
    tb_bom_evento_entregas,
    tb_bom_concepto_asignaciones,
    tb_bom_hecho_grupo_asignaciones,
    tb_bom_item_grupo_asignaciones
FROM anon, authenticated, PUBLIC;

DO $$
DECLARE
    tabla TEXT;
BEGIN
    FOREACH tabla IN ARRAY ARRAY[
        'tb_bom_paquetes',
        'tb_bom_proyecto_estado',
        'tb_bom_lineas',
        'tb_bom_eventos_outbox',
        'tb_bom_evento_entregas',
        'tb_bom_concepto_asignaciones',
        'tb_bom_hecho_grupo_asignaciones',
        'tb_bom_item_grupo_asignaciones'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = tabla
              AND policyname = 'deny_anon_authenticated'
        ) THEN
            EXECUTE format(
                'CREATE POLICY deny_anon_authenticated ON public.%I FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)',
                tabla
            );
        END IF;
    END LOOP;
END $$;

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
VALUES
    (
        'bom.outbox_intervalo_segundos', '15',
        'Intervalo del consumidor durable de eventos BOM.', 'integer'
    ),
    (
        'bom.outbox_lote', '20',
        'Cantidad maxima de entregas BOM reclamadas por ciclo.', 'integer'
    ),
    (
        'bom.outbox_max_intentos', '8',
        'Intentos maximos por entrega antes de marcarla agotada.', 'integer'
    ),
    (
        'bom.outbox_lease_segundos', '120',
        'Duracion del lease de una entrega reclamada por el worker.', 'integer'
    )
ON CONFLICT (clave) DO NOTHING;

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
VALUES (
    'bom.multi_paquete_habilitado',
    'false',
    'Habilita la creacion de multiples paquetes BOM independientes por proyecto.',
    'boolean'
)
ON CONFLICT (clave) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 8. Auditoria post-migracion
-- -----------------------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tb_bom b
        JOIN tb_bom_paquetes p ON p.id_paquete = b.id_paquete
        WHERE b.id_proyecto <> p.id_proyecto
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: proyecto incompatible entre paquete y version';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_paquetes p
        JOIN tb_bom b ON b.id_bom = p.cabeza_trabajo_id
        WHERE b.id_paquete <> p.id_paquete
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: cabeza de trabajo pertenece a otro paquete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_paquetes p
        JOIN tb_bom b ON b.id_bom = p.cabeza_oficial_id
        WHERE b.id_paquete <> p.id_paquete
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: cabeza oficial pertenece a otro paquete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_items i
        JOIN tb_bom b ON b.id_bom = i.id_bom
        JOIN tb_bom_lineas l ON l.id_linea_bom = i.id_linea_bom
        WHERE i.id_paquete <> b.id_paquete OR i.id_paquete <> l.id_paquete
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: item, version y linea estable no pertenecen al mismo paquete';
    END IF;

    IF EXISTS (
        SELECT 1 FROM tb_bom_paquetes paquete
        WHERE paquete.estado_paquete = 'ACTIVO'
          AND paquete.cabeza_trabajo_id IS NULL
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: paquete activo sin cabeza de trabajo';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_paquetes paquete
        JOIN tb_bom cabeza ON cabeza.id_bom = paquete.cabeza_trabajo_id
        WHERE cabeza.estatus = 'CANCELADO'
           OR EXISTS (
               SELECT 1 FROM tb_bom otra
               WHERE otra.id_paquete = paquete.id_paquete
                 AND otra.estatus <> 'CANCELADO'
                 AND (otra.version, otra.id_bom) > (cabeza.version, cabeza.id_bom)
           )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: la cabeza de trabajo no es la version vigente mas reciente';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_paquetes paquete
        JOIN tb_bom oficial ON oficial.id_bom = paquete.cabeza_oficial_id
        WHERE oficial.estatus <> 'APROBADO_FINAL'
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: cabeza oficial sin aprobacion final';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom version
        JOIN tb_bom_paquetes paquete ON paquete.id_paquete = version.id_paquete
        WHERE version.estatus NOT IN ('APROBADO_FINAL', 'CANCELADO')
          AND paquete.cabeza_trabajo_id <> version.id_bom
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: version no terminal fuera de la cabeza de trabajo';
    END IF;

    IF EXISTS (
        SELECT 1 FROM tb_bom bom
        WHERE (bom.modulos_fv_snapshot IS NULL)
              <> (bom.potencia_pico_kwp_snapshot IS NULL)
           OR (bom.subtotal_base_mxn_snapshot IS NULL)
              <> (bom.subtotal_base_usd_snapshot IS NULL)
           OR (bom.subtotal_base_mxn_snapshot IS NULL)
              <> (bom.total_aprobado_mxn IS NULL)
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: snapshot parcial en una version';
    END IF;

    IF EXISTS (
        SELECT 1 FROM tb_bom_adendas adenda
        WHERE (adenda.impacto_base_mxn_snapshot IS NULL)
              <> (adenda.impacto_base_usd_snapshot IS NULL)
           OR (adenda.impacto_base_mxn_snapshot IS NULL)
              <> (adenda.impacto_aprobado_mxn IS NULL)
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: snapshot parcial en una adenda';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_historial historial
        LEFT JOIN tb_bom_items item
          ON item.id_item = historial.id_item
         AND item.id_bom = historial.id_bom
         AND item.id_paquete = historial.id_paquete
         AND item.id_linea_bom = historial.id_linea_bom
        WHERE historial.id_item IS NOT NULL AND item.id_item IS NULL
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: historial con item o linea incompatible';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_materiales_historial material
        WHERE material.id_bom_item IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM tb_bom_concepto_asignaciones asignacion
              WHERE asignacion.id_material = material.id
          )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: concepto BOM vinculado sin asignacion durable';
    END IF;

    IF EXISTS (
        SELECT asignacion.id_material
        FROM tb_bom_concepto_asignaciones asignacion
        JOIN tb_materiales_historial material ON material.id = asignacion.id_material
        GROUP BY asignacion.id_material, material.importe
        HAVING ABS(SUM(asignacion.importe_asignado)) > ABS(material.importe) + 0.000001
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: concepto CFDI sobreasignado';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_concepto_asignaciones asignacion
        WHERE asignacion.asignacion_grupo_completa
          AND ABS(COALESCE((
              SELECT SUM(grupo.importe_asignado)
              FROM tb_bom_hecho_grupo_asignaciones grupo
              WHERE grupo.id_asignacion_concepto = asignacion.id_asignacion
          ), 0) - asignacion.importe_asignado) > 0.000001
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: asignacion multigrupo marcada completa sin reconciliar';
    END IF;

    IF EXISTS (
        SELECT asignacion.id_bom_item
        FROM tb_bom_item_grupo_asignaciones asignacion
        GROUP BY asignacion.id_bom_item
        HAVING ABS(SUM(asignacion.porcentaje) - 1) > 0.000001
    ) OR EXISTS (
        SELECT 1
        FROM tb_bom_item_grupo_asignaciones asignacion
        WHERE NOT EXISTS (
            SELECT 1
            FROM tb_bom_item_grupos_operativos operativa
            WHERE operativa.id_item = asignacion.id_bom_item
              AND operativa.id_grupo = asignacion.id_grupo
        )
          AND (
              EXISTS (
                  SELECT 1
                  FROM tb_bom_item_grupos_operativos alguna
                  WHERE alguna.id_item = asignacion.id_bom_item
              )
              OR NOT EXISTS (
                  SELECT 1
                  FROM tb_bom_item_grupos base
                  WHERE base.id_item = asignacion.id_bom_item
                    AND base.id_grupo = asignacion.id_grupo
              )
          )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: distribucion financiera de item invalida';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_cotizacion_items linea
        CROSS JOIN LATERAL (
            SELECT COUNT(*) AS elementos,
                   SUM(snapshot.porcentaje) AS porcentaje_total,
                   BOOL_OR(
                       snapshot.id_grupo IS NULL
                       OR snapshot.codigo IS NULL
                       OR snapshot.nombre IS NULL
                       OR snapshot.porcentaje IS NULL
                       OR snapshot.porcentaje <= 0
                   ) AS invalida
            FROM JSONB_TO_RECORDSET(linea.grupo_distribucion_snapshot)
                AS snapshot(
                    id_grupo INTEGER,
                    codigo VARCHAR,
                    nombre VARCHAR,
                    porcentaje NUMERIC
                )
        ) validacion
        WHERE validacion.elementos > 0
          AND (
              validacion.invalida
              OR ABS(validacion.porcentaje_total - 1) > 0.000001
          )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: snapshot de grupos de cotizacion invalido';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_pagos pago
        JOIN tb_bom_autorizaciones autorizacion ON autorizacion.id = pago.autorizacion_id
        WHERE pago.moneda <> autorizacion.moneda
    ) OR EXISTS (
        SELECT autorizacion.id
        FROM tb_bom_autorizaciones autorizacion
        JOIN tb_bom_pagos pago ON pago.autorizacion_id = autorizacion.id
        GROUP BY autorizacion.id, autorizacion.monto_total, autorizacion.estatus
        HAVING SUM(pago.monto_pagado) - autorizacion.monto_total > 0.005
           OR (autorizacion.monto_total - SUM(pago.monto_pagado) > 0.005
               AND autorizacion.estatus <> 'PAGO_PARCIAL')
           OR (autorizacion.monto_total - SUM(pago.monto_pagado) <= 0.005
               AND autorizacion.estatus <> 'PAGADO')
    ) OR EXISTS (
        SELECT 1
        FROM tb_bom_autorizaciones autorizacion
        WHERE autorizacion.estatus IN ('PAGO_PARCIAL', 'PAGADO')
          AND NOT EXISTS (
              SELECT 1 FROM tb_bom_pagos pago
              WHERE pago.autorizacion_id = autorizacion.id
          )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: pagos, saldo o estado no reconciliados';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_eventos_outbox evento
        LEFT JOIN tb_bom_paquetes paquete ON paquete.id_paquete = evento.id_paquete
        LEFT JOIN tb_bom bom ON bom.id_bom = evento.id_bom
        LEFT JOIN tb_bom_items item ON item.id_item = evento.id_item
        WHERE (evento.id_paquete IS NOT NULL
               AND paquete.id_proyecto <> evento.id_proyecto)
           OR (evento.id_bom IS NOT NULL
               AND (bom.id_paquete <> evento.id_paquete
                    OR bom.id_proyecto <> evento.id_proyecto))
           OR (evento.id_item IS NOT NULL AND item.id_bom <> evento.id_bom)
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: outbox con identidad cruzada';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM tb_bom_aprobaciones aprobacion
        WHERE aprobacion.vigente
          AND aprobacion.ciclo <> (
              SELECT MAX(otra.ciclo)
              FROM tb_bom_aprobaciones otra
              WHERE otra.id_bom = aprobacion.id_bom
          )
    ) THEN
        RAISE EXCEPTION 'BOM multi-paquete: aprobacion vigente de un ciclo cerrado';
    END IF;
END $$;
