-- ─────────────────────────────────────────────────────────────────────────────
-- SEED DEV: Módulo RRHH, Vacaciones y Mi Perfil
-- Generado 2026-05-14
-- Ejecutar en SQL Editor de Supabase (proyecto DEV)
-- ─────────────────────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────
-- 1. Puestos en tb_usuarios + acceso RRHH
-- ─────────────────────────────────────────────
UPDATE tb_usuarios SET es_rh = true, puesto = 'Director General'
  WHERE id_usuario = '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'; -- Guillermo Rodriguez

UPDATE tb_usuarios SET es_rh = true, puesto = 'Líder de Sistemas'
  WHERE id_usuario = '33f7d1fd-da01-4e2e-b7a2-b6b9605c43e0'; -- Sebastian Leocadio

UPDATE tb_usuarios SET puesto = 'Gerente Comercial'         WHERE id_usuario = '6378efc4-1ae7-4e71-b866-55ea782677ff';
UPDATE tb_usuarios SET puesto = 'Gerente de Simulación'     WHERE id_usuario = '4d01f8b1-d26e-4479-86f3-04e4e726cd8f';
UPDATE tb_usuarios SET puesto = 'Gerente O&M'               WHERE id_usuario = 'aa8e6547-c009-4ec0-bd43-c8cf46364017';
UPDATE tb_usuarios SET puesto = 'Supervisora O&M'           WHERE id_usuario = '2ea4859c-8d17-4131-9d5a-78031f8ca6fd';
UPDATE tb_usuarios SET puesto = 'Gerente de Construcción'   WHERE id_usuario = 'f2b92d3b-c363-485e-b71b-f0894c0c4846';
UPDATE tb_usuarios SET puesto = 'Gerente de Ingeniería'     WHERE id_usuario = 'bdcf086c-6290-49c5-b35e-b4945b530d4b';
UPDATE tb_usuarios SET puesto = 'Supervisor de Construcción' WHERE id_usuario = 'fd87085f-3e38-4374-85d8-dc05cb70971e';
UPDATE tb_usuarios SET puesto = 'Instaladora'               WHERE id_usuario = 'f99addf0-f03a-48d6-9fd2-f931bb5aeeb5';
UPDATE tb_usuarios SET puesto = 'Coordinadora de Compras'   WHERE id_usuario = 'fe69291d-282f-466a-9edc-8c4c0dc8e2fd';
UPDATE tb_usuarios SET puesto = 'Ejecutiva Comercial'       WHERE id_usuario = 'eaaad3ae-9150-4ace-b48f-f89cf97d0baa';
UPDATE tb_usuarios SET puesto = 'Ingeniero de Proyectos'    WHERE id_usuario = '87bfc202-3f2d-4089-a6ee-3984f0afa6b5';
UPDATE tb_usuarios SET puesto = 'Auxiliar de Compras'       WHERE id_usuario = 'a02657af-c349-4c52-9a8e-9035309b2157';
UPDATE tb_usuarios SET puesto = 'Ejecutivo Comercial'       WHERE id_usuario = '26b89695-3b7a-4b64-a054-ceb193f32df1';
UPDATE tb_usuarios SET puesto = 'Técnico de Obra'           WHERE id_usuario = 'f1854bfb-4a6d-47d0-b7ab-15f8c0508bdb';
UPDATE tb_usuarios SET puesto = 'Ingeniero de Proyectos'    WHERE id_usuario = '70232911-3821-45a0-bc7c-e59a04510069';
UPDATE tb_usuarios SET puesto = 'Instalador'                WHERE id_usuario = '36e19f0d-4b0e-4aa0-8d4e-77783777e556';
UPDATE tb_usuarios SET puesto = 'Instalador'                WHERE id_usuario = 'b62f4c4e-abfb-4539-8088-38e1dfff5597';
UPDATE tb_usuarios SET puesto = 'Analista de Simulación'    WHERE id_usuario = '17846c8d-c38a-45b6-ae6d-80cf20560355';
UPDATE tb_usuarios SET puesto = 'Técnico Electricista'      WHERE id_usuario = '5a10cedc-7df1-4e89-a47c-a4b83693c7b4';
UPDATE tb_usuarios SET puesto = 'Ingeniero Eléctrico'       WHERE id_usuario = 'c82342c7-19ca-4b4f-be9d-9a87863c9059';
UPDATE tb_usuarios SET puesto = 'Analista Comercial'        WHERE id_usuario = '189b2baf-65be-4d5e-bf14-cc64017c9dd1';
UPDATE tb_usuarios SET puesto = 'Practicante'               WHERE id_usuario = 'c6aba847-ab12-4314-8caa-9410cdb6f828';

