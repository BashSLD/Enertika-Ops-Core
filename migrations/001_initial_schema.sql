-- ============================================================
-- Migración Inicial: Schema completo de Enertika-Core-Ops
-- Generado: 2026-02-20 23:35:19
-- NOTA: Este archivo es IDEMPOTENTE (se puede ejecutar múltiples veces)
-- ============================================================

-- ============================================================
-- EXTENSIONES
-- ============================================================
-- NOTA: Extensiones internas de Supabase (hypopg, index_advisor, pg_graphql,
-- pg_stat_statements, supabase_vault) deben habilitarse manualmente desde el
-- dashboard de Supabase en: Database → Extensions
-- Solo se instalan aquí las que la aplicación usa directamente.

CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- búsqueda de similitud de texto
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid() y funciones crypto
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- uuid_generate_v4()

-- ============================================================
-- SECUENCIAS
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS tb_beneficiario_proveedor_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_bom_aprobaciones_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_bom_historial_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_categorias_compra_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_documentos_traspaso_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_estatus_global_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_estatus_levantamiento_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_motivos_cambio_deadline_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_motivos_cierre_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_motivos_rechazo_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_motivos_retrabajo_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_origenes_adjuntos_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_tecnologias_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_tipos_entrega_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_tipos_solicitud_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_cat_zonas_compra_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_comprobante_facturas_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_config_emails_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_config_umbrales_kpi_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_email_defaults_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_historial_cambios_deadline_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_traspaso_documentos_id_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE IF NOT EXISTS tb_traspaso_rechazos_id_seq START WITH 1 INCREMENT BY 1;

-- ============================================================
-- TABLAS
-- ============================================================

-- Tabla: tb_cat_categorias_compra
CREATE TABLE IF NOT EXISTS tb_cat_categorias_compra (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_categorias_compra_id_seq'::regclass),
    nombre VARCHAR(50) NOT NULL,
    activo BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    descripcion TEXT,
    PRIMARY KEY (id),
    CONSTRAINT uq_categoria_compra_nombre UNIQUE (nombre)
);


-- Tabla: tb_cat_departamentos
CREATE TABLE IF NOT EXISTS tb_cat_departamentos (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    nombre VARCHAR(100) NOT NULL,
    slug VARCHAR(50) NOT NULL,
    descripcion TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_departamentos_catalogo_nombre_key UNIQUE (nombre),
    CONSTRAINT tb_departamentos_catalogo_slug_key UNIQUE (slug)
);


-- Tabla: tb_cat_documentos_traspaso
CREATE TABLE IF NOT EXISTS tb_cat_documentos_traspaso (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_documentos_traspaso_id_seq'::regclass),
    area_origen VARCHAR(50) NOT NULL,
    area_destino VARCHAR(50) NOT NULL,
    nombre_documento VARCHAR(200) NOT NULL,
    descripcion TEXT,
    es_obligatorio BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    activo BOOLEAN DEFAULT true,
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_documentos_traspaso_area_origen_area_destino_nombre__key UNIQUE (area_origen, area_destino, nombre_documento)
);


-- Tabla: tb_cat_estatus_levantamiento
CREATE TABLE IF NOT EXISTS tb_cat_estatus_levantamiento (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_estatus_levantamiento_id_seq'::regclass),
    nombre VARCHAR(50) NOT NULL,
    codigo VARCHAR(30) NOT NULL,
    descripcion TEXT,
    color_hex VARCHAR(10),
    activo BOOLEAN NOT NULL DEFAULT true,
    orden_kanban INTEGER NOT NULL,
    grupo_kanban VARCHAR(20) NOT NULL,
    es_estatus_final BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_estatus_levantamiento_codigo_key UNIQUE (codigo),
    CONSTRAINT tb_cat_estatus_levantamiento_nombre_key UNIQUE (nombre)
);


-- Tabla: tb_cat_estatus_oportunidades
CREATE TABLE IF NOT EXISTS tb_cat_estatus_oportunidades (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_estatus_global_id_seq'::regclass),
    nombre VARCHAR(50) NOT NULL,
    descripcion TEXT,
    color_hex VARCHAR(10),
    activo BOOLEAN DEFAULT true,
    modulo_aplicable VARCHAR(50) DEFAULT 'COMERCIAL'::character varying,
    cuenta_para_kpi BOOLEAN DEFAULT false,
    es_estatus_final BOOLEAN DEFAULT false,
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_estatus_global_nombre_key UNIQUE (nombre)
);


-- Tabla: tb_cat_modulos
CREATE TABLE IF NOT EXISTS tb_cat_modulos (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    nombre VARCHAR(50) NOT NULL,
    slug VARCHAR(50) NOT NULL,
    ruta VARCHAR(100) NOT NULL,
    icono VARCHAR(50),
    descripcion TEXT,
    is_active BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_modulos_catalogo_nombre_key UNIQUE (nombre),
    CONSTRAINT tb_modulos_catalogo_slug_key UNIQUE (slug)
);


-- Tabla: tb_cat_motivos_cambio_deadline
CREATE TABLE IF NOT EXISTS tb_cat_motivos_cambio_deadline (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_motivos_cambio_deadline_id_seq'::regclass),
    codigo VARCHAR(30) NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    activo BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_motivos_cambio_deadline_codigo_key UNIQUE (codigo)
);


-- Tabla: tb_cat_motivos_cierre
CREATE TABLE IF NOT EXISTS tb_cat_motivos_cierre (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_motivos_cierre_id_seq'::regclass),
    categoria VARCHAR(50) NOT NULL,
    motivo VARCHAR(255) NOT NULL,
    aplicacion VARCHAR(20) NOT NULL,
    activo BOOLEAN DEFAULT true,
    es_no_viable BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_motivos_cierre_aplicacion_check CHECK (((aplicacion)::text = ANY ((ARRAY['CANCELACION'::character varying, 'PERDIDA'::character varying, 'AMBOS'::character varying])::text[])))
);


-- Tabla: tb_cat_motivos_rechazo
CREATE TABLE IF NOT EXISTS tb_cat_motivos_rechazo (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_motivos_rechazo_id_seq'::regclass),
    area VARCHAR(50) NOT NULL,
    motivo VARCHAR(300) NOT NULL,
    activo BOOLEAN DEFAULT true,
    PRIMARY KEY (id)
);


-- Tabla: tb_cat_motivos_retrabajo
CREATE TABLE IF NOT EXISTS tb_cat_motivos_retrabajo (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_motivos_retrabajo_id_seq'::regclass),
    codigo VARCHAR(30) NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    activo BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_motivos_retrabajo_codigo_key UNIQUE (codigo)
);


-- Tabla: tb_cat_origenes_adjuntos
CREATE TABLE IF NOT EXISTS tb_cat_origenes_adjuntos (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_origenes_adjuntos_id_seq'::regclass),
    slug VARCHAR(50) NOT NULL,
    descripcion TEXT,
    activo BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_origenes_adjuntos_slug_key UNIQUE (slug)
);


-- Tabla: tb_cat_tecnologias
CREATE TABLE IF NOT EXISTS tb_cat_tecnologias (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_tecnologias_id_seq'::regclass),
    nombre VARCHAR(50) NOT NULL,
    activo BOOLEAN DEFAULT true,
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_tecnologias_nombre_key UNIQUE (nombre)
);


-- Tabla: tb_cat_tipos_entrega
CREATE TABLE IF NOT EXISTS tb_cat_tipos_entrega (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_tipos_entrega_id_seq'::regclass),
    nombre VARCHAR(50) NOT NULL,
    activo BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_tipos_entrega_nombre_key UNIQUE (nombre)
);


-- Tabla: tb_cat_tipos_solicitud
CREATE TABLE IF NOT EXISTS tb_cat_tipos_solicitud (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_tipos_solicitud_id_seq'::regclass),
    nombre VARCHAR(50) NOT NULL,
    codigo_interno VARCHAR(20),
    activo BOOLEAN DEFAULT true,
    es_seguimiento BOOLEAN DEFAULT false,
    PRIMARY KEY (id),
    CONSTRAINT tb_cat_tipos_solicitud_nombre_key UNIQUE (nombre)
);


-- Tabla: tb_cat_zonas_compra
CREATE TABLE IF NOT EXISTS tb_cat_zonas_compra (
    id INTEGER NOT NULL DEFAULT nextval('tb_cat_zonas_compra_id_seq'::regclass),
    nombre VARCHAR(50) NOT NULL,
    activo BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT uq_zona_compra_nombre UNIQUE (nombre)
);


-- Tabla: tb_cfdi_relacionados
CREATE TABLE IF NOT EXISTS tb_cfdi_relacionados (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    uuid_factura UUID NOT NULL,
    uuid_relacionado UUID NOT NULL,
    tipo_relacion VARCHAR(2) NOT NULL,
    tipo_relacion_desc TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_cfdi_relacion UNIQUE (uuid_factura, uuid_relacionado, tipo_relacion)
);


-- Tabla: tb_clientes
CREATE TABLE IF NOT EXISTS tb_clientes (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    nombre_fiscal TEXT NOT NULL,
    direccion_fiscal TEXT,
    contacto_principal TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    id_interno_simulacion TEXT,
    PRIMARY KEY (id),
    CONSTRAINT tb_clientes_nombre_fiscal_unique UNIQUE (nombre_fiscal)
);


-- Tabla: tb_config_emails
CREATE TABLE IF NOT EXISTS tb_config_emails (
    id INTEGER NOT NULL DEFAULT nextval('tb_config_emails_id_seq'::regclass),
    modulo VARCHAR(50) NOT NULL,
    trigger_field VARCHAR(50) NOT NULL,
    trigger_value VARCHAR(50) NOT NULL,
    email_to_add VARCHAR(150) NOT NULL,
    type VARCHAR(10),
    descripcion TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_config_emails_type_check CHECK (((type)::text = ANY (ARRAY[('TO'::character varying)::text, ('CC'::character varying)::text])))
);


-- Tabla: tb_configuracion_global
CREATE TABLE IF NOT EXISTS tb_configuracion_global (
    clave VARCHAR(50) NOT NULL,
    valor TEXT NOT NULL,
    descripcion TEXT,
    tipo_dato VARCHAR(20) DEFAULT 'string'::character varying,
    PRIMARY KEY (clave)
);


-- Tabla: tb_email_defaults
CREATE TABLE IF NOT EXISTS tb_email_defaults (
    id INTEGER NOT NULL DEFAULT nextval('tb_email_defaults_id_seq'::regclass),
    default_to TEXT DEFAULT ''::text,
    default_cc TEXT DEFAULT ''::text,
    default_cco TEXT DEFAULT ''::text,
    PRIMARY KEY (id)
);


-- Tabla: tb_proveedores
CREATE TABLE IF NOT EXISTS tb_proveedores (
    id_proveedor UUID NOT NULL DEFAULT gen_random_uuid(),
    rfc VARCHAR(13) NOT NULL,
    razon_social TEXT NOT NULL,
    nombre_comercial TEXT,
    activo BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id_proveedor),
    CONSTRAINT uq_proveedor_rfc UNIQUE (rfc)
);


-- Tabla: tb_departamento_modulos
CREATE TABLE IF NOT EXISTS tb_departamento_modulos (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    departamento_slug VARCHAR(50),
    modulo_slug VARCHAR(50),
    rol_default VARCHAR(20) DEFAULT 'viewer'::character varying,
    PRIMARY KEY (id),
    CONSTRAINT tb_departamento_modulos_unique UNIQUE (departamento_slug, modulo_slug)
);


