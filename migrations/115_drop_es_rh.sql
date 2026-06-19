-- Elimina columna muerta es_rh de tb_usuarios.
-- El acceso real a módulo RRHH usa RBAC estándar (tb_permisos_modulos slug=rrhh).
ALTER TABLE tb_usuarios DROP COLUMN IF EXISTS es_rh;
