-- Matcher automatico catalogo interno <-> factura XML (doc 39, punto 6.2).
--
-- tb_materiales_historial: sugerencia (pendiente de revision humana). Nombres
-- propios para no chocar con id_bom_item_sugerido/sugerencia_confianza/
-- sugerencia_origen, ya usados por el matcher factura<->BOM sobre la misma
-- fila (mig 125).
ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS id_material_interno_sugerido uuid
        REFERENCES tb_cat_materiales(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS sugerencia_interno_confianza varchar(10),
    ADD COLUMN IF NOT EXISTS sugerencia_interno_origen varchar(20);

CREATE INDEX IF NOT EXISTS idx_materiales_historial_interno_sugerido
    ON tb_materiales_historial (id_material_interno_sugerido);

-- tb_materiales_interno_xml: auditoria del vinculo confirmado. origen NOT NULL
-- DEFAULT 'HUMANO': todo lo ya existente y todo lo que siga entrando por la UI
-- manual queda HUMANO; solo el matcher automatico escribe
-- 'AUTO_CLAVE_SAT'/'AUTO_MEMORIA'/'AUTO_TEXTO' explicitamente.
ALTER TABLE tb_materiales_interno_xml
    ADD COLUMN IF NOT EXISTS confianza varchar(10),
    ADD COLUMN IF NOT EXISTS origen varchar(20) NOT NULL DEFAULT 'HUMANO';
