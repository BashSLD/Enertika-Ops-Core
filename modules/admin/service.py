# modules/admin/service.py
"""
Service Layer para el módulo Admin.
Maneja toda la lógica de negocio y queries a la base de datos.
Patrón recomendado por GUIA_MAESTRA líneas 703-833.
"""
from typing import List, Dict, Optional
from uuid import UUID
import logging

logger = logging.getLogger("AdminModule")


class AdminService:
    """Maneja toda la lógica de negocio del módulo Admin."""
    
    async def get_users_enriched(self, conn) -> List[Dict]:
        """
        Obtiene usuarios con sus módulos asignados y módulo preferido.
        
        Returns:
            List[Dict]: Lista de usuarios enriquecidos con permisos
        """
        users = await conn.fetch("SELECT * FROM tb_usuarios ORDER BY nombre")
        
        users_enriched = []
        for user in users:
            user_dict = dict(user)
            
            # Obtener módulos del usuario
            permisos = await conn.fetch(
                """SELECT pm.modulo_slug, pm.rol_modulo, mc.nombre as modulo_nombre
                   FROM tb_permisos_modulos pm
                   JOIN tb_modulos_catalogo mc ON pm.modulo_slug = mc.slug
                   WHERE pm.usuario_id = $1
                   ORDER BY mc.orden""",
                user['id_usuario']
            )
            user_dict['user_modules'] = [dict(p) for p in permisos]
            
            # Obtener nombre del módulo preferido
            if user['modulo_preferido']:
                mod_pref = await conn.fetchval(
                    "SELECT nombre FROM tb_modulos_catalogo WHERE slug = $1",
                    user['modulo_preferido']
                )
                user_dict['modulo_preferido_nombre'] = mod_pref
            else:
                user_dict['modulo_preferido_nombre'] = None
                
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
        Obtiene catálogos necesarios para el formulario de reglas de email.
        Patrón recomendado por GUIA_MAESTRA líneas 703-727.
        
        Returns:
            Dict: Catálogos de tecnologías y tipos de solicitud
        """
        tecnologias = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        )
        tipos_solicitud = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        )
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos_solicitud]
        }
    
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


def get_admin_service():
    """Helper para inyección de dependencias."""
    return AdminService()
