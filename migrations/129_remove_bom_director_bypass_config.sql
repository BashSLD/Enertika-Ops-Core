-- Limpia la configuracion legacy que permitia a Direccion aprobar pasos
-- intermedios del workflow BOM. El flujo ahora exige Obra y Construccion.

DELETE FROM tb_configuracion_global
WHERE clave = 'bom.director_bypass_aprobaciones';
