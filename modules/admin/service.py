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
import secrets
import time

from .schemas import ConfiguracionGlobalUpdate, EmailRuleCreate
from .db_service import AdminDBService
from .constants import ROLES_ORGANIZACIONALES_VALIDOS
from core.config_service import ConfigService
from core.microsoft import MicrosoftAuth
from modules.asistencia.constants import BIOTIME_CONFIG_KEYS
from modules.cfe.constants import CFE_CONFIG_KEYS
from .permission_utils import validate_module_roles

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
            "sp_visitas_site_id": config_dict.get("SP_VISITAS_SITE_ID", ""),
            "sp_visitas_drive_id": config_dict.get("SP_VISITAS_DRIVE_ID", ""),
            # SAT Inbox SharePoint
            "sp_sat_site_id": config_dict.get("SP_SAT_SITE_ID", ""),
            "sp_sat_drive_id": config_dict.get("SP_SAT_DRIVE_ID", ""),
            "sp_sat_base_folder": config_dict.get("SP_SAT_BASE_FOLDER", "SAT-Inbox"),
            # BioTime
            "biotime_base_url": config_dict.get("BIOTIME_BASE_URL", ""),
            "biotime_username": config_dict.get("BIOTIME_USERNAME", ""),
            "biotime_password_configured": bool(config_dict.get("BIOTIME_PASSWORD", "")),
            "biotime_password_masked": "********" if config_dict.get("BIOTIME_PASSWORD", "") else "",
            "biotime_sync_activo": config_dict.get("BIOTIME_SYNC_ACTIVO", "false").lower() == "true",
            "biotime_sync_interval_seg": int(config_dict.get("BIOTIME_SYNC_INTERVAL_SEG", "900")),
            "biotime_sync_page_size": int(config_dict.get("BIOTIME_SYNC_PAGE_SIZE", "200")),
            "biotime_sync_lookback_hrs": int(config_dict.get("BIOTIME_SYNC_LOOKBACK_HRS", "48")),
            "biotime_sync_timeout_seg": int(config_dict.get("BIOTIME_SYNC_TIMEOUT_SEG", "30")),
            "asistencia_recalc_dias": int(config_dict.get("ASISTENCIA_RECALC_DIAS", "7")),
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
            "comercial_popup_targets": config_dict.get("COMERCIAL_POPUP_TARGETS") or "",
            # Reporte Semanal
            "reporte_semanal_destinatarios": config_dict.get("reporte_semanal_destinatarios") or "",
            # Visita a Obra
            "visita_obra_destinatarios": config_dict.get("visita_obra_destinatarios") or "",
            # Reporte Desarrollo CEO
            "reporte_desarrollo_ceo_email": config_dict.get("reporte_desarrollo_ceo_email") or "",
            "reporte_ceo_activo": config_dict.get("reporte_desarrollo_ceo_activo", "true").lower() == "true",
            # Notificaciones Vacaciones
            "vacaciones_cco_emails": config_dict.get("VACACIONES_CCO_EMAILS") or "",
            # Vacaciones — Anticipos y Expiración
            "vacaciones_meses_expiracion": int(config_dict.get("VACACIONES_MESES_EXPIRACION", "18")),
            "vacaciones_anticipo_habilitado": config_dict.get("VACACIONES_ANTICIPO_HABILITADO", "true").lower() == "true",
            "vacaciones_anticipo_meses_semestre": int(config_dict.get("VACACIONES_ANTICIPO_MESES_SEMESTRE", "6")),
            "vacaciones_anticipo_porcentaje_liberacion": int(config_dict.get("VACACIONES_ANTICIPO_PORCENTAJE_LIBERACION", "50")),
            "vacaciones_anticipo_maximo_dias": int(config_dict.get("VACACIONES_ANTICIPO_MAXIMO_DIAS", "7")),
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
            ("SP_VISITAS_SITE_ID", datos.sp_visitas_site_id or ""),
            ("SP_VISITAS_DRIVE_ID", datos.sp_visitas_drive_id or ""),
            # SAT Inbox SharePoint
            ("SP_SAT_SITE_ID", datos.sp_sat_site_id or ""),
            ("SP_SAT_DRIVE_ID", datos.sp_sat_drive_id or ""),
            ("SP_SAT_BASE_FOLDER", datos.sp_sat_base_folder or "SAT-Inbox"),
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
            ("COMERCIAL_POPUP_TARGETS", datos.comercial_popup_targets or ""),
            # Reporte Semanal
            ("reporte_semanal_destinatarios", datos.reporte_semanal_destinatarios or ""),
            # Visita a Obra
            ("visita_obra_destinatarios", datos.visita_obra_destinatarios or ""),
            # Reporte Desarrollo CEO
            ("reporte_desarrollo_ceo_email", datos.reporte_desarrollo_ceo_email or ""),
        ]

        for clave, valor in updates:
            await self.db.upsert_global_config(conn, clave, valor)
        logger.info(f"Configuración global actualizada (incluyendo SharePoint): SLA={datos.dias_sla_default}")
        ConfigService.invalidar_cache()


    async def resolve_biotime_credentials(
        self,
        conn,
        *,
        base_url: str = "",
        username: str = "",
        password: str = "",
    ) -> tuple[str, str, str]:
        resolved_url = (base_url or "").strip().rstrip("/") or await ConfigService.get_global_config(
            conn, BIOTIME_CONFIG_KEYS["base_url"], "", str
        )
        resolved_url = "".join((resolved_url or "").split()).rstrip("/")
        resolved_user = (username or "").strip() or await ConfigService.get_global_config(
            conn, BIOTIME_CONFIG_KEYS["username"], "", str
        )
        resolved_pwd = (password or "").strip() or await ConfigService.get_global_config(
            conn, BIOTIME_CONFIG_KEYS["password"], "", str
        )
        return resolved_url, resolved_user, resolved_pwd

    async def update_biotime_config(
        self,
        conn,
        *,
        base_url: str,
        username: str,
        password: str,
        sync_activo: bool,
        interval_seconds: int,
        page_size: int,
        lookback_hours: int,
        timeout_seconds: int,
        recalc_days: int,
    ) -> None:
        base_url = "".join((base_url or "").split()).rstrip("/")
        username = (username or "").strip()
        resolved_password = (password or "").strip() or await ConfigService.get_global_config(
            conn, BIOTIME_CONFIG_KEYS["password"], "", str
        )

        if sync_activo and (not base_url or not username or not resolved_password):
            raise ValueError("Para activar BioTime debes configurar URL base, usuario y contraseña")
        if interval_seconds < 60:
            raise ValueError("El intervalo mínimo de sincronización es 60 segundos")
        if page_size < 1 or page_size > 1000:
            raise ValueError("El tamaño de página debe estar entre 1 y 1000")
        if lookback_hours < 1 or lookback_hours > 744:
            raise ValueError("La ventana de busqueda debe estar entre 1 y 744 horas")
        if timeout_seconds < 5 or timeout_seconds > 120:
            raise ValueError("El timeout debe estar entre 5 y 120 segundos")
        if recalc_days < 0 or recalc_days > 31:
            raise ValueError("El recálculo debe estar entre 0 y 31 días")

        updates = [
            (BIOTIME_CONFIG_KEYS["base_url"], base_url),
            (BIOTIME_CONFIG_KEYS["sync_activo"], "true" if sync_activo else "false"),
            (BIOTIME_CONFIG_KEYS["interval_seconds"], str(interval_seconds)),
            (BIOTIME_CONFIG_KEYS["page_size"], str(page_size)),
            (BIOTIME_CONFIG_KEYS["lookback_hours"], str(lookback_hours)),
            (BIOTIME_CONFIG_KEYS["timeout_seconds"], str(timeout_seconds)),
            (BIOTIME_CONFIG_KEYS["recalc_days"], str(recalc_days)),
        ]
        if username:
            updates.append((BIOTIME_CONFIG_KEYS["username"], username))
        if (password or "").strip():
            updates.append((BIOTIME_CONFIG_KEYS["password"], resolved_password))

        for clave, valor in updates:
            await self.db.upsert_global_config(conn, clave, valor)
        logger.info("Configuracion BioTime actualizada. sync_activo=%s", sync_activo)
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
                        {"label": "Solicitud Extraordinaria", "value": "EXTRAORDINARIA"},
                        {"label": "Nuevo Comentario",         "value": "NUEVO_COMENTARIO"},
                        {"label": "Cambio de Estatus",        "value": "CAMBIO_ESTATUS"},
                        {"label": "Asignación",               "value": "ASIGNACION"},
                        {"label": "Solicitud de Viáticos",    "value": "SOLICITUD_VIATICOS"},
                        {"label": "Oportunidad Ganada",       "value": "OPORTUNIDAD_GANADA"},
                        {"label": "Solicitud de vacaciones aprobada",  "value": "VACACIONES_SOLICITUD_APROBADA"},
                        {"label": "Solicitud de vacaciones rechazada", "value": "VACACIONES_SOLICITUD_RECHAZADA"},
                    ]
            # Si no existe en BD, usar fallback
            return [
                {"label": "Solicitud Extraordinaria", "value": "EXTRAORDINARIA"},
                {"label": "Nuevo Comentario",         "value": "NUEVO_COMENTARIO"},
                {"label": "Cambio de Estatus",        "value": "CAMBIO_ESTATUS"},
                {"label": "Asignación",               "value": "ASIGNACION"},
                {"label": "Solicitud de Viáticos",    "value": "SOLICITUD_VIATICOS"},
                {"label": "Oportunidad Ganada",       "value": "OPORTUNIDAD_GANADA"},
                {"label": "Solicitud de vacaciones aprobada",  "value": "VACACIONES_SOLICITUD_APROBADA"},
                {"label": "Solicitud de vacaciones rechazada", "value": "VACACIONES_SOLICITUD_RECHAZADA"},
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

    async def update_user_department(self, conn, user_id: UUID, department_slug: Optional[str]) -> Optional[str]:
        """Asigna o limpia el departamento de un usuario. None → department = NULL."""
        if not department_slug:
            await self.db.update_user_department(conn, user_id, None)
            logger.info(f"Departamento removido para usuario {user_id}")
            return None

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
        validate_module_roles(module_roles)
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

    async def update_user_levantamiento_flag(self, conn, user_id: UUID, value: bool) -> None:
        """
        Actualiza el flag puede_asignarse_levantamientos del usuario.

        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            value: Nuevo valor del flag
        """
        await self.db.update_user_levantamiento_flag(conn, user_id, value)
        logger.info(f"Flag levantamientos actualizado para usuario {user_id}: {value}")

    async def update_user_rol_organizacional(self, conn, user_id: UUID, rol: str) -> None:
        """
        Actualiza el rol organizacional del usuario.

        Args:
            conn: Conexión a la base de datos
            user_id: ID del usuario
            rol: jefe_comercial | jefe_ingenieria | jefe_construccion | director | '' (ninguno)
        """
        if rol not in ROLES_ORGANIZACIONALES_VALIDOS:
            raise ValueError(f"Rol organizacional inválido: {rol}")
        await self.db.update_user_rol_organizacional(conn, user_id, rol)
        logger.info(f"Rol organizacional actualizado para usuario {user_id}: '{rol or 'ninguno'}'")

    async def get_user_enriched_by_id(self, conn, user_id: UUID) -> Optional[Dict]:
        """Obtiene un usuario enriquecido con módulos asignados y nombre de módulo preferido."""
        user = await self.db.fetch_user_by_id(conn, user_id)
        if not user:
            return None
        permissions = await self.db.fetch_permissions_enriched_by_user(conn, user_id)
        user['user_modules'] = permissions
        if user.get('modulo_preferido'):
            nombres = await self.db.fetch_modulos_by_slugs(conn, [user['modulo_preferido']])
            user['modulo_preferido_nombre'] = nombres.get(user['modulo_preferido'])
        else:
            user['modulo_preferido_nombre'] = None
        return user

    async def save_user_all(
        self, conn, user_id: UUID,
        rol_sistema: str,
        department_slug: Optional[str],
        modulo_preferido: Optional[str],
        puede_asignarse_simulacion: bool,
        puede_asignarse_levantamientos: bool,
        rol_organizacional: str,
        module_roles: Dict[str, str],
    ) -> Dict:
        """Guarda toda la configuración de un usuario en una sola operación atómica."""
        if rol_organizacional not in ROLES_ORGANIZACIONALES_VALIDOS:
            raise ValueError(f"Rol organizacional inválido: {rol_organizacional}")
        validate_module_roles(module_roles)

        async with conn.transaction():
            if department_slug:
                dept_nombre = await self.db.fetch_department_name_by_slug(conn, department_slug)
                if not dept_nombre:
                    raise ValueError("Departamento no encontrado")
            else:
                dept_nombre = None
            await self.db.update_user_role(conn, user_id, rol_sistema)
            await self.db.update_user_department(conn, user_id, dept_nombre)
            await self.db.delete_user_permissions(conn, user_id)
            await self.db.insert_user_permissions_bulk(conn, user_id, module_roles)
            await self.db.update_user_preferred_module(conn, user_id, modulo_preferido)
            await self.db.update_user_simulation_flag(conn, user_id, puede_asignarse_simulacion)
            await self.db.update_user_levantamiento_flag(conn, user_id, puede_asignarse_levantamientos)
            await self.db.update_user_rol_organizacional(conn, user_id, rol_organizacional)
            result = await self.get_user_enriched_by_id(conn, user_id)

        logger.info("Configuracion completa guardada para usuario %s", user_id)
        return result

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

    # --- Ubicaciones ---

    async def get_ubicaciones(self, conn) -> dict:
        return {
            "sucursales": await self.db.fetch_sucursales(conn),
            "zonas_compra": await self.db.fetch_zonas_compra(conn),
        }

    async def create_sucursal(self, conn, codigo: str, nombre: str) -> None:
        codigo_clean = codigo.strip().upper()
        nombre_clean = nombre.strip()
        if not codigo_clean or not nombre_clean:
            raise ValueError("Código y nombre son requeridos")
        await self.db.insert_sucursal(conn, codigo_clean, nombre_clean)

    async def toggle_sucursal(self, conn, sucursal_id: str, current_status: bool) -> None:
        try:
            UUID(sucursal_id)
        except ValueError as exc:
            raise ValueError("ID de sucursal no valido") from exc
        await self.db.toggle_sucursal(conn, sucursal_id, not current_status)

    async def create_zona_compra(self, conn, nombre: str, orden: int) -> None:
        nombre_clean = nombre.strip()
        if not nombre_clean:
            raise ValueError("El nombre es requerido")
        await self.db.insert_zona_compra(conn, nombre_clean, orden)

    async def toggle_zona_compra(self, conn, zona_id: int, current_status: bool) -> None:
        await self.db.toggle_catalogo_status(conn, "tb_cat_zonas_compra", zona_id, not current_status)

    async def sync_ms_profiles(self, conn) -> dict:
        ms_auth = MicrosoftAuth()
        users = await self.db.fetch_users_missing_profile(conn)
        updated = 0
        skipped = 0

        for user in users:
            token_result = await ms_auth.refresh_access_token(user["refresh_token"])
            if not token_result or not token_result.get("access_token"):
                skipped += 1
                logger.warning("sync_ms_profiles: token expirado para %s", user["id_usuario"])
                continue

            new_access = token_result["access_token"]
            new_refresh = token_result.get("refresh_token") or user["refresh_token"]
            expires_at = int(time.time() + token_result.get("expires_in", 3600))

            profile = await ms_auth.get_user_profile(new_access)
            department = profile.get("department") or None
            puesto = profile.get("jobTitle") or None

            try:
                await self.db.update_user_ms_profile(
                    conn, user["id_usuario"],
                    department, puesto, new_access, new_refresh, expires_at,
                )
                updated += 1
                logger.info("sync_ms_profiles: %s — dept=%s puesto=%s", user["id_usuario"], department, puesto)
            except asyncpg.PostgresError:
                logger.error("sync_ms_profiles: error BD para %s", user["id_usuario"])
                continue

        return {"updated": updated, "skipped": skipped, "total": len(users)}

    # ========================================
    # REPORTE SEMANAL
    # ========================================

    async def generar_reporte_semanal(self, conn, fecha_inicio=None, fecha_fin=None) -> dict:
        """
        Genera los datos del reporte semanal de actividad en ECO.
        Si no se pasan fechas, usa la semana actual (lunes a viernes).
        Retorna: datos (métricas), fecha_inicio, fecha_fin (fecha_fin es exclusivo en la query).
        """
        from datetime import timedelta
        from core.timezone import today_mx

        if not fecha_inicio:
            today = today_mx()
            fecha_inicio = today - timedelta(days=today.weekday())  # Lunes
            fecha_fin = fecha_inicio + timedelta(days=5)            # Sábado (exclusivo → cubre L-V)

        datos = await self.db.get_reporte_semanal_data(conn, fecha_inicio, fecha_fin)
        return {
            "datos": datos,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
        }

    async def enviar_reporte_semanal(self, conn) -> bool:
        """
        Genera y envía el reporte semanal por correo.
        Los destinatarios se leen desde tb_configuracion_global (clave: reporte_semanal_destinatarios).
        Retorna True si el correo fue enviado, False si no hay destinatarios configurados.
        """
        from datetime import timedelta
        from core.workflow.notification_service import NotificationService
        from core.config import settings

        destinatarios_raw = await ConfigService.get_global_config(
            conn, "reporte_semanal_destinatarios", "", str
        )
        destinatarios_raw = destinatarios_raw.replace(";", ",")
        destinatarios = {e.strip() for e in destinatarios_raw.split(",") if e.strip()}

        if not destinatarios:
            logger.warning("[REPORTE_SEMANAL] Sin destinatarios configurados — correo no enviado")
            return False

        reporte = await self.generar_reporte_semanal(conn)
        fecha_inicio = reporte["fecha_inicio"]
        fecha_fin_display = reporte["fecha_fin"] - timedelta(days=1)

        notif = NotificationService()
        html = notif._render_template("shared/emails/reporte_semanal.html", {
            "datos": reporte["datos"],
            "fecha_inicio": fecha_inicio,
            "fecha_fin_display": fecha_fin_display,
            "base_url": settings.APP_BASE_URL,
        })

        subject = (
            f"Actividad en ECO — Semana del "
            f"{fecha_inicio.strftime('%d/%m')} al {fecha_fin_display.strftime('%d/%m/%Y')}"
        )

        sender = await notif._get_notification_sender(conn, "DEFAULT")
        await notif._send_email(destinatarios, set(), subject, html, sender["email"])
        logger.info(f"[REPORTE_SEMANAL] Enviado a {len(destinatarios)} destinatarios")
        return True

    async def get_recordatorios_oportunidad_monitor(self, conn) -> dict:
        """
        Retorna resumen para monitor operativo de recordatorios automáticos.
        """
        data = await self.db.get_recordatorios_oportunidad_monitor_data(conn)
        return {
            "pendientes_activos": int(data.get("pendientes_activos", 0) or 0),
            "vencidos_por_enviar": int(data.get("vencidos_por_enviar", 0) or 0),
            "enviados_total": int(data.get("enviados_total", 0) or 0),
            "no_enviados_total": int(data.get("no_enviados_total", 0) or 0),
        }


    async def get_cfe_config(self, conn) -> dict:
        user = await ConfigService.get_global_config(conn, CFE_CONFIG_KEYS["mi_user"], "", str)
        has_pass = bool(
            await ConfigService.get_global_config(conn, CFE_CONFIG_KEYS["mi_pass"], "", str)
        )
        has_session = bool(
            await ConfigService.get_global_config(conn, CFE_CONFIG_KEYS["session_json"], "", str)
        )
        token = await ConfigService.get_global_config(conn, CFE_CONFIG_KEYS["upload_token"], "", str)
        return {
            "cfe_user": user,
            "cfe_has_pass": has_pass,
            "cfe_has_session": has_session,
            "cfe_session_token": token,
        }

    async def update_cfe_config(self, conn, *, user: str, password: str) -> None:
        updates = [(CFE_CONFIG_KEYS["mi_user"], user.strip())]
        if password.strip():
            updates.append((CFE_CONFIG_KEYS["mi_pass"], password.strip()))
        for clave, valor in updates:
            await self.db.upsert_global_config(conn, clave, valor)
        ConfigService.invalidar_cache()
        logger.info("Configuración CFE MiEspacio actualizada")

    async def update_cfe_session(self, conn, *, session_json: str) -> None:
        """Guarda el state.json de MiEspacio pegado por un admin (renovacion manual de sesion)."""
        raw = session_json.strip()
        if not raw:
            raise ValueError("Pega el contenido del state.json de la sesion.")
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("El contenido pegado no es un JSON valido.")
        await self.db.upsert_global_config(conn, CFE_CONFIG_KEYS["session_json"], raw)
        ConfigService.invalidar_cache()
        logger.info("Sesion CFE MiEspacio actualizada manualmente")

    async def regenerate_cfe_token(self, conn) -> str:
        """Genera y guarda un nuevo token compartido para el lanzador local de renovacion."""
        token = secrets.token_urlsafe(32)
        await self.db.upsert_global_config(conn, CFE_CONFIG_KEYS["upload_token"], token)
        ConfigService.invalidar_cache()
        logger.info("Token de subida de sesion CFE regenerado")
        return token


def get_admin_service():
    """Helper para inyección de dependencias."""
    return AdminService()
