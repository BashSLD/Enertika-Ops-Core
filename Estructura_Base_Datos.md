| esquema  | nombre_tabla               | filas_estimadas |
| -------- | -------------------------- | --------------- |
| auth     | audit_log_entries          | -1              |
| auth     | flow_state                 | -1              |
| auth     | identities                 | -1              |
| auth     | instances                  | -1              |
| auth     | mfa_amr_claims             | -1              |
| auth     | mfa_challenges             | -1              |
| auth     | mfa_factors                | -1              |
| auth     | oauth_authorizations       | -1              |
| auth     | oauth_client_states        | -1              |
| auth     | oauth_clients              | -1              |
| auth     | oauth_consents             | -1              |
| auth     | one_time_tokens            | -1              |
| auth     | refresh_tokens             | -1              |
| auth     | saml_providers             | -1              |
| auth     | saml_relay_states          | -1              |
| auth     | schema_migrations          | 72              |
| auth     | sessions                   | -1              |
| auth     | sso_domains                | -1              |
| auth     | sso_providers              | -1              |
| auth     | users                      | -1              |
| public   | tb_bitacora                | -1              |
| public   | tb_catalogo_materiales     | -1              |
| public   | tb_clientes                | 25              |
| public   | tb_compras_tracking        | -1              |
| public   | tb_levantamientos          | -1              |
| public   | tb_oportunidades           | -1              |
| public   | tb_permisos_usuarios       | -1              |
| public   | tb_proyecto_materiales     | -1              |
| public   | tb_proyectos               | -1              |
| public   | tb_seguimiento_workflow    | -1              |
| public   | tb_simulaciones_trabajo    | -1              |
| public   | tb_sitios_oportunidad      | 23              |
| public   | tb_usuarios                | -1              |
| public   | tb_validaciones_fase       | -1              |
| public   | tb_versiones_oferta        | -1              |
| realtime | messages                   | -1              |
| realtime | schema_migrations          | 65              |
| realtime | subscription               | -1              |
| storage  | buckets                    | -1              |
| storage  | buckets_analytics          | -1              |
| storage  | buckets_vectors            | -1              |
| storage  | migrations                 | -1              |
| storage  | objects                    | -1              |
| storage  | prefixes                   | -1              |
| storage  | s3_multipart_uploads       | -1              |
| storage  | s3_multipart_uploads_parts | -1              |
| storage  | vector_indexes             | -1              |
| vault    | secrets                    | -1              |

