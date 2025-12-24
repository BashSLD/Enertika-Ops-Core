# 📸 Radiografía de Base de Datos (Snapshot)

**Generado el:** 83280.703

## 📦 Tabla: `tb_bitacora`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_log** | `uuid` | NO | `gen_random_uuid()` |
| **id_entidad_fk** | `uuid` | NO | `-` |
| **entidad_tipo** | `text` | NO | `-` |
| **comentario** | `text` | NO | `-` |
| **usuario_id** | `uuid` | NO | `-` |
| **timestamp** | `timestamp with time zone` | YES | `now()` |

## 📦 Tabla: `tb_catalogo_materiales`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `uuid` | NO | `gen_random_uuid()` |
| **codigo_sku** | `text` | YES | `-` |
| **nombre** | `text` | NO | `-` |
| **unidad_medida** | `text` | YES | `-` |
| **categoria** | `text` | YES | `-` |
| **costo_referencia** | `numeric` | YES | `0` |
| **created_at** | `timestamp with time zone` | YES | `now()` |

## 📦 Tabla: `tb_clientes`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `uuid` | NO | `gen_random_uuid()` |
| **nombre_fiscal** | `text` | NO | `-` |
| **direccion_fiscal** | `text` | YES | `-` |
| **contacto_principal** | `text` | YES | `-` |
| **created_at** | `timestamp with time zone` | YES | `now()` |

## 📦 Tabla: `tb_compras_tracking`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_tracking** | `uuid` | NO | `gen_random_uuid()` |
| **id_proyecto** | `uuid` | NO | `-` |
| **descripcion_proveedor** | `text` | NO | `-` |
| **descripcion_interna** | `text` | NO | `-` |
| **categoria_gasto** | `text` | YES | `-` |
| **monto** | `real` | NO | `-` |
| **fecha_factura** | `date` | NO | `-` |
| **status_pago** | `text` | NO | `-` |
| **creado_por_id** | `uuid` | NO | `-` |

## 📦 Tabla: `tb_config_emails`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `integer` | NO | `nextval('tb_config_emails_id_seq'::regclass)` |
| **modulo** | `character varying` | NO | `-` |
| **trigger_field** | `character varying` | NO | `-` |
| **trigger_value** | `character varying` | NO | `-` |
| **email_to_add** | `character varying` | NO | `-` |
| **type** | `character varying` | YES | `-` |
| **descripcion** | `text` | YES | `-` |
| **created_at** | `timestamp without time zone` | YES | `now()` |

## 📦 Tabla: `tb_email_defaults`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `integer` | NO | `nextval('tb_email_defaults_id_seq'::regclass)` |
| **default_to** | `text` | YES | `''::text` |
| **default_cc** | `text` | YES | `''::text` |
| **default_cco** | `text` | YES | `''::text` |

## 📦 Tabla: `tb_levantamientos`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_levantamiento** | `uuid` | NO | `gen_random_uuid()` |
| **id_sitio** | `uuid` | NO | `-` |
| **solicitado_por_id** | `uuid` | NO | `-` |
| **tecnico_asignado_id** | `uuid` | YES | `-` |
| **fecha_solicitud** | `timestamp with time zone` | YES | `now()` |
| **status_tarea** | `text` | NO | `-` |
| **evidencia_docs_url** | `text` | YES | `-` |
| **jefe_area_id** | `uuid` | YES | `-` |

## 📦 Tabla: `tb_oportunidades`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_oportunidad** | `uuid` | NO | `gen_random_uuid()` |
| **op_id_estandar** | `text` | NO | `-` |
| **cliente_nombre** | `text` | NO | `-` |
| **status_global** | `text` | NO | `-` |
| **fecha_creacion** | `timestamp with time zone` | YES | `now()` |
| **creado_por_id** | `uuid` | NO | `-` |
| **nombre_proyecto** | `text` | YES | `-` |
| **canal_venta** | `text` | YES | `-` |
| **solicitado_por** | `text` | YES | `-` |
| **tipo_tecnologia** | `text` | YES | `-` |
| **tipo_solicitud** | `text` | YES | `-` |
| **cantidad_sitios** | `integer` | YES | `1` |
| **prioridad** | `text` | YES | `'Normal'::text` |
| **direccion_obra** | `text` | YES | `-` |
| **coordenadas_gps** | `text` | YES | `-` |
| **google_maps_link** | `text` | YES | `-` |
| **sharepoint_folder_url** | `text` | YES | `-` |
| **deadline_calculado** | `timestamp with time zone` | YES | `-` |
| **titulo_proyecto** | `text` | YES | `-` |
| **id_interno_simulacion** | `text` | YES | `-` |
| **fecha_solicitud** | `timestamp with time zone` | YES | `now()` |
| **email_enviado** | `boolean` | YES | `false` |
| **cliente_id** | `uuid` | YES | `-` |
| **responsable_simulacion_id** | `uuid` | YES | `-` |

## 📦 Tabla: `tb_permisos_usuarios`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_permiso** | `uuid` | NO | `gen_random_uuid()` |
| **usuario_id** | `uuid` | NO | `-` |
| **departamento_rol** | `text` | NO | `-` |

