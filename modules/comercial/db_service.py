
# SQL Queries for Commercial Module

QUERY_GET_OPORTUNIDADES_LIST = """
    SELECT
        o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre, o.canal_venta,
        o.fecha_solicitud, estatus.nombre as status_global, o.email_enviado, o.id_interno_simulacion,
        tipo_sol.nombre as tipo_solicitud, o.deadline_calculado, o.deadline_negociado, o.cantidad_sitios,
        o.titulo_proyecto, o.prioridad, o.es_fuera_horario,
        o.es_licitacion, o.fecha_entrega_simulacion,
        o.fecha_ideal_usuario, o.google_maps_link,
        u_creador.nombre as solicitado_por,
        u_sim.nombre as responsable_simulacion,
        u_sim.email as responsable_email,
        CASE WHEN db.id IS NOT NULL THEN true ELSE false END as tiene_detalles_bess,
        lev_estatus.nombre as status_levantamiento,
        lev.fecha_visita_programada as fecha_programada,
        lev.id_levantamiento,
        u_tecnico.nombre as tecnico_asignado_nombre,
        pg.id_proyecto,
        COALESCE(pg.proyectos_count, 0) as proyectos_count,
        pg.area_actual AS proyecto_area_actual
    FROM tb_oportunidades o
    LEFT JOIN tb_cat_estatus_oportunidades estatus ON o.id_estatus_global = estatus.id
    LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
    LEFT JOIN tb_usuarios u_creador ON o.creado_por_id = u_creador.id_usuario
    LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
    LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
    LEFT JOIN (
        SELECT DISTINCT ON (l.id_oportunidad)
            l.id_oportunidad, l.id_levantamiento, l.id_estatus_global,
            l.fecha_visita_programada, l.tecnico_asignado_id
        FROM tb_levantamientos l
        ORDER BY l.id_oportunidad, l.id_estatus_global ASC
    ) lev ON o.id_oportunidad = lev.id_oportunidad
    LEFT JOIN tb_cat_estatus_levantamiento lev_estatus ON lev.id_estatus_global = lev_estatus.id
    LEFT JOIN tb_usuarios u_tecnico ON lev.tecnico_asignado_id = u_tecnico.id_usuario
    LEFT JOIN (
        SELECT
            p.id_oportunidad,
            (ARRAY_AGG(p.id_proyecto ORDER BY p.created_at DESC NULLS LAST))[1] AS id_proyecto,
            COUNT(*)::int AS proyectos_count,
            (ARRAY_AGG(p.area_actual ORDER BY p.fecha_inicio_area DESC NULLS LAST, p.created_at DESC NULLS LAST))[1] AS area_actual
        FROM tb_proyectos_gate p
        GROUP BY p.id_oportunidad
    ) pg ON pg.id_oportunidad = o.id_oportunidad
    WHERE o.email_enviado = true
"""

QUERY_INSERT_HISTORIAL_ESTATUS = """
    INSERT INTO tb_historial_estatus (
        id_oportunidad, id_estatus_anterior, id_estatus_nuevo, 
        fecha_cambio_real, fecha_cambio_sla, cambiado_por_id
    ) VALUES (
        $1, $2, $3, $4, $5, $6
    )
"""

QUERY_GET_OPORTUNIDAD_OWNER = "SELECT creado_por_id FROM tb_oportunidades WHERE id_oportunidad = $1"
QUERY_GET_OPORTUNIDAD_FROM_SITIO = "SELECT id_oportunidad FROM tb_sitios_oportunidad WHERE id_sitio = $1"

QUERY_INSERT_OPORTUNIDAD = """
    INSERT INTO tb_oportunidades (
        id_oportunidad, op_id_estandar, id_interno_simulacion,
        titulo_proyecto, nombre_proyecto, cliente_nombre, cliente_id, canal_venta,
        id_tecnologia, id_tipo_solicitud, id_estatus_global,
        cantidad_sitios, prioridad,
        direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
        creado_por_id, fecha_solicitud,
        es_fuera_horario, deadline_calculado,
        solicitado_por, es_carga_manual,
        clasificacion_solicitud, solicitado_por_id, es_licitacion,
        fecha_ideal_usuario,
        parent_id
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $26, $7,
        $8, $9, $22,
        $10, $11, $12, $13, $14, $15,
        $16, $17,
        $18, $19,
        $20, $21,
        $23, $24, $25,
        $27,
        $28
    )
"""

