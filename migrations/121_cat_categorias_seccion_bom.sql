-- 121_cat_categorias_seccion_bom.sql
-- Agrega la sección de BOM (DC / AC / CM / Otros) a cada categoría de compra.
-- Necesario para la vista "Resumen de compra" del BOM, que agrupa el comparativo
-- Presupuesto vs Facturado vs Pagado en dos niveles: sección (resumen) y categoría (detalle).
--
-- MAPEO PROVISIONAL (2026-06-22): pendiente de confirmación del equipo en dos puntos
--   (Inversores -> AC ; Misceláneos/Accesorios -> Otros). Ver CONSULTA_RESUMEN_DE_COMPRA.md.
--   Al confirmarse, ajustar únicamente los valores de este UPDATE (o crear migración de corrección).
--
-- Idempotente. Aplicar en DEV primero, luego PROD, antes de desplegar el código que la usa.

ALTER TABLE tb_cat_categorias_compra
    ADD COLUMN IF NOT EXISTS seccion_bom VARCHAR;

-- DC (corriente directa)
UPDATE tb_cat_categorias_compra SET seccion_bom = 'DC'    WHERE id IN (11, 2, 4, 6, 13);
-- AC (corriente alterna) — Inversores (12) incluido provisionalmente en AC
UPDATE tb_cat_categorias_compra SET seccion_bom = 'AC'    WHERE id IN (12, 1, 3, 5, 7, 14);
-- CM (comunicación / monitoreo)
UPDATE tb_cat_categorias_compra SET seccion_bom = 'CM'    WHERE id IN (10);
-- Otros (cajón: Misceláneos, Accesorios eléctricos) — provisional
UPDATE tb_cat_categorias_compra SET seccion_bom = 'Otros' WHERE id IN (8, 9);
