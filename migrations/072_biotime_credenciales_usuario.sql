-- Migración 072: reemplazar BIOTIME_ACCESS_KEY por BIOTIME_USERNAME + BIOTIME_PASSWORD
-- El código ahora usa autenticación por sesión Django (usuario/contraseña) en lugar de API key.

-- Agregar claves nuevas si no existen
INSERT INTO tb_configuracion_global (clave, valor, descripcion)
VALUES
    ('BIOTIME_USERNAME', '', 'Usuario para autenticación en BioTime PRO'),
    ('BIOTIME_PASSWORD', '', 'Contraseña para autenticación en BioTime PRO')
ON CONFLICT (clave) DO NOTHING;

-- Dejar BIOTIME_ACCESS_KEY en BD para no romper instancias que aun no migraron,
-- pero marcarla como obsoleta en la descripcion.
UPDATE tb_configuracion_global
SET descripcion = '[OBSOLETA - reemplazada por BIOTIME_USERNAME y BIOTIME_PASSWORD]'
WHERE clave = 'BIOTIME_ACCESS_KEY';
