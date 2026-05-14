# modules/admin/db_service.py
"""
Capa de Acceso a Datos para el Modulo Admin.
Todas las queries SQL puras reciben conn como primer parametro.
"""
from typing import List, Dict, Optional
from uuid import UUID
import logging

logger = logging.getLogger("Admin.DBService")


class AdminDBService:
    """Capa de Acceso a Datos para el Modulo Admin."""

    # ========================================
    # USUARIOS
    # ========================================

    async def fetch_all_users(self, conn) -> List[dict]:
        """Obtiene todos los usuarios ordenados por nombre."""
        rows = await conn.fetch("SELECT * FROM tb_usuarios ORDER BY nombre")
        return [dict(r) for r in rows]

    async def fetch_all_permissions(self, conn) -> List[dict]:
        """Obtiene todos los permisos de modulo con JOIN a catalogo de modulos."""
        rows = await conn.fetch("""
            SELECT pm.usuario_id, pm.modulo_slug, pm.rol_modulo, mc.nombre as modulo_nombre
            FROM tb_permisos_modulos pm
            JOIN tb_cat_modulos mc ON pm.modulo_slug = mc.slug
            ORDER BY mc.orden
        """)
        return [dict(r) for r in rows]

    async def fetch_modulos_by_slugs(self, conn, slugs: List[str]) -> Dict[str, str]:
        """Obtiene nombres de modulos por lista de slugs.

        Returns:
            Dict con slug -> nombre
        """
        if not slugs:
            return {}
        rows = await conn.fetch(
            "SELECT slug, nombre FROM tb_cat_modulos WHERE slug = ANY($1)",
            slugs
        )
        return {row['slug']: row['nombre'] for row in rows}

    async def fetch_user_by_id(self, conn, user_id: UUID) -> Optional[dict]:
        """Obtiene un usuario por su ID."""
        row = await conn.fetchrow(
            "SELECT * FROM tb_usuarios WHERE id_usuario = $1",
            user_id
        )
        return dict(row) if row else None

    async def update_user_role(self, conn, user_id: UUID, role: str) -> None:
        """Actualiza el rol de sistema de un usuario."""
        await conn.execute(
            "UPDATE tb_usuarios SET rol_sistema = $1 WHERE id_usuario = $2",
            role, user_id
        )

    async def update_user_department(self, conn, user_id: UUID, department_name: Optional[str]) -> None:
        """Actualiza el departamento de un usuario."""
        await conn.execute(
            "UPDATE tb_usuarios SET department = $1 WHERE id_usuario = $2",
            department_name, user_id
        )

    async def update_user_preferred_module(self, conn, user_id: UUID, modulo_slug: Optional[str]) -> None:
        """Establece el modulo preferido del usuario."""
        await conn.execute(
            "UPDATE tb_usuarios SET modulo_preferido = $1 WHERE id_usuario = $2",
            modulo_slug, user_id
        )

    async def update_user_simulation_flag(self, conn, user_id: UUID, value: bool) -> None:
        """Actualiza el flag puede_asignarse_simulacion del usuario."""
        await conn.execute(
            "UPDATE tb_usuarios SET puede_asignarse_simulacion = $1 WHERE id_usuario = $2",
            value, user_id
        )

    async def update_user_levantamiento_flag(self, conn, user_id: UUID, value: bool) -> None:
        """Actualiza el flag puede_asignarse_levantamientos del usuario."""
        await conn.execute(
            "UPDATE tb_usuarios SET puede_asignarse_levantamientos = $1 WHERE id_usuario = $2",
            value, user_id
        )

    async def update_user_rol_organizacional(self, conn, user_id: UUID, rol: str) -> None:
        """Actualiza el rol organizacional del usuario (jefe_comercial, jefe_ingenieria, jefe_construccion, director, o NULL)."""
        valor = rol if rol else None
        await conn.execute(
            "UPDATE tb_usuarios SET rol_organizacional = $1 WHERE id_usuario = $2",
            valor, user_id
        )

    async def deactivate_user(self, conn, user_id: UUID) -> None:
        """Marca un usuario como inactivo (soft delete)."""
        await conn.execute(
            "UPDATE tb_usuarios SET is_active = FALSE WHERE id_usuario = $1",
            user_id
        )

    async def reactivate_user(self, conn, user_id: UUID) -> None:
        """Marca un usuario como activo."""
        await conn.execute(
            "UPDATE tb_usuarios SET is_active = TRUE WHERE id_usuario = $1",
            user_id
        )

    # ========================================
    # PERMISOS DE MODULO
    # ========================================

    async def fetch_user_permissions(self, conn, user_id: UUID) -> List[dict]:
        """Obtiene los permisos de modulo de un usuario."""
        rows = await conn.fetch(
            "SELECT modulo_slug, rol_modulo FROM tb_permisos_modulos WHERE usuario_id = $1",
            user_id
        )
        return [dict(r) for r in rows]

    async def delete_user_permissions(self, conn, user_id: UUID) -> None:
        """Elimina todos los permisos de modulo de un usuario."""
        await conn.execute(
            "DELETE FROM tb_permisos_modulos WHERE usuario_id = $1",
            user_id
        )

    async def insert_user_permission(self, conn, user_id: UUID, module_slug: str, rol: str) -> None:
        """Inserta un permiso de modulo para un usuario."""
        await conn.execute(
            """INSERT INTO tb_permisos_modulos (usuario_id, modulo_slug, rol_modulo)
               VALUES ($1, $2, $3)""",
            user_id, module_slug, rol
        )

    # ========================================
    # CATALOGOS (Departamentos, Modulos)
    # ========================================

    async def fetch_departments_catalog(self, conn) -> List[dict]:
        """Obtiene catalogo de departamentos activos."""
        rows = await conn.fetch(
            "SELECT id, nombre, slug FROM tb_cat_departamentos WHERE is_active = true ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def fetch_department_name_by_slug(self, conn, slug: str) -> Optional[str]:
        """Obtiene el nombre de un departamento por su slug."""
        return await conn.fetchval(
            "SELECT nombre FROM tb_cat_departamentos WHERE slug = $1",
            slug
        )

    async def fetch_modules_catalog(self, conn) -> List[dict]:
        """Obtiene catalogo de modulos activos."""
        rows = await conn.fetch(
            "SELECT id, nombre, slug, icono FROM tb_cat_modulos WHERE is_active = true ORDER BY orden"
        )
        return [dict(r) for r in rows]

    # ========================================
    # REGLAS DE CORREO
    # ========================================

    async def fetch_email_rules(self, conn) -> List[dict]:
        """Obtiene todas las reglas de correo configuradas."""
        rows = await conn.fetch(
            "SELECT * FROM tb_config_emails ORDER BY modulo, trigger_field"
        )
        return [dict(r) for r in rows]

    async def insert_email_rule(
        self, conn, modulo: str, trigger_field: str,
        trigger_value: str, email_to_add: str, type: str
    ) -> None:
        """Inserta una nueva regla de correo."""
        await conn.execute(
            """INSERT INTO tb_config_emails
               (modulo, trigger_field, trigger_value, email_to_add, type)
               VALUES ($1, $2, $3, $4, $5)""",
            modulo, trigger_field, trigger_value, email_to_add, type
        )

    async def delete_email_rule(self, conn, rule_id: int) -> None:
        """Elimina una regla de correo por ID."""
        await conn.execute(
            "DELETE FROM tb_config_emails WHERE id = $1",
            rule_id
        )

    # ========================================
    # EMAIL DEFAULTS
    # ========================================

    async def fetch_email_defaults(self, conn) -> Optional[dict]:
        """Obtiene la configuracion global de correos (defaults)."""
        row = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
        return dict(row) if row else None

    async def ensure_email_defaults_row(self, conn) -> None:
        """Asegura que exista la fila ID=1 en tb_email_defaults."""
        row = await conn.fetchrow("SELECT id FROM tb_email_defaults WHERE id = 1")
        if not row:
            await conn.execute(
                "INSERT INTO tb_email_defaults (id, default_to, default_cc, default_cco) VALUES (1, '', '', '')"
            )

    async def update_email_defaults(
        self, conn, default_to: str, default_cc: str, default_cco: str
    ) -> None:
        """Actualiza la configuracion global de correos."""
        await conn.execute(
            """UPDATE tb_email_defaults
               SET default_to = $1, default_cc = $2, default_cco = $3
               WHERE id = 1""",
            default_to, default_cc, default_cco
        )

    async def fetch_email_remitente_default(self, conn) -> Optional[str]:
        """Obtiene el remitente por defecto de tb_correos_notificaciones."""
        return await conn.fetchval(
            "SELECT email_remitente FROM tb_correos_notificaciones "
            "WHERE departamento = 'DEFAULT' AND activo = true LIMIT 1"
        )

    # ========================================
    # CONFIGURACION GLOBAL
    # ========================================

    async def fetch_fiel_config(self, conn) -> dict:
        """Obtiene la config FIEL activa para ISA, o dict vacío si no existe."""
        row = await conn.fetchrow(
            "SELECT sp_path_cer, sp_path_key, password_fiel FROM tb_sat_fiel_config WHERE empresa='ISA' AND activo=TRUE"
        )
        return dict(row) if row else {}

    async def guardar_fiel_config(
        self, conn, sp_path_cer: str, sp_path_key: str, password_fiel: str
    ) -> None:
        """Guarda o actualiza la configuración FIEL de ISA."""
        await conn.execute(
            """
            INSERT INTO tb_sat_fiel_config (empresa, sp_path_cer, sp_path_key, password_fiel, activo)
            VALUES ('ISA', $1, $2, $3, TRUE)
            ON CONFLICT (empresa) WHERE activo = TRUE
            DO UPDATE SET sp_path_cer=$1, sp_path_key=$2, password_fiel=$3, updated_at=NOW()
            """,
            sp_path_cer, sp_path_key, password_fiel,
        )

    async def fetch_global_config(self, conn) -> Dict[str, str]:
        """Obtiene toda la configuracion global como dict clave->valor."""
        rows = await conn.fetch("SELECT clave, valor FROM tb_configuracion_global")
        return {row['clave']: row['valor'] for row in rows}

    async def upsert_global_config(self, conn, clave: str, valor: str) -> None:
        """Inserta o actualiza un par clave-valor en configuracion global."""
        await conn.execute(
            """INSERT INTO tb_configuracion_global (clave, valor)
               VALUES ($1, $2)
               ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor""",
            clave, valor
        )

    async def delete_global_config_keys(self, conn, keys: List[str]) -> None:
        """Elimina claves de configuracion global."""
        await conn.execute(
            "DELETE FROM tb_configuracion_global WHERE clave = ANY($1)",
            keys
        )

    # ========================================
    # TRIGGER OPTIONS (Opciones dinamicas)
    # ========================================

    async def fetch_tecnologias_options(self, conn) -> List[dict]:
        """Obtiene opciones de tecnologias para trigger de reglas."""
        rows = await conn.fetch(
            "SELECT nombre as label, CAST(id AS TEXT) as value FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def fetch_tipos_solicitud_options(self, conn) -> List[dict]:
        """Obtiene opciones de tipos de solicitud para trigger de reglas."""
        rows = await conn.fetch(
            "SELECT nombre as label, CAST(id AS TEXT) as value FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def fetch_estatus_options(self, conn) -> List[dict]:
        """Obtiene opciones de estatus global para trigger de reglas."""
        rows = await conn.fetch(
            "SELECT nombre as label, CAST(id AS TEXT) as value FROM tb_cat_estatus_oportunidades WHERE activo = true ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def fetch_eventos_sistema_config(self, conn) -> Optional[str]:
        """Obtiene el JSON de eventos del sistema desde configuracion global."""
        return await conn.fetchval(
            "SELECT valor FROM tb_configuracion_global WHERE clave = 'EVENTOS_SISTEMA'"
        )

    # ========================================
    # CATALOGOS DE REGLAS (Tecnologias, Tipos, Estatus, Origenes)
    # ========================================

    async def fetch_catalogo_tecnologias(self, conn) -> List[dict]:
        """Obtiene catalogo completo de tecnologias activas."""
        rows = await conn.fetch(
            "SELECT id, nombre, activo FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def fetch_catalogo_tipos_solicitud(self, conn) -> List[dict]:
        """Obtiene catalogo completo de tipos de solicitud activos."""
        rows = await conn.fetch(
            "SELECT id, nombre, codigo_interno, activo FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def fetch_catalogo_estatus(self, conn) -> List[dict]:
        """Obtiene catalogo completo de estatus global activos."""
        rows = await conn.fetch(
            "SELECT id, nombre, descripcion, color_hex, activo FROM tb_cat_estatus_oportunidades WHERE activo = true ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def fetch_catalogo_origenes_adjuntos(self, conn) -> List[dict]:
        """Obtiene catalogo completo de origenes de adjuntos activos."""
        rows = await conn.fetch(
            "SELECT id, slug, descripcion, activo FROM tb_cat_origenes_adjuntos WHERE activo = true ORDER BY slug"
        )
        return [dict(r) for r in rows]

    # ========================================
    # GESTION DE CATALOGOS (CRUD)
    # ========================================

    # --- Tecnologias ---

    async def check_tecnologia_exists(self, conn, nombre: str) -> bool:
        """Verifica si una tecnologia ya existe (case-insensitive)."""
        exists = await conn.fetchval(
            "SELECT 1 FROM tb_cat_tecnologias WHERE nombre ILIKE $1",
            nombre
        )
        return bool(exists)

    async def insert_tecnologia(self, conn, nombre: str) -> None:
        """Inserta una nueva tecnologia."""
        await conn.execute(
            "INSERT INTO tb_cat_tecnologias (nombre, activo) VALUES ($1, true)",
            nombre
        )

    async def update_tecnologia(self, conn, id_tech: int, nombre: str, activo: bool) -> None:
        """Actualiza nombre y estado de una tecnologia."""
        await conn.execute(
            "UPDATE tb_cat_tecnologias SET nombre = $1, activo = $2 WHERE id = $3",
            nombre, activo, id_tech
        )

    # --- Tipos de Solicitud ---

    async def insert_tipo_solicitud(self, conn, nombre: str, codigo_interno: str) -> None:
        """Inserta un nuevo tipo de solicitud."""
        await conn.execute(
            "INSERT INTO tb_cat_tipos_solicitud (nombre, codigo_interno, activo) VALUES ($1, $2, true)",
            nombre, codigo_interno
        )

    async def fetch_tipo_solicitud_codigo(self, conn, id_tipo: int) -> Optional[str]:
        """Obtiene el codigo interno actual de un tipo de solicitud."""
        return await conn.fetchval(
            "SELECT codigo_interno FROM tb_cat_tipos_solicitud WHERE id = $1",
            id_tipo
        )

    async def update_tipo_solicitud(
        self, conn, id_tipo: int, nombre: str, codigo: str, activo: bool
    ) -> None:
        """Actualiza un tipo de solicitud."""
        await conn.execute(
            """UPDATE tb_cat_tipos_solicitud
               SET nombre = $1, codigo_interno = $2, activo = $3
               WHERE id = $4""",
            nombre, codigo, activo, id_tipo
        )

    # --- Estatus Global ---

    async def insert_estatus(self, conn, nombre: str, descripcion: str, color: str) -> None:
        """Inserta un nuevo estatus global."""
        await conn.execute(
            "INSERT INTO tb_cat_estatus_oportunidades (nombre, descripcion, color_hex, activo) VALUES ($1, $2, $3, true)",
            nombre, descripcion, color
        )

    # --- Origenes de Adjuntos ---

    async def check_origen_adjunto_exists(self, conn, slug: str) -> bool:
        """Verifica si un origen de adjunto ya existe."""
        exists = await conn.fetchval(
            "SELECT 1 FROM tb_cat_origenes_adjuntos WHERE slug = $1",
            slug
        )
        return bool(exists)

    async def insert_origen_adjunto(self, conn, slug: str, descripcion: str) -> None:
        """Inserta un nuevo origen de adjunto."""
        await conn.execute(
            "INSERT INTO tb_cat_origenes_adjuntos (slug, descripcion, activo) VALUES ($1, $2, true)",
            slug, descripcion
        )

    # --- Toggle Generico ---

    # Whitelist de tablas permitidas para toggle generico (previene SQL injection)
    ALLOWED_TOGGLE_TABLES = frozenset({
        "tb_cat_tecnologias",
        "tb_cat_tipos_solicitud",
        "tb_cat_estatus_oportunidades",
        "tb_cat_origenes_adjuntos",
        "tb_cat_zonas_compra",
    })

    async def toggle_catalogo_status(self, conn, table: str, item_id: int, new_status: bool) -> None:
        """Toggle generico de activo/inactivo para tablas de catalogo.

        Valida tabla contra whitelist para prevenir SQL injection.

        Args:
            conn: Conexion a la base de datos
            table: Nombre de la tabla (debe estar en ALLOWED_TOGGLE_TABLES)
            item_id: ID del registro
            new_status: Nuevo valor de activo

        Raises:
            ValueError: Si la tabla no esta en la whitelist
        """
        if not isinstance(table, str) or table not in self.ALLOWED_TOGGLE_TABLES:
            raise ValueError(f"Tabla no permitida: {table}")

        await conn.execute(
            f"UPDATE {table} SET activo = $1 WHERE id = $2",
            new_status, item_id
        )

    # ========================================
    # UBICACIONES (Sucursales + Zonas de Compra)
    # ========================================

    async def fetch_sucursales(self, conn) -> list:
        rows = await conn.fetch(
            "SELECT id, codigo, nombre, activa FROM tb_cat_sucursales ORDER BY nombre"
        )
        return [dict(r) for r in rows]

    async def insert_sucursal(self, conn, codigo: str, nombre: str) -> None:
        await conn.execute(
            "INSERT INTO tb_cat_sucursales (id, codigo, nombre, activa) VALUES (gen_random_uuid(), $1, $2, true)",
            codigo, nombre,
        )

    async def toggle_sucursal(self, conn, sucursal_id: str, new_status: bool) -> None:
        await conn.execute(
            "UPDATE tb_cat_sucursales SET activa = $1 WHERE id = $2::uuid",
            new_status, sucursal_id,
        )

    async def fetch_zonas_compra(self, conn) -> list:
        rows = await conn.fetch(
            "SELECT id, nombre, activo, orden FROM tb_cat_zonas_compra ORDER BY orden, nombre"
        )
        return [dict(r) for r in rows]

    async def insert_zona_compra(self, conn, nombre: str, orden: int) -> None:
        await conn.execute(
            "INSERT INTO tb_cat_zonas_compra (nombre, activo, orden) VALUES ($1, true, $2)",
            nombre, orden,
        )

    async def fetch_users_missing_profile(self, conn) -> list:
        rows = await conn.fetch("""
            SELECT id_usuario, refresh_token
            FROM tb_usuarios
            WHERE is_active = TRUE
              AND refresh_token IS NOT NULL
              AND (puesto IS NULL OR department IS NULL)
        """)
        return [dict(r) for r in rows]

    async def update_user_ms_profile(
        self, conn, user_id: UUID,
        department: Optional[str], puesto: Optional[str],
        access_token: str, refresh_token: str, token_expires_at: int,
    ) -> None:
        await conn.execute("""
            UPDATE tb_usuarios
            SET department       = COALESCE($2, department),
                puesto           = COALESCE($3, puesto),
                access_token     = $4,
                refresh_token    = $5,
                token_expires_at = $6
            WHERE id_usuario = $1
        """, user_id, department, puesto, access_token, refresh_token, token_expires_at)

    # ========================================
    # CONFIGURACION UMBRALES KPI
    # ========================================

    async def update_umbrales_kpi(
        self, conn, tipo_kpi: str, departamento: str,
        umbral_excelente: int, umbral_bueno: int, modificado_por_id: UUID
    ) -> None:
        async with conn.transaction():
            await conn.execute("""
                UPDATE tb_config_umbrales_kpi
                SET activo = FALSE
                WHERE tipo_kpi = $1
                  AND activo = TRUE
                  AND departamento = $2
            """, tipo_kpi, departamento)

            await conn.execute("""
                INSERT INTO tb_config_umbrales_kpi (
                    tipo_kpi,
                    departamento,
                    umbral_excelente,
                    umbral_bueno,
                    modificado_por_id,
                    fecha_modificacion
                ) VALUES ($1, $2, $3, $4, $5, NOW())
            """, tipo_kpi, departamento, umbral_excelente, umbral_bueno, modificado_por_id)

    # ========================================
    # REPORTE SEMANAL
    # ========================================

    async def get_reporte_semanal_data(self, conn, fecha_inicio, fecha_fin) -> dict:
        """
        Obtiene métricas de actividad para el rango de fechas indicado.
        fecha_inicio y fecha_fin son objetos date (inicio inclusivo, fin exclusivo).
        """
        row = await conn.fetchrow("""
            SELECT
              (SELECT COUNT(*) FROM tb_oportunidades
               WHERE fecha_creacion >= $1 AND fecha_creacion < $2
              ) AS nuevas_oportunidades,

              (SELECT COUNT(*) FROM tb_oportunidades o
               JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
               WHERE e.es_estatus_final = false
                 AND e.modulo_aplicable = 'SIMULACION'
              ) AS en_simulacion_activas,

              (SELECT COUNT(*) FROM tb_levantamientos
               WHERE fecha_solicitud >= $1 AND fecha_solicitud < $2
              ) AS levantamientos_semana,

              (SELECT COUNT(*) FROM tb_levantamientos l
               JOIN tb_cat_estatus_levantamiento e ON l.id_estatus_global = e.id
               WHERE e.es_estatus_final = false
              ) AS levantamientos_activos,

              (SELECT COUNT(*) FROM tb_oportunidades) AS total_oportunidades
        """, fecha_inicio, fecha_fin)
        return dict(row)

    async def get_recordatorios_oportunidad_monitor_data(self, conn) -> dict:
        """
        Obtiene métricas de monitor para recordatorios automáticos de oportunidades ganadas.
        """
        row = await conn.fetchrow(
            """
            SELECT
              (
                SELECT COUNT(*)
                FROM tb_recordatorios_oportunidad_ganada r
                WHERE r.activo = TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM tb_proyectos_gate p
                    WHERE p.id_oportunidad = r.id_oportunidad
                  )
              ) AS pendientes_activos,
              (
                SELECT COUNT(*)
                FROM tb_recordatorios_oportunidad_ganada r
                WHERE r.activo = TRUE
                  AND r.proximo_recordatorio_at <= NOW()
                  AND NOT EXISTS (
                    SELECT 1
                    FROM tb_proyectos_gate p
                    WHERE p.id_oportunidad = r.id_oportunidad
                  )
              ) AS vencidos_por_enviar,
              (
                SELECT COUNT(*)
                FROM tb_recordatorios_oportunidad_ganada_log
                WHERE status = 'ENVIADO'
              ) AS enviados_total,
              (
                SELECT COUNT(*)
                FROM tb_recordatorios_oportunidad_ganada_log
                WHERE status = 'NO_ENVIADO'
              ) AS no_enviados_total
            """
        )
        return dict(row)


def get_admin_db_service() -> AdminDBService:
    """Helper para inyeccion de dependencias."""
    return AdminDBService()
