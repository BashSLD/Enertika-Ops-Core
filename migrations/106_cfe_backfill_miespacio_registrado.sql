-- migrations/106_cfe_backfill_miespacio_registrado.sql
-- Backfill: marca 'registrado' los servicios 'no_verificado' previos a la feature
-- de alta MiEspacio que demostrablemente ya estan registrados alli.
--
-- Senal conservadora y conclusiva: tener un PDF completado. Los PDF solo se
-- obtienen de MiEspacio (Otras Facturas); el portal publico no los entrega. Por
-- eso un PDF completado prueba el registro en MiEspacio (a diferencia del XML,
-- que puede venir del portal publico sin registro). Idempotente: solo toca filas
-- 'no_verificado'; re-ejecutar no afecta nada.

UPDATE tb_cfe_servicios s
SET miespacio_estatus = 'registrado',
    miespacio_verificado_en = now()
WHERE s.miespacio_estatus = 'no_verificado'
  AND EXISTS (
    SELECT 1 FROM tb_cfe_descargas d
    WHERE d.servicio_id = s.id
      AND d.tipo = 'pdf'
      AND d.estatus = 'completado'
  );
