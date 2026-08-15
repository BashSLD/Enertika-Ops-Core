-- 164: Inmutabilidad a nivel BD del snapshot de APROBADO_FINAL en tb_bom, y
-- creacion automatica de tb_bom_proyecto_estado para paquetes nuevos.
-- Migracion aditiva, solo agrega 2 triggers de defensa. No requiere backfill:
-- 0 paquetes sin fila de estado y 0 BOM en APROBADO_FINAL verificados en PROD.

-- -----------------------------------------------------------------------------
-- 1. Bloquear edicion del snapshot congelado en APROBADO_FINAL
-- -----------------------------------------------------------------------------
-- Hoy el unico sitio de codigo que escribe estas columnas es aprobar_final()
-- (core/bom/service.py), protegido por CAS (exige estatus previo EN_REVISION_FINAL),
-- asi que en la practica nunca se reescriben. Este trigger lo garantiza tambien a
-- nivel BD ante un futuro mutador que no respete esa disciplina.

CREATE OR REPLACE FUNCTION fn_bom_bloquear_snapshot_aprobado()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.total_aprobado_mxn IS DISTINCT FROM OLD.total_aprobado_mxn
        OR NEW.tipo_cambio_aprobacion IS DISTINCT FROM OLD.tipo_cambio_aprobacion
        OR NEW.fecha_tipo_cambio_aprobacion IS DISTINCT FROM OLD.fecha_tipo_cambio_aprobacion
        OR NEW.subtotal_base_mxn_snapshot IS DISTINCT FROM OLD.subtotal_base_mxn_snapshot
        OR NEW.subtotal_base_usd_snapshot IS DISTINCT FROM OLD.subtotal_base_usd_snapshot
    THEN
        RAISE EXCEPTION
            'El snapshot financiero de un BOM APROBADO_FINAL no puede modificarse (id_bom=%)',
            OLD.id_bom;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_bloquear_snapshot_aprobado ON tb_bom;
CREATE TRIGGER trg_bom_bloquear_snapshot_aprobado
BEFORE UPDATE ON tb_bom
FOR EACH ROW
WHEN (OLD.estatus = 'APROBADO_FINAL')
EXECUTE FUNCTION fn_bom_bloquear_snapshot_aprobado();

-- -----------------------------------------------------------------------------
-- 2. Crear tb_bom_proyecto_estado automaticamente para paquetes nuevos
-- -----------------------------------------------------------------------------
-- La fila ya se autocura via upsert-on-read en get_estado_proyecto_for_update()
-- (core/bom/db_service.py). Este trigger es una defensa adicional a nivel BD para
-- que la fila exista desde el INSERT del paquete, sin depender de que todo
-- consumidor futuro pase por esa funcion.

CREATE OR REPLACE FUNCTION fn_bom_paquetes_crear_estado_proyecto()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO tb_bom_proyecto_estado (id_proyecto)
    VALUES (NEW.id_proyecto)
    ON CONFLICT (id_proyecto) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_bom_paquetes_crear_estado_proyecto ON tb_bom_paquetes;
CREATE TRIGGER trg_bom_paquetes_crear_estado_proyecto
AFTER INSERT ON tb_bom_paquetes
FOR EACH ROW EXECUTE FUNCTION fn_bom_paquetes_crear_estado_proyecto();