QUERY_BUSCAR_OPORTUNIDADES_PARA_RELACIONAR = """
    SELECT
        id_oportunidad,
        titulo_proyecto,
        op_id_estandar,
        fecha_solicitud AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud
    FROM tb_oportunidades
    WHERE email_enviado = true
    AND parent_id IS NULL
    AND (
        titulo_proyecto ILIKE $1
        OR cliente_nombre ILIKE $1
        OR op_id_estandar ILIKE $1
    )
    ORDER BY fecha_solicitud DESC
    LIMIT 10
"""

QUERY_INSERT_FOLLOWUP = """
    INSERT INTO tb_oportunidades (
        id_oportunidad, creado_por_id, parent_id,
        titulo_proyecto, nombre_proyecto, cliente_nombre, cliente_id,
        canal_venta, solicitado_por,
        id_tecnologia, id_tipo_solicitud, cantidad_sitios, prioridad,
        direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
        id_interno_simulacion, op_id_estandar,
        id_estatus_global,     -- $22 (Dinámico)
        deadline_calculado, es_fuera_horario, 
        fecha_solicitud,       -- $23 (now_mx)
        email_enviado,
        es_licitacion,         -- HEREDADO
        fecha_ideal_usuario,
        conversion_pendiente,  -- $26
        sitios_json_pendiente  -- $27
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, 
        $22,  -- ID Estatus (Ya no es 1 fijo)
        $20, $21, 
        $23,  -- Fecha Solicitud (Ya no es NOW())
        FALSE,
        $24,   -- es_licitacion
        $25,   -- fecha_ideal_usuario (heredada o default)
        $26,   -- conversion_pendiente
        $27    -- sitios_json_pendiente
    ) RETURNING id_oportunidad
"""

QUERY_CLONE_SITIOS = """
    INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa, google_maps_link, numero_servicio, comentarios, id_estatus_global, id_tipo_solicitud)
    SELECT gen_random_uuid(), $1, nombre_sitio, direccion, tipo_tarifa, google_maps_link, numero_servicio, comentarios, $4, $3
    FROM tb_sitios_oportunidad WHERE id_oportunidad = $2
"""

# Catalog Queries
QUERY_GET_TECNOLOGIAS = "SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
QUERY_GET_TIPOS_SOLICITUD = "SELECT id, nombre, codigo_interno FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
QUERY_GET_ESTATUS_GLOBAL = "SELECT id, nombre FROM tb_cat_estatus_oportunidades WHERE activo = true AND modulo_aplicable IN ('SIMULACION', 'COMERCIAL') ORDER BY nombre"
QUERY_GET_USUARIOS_COMERCIAL = """
    SELECT id_usuario as id, nombre 
    FROM tb_usuarios 
    WHERE is_active = true AND department IN ('Comercial')
    ORDER BY nombre
"""
QUERY_GET_ALL_USUARIOS = "SELECT id_usuario, nombre FROM tb_usuarios WHERE is_active = true ORDER BY nombre"

QUERY_GET_TIPO_ACTUALIZACION_ID = "SELECT id FROM tb_cat_tipos_solicitud WHERE codigo_interno = 'ACTUALIZACION' AND activo = true"

# Validation & Access
QUERY_CHECK_USER_TOKEN = "SELECT CASE WHEN access_token IS NOT NULL THEN true ELSE false END FROM tb_usuarios WHERE id_usuario = $1"

# Lookup Helpers
QUERY_GET_TECNOLOGIA_NAME = "SELECT nombre FROM tb_cat_tecnologias WHERE id = $1"
QUERY_GET_TIPO_SOLICITUD_ID_BY_CODE = "SELECT id FROM tb_cat_tipos_solicitud WHERE UPPER(codigo_interno) = UPPER($1)"
QUERY_GET_TIPO_SOLICITUD_CODE = "SELECT codigo_interno FROM tb_cat_tipos_solicitud WHERE id = $1"
QUERY_GET_TIPO_SOLICITUD_NAME = "SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1"
QUERY_GET_USER_NAME = "SELECT nombre FROM tb_usuarios WHERE id_usuario = $1"

# BESS
QUERY_GET_DETALLES_BESS = """
    SELECT 
        db.uso_sistema_json,
        db.cargas_criticas_kw,
        db.tiene_motores,
        db.potencia_motor_hp,
        db.tiempo_autonomia,
        db.voltaje_operacion,
        db.cargas_separadas,
        db.tiene_planta_emergencia
    FROM tb_detalles_bess db
    WHERE db.id_oportunidad = $1
"""

