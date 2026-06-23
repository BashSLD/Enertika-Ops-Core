-- Migra matches BOM de baja confianza ya persistidos a columnas de sugerencia.

UPDATE tb_materiales_historial
SET id_bom_item_sugerido = COALESCE(id_bom_item_sugerido, id_bom_item),
    sugerencia_confianza = COALESCE(sugerencia_confianza, match_confianza),
    sugerencia_origen = COALESCE(sugerencia_origen, match_origen),
    id_bom_item = NULL,
    match_confianza = NULL,
    match_origen = NULL
WHERE id_bom_item IS NOT NULL
  AND match_confianza = 'BAJA';