-- ─────────────────────────────────────────────
-- 2. Datos laborales (tb_empleados_datos)
-- id_aprobador_vacaciones = jefe directo que aprueba vacaciones
-- ─────────────────────────────────────────────
INSERT INTO tb_empleados_datos
  (usuario_id, numero_empleado, fecha_contratacion, puesto, departamento, id_aprobador_vacaciones, dias_vacaciones_ajuste)
VALUES
  -- Dirección
  ('7bb0b2e8-3e9c-4d35-981a-5c143d32aab9', 'EK-001', '2019-03-01', 'Director General',          'Dirección',    NULL,                                          5),
  -- Sistemas
  ('33f7d1fd-da01-4e2e-b7a2-b6b9605c43e0', 'EK-002', '2021-04-01', 'Líder de Sistemas',         'Sistemas',     '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',        0),
  -- Comercial
  ('6378efc4-1ae7-4e71-b866-55ea782677ff', 'EK-003', '2020-06-15', 'Gerente Comercial',          'Comercial',    '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',        0),
  ('eaaad3ae-9150-4ace-b48f-f89cf97d0baa', 'EK-004', '2022-08-15', 'Ejecutiva Comercial',        'Comercial',    '6378efc4-1ae7-4e71-b866-55ea782677ff',        0),
  ('26b89695-3b7a-4b64-a054-ceb193f32df1', 'EK-005', '2023-01-10', 'Ejecutivo Comercial',        'Comercial',    '6378efc4-1ae7-4e71-b866-55ea782677ff',        0),
  ('189b2baf-65be-4d5e-bf14-cc64017c9dd1', 'EK-006', '2022-11-01', 'Analista Comercial',         'Comercial',    '6378efc4-1ae7-4e71-b866-55ea782677ff',        0),
  -- Simulación
  ('4d01f8b1-d26e-4479-86f3-04e4e726cd8f', 'EK-007', '2021-01-10', 'Gerente de Simulación',      'Simulación',   '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',        0),
  ('17846c8d-c38a-45b6-ae6d-80cf20560355', 'EK-008', '2023-06-01', 'Analista de Simulación',     'Simulación',   '4d01f8b1-d26e-4479-86f3-04e4e726cd8f',        0),
  ('c6aba847-ab12-4314-8caa-9410cdb6f828', 'EK-009', '2024-01-15', 'Practicante',                'Simulación',   '4d01f8b1-d26e-4479-86f3-04e4e726cd8f',        0),
  -- O&M
  ('aa8e6547-c009-4ec0-bd43-c8cf46364017', 'EK-010', '2020-09-01', 'Gerente O&M',                'O & M',        '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',        0),
  ('2ea4859c-8d17-4131-9d5a-78031f8ca6fd', 'EK-011', '2021-07-20', 'Supervisora O&M',            'O & M',        'aa8e6547-c009-4ec0-bd43-c8cf46364017',        0),
  -- Construcción
  ('f2b92d3b-c363-485e-b71b-f0894c0c4846', 'EK-012', '2019-11-15', 'Gerente de Construcción',    'Construcción', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',        0),
  ('fd87085f-3e38-4374-85d8-dc05cb70971e', 'EK-013', '2021-09-01', 'Supervisor de Construcción', 'Construcción', 'f2b92d3b-c363-485e-b71b-f0894c0c4846',        0),
  ('f99addf0-f03a-48d6-9fd2-f931bb5aeeb5', 'EK-014', '2022-03-15', 'Instaladora',                'Construcción', 'f2b92d3b-c363-485e-b71b-f0894c0c4846',        0),
  ('f1854bfb-4a6d-47d0-b7ab-15f8c0508bdb', 'EK-015', '2023-04-01', 'Técnico de Obra',            'Construcción', 'f2b92d3b-c363-485e-b71b-f0894c0c4846',        0),
  ('36e19f0d-4b0e-4aa0-8d4e-77783777e556', 'EK-016', '2021-12-01', 'Instalador',                 'Construcción', 'f2b92d3b-c363-485e-b71b-f0894c0c4846',        0),
  ('b62f4c4e-abfb-4539-8088-38e1dfff5597', 'EK-017', '2022-07-01', 'Instalador',                 'Construcción', 'f2b92d3b-c363-485e-b71b-f0894c0c4846',        0),
  ('5a10cedc-7df1-4e89-a47c-a4b83693c7b4', 'EK-018', '2023-09-15', 'Técnico Electricista',       'Construcción', 'f2b92d3b-c363-485e-b71b-f0894c0c4846',        0),
  -- Ingeniería
  ('bdcf086c-6290-49c5-b35e-b4945b530d4b', 'EK-019', '2022-03-01', 'Gerente de Ingeniería',      'Ingeniería',   '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',        0),
  ('87bfc202-3f2d-4089-a6ee-3984f0afa6b5', 'EK-020', '2022-06-01', 'Ingeniero de Proyectos',     'Ingeniería',   'bdcf086c-6290-49c5-b35e-b4945b530d4b',        0),
  ('70232911-3821-45a0-bc7c-e59a04510069', 'EK-021', '2023-02-15', 'Ingeniero de Proyectos',     'Ingeniería',   'bdcf086c-6290-49c5-b35e-b4945b530d4b',        0),
  ('c82342c7-19ca-4b4f-be9d-9a87863c9059', 'EK-022', '2023-08-01', 'Ingeniero Eléctrico',        'Ingeniería',   'bdcf086c-6290-49c5-b35e-b4945b530d4b',        0),
  -- Compras
  ('fe69291d-282f-466a-9edc-8c4c0dc8e2fd', 'EK-023', '2022-01-15', 'Coordinadora de Compras',    'Compras',      '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',        0),
  ('a02657af-c349-4c52-9a8e-9035309b2157', 'EK-024', '2021-03-01', 'Auxiliar de Compras',        'Compras',      'fe69291d-282f-466a-9edc-8c4c0dc8e2fd',        0)
ON CONFLICT (usuario_id) DO UPDATE SET
  numero_empleado        = EXCLUDED.numero_empleado,
  fecha_contratacion     = EXCLUDED.fecha_contratacion,
  puesto                 = EXCLUDED.puesto,
  departamento           = EXCLUDED.departamento,
  id_aprobador_vacaciones = EXCLUDED.id_aprobador_vacaciones,
  dias_vacaciones_ajuste = EXCLUDED.dias_vacaciones_ajuste;

-- ─────────────────────────────────────────────
-- 3. Jerarquía de jefes (tb_empleados_jefes)
-- ─────────────────────────────────────────────
INSERT INTO tb_empleados_jefes (empleado_id, jefe_id) VALUES
  -- Reportan a Guillermo (Director)
  ('33f7d1fd-da01-4e2e-b7a2-b6b9605c43e0', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'), -- Sebastian
  ('6378efc4-1ae7-4e71-b866-55ea782677ff', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'), -- Sharon
  ('4d01f8b1-d26e-4479-86f3-04e4e726cd8f', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'), -- Eimy
  ('aa8e6547-c009-4ec0-bd43-c8cf46364017', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'), -- Brenda
  ('f2b92d3b-c363-485e-b71b-f0894c0c4846', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'), -- Leonardo
  ('bdcf086c-6290-49c5-b35e-b4945b530d4b', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'), -- Abdal
  ('fe69291d-282f-466a-9edc-8c4c0dc8e2fd', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9'), -- Daniela Moran
  -- Comercial → Sharon
  ('eaaad3ae-9150-4ace-b48f-f89cf97d0baa', '6378efc4-1ae7-4e71-b866-55ea782677ff'), -- Daniela Mendez
  ('26b89695-3b7a-4b64-a054-ceb193f32df1', '6378efc4-1ae7-4e71-b866-55ea782677ff'), -- Hector Fuentes
  ('189b2baf-65be-4d5e-bf14-cc64017c9dd1', '6378efc4-1ae7-4e71-b866-55ea782677ff'), -- Ximena
  -- Simulación → Eimy
  ('17846c8d-c38a-45b6-ae6d-80cf20560355', '4d01f8b1-d26e-4479-86f3-04e4e726cd8f'), -- Katia
  ('c6aba847-ab12-4314-8caa-9410cdb6f828', '4d01f8b1-d26e-4479-86f3-04e4e726cd8f'), -- User Test
  -- O&M → Brenda / Linda → Brenda
  ('2ea4859c-8d17-4131-9d5a-78031f8ca6fd', 'aa8e6547-c009-4ec0-bd43-c8cf46364017'), -- Linda → Brenda
  -- Construcción → Leonardo
  ('fd87085f-3e38-4374-85d8-dc05cb70971e', 'f2b92d3b-c363-485e-b71b-f0894c0c4846'), -- Arturo
  ('f99addf0-f03a-48d6-9fd2-f931bb5aeeb5', 'f2b92d3b-c363-485e-b71b-f0894c0c4846'), -- Claudia
  ('f1854bfb-4a6d-47d0-b7ab-15f8c0508bdb', 'f2b92d3b-c363-485e-b71b-f0894c0c4846'), -- Hector Sanchez
  ('36e19f0d-4b0e-4aa0-8d4e-77783777e556', 'f2b92d3b-c363-485e-b71b-f0894c0c4846'), -- Julio Callejas
  ('b62f4c4e-abfb-4539-8088-38e1dfff5597', 'f2b92d3b-c363-485e-b71b-f0894c0c4846'), -- Julio Euan
  ('5a10cedc-7df1-4e89-a47c-a4b83693c7b4', 'f2b92d3b-c363-485e-b71b-f0894c0c4846'), -- Miguel
  -- Ingeniería → Abdal
  ('87bfc202-3f2d-4089-a6ee-3984f0afa6b5', 'bdcf086c-6290-49c5-b35e-b4945b530d4b'), -- Francisco
  ('70232911-3821-45a0-bc7c-e59a04510069', 'bdcf086c-6290-49c5-b35e-b4945b530d4b'), -- Irving
  ('c82342c7-19ca-4b4f-be9d-9a87863c9059', 'bdcf086c-6290-49c5-b35e-b4945b530d4b'), -- Omar
  -- Compras → Daniela Moran
  ('a02657af-c349-4c52-9a8e-9035309b2157', 'fe69291d-282f-466a-9edc-8c4c0dc8e2fd')  -- Guadalupe → Daniela Moran
ON CONFLICT (empleado_id, jefe_id) DO NOTHING;

-- ─────────────────────────────────────────────
-- 4. Solicitudes de ausencia
-- Tipos: vacaciones=21fa4cec, HO=d8a64301, ext=f0a41f44, permiso_goce=e7c2a60a
-- ─────────────────────────────────────────────

-- 4A. APROBADAS ──────────────────────────────

-- Sharon: Vacaciones 7-16 enero 2026 (8 días) — aprobó Guillermo
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, aprobado_por, fecha_solicitud, fecha_resolucion, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000001',
  '6378efc4-1ae7-4e71-b866-55ea782677ff',
  '21fa4cec-c98b-439f-9bc2-1e611e7763af',
  '2026-01-07', '2026-01-16', 8, '2026-01-19',
  'aprobado', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',
  '2025-12-20 10:00:00-06', '2025-12-21 09:15:00-06',
  'Vacaciones de fin de año'
);

-- Daniela Mendez: Vacaciones 16-20 feb 2026 (5 días) — aprobó Sharon
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, aprobado_por, fecha_solicitud, fecha_resolucion, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000002',
  'eaaad3ae-9150-4ace-b48f-f89cf97d0baa',
  '21fa4cec-c98b-439f-9bc2-1e611e7763af',
  '2026-02-16', '2026-02-20', 5, '2026-02-23',
  'aprobado', '6378efc4-1ae7-4e71-b866-55ea782677ff',
  '2026-02-02 11:30:00-06', '2026-02-03 08:45:00-06',
  NULL
);

-- Katia: Vacaciones 10-14 marzo 2026 (5 días) — aprobó Eimy
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, aprobado_por, fecha_solicitud, fecha_resolucion, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000003',
  '17846c8d-c38a-45b6-ae6d-80cf20560355',
  '21fa4cec-c98b-439f-9bc2-1e611e7763af',
  '2026-03-10', '2026-03-14', 5, '2026-03-17',
  'aprobado', '4d01f8b1-d26e-4479-86f3-04e4e726cd8f',
  '2026-02-25 14:00:00-06', '2026-02-26 10:00:00-06',
  'Semana Santa anticipada'
);

-- Irving: Home Office 6-10 abril 2026 (5 días HO) — aprobó Abdal
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, aprobado_por, fecha_solicitud, fecha_resolucion, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000004',
  '70232911-3821-45a0-bc7c-e59a04510069',
  'd8a64301-5a35-4afe-ad9b-2f9d70ef7fc2',
  '2026-04-06', '2026-04-10', 5, '2026-04-13',
  'aprobado', 'bdcf086c-6290-49c5-b35e-b4945b530d4b',
  '2026-03-30 09:00:00-06', '2026-03-31 11:30:00-06',
  'Trabajo remoto — entrega de planos'
);

-- Sebastian: Vacaciones 23-27 marzo 2026 (5 días) — aprobó Guillermo
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, aprobado_por, fecha_solicitud, fecha_resolucion, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000005',
  '33f7d1fd-da01-4e2e-b7a2-b6b9605c43e0',
  '21fa4cec-c98b-439f-9bc2-1e611e7763af',
  '2026-03-23', '2026-03-27', 5, '2026-03-30',
  'aprobado', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9',
  '2026-03-10 10:00:00-06', '2026-03-11 08:00:00-06',
  'Semana Santa'
);

-- 4B. RECHAZADAS ─────────────────────────────

-- Arturo Garcia: Vacaciones 13-17 abril 2026 — rechazó Leonardo
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, aprobado_por, motivo_rechazo, fecha_solicitud, fecha_resolucion)
VALUES (
  'a1000001-0000-0000-0000-000000000006',
  'fd87085f-3e38-4374-85d8-dc05cb70971e',
  '21fa4cec-c98b-439f-9bc2-1e611e7763af',
  '2026-04-13', '2026-04-17', 5, '2026-04-20',
  'rechazado', 'f2b92d3b-c363-485e-b71b-f0894c0c4846',
  'Proyecto en fase crítica de instalación — reprogramar para mayo',
  '2026-04-01 08:30:00-06', '2026-04-02 09:00:00-06'
);

-- Hector Fuentes: Permiso sin goce 5-6 mayo 2026 — rechazó Sharon
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, aprobado_por, motivo_rechazo, fecha_solicitud, fecha_resolucion)
VALUES (
  'a1000001-0000-0000-0000-000000000007',
  '26b89695-3b7a-4b64-a054-ceb193f32df1',
  'dedc0ec2-9a01-4a66-8442-43115f583d76',
  '2026-05-05', '2026-05-06', 2, '2026-05-07',
  'rechazado', '6378efc4-1ae7-4e71-b866-55ea782677ff',
  'Cierre de propuesta con cliente — presencia requerida',
  '2026-04-28 16:00:00-06', '2026-04-29 10:00:00-06'
);

-- 4C. PENDIENTES ─────────────────────────────

-- Omar Mejia: Vacaciones 1-12 junio 2026 (10 días) — pendiente, aprobador Abdal
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, fecha_solicitud, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000008',
  'c82342c7-19ca-4b4f-be9d-9a87863c9059',
  '21fa4cec-c98b-439f-9bc2-1e611e7763af',
  '2026-06-01', '2026-06-12', 10, '2026-06-15',
  'pendiente', '2026-05-12 11:00:00-06',
  'Vacaciones de verano'
);

