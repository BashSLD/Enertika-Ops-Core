-- Columnas data-driven en tb_cat_tipos_ausencia para permisos horarios (llegar tarde /
-- salir temprano): reemplazan comparaciones hardcodeadas de slug en
-- modules/vacaciones/service.py por flags de catalogo.

ALTER TABLE tb_cat_tipos_ausencia ADD COLUMN IF NOT EXISTS requiere_hora_llegada boolean NOT NULL DEFAULT false;
ALTER TABLE tb_cat_tipos_ausencia ADD COLUMN IF NOT EXISTS requiere_hora_salida boolean NOT NULL DEFAULT false;
ALTER TABLE tb_cat_tipos_ausencia ADD COLUMN IF NOT EXISTS un_solo_dia boolean NOT NULL DEFAULT false;
ALTER TABLE tb_cat_tipos_ausencia ADD COLUMN IF NOT EXISTS combinable_con_tipo_id uuid NULL;

DO $$ BEGIN
  ALTER TABLE tb_cat_tipos_ausencia
    ADD CONSTRAINT fk_tipos_ausencia_combinable
    FOREIGN KEY (combinable_con_tipo_id) REFERENCES tb_cat_tipos_ausencia(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

UPDATE tb_cat_tipos_ausencia
SET requiere_hora_llegada = true,
    un_solo_dia = true,
    combinable_con_tipo_id = (SELECT id FROM tb_cat_tipos_ausencia WHERE slug = 'permiso_salir_temprano')
WHERE slug = 'permiso_llegar_tarde';

UPDATE tb_cat_tipos_ausencia
SET requiere_hora_salida = true,
    un_solo_dia = true,
    combinable_con_tipo_id = (SELECT id FROM tb_cat_tipos_ausencia WHERE slug = 'permiso_llegar_tarde')
WHERE slug = 'permiso_salir_temprano';