## 📦 Tabla: `tb_proyecto_materiales`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `uuid` | NO | `gen_random_uuid()` |
| **proyecto_id** | `uuid` | YES | `-` |
| **material_id** | `uuid` | YES | `-` |
| **cantidad_estimada_ing** | `numeric` | YES | `-` |
| **cantidad_comprada** | `numeric` | YES | `0` |
| **estatus_compra** | `text` | YES | `'Pendiente'::text` |
| **proveedor** | `text` | YES | `-` |
| **costo_real_unitario** | `numeric` | YES | `-` |
| **created_at** | `timestamp with time zone` | YES | `now()` |

## 📦 Tabla: `tb_proyectos`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_proyecto** | `uuid` | NO | `gen_random_uuid()` |
| **id_oportunidad** | `uuid` | NO | `-` |
| **proyecto_id_estandar** | `text` | NO | `-` |
| **status_fase** | `text` | NO | `-` |
| **aprobacion_direccion** | `boolean` | NO | `false` |
| **fecha_aprobacion** | `timestamp with time zone` | YES | `-` |

## 📦 Tabla: `tb_seguimiento_workflow`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `uuid` | NO | `gen_random_uuid()` |
| **oportunidad_id** | `uuid` | YES | `-` |
| **departamento_actual** | `text` | YES | `'VENTAS'::text` |
| **estatus_revision** | `text` | YES | `'NA'::text` |
| **responsable_direccion** | `text` | YES | `-` |
| **responsable_simulacion** | `text` | YES | `-` |
| **responsable_ingenieria** | `text` | YES | `-` |
| **responsable_construccion** | `text` | YES | `-` |
| **responsable_om** | `text` | YES | `-` |
| **responsable_compras** | `text` | YES | `-` |
| **fecha_entrada_ingenieria** | `timestamp with time zone` | YES | `-` |
| **fecha_entrada_construccion** | `timestamp with time zone` | YES | `-` |
| **fecha_entrada_oym** | `timestamp with time zone` | YES | `-` |
| **updated_at** | `timestamp with time zone` | YES | `now()` |

## 📦 Tabla: `tb_simulaciones_trabajo`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_simulacion** | `uuid` | NO | `gen_random_uuid()` |
| **id_oportunidad** | `uuid` | NO | `-` |
| **tecnico_asignado_id** | `uuid` | YES | `-` |
| **tipo_solicitud** | `text` | NO | `-` |
| **fecha_solicitud** | `timestamp with time zone` | YES | `now()` |
| **deadline_estimado** | `timestamp with time zone` | YES | `-` |
| **fecha_entrega_real** | `timestamp with time zone` | YES | `-` |
| **potencia_simulada_kwp** | `real` | YES | `-` |
| **status_simulacion** | `text` | NO | `-` |

## 📦 Tabla: `tb_sitios_oportunidad`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_sitio** | `uuid` | NO | `gen_random_uuid()` |
| **id_oportunidad** | `uuid` | NO | `-` |
| **direccion** | `text` | NO | `-` |
| **tipo_tarifa** | `text` | YES | `-` |
| **fecha_carga** | `timestamp with time zone` | YES | `now()` |
| **nombre_sitio** | `text` | YES | `-` |
| **google_maps_link** | `text` | YES | `-` |
| **numero_servicio** | `text` | YES | `-` |
| **comentarios** | `text` | YES | `-` |

## 📦 Tabla: `tb_usuarios`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id_usuario** | `uuid` | NO | `gen_random_uuid()` |
| **email** | `text` | NO | `-` |
| **nombre** | `text` | NO | `-` |
| **department** | `text` | YES | `-` |
| **rol_sistema** | `character varying` | YES | `'USER'::character varying` |
| **permisos_extra** | `jsonb` | YES | `'{}'::jsonb` |
| **is_active** | `boolean` | YES | `true` |

## 📦 Tabla: `tb_validaciones_fase`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `uuid` | NO | `gen_random_uuid()` |
| **proyecto_id** | `uuid` | YES | `-` |
| **fase_origen** | `text` | YES | `-` |
| **fase_destino** | `text` | YES | `-` |
| **link_evidencia_entrega** | `text` | YES | `-` |
| **estado_validacion** | `text` | YES | `'PENDIENTE'::text` |
| **comentarios_rechazo** | `text` | YES | `-` |
| **responsable_validacion** | `text` | YES | `-` |
| **fecha_decision** | `timestamp with time zone` | YES | `-` |

## 📦 Tabla: `tb_versiones_oferta`

| Columna | Tipo | Null | Default |
| :--- | :--- | :--- | :--- |
| **id** | `uuid` | NO | `gen_random_uuid()` |
| **oportunidad_id** | `uuid` | YES | `-` |
| **numero_version** | `integer` | YES | `1` |
| **monto_cotizado** | `numeric` | YES | `-` |
| **link_propuesta** | `text` | YES | `-` |
| **created_at** | `timestamp with time zone` | YES | `now()` |