# Workflow & Notifications
QUERY_GET_COMENTARIOS_WORKFLOW = """
    WITH cadena AS (
        SELECT id_oportunidad FROM tb_oportunidades WHERE id_oportunidad = $1
        UNION
        SELECT id_oportunidad FROM tb_oportunidades WHERE parent_id = $1
        UNION
        SELECT parent_id FROM tb_oportunidades 
        WHERE id_oportunidad = $1 AND parent_id IS NOT NULL
        UNION
        SELECT id_oportunidad FROM tb_oportunidades 
        WHERE parent_id = (
            SELECT parent_id FROM tb_oportunidades WHERE id_oportunidad = $1
        ) AND parent_id IS NOT NULL
    )
    SELECT 
        cw.comentario,
        cw.usuario_nombre,
        cw.modulo_origen,
        cw.fecha_comentario AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City' as fecha_comentario,
        op.op_id_estandar as comentario_op_estandar
    FROM tb_comentarios_workflow cw
    LEFT JOIN tb_oportunidades op ON cw.id_oportunidad = op.id_oportunidad
    WHERE cw.id_oportunidad IN (SELECT id_oportunidad FROM cadena)
    ORDER BY cw.fecha_comentario DESC
"""

# Site Management
QUERY_GET_CANTIDAD_SITIOS = "SELECT cantidad_sitios FROM tb_oportunidades WHERE id_oportunidad = $1"
QUERY_GET_TIPO_SOLICITUD_FROM_OP = "SELECT id_tipo_solicitud FROM tb_oportunidades WHERE id_oportunidad = $1"
QUERY_DELETE_SITIOS_OP = "DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1"
QUERY_INSERT_SITIO_BULK = """
    INSERT INTO tb_sitios_oportunidad (
        id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa,
        google_maps_link, numero_servicio, comentarios, id_estatus_global, id_tipo_solicitud
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""
QUERY_DELETE_SITIO = "DELETE FROM tb_sitios_oportunidad WHERE id_sitio = $1"
QUERY_GET_SITIOS_SIMPLE = "SELECT * FROM tb_sitios_oportunidad WHERE id_oportunidad = $1 ORDER BY fecha_carga ASC"

QUERY_INSERT_SITIO_UNICO = """
    INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, nombre_sitio, direccion, google_maps_link, id_tipo_solicitud, id_estatus_global)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
"""

QUERY_GET_ULTIMO_MOVIMIENTO_HILO = """
    WITH root AS (
        SELECT COALESCE(parent_id, id_oportunidad) AS root_id
        FROM tb_oportunidades
        WHERE id_oportunidad = $1
    )
    SELECT o.id_oportunidad, o.op_id_estandar, ts.nombre AS tipo_solicitud
    FROM tb_oportunidades o
    JOIN tb_cat_tipos_solicitud ts ON ts.id = o.id_tipo_solicitud
    CROSS JOIN root
    WHERE (o.id_oportunidad = root.root_id OR o.parent_id = root.root_id)
      AND o.email_enviado = TRUE
    ORDER BY o.fecha_creacion DESC
    LIMIT 1