-- Tabla: tb_usuarios
CREATE TABLE IF NOT EXISTS tb_usuarios (
    id_usuario UUID NOT NULL DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    nombre TEXT NOT NULL,
    department TEXT,
    rol_sistema VARCHAR(20) DEFAULT 'USER'::character varying,
    permisos_extra JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT true,
    modulo_preferido VARCHAR(50),
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at BIGINT,
    ultimo_login TIMESTAMP WITH TIME ZONE DEFAULT now(),
    puede_ser_jefe_area BOOLEAN DEFAULT false,
    puede_asignarse_simulacion BOOLEAN DEFAULT false,
    es_jefe_levantamientos_default BOOLEAN DEFAULT false,
    PRIMARY KEY (id_usuario),
    CONSTRAINT tb_usuarios_email_key UNIQUE (email)
);


-- Tabla: tb_beneficiario_proveedor
CREATE TABLE IF NOT EXISTS tb_beneficiario_proveedor (
    id INTEGER NOT NULL DEFAULT nextval('tb_beneficiario_proveedor_id_seq'::regclass),
    beneficiario_nombre TEXT NOT NULL,
    id_proveedor UUID NOT NULL,
    confianza VARCHAR(20) DEFAULT 'MANUAL'::character varying,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    created_by_id UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_beneficiario_proveedor UNIQUE (beneficiario_nombre, id_proveedor)
);


-- Tabla: tb_config_umbrales_kpi
CREATE TABLE IF NOT EXISTS tb_config_umbrales_kpi (
    id INTEGER NOT NULL DEFAULT nextval('tb_config_umbrales_kpi_id_seq'::regclass),
    tipo_kpi VARCHAR(50) NOT NULL,
    departamento VARCHAR(50) DEFAULT 'SIMULACION'::character varying,
    umbral_excelente NUMERIC(5, 2) NOT NULL,
    umbral_bueno NUMERIC(5, 2) NOT NULL,
    color_excelente VARCHAR(50) DEFAULT 'emerald'::character varying,
    color_bueno VARCHAR(50) DEFAULT 'yellow'::character varying,
    color_critico VARCHAR(50) DEFAULT 'red'::character varying,
    activo BOOLEAN DEFAULT true,
    fecha_vigencia TIMESTAMP WITH TIME ZONE DEFAULT now(),
    modificado_por_id UUID,
    fecha_modificacion TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT chk_umbrales_validos CHECK (((umbral_excelente > umbral_bueno) AND (umbral_bueno > (0)::numeric) AND (umbral_excelente <= (100)::numeric)))
);


-- Tabla: tb_correos_notificaciones
CREATE TABLE IF NOT EXISTS tb_correos_notificaciones (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    departamento VARCHAR(50) NOT NULL,
    email_remitente VARCHAR(255) NOT NULL,
    nombre_remitente VARCHAR(255) NOT NULL,
    descripcion TEXT,
    activo BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_by UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_departamento_activo UNIQUE (departamento, activo)
);


-- Tabla: tb_oportunidades
CREATE TABLE IF NOT EXISTS tb_oportunidades (
    id_oportunidad UUID NOT NULL DEFAULT gen_random_uuid(),
    op_id_estandar TEXT NOT NULL,
    cliente_nombre TEXT NOT NULL,
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT now(),
    creado_por_id UUID NOT NULL,
    nombre_proyecto TEXT,
    canal_venta TEXT,
    solicitado_por TEXT,
    cantidad_sitios INTEGER DEFAULT 1,
    prioridad TEXT DEFAULT 'Normal'::text,
    direccion_obra TEXT,
    coordenadas_gps TEXT,
    google_maps_link TEXT,
    sharepoint_folder_url TEXT,
    deadline_calculado TIMESTAMP WITH TIME ZONE,
    titulo_proyecto TEXT,
    id_interno_simulacion TEXT,
    fecha_solicitud TIMESTAMP WITH TIME ZONE DEFAULT now(),
    email_enviado BOOLEAN DEFAULT false,
    cliente_id UUID,
    responsable_simulacion_id UUID,
    parent_id UUID,
    es_fuera_horario BOOLEAN DEFAULT false,
    fecha_entrega_simulacion TIMESTAMP WITH TIME ZONE,
    kpi_status_compromiso VARCHAR(50),
    id_tecnologia INTEGER,
    id_tipo_solicitud INTEGER,
    id_estatus_global INTEGER,
    kpi_status_sla_interno VARCHAR(50),
    deadline_negociado TIMESTAMP WITH TIME ZONE,
    es_carga_manual BOOLEAN DEFAULT false,
    monto_cierre_usd NUMERIC(12, 2),
    potencia_cierre_fv_kwp NUMERIC(10, 2),
    capacidad_cierre_bess_kwh NUMERIC(10, 2),
    id_motivo_cierre INTEGER,
    clasificacion_solicitud VARCHAR(20) DEFAULT 'NORMAL'::character varying,
    solicitado_por_id UUID,
    es_licitacion BOOLEAN DEFAULT false,
    tiempo_elaboracion_horas NUMERIC,
    entregado_por_id UUID,
    es_retrabajo BOOLEAN DEFAULT false,
    id_motivo_retrabajo INTEGER,
    fecha_ideal_usuario DATE,
    PRIMARY KEY (id_oportunidad),
    CONSTRAINT tb_oportunidades_op_id_estandar_key UNIQUE (op_id_estandar),
    CONSTRAINT check_clasificacion_valid CHECK (((clasificacion_solicitud)::text = ANY ((ARRAY['NORMAL'::character varying, 'ESPECIAL'::character varying, 'EXTRAORDINARIO'::character varying])::text[])))
);


-- Tabla: tb_permisos_modulos
CREATE TABLE IF NOT EXISTS tb_permisos_modulos (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL,
    modulo_slug VARCHAR(50) NOT NULL,
    rol_modulo VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_permisos_modulos_unique UNIQUE (usuario_id, modulo_slug),
    CONSTRAINT tb_permisos_modulos_rol_modulo_check CHECK (((rol_modulo)::text = ANY (ARRAY[('viewer'::character varying)::text, ('editor'::character varying)::text, ('assignor'::character varying)::text, ('admin'::character varying)::text])))
);


-- Tabla: tb_comentarios_workflow
CREATE TABLE IF NOT EXISTS tb_comentarios_workflow (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    id_oportunidad UUID NOT NULL,
    usuario_email VARCHAR(100) NOT NULL,
    comentario TEXT NOT NULL,
    departamento_origen VARCHAR(50),
    fecha_comentario TIMESTAMP WITH TIME ZONE DEFAULT now(),
    usuario_id UUID,
    usuario_nombre TEXT,
    modulo_origen VARCHAR(50),
    PRIMARY KEY (id)
);


-- Tabla: tb_detalles_bess
CREATE TABLE IF NOT EXISTS tb_detalles_bess (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    id_oportunidad UUID NOT NULL,
    cargas_criticas_kw NUMERIC(10, 2),
    tiene_motores BOOLEAN DEFAULT false,
    potencia_motor_hp NUMERIC(10, 2),
    tiempo_autonomia VARCHAR(50),
    voltaje_operacion VARCHAR(50),
    cargas_separadas BOOLEAN,
    tiene_planta_emergencia BOOLEAN DEFAULT false,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT now(),
    uso_sistema_json JSONB,
    PRIMARY KEY (id)
);


-- Tabla: tb_historial_cambios_deadline
CREATE TABLE IF NOT EXISTS tb_historial_cambios_deadline (
    id INTEGER NOT NULL DEFAULT nextval('tb_historial_cambios_deadline_id_seq'::regclass),
    id_oportunidad UUID NOT NULL,
    deadline_anterior TIMESTAMP WITH TIME ZONE,
    deadline_nuevo TIMESTAMP WITH TIME ZONE NOT NULL,
    id_motivo_cambio INTEGER NOT NULL,
    comentario TEXT,
    usuario_id UUID NOT NULL,
    usuario_nombre VARCHAR(150),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);


-- Tabla: tb_historial_estatus
CREATE TABLE IF NOT EXISTS tb_historial_estatus (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    id_oportunidad UUID NOT NULL,
    id_estatus_anterior INTEGER,
    id_estatus_nuevo INTEGER NOT NULL,
    fecha_cambio_real TIMESTAMP WITH TIME ZONE NOT NULL,
    fecha_cambio_sla TIMESTAMP WITH TIME ZONE NOT NULL,
    cambiado_por_id UUID,
    notas TEXT,
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT chk_estatus_diferentes CHECK (((id_estatus_anterior IS NULL) OR (id_estatus_anterior <> id_estatus_nuevo)))
);


-- Tabla: tb_notificaciones
CREATE TABLE IF NOT EXISTS tb_notificaciones (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    titulo VARCHAR(255) NOT NULL,
    mensaje TEXT,
    id_oportunidad UUID,
    leida BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT chk_tipo_notificacion CHECK (((tipo)::text = ANY ((ARRAY['ASIGNACION'::character varying, 'CAMBIO_ESTATUS'::character varying, 'NUEVO_COMENTARIO'::character varying])::text[])))
);


-- Tabla: tb_proyectos_gate
CREATE TABLE IF NOT EXISTS tb_proyectos_gate (
    id_proyecto UUID NOT NULL DEFAULT gen_random_uuid(),
    id_oportunidad UUID NOT NULL,
    proyecto_id_estandar TEXT NOT NULL,
    status_fase TEXT NOT NULL,
    aprobacion_direccion BOOLEAN NOT NULL DEFAULT false,
    fecha_aprobacion TIMESTAMP WITH TIME ZONE,
    prefijo VARCHAR(10) DEFAULT 'MX'::character varying,
    consecutivo INTEGER,
    id_tecnologia INTEGER,
    nombre_corto TEXT,
    sharepoint_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    created_by_id UUID,
    area_actual VARCHAR(50) DEFAULT 'INGENIERIA'::character varying,
    fecha_inicio_area TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id_proyecto),
    CONSTRAINT tb_proyectos_id_oportunidad_key UNIQUE (id_oportunidad),
    CONSTRAINT tb_proyectos_proyecto_id_estandar_key UNIQUE (proyecto_id_estandar)
);


-- Tabla: tb_sitios_oportunidad
CREATE TABLE IF NOT EXISTS tb_sitios_oportunidad (
    id_sitio UUID NOT NULL DEFAULT gen_random_uuid(),
    id_oportunidad UUID NOT NULL,
    direccion TEXT NOT NULL,
    tipo_tarifa TEXT,
    fecha_carga TIMESTAMP WITH TIME ZONE DEFAULT now(),
    nombre_sitio TEXT,
    google_maps_link TEXT,
    numero_servicio TEXT,
    comentarios TEXT,
    id_estatus_global INTEGER,
    fecha_cierre TIMESTAMP WITH TIME ZONE,
    id_tipo_solicitud INTEGER,
    potencia_fv_kwp NUMERIC(10, 2) DEFAULT 0,
    capacidad_bess_kwh NUMERIC(10, 2) DEFAULT 0,
    tiempo_elaboracion_horas NUMERIC(10, 2),
    es_retrabajo BOOLEAN DEFAULT false,
    id_motivo_retrabajo INTEGER,
    kpi_status_interno VARCHAR(30),
    kpi_status_compromiso VARCHAR(30),
    PRIMARY KEY (id_sitio)
);


-- Tabla: tb_bom
CREATE TABLE IF NOT EXISTS tb_bom (
    id_bom UUID NOT NULL DEFAULT gen_random_uuid(),
    id_proyecto UUID NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    estatus VARCHAR(30) NOT NULL DEFAULT 'BORRADOR'::character varying,
    elaborado_por UUID NOT NULL,
    responsable_ing UUID,
    coordinador_obra UUID,
    fecha_envio_ing TIMESTAMP WITH TIME ZONE,
    fecha_aprobacion_ing TIMESTAMP WITH TIME ZONE,
    fecha_envio_const TIMESTAMP WITH TIME ZONE,
    fecha_aprobacion_const TIMESTAMP WITH TIME ZONE,
    notas TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    jefe_construccion UUID,
    fecha_aprobacion_jefe_const TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id_bom),
    CONSTRAINT tb_bom_id_proyecto_version_key UNIQUE (id_proyecto, version),
    CONSTRAINT tb_bom_estatus_check CHECK (((estatus)::text = ANY ((ARRAY['BORRADOR'::character varying, 'EN_REVISION_ING'::character varying, 'APROBADO_ING'::character varying, 'EN_REVISION_CONST'::character varying, 'APROBADO'::character varying, 'CANCELADO'::character varying])::text[])))
);


