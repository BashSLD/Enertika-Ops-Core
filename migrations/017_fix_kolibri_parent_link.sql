-- Migración 017: Corrección de vínculo de hilo para AVICOLAS KOLIBRI
-- Contexto: El levantamiento OP-2603020901 fue solicitado como nuevo por error.
--           Corresponde al mismo hilo que la Pre Oferta OP-2602061259 (Multisitio 5).
--           Los 4 levantamientos ya entregados se conservan sin cambios.
-- Fecha: 2026-03-10

UPDATE tb_oportunidades
SET parent_id = '3aee894e-cdee-4a6c-8647-5f7b479c9976'  -- Pre Oferta OP-2602061259
WHERE id_oportunidad = '37488cc8-04de-48d0-8641-7198270924e8'  -- Levantamiento OP-2603020901
  AND parent_id IS NULL;  -- Guarda de seguridad: solo si aún no tiene padre
