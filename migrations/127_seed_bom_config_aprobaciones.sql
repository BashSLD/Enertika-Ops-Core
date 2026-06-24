-- Migración 127: sembrar claves de configuración de aprobaciones del BOM
-- Hasta ahora estas claves solo existían como default en código (service.py y
-- admin/router.py). Sin fila en tb_configuracion_global, la pantalla de Admin las
-- mostraba con su default pero la clave no existía en BD con descripción.
-- Se siembran con sus defaults seguros e idempotentemente.

-- gestion_solo_responsable = true: solo el responsable del rol (o su suplente)
-- aprueba/rechaza el BOM; si false, cualquier titular del rol global puede.
INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'bom.gestion_solo_responsable', 'true',
       'Si true, solo el responsable asignado del proyecto (o su suplente) puede aprobar/rechazar el BOM; si false, cualquier titular del rol global puede', 'boolean'
WHERE NOT EXISTS (
    SELECT 1 FROM tb_configuracion_global WHERE clave = 'bom.gestion_solo_responsable'
);

-- director_bypass_aprobaciones = false: por defecto Dirección NO firma pasos
-- intermedios del BOM (solo ve); el toggle de Admin permite reactivarlo.
INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'bom.director_bypass_aprobaciones', 'false',
       'Si true, Dirección puede aprobar cualquier paso intermedio del BOM como respaldo, independientemente del responsable asignado', 'boolean'
WHERE NOT EXISTS (
    SELECT 1 FROM tb_configuracion_global WHERE clave = 'bom.director_bypass_aprobaciones'
);
