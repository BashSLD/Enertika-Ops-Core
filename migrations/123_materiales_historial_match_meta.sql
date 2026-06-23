-- 123: Metadatos del match factura<->BOM en tb_materiales_historial.
-- match_confianza: nivel de certeza del enlace concepto->item (ALTA | BAJA | HUMANO).
-- match_origen: senal que produjo el enlace (CLAVE_SAT | MEMORIA | COTIZACION | TEXTO | HUMANO).
-- Ambas nullable: NULL = concepto sin enlazar a un item del BOM.

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS match_confianza VARCHAR(10);

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS match_origen VARCHAR(20);