"""

QUERY_CHECK_GRUPO_BLOQUEADOR = """
    WITH root AS (
        SELECT COALESCE(parent_id, id_oportunidad) AS id
        FROM tb_oportunidades
        WHERE id_oportunidad = $1
    ),
    t_op AS (
        SELECT id FROM tb_cat_estatus_oportunidades
        WHERE LOWER(nombre) IN ('ganada', 'cancelado', 'perdido', 'entregado')
    ),
    t_lev AS (
        SELECT id FROM tb_cat_estatus_levantamiento
        WHERE LOWER(nombre) IN ('completado', 'cancelado', 'entregado')
    ),
    miembros AS (
        SELECT o.id_oportunidad, o.op_id_estandar,
               ce.nombre AS estado_op,
               ts.nombre AS tipo_solicitud,
               o.id_estatus_global
        FROM tb_oportunidades o
        JOIN tb_cat_estatus_oportunidades ce ON ce.id = o.id_estatus_global
        JOIN tb_cat_tipos_solicitud ts ON ts.id = o.id_tipo_solicitud
        CROSS JOIN root
        WHERE o.id_oportunidad = root.id OR o.parent_id = root.id
    )
    SELECT
        EXISTS(
            SELECT 1 FROM miembros WHERE LOWER(estado_op) = 'ganada'
        ) AS grupo_ganado,
        EXISTS(
            SELECT 1 FROM miembros WHERE id_estatus_global NOT IN (SELECT id FROM t_op)
        ) AS tiene_activo_op,
        EXISTS(
            SELECT 1
            FROM miembros m
            JOIN tb_levantamientos l ON l.id_oportunidad = m.id_oportunidad
            JOIN tb_cat_estatus_levantamiento cel ON cel.id = l.id_estatus_global
            WHERE l.id_estatus_global NOT IN (SELECT id FROM t_lev)
        ) AS tiene_activo_lev,
        (SELECT op_id_estandar FROM miembros
         WHERE id_estatus_global NOT IN (SELECT id FROM t_op) LIMIT 1) AS bloqueador_op_id,
        (SELECT estado_op FROM miembros
         WHERE id_estatus_global NOT IN (SELECT id FROM t_op) LIMIT 1) AS bloqueador_op_estado,
        (SELECT tipo_solicitud FROM miembros
         WHERE id_estatus_global NOT IN (SELECT id FROM t_op) LIMIT 1) AS bloqueador_op_tipo,
        (SELECT m.op_id_estandar
         FROM miembros m
         JOIN tb_levantamientos l ON l.id_oportunidad = m.id_oportunidad
         JOIN tb_cat_estatus_levantamiento cel ON cel.id = l.id_estatus_global
         WHERE l.id_estatus_global NOT IN (SELECT id FROM t_lev) LIMIT 1) AS bloqueador_lev_op_id,
        (SELECT cel.nombre
         FROM miembros m
         JOIN tb_levantamientos l ON l.id_oportunidad = m.id_oportunidad
         JOIN tb_cat_estatus_levantamiento cel ON cel.id = l.id_estatus_global
         WHERE l.id_estatus_global NOT IN (SELECT id FROM t_lev) LIMIT 1) AS bloqueador_lev_estado,
        (SELECT op_id_estandar FROM miembros WHERE LOWER(estado_op) = 'ganada' LIMIT 1) AS ganado_op_id
"""

# Updates
QUERY_UPDATE_EMAIL_ENVIADO = "UPDATE tb_oportunidades SET email_enviado = TRUE WHERE id_oportunidad = $1"
QUERY_UPDATE_PRIORIDAD = "UPDATE tb_oportunidades SET prioridad = $1 WHERE id_oportunidad = $2"
QUERY_UPDATE_OPORTUNIDAD_OWNER = "UPDATE tb_oportunidades SET creado_por_id = $1 WHERE id_oportunidad = $2"

# Publicar borrador: marca como enviado y fija fecha/SLA al momento real del envío
QUERY_PUBLISH_BORRADOR = """
    UPDATE tb_oportunidades
    SET email_enviado    = TRUE,
        fecha_solicitud  = $2,
        es_fuera_horario = $3,
        deadline_calculado = $4
    WHERE id_oportunidad = $1
"""

# Corrige las fechas del registro inicial de historial (id_estatus_anterior IS NULL)
QUERY_UPDATE_HISTORIAL_INICIAL_FECHAS = """
    UPDATE tb_historial_estatus
    SET fecha_cambio_real = $2,
        fecha_cambio_sla  = $3
    WHERE id_oportunidad = $1
      AND id_estatus_anterior IS NULL
"""

# Deletions
QUERY_DELETE_OPORTUNIDAD = "DELETE FROM tb_oportunidades WHERE id_oportunidad = $1"
# (Others are simple deletes, usually inline is acceptable if simple, but better in consts)
QUERY_DELETE_COMENTARIOS_WF = "DELETE FROM tb_comentarios_workflow WHERE id_oportunidad = $1"
QUERY_DELETE_NOTIFICACIONES = "DELETE FROM tb_notificaciones WHERE id_oportunidad = $1"
QUERY_DELETE_DOCS = "DELETE FROM tb_documentos_attachments WHERE id_oportunidad = $1"
QUERY_DELETE_LEVANTAMIENTOS = "DELETE FROM tb_levantamientos WHERE id_oportunidad = $1"
QUERY_DELETE_BESS = "DELETE FROM tb_detalles_bess WHERE id_oportunidad = $1"

# Clients
QUERY_SEARCH_CLIENTES = """
    SELECT id, nombre_fiscal
    FROM tb_clientes
    WHERE nombre_fiscal ILIKE $1
    ORDER BY nombre_fiscal
    LIMIT 10
