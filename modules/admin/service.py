# modules/admin/service.py
"""
Service Layer para el módulo Admin.
Contiene lógica de negocio y orquestación.
Las queries SQL se delegan a AdminDBService (db_service.py).
"""
from typing import List, Dict, Optional
from uuid import UUID
import json
import logging

from .schemas import ConfiguracionGlobalUpdate, EmailRuleCreate
from .db_service import AdminDBService
from core.config_service import ConfigService

logger = logging.getLogger("AdminModule")


class AdminService:
    """Maneja toda la lógica de negocio del módulo Admin."""

    def __init__(self):
        self.db = AdminDBService()

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
        users = await self.db.fetch_all_users(conn)
        if not users:
            return []

        # 2. Obtener todos los permisos de una sola vez con JOIN
        all_permissions = await self.db.fetch_all_permissions(conn)

        # 3. Obtener nombres de módulos preferidos de una sola vez
        modulos_preferidos_slugs = [u['modulo_preferido'] for u in users if u.get('modulo_preferido')]
        modulo_nombres_map = await self.db.fetch_modulos_by_slugs(conn, modulos_preferidos_slugs)

        # 4. Mapear permisos a usuarios en memoria (O(n))
        perm_map = {}
        for p in all_permissions:
            uid = p['usuario_id']
            if uid not in perm_map:
                perm_map[uid] = []
            perm_map[uid].append(p)

        # 5. Construir usuarios enriquecidos
        users_enriched = []
        for user in users:
            user['user_modules'] = perm_map.get(user['id_usuario'], [])
            user['modulo_preferido_nombre'] = modulo_nombres_map.get(user.get('modulo_preferido'))
            users_enriched.append(user)

        return users_enriched

    async def get_email_rules(self, conn) -> List[Dict]:
        """
        Obtiene todas las reglas de correo configuradas.

        Returns:
            List[Dict]: Lista de reglas de email
        """
        return await self.db.fetch_email_rules(conn)

    async def get_email_defaults(self, conn) -> Dict:
        """
        Obtiene la configuración global de correos (defaults).

        Returns:
            Dict: Configuración de defaults o dict vacío si no existe
        """
        defaults = await self.db.fetch_email_defaults(conn)
        if not defaults:
            return {"default_to": "", "default_cc": "", "default_cco": ""}
        return defaults

    async def get_departments_catalog(self, conn) -> List[Dict]:
        """
        Obtiene catálogo de departamentos activos.

        Returns:
            List[Dict]: Lista de departamentos con id, nombre, slug
        """
        departments = await self.db.fetch_departments_catalog(conn)
        # Transformar id a string para uso en templates
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
        modules = await self.db.fetch_modules_catalog(conn)
        # Transformar id a string para uso en templates
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
        tecnologias = await self.db.fetch_catalogo_tecnologias(conn)
        tipos_solicitud = await self.db.fetch_catalogo_tipos_solicitud(conn)
        estatus = await self.db.fetch_catalogo_estatus(conn)
        origenes = await self.db.fetch_catalogo_origenes_adjuntos(conn)

        return {
            "tecnologias": tecnologias,
            "tipos_solicitud": tipos_solicitud,
            "estatus": estatus,
            "origenes_adjuntos": origenes
        }

    # --- GESTIÓN DE CONFIGURACIÓN GLOBAL ---

    async def get_global_config(self, conn) -> dict:
        """
        Recupera la configuración global y la tipifica correctamente.
        La tabla almacena todo como strings (key-value), aquí se transforman a tipos Python.

        Returns:
            dict: Configuración tipificada
        """
        config_dict = await self.db.fetch_global_config(conn)

        # Transformación de tipos para el Schema
        return {
            "hora_corte_l_v": config_dict.get("HORA_CORTE_L_V", "18:00"),
            "dias_sla_default": int(config_dict.get("DIAS_SLA_DEFAULT", "7")),
            "dias_fin_semana": json.loads(config_dict.get("DIAS_FIN_SEMANA", "[5, 6]")),
            # SharePoint Config
            "sharepoint_site_id": config_dict.get("SHAREPOINT_SITE_ID", ""),
            "sharepoint_drive_id": config_dict.get("SHAREPOINT_DRIVE_ID", ""),
            "sharepoint_base_folder": config_dict.get("SHAREPOINT_BASE_FOLDER", ""),
            "max_upload_size_mb": int(config_dict.get("MAX_UPLOAD_SIZE_MB", "500")),
            # Simulation KPIS
            "sim_peso_compromiso": config_dict.get("sim_peso_compromiso", None),
            "sim_peso_interno": config_dict.get("sim_peso_interno", None),
            "sim_peso_volumen": config_dict.get("sim_peso_volumen", None),
            "sim_umbral_min_entregas": config_dict.get("sim_umbral_min_entregas", None),
            "sim_umbral_ratio_licitaciones": config_dict.get("sim_umbral_ratio_licitaciones", None),
            "sim_umbral_verde": config_dict.get("sim_umbral_verde", None),
            "sim_umbral_ambar": config_dict.get("sim_umbral_ambar", None),
            "sim_mult_licitaciones": config_dict.get("sim_mult_licitaciones", None),
            "sim_mult_actualizaciones": config_dict.get("sim_mult_actualizaciones", None),
            "sim_penalizacion_retrabajos": config_dict.get("sim_penalizacion_retrabajos", None),
            "sim_penalizacion_retrabajos": config_dict.get("sim_penalizacion_retrabajos", None),
            "sim_volumen_max": config_dict.get("sim_volumen_max", None),
            # Comercial Config
            "comercial_popup_targets": config_dict.get("COMERCIAL_POPUP_TARGETS", "")
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
            ("sim_mult_actualizaciones", str(datos.sim_mult_actualizaciones)),
            ("sim_penalizacion_retrabajos", str(datos.sim_penalizacion_retrabajos)),
            ("sim_volumen_max", str(datos.sim_volumen_max)),
            # Comercial Config
            ("COMERCIAL_POPUP_TARGETS", datos.comercial_popup_targets or "")
        ]

        for clave, valor in updates:
            await self.db.upsert_global_config(conn, clave, valor)
        logger.info(f"Configuración global actualizada (incluyendo SharePoint): SLA={datos.dias_sla_default}")
        ConfigService.invalidar_cache()


    async def reset_simulation_defaults(self, conn) -> None:
        """
        Elimina las configuraciones personalizadas de simulación para restaurar los defaults del código.
        """
        keys_to_delete = [
            "sim_peso_compromiso",
            "sim_peso_interno",
            "sim_peso_volumen",
            "sim_umbral_min_entregas",
            "sim_umbral_ratio_licitaciones",
            "sim_umbral_verde",
            "sim_umbral_ambar",
            "sim_mult_licitaciones",
            "sim_mult_actualizaciones",
            "sim_penalizacion_retrabajos",
            "sim_volumen_max"
        ]

        await self.db.delete_global_config_keys(conn, keys_to_delete)
        logger.info("Configuración de simulación restaurada a defaults (filas eliminadas)")
        ConfigService.invalidar_cache()

    # --- LÓGICA PARA REGLAS DE CORREO DINÁMICAS ---

    async def get_options_for_trigger(self, conn, trigger_field: str) -> List[Dict]:
        """Retorna las opciones válidas de forma dinámica (BD) para evitar hardcoding."""
        if trigger_field == "Tecnología":
            return await self.db.fetch_tecnologias_options(conn)

        elif trigger_field == "Tipo Solicitud":
            return await self.db.fetch_tipos_solicitud_options(conn)

        elif trigger_field == "Estatus":
            return await self.db.fetch_estatus_options(conn)

        elif trigger_field == "EVENTO":
            config_json = await self.db.fetch_eventos_sistema_config(conn)
            if config_json:
                try:
                    return json.loads(config_json)
                except json.JSONDecodeError:
                    logger.error("Error decodificando EVENTOS_SISTEMA de tb_configuracion_global")
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
        await self.db.insert_email_rule(conn, modulo, trigger_field, trigger_value, email_to_add, type)
        logger.info(f"Regla de email creada: {trigger_field}={trigger_value} -> {email_to_add}")

    async def delete_email_rule(self, conn, rule_id: int) -> None:
        """
        Elimina una regla de correo.

        Args:
            conn: Conexión a la base de datos
            rule_id: ID de la regla a eliminar
        """
        await self.db.delete_email_rule(conn, rule_id)
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
        await self.db.ensure_email_defaults_row(conn)
        await self.db.update_email_defaults(conn, default_to, default_cc, default_cco)
        logger.info("Email defaults actualizados")

    async def update_user_role(self, conn, user_id: UUID, role: str) -> None:
        """
        Actualiza el rol de sistema de un usuario.

        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            role: Nuevo rol (ADMIN/MANAGER/USER)
        """
        await self.db.update_user_role(conn, user_id, role)
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
        dept_nombre = await self.db.fetch_department_name_by_slug(conn, department_slug)

        if not dept_nombre:
            raise ValueError("Departamento no encontrado")

        await self.db.update_user_department(conn, user_id, dept_nombre)
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
        await self.db.delete_user_permissions(conn, user_id)

        for module_slug, rol in module_roles.items():
            if rol:  # Solo si hay un rol seleccionado
                await self.db.insert_user_permission(conn, user_id, module_slug, rol)
        logger.info(f"Módulos actualizados para usuario {user_id}")

    async def update_preferred_module(self, conn, user_id: UUID, modulo_slug: Optional[str]) -> None:
        """
        Establece el módulo preferido del usuario.

        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            modulo_slug: Slug del módulo preferido (None para auto)
        """
        await self.db.update_user_preferred_module(conn, user_id, modulo_slug if modulo_slug else None)
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
        return await self.db.fetch_user_permissions(conn, user_id)

    async def update_user_simulation_flag(self, conn, user_id: UUID, value: bool) -> None:
        """
        Actualiza el flag puede_asignarse_simulacion del usuario.

        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            value: Nuevo valor del flag
        """
        await self.db.update_user_simulation_flag(conn, user_id, value)
        logger.info(f"Flag simulación actualizado para usuario {user_id}: {value}")

    async def deactivate_user(self, conn, user_id: UUID) -> Dict:
        """
        Desactiva un usuario (soft delete).

        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario a desactivar

        Returns:
            Dict: Usuario actualizado con is_active=False
        """
        await self.db.deactivate_user(conn, user_id)
        user = await self.db.fetch_user_by_id(conn, user_id)

        logger.info(f"Usuario desactivado (soft delete): {user_id}")
        return user

    async def reactivate_user(self, conn, user_id: UUID) -> Dict:
        """
        Reactiva un usuario previamente desactivado.

        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario a reactivar

        Returns:
            Dict: Usuario actualizado con is_active=True
        """
        await self.db.reactivate_user(conn, user_id)
        user = await self.db.fetch_user_by_id(conn, user_id)

        logger.info(f"Usuario reactivado: {user_id}")
        return user

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
        if await self.db.check_tecnologia_exists(conn, nombre):
            raise ValueError(f"La tecnología '{nombre}' ya existe.")

        await self.db.insert_tecnologia(conn, nombre)
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
        await self.db.update_tecnologia(conn, id_tech, nombre, activo)
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
        codigo_clean = codigo.strip().upper()

        await self.db.insert_tipo_solicitud(conn, nombre, codigo_clean)
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
        current_code = await self.db.fetch_tipo_solicitud_codigo(conn, id_tipo)

        if current_code != codigo:
            logger.warning(
                f"ALERTA - Cambiando código interno ID {id_tipo}: '{current_code}' -> '{codigo}' "
                f"(esto puede afectar lógica de backend)"
            )

        await self.db.update_tipo_solicitud(conn, id_tipo, nombre, codigo, activo)
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
        await self.db.insert_estatus(conn, nombre, descripcion, color)
        logger.info(f"Nuevo estatus creado: {nombre} (color: {color})")

    # --- Orígenes de Adjuntos ---

    async def create_origen_adjunto(self, conn, slug: str, descripcion: str) -> None:
        """Crea un nuevo origen de adjunto en el catálogo."""
        slug_clean = slug.strip().lower()

        if await self.db.check_origen_adjunto_exists(conn, slug_clean):
            raise ValueError(f"El origen '{slug_clean}' ya existe.")

        await self.db.insert_origen_adjunto(conn, slug_clean, descripcion)
        logger.info(f"Nuevo origen de adjunto creado: {slug_clean}")

    async def toggle_catalogo_status(self, conn, table: str, item_id: int, current_status: bool) -> None:
        """
        Switch generico para Soft Delete/Activate de catalogos.
        Valida tabla contra whitelist para prevenir SQL injection.
        """
        new_status = not current_status
        await self.db.toggle_catalogo_status(conn, table, item_id, new_status)
        logger.info(f"Catalogo {table} ID {item_id}: activo cambiado a {new_status}")


def get_admin_service():
    """Helper para inyección de dependencias."""
    return AdminService()
