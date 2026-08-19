-- Elimina tb_bom_propuestas_cambio (mecanismo "propuesta de cambio pre-final" de
-- Construccion/Obra fuera de turno). Muerto desde el refactor a multi-BOM (36173b5,
-- 2026-08-05): requiere_propuesta_construccion()/base_construccion_bloqueada() quedaron
-- hardcoded a False (Construccion/Obra edita directo en su turno) y el endpoint manual
-- de creacion nunca tuvo boton/form en la UI. Confirmado sin uso real: 0 filas siempre
-- en PROD, 1 fila de fixture de QA en DEV. Sin FKs de otras tablas apuntando a esta.

DROP TABLE IF EXISTS tb_bom_propuestas_cambio;
