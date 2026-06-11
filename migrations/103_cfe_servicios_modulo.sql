-- Agrega columna modulos (array) a tb_cfe_servicios para que un servicio pueda pertenecer a uno o ambos departamentos
ALTER TABLE tb_cfe_servicios
    ADD COLUMN IF NOT EXISTS modulos TEXT[] NOT NULL DEFAULT '{oym}';
