-- 109_saneamiento_ceros_fv_bess.sql
-- Limpia ceros sin sentido en magnitudes de tecnologia no aplicable:
--   - FV-family (tech 1,4,5) con capacidad_cierre_bess_kwh = 0  -> NULL (FV puro no lleva BESS)
--   - BESS puro (tech 2)     con potencia_cierre_fv_kwp     = 0  -> NULL (BESS puro no lleva FV)
-- El 0 era ruido (el modal viejo mostraba ambos campos; ya corregido). 0 = NULL aqui (lossless).
-- NO toca filas con valor > 0 (esas requieren decision humana via Excel de correccion).
-- NO afecta tb_entregas_componente (esos ceros nunca se cargaron alli).
-- Backup previo: scripts/decouple_fv_bess/_backup_saneamiento_109.json
-- Alcance esperado: 20 filas FV-family + 3 filas BESS = 23 (snapshot 2026-06-15).
-- NOTA: aplicar en PRODUCCION (MCP Supabase). El .env apunta a DEV.

UPDATE tb_oportunidades
SET capacidad_cierre_bess_kwh = NULL
WHERE id_tecnologia IN (1, 4, 5)
  AND capacidad_cierre_bess_kwh = 0;

UPDATE tb_oportunidades
SET potencia_cierre_fv_kwp = NULL
WHERE id_tecnologia = 2
  AND potencia_cierre_fv_kwp = 0;

-- ============================================================================
-- ROLLBACK (ejecutar SOLO si se necesita revertir; restaura los 0 originales
-- por id_oportunidad segun el backup del 2026-06-15)
-- ============================================================================
-- UPDATE tb_oportunidades SET capacidad_cierre_bess_kwh = 0
-- WHERE id_oportunidad IN (
--   '802652ea-d21a-48de-b364-87eb9930d8c7','a2f94b1e-5024-4e0a-9250-da5a490c3c90',
--   'eb94f502-a897-45d8-ab91-01c40ee13d47','57faf1f2-395f-435b-9602-9de8e586fd4a',
--   '039d879c-15fd-4cb1-b3a3-e97a516a303f','926b2a2d-f819-4662-80e2-cc62d820d6d8',
--   '4efc42f2-fa81-4d01-9fd3-a9702c1a66f4','18d212ba-bffb-4814-825c-2f0b95a8c227',
--   'c2935a7f-149d-45a8-a42b-ab8b7a22d714','8294f8dd-1c64-4824-8ec6-04e533957866',
--   '60e45291-17a1-43ff-9239-4b32c6e7b809','78cd0888-8b62-4083-b2c7-ff19fb27ffdb',
--   '126482e3-4c25-4dda-9f84-fd0feec202cd','3dc9da2e-c01f-4144-9ad1-3809fef7a7e8',
--   '0d4c112d-9d6f-47b9-bbde-57dac1029404','9caac672-74a2-466b-8ae8-889d13156e80',
--   '085ebccb-5d07-47c0-8926-c7523b79ae53','1f021b14-1c23-413b-b390-a5f96dcdd651',
--   '11abbfe0-1fcb-4e29-9fdc-ba965d779e8e','acb12d39-4138-426b-9ca7-e05df3121fba'
-- );
-- UPDATE tb_oportunidades SET potencia_cierre_fv_kwp = 0
-- WHERE id_oportunidad IN (
--   '4040c0f9-280a-4dba-bb6c-1730ea47dae0','beacf724-ab81-45a9-af78-194b0d19cc8e',
--   '53b69ef1-dd4c-4fa1-8226-cfd6d4b30ea8'
-- );