| tabla                   | columna                    | tipo_dato                | es_nulo | valor_default     |
| ----------------------- | -------------------------- | ------------------------ | ------- | ----------------- |
| tb_bitacora             | id_log                     | uuid                     | NO      | gen_random_uuid() |
| tb_bitacora             | id_entidad_fk              | uuid                     | NO      | null              |
| tb_bitacora             | entidad_tipo               | text                     | NO      | null              |
| tb_bitacora             | comentario                 | text                     | NO      | null              |
| tb_bitacora             | usuario_id                 | uuid                     | NO      | null              |
| tb_bitacora             | timestamp                  | timestamp with time zone | YES     | now()             |
| tb_catalogo_materiales  | id                         | uuid                     | NO      | gen_random_uuid() |
| tb_catalogo_materiales  | codigo_sku                 | text                     | YES     | null              |
| tb_catalogo_materiales  | nombre                     | text                     | NO      | null              |
| tb_catalogo_materiales  | unidad_medida              | text                     | YES     | null              |
| tb_catalogo_materiales  | categoria                  | text                     | YES     | null              |
| tb_catalogo_materiales  | costo_referencia           | numeric                  | YES     | 0                 |
| tb_catalogo_materiales  | created_at                 | timestamp with time zone | YES     | now()             |
| tb_clientes             | id                         | uuid                     | NO      | gen_random_uuid() |
| tb_clientes             | nombre_fiscal              | text                     | NO      | null              |
| tb_clientes             | direccion_fiscal           | text                     | YES     | null              |
| tb_clientes             | contacto_principal         | text                     | YES     | null              |
| tb_clientes             | created_at                 | timestamp with time zone | YES     | now()             |
| tb_compras_tracking     | id_tracking                | uuid                     | NO      | gen_random_uuid() |
| tb_compras_tracking     | id_proyecto                | uuid                     | NO      | null              |
| tb_compras_tracking     | descripcion_proveedor      | text                     | NO      | null              |
| tb_compras_tracking     | descripcion_interna        | text                     | NO      | null              |
| tb_compras_tracking     | categoria_gasto            | text                     | YES     | null              |
| tb_compras_tracking     | monto                      | real                     | NO      | null              |
| tb_compras_tracking     | fecha_factura              | date                     | NO      | null              |
| tb_compras_tracking     | status_pago                | text                     | NO      | null              |
| tb_compras_tracking     | creado_por_id              | uuid                     | NO      | null              |
| tb_levantamientos       | id_levantamiento           | uuid                     | NO      | gen_random_uuid() |
| tb_levantamientos       | id_sitio                   | uuid                     | NO      | null              |
| tb_levantamientos       | solicitado_por_id          | uuid                     | NO      | null              |
| tb_levantamientos       | tecnico_asignado_id        | uuid                     | YES     | null              |
| tb_levantamientos       | fecha_solicitud            | timestamp with time zone | YES     | now()             |
| tb_levantamientos       | status_tarea               | text                     | NO      | null              |
| tb_levantamientos       | evidencia_docs_url         | text                     | YES     | null              |
| tb_levantamientos       | jefe_area_id               | uuid                     | YES     | null              |
| tb_oportunidades        | id_oportunidad             | uuid                     | NO      | gen_random_uuid() |
| tb_oportunidades        | op_id_estandar             | text                     | NO      | null              |
| tb_oportunidades        | cliente_nombre             | text                     | NO      | null              |
| tb_oportunidades        | status_global              | text                     | NO      | null              |
| tb_oportunidades        | fecha_creacion             | timestamp with time zone | YES     | now()             |
| tb_oportunidades        | creado_por_id              | uuid                     | NO      | null              |
| tb_oportunidades        | nombre_proyecto            | text                     | YES     | null              |
| tb_oportunidades        | canal_venta                | text                     | YES     | null              |
| tb_oportunidades        | solicitado_por             | text                     | YES     | null              |
| tb_oportunidades        | tipo_tecnologia            | text                     | YES     | null              |
| tb_oportunidades        | tipo_solicitud             | text                     | YES     | null              |
| tb_oportunidades        | cantidad_sitios            | integer                  | YES     | 1                 |
| tb_oportunidades        | prioridad                  | text                     | YES     | 'Normal'::text    |
| tb_oportunidades        | direccion_obra             | text                     | YES     | null              |
| tb_oportunidades        | coordenadas_gps            | text                     | YES     | null              |
| tb_oportunidades        | google_maps_link           | text                     | YES     | null              |
| tb_oportunidades        | sharepoint_folder_url      | text                     | YES     | null              |
| tb_oportunidades        | deadline_calculado         | timestamp with time zone | YES     | null              |
| tb_oportunidades        | titulo_proyecto            | text                     | YES     | null              |
| tb_oportunidades        | id_interno_simulacion      | text                     | YES     | null              |
| tb_oportunidades        | fecha_solicitud            | timestamp with time zone | YES     | now()             |
| tb_oportunidades        | email_enviado              | boolean                  | YES     | false             |
| tb_oportunidades        | cliente_id                 | uuid                     | YES     | null              |
| tb_oportunidades        | responsable_simulacion_id  | uuid                     | YES     | null              |
| tb_permisos_usuarios    | id_permiso                 | uuid                     | NO      | gen_random_uuid() |
| tb_permisos_usuarios    | usuario_id                 | uuid                     | NO      | null              |
| tb_permisos_usuarios    | departamento_rol           | text                     | NO      | null              |
| tb_proyecto_materiales  | id                         | uuid                     | NO      | gen_random_uuid() |
| tb_proyecto_materiales  | proyecto_id                | uuid                     | YES     | null              |
| tb_proyecto_materiales  | material_id                | uuid                     | YES     | null              |
| tb_proyecto_materiales  | cantidad_estimada_ing      | numeric                  | YES     | null              |
| tb_proyecto_materiales  | cantidad_comprada          | numeric                  | YES     | 0                 |
| tb_proyecto_materiales  | estatus_compra             | text                     | YES     | 'Pendiente'::text |
| tb_proyecto_materiales  | proveedor                  | text                     | YES     | null              |
| tb_proyecto_materiales  | costo_real_unitario        | numeric                  | YES     | null              |
| tb_proyecto_materiales  | created_at                 | timestamp with time zone | YES     | now()             |
| tb_proyectos            | id_proyecto                | uuid                     | NO      | gen_random_uuid() |
| tb_proyectos            | id_oportunidad             | uuid                     | NO      | null              |
| tb_proyectos            | proyecto_id_estandar       | text                     | NO      | null              |
| tb_proyectos            | status_fase                | text                     | NO      | null              |
| tb_proyectos            | aprobacion_direccion       | boolean                  | NO      | false             |
| tb_proyectos            | fecha_aprobacion           | timestamp with time zone | YES     | null              |
| tb_seguimiento_workflow | id                         | uuid                     | NO      | gen_random_uuid() |
| tb_seguimiento_workflow | oportunidad_id             | uuid                     | YES     | null              |
| tb_seguimiento_workflow | departamento_actual        | text                     | YES     | 'VENTAS'::text    |
| tb_seguimiento_workflow | estatus_revision           | text                     | YES     | 'NA'::text        |
| tb_seguimiento_workflow | responsable_direccion      | text                     | YES     | null              |
| tb_seguimiento_workflow | responsable_simulacion     | text                     | YES     | null              |
| tb_seguimiento_workflow | responsable_ingenieria     | text                     | YES     | null              |
| tb_seguimiento_workflow | responsable_construccion   | text                     | YES     | null              |
| tb_seguimiento_workflow | responsable_om             | text                     | YES     | null              |
| tb_seguimiento_workflow | responsable_compras        | text                     | YES     | null              |
| tb_seguimiento_workflow | fecha_entrada_ingenieria   | timestamp with time zone | YES     | null              |
| tb_seguimiento_workflow | fecha_entrada_construccion | timestamp with time zone | YES     | null              |
| tb_seguimiento_workflow | fecha_entrada_oym          | timestamp with time zone | YES     | null              |
| tb_seguimiento_workflow | updated_at                 | timestamp with time zone | YES     | now()             |
| tb_simulaciones_trabajo | id_simulacion              | uuid                     | NO      | gen_random_uuid() |
| tb_simulaciones_trabajo | id_oportunidad             | uuid                     | NO      | null              |
| tb_simulaciones_trabajo | tecnico_asignado_id        | uuid                     | YES     | null              |
| tb_simulaciones_trabajo | tipo_solicitud             | text                     | NO      | null              |
| tb_simulaciones_trabajo | fecha_solicitud            | timestamp with time zone | YES     | now()             |
| tb_simulaciones_trabajo | deadline_estimado          | timestamp with time zone | YES     | null              |
| tb_simulaciones_trabajo | fecha_entrega_real         | timestamp with time zone | YES     | null              |
| tb_simulaciones_trabajo | potencia_simulada_kwp      | real                     | YES     | null              |
| tb_simulaciones_trabajo | status_simulacion          | text                     | NO      | null              |

