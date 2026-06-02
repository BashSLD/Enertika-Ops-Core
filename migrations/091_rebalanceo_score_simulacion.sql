-- 091_rebalanceo_score_simulacion.sql
-- Rebalanceo de pesos del score de desempeño: 50/35/15 → 50/25/25
-- sim_volumen_max cambia de tope fijo (100) a piso mínimo (15) para normalización relativa al período.
-- Idempotente: UPDATE no falla si la fila no existe (simplemente no actualiza ninguna fila).

UPDATE tb_configuracion_global SET valor = '0.25' WHERE clave = 'sim_peso_interno';
UPDATE tb_configuracion_global SET valor = '0.25' WHERE clave = 'sim_peso_volumen';
UPDATE tb_configuracion_global SET valor = '15'   WHERE clave = 'sim_volumen_max';