"""
QUERY_GET_CLIENTE_BY_ID = "SELECT nombre_fiscal, id_interno_simulacion FROM tb_clientes WHERE id = $1"
QUERY_GET_OLDEST_OP_BY_CLIENTE = "SELECT op_id_estandar FROM tb_oportunidades WHERE cliente_id = $1 ORDER BY fecha_solicitud ASC LIMIT 1"
QUERY_UPDATE_CLIENTE_ID_INTERNO = "UPDATE tb_clientes SET id_interno_simulacion = $1 WHERE id = $2"

# Oportunidad Full (for followup creation)
QUERY_GET_OPORTUNIDAD_FULL = "SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1"

# Paso 2 form data
QUERY_GET_PASO2_DATA = """
    SELECT id_interno_simulacion, titulo_proyecto, cliente_nombre, cantidad_sitios
    FROM tb_oportunidades WHERE id_oportunidad = $1
"""

# Site Management (extended)
QUERY_GET_SITIO_IDS_BY_OP = "SELECT id_sitio FROM tb_sitios_oportunidad WHERE id_oportunidad = $1"
QUERY_DELETE_SITIOS_BY_IDS = "DELETE FROM tb_sitios_oportunidad WHERE id_sitio = ANY($1::uuid[])"
QUERY_RELINK_LEVANTAMIENTOS = "UPDATE tb_levantamientos SET id_sitio = $1 WHERE id_oportunidad = $2"
QUERY_UPDATE_CANTIDAD_SITIOS = "UPDATE tb_oportunidades SET cantidad_sitios = $1 WHERE id_oportunidad = $2"
QUERY_COUNT_SITIOS_BY_OP = "SELECT count(*) FROM tb_sitios_oportunidad WHERE id_oportunidad = $1"

# Conversión unisitio → multisitio
QUERY_RENAME_ORIGINAL_SITE = """
    UPDATE tb_sitios_oportunidad
    SET nombre_sitio = 'Sitio 1'
    WHERE id_oportunidad = $1
      AND (nombre_sitio IS NULL OR TRIM(nombre_sitio) = '')
"""
QUERY_INCREMENT_CANTIDAD_SITIOS = """
    UPDATE tb_oportunidades
    SET cantidad_sitios = cantidad_sitios + $1
    WHERE id_oportunidad = $2
"""

# Conversión diferida: leer y limpiar datos pendientes
QUERY_GET_CONVERSION_PENDIENTE = """
    SELECT conversion_pendiente, sitios_json_pendiente, parent_id
    FROM tb_oportunidades
    WHERE id_oportunidad = $1
"""

QUERY_CLEAR_CONVERSION_PENDIENTE = """
    UPDATE tb_oportunidades
    SET conversion_pendiente = FALSE,
        sitios_json_pendiente = NULL
    WHERE id_oportunidad = $1
"""

# Status Updates (cierre de venta)
QUERY_GET_OP_ESTATUS = "SELECT id_estatus_global FROM tb_oportunidades WHERE id_oportunidad = $1"
QUERY_UPDATE_OP_ESTATUS = "UPDATE tb_oportunidades SET id_estatus_global = $1 WHERE id_oportunidad = $2"
QUERY_UPDATE_SITIOS_ESTATUS_BY_IDS = """
    UPDATE tb_sitios_oportunidad SET id_estatus_global = $1
    WHERE id_sitio = ANY($2) AND id_oportunidad = $3
"""
QUERY_UPDATE_SITIOS_ESTATUS_OTHERS = """
    UPDATE tb_sitios_oportunidad SET id_estatus_global = $1
    WHERE id_oportunidad = $2 AND id_sitio != ALL($3) AND id_estatus_global = $4
"""
QUERY_UPDATE_SITIOS_ESTATUS_ALL = """
    UPDATE tb_sitios_oportunidad SET id_estatus_global = $1
    WHERE id_oportunidad = $2
"""

# Borradores (email_enviado = false, < 24h)
QUERY_GET_BORRADORES = """
    SELECT
        o.id_oportunidad, o.op_id_estandar, o.id_interno_simulacion,
        o.cliente_nombre, o.nombre_proyecto, o.titulo_proyecto,
        o.canal_venta, o.cantidad_sitios, o.fecha_creacion,
        tec.nombre as tipo_tecnologia,
        tipo_sol.nombre as tipo_solicitud,
        u.nombre as creado_por_nombre,
        EXTRACT(EPOCH FROM (o.fecha_creacion + INTERVAL '24 hours' - NOW()))::int
            AS segundos_restantes
    FROM tb_oportunidades o
    LEFT JOIN tb_cat_tecnologias tec ON o.id_tecnologia = tec.id
    LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
    LEFT JOIN tb_usuarios u ON o.creado_por_id = u.id_usuario
    WHERE o.email_enviado = false
      AND o.fecha_creacion > NOW() - INTERVAL '24 hours'
    ORDER BY o.fecha_creacion DESC