-- Daniela Moran: Home Office 18-22 mayo 2026 (5 días HO) — pendiente, aprobador Guillermo
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, fecha_solicitud, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000009',
  'fe69291d-282f-466a-9edc-8c4c0dc8e2fd',
  'd8a64301-5a35-4afe-ad9b-2f9d70ef7fc2',
  '2026-05-18', '2026-05-22', 5, '2026-05-25',
  'pendiente', '2026-05-13 09:30:00-06',
  'Trabajo desde casa — trámites personales'
);

-- Sebastian: Home Office 19-20 mayo 2026 (2 días HO) — pendiente, aprobador Guillermo
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, fecha_solicitud, observaciones)
VALUES (
  'a1000001-0000-0000-0000-000000000010',
  '33f7d1fd-da01-4e2e-b7a2-b6b9605c43e0',
  'd8a64301-5a35-4afe-ad9b-2f9d70ef7fc2',
  '2026-05-19', '2026-05-20', 2, '2026-05-21',
  'pendiente', '2026-05-14 08:00:00-06',
  'Home office — integración módulo asistencia'
);

-- Claudia Diaz: Vacaciones 8-12 junio 2026 — pendiente con firma_solicitante_pendiente
INSERT INTO tb_solicitudes_ausencia
  (id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados, fecha_presentarse,
   estado, fecha_solicitud, firma_solicitante_pendiente)