-- Tabla: tb_comprobantes_pago
CREATE TABLE IF NOT EXISTS tb_comprobantes_pago (
    id_comprobante UUID NOT NULL DEFAULT gen_random_uuid(),
    fecha_pago DATE NOT NULL,
    beneficiario_orig TEXT NOT NULL,
    monto NUMERIC(15, 2) NOT NULL,
    moneda VARCHAR(3) DEFAULT 'MXN'::character varying,
    id_proveedor UUID,
    id_zona INTEGER,
    id_proyecto UUID,
    id_categoria INTEGER,
    estatus VARCHAR(20) DEFAULT 'PENDIENTE'::character varying,
    uuid_factura UUID,
    capturado_por_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    es_anticipo BOOLEAN DEFAULT false,
    tipo_factura VARCHAR(30) DEFAULT 'NORMAL'::character varying,
    id_comprobante_anticipo UUID,
    PRIMARY KEY (id_comprobante),
    CONSTRAINT uq_comprobante_duplicado UNIQUE (fecha_pago, beneficiario_orig, monto),
    CONSTRAINT tb_comprobantes_pago_estatus_check CHECK (((estatus)::text = ANY ((ARRAY['PENDIENTE'::character varying, 'FACTURADO'::character varying, 'ANTICIPO'::character varying])::text[]))),
    CONSTRAINT tb_comprobantes_pago_moneda_check CHECK (((moneda)::text = ANY ((ARRAY['MXN'::character varying, 'USD'::character varying])::text[])))
);


-- Tabla: tb_control_presupuestal_proyectos
CREATE TABLE IF NOT EXISTS tb_control_presupuestal_proyectos (
    id_tracking UUID NOT NULL DEFAULT gen_random_uuid(),
    id_proyecto UUID NOT NULL,
    descripcion_proveedor TEXT NOT NULL,
    descripcion_interna TEXT NOT NULL,
    categoria_gasto TEXT,
    monto REAL NOT NULL,
    fecha_factura DATE NOT NULL,
    status_pago TEXT NOT NULL,
    creado_por_id UUID NOT NULL,
    PRIMARY KEY (id_tracking)
);


-- Tabla: tb_levantamientos
CREATE TABLE IF NOT EXISTS tb_levantamientos (
    id_levantamiento UUID NOT NULL DEFAULT gen_random_uuid(),
    id_sitio UUID NOT NULL,
    solicitado_por_id UUID NOT NULL,
    tecnico_asignado_id UUID,
    fecha_solicitud TIMESTAMP WITH TIME ZONE DEFAULT now(),
    jefe_area_id UUID,
    id_estatus_global INTEGER NOT NULL DEFAULT 8,
    fecha_visita_programada TIMESTAMP WITH TIME ZONE,
    id_oportunidad UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_by_id UUID,
    motivo_pospone TEXT,
    fecha_reagenda TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id_levantamiento)
);


-- Tabla: tb_traspasos_proyecto
CREATE TABLE IF NOT EXISTS tb_traspasos_proyecto (
    id_traspaso UUID NOT NULL DEFAULT gen_random_uuid(),
    id_proyecto UUID NOT NULL,
    area_origen VARCHAR(50) NOT NULL,
    area_destino VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ENVIADO'::character varying,
    enviado_por UUID NOT NULL,
    enviado_por_nombre VARCHAR(200),
    fecha_envio TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    recibido_por UUID,
    recibido_por_nombre VARCHAR(200),
    fecha_recepcion TIMESTAMP WITH TIME ZONE,
    rechazado_por UUID,
    rechazado_por_nombre VARCHAR(200),
    fecha_rechazo TIMESTAMP WITH TIME ZONE,
    comentario_envio TEXT,
    comentario_rechazo TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id_traspaso)
);


-- Tabla: tb_bom_aprobaciones
CREATE TABLE IF NOT EXISTS tb_bom_aprobaciones (
    id INTEGER NOT NULL DEFAULT nextval('tb_bom_aprobaciones_id_seq'::regclass),
    id_bom UUID NOT NULL,
    tipo VARCHAR(30) NOT NULL,
    version_bom INTEGER NOT NULL,
    usuario_id UUID NOT NULL,
    comentarios TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_bom_aprobaciones_tipo_check CHECK (((tipo)::text = ANY ((ARRAY['ENVIO_REVISION_ING'::character varying, 'APROBACION_ING'::character varying, 'RECHAZO_ING'::character varying, 'ENVIO_REVISION_CONST'::character varying, 'APROBACION_CONST'::character varying, 'RECHAZO_CONST'::character varying, 'DEVOLUCION_BORRADOR'::character varying, 'CANCELACION'::character varying, 'SOLICITUD_MODIFICACION'::character varying, 'APROBACION_MODIFICACION'::character varying])::text[])))
);


-- Tabla: tb_comprobante_facturas
CREATE TABLE IF NOT EXISTS tb_comprobante_facturas (
    id INTEGER NOT NULL DEFAULT nextval('tb_comprobante_facturas_id_seq'::regclass),
    id_comprobante UUID NOT NULL,
    uuid_factura TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'NORMAL'::text,
    monto NUMERIC(14, 2),
    moneda VARCHAR(3) DEFAULT 'MXN'::character varying,
    fecha DATE,
    id_proveedor UUID,
    rfc_emisor VARCHAR(13),
    nombre_emisor TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_comprobante_facturas_id_comprobante_uuid_factura_key UNIQUE (id_comprobante, uuid_factura),
    CONSTRAINT tb_comprobante_facturas_tipo_check CHECK ((tipo = ANY (ARRAY['NORMAL'::text, 'ANTICIPO'::text, 'CIERRE_ANTICIPO'::text, 'NOTA_CREDITO'::text])))
);


-- Tabla: tb_documentos_attachments
CREATE TABLE IF NOT EXISTS tb_documentos_attachments (
    id_documento UUID NOT NULL,
    nombre_archivo TEXT NOT NULL,
    url_sharepoint TEXT,
    drive_item_id TEXT,
    parent_drive_id TEXT,
    tipo_contenido TEXT,
    tamano_bytes BIGINT,
    origen_slug VARCHAR(50) NOT NULL DEFAULT 'comentario'::character varying,
    id_oportunidad UUID,
    id_comentario UUID,
    subido_por_id UUID,
    fecha_subida TIMESTAMP WITH TIME ZONE DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb,
    activo BOOLEAN DEFAULT true,
    id_levantamiento UUID,
    PRIMARY KEY (id_documento),
    CONSTRAINT tb_documentos_attachments_drive_item_id_key UNIQUE (drive_item_id)
);


-- Tabla: tb_levantamiento_asignaciones
CREATE TABLE IF NOT EXISTS tb_levantamiento_asignaciones (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    id_levantamiento UUID NOT NULL,
    tecnico_id UUID NOT NULL,
    asignado_en TIMESTAMP WITH TIME ZONE DEFAULT now(),
    asignado_por_id UUID,
    PRIMARY KEY (id),
    CONSTRAINT tb_levantamiento_tecnicos_id_levantamiento_tecnico_id_key UNIQUE (id_levantamiento, tecnico_id)
);