| table_schema | constraint_name                                  | tabla_origen            | columna_origen            | tabla_destino          | columna_destino |
| ------------ | ------------------------------------------------ | ----------------------- | ------------------------- | ---------------------- | --------------- |
| public       | tb_bitacora_usuario_id_fkey                      | tb_bitacora             | usuario_id                | tb_usuarios            | id_usuario      |
| public       | tb_compras_tracking_creado_por_id_fkey           | tb_compras_tracking     | creado_por_id             | tb_usuarios            | id_usuario      |
| public       | tb_compras_tracking_id_proyecto_fkey             | tb_compras_tracking     | id_proyecto               | tb_proyectos           | id_proyecto     |
| public       | tb_levantamientos_jefe_area_id_fkey              | tb_levantamientos       | jefe_area_id              | tb_usuarios            | id_usuario      |
| public       | tb_levantamientos_id_sitio_fkey                  | tb_levantamientos       | id_sitio                  | tb_sitios_oportunidad  | id_sitio        |
| public       | tb_levantamientos_solicitado_por_id_fkey         | tb_levantamientos       | solicitado_por_id         | tb_usuarios            | id_usuario      |
| public       | tb_levantamientos_tecnico_asignado_id_fkey       | tb_levantamientos       | tecnico_asignado_id       | tb_usuarios            | id_usuario      |
| public       | tb_oportunidades_cliente_id_fkey                 | tb_oportunidades        | cliente_id                | tb_clientes            | id              |
| public       | tb_oportunidades_responsable_simulacion_id_fkey  | tb_oportunidades        | responsable_simulacion_id | tb_usuarios            | id_usuario      |
| public       | tb_oportunidades_creado_por_id_fkey              | tb_oportunidades        | creado_por_id             | tb_usuarios            | id_usuario      |
| public       | tb_permisos_usuarios_usuario_id_fkey             | tb_permisos_usuarios    | usuario_id                | tb_usuarios            | id_usuario      |
| public       | tb_proyecto_materiales_material_id_fkey          | tb_proyecto_materiales  | material_id               | tb_catalogo_materiales | id              |
| public       | tb_proyectos_id_oportunidad_fkey                 | tb_proyectos            | id_oportunidad            | tb_oportunidades       | id_oportunidad  |
| public       | tb_simulaciones_trabajo_id_oportunidad_fkey      | tb_simulaciones_trabajo | id_oportunidad            | tb_oportunidades       | id_oportunidad  |
| public       | tb_simulaciones_trabajo_tecnico_asignado_id_fkey | tb_simulaciones_trabajo | tecnico_asignado_id       | tb_usuarios            | id_usuario      |
| public       | tb_sitios_oportunidad_id_oportunidad_fkey        | tb_sitios_oportunidad   | id_oportunidad            | tb_oportunidades       | id_oportunidad  |