VALUES (
  'a1000001-0000-0000-0000-000000000011',
  'f99addf0-f03a-48d6-9fd2-f931bb5aeeb5',
  '21fa4cec-c98b-439f-9bc2-1e611e7763af',
  '2026-06-08', '2026-06-12', 5, '2026-06-15',
  'pendiente', '2026-05-14 07:45:00-06',
  true
);

-- ─────────────────────────────────────────────
-- 5. Consumo FIFO de vacaciones (solo para solicitudes aprobadas de tipo vacaciones)
-- num_periodo = año de antigüedad del que se consume
-- fecha_aniversario_periodo = fecha de inicio de ese período aniversario
-- ─────────────────────────────────────────────

-- Sharon (contratación 2020-06-15) → solicitud a1...001 (8 días) → consume período 5 (2024-06-15)
INSERT INTO tb_vacaciones_consumo (solicitud_id, num_periodo, dias_consumidos, fecha_aniversario_periodo)
VALUES ('a1000001-0000-0000-0000-000000000001', 5, 8, '2024-06-15');

-- Daniela Mendez (contratación 2022-08-15) → solicitud a1...002 (5 días) → consume período 3 (2024-08-15)
INSERT INTO tb_vacaciones_consumo (solicitud_id, num_periodo, dias_consumidos, fecha_aniversario_periodo)
VALUES ('a1000001-0000-0000-0000-000000000002', 3, 5, '2024-08-15');

