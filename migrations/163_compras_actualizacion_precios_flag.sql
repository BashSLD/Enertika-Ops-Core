-- Feature flag para la tab "Actualizacion de precios" de Compras (BOMs en BORRADOR)
-- y su modal de escritura de costo/moneda. Kill-switch de despliegue, igual patron
-- que bom.multi_paquete_habilitado (migracion 160).

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
VALUES (
    'compras.actualizacion_precios_habilitada',
    'false',
    'Habilita la tab de Actualizacion de precios en Compras y el modal de escritura de costo/moneda sobre BOMs en BORRADOR.',
    'boolean'
)
ON CONFLICT (clave) DO NOTHING;
