-- Mapeo persistido de carpeta SharePoint por proyecto (id_proyecto), resuelto por busqueda automatica o seleccion manual

ALTER TABLE tb_proyectos_gate
    ADD COLUMN IF NOT EXISTS sharepoint_folder_id TEXT,
    ADD COLUMN IF NOT EXISTS sharepoint_drive_id TEXT,
    ADD COLUMN IF NOT EXISTS sharepoint_resuelto_en TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sharepoint_origen TEXT
        CHECK (sharepoint_origen IN ('BUSQUEDA_AUTOMATICA', 'MANUAL'));

-- Config para identificar la carpeta administrativa "Proyectos sin expediente" en
-- el drive de Visitas — se usa como fallback deliberado cuando no se encuentra la
-- carpeta del proyecto, y se excluye del matching fuzzy por proyecto para evitar
-- falsos positivos contra ella.
INSERT INTO tb_configuracion_global (clave, valor, descripcion)
VALUES
    ('SP_VISITAS_CARPETA_SIN_EXPEDIENTE', 'Proyectos sin expediente', 'Nombre de la carpeta administrativa de fallback en el drive de Visitas cuando no se encuentra la carpeta del proyecto')
ON CONFLICT (clave) DO NOTHING;
