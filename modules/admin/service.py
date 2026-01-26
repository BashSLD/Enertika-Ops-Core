# modules/admin/service.py
"""
Service Layer para el módulo Admin.
"""
from typing import List, Dict, Optional
from uuid import UUID
import json
import logging

from .schemas import ConfiguracionGlobalUpdate, EmailRuleCreate

logger = logging.getLogger("AdminModule")


class AdminService:
    """Maneja toda la lógica de negocio del módulo Admin."""
    
    async def get_users_enriched(self, conn) -> List[Dict]:
        """
        Obtiene usuarios con sus módulos asignados y módulo preferido.
        
        OPTIMIZACIÓN: Resuelve N+1 query problem mediante:
        - 1 query para todos los usuarios
        - 1 query para todos los permisos (con JOIN a módulos)
        - 1 query para nombres de módulos preferidos
        - Agrupación en memoria O(n)
        
        Returns:
            List[Dict]: Lista de usuarios enriquecidos con permisos
        """
        # 1. Obtener todos los usuarios
        users = await conn.fetch("SELECT * FROM tb_usuarios ORDER BY nombre")
        if not users:
            return []
        
        # 2. Obtener todos los permisos de una sola vez con JOIN
        all_permissions = await conn.fetch("""
            SELECT pm.usuario_id, pm.modulo_slug, pm.rol_modulo, mc.nombre as modulo_nombre
            FROM tb_permisos_modulos pm
            JOIN tb_modulos_catalogo mc ON pm.modulo_slug = mc.slug
            ORDER BY mc.orden
        """)
        
        # 3. Obtener nombres de módulos preferidos de una sola vez
        modulos_preferidos_slugs = {u['modulo_preferido'] for u in users if u['modulo_preferido']}
        modulo_nombres_map = {}
        if modulos_preferidos_slugs:
            modulos_rows = await conn.fetch(
                "SELECT slug, nombre FROM tb_modulos_catalogo WHERE slug = ANY($1)",
                list(modulos_preferidos_slugs)
            )
            modulo_nombres_map = {row['slug']: row['nombre'] for row in modulos_rows}
        
        # 4. Mapear permisos a usuarios en memoria (O(n))
        perm_map = {}
        for p in all_permissions:
            uid = p['usuario_id']
            if uid not in perm_map:
                perm_map[uid] = []
            perm_map[uid].append(dict(p))
        
        # 5. Construir usuarios enriquecidos
        users_enriched = []
        for user in users:
            user_dict = dict(user)
            user_dict['user_modules'] = perm_map.get(user['id_usuario'], [])
            user_dict['modulo_preferido_nombre'] = modulo_nombres_map.get(user['modulo_preferido'])
            users_enriched.append(user_dict)
        
        return users_enriched
    
    async def get_email_rules(self, conn) -> List[Dict]:
        """
        Obtiene todas las reglas de correo configuradas.
        
        Returns:
            List[Dict]: Lista de reglas de email
        """
        rules = await conn.fetch(
            "SELECT * FROM tb_config_emails ORDER BY modulo, trigger_field"
        )
        return [dict(r) for r in rules]
    
    async def get_email_defaults(self, conn) -> Dict:
        """
        Obtiene la configuración global de correos (defaults).
        
        Returns:
            Dict: Configuración de defaults o dict vacío si no existe
        """
        defaults = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
        if not defaults:
            return {"default_to": "", "default_cc": "", "default_cco": ""}
        return dict(defaults)
    
    async def get_departments_catalog(self, conn) -> List[Dict]:
        """
        Obtiene catálogo de departamentos activos.
        
        Returns:
            List[Dict]: Lista de departamentos con id, nombre, slug
        """
        departments = await conn.fetch(
            "SELECT id, nombre, slug FROM tb_departamentos_catalogo WHERE is_active = true ORDER BY nombre"
        )
        return [
            {
                "id": str(d['id']),
                "nombre": d['nombre'],
                "slug": d['slug']
            } for d in departments
        ]
    
    async def get_modules_catalog(self, conn) -> List[Dict]:
        """
        Obtiene catálogo de módulos activos.
        
        Returns:
            List[Dict]: Lista de módulos con id, nombre, slug, icono
        """
        modules = await conn.fetch(
            "SELECT id, nombre, slug, icono FROM tb_modulos_catalogo WHERE is_active = true ORDER BY orden"
        )
        return [
            {
                "id": str(m['id']),
                "nombre": m['nombre'],
                "slug": m['slug'],
                "icono": m['icono']
            } for m in modules
        ]
    
    async def get_catalogos_reglas(self, conn) -> Dict:
        """
        Obtiene catálogos necesarios para formularios y gestión.
        Patrón recomendado por GUIA_MAESTRA líneas 703-727.
        
        Returns:
            Dict: Catálogos de tecnologías, tipos de solicitud y estatus
        """
        tecnologias = await conn.fetch(
            "SELECT id, nombre, activo FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        )
        tipos_solicitud = await conn.fetch(
            "SELECT id, nombre, codigo_interno, activo FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        )
        estatus = await conn.fetch(
            "SELECT id, nombre, descripcion, color_hex, activo FROM tb_cat_estatus_global WHERE activo = true ORDER BY nombre"
        )
        origenes = await conn.fetch(
            "SELECT id, slug, descripcion, activo FROM tb_cat_origenes_adjuntos WHERE activo = true ORDER BY slug"
        )
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos_solicitud],
            "estatus": [dict(e) for e in estatus],
            "origenes_adjuntos": [dict(o) for o in origenes]
        }
    
    # --- GESTIÓN DE CONFIGURACIÓN GLOBAL ---
    
    async def get_global_config(self, conn) -> dict:
        """
        Recupera la configuración global y la tipifica correctamente.
        La tabla almacena todo como strings (key-value), aquí se transforman a tipos Python.
        
        Returns:
            dict: Configuración tipificada
        """
        rows = await conn.fetch("SELECT clave, valor FROM tb_configuracion_global")
        config_dict = {row['clave']: row['valor'] for row in rows}
        
        # Transformación de tipos para el Schema
        return {
            "hora_corte_l_v": config_dict.get("HORA_CORTE_L_V", "18:00"),
            "dias_sla_default": int(config_dict.get("DIAS_SLA_DEFAULT", "7")),
            "dias_fin_semana": json.loads(config_dict.get("DIAS_FIN_SEMANA", "[5, 6]")),
            # SharePoint Config
            "sharepoint_site_id": config_dict.get("SHAREPOINT_SITE_ID", ""),
            "sharepoint_drive_id": config_dict.get("SHAREPOINT_DRIVE_ID", ""),
            "sharepoint_base_folder": config_dict.get("SHAREPOINT_BASE_FOLDER", ""),
            "max_upload_size_mb": int(config_dict.get("MAX_UPLOAD_SIZE_MB", "500"))
        }

    async def update_global_config(self, conn, datos: ConfiguracionGlobalUpdate) -> None:
        """
        Actualiza los parámetros globales del sistema.
        Usa UPSERT para evitar duplicados en tabla key-value.
        
        Args:
            conn: Conexión a la base de datos
            datos: Schema validado con los nuevos valores
        """
        updates = [
            ("HORA_CORTE_L_V", datos.hora_corte_l_v),
            ("DIAS_SLA_DEFAULT", str(datos.dias_sla_default)),
            ("DIAS_FIN_SEMANA", json.dumps(datos.dias_fin_semana)),
            # SharePoint Config
            ("SHAREPOINT_SITE_ID", datos.sharepoint_site_id or ""),
            ("SHAREPOINT_DRIVE_ID", datos.sharepoint_drive_id or ""),
            ("SHAREPOINT_BASE_FOLDER", datos.sharepoint_base_folder or ""),
            ("MAX_UPLOAD_SIZE_MB", str(datos.max_upload_size_mb)),
            # Simulation KPI Config
            ("sim_peso_compromiso", str(datos.sim_peso_compromiso)),
            ("sim_peso_interno", str(datos.sim_peso_interno)),
            ("sim_peso_volumen", str(datos.sim_peso_volumen)),
            ("sim_umbral_min_entregas", str(datos.sim_umbral_min_entregas)),
            ("sim_umbral_ratio_licitaciones", str(datos.sim_umbral_ratio_licitaciones)),
            ("sim_umbral_verde", str(datos.sim_umbral_verde)),
            ("sim_umbral_ambar", str(datos.sim_umbral_ambar)),
            ("sim_mult_licitaciones", str(datos.sim_mult_licitaciones)),
            ("sim_mult_actualizaciones", str(datos.sim_mult_actualizaciones)),
            ("sim_penalizacion_retrabajos", str(datos.sim_penalizacion_retrabajos)),
            ("sim_volumen_max", str(datos.sim_volumen_max))
        ]
        
        for clave, valor in updates:
            await conn.execute(
                """INSERT INTO tb_configuracion_global (clave, valor) 
                   VALUES ($1, $2)
                   ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor""",
                clave, valor
            )
        logger.info(f"Configuración global actualizada (incluyendo SharePoint): SLA={datos.dias_sla_default}")
    
    # --- LÓGICA PARA REGLAS DE CORREO DINÁMICAS ---

    async def get_options_for_trigger(self, conn, trigger_field: str) -> List[Dict]:
        """Retorna las opciones válidas de forma dinámica (BD) para evitar hardcoding."""
        if trigger_field == "Tecnología":
            query = "SELECT nombre as label, CAST(id AS TEXT) as value FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        
        elif trigger_field == "Tipo Solicitud":
            query = "SELECT nombre as label, CAST(id AS TEXT) as value FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        
        elif trigger_field == "Estatus":
            query = "SELECT nombre as label, CAST(id AS TEXT) as value FROM tb_cat_estatus_global WHERE activo = true ORDER BY nombre"
        
        elif trigger_field == "EVENTO":
            # Leer de BD (tb_configuracion_global) para evitar hardcoding
            config_json = await conn.fetchval(
                "SELECT valor FROM tb_configuracion_global WHERE clave = 'EVENTOS_SISTEMA'"
            )
            if config_json:
                try:
                    return json.loads(config_json)
                except json.JSONDecodeError:
                    logger.error("Error decodificando EVENTOS_SISTEMA de tb_configuracion_global")
                    # Fallback a eventos comunes
                    return [
                        {"label": "Nuevo Comentario", "value": "NUEVO_COMENTARIO"},
                        {"label": "Cambio de Estatus", "value": "CAMBIO_ESTATUS"},
                        {"label": "Asignación", "value": "ASIGNACION"}
                    ]
            # Si no existe en BD, usar fallback
            return [
                {"label": "Nuevo Comentario", "value": "NUEVO_COMENTARIO"},
                {"label": "Cambio de Estatus", "value": "CAMBIO_ESTATUS"},
                {"label": "Asignación", "value": "ASIGNACION"}
            ]
        
        else:
            return [] 
            
        rows = await conn.fetch(query)
        return [dict(r) for r in rows]
    
    async def add_email_rule(
        self, 
        conn, 
        modulo: str, 
        trigger_field: str, 
        trigger_value: str, 
        email_to_add: str, 
        type: str
    ) -> None:
        """
        Agrega una nueva regla de correo.
        
        Args:
            conn: Conexión a la base de datos
            modulo: Módulo al que aplica la regla
            trigger_field: Campo que dispara la regla
            trigger_value: Valor que debe tener el campo
            email_to_add: Email a agregar
            type: Tipo (TO/CC)
        """
        await conn.execute(
            """INSERT INTO tb_config_emails 
               (modulo, trigger_field, trigger_value, email_to_add, type) 
               VALUES ($1, $2, $3, $4, $5)""",
            modulo, trigger_field, trigger_value, email_to_add, type
        )
        logger.info(f"Regla de email creada: {trigger_field}={trigger_value} -> {email_to_add}")
    
    async def delete_email_rule(self, conn, rule_id: int) -> None:
        """
        Elimina una regla de correo.
        
        Args:
            conn: Conexión a la base de datos
            rule_id: ID de la regla a eliminar
        """
        await conn.execute("DELETE FROM tb_config_emails WHERE id = $1", rule_id)
        logger.info(f"Regla de email eliminada: ID {rule_id}")
    
    async def update_email_defaults(
        self, 
        conn, 
        default_to: str, 
        default_cc: str, 
        default_cco: str
    ) -> None:
        """
        Actualiza la configuración global de correos.
        
        Args:
            conn: Conexión a la base de datos
            default_to: Destinatarios TO por defecto
            default_cc: Destinatarios CC por defecto
            default_cco: Destinatarios CCO por defecto
        """
        # Validar que existe row ID 1
        row = await conn.fetchrow("SELECT id FROM tb_email_defaults WHERE id = 1")
        if not row:
            await conn.execute(
                "INSERT INTO tb_email_defaults (id, default_to, default_cc, default_cco) VALUES (1, '', '', '')"
            )
        
        await conn.execute(
            """UPDATE tb_email_defaults 
               SET default_to = $1, default_cc = $2, default_cco = $3 
               WHERE id = 1""",
            default_to, default_cc, default_cco
        )
        logger.info("Email defaults actualizados")
    
    async def update_user_role(self, conn, user_id: UUID, role: str) -> None:
        """
        Actualiza el rol de sistema de un usuario.
        
        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            role: Nuevo rol (ADMIN/MANAGER/USER)
        """
        await conn.execute(
            "UPDATE tb_usuarios SET rol_sistema = $1 WHERE id_usuario = $2", 
            role, user_id
        )
        logger.info(f"Rol actualizado para usuario {user_id}: {role}")
    
    async def update_user_department(self, conn, user_id: UUID, department_slug: str) -> str:
        """
        Asigna un departamento a un usuario.
        
        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            department_slug: Slug del departamento
            
        Returns:
            str: Nombre del departamento asignado
        """
        # Obtener nombre del departamento
        dept_nombre = await conn.fetchval(
            "SELECT nombre FROM tb_departamentos_catalogo WHERE slug = $1",
            department_slug
        )
        
        if not dept_nombre:
            raise ValueError("Departamento no encontrado")
        
        # Actualizar usuario
        await conn.execute(
            "UPDATE tb_usuarios SET department = $1 WHERE id_usuario = $2",
            dept_nombre, user_id
        )
        logger.info(f"Departamento actualizado para usuario {user_id}: {dept_nombre}")
        return dept_nombre
    
    async def update_user_modules(self, conn, user_id: UUID, module_roles: Dict[str, str]) -> None:
        """
        Actualiza los módulos y roles asignados a un usuario.
        
        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            module_roles: Dict con módulo_slug: rol
        """
        # Borrar permisos actuales
        await conn.execute("DELETE FROM tb_permisos_modulos WHERE usuario_id = $1", user_id)
        
        # Insertar nuevos permisos
        for module_slug, rol in module_roles.items():
            if rol:  # Solo si hay un rol seleccionado
                await conn.execute(
                    """INSERT INTO tb_permisos_modulos (usuario_id, modulo_slug, rol_modulo)
                       VALUES ($1, $2, $3)""",
                    user_id, module_slug, rol
                )
        logger.info(f"Módulos actualizados para usuario {user_id}")
    
    async def update_preferred_module(self, conn, user_id: UUID, modulo_slug: Optional[str]) -> None:
        """
        Establece el módulo preferido del usuario.
        
        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            modulo_slug: Slug del módulo preferido (None para auto)
        """
        await conn.execute(
            "UPDATE tb_usuarios SET modulo_preferido = $1 WHERE id_usuario = $2",
            modulo_slug if modulo_slug else None, user_id
        )
        logger.info(f"Módulo preferido actualizado para usuario {user_id}: {modulo_slug}")
    
    async def get_user_modules(self, conn, user_id: UUID) -> List[Dict]:
        """
        Obtiene los módulos asignados a un usuario.
        
        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            
        Returns:
            List[Dict]: Lista de permisos del usuario
        """
        permisos = await conn.fetch(
            "SELECT modulo_slug, rol_modulo FROM tb_permisos_modulos WHERE usuario_id = $1",
            user_id
        )
        return [dict(p) for p in permisos]
    
    async def deactivate_user(self, conn, user_id: UUID) -> Dict:
        """
        Desactiva un usuario (soft delete).
        
        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario a desactivar
            
        Returns:
            Dict: Usuario actualizado con is_active=False
        """
        # Soft Delete: Marcar como inactivo
        await conn.execute(
            "UPDATE tb_usuarios SET is_active = FALSE WHERE id_usuario = $1",
            user_id
        )
        
        # Obtener usuario actualizado para renderizar
        user = await conn.fetchrow(
            "SELECT * FROM tb_usuarios WHERE id_usuario = $1",
            user_id
        )
        
        logger.info(f"Usuario desactivado (soft delete): {user_id}")
        return dict(user) if user else None
    
    async def reactivate_user(self, conn, user_id: UUID) -> Dict:
        """
        Reactiva un usuario previamente desactivado.
        
        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario a reactivar
            
        Returns:
            Dict: Usuario actualizado con is_active=True
        """
        # Restore: Marcar como activo
        await conn.execute(
            "UPDATE tb_usuarios SET is_active = TRUE WHERE id_usuario = $1",
            user_id
        )
        
        # Obtener usuario actualizado para renderizar
        user = await conn.fetchrow(
            "SELECT * FROM tb_usuarios WHERE id_usuario = $1",
            user_id
        )
        
        logger.info(f"Usuario reactivado: {user_id}")
        return dict(user) if user else None
    
    # --- GESTIÓN AVANZADA DE CATÁLOGOS ---
    
    # --- Tecnologías ---
    
    async def create_tecnologia(self, conn, nombre: str) -> None:
        """
        Crea una nueva tecnología con validación de duplicados.
        
        Args:
            conn: Conexión a la base de datos
            nombre: Nombre de la nueva tecnología
            
        Raises:
            ValueError: Si la tecnología ya existe
        """
        # Validación de duplicados (case-insensitive)
        exists = await conn.fetchval(
            "SELECT 1 FROM tb_cat_tecnologias WHERE nombre ILIKE $1", 
            nombre
        )
        if exists:
            raise ValueError(f"La tecnología '{nombre}' ya existe.")
        
        await conn.execute(
            "INSERT INTO tb_cat_tecnologias (nombre, activo) VALUES ($1, true)", 
            nombre
        )
        logger.info(f"Nueva tecnología creada: {nombre}")
    
    async def update_tecnologia(self, conn, id_tech: int, nombre: str, activo: bool) -> None:
        """
        Actualiza nombre o estado de una tecnología.
        
        Args:
            conn: Conexión a la base de datos
            id_tech: ID de la tecnología a actualizar
            nombre: Nuevo nombre
            activo: Nuevo estado
        """
        await conn.execute(
            "UPDATE tb_cat_tecnologias SET nombre = $1, activo = $2 WHERE id = $3",
            nombre, activo, id_tech
        )
        logger.info(f"Tecnología ID {id_tech} actualizada: {nombre} (activo={activo})")
    
    # --- Tipos de Solicitud ---
    
    async def create_tipo_solicitud(self, conn, nombre: str, codigo: str) -> None:
        """
        Crea un nuevo tipo de solicitud.
        El código interno es vital para el backend, se normaliza a mayúsculas.
        
        Args:
            conn: Conexión a la base de datos
            nombre: Nombre del tipo de solicitud
            codigo: Código interno (se convertirá a mayúsculas)
        """
        # Normalizar código a mayúsculas para consistencia
        codigo_clean = codigo.strip().upper()
        
        await conn.execute(
            "INSERT INTO tb_cat_tipos_solicitud (nombre, codigo_interno, activo) VALUES ($1, $2, true)",
            nombre, codigo_clean
        )
        logger.info(f"Nuevo tipo de solicitud creado: {nombre} (código: {codigo_clean})")
    
    async def update_tipo_solicitud(self, conn, id_tipo: int, nombre: str, codigo: str, activo: bool) -> None:
        """
        Actualiza tipo de solicitud con validación del código interno.
        Registra advertencia si se cambia el código interno.
        
        Args:
            conn: Conexión a la base de datos
            id_tipo: ID del tipo a actualizar
            nombre: Nuevo nombre
            codigo: Nuevo código interno
            activo: Nuevo estado
        """
        # Verificar si se está cambiando el código interno
        current_code = await conn.fetchval(
            "SELECT codigo_interno FROM tb_cat_tipos_solicitud WHERE id = $1", 
            id_tipo
        )
        
        if current_code != codigo:
            logger.warning(
                f"ALERTA - Cambiando código interno ID {id_tipo}: '{current_code}' -> '{codigo}' "
                f"(esto puede afectar lógica de backend)"
            )
        
        await conn.execute(
            """UPDATE tb_cat_tipos_solicitud 
               SET nombre = $1, codigo_interno = $2, activo = $3 
               WHERE id = $4""",
            nombre, codigo, activo, id_tipo
        )
        logger.info(f"Tipo de solicitud ID {id_tipo} actualizado: {nombre}")
    
    # --- Estatus Global ---
    
    async def create_estatus(self, conn, nombre: str, descripcion: str, color: str) -> None:
        """
        Crea un nuevo estatus global.
        
        Args:
            conn: Conexión a la base de datos
            nombre: Nombre del estatus
            descripcion: Descripción del estatus
            color: Color hex (ej: #00BABB)
        """
        await conn.execute(
            "INSERT INTO tb_cat_estatus_global (nombre, descripcion, color_hex, activo) VALUES ($1, $2, $3, true)",
            nombre, descripcion, color
        )
        logger.info(f"Nuevo estatus creado: {nombre} (color: {color})")
    
    # --- Orígenes de Adjuntos ---

    async def create_origen_adjunto(self, conn, slug: str, descripcion: str) -> None:
        """Crea un nuevo origen de adjunto en el catálogo."""
        slug_clean = slug.strip().lower()
        
        # Validar duplicados
        exists = await conn.fetchval(
            "SELECT 1 FROM tb_cat_origenes_adjuntos WHERE slug = $1", 
            slug_clean
        )
        if exists:
            # Si existe pero está inactivo, lo reactivamos? Mejor error por ahora
            raise ValueError(f"El origen '{slug_clean}' ya existe.")
            
        await conn.execute(
            "INSERT INTO tb_cat_origenes_adjuntos (slug, descripcion, activo) VALUES ($1, $2, true)",
            slug_clean, descripcion
        )
        logger.info(f"Nuevo origen de adjunto creado: {slug_clean}")

    async def toggle_catalogo_status(self, conn, table: str, item_id: int, current_status: bool) -> None:
        """
        Switch genérico para Soft Delete/Activate de catálogos.
        Incluye whitelist de seguridad para prevenir SQL injection.
        
        Args:
            conn: Conexión a la base de datos
            table: Nombre de la tabla del catálogo
            item_id: ID del elemento a modificar
            current_status: Estado actual del campo activo
        
        Raises:
            ValueError: Si la tabla no está en la whitelist de tablas permitidas
        """
        # Validación de seguridad para evitar inyección SQL en nombre de tabla
        valid_tables = [
            "tb_cat_tecnologias", 
            "tb_cat_tipos_solicitud", 
            "tb_cat_estatus_global",
            "tb_cat_origenes_adjuntos" # New whitelist item
        ]
        if table not in valid_tables:
            raise ValueError(f"Tabla no permitida: {table}")
            
        new_status = not current_status
        # Note: tb_cat_origenes_adjuntos uses integer ID too? Schema says yes (SERIAL PRIMARY KEY)
        # Verify schema 09-sharepoint_schema.sql: 
        # CREATE TABLE IF NOT EXISTS tb_cat_origenes_adjuntos (
        #    id SERIAL PRIMARY KEY, ...
        # )
        # So item_id: int is correct.
        
        await conn.execute(
            f"UPDATE {table} SET activo = $1 WHERE id = $2", 
            new_status, item_id
        )
        logger.info(f"Catálogo {table} ID {item_id}: activo cambiado a {new_status}")


def get_admin_service():
    """Helper para inyección de dependencias."""
    return AdminService()