"""

QUERY_GET_BORRADORES_BY_USER = """
    SELECT
        o.id_oportunidad, o.op_id_estandar, o.id_interno_simulacion,
        o.cliente_nombre, o.nombre_proyecto, o.titulo_proyecto,
        o.canal_venta, o.cantidad_sitios, o.fecha_creacion,
        tec.nombre as tipo_tecnologia,
        tipo_sol.nombre as tipo_solicitud,
        u.nombre as creado_por_nombre,
        EXTRACT(EPOCH FROM (o.fecha_creacion + INTERVAL '24 hours' - NOW()))::int
            AS segundos_restantes
    FROM tb_oportunidades o
    LEFT JOIN tb_cat_tecnologias tec ON o.id_tecnologia = tec.id
    LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
    LEFT JOIN tb_usuarios u ON o.creado_por_id = u.id_usuario
    WHERE o.email_enviado = false
      AND o.fecha_creacion > NOW() - INTERVAL '24 hours'
      AND o.creado_por_id = $1
    ORDER BY o.fecha_creacion DESC
"""

QUERY_GET_BORRADORES_COUNT = """
    SELECT COUNT(*) FROM tb_oportunidades
    WHERE email_enviado = false
      AND fecha_creacion > NOW() - INTERVAL '24 hours'
"""

QUERY_GET_BORRADORES_COUNT_BY_USER = """
    SELECT COUNT(*) FROM tb_oportunidades
    WHERE email_enviado = false
      AND fecha_creacion > NOW() - INTERVAL '24 hours'
      AND creado_por_id = $1
"""

QUERY_GET_EXPIRED_BORRADORES_IDS = """
    SELECT id_oportunidad FROM tb_oportunidades
    WHERE email_enviado = false
      AND fecha_creacion <= NOW() - INTERVAL '24 hours'
"""

QUERY_CHECK_BORRADOR_VIGENTE = """
    SELECT email_enviado,
           fecha_creacion > NOW() - INTERVAL '24 hours' AS vigente
    FROM tb_oportunidades
    WHERE id_oportunidad = $1
"""

QUERY_REFRESH_BORRADOR_FECHA = """
    UPDATE tb_oportunidades
    SET fecha_creacion = NOW()
    WHERE id_oportunidad = $1
      AND email_enviado = FALSE
      AND fecha_creacion > NOW() - INTERVAL '24 hours'
"""

# Notificación Oportunidad Ganada
QUERY_UPDATE_NOTIFICACION_GANADA_AT = """
    UPDATE tb_oportunidades
    SET notificacion_ganada_at = NOW() AT TIME ZONE 'America/Mexico_City'
    WHERE id_oportunidad = $1
"""

QUERY_GET_PROYECTO_FOR_OPORTUNIDAD = """
    SELECT id_proyecto
    FROM tb_proyectos_gate
    WHERE id_oportunidad = $1
    ORDER BY created_at DESC
    LIMIT 1
"""

QUERY_GET_PROGRESO_GATE = """
    SELECT id_proyecto, area_actual, fecha_inicio_area, status_fase
    FROM tb_proyectos_gate
    WHERE id_oportunidad = $1
    ORDER BY created_at DESC
    LIMIT 1
"""

QUERY_GET_JEFE_BY_ROL_ORG = """
    SELECT id_usuario, nombre
    FROM tb_usuarios
    WHERE rol_organizacional = $1 AND is_active = TRUE
    LIMIT 1
"""

QUERY_GET_EQUIPO_PROYECTO_ACTIVO = """
    SELECT pu.rol_proyecto, pu.area, u.nombre AS nombre_usuario
    FROM tb_proyecto_usuarios pu
    JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
    WHERE pu.id_proyecto = $1 AND pu.activo = true
"""

QUERY_GET_NOTIFICACION_GANADA_AT = """
    SELECT notificacion_ganada_at FROM tb_oportunidades WHERE id_oportunidad = $1
"""
