-- Corrige fn_bom_validar_documento_cotizacion: el chequeo de tb_bom_autorizaciones
-- referenciaba NEW.monto_total dentro de una expresion booleana combinada via AND
-- con TG_TABLE_NAME = 'tb_bom_autorizaciones' en el MISMO IF que el chequeo de
-- tb_bom_cotizacion_items. PL/pgSQL no aisla la resolucion de campos de un RECORD
-- (NEW) polimorfico por rama de un AND compuesto, asi que al insertar en
-- tb_bom_cotizacion_items (que no tiene columna monto_total) fallaba con
-- asyncpg.exceptions.UndefinedColumnError: record "new" has no field "monto_total".
-- Fix: separar en bloques IF/ELSIF top-level por TG_TABLE_NAME, cada uno con su
-- propio IF anidado, para que NEW.monto_total solo se resuelva en la rama de
-- tb_bom_autorizaciones.

CREATE OR REPLACE FUNCTION public.fn_bom_validar_documento_cotizacion()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    cotizacion RECORD;
BEGIN
    SELECT * INTO cotizacion
    FROM tb_bom_cotizaciones
    WHERE id = NEW.cotizacion_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'tb_bom_cotizacion_items' THEN
        IF NEW.bom_id <> cotizacion.bom_id OR NEW.moneda <> cotizacion.moneda THEN
            RAISE EXCEPTION 'La linea no coincide con el BOM o moneda de la cotizacion';
        END IF;
    ELSIF TG_TABLE_NAME = 'tb_bom_autorizaciones' THEN
        IF NEW.bom_id <> cotizacion.bom_id
            OR NEW.moneda <> cotizacion.moneda
            OR ABS(NEW.monto_total - cotizacion.total) > 0.01 THEN
            RAISE EXCEPTION 'La autorizacion no coincide con su cotizacion';
        END IF;
    END IF;

    RETURN NEW;
END;
$function$;