-- Tabla: tb_levantamiento_viaticos
CREATE TABLE IF NOT EXISTS tb_levantamiento_viaticos (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    id_levantamiento UUID NOT NULL,
    usuario_id UUID NOT NULL,
    concepto TEXT NOT NULL,
    monto NUMERIC(12, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    created_by_id UUID,
    PRIMARY KEY (id),
    CONSTRAINT tb_levantamiento_viaticos_monto_check CHECK ((monto > (0)::numeric))
);


-- Tabla: tb_levantamiento_viaticos_historico
CREATE TABLE IF NOT EXISTS tb_levantamiento_viaticos_historico (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    id_levantamiento UUID NOT NULL,
    enviado_por_id UUID NOT NULL,
    enviado_por_nombre TEXT NOT NULL,
    fecha_envio TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    to_destinatarios TEXT[],
    cc_destinatarios TEXT[],
    viaticos_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_monto NUMERIC(12, 2) NOT NULL,
    estatus VARCHAR(20) NOT NULL DEFAULT 'enviado'::character varying,
    error_detalle TEXT,
    PRIMARY KEY (id),
    CONSTRAINT tb_levantamiento_viaticos_historico_estatus_check CHECK (((estatus)::text = ANY ((ARRAY['enviado'::character varying, 'error'::character varying, 'devuelto'::character varying])::text[])))
);


-- Tabla: tb_levantamientos_historial
CREATE TABLE IF NOT EXISTS tb_levantamientos_historial (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    id_levantamiento UUID NOT NULL,
    id_estatus_anterior INTEGER,
    id_estatus_nuevo INTEGER NOT NULL,
    fecha_transicion TIMESTAMP WITH TIME ZONE DEFAULT now(),
    modificado_por_id UUID NOT NULL,
    modificado_por_nombre TEXT NOT NULL,
    modificado_por_email TEXT NOT NULL,
    observaciones TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    PRIMARY KEY (id)
);


-- Tabla: tb_materiales_historial
CREATE TABLE IF NOT EXISTS tb_materiales_historial (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    uuid_factura UUID NOT NULL,
    id_comprobante UUID,
    id_proveedor UUID NOT NULL,
    descripcion_proveedor TEXT NOT NULL,
    cantidad NUMERIC(15, 4) NOT NULL,
    precio_unitario NUMERIC(15, 4) NOT NULL,
    importe NUMERIC(15, 2) NOT NULL,
    unidad VARCHAR(50),
    clave_prod_serv VARCHAR(10),
    clave_unidad VARCHAR(10),
    descripcion_interna TEXT,
    id_categoria INTEGER,
    origen VARCHAR(20) DEFAULT 'XML'::character varying,
    fecha_factura DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    created_by_id UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_material_historial UNIQUE (uuid_factura, descripcion_proveedor, cantidad, precio_unitario)
);


-- Tabla: tb_traspaso_documentos
CREATE TABLE IF NOT EXISTS tb_traspaso_documentos (
    id INTEGER NOT NULL DEFAULT nextval('tb_traspaso_documentos_id_seq'::regclass),
    id_traspaso UUID NOT NULL,
    id_documento_catalogo INTEGER NOT NULL,
    verificado BOOLEAN DEFAULT false,
    verificado_por UUID,
    fecha_verificacion TIMESTAMP WITH TIME ZONE,
    notas TEXT,
    PRIMARY KEY (id)
);


-- Tabla: tb_traspaso_rechazos
CREATE TABLE IF NOT EXISTS tb_traspaso_rechazos (
    id INTEGER NOT NULL DEFAULT nextval('tb_traspaso_rechazos_id_seq'::regclass),
    id_traspaso UUID NOT NULL,
    id_motivo INTEGER NOT NULL,
    PRIMARY KEY (id)
);


-- Tabla: tb_bom_items
CREATE TABLE IF NOT EXISTS tb_bom_items (
    id_item UUID NOT NULL DEFAULT gen_random_uuid(),
    id_bom UUID NOT NULL,
    id_categoria INTEGER,
    descripcion TEXT NOT NULL,
    cantidad NUMERIC(14, 4) NOT NULL,
    unidad_medida VARCHAR(50),
    fecha_requerida DATE,
    fecha_llegada_real DATE,
    id_proveedor UUID,
    tipo_entrega VARCHAR(50),
    fecha_estimada_entrega DATE,
    comentarios TEXT,
    entregado BOOLEAN DEFAULT false,
    fecha_entrega_check TIMESTAMP WITH TIME ZONE,
    orden INTEGER DEFAULT 0,
    activo BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    precio_unitario NUMERIC(14, 4),
    origen_precio VARCHAR(20) DEFAULT 'MANUAL'::character varying,
    id_material_ref UUID,
    cantidad_recibida NUMERIC DEFAULT 0,
    PRIMARY KEY (id_item),
    CONSTRAINT tb_bom_items_origen_precio_check CHECK (((origen_precio)::text = ANY ((ARRAY['CATALOGO'::character varying, 'MANUAL'::character varying])::text[])))
);


-- Tabla: tb_bom_historial
CREATE TABLE IF NOT EXISTS tb_bom_historial (
    id INTEGER NOT NULL DEFAULT nextval('tb_bom_historial_id_seq'::regclass),
    id_bom UUID NOT NULL,
    id_item UUID,
    accion VARCHAR(20) NOT NULL,
    campo_modificado VARCHAR(100),
    valor_anterior TEXT,
    valor_nuevo TEXT,
    version_bom INTEGER NOT NULL,
    realizado_por UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT tb_bom_historial_accion_check CHECK (((accion)::text = ANY ((ARRAY['CREADO'::character varying, 'EDITADO'::character varying, 'ELIMINADO'::character varying, 'AGREGADO'::character varying, 'RESTAURADO'::character varying])::text[])))
);

-- ============================================================
-- FOREIGN KEYS
-- ============================================================
ALTER TABLE tb_beneficiario_proveedor ADD CONSTRAINT tb_beneficiario_proveedor_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_beneficiario_proveedor ADD CONSTRAINT tb_beneficiario_proveedor_id_proveedor_fkey FOREIGN KEY (id_proveedor) REFERENCES tb_proveedores(id_proveedor);
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_coordinador_obra_fkey FOREIGN KEY (coordinador_obra) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_elaborado_por_fkey FOREIGN KEY (elaborado_por) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_id_proyecto_fkey FOREIGN KEY (id_proyecto) REFERENCES tb_proyectos_gate(id_proyecto);
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_jefe_construccion_fkey FOREIGN KEY (jefe_construccion) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_bom ADD CONSTRAINT tb_bom_responsable_ing_fkey FOREIGN KEY (responsable_ing) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_bom_aprobaciones ADD CONSTRAINT tb_bom_aprobaciones_id_bom_fkey FOREIGN KEY (id_bom) REFERENCES tb_bom(id_bom) ON DELETE CASCADE;
ALTER TABLE tb_bom_aprobaciones ADD CONSTRAINT tb_bom_aprobaciones_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_bom_historial ADD CONSTRAINT tb_bom_historial_id_bom_fkey FOREIGN KEY (id_bom) REFERENCES tb_bom(id_bom) ON DELETE CASCADE;
ALTER TABLE tb_bom_historial ADD CONSTRAINT tb_bom_historial_id_item_fkey FOREIGN KEY (id_item) REFERENCES tb_bom_items(id_item);
ALTER TABLE tb_bom_historial ADD CONSTRAINT tb_bom_historial_realizado_por_fkey FOREIGN KEY (realizado_por) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_id_bom_fkey FOREIGN KEY (id_bom) REFERENCES tb_bom(id_bom) ON DELETE CASCADE;
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_id_categoria_fkey FOREIGN KEY (id_categoria) REFERENCES tb_cat_categorias_compra(id);
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_id_material_ref_fkey FOREIGN KEY (id_material_ref) REFERENCES tb_materiales_historial(id) ON DELETE SET NULL;
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_id_proveedor_fkey FOREIGN KEY (id_proveedor) REFERENCES tb_proveedores(id_proveedor);
ALTER TABLE tb_comentarios_workflow ADD CONSTRAINT tb_bitacora_simulacion_id_oportunidad_fkey FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE;
ALTER TABLE tb_comprobante_facturas ADD CONSTRAINT tb_comprobante_facturas_id_comprobante_fkey FOREIGN KEY (id_comprobante) REFERENCES tb_comprobantes_pago(id_comprobante);
ALTER TABLE tb_comprobante_facturas ADD CONSTRAINT tb_comprobante_facturas_id_proveedor_fkey FOREIGN KEY (id_proveedor) REFERENCES tb_proveedores(id_proveedor);
ALTER TABLE tb_comprobantes_pago ADD CONSTRAINT tb_comprobantes_pago_capturado_por_id_fkey FOREIGN KEY (capturado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_comprobantes_pago ADD CONSTRAINT tb_comprobantes_pago_id_categoria_fkey FOREIGN KEY (id_categoria) REFERENCES tb_cat_categorias_compra(id);
ALTER TABLE tb_comprobantes_pago ADD CONSTRAINT tb_comprobantes_pago_id_comprobante_anticipo_fkey FOREIGN KEY (id_comprobante_anticipo) REFERENCES tb_comprobantes_pago(id_comprobante);
ALTER TABLE tb_comprobantes_pago ADD CONSTRAINT tb_comprobantes_pago_id_proveedor_fkey FOREIGN KEY (id_proveedor) REFERENCES tb_proveedores(id_proveedor);
ALTER TABLE tb_comprobantes_pago ADD CONSTRAINT tb_comprobantes_pago_id_proyecto_fkey FOREIGN KEY (id_proyecto) REFERENCES tb_proyectos_gate(id_proyecto);
ALTER TABLE tb_comprobantes_pago ADD CONSTRAINT tb_comprobantes_pago_id_zona_fkey FOREIGN KEY (id_zona) REFERENCES tb_cat_zonas_compra(id);
ALTER TABLE tb_config_umbrales_kpi ADD CONSTRAINT tb_config_umbrales_kpi_modificado_por_id_fkey FOREIGN KEY (modificado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_control_presupuestal_proyectos ADD CONSTRAINT tb_compras_tracking_creado_por_id_fkey FOREIGN KEY (creado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_control_presupuestal_proyectos ADD CONSTRAINT fk_control_presupuestal_proyecto FOREIGN KEY (id_proyecto) REFERENCES tb_proyectos_gate(id_proyecto);
ALTER TABLE tb_correos_notificaciones ADD CONSTRAINT tb_correos_notificaciones_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_departamento_modulos ADD CONSTRAINT tb_departamento_modulos_departamento_slug_fkey FOREIGN KEY (departamento_slug) REFERENCES tb_cat_departamentos(slug);
ALTER TABLE tb_departamento_modulos ADD CONSTRAINT tb_departamento_modulos_modulo_slug_fkey FOREIGN KEY (modulo_slug) REFERENCES tb_cat_modulos(slug);
ALTER TABLE tb_detalles_bess ADD CONSTRAINT tb_detalles_bess_id_oportunidad_fkey FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE;
ALTER TABLE tb_documentos_attachments ADD CONSTRAINT tb_documentos_attachments_id_comentario_fkey FOREIGN KEY (id_comentario) REFERENCES tb_comentarios_workflow(id);
ALTER TABLE tb_documentos_attachments ADD CONSTRAINT tb_documentos_attachments_id_levantamiento_fkey FOREIGN KEY (id_levantamiento) REFERENCES tb_levantamientos(id_levantamiento);
ALTER TABLE tb_documentos_attachments ADD CONSTRAINT tb_documentos_attachments_id_oportunidad_fkey FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad);
ALTER TABLE tb_documentos_attachments ADD CONSTRAINT tb_documentos_attachments_origen_slug_fkey FOREIGN KEY (origen_slug) REFERENCES tb_cat_origenes_adjuntos(slug);
ALTER TABLE tb_documentos_attachments ADD CONSTRAINT tb_documentos_attachments_subido_por_id_fkey FOREIGN KEY (subido_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_historial_cambios_deadline ADD CONSTRAINT tb_historial_cambios_deadline_id_motivo_cambio_fkey FOREIGN KEY (id_motivo_cambio) REFERENCES tb_cat_motivos_cambio_deadline(id);
ALTER TABLE tb_historial_cambios_deadline ADD CONSTRAINT tb_historial_cambios_deadline_id_oportunidad_fkey FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE;
ALTER TABLE tb_historial_cambios_deadline ADD CONSTRAINT tb_historial_cambios_deadline_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_historial_estatus ADD CONSTRAINT tb_historial_estatus_cambiado_por_id_fkey FOREIGN KEY (cambiado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_historial_estatus ADD CONSTRAINT tb_historial_estatus_id_estatus_anterior_fkey FOREIGN KEY (id_estatus_anterior) REFERENCES tb_cat_estatus_oportunidades(id);
ALTER TABLE tb_historial_estatus ADD CONSTRAINT tb_historial_estatus_id_estatus_nuevo_fkey FOREIGN KEY (id_estatus_nuevo) REFERENCES tb_cat_estatus_oportunidades(id);
ALTER TABLE tb_historial_estatus ADD CONSTRAINT tb_historial_estatus_id_oportunidad_fkey FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE;
ALTER TABLE tb_levantamiento_asignaciones ADD CONSTRAINT tb_levantamiento_tecnicos_asignado_por_id_fkey FOREIGN KEY (asignado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_levantamiento_asignaciones ADD CONSTRAINT tb_levantamiento_tecnicos_id_levantamiento_fkey FOREIGN KEY (id_levantamiento) REFERENCES tb_levantamientos(id_levantamiento) ON DELETE CASCADE;
ALTER TABLE tb_levantamiento_asignaciones ADD CONSTRAINT tb_levantamiento_tecnicos_tecnico_id_fkey FOREIGN KEY (tecnico_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_levantamiento_viaticos ADD CONSTRAINT tb_levantamiento_viaticos_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
ALTER TABLE tb_levantamiento_viaticos ADD CONSTRAINT tb_levantamiento_viaticos_id_levantamiento_fkey FOREIGN KEY (id_levantamiento) REFERENCES tb_levantamientos(id_levantamiento) ON DELETE CASCADE;
ALTER TABLE tb_levantamiento_viaticos ADD CONSTRAINT tb_levantamiento_viaticos_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
ALTER TABLE tb_levantamiento_viaticos_historico ADD CONSTRAINT tb_levantamiento_viaticos_historico_enviado_por_id_fkey FOREIGN KEY (enviado_por_id) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
ALTER TABLE tb_levantamiento_viaticos_historico ADD CONSTRAINT tb_levantamiento_viaticos_historico_id_levantamiento_fkey FOREIGN KEY (id_levantamiento) REFERENCES tb_levantamientos(id_levantamiento) ON DELETE CASCADE;
ALTER TABLE tb_levantamientos ADD CONSTRAINT fk_lev_estatus_levantamiento FOREIGN KEY (id_estatus_global) REFERENCES tb_cat_estatus_levantamiento(id);
ALTER TABLE tb_levantamientos ADD CONSTRAINT fk_lev_oportunidad FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE;
ALTER TABLE tb_levantamientos ADD CONSTRAINT tb_levantamientos_id_sitio_fkey FOREIGN KEY (id_sitio) REFERENCES tb_sitios_oportunidad(id_sitio);
ALTER TABLE tb_levantamientos ADD CONSTRAINT tb_levantamientos_jefe_area_id_fkey FOREIGN KEY (jefe_area_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_levantamientos ADD CONSTRAINT tb_levantamientos_solicitado_por_id_fkey FOREIGN KEY (solicitado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_levantamientos ADD CONSTRAINT tb_levantamientos_tecnico_asignado_id_fkey FOREIGN KEY (tecnico_asignado_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_levantamientos ADD CONSTRAINT fk_lev_updated_by FOREIGN KEY (updated_by_id) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
ALTER TABLE tb_levantamientos_historial ADD CONSTRAINT fk_lev_hist_estatus_anterior FOREIGN KEY (id_estatus_anterior) REFERENCES tb_cat_estatus_levantamiento(id) ON DELETE SET NULL;
ALTER TABLE tb_levantamientos_historial ADD CONSTRAINT fk_lev_hist_estatus_nuevo FOREIGN KEY (id_estatus_nuevo) REFERENCES tb_cat_estatus_levantamiento(id) ON DELETE RESTRICT;
ALTER TABLE tb_levantamientos_historial ADD CONSTRAINT fk_lev_hist_levantamiento FOREIGN KEY (id_levantamiento) REFERENCES tb_levantamientos(id_levantamiento) ON DELETE CASCADE;
ALTER TABLE tb_levantamientos_historial ADD CONSTRAINT fk_lev_hist_usuario FOREIGN KEY (modificado_por_id) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
ALTER TABLE tb_materiales_historial ADD CONSTRAINT tb_materiales_historial_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_materiales_historial ADD CONSTRAINT tb_materiales_historial_id_categoria_fkey FOREIGN KEY (id_categoria) REFERENCES tb_cat_categorias_compra(id);
ALTER TABLE tb_materiales_historial ADD CONSTRAINT tb_materiales_historial_id_comprobante_fkey FOREIGN KEY (id_comprobante) REFERENCES tb_comprobantes_pago(id_comprobante);
ALTER TABLE tb_materiales_historial ADD CONSTRAINT tb_materiales_historial_id_proveedor_fkey FOREIGN KEY (id_proveedor) REFERENCES tb_proveedores(id_proveedor);
ALTER TABLE tb_notificaciones ADD CONSTRAINT fk_notif_oportunidad FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE;
ALTER TABLE tb_notificaciones ADD CONSTRAINT fk_notif_usuario FOREIGN KEY (usuario_id) REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE;
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_cliente_id_fkey FOREIGN KEY (cliente_id) REFERENCES tb_clientes(id);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_creado_por_id_fkey FOREIGN KEY (creado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_entregado_por_id_fkey FOREIGN KEY (entregado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_id_estatus_global_fkey FOREIGN KEY (id_estatus_global) REFERENCES tb_cat_estatus_oportunidades(id);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_id_motivo_cierre_fkey FOREIGN KEY (id_motivo_cierre) REFERENCES tb_cat_motivos_cierre(id);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_id_motivo_retrabajo_fkey FOREIGN KEY (id_motivo_retrabajo) REFERENCES tb_cat_motivos_retrabajo(id);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_id_tecnologia_fkey FOREIGN KEY (id_tecnologia) REFERENCES tb_cat_tecnologias(id);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_id_tipo_solicitud_fkey FOREIGN KEY (id_tipo_solicitud) REFERENCES tb_cat_tipos_solicitud(id);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_responsable_simulacion_id_fkey FOREIGN KEY (responsable_simulacion_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_oportunidades ADD CONSTRAINT tb_oportunidades_solicitado_por_id_fkey FOREIGN KEY (solicitado_por_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_permisos_modulos ADD CONSTRAINT fk_modulo_slug FOREIGN KEY (modulo_slug) REFERENCES tb_cat_modulos(slug);
ALTER TABLE tb_permisos_modulos ADD CONSTRAINT tb_permisos_modulos_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE;
ALTER TABLE tb_proyectos_gate ADD CONSTRAINT tb_proyectos_gate_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_proyectos_gate ADD CONSTRAINT tb_proyectos_id_oportunidad_fkey FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad);
ALTER TABLE tb_proyectos_gate ADD CONSTRAINT tb_proyectos_gate_id_tecnologia_fkey FOREIGN KEY (id_tecnologia) REFERENCES tb_cat_tecnologias(id);
ALTER TABLE tb_sitios_oportunidad ADD CONSTRAINT tb_sitios_oportunidad_id_estatus_global_fkey FOREIGN KEY (id_estatus_global) REFERENCES tb_cat_estatus_oportunidades(id);
ALTER TABLE tb_sitios_oportunidad ADD CONSTRAINT tb_sitios_oportunidad_id_motivo_retrabajo_fkey FOREIGN KEY (id_motivo_retrabajo) REFERENCES tb_cat_motivos_retrabajo(id);
ALTER TABLE tb_sitios_oportunidad ADD CONSTRAINT tb_sitios_oportunidad_id_oportunidad_fkey FOREIGN KEY (id_oportunidad) REFERENCES tb_oportunidades(id_oportunidad);
ALTER TABLE tb_sitios_oportunidad ADD CONSTRAINT tb_sitios_oportunidad_id_tipo_solicitud_fkey FOREIGN KEY (id_tipo_solicitud) REFERENCES tb_cat_tipos_solicitud(id);
ALTER TABLE tb_traspaso_documentos ADD CONSTRAINT tb_traspaso_documentos_id_documento_catalogo_fkey FOREIGN KEY (id_documento_catalogo) REFERENCES tb_cat_documentos_traspaso(id);
ALTER TABLE tb_traspaso_documentos ADD CONSTRAINT tb_traspaso_documentos_id_traspaso_fkey FOREIGN KEY (id_traspaso) REFERENCES tb_traspasos_proyecto(id_traspaso) ON DELETE CASCADE;
ALTER TABLE tb_traspaso_documentos ADD CONSTRAINT tb_traspaso_documentos_verificado_por_fkey FOREIGN KEY (verificado_por) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_traspaso_rechazos ADD CONSTRAINT tb_traspaso_rechazos_id_motivo_fkey FOREIGN KEY (id_motivo) REFERENCES tb_cat_motivos_rechazo(id);
ALTER TABLE tb_traspaso_rechazos ADD CONSTRAINT tb_traspaso_rechazos_id_traspaso_fkey FOREIGN KEY (id_traspaso) REFERENCES tb_traspasos_proyecto(id_traspaso) ON DELETE CASCADE;
ALTER TABLE tb_traspasos_proyecto ADD CONSTRAINT tb_traspasos_proyecto_enviado_por_fkey FOREIGN KEY (enviado_por) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_traspasos_proyecto ADD CONSTRAINT tb_traspasos_proyecto_id_proyecto_fkey FOREIGN KEY (id_proyecto) REFERENCES tb_proyectos_gate(id_proyecto);
ALTER TABLE tb_traspasos_proyecto ADD CONSTRAINT tb_traspasos_proyecto_rechazado_por_fkey FOREIGN KEY (rechazado_por) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_traspasos_proyecto ADD CONSTRAINT tb_traspasos_proyecto_recibido_por_fkey FOREIGN KEY (recibido_por) REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_usuarios ADD CONSTRAINT fk_modulo_preferido FOREIGN KEY (modulo_preferido) REFERENCES tb_cat_modulos(slug);

-- ============================================================
-- ÍNDICES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_benef_prov_nombre ON public.tb_beneficiario_proveedor USING btree (beneficiario_nombre);
CREATE INDEX IF NOT EXISTS idx_benef_prov_proveedor ON public.tb_beneficiario_proveedor USING btree (id_proveedor);
CREATE UNIQUE INDEX IF NOT EXISTS uq_beneficiario_proveedor ON public.tb_beneficiario_proveedor USING btree (beneficiario_nombre, id_proveedor);
CREATE INDEX IF NOT EXISTS idx_bom_estatus ON public.tb_bom USING btree (estatus);
CREATE INDEX IF NOT EXISTS idx_bom_proyecto ON public.tb_bom USING btree (id_proyecto);
CREATE UNIQUE INDEX IF NOT EXISTS tb_bom_id_proyecto_version_key ON public.tb_bom USING btree (id_proyecto, version);
CREATE INDEX IF NOT EXISTS idx_bom_aprobaciones_bom ON public.tb_bom_aprobaciones USING btree (id_bom);
CREATE INDEX IF NOT EXISTS idx_bom_historial_bom ON public.tb_bom_historial USING btree (id_bom);
CREATE INDEX IF NOT EXISTS idx_bom_items_activo ON public.tb_bom_items USING btree (id_bom, activo);
CREATE INDEX IF NOT EXISTS idx_bom_items_bom ON public.tb_bom_items USING btree (id_bom);
CREATE UNIQUE INDEX IF NOT EXISTS uq_categoria_compra_nombre ON public.tb_cat_categorias_compra USING btree (nombre);
CREATE UNIQUE INDEX IF NOT EXISTS tb_departamentos_catalogo_nombre_key ON public.tb_cat_departamentos USING btree (nombre);
CREATE UNIQUE INDEX IF NOT EXISTS tb_departamentos_catalogo_slug_key ON public.tb_cat_departamentos USING btree (slug);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_documentos_traspaso_area_origen_area_destino_nombre__key ON public.tb_cat_documentos_traspaso USING btree (area_origen, area_destino, nombre_documento);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_estatus_levantamiento_codigo_key ON public.tb_cat_estatus_levantamiento USING btree (codigo);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_estatus_levantamiento_nombre_key ON public.tb_cat_estatus_levantamiento USING btree (nombre);
CREATE INDEX IF NOT EXISTS idx_estatus_modulo ON public.tb_cat_estatus_oportunidades USING btree (modulo_aplicable);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_estatus_global_nombre_key ON public.tb_cat_estatus_oportunidades USING btree (nombre);
CREATE UNIQUE INDEX IF NOT EXISTS tb_modulos_catalogo_nombre_key ON public.tb_cat_modulos USING btree (nombre);
CREATE UNIQUE INDEX IF NOT EXISTS tb_modulos_catalogo_slug_key ON public.tb_cat_modulos USING btree (slug);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_motivos_cambio_deadline_codigo_key ON public.tb_cat_motivos_cambio_deadline USING btree (codigo);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_motivos_retrabajo_codigo_key ON public.tb_cat_motivos_retrabajo USING btree (codigo);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_origenes_adjuntos_slug_key ON public.tb_cat_origenes_adjuntos USING btree (slug);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_tecnologias_nombre_key ON public.tb_cat_tecnologias USING btree (nombre);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_tipos_entrega_nombre_key ON public.tb_cat_tipos_entrega USING btree (nombre);
CREATE UNIQUE INDEX IF NOT EXISTS tb_cat_tipos_solicitud_nombre_key ON public.tb_cat_tipos_solicitud USING btree (nombre);
CREATE UNIQUE INDEX IF NOT EXISTS uq_zona_compra_nombre ON public.tb_cat_zonas_compra USING btree (nombre);
CREATE INDEX IF NOT EXISTS idx_cfdi_rel_factura ON public.tb_cfdi_relacionados USING btree (uuid_factura);
CREATE INDEX IF NOT EXISTS idx_cfdi_rel_relacionado ON public.tb_cfdi_relacionados USING btree (uuid_relacionado);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cfdi_relacion ON public.tb_cfdi_relacionados USING btree (uuid_factura, uuid_relacionado, tipo_relacion);
CREATE INDEX IF NOT EXISTS idx_clientes_nombre_fiscal_trgm ON public.tb_clientes USING gin (nombre_fiscal gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS tb_clientes_nombre_fiscal_unique ON public.tb_clientes USING btree (nombre_fiscal);
CREATE INDEX IF NOT EXISTS idx_comentarios_oportunidad ON public.tb_comentarios_workflow USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_comprobante_facturas_comprobante ON public.tb_comprobante_facturas USING btree (id_comprobante);
CREATE INDEX IF NOT EXISTS idx_comprobante_facturas_uuid ON public.tb_comprobante_facturas USING btree (uuid_factura);
CREATE UNIQUE INDEX IF NOT EXISTS tb_comprobante_facturas_id_comprobante_uuid_factura_key ON public.tb_comprobante_facturas USING btree (id_comprobante, uuid_factura);
CREATE INDEX IF NOT EXISTS idx_comprobantes_anticipo_ref ON public.tb_comprobantes_pago USING btree (id_comprobante_anticipo) WHERE (id_comprobante_anticipo IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_comprobantes_capturado_por ON public.tb_comprobantes_pago USING btree (capturado_por_id);
CREATE INDEX IF NOT EXISTS idx_comprobantes_estatus ON public.tb_comprobantes_pago USING btree (estatus);
CREATE INDEX IF NOT EXISTS idx_comprobantes_fecha ON public.tb_comprobantes_pago USING btree (fecha_pago);
CREATE INDEX IF NOT EXISTS idx_comprobantes_proveedor ON public.tb_comprobantes_pago USING btree (id_proveedor);
CREATE INDEX IF NOT EXISTS idx_comprobantes_proyecto ON public.tb_comprobantes_pago USING btree (id_proyecto);
CREATE INDEX IF NOT EXISTS idx_comprobantes_tipo_factura ON public.tb_comprobantes_pago USING btree (tipo_factura);
CREATE INDEX IF NOT EXISTS idx_comprobantes_vista_default ON public.tb_comprobantes_pago USING btree (estatus, fecha_pago DESC) WHERE ((estatus)::text = 'PENDIENTE'::text);
CREATE UNIQUE INDEX IF NOT EXISTS uq_comprobante_duplicado ON public.tb_comprobantes_pago USING btree (fecha_pago, beneficiario_orig, monto);
CREATE INDEX IF NOT EXISTS idx_config_umbrales_dept_activo ON public.tb_config_umbrales_kpi USING btree (tipo_kpi, departamento, activo);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kpi_dept_only_active ON public.tb_config_umbrales_kpi USING btree (tipo_kpi, departamento) WHERE (activo = true);
CREATE INDEX IF NOT EXISTS idx_compras_proyecto ON public.tb_control_presupuestal_proyectos USING btree (id_proyecto);
CREATE INDEX IF NOT EXISTS idx_correos_notif_activo ON public.tb_correos_notificaciones USING btree (activo) WHERE (activo = true);
CREATE INDEX IF NOT EXISTS idx_correos_notif_departamento ON public.tb_correos_notificaciones USING btree (departamento);
CREATE UNIQUE INDEX IF NOT EXISTS uq_departamento_activo ON public.tb_correos_notificaciones USING btree (departamento, activo);
CREATE UNIQUE INDEX IF NOT EXISTS tb_departamento_modulos_unique ON public.tb_departamento_modulos USING btree (departamento_slug, modulo_slug);
CREATE INDEX IF NOT EXISTS idx_bess_oportunidad ON public.tb_detalles_bess USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_attach_comentario ON public.tb_documentos_attachments USING btree (id_comentario);
CREATE INDEX IF NOT EXISTS idx_attach_drive_item ON public.tb_documentos_attachments USING btree (drive_item_id);
CREATE INDEX IF NOT EXISTS idx_attach_levantamiento ON public.tb_documentos_attachments USING btree (id_levantamiento);
CREATE INDEX IF NOT EXISTS idx_attach_oportunidad ON public.tb_documentos_attachments USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_attach_origen ON public.tb_documentos_attachments USING btree (origen_slug);
CREATE UNIQUE INDEX IF NOT EXISTS tb_documentos_attachments_drive_item_id_key ON public.tb_documentos_attachments USING btree (drive_item_id);
CREATE INDEX IF NOT EXISTS idx_historial_deadline_fecha ON public.tb_historial_cambios_deadline USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_historial_deadline_oportunidad ON public.tb_historial_cambios_deadline USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_historial_deadline_usuario ON public.tb_historial_cambios_deadline USING btree (usuario_id);
CREATE INDEX IF NOT EXISTS idx_historial_estatus_cambio ON public.tb_historial_estatus USING btree (id_estatus_anterior, id_estatus_nuevo);
CREATE INDEX IF NOT EXISTS idx_historial_estatus_nuevo ON public.tb_historial_estatus USING btree (id_estatus_nuevo);
CREATE INDEX IF NOT EXISTS idx_historial_fecha_cambio ON public.tb_historial_estatus USING btree (fecha_cambio_sla);
CREATE INDEX IF NOT EXISTS idx_historial_oportunidad ON public.tb_historial_estatus USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_lev_tecnicos_levantamiento ON public.tb_levantamiento_asignaciones USING btree (id_levantamiento);
CREATE INDEX IF NOT EXISTS idx_lev_tecnicos_tecnico ON public.tb_levantamiento_asignaciones USING btree (tecnico_id);
CREATE UNIQUE INDEX IF NOT EXISTS tb_levantamiento_tecnicos_id_levantamiento_tecnico_id_key ON public.tb_levantamiento_asignaciones USING btree (id_levantamiento, tecnico_id);
CREATE INDEX IF NOT EXISTS idx_lev_viaticos_levantamiento ON public.tb_levantamiento_viaticos USING btree (id_levantamiento);
CREATE UNIQUE INDEX IF NOT EXISTS pk_lev_viaticos ON public.tb_levantamiento_viaticos USING btree (id);
CREATE INDEX IF NOT EXISTS idx_lev_viaticos_hist_fecha ON public.tb_levantamiento_viaticos_historico USING btree (fecha_envio);
CREATE INDEX IF NOT EXISTS idx_lev_viaticos_hist_levantamiento ON public.tb_levantamiento_viaticos_historico USING btree (id_levantamiento);
CREATE UNIQUE INDEX IF NOT EXISTS pk_lev_viaticos_hist ON public.tb_levantamiento_viaticos_historico USING btree (id);
CREATE INDEX IF NOT EXISTS idx_lev_created ON public.tb_levantamientos USING btree (created_at);
CREATE INDEX IF NOT EXISTS idx_lev_estatus ON public.tb_levantamientos USING btree (id_estatus_global);
CREATE INDEX IF NOT EXISTS idx_lev_jefe ON public.tb_levantamientos USING btree (jefe_area_id);
CREATE INDEX IF NOT EXISTS idx_lev_oportunidad ON public.tb_levantamientos USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_lev_tecnico ON public.tb_levantamientos USING btree (tecnico_asignado_id);
CREATE INDEX IF NOT EXISTS idx_levantamiento_sitio ON public.tb_levantamientos USING btree (id_sitio);
CREATE INDEX IF NOT EXISTS idx_lev_hist_fecha ON public.tb_levantamientos_historial USING btree (fecha_transicion DESC);
CREATE INDEX IF NOT EXISTS idx_lev_hist_levantamiento ON public.tb_levantamientos_historial USING btree (id_levantamiento);
CREATE INDEX IF NOT EXISTS idx_lev_hist_usuario ON public.tb_levantamientos_historial USING btree (modificado_por_id);
CREATE INDEX IF NOT EXISTS idx_materiales_descripcion_trgm ON public.tb_materiales_historial USING gin (descripcion_proveedor gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_materiales_historial_categoria ON public.tb_materiales_historial USING btree (id_categoria);
CREATE INDEX IF NOT EXISTS idx_materiales_historial_fecha ON public.tb_materiales_historial USING btree (fecha_factura);
CREATE INDEX IF NOT EXISTS idx_materiales_historial_origen ON public.tb_materiales_historial USING btree (origen);
CREATE INDEX IF NOT EXISTS idx_materiales_historial_proveedor ON public.tb_materiales_historial USING btree (id_proveedor);
CREATE INDEX IF NOT EXISTS idx_materiales_historial_uuid ON public.tb_materiales_historial USING btree (uuid_factura);
CREATE UNIQUE INDEX IF NOT EXISTS uq_material_historial ON public.tb_materiales_historial USING btree (uuid_factura, descripcion_proveedor, cantidad, precio_unitario);
CREATE INDEX IF NOT EXISTS idx_notif_created ON public.tb_notificaciones USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_oportunidad ON public.tb_notificaciones USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_notif_usuario ON public.tb_notificaciones USING btree (usuario_id);
CREATE INDEX IF NOT EXISTS idx_notif_usuario_leida ON public.tb_notificaciones USING btree (usuario_id, leida) WHERE (leida = false);
CREATE INDEX IF NOT EXISTS idx_oportunidades_creado_por ON public.tb_oportunidades USING btree (creado_por_id);
CREATE INDEX IF NOT EXISTS idx_oportunidades_entregado_por ON public.tb_oportunidades USING btree (entregado_por_id);
CREATE INDEX IF NOT EXISTS idx_oportunidades_fecha_solicitud ON public.tb_oportunidades USING btree (fecha_solicitud DESC);
CREATE INDEX IF NOT EXISTS idx_oportunidades_id_estatus ON public.tb_oportunidades USING btree (id_estatus_global);
CREATE INDEX IF NOT EXISTS idx_oportunidades_id_tecnologia ON public.tb_oportunidades USING btree (id_tecnologia);
CREATE INDEX IF NOT EXISTS idx_oportunidades_id_tipo ON public.tb_oportunidades USING btree (id_tipo_solicitud);
CREATE INDEX IF NOT EXISTS idx_oportunidades_responsable_sim ON public.tb_oportunidades USING btree (responsable_simulacion_id);
CREATE INDEX IF NOT EXISTS idx_ops_comercial_perf ON public.tb_oportunidades USING btree (creado_por_id, fecha_solicitud DESC);
CREATE INDEX IF NOT EXISTS idx_ops_estatus_global ON public.tb_oportunidades USING btree (id_estatus_global) WHERE (email_enviado = true);
CREATE INDEX IF NOT EXISTS idx_ops_global_perf ON public.tb_oportunidades USING btree (email_enviado, fecha_solicitud DESC);
CREATE UNIQUE INDEX IF NOT EXISTS tb_oportunidades_op_id_estandar_key ON public.tb_oportunidades USING btree (op_id_estandar);
CREATE INDEX IF NOT EXISTS idx_permisos_modulos_modulo ON public.tb_permisos_modulos USING btree (modulo_slug);
CREATE INDEX IF NOT EXISTS idx_permisos_modulos_usuario ON public.tb_permisos_modulos USING btree (usuario_id);
CREATE UNIQUE INDEX IF NOT EXISTS tb_permisos_modulos_unique ON public.tb_permisos_modulos USING btree (usuario_id, modulo_slug);
CREATE INDEX IF NOT EXISTS idx_proveedores_nombre_comercial ON public.tb_proveedores USING btree (nombre_comercial);
CREATE INDEX IF NOT EXISTS idx_proveedores_razon ON public.tb_proveedores USING btree (razon_social);
CREATE UNIQUE INDEX IF NOT EXISTS uq_proveedor_rfc ON public.tb_proveedores USING btree (rfc);
CREATE INDEX IF NOT EXISTS idx_proyectos_area_actual ON public.tb_proyectos_gate USING btree (area_actual);
CREATE UNIQUE INDEX IF NOT EXISTS idx_proyectos_gate_consecutivo ON public.tb_proyectos_gate USING btree (consecutivo) WHERE (consecutivo IS NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS tb_proyectos_id_oportunidad_key ON public.tb_proyectos_gate USING btree (id_oportunidad);
CREATE UNIQUE INDEX IF NOT EXISTS tb_proyectos_proyecto_id_estandar_key ON public.tb_proyectos_gate USING btree (proyecto_id_estandar);
CREATE INDEX IF NOT EXISTS idx_sitios_op ON public.tb_sitios_oportunidad USING btree (id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_sitios_retrabajo ON public.tb_sitios_oportunidad USING btree (es_retrabajo) WHERE (es_retrabajo = true);
CREATE INDEX IF NOT EXISTS idx_traspasos_area_destino ON public.tb_traspasos_proyecto USING btree (area_destino, status);
CREATE INDEX IF NOT EXISTS idx_traspasos_proyecto ON public.tb_traspasos_proyecto USING btree (id_proyecto);
CREATE INDEX IF NOT EXISTS idx_traspasos_status ON public.tb_traspasos_proyecto USING btree (status);
CREATE INDEX IF NOT EXISTS idx_usuarios_jefe_area ON public.tb_usuarios USING btree (puede_ser_jefe_area) WHERE (puede_ser_jefe_area = true);
CREATE UNIQUE INDEX IF NOT EXISTS tb_usuarios_email_key ON public.tb_usuarios USING btree (email);
CREATE UNIQUE INDEX IF NOT EXISTS uq_usuario_jefe_lev_default ON public.tb_usuarios USING btree (es_jefe_levantamientos_default) WHERE (es_jefe_levantamientos_default = true);

-- ============================================================
-- VISTAS
-- ============================================================
CREATE OR REPLACE VIEW vw_cambios_deadline_resumen AS
 SELECT h.id_oportunidad,
    o.op_id_estandar,
    o.nombre_proyecto,
    count(*) AS total_cambios,
    min(h.created_at) AS primer_cambio,
    max(h.created_at) AS ultimo_cambio,
    EXTRACT(day FROM (max(h.deadline_nuevo) - min(COALESCE(h.deadline_anterior, o.deadline_calculado)))) AS dias_extendidos
   FROM (tb_historial_cambios_deadline h
     JOIN tb_oportunidades o ON ((h.id_oportunidad = o.id_oportunidad)))
  GROUP BY h.id_oportunidad, o.op_id_estandar, o.nombre_proyecto;;

CREATE OR REPLACE VIEW vw_metricas_sitios AS
 SELECT s.id_sitio,
    s.id_oportunidad,
    s.nombre_sitio,
    s.id_estatus_global AS estatus_sitio,
    es.nombre AS estatus_sitio_nombre,
    s.fecha_cierre AS fecha_entrega_sitio,
    s.es_retrabajo,
    s.kpi_status_interno,
    s.kpi_status_compromiso,
    mr.nombre AS motivo_retrabajo_nombre,
    o.op_id_estandar,
    o.nombre_proyecto,
    o.cliente_nombre,
    o.fecha_solicitud,
    o.deadline_calculado,
    o.deadline_negociado,
    COALESCE(o.deadline_negociado, o.deadline_calculado) AS deadline_efectivo,
    o.responsable_simulacion_id,
    u.nombre AS responsable_nombre,
    t.nombre AS tecnologia_nombre,
    ts.nombre AS tipo_solicitud_nombre
   FROM ((((((tb_sitios_oportunidad s
     JOIN tb_oportunidades o ON ((s.id_oportunidad = o.id_oportunidad)))
     LEFT JOIN tb_cat_estatus_oportunidades es ON ((s.id_estatus_global = es.id)))
     LEFT JOIN tb_cat_motivos_retrabajo mr ON ((s.id_motivo_retrabajo = mr.id)))
     LEFT JOIN tb_usuarios u ON ((o.responsable_simulacion_id = u.id_usuario)))
     LEFT JOIN tb_cat_tecnologias t ON ((o.id_tecnologia = t.id)))
     LEFT JOIN tb_cat_tipos_solicitud ts ON ((o.id_tipo_solicitud = ts.id)));;

-- ============================================================
-- DATOS DE CATÁLOGOS (esenciales para que la app funcione)
-- ============================================================

-- Datos: tb_cat_categorias_compra
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (1, 'Cableado AC', TRUE, 1, 'Todo THHW, XHHW, Cu Desnudo, etc. Cal. 8 AWG-500 KCMIL Cu-Al') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (2, 'Cableado DC', TRUE, 2, 'Cable XLPE, RHHW, FV, etc. Cal. 12-8 AWG, MC4') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (3, 'Canalizacion AC', TRUE, 3, 'Charola tipo escalera, tapas y accesorios de montaje') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (4, 'Canalizacion DC', TRUE, 4, 'Charola tipo malla GC, tapas y accesorios de montaje') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (5, 'Protecciones AC', TRUE, 5, 'Interruptores con zapatas ABB, Siemens, Square D, WEG, Biticino, Tableros AC') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (6, 'Protecciones DC', TRUE, 6, 'Portafusibles, fusibles, PDS, MCB, Disyuntores riel din') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (7, 'Interconexion AC', TRUE, 7, 'Barras de cobre max 2000A, zapatas ponchables') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (8, 'Miscelaneos', TRUE, 8, 'Tornilleria, ferrules, cinchos, etc') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (9, 'Accesorios electricos', TRUE, 9, 'Tuberia PG, PD, PEAD, PVC, condulets, gabinetes, conectores, registros, etc.') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (10, 'Comunicacion', TRUE, 10, 'Cable belden, ITM riel din, transformador 5kva') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (11, 'Panel', TRUE, 11, 'JA Solar, Trina Solar, Canadian Solar, Longi, etc.') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (12, 'Inversores', TRUE, 12, 'Huawei, Growatt, Solis, SMA, microinversores y sus accesorios') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (13, 'Estructura FV', TRUE, 13, 'K2 Systems, Novotegra, Aluminext, Ralux, S-5!, Supports, Sun Support, etc.') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_categorias_compra (id, nombre, activo, orden, descripcion) VALUES (14, 'Transformador', TRUE, 14, 'Pedestal, seco, subestacion, poste, accesorios para MT, etc.') ON CONFLICT DO NOTHING;

-- Datos: tb_cat_departamentos
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('2069890b-128d-4a0e-b235-ce5f3ff4e218', 'Comercial', 'comercial', 'Departamento de ventas y atención comercial', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('5a7cab1b-6476-4df0-a3ee-91dbb635ae23', 'Simulación', 'simulacion', 'Departamento de simulaciones técnicas', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('5e403cc5-01ee-4cf4-a458-b7622b440d71', 'Sistemas', 'sistemas', 'Departamento de sistemas y TI', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('a79f3015-8c9e-48bb-b00c-a17ff06671f8', 'Ingeniería', 'ingenieria', 'Departamento de ingeniería y diseño', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('b5b93796-fc76-4b7a-a83e-0d09c2f10bac', 'Dirección', 'direccion', 'Dirección general', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('d3473fad-ea7d-48ed-b2b6-cab134934b56', 'O & M', 'oym', 'Departamento de operación y mantenimiento', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('d7bad48a-10fc-4f46-9881-87350c58743e', 'Compras', 'compras', 'Departamento de compras y adquisiciones', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_departamentos (id, nombre, slug, descripcion, is_active, created_at) VALUES ('ee1d4261-5e6d-40ce-9ed0-7d26c0184cdf', 'Construcción', 'construccion', 'Departamento de construcción y obras', TRUE, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;

-- Datos: tb_cat_documentos_traspaso
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (1, 'INGENIERIA', 'CONSTRUCCION', 'Planos ejecutivos', 'Planos de ingenieria aprobados y firmados', TRUE, 1, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (2, 'INGENIERIA', 'CONSTRUCCION', 'Memoria de calculo', 'Memoria de calculo estructural y electrica', TRUE, 2, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (3, 'INGENIERIA', 'CONSTRUCCION', 'Diagrama unifilar', 'Diagrama unifilar del sistema', TRUE, 3, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (4, 'INGENIERIA', 'CONSTRUCCION', 'Lista de materiales (BOM)', 'Bill of materials completo', TRUE, 4, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (5, 'INGENIERIA', 'CONSTRUCCION', 'Estudio de interconexion', 'Estudio de interconexion aprobado por CFE', FALSE, 5, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (6, 'INGENIERIA', 'CONSTRUCCION', 'Permisos y licencias', 'Permisos municipales y licencias aplicables', FALSE, 6, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (7, 'INGENIERIA', 'CONSTRUCCION', 'Cronograma de obra', 'Programa de obra detallado', TRUE, 7, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (8, 'CONSTRUCCION', 'OYM', 'Dossier de obra', 'Dossier completo de la obra ejecutada', TRUE, 1, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (9, 'CONSTRUCCION', 'OYM', 'Planos as-built', 'Planos actualizados segun construccion real', TRUE, 2, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (10, 'CONSTRUCCION', 'OYM', 'Acta de puesta en marcha', 'Acta de comisionamiento y puesta en servicio', TRUE, 3, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (11, 'CONSTRUCCION', 'OYM', 'Manuales de operacion', 'Manuales de equipos y sistemas', TRUE, 4, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (12, 'CONSTRUCCION', 'OYM', 'Garantias de equipos', 'Certificados de garantia de equipos principales', TRUE, 5, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (13, 'CONSTRUCCION', 'OYM', 'Protocolo de pruebas', 'Resultados de pruebas de aceptacion (FAT/SAT)', FALSE, 6, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_documentos_traspaso (id, area_origen, area_destino, nombre_documento, descripcion, es_obligatorio, orden, activo) VALUES (14, 'CONSTRUCCION', 'OYM', 'Capacitacion entregada', 'Evidencia de capacitacion al equipo de OyM', FALSE, 7, TRUE) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_estatus_levantamiento
INSERT INTO tb_cat_estatus_levantamiento (id, nombre, codigo, descripcion, color_hex, activo, orden_kanban, grupo_kanban, es_estatus_final) VALUES (1, 'Pendiente', 'pendiente', 'Levantamiento solicitado, pendiente de agendar.', '#F97316', TRUE, 1, 'activo', FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_levantamiento (id, nombre, codigo, descripcion, color_hex, activo, orden_kanban, grupo_kanban, es_estatus_final) VALUES (2, 'Agendado', 'agendado', 'Visita con fecha y técnico asignados.', '#3B82F6', TRUE, 2, 'activo', FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_levantamiento (id, nombre, codigo, descripcion, color_hex, activo, orden_kanban, grupo_kanban, es_estatus_final) VALUES (3, 'En Proceso', 'en_proceso', 'El técnico está ejecutando el levantamiento en sitio.', '#EAB308', TRUE, 3, 'activo', FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_levantamiento (id, nombre, codigo, descripcion, color_hex, activo, orden_kanban, grupo_kanban, es_estatus_final) VALUES (4, 'Pospuesto', 'pospuesto', 'El levantamiento fue pospuesto por algún motivo.', '#6B7280', TRUE, 4, 'activo', FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_levantamiento (id, nombre, codigo, descripcion, color_hex, activo, orden_kanban, grupo_kanban, es_estatus_final) VALUES (5, 'Completado', 'completado', 'Completado, pendiente de entrega formal.', '#22C55E', TRUE, 5, 'terminado', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_levantamiento (id, nombre, codigo, descripcion, color_hex, activo, orden_kanban, grupo_kanban, es_estatus_final) VALUES (6, 'Entregado', 'entregado', 'Informe de levantamiento entregado al cliente.', '#10B981', TRUE, 6, 'terminado', TRUE) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_estatus_oportunidades
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (1, 'Pendiente', 'Cuando se envia una oportunidad, simulacion aun no hay revisado ni el correo de la oportunidad.', '#F59E0B', TRUE, 'SIMULACION', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (2, 'En Proceso', 'Cuando simulaicon esta manos a la obra, se esta trabajando la oportunidad.', '#3B82F6', TRUE, 'SIMULACION', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (3, 'En Revisión', 'Cuando Direccion ya lo tiene y esta revisando los detalles', '#8B5CF6', TRUE, 'SIMULACION', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (4, 'Entregado', 'Cuando se envia a comercial la simulacion', '#10B981', TRUE, 'SIMULACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (5, 'Cancelado', 'Oportunidades que se registraron pero por algún motivo ya no se tuvo que trabajar', '#6B7280', TRUE, 'SIMULACION', FALSE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (6, 'Perdido', 'Oportunidades trabajadas pero el cliente ya no las acepta es importante para el calculo de kpis', '#EF4444', TRUE, 'SIMULACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (7, 'Ganada', 'Proyecto cerrado exitosamente', '#22C55E', TRUE, 'SIMULACION', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (8, 'Lev_Pendiente', 'Levantamiento recibido, sin asignar técnico', '#FF9800', TRUE, 'LEVANTAMIENTOS', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (9, 'Lev_Agendado', 'Visita programada con fecha y técnico asignado', '#2196F3', TRUE, 'LEVANTAMIENTOS', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (10, 'Lev_En_Proceso', 'Técnico realizando levantamiento en sitio', '#FFC107', TRUE, 'LEVANTAMIENTOS', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (11, 'Lev_Completado', 'Levantamiento realizado, pendiente de entrega', '#4CAF50', TRUE, 'LEVANTAMIENTOS', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (12, 'Lev_Entregado', 'Reporte de levantamiento entregado y finalizado', '#1B5E20', TRUE, 'LEVANTAMIENTOS', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_estatus_oportunidades (id, nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final) VALUES (13, 'Lev_Pospuesto', 'Levantamiento pospuesto o cancelado', '#9E9E9E', TRUE, 'LEVANTAMIENTOS', FALSE, FALSE) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_modulos
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('01204395-3727-4070-9c73-04f6a49e09a4', 'Compras', 'compras', '/compras/ui', 'bi-cart', 'Compras y adquisiciones', TRUE, 60, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('036b8fcb-a2e0-48ad-bd8c-e03c5335ad4c', 'Comercial', 'comercial', '/comercial/ui', 'bi-briefcase', 'Gestión de oportunidades comerciales', TRUE, 10, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('105207a4-5441-481b-81ab-170b4eea550d', 'Admin', 'admin', '/admin/ui', 'bi-gear', 'Administración del sistema', TRUE, 100, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('2d550d73-1222-4121-97a1-61ac9164f020', 'Construcción', 'construccion', '/construccion/ui', 'bi-hammer', 'Seguimiento de construcción', TRUE, 50, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('388875bc-7c2d-49f1-baf7-78a839628818', 'Simulación', 'simulacion', '/simulacion/ui', 'bi-calculator', 'Simulaciones técnicas', TRUE, 20, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('4118a099-e451-4974-9d56-2ff8db8e6561', 'O & M', 'oym', '/oym/ui', 'bi-tools', 'Operación y mantenimiento', TRUE, 70, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('70d18224-115a-47b4-a0c5-099ea48a9a70', 'Ingeniería', 'ingenieria', '/ingenieria/ui', 'bi-cpu', 'Area para el dimensionamiento de los proyectos', TRUE, 45, '2026-01-29 09:01:18.400969') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('e16dd32c-492d-4e10-b598-5f32797f05d2', 'Proyectos', 'proyectos', '/proyectos/ui', 'bi-kanban', 'Gestión de proyectos', TRUE, 40, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_modulos (id, nombre, slug, ruta, icono, descripcion, is_active, orden, created_at) VALUES ('f143e3c7-cbeb-4b7d-98b1-503fc86ed76b', 'Levantamientos', 'levantamientos', '/levantamientos/ui', 'bi-geo', 'Levantamientos de campo', TRUE, 30, '2025-12-24 21:45:56.204917') ON CONFLICT DO NOTHING;

-- Datos: tb_cat_motivos_cambio_deadline
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (1, 'SOLICITUD_CLIENTE', 'Solicitud del cliente', 'El cliente solicitó cambio de fecha', TRUE, 1, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (2, 'COMPLEJIDAD_TECNICA', 'Complejidad técnica', 'La complejidad técnica es mayor a la esperada', TRUE, 2, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (3, 'FALTA_INFO', 'Falta de información', 'Se requiere información adicional del cliente', TRUE, 3, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (4, 'CARGA_TRABAJO', 'Carga de trabajo', 'Alta carga de trabajo del equipo', TRUE, 4, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (5, 'ERROR_CALCULO_SLA', 'Error en cálculo inicial', 'El SLA inicial fue calculado incorrectamente', TRUE, 5, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (6, 'PRIORIDAD_OTRO', 'Priorización de otro proyecto', 'Se priorizó otro proyecto urgente', TRUE, 6, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (7, 'DEPENDENCIA_EXTERNA', 'Dependencia externa', 'Depende de información/aprobación externa', TRUE, 7, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cambio_deadline (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (8, 'OTRO', 'Otro motivo', 'Otro motivo no listado', TRUE, 99, '2026-01-20 15:37:23.394336+00:00') ON CONFLICT DO NOTHING;

-- Datos: tb_cat_motivos_cierre
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (1, 'Técnico', 'Estructura no apta / Techo en mal estado', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (2, 'Técnico', 'Sombreado crítico / Excesivo', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (3, 'Técnico', 'Espacio insuficiente para FV o BESS', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (4, 'Técnico', 'Infraestructura eléctrica incompatible (Tableros/Transformador)', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (5, 'Técnico', 'Interconexión no viable con CFE', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (6, 'Regulatorio', 'Recibo CFE incompatible / Tarifa no elegible', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (7, 'Regulatorio', 'Problemas legales del predio / Arrendamiento', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (8, 'Regulatorio', 'Rechazo por Compliance / HSE', 'CANCELACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (9, 'Económico', 'Cliente sin presupuesto / No hay CAPEX', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (10, 'Económico', 'Retorno financiero (ROI/Payback) no atractivo', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (11, 'Económico', 'Precio fuera de expectativa', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (12, 'Económico', 'Prioridades internas cambiaron / Congelamiento', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (13, 'Competencia', 'Cliente eligió otro proveedor (Mejor Precio)', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (14, 'Competencia', 'Cliente eligió otro proveedor (Mejor Solución)', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (15, 'Otros', 'Decisión Corporativa / Fuerza Mayor', 'AMBOS', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (17, 'Otros', 'No cumplir con tiempos de entrega / Areas Internas', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (18, 'Otros', 'No cumplir con tiempos de entrega / Proveedor', 'PERDIDA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (19, 'Económico', 'Proyecto inviable técnicamente/economicamente', 'PERDIDA', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_cierre (id, categoria, motivo, aplicacion, activo, es_no_viable) VALUES (21, 'Otros', 'Carga incorrecta en sistema', 'CANCELACION', TRUE, FALSE) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_motivos_rechazo
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (1, 'CONSTRUCCION', 'Planos incompletos o con errores', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (2, 'CONSTRUCCION', 'Falta memoria de calculo', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (3, 'CONSTRUCCION', 'BOM incompleto o con discrepancias', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (4, 'CONSTRUCCION', 'Permisos pendientes de tramitar', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (5, 'CONSTRUCCION', 'Estudio de interconexion no aprobado', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (6, 'CONSTRUCCION', 'Falta informacion del sitio', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (7, 'CONSTRUCCION', 'Cronograma no viable', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (8, 'OYM', 'Dossier de obra incompleto', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (9, 'OYM', 'Planos as-built no actualizados', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (10, 'OYM', 'Pendiente acta de puesta en marcha', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (11, 'OYM', 'Manuales de operacion faltantes', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (12, 'OYM', 'Garantias no entregadas', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (13, 'OYM', 'Capacitacion no realizada', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_rechazo (id, area, motivo, activo) VALUES (14, 'OYM', 'Pendientes de obra no resueltos', TRUE) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_motivos_retrabajo
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (1, 'ERROR_CALCULO', 'Error de cálculo', 'Error en los cálculos de la simulación', TRUE, 1, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (2, 'ERROR_DATOS', 'Datos mal interpretados', 'Se interpretaron incorrectamente los datos del cliente', TRUE, 2, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (3, 'CAMBIO_CRITERIO', 'Cambio de criterio técnico', 'Se cambió el criterio técnico después de la entrega', TRUE, 3, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (4, 'OMISION_REQ', 'Omisión de requerimiento', 'Se omitió un requerimiento del cliente', TRUE, 4, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (5, 'FALLA_HERRAMIENTA', 'Falla en herramienta', 'Error en software o herramienta de simulación', TRUE, 5, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (6, 'INFO_INCOMPLETA', 'Información incompleta', 'El cliente proporcionó información incompleta inicialmente', TRUE, 6, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (7, 'CAMBIO_ALCANCE', 'Cambio de alcance por cliente', 'El cliente modificó el alcance después de iniciar', TRUE, 7, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_motivos_retrabajo (id, codigo, nombre, descripcion, activo, orden, created_at) VALUES (8, 'OTRO', 'Otro motivo', 'Otro motivo no listado', TRUE, 99, '2026-01-20 15:37:05.871220+00:00') ON CONFLICT DO NOTHING;

-- Datos: tb_cat_origenes_adjuntos
INSERT INTO tb_cat_origenes_adjuntos (id, slug, descripcion, activo, created_at) VALUES (1, 'comentario', 'Adjunto subido en comentarios de workflow', TRUE, '2026-01-14 19:42:04.624627+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_origenes_adjuntos (id, slug, descripcion, activo, created_at) VALUES (2, 'email', 'Adjunto procesado desde email entrante', TRUE, '2026-01-14 19:42:04.624627+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_origenes_adjuntos (id, slug, descripcion, activo, created_at) VALUES (3, 'levantamiento', 'Evidencia de levantamiento en sitio', TRUE, '2026-01-14 19:42:04.624627+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_origenes_adjuntos (id, slug, descripcion, activo, created_at) VALUES (4, 'sistema', 'Archivo generado por el sistema (ej. reportes)', TRUE, '2026-01-14 19:42:04.624627+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_origenes_adjuntos (id, slug, descripcion, activo, created_at) VALUES (5, 'comprobante_pago', 'Archivos asociados a comprobantes de pago (PDF y XML)', TRUE, '2026-02-10 15:19:40.797444+00:00') ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_origenes_adjuntos (id, slug, descripcion, activo, created_at) VALUES (6, 'factura_xml', 'Facturas XML CFDI procesadas en modulo Compras', TRUE, '2026-02-10 15:19:40.797444+00:00') ON CONFLICT DO NOTHING;

-- Datos: tb_cat_tecnologias
INSERT INTO tb_cat_tecnologias (id, nombre, activo) VALUES (1, 'FV', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tecnologias (id, nombre, activo) VALUES (2, 'BESS', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tecnologias (id, nombre, activo) VALUES (3, 'FV + BESS', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tecnologias (id, nombre, activo) VALUES (4, 'FV AISLADO', TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tecnologias (id, nombre, activo) VALUES (5, 'BOMBEO SOLAR', TRUE) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_tipos_entrega
INSERT INTO tb_cat_tipos_entrega (id, nombre, activo, orden) VALUES (1, 'RECOLECCION', TRUE, 1) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_entrega (id, nombre, activo, orden) VALUES (2, 'ENTREGA_SITIO', TRUE, 2) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_entrega (id, nombre, activo, orden) VALUES (3, 'ENTREGA_SEDE', TRUE, 3) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_entrega (id, nombre, activo, orden) VALUES (4, 'OTRO', TRUE, 4) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_tipos_solicitud
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (1, 'Pre Oferta', 'PRE_OFERTA', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (2, 'Licitación', 'LICITACION', FALSE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (3, 'Levantamiento', 'LEVANTAMIENTO', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (4, 'Actualización', 'ACTUALIZACION', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (5, 'Oferta Final', 'OFERTA_FINAL', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (6, 'Cierre de Venta', 'CIERRE_VENTA', TRUE, TRUE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (7, 'Simulación', 'SIMULACION', TRUE, FALSE) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_tipos_solicitud (id, nombre, codigo_interno, activo, es_seguimiento) VALUES (8, 'Recibos', 'RECIBOS', TRUE, FALSE) ON CONFLICT DO NOTHING;

-- Datos: tb_cat_zonas_compra
INSERT INTO tb_cat_zonas_compra (id, nombre, activo, orden) VALUES (1, 'QUERETARO', TRUE, 1) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_zonas_compra (id, nombre, activo, orden) VALUES (2, 'MERIDA', TRUE, 2) ON CONFLICT DO NOTHING;
INSERT INTO tb_cat_zonas_compra (id, nombre, activo, orden) VALUES (3, 'VERACRUZ', TRUE, 3) ON CONFLICT DO NOTHING;

-- ============================================================
-- FIN DE MIGRACIÓN INICIAL
-- ============================================================