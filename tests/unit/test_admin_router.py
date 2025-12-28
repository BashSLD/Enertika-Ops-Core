import pytest
from fastapi.testclient import TestClient


class TestAdminRouter:
    """Tests para endpoints del módulo admin."""
    
    def test_admin_dashboard_requires_auth(self, client):
        """Verifica que /admin/ui requiera autenticación."""
        # Sin autenticación debe redirigir o retornar 401/403
        response = client.get("/admin/ui")
        
        # Puede ser redirect (307) o unauthorized (401) dependiendo de configuración
        assert response.status_code in [307, 401, 403]
    
    def test_admin_dashboard_loads_with_auth(self, client_admin):
        """Verifica que el dashboard cargue correctamente para admin."""
        response = client_admin.get("/admin/ui")
        
        assert response.status_code == 200
        assert "Panel de Administración" in response.text
        assert "Usuarios y Roles" in response.text
    
    def test_update_user_role_requires_admin(self, client_user):
        """Verifica que solo ADMIN/MANAGER puedan cambiar roles."""
        response = client_user.post(
            "/admin/users/role",
            data={
                "user_id": "test-uuid",
                "role": "ADMIN"
            }
        )
        
        # Usuario normal no puede cambiar roles
        assert response.status_code == 403
    
    def test_update_user_role_success_as_admin(self, client_admin, mock_db_conn):
        """Verifica que ADMIN pueda cambiar roles."""
        response = client_admin.post(
            "/admin/users/role",
            data={
                "user_id": "test-uuid",
                "role": "MANAGER"
            }
        )
        
        # Admin puede cambiar roles
        assert response.status_code == 200
        assert "Rol actualizado" in response.text
    
    def test_delete_user_soft_delete(self, client_admin, mock_db_conn):
        """Verifica que DELETE no borre físicamente el usuario."""
        user_id = "test-uuid-123"
        
        # Mock: usuario después de soft delete
        mock_db_conn.set_fetchrow_result({
            'id_usuario': user_id,
            'nombre': 'Test User',
            'is_active': False
        })
        
        response = client_admin.delete(f"/admin/users/{user_id}")
        
        assert response.status_code == 200
        # Debe retornar la fila actualizada (partial)
        assert "Test User" in response.text
        # Verificar que NO se hizo DELETE físico
        assert not mock_db_conn.execute_called_with_pattern('DELETE FROM tb_usuarios')
        # Verificar que SÍ se hizo UPDATE
        assert mock_db_conn.execute_called_with_pattern('UPDATE tb_usuarios SET is_active = FALSE')
    
    def test_restore_user_reactivates(self, client_admin, mock_db_conn):
        """Verifica que POST /restore reactive un usuario."""
        user_id = "test-uuid-456"
        
        # Mock: usuario después de reactivar
        mock_db_conn.set_fetchrow_result({
            'id_usuario': user_id,
            'nombre': 'Restored User',
            'is_active': True
        })
        
        response = client_admin.post(f"/admin/users/{user_id}/restore")
        
        assert response.status_code == 200
        assert "Restored User" in response.text
        # Verificar UPDATE a TRUE
        assert mock_db_conn.execute_called_with_pattern('UPDATE tb_usuarios SET is_active = TRUE')
    
    def test_add_email_rule_requires_admin(self, client_user):
        """Verifica que solo ADMIN/MANAGER puedan agregar reglas."""
        response = client_user.post(
            "/admin/rules/add",
            data={
                "modulo": "COMERCIAL",
                "trigger_field": "tipo_tecnologia",
                "trigger_value": "BESS",
                "email_to_add": "test@enertika.mx",
                "type": "CC"
            }
        )
        
        assert response.status_code == 403
    
    def test_delete_email_rule_success(self, client_admin, mock_db_conn):
        """Verifica que las reglas se puedan eliminar."""
        rule_id = 123
        
        response = client_admin.delete(f"/admin/rules/{rule_id}")
        
        assert response.status_code == 200
        # Verificar que se llamó al service para eliminar
        assert mock_db_conn.execute_called_with_pattern('DELETE FROM tb_config_emails')
    
    def test_update_email_defaults_success(self, client_admin, mock_db_conn):
        """Verifica actualización de configuración global de emails."""
        response = client_admin.post(
            "/admin/defaults/update",
            data={
                "default_to": "admin@enertika.mx",
                "default_cc": "backup@enertika.mx",
                "default_cco": "log@enertika.mx"
            }
        )
        
        assert response.status_code == 200
        assert "Configuración Actualizada" in response.text
    
    def test_update_user_modules_replaces_permissions(self, client_admin, mock_db_conn):
        """Verifica que actualizar módulos borre los anteriores primero."""
        user_id = "test-uuid-789"
        
        response = client_admin.post(
            f"/admin/users/{user_id}/modules",
            data={
                "modulo_comercial": "editor",
                "modulo_admin": "viewer"
            }
        )
        
        assert response.status_code == 200
        # Verificar que primero eliminó permisos anteriores
        assert mock_db_conn.execute_called_with_pattern('DELETE FROM tb_permisos_modulos')
        # Luego insertó los nuevos
        assert mock_db_conn.execute_called_with_pattern('INSERT INTO tb_permisos_modulos')
