import pytest
from starlette.datastructures import FormData

from modules.admin.permission_utils import extract_module_roles, validate_module_roles


def test_extract_module_roles_ignores_preferred_module():
    form_data = FormData(
        [
            ("modulo_comercial", "editor"),
            ("modulo_preferido", "comercial"),
            ("modulo_simulacion", ""),
        ]
    )

    assert extract_module_roles(form_data) == {"comercial": "editor"}


def test_validate_module_roles_rejects_invalid_role():
    with pytest.raises(ValueError, match="Rol de modulo invalido: comercial"):
        validate_module_roles({"preferido": "comercial"})
