-- ============================================================
-- Migración 016: Revisión post-carga manual
-- Fecha: 2026-03-10
-- Clientes: Agrana Fruit, Avicolas Kolibri, Hotel Sutuk,
--           La Termoplastic FBM, Residencias Liborio,
--           Restaurantes Almorzero de Puebla, Voestalpine,
--           Cummins, Teneria Panamericana del Bajio,
--           Seroc Corrugados
-- ============================================================

BEGIN;

-- ============================================================
-- 1. AGRANA FRUIT
--    Eliminar la oportunidad de tipo Actualización (carga manual)
--    OP-2512020000 — hijo de OP-2511191306
--    Primero eliminar el sitio referenciado (FK constraint)
-- ============================================================
DELETE FROM tb_sitios_oportunidad
WHERE id_oportunidad = '4945961f-94f3-478d-8a93-da40fe1f5a35';

DELETE FROM tb_oportunidades
WHERE id_oportunidad = '4945961f-94f3-478d-8a93-da40fe1f5a35';


-- ============================================================
-- 2. AVICOLAS KOLIBRI
--    Renombrar nombre_sitio en tb_sitios_oportunidad
--    a) Pre Oferta padre: OP-2602061259 (5 sitios)
--    b) Oferta Final hijo: OP-2603100648 (5 sitios heredados)
-- ============================================================

-- a) Sitios de Pre Oferta (OP-2602061259)
UPDATE tb_sitios_oportunidad SET nombre_sitio = 'TEPANCO'
  WHERE id_sitio = 'ec6fb696-4518-493a-8557-19b99dd0e6e5';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'CUACNOPALAN 1'
  WHERE id_sitio = '80447ada-a0a6-45c0-93f9-c27b314f0e94';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'CUACNOPALAN 2'
  WHERE id_sitio = '2649b539-3990-4835-83db-ec19e5f61f4a';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'CUAYUCATEPEC'
  WHERE id_sitio = 'af5cb40d-53b7-44a8-bcde-d40053c86c1b';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'POZO PALMAR'
  WHERE id_sitio = '5ee2c3cf-93f4-40b1-b6c2-6e82b2bb325c';

-- b) Sitios de Oferta Final hijo (OP-2603100648, creada 2026-03-10)
UPDATE tb_sitios_oportunidad SET nombre_sitio = 'TEPANCO'
  WHERE id_sitio = '442ed663-e6db-42ff-a167-6f61d488a721';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'CUACNOPALAN 1'
  WHERE id_sitio = '87dc78f9-da74-4149-a39f-6738569bf70f';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'CUACNOPALAN 2'
  WHERE id_sitio = '58d4266b-c6c2-41d7-a528-18e2b9810a41';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'CUAYUCATEPEC'
  WHERE id_sitio = 'cf382d14-dee7-494a-aaf4-30b0baaab6f5';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'POZO PALMAR'
  WHERE id_sitio = '3201d895-f10f-4b38-bcb1-c95318d327ac';


-- ============================================================
-- 3. HOTEL SUTUK
--    Actualizar tecnico_asignado_id del levantamiento
--    Levantamiento: 80171d80 (OP-2510161059)
--    Abdal A. Flores → Julio E. Euan Novelo
-- ============================================================
UPDATE tb_levantamientos
SET tecnico_asignado_id = 'b62f4c4e-abfb-4539-8088-38e1dfff5597',
    updated_at = NOW()
WHERE id_levantamiento = '80171d80-5c40-4dbb-b3a1-f6b066c0331e';


-- ============================================================
-- 4. LA TERMOPLASTIC FBM
--    Actualizar tecnico_asignado_id del levantamiento
--    Levantamiento: 3f69dfd2 (OP-2602060758)
--    Abdal A. Flores → Omar Mejía Guzmán
-- ============================================================
UPDATE tb_levantamientos
SET tecnico_asignado_id = 'c82342c7-19ca-4b4f-be9d-9a87863c9059',
    updated_at = NOW()
WHERE id_levantamiento = '3f69dfd2-30a2-40fc-a5e1-2b0f400b13ed';


-- ============================================================
-- 5. RESIDENCIAS LIBORIO
--    a) Actualizar tecnico del levantamiento (sitio 1)
--    b) Eliminar sitio 2 del Levantamiento + actualizar cantidad
--    c) Eliminar sitio 2 del Oferta Final + actualizar cantidad
-- ============================================================

-- a) Tecnico: Abdal A. Flores → Julio E. Euan Novelo
UPDATE tb_levantamientos
SET tecnico_asignado_id = 'b62f4c4e-abfb-4539-8088-38e1dfff5597',
    updated_at = NOW()
WHERE id_levantamiento = '006525fe-c25f-4165-a172-7902c1927758';

-- b) Eliminar sitio 2 de la oportunidad Levantamiento (OP-2601091018)
--    "SITIO SECUNDARIO - 2. Servicio 771" — sin levantamiento asociado
DELETE FROM tb_sitios_oportunidad
WHERE id_sitio = '95cf3781-225d-4e94-9eb7-ce6cf4e24aad';