-- Katia (contratación 2023-06-01) → solicitud a1...003 (5 días) → consume período 2 (2024-06-01)
INSERT INTO tb_vacaciones_consumo (solicitud_id, num_periodo, dias_consumidos, fecha_aniversario_periodo)
VALUES ('a1000001-0000-0000-0000-000000000003', 2, 5, '2024-06-01');

-- Sebastian (contratación 2021-04-01) → solicitud a1...005 (5 días) → consume período 5 (2025-04-01)
INSERT INTO tb_vacaciones_consumo (solicitud_id, num_periodo, dias_consumidos, fecha_aniversario_periodo)
VALUES ('a1000001-0000-0000-0000-000000000005', 5, 5, '2025-04-01');

-- ─────────────────────────────────────────────
-- 6. Firmas de solicitudes aprobadas
-- (solicitante + aprobador)
-- ─────────────────────────────────────────────

-- Solicitud 001 — Sharon / Guillermo
INSERT INTO tb_solicitudes_firmas (solicitud_id, firmante_id, rol_firma, fecha_firma) VALUES
  ('a1000001-0000-0000-0000-000000000001', '6378efc4-1ae7-4e71-b866-55ea782677ff', 'solicitante', '2025-12-20 10:05:00-06'),
  ('a1000001-0000-0000-0000-000000000001', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9', 'aprobador',   '2025-12-21 09:15:00-06');

-- Solicitud 002 — Daniela Mendez / Sharon
INSERT INTO tb_solicitudes_firmas (solicitud_id, firmante_id, rol_firma, fecha_firma) VALUES
  ('a1000001-0000-0000-0000-000000000002', 'eaaad3ae-9150-4ace-b48f-f89cf97d0baa', 'solicitante', '2026-02-02 11:35:00-06'),
  ('a1000001-0000-0000-0000-000000000002', '6378efc4-1ae7-4e71-b866-55ea782677ff', 'aprobador',   '2026-02-03 08:45:00-06');

-- Solicitud 003 — Katia / Eimy
INSERT INTO tb_solicitudes_firmas (solicitud_id, firmante_id, rol_firma, fecha_firma) VALUES
  ('a1000001-0000-0000-0000-000000000003', '17846c8d-c38a-45b6-ae6d-80cf20560355', 'solicitante', '2026-02-25 14:05:00-06'),
  ('a1000001-0000-0000-0000-000000000003', '4d01f8b1-d26e-4479-86f3-04e4e726cd8f', 'aprobador',   '2026-02-26 10:00:00-06');

-- Solicitud 004 — Irving / Abdal (HO — no requiere consumo pero sí firmas)
INSERT INTO tb_solicitudes_firmas (solicitud_id, firmante_id, rol_firma, fecha_firma) VALUES
  ('a1000001-0000-0000-0000-000000000004', '70232911-3821-45a0-bc7c-e59a04510069', 'solicitante', '2026-03-30 09:05:00-06'),
  ('a1000001-0000-0000-0000-000000000004', 'bdcf086c-6290-49c5-b35e-b4945b530d4b', 'aprobador',   '2026-03-31 11:30:00-06');

-- Solicitud 005 — Sebastian / Guillermo
INSERT INTO tb_solicitudes_firmas (solicitud_id, firmante_id, rol_firma, fecha_firma) VALUES
  ('a1000001-0000-0000-0000-000000000005', '33f7d1fd-da01-4e2e-b7a2-b6b9605c43e0', 'solicitante', '2026-03-10 10:05:00-06'),
  ('a1000001-0000-0000-0000-000000000005', '7bb0b2e8-3e9c-4d35-981a-5c143d32aab9', 'aprobador',   '2026-03-11 08:00:00-06');

-- ─────────────────────────────────────────────
-- VERIFICACIÓN RÁPIDA
-- ─────────────────────────────────────────────
SELECT
  u.nombre,
  e.numero_empleado,
  e.puesto,
  e.departamento,
  e.fecha_contratacion,
  ap.nombre AS aprobador
FROM tb_empleados_datos e
JOIN tb_usuarios u ON u.id_usuario = e.usuario_id
LEFT JOIN tb_usuarios ap ON ap.id_usuario = e.id_aprobador_vacaciones
ORDER BY e.departamento, e.numero_empleado;
