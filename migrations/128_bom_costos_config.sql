-- Configuracion para validacion/notificacion de costos pendientes en BOM.
-- Idempotente: no sobreescribe valores editados desde Admin.

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
VALUES
    (
        'bom.costos_notificacion_asunto',
        'BOM {proyecto_id} - Items sin costo asignado',
        'Asunto del correo enviado a Compras cuando un BOM tiene items sin costo.',
        'string'
    ),
    (
        'bom.costos_notificacion_template',
        'El ingeniero ingreso {total_items} item(s) para el BOM del proyecto {proyecto_id} sin costo asignado. Ingresa para actualizar el/los item(s).',
        'Texto base del correo enviado a Compras cuando un BOM tiene items sin costo.',
        'string'
    ),
    (
        'bom.costos_notificacion_sse_activa',
        'false',
        'Activa aviso SSE interno a usuarios de Compras cuando se notifican items sin costo en BOM.',
        'boolean'
    )
ON CONFLICT (clave) DO NOTHING;
