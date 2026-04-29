"""
Tests para la logica de permisos (core/permissions.py).
Pruebas puras de logica de roles — sin BD ni HTTP.
"""
import pytest

from core.permissions import (
    ROLE_HIERARCHY,
    get_user_module_role,
    user_has_module_access,
)


# ============================
# Tests de jerarquia de roles
# ============================

class TestRoleHierarchy:

    def test_viewer_is_lowest(self):
        assert ROLE_HIERARCHY["viewer"] < ROLE_HIERARCHY["editor"]
        assert ROLE_HIERARCHY["viewer"] < ROLE_HIERARCHY["admin"]

    def test_editor_is_middle(self):
        assert ROLE_HIERARCHY["editor"] > ROLE_HIERARCHY["viewer"]
        assert ROLE_HIERARCHY["editor"] < ROLE_HIERARCHY["admin"]

    def test_admin_is_highest(self):
        assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["editor"]
        assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["viewer"]


# ============================
# Tests de get_user_module_role
# ============================

class TestGetUserModuleRole:

    def test_admin_global_gets_admin_role(self, admin_context):
        role = get_user_module_role("comercial", admin_context)
        assert role == "admin"

    def test_admin_global_any_module(self, admin_context):
        role = get_user_module_role("modulo_inexistente", admin_context)
        assert role == "admin"

    def test_user_with_module_role(self, user_context):
        role = get_user_module_role("comercial", user_context)
        assert role == "viewer"

    def test_user_without_module_role(self, user_context):
        role = get_user_module_role("simulacion", user_context)
        assert role == ""

    def test_manager_with_specific_roles(self, manager_context):
        assert get_user_module_role("comercial", manager_context) == "editor"
        assert get_user_module_role("simulacion", manager_context) == "admin"


# ============================
# Tests de user_has_module_access
# ============================

class TestUserHasModuleAccess:

    def test_admin_always_has_access(self, admin_context):
        assert user_has_module_access("comercial", admin_context, "admin") is True
        assert user_has_module_access("cualquier_modulo", admin_context, "admin") is True

    def test_user_viewer_can_view(self, user_context):
        assert user_has_module_access("comercial", user_context, "viewer") is True

    def test_user_viewer_cannot_edit(self, user_context):
        assert user_has_module_access("comercial", user_context, "editor") is False

    def test_user_viewer_cannot_admin(self, user_context):
        assert user_has_module_access("comercial", user_context, "admin") is False

    def test_user_no_module_access(self, user_context):
        assert user_has_module_access("simulacion", user_context, "viewer") is False

    def test_manager_editor_can_edit(self, manager_context):
        assert user_has_module_access("comercial", manager_context, "editor") is True

    def test_manager_editor_cannot_admin(self, manager_context):
        assert user_has_module_access("comercial", manager_context, "admin") is False

    def test_manager_module_admin_can_admin(self, manager_context):
        assert user_has_module_access("simulacion", manager_context, "admin") is True

    def test_empty_context_no_access(self):
        empty_ctx = {"role": "USER", "module_roles": {}}
        assert user_has_module_access("comercial", empty_ctx, "viewer") is False
