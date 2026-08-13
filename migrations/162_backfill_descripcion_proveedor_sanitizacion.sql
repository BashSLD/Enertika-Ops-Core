-- 162: Backfill de limpieza de formato en tb_materiales_historial.descripcion_proveedor.
--
-- Datos historicos cargados antes del fix en modules/compras/xml_extractor.py
-- (_sanitize_descripcion) conservan ruido de formato del proveedor: guion-vineta
-- pegado al inicio ("-CABLE MULTICONDUCTOR..."), espacios finales, saltos de
-- linea sueltos al final (via &#10; en el XML, que el parser no colapsa por
-- ser referencia de caracter explicita) y espacios dobles internos
-- ("TAQUETE GRIS 5/16  MCA..."). Misma regla que el extractor: solo limpieza
-- de formato, nunca normalizacion de contenido (eso es descripcion_norm via
-- core/materials/normalizer.py). Idempotente: el WHERE solo matchea filas
-- cuyo valor actual difiere del valor ya saneado.
--
-- v2: btrim() sin segundo argumento solo recorta espacios literales (0x20),
-- no \n/\t/\r -- dejaba filas con salto de linea final sin limpiar. Se
-- reemplaza por regexp_replace con \s para cubrir todo whitespace en los
-- extremos.

UPDATE public.tb_materiales_historial
SET descripcion_proveedor = regexp_replace(
        regexp_replace(
            regexp_replace(descripcion_proveedor, '^\s+|\s+$', '', 'g'),
            '^-(?=\S)', ''
        ),
        ' {2,}', ' ', 'g'
    )
WHERE descripcion_proveedor IS DISTINCT FROM regexp_replace(
        regexp_replace(
            regexp_replace(descripcion_proveedor, '^\s+|\s+$', '', 'g'),
            '^-(?=\S)', ''
        ),
        ' {2,}', ' ', 'g'
    );