UPDATE tb_oportunidades
SET cantidad_sitios = 1
WHERE id_oportunidad = '1a165eed-e8bd-4582-8b80-37fad5971fa3';

-- c) Eliminar sitio 2 de la oportunidad Oferta Final (OP-2601200737)
--    "SITIO SECUNDARIO - 2. Servicio 771"
DELETE FROM tb_sitios_oportunidad
WHERE id_sitio = '5f46ca34-7746-4407-8ba7-71e4dfa00ec7';

UPDATE tb_oportunidades
SET cantidad_sitios = 1
WHERE id_oportunidad = 'c04463ae-09dd-4cff-acd1-27b8fc2892ca';


-- ============================================================
-- 6. RESTAURANTES ALMORZERO DE PUEBLA
--    Renombrar nombre_sitio (direcciones ya correctas en BD)
--    OP-2601151420 — Pre Oferta, 2 sitios
-- ============================================================
UPDATE tb_sitios_oportunidad SET nombre_sitio = 'ZABALETA'
  WHERE id_sitio = '4c5b5203-b572-424c-b989-d962bdfecf38';

UPDATE tb_sitios_oportunidad SET nombre_sitio = 'CHOLULA'
  WHERE id_sitio = 'ed10622d-6308-4b24-ab6c-3307f990550e';


-- ============================================================
-- 7. VOESTALPINE
--    Actualizar tecnico_asignado_id del levantamiento
--    Levantamiento: 50aaf692 (OP-2508080000)
--    Abdal A. Flores → Francisco A. Alfaro Ferreyra
-- ============================================================
UPDATE tb_levantamientos
SET tecnico_asignado_id = '87bfc202-3f2d-4089-a6ee-3984f0afa6b5',
    updated_at = NOW()
WHERE id_levantamiento = '50aaf692-ef7b-4379-8753-fda3721770e4';


-- ============================================================
-- 8. CUMMINS
--    Actualizar tecnico_asignado_id del levantamiento
--    Levantamiento: a1a439fa (OP-2512041127)
--    Abdal A. Flores → Omar Mejía Guzmán
-- ============================================================
UPDATE tb_levantamientos
SET tecnico_asignado_id = 'c82342c7-19ca-4b4f-be9d-9a87863c9059',
    updated_at = NOW()
WHERE id_levantamiento = 'a1a439fa-9b93-48cd-980d-fc14aea55712';


-- ============================================================
-- 9. TENERIA PANAMERICANA DEL BAJIO
--    Renombrar nombre_sitio + corregir dirección PLANTA 319
--    (colonia cambia de "Cristóbal Colón" → "Echeveste Poniente")
--    4 oportunidades: Pre Oferta, Levantamiento, Oferta Final, Actualización
-- ============================================================

-- Pre Oferta (OP-2512011635)
UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 319',
    direccion    = 'Av. Transportistas 319, Echeveste Poniente, 37179 León de los Aldama, Gto.'
WHERE id_sitio = 'd943056e-ed2e-4a71-a770-d05853815f79';

UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 426'
WHERE id_sitio = '99a9ce70-9a73-4d8b-a794-26bf7b42bf51';

-- Levantamiento (OP-2512020853)
UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 319',
    direccion    = 'Av. Transportistas 319, Echeveste Poniente, 37179 León de los Aldama, Gto.'
WHERE id_sitio = '770ff732-cf79-4e50-9bc9-c55b0410628f';

UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 426'
WHERE id_sitio = '7847dc3c-751d-4f66-93e0-68bfb189aec1';

-- Oferta Final (OP-2512120937) — también limpia prefijo "Sitio 319/426:"
UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 319',
    direccion    = 'Av. Transportistas 319, Echeveste Poniente, 37179 León de los Aldama, Gto.'
WHERE id_sitio = 'a5e370a0-7436-416c-b85c-0fa7e8429e93';

UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 426',
    direccion    = 'Av. Transportistas 426-2, Cristóbal Colón, 37179 León de los Aldama, Gto.'
WHERE id_sitio = '7425152e-2312-474d-ba4f-a055331c4b3f';

-- Actualización (OP-2602271200) — también limpia prefijo "Sitio 319/426:"
UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 319',
    direccion    = 'Av. Transportistas 319, Echeveste Poniente, 37179 León de los Aldama, Gto.'
WHERE id_sitio = '16cf987e-0b23-4c49-9495-5ea0e90dff0a';

UPDATE tb_sitios_oportunidad
SET nombre_sitio = 'PLANTA 426',
    direccion    = 'Av. Transportistas 426-2, Cristóbal Colón, 37179 León de los Aldama, Gto.'
WHERE id_sitio = 'a14fd957-8a1f-461a-af2b-e1e0ccd16c8d';


-- ============================================================
-- 10. SEROC CORRUGADOS
--     Corregir id_tipo_solicitud: Actualización (4) → Pre Oferta (1)
--     OP-2601131542 (standalone, sin padre ni hijos)
-- ============================================================
UPDATE tb_oportunidades
SET id_tipo_solicitud = 1
WHERE id_oportunidad = '1744c59d-4b82-48e2-b43a-cb52834f51f0';


COMMIT;
