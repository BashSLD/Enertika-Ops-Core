"""
Módulo de Permisos y Control de Acceso
Sistema de validación de permisos basado en módulos y roles
"""
from fastapi import Depends, HTTPException, status
from typing import Callable
from core.security import get_current_user_context

# Jerarquía de roles (de menor a mayor privilegio)
ROLE_HIERARCHY = {
    "viewer": 1,    # Solo lectura
    "editor": 2,    # Lectura + edición
    "assignor": 3,  # Lectura + edición + asignación
    "admin": 4      # Control total del módulo
}


def require_module_access(module_slug: str, min_role: str = "viewer") -> Callable:
    """
    Dependency factory para validar acceso a un módulo.
    
    Args:
        module_slug: Slug del módulo (ej: "comercial", "simulacion")
        min_role: Rol mínimo requerido ("viewer", "editor", "assignor", "admin")
    
    Returns:
        Dependency function que valida el acceso
        
    Raises:
        HTTPException 403: Si el usuario no tiene acceso o rol insuficiente
    
    Ejemplo de uso:
        @router.get("/comercial/ui")
        async def comercial_ui(
            context = Depends(get_current_user_context),
            _ = Depends(require_module_access("comercial", "viewer"))
        ):
            # Solo se ejecuta si el usuario tiene acceso
            ...
    """
    async def _validate(context = Depends(get_current_user_context)):
        # Los ADMIN siempre tienen acceso total
        if context.get("role") == "ADMIN":
            return True
        
        module_roles = context.get("module_roles", {})
        
        # Verificar si tiene el módulo asignado
        if module_slug not in module_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes acceso al módulo '{module_slug}'. Contacta al administrador."
            )
        
        # Verificar rol mínimo
        user_role = module_roles[module_slug]
        user_role_level = ROLE_HIERARCHY.get(user_role, 0)
        min_role_level = ROLE_HIERARCHY.get(min_role, 0)
        
        if user_role_level < min_role_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requieres permisos de '{min_role}' o superior en este módulo. Tu rol actual: '{user_role}'"
            )
        
        return True
    
    return Depends(_validate)


def get_user_module_role(module_slug: str, context: dict) -> str:
    """
    Obtiene el rol del usuario en un módulo específico.
    
    Args:
        module_slug: Slug del módulo
        context: Contexto del usuario (retornado por get_current_user_context)
    
    Returns:
        Rol del usuario en el módulo ("viewer", "editor", "assignor", "admin")
        Si es ADMIN del sistema, retorna "admin"
        Si no tiene acceso, retorna cadena vacía ""
    """
    if context.get("role") == "ADMIN":
        return "admin"
    
    module_roles = context.get("module_roles", {})
    return module_roles.get(module_slug, "")


def user_has_module_access(module_slug: str, context: dict, min_role: str = "viewer") -> bool:
    """
    Verifica si un usuario tiene acceso a un módulo con un rol mínimo.
    
    Args:
        module_slug: Slug del módulo
        context: Contexto del usuario
        min_role: Rol mínimo requerido
    
    Returns:
        True si tiene acceso con el rol mínimo, False en caso contrario
    """
    if context.get("role") == "ADMIN":
        return True
    
    user_role = get_user_module_role(module_slug, context)
    
    if not user_role:
        return False
    
    user_role_level = ROLE_HIERARCHY.get(user_role, 0)
    min_role_level = ROLE_HIERARCHY.get(min_role, 0)
    
    return user_role_level >= min_role_level


def get_module_permissions(module_slug: str, context: dict) -> dict:
    """
    Obtiene un diccionario con los permisos del usuario en un módulo.
    
    Args:
        module_slug: Slug del módulo
        context: Contexto del usuario
    
    Returns:
        Dict con permisos: {"can_view": bool, "can_edit": bool, "can_assign": bool, "is_admin": bool}
    """
    user_role = get_user_module_role(module_slug, context)
    
    if not user_role:
        return {
            "can_view": False,
            "can_edit": False,
            "can_assign": False,
            "is_admin": False
        }
    
    role_level = ROLE_HIERARCHY.get(user_role, 0)
    
    return {
        "can_view": role_level >= ROLE_HIERARCHY["viewer"],
        "can_edit": role_level >= ROLE_HIERARCHY["editor"],
        "can_assign": role_level >= ROLE_HIERARCHY["assignor"],
        "is_admin": role_level >= ROLE_HIERARCHY["admin"]
    }
