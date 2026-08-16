-- Flag independiente de origen_precio: marca que un precio_unitario fue capturado por
-- Ingenieria (entrada manual o item sin costo) y aun no fue confirmado/editado por Compras
-- como costo oficial (Fase 4, doc 38-plan-fase4-autoridad-costos.md).

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS precio_pendiente_confirmacion boolean NOT NULL DEFAULT false;
