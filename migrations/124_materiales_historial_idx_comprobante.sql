-- Indice de covering para la FK tb_materiales_historial.id_comprobante.
-- La conciliacion factura<->item BOM (get_conceptos_conciliacion) hace JOIN
-- tb_comprobantes_pago -> tb_materiales_historial por id_comprobante; sin este
-- indice Postgres resuelve con Seq Scan sobre el historial (advisor:
-- tb_materiales_historial_id_comprobante_fkey sin covering index).
CREATE INDEX IF NOT EXISTS idx_materiales_historial_comprobante
    ON tb_materiales_historial (id_comprobante);
