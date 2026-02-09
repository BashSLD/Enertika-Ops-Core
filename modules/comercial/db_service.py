
# SQL Queries for Commercial Module

QUERY_GET_OPORTUNIDADES_LIST = """
    SELECT
        o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre, o.canal_venta,
        o.fecha_solicitud, estatus.nombre as status_global, o.email_enviado, o.id_interno_simulacion,
        tipo_sol.nombre as tipo_solicitud, o.deadline_calculado, o.deadline_negociado, o.cantidad_sitios,
        o.titulo_proyecto, o.prioridad, o.es_fuera_horario,
        o.es_licitacion, o.fecha_entrega_simulacion,
        o.fecha_ideal_usuario,
        u_creador.nombre as solicitado_por,
        u_sim.nombre as responsable_simulacion,
        u_sim.email as responsable_email,
        CASE WHEN db.id IS NOT NULL THEN true ELSE false END as tiene_detalles_bess,
        lev_estatus.nombre as status_levantamiento,
        lev.fecha_visita_programada as fecha_programada,
        u_tecnico.nombre as tecnico_asignado_nombre
    FROM tb_oportunidades o
    LEFT JOIN tb_cat_estatus_global estatus ON o.id_estatus_global = estatus.id
    LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
    LEFT JOIN tb_usuarios u_creador ON o.creado_por_id = u_creador.id_usuario
    LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
    LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
    LEFT JOIN tb_levantamientos lev ON o.id_oportunidad = lev.id_oportunidad
    LEFT JOIN tb_cat_estatus_global lev_estatus ON lev.id_estatus_global = lev_estatus.id
    LEFT JOIN tb_usuarios u_tecnico ON lev.tecnico_asignado_id = u_tecnico.id_usuario
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
        fecha_ideal_usuario
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $26, $7,
        $8, $9, $22, 
        $10, $11, $12, $13, $14, $15, 
        $16, $17, 
        $18, $19,
        $20, $21,
        $23, $24, $25,
        $27
    )
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
        fecha_ideal_usuario
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, 
        $22,  -- ID Estatus (Ya no es 1 fijo)
        $20, $21, 
        $23,  -- Fecha Solicitud (Ya no es NOW())
        FALSE,
        $24,   -- es_licitacion
        $25    -- fecha_ideal_usuario (heredada o default)
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
QUERY_GET_ESTATUS_GLOBAL = "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true AND modulo_aplicable IN ('SIMULACION', 'COMERCIAL') ORDER BY nombre"
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
    SELECT 
        comentario,
        usuario_nombre,
        modulo_origen,
        fecha_comentario AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City' as fecha_comentario
    FROM tb_comentarios_workflow
    WHERE id_oportunidad = $1
    ORDER BY fecha_comentario DESC
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
QUERY_GET_SITIOS_SIMPLE = "SELECT * FROM tb_sitios_oportunidad WHERE id_oportunidad = $1 ORDER BY id_sitio"

QUERY_INSERT_SITIO_UNICO = """
    INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, nombre_sitio, direccion, google_maps_link, id_tipo_solicitud, id_estatus_global)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
"""

# Updates
QUERY_UPDATE_EMAIL_ENVIADO = "UPDATE tb_oportunidades SET email_enviado = TRUE WHERE id_oportunidad = $1"
QUERY_UPDATE_PRIORIDAD = "UPDATE tb_oportunidades SET prioridad = $1 WHERE id_oportunidad = $2"
QUERY_UPDATE_OPORTUNIDAD_OWNER = "UPDATE tb_oportunidades SET creado_por_id = $1 WHERE id_oportunidad = $2"

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
