from typing import Mapping

from .constants import ROLES_MODULO_VALIDOS


def extract_module_roles(form_data) -> dict[str, str]:
    """Extrae permisos de modulo sin mezclar campos de configuracion general."""
    module_roles = {}
    for key, value in form_data.items():
        if not key.startswith("modulo_") or key == "modulo_preferido" or not value:
            continue
        module_slug = key.removeprefix("modulo_")
        if module_slug:
            module_roles[module_slug] = value
    return module_roles


def validate_module_roles(module_roles: Mapping[str, str]) -> None:
    invalid_roles = sorted(
        {rol for rol in module_roles.values() if rol not in ROLES_MODULO_VALIDOS}
    )
    if invalid_roles:
        raise ValueError(f"Rol de modulo invalido: {', '.join(invalid_roles)}")
