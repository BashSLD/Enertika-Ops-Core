import pytest
from modules.admin.service import AdminService
from uuid import uuid4, UUID


class TestAdminService:
    """Tests para el service layer del módulo admin."""
    
    @pytest.mark.asyncio
    async def test_deactivate_user(self, mock_db_conn):
        """Verifica que deactivate_user haga soft-delete correctamente."""
        service = AdminService()
        user_id = uuid4()
        
        # Mock de usuario desactivado
        mock_db_conn.set_fetchrow_result({
            'id_usuario': str(user_id),
            'nombre': 'Test User',
            'email': 'test@enertika.mx',
            'is_active': False
        })
        
        result = await service.deactivate_user(mock_db_conn, user_id)
        
        assert result is not None
        assert result['is_active'] is False
        # Verificar que se llamó UPDATE
        assert mock_db_conn.execute_called_with_pattern('UPDATE tb_usuarios SET is_active = FALSE')
    
    @pytest.mark.asyncio
    async def test_reactivate_user(self, mock_db_conn):
        """Verifica que reactivate_user reactive un usuario."""
        service = AdminService()
        user_id = uuid4()
        
        # Mock de usuario reactivado
        mock_db_conn.set_fetchrow_result({
            'id_usuario': str(user_id),
            'nombre': 'Test User',
            'email': 'test@enertika.mx',
            'is_active': True
        })
        
        result = await service.reactivate_user(mock_db_conn, user_id)
        
        assert result is not None
        assert result['is_active'] is True
        # Verificar que se llamó UPDATE
        assert mock_db_conn.execute_called_with_pattern('UPDATE tb_usuarios SET is_active = TRUE')
    
    @pytest.mark.asyncio
    async def test_get_users_enriched(self, mock_db_conn):
        """Verifica que retorne usuarios con módulos y preferencias."""
        service = AdminService()
        
        # Mock de usuarios
        mock_db_conn.set_fetch_result([
            {'id_usuario': str(uuid4()), 'nombre': 'User 1', 'modulo_preferido': 'comercial'},
            {'id_usuario': str(uuid4()), 'nombre': 'User 2', 'modulo_preferido': None}
        ])
        
        # Mock de permisos de módulos
        mock_db_conn.set_fetch_result_nth(1, [
            {'modulo_slug': 'comercial', 'rol_modulo': 'editor', 'modulo_nombre': 'Comercial'}
        ])
        mock_db_conn.set_fetch_result_nth(2, [])
        
        # Mock de nombres de módulos preferidos
        mock_db_conn.set_fetchval_result('Comercial')
        
        result = await service.get_users_enriched(mock_db_conn)
        
        assert len(result) == 2
        assert 'user_modules' in result[0]
        assert 'modulo_preferido_nombre' in result[0]
    
    @pytest.mark.asyncio
    async def test_update_user_role(self, mock_db_conn):
        """Verifica actualización del rol de sistema."""
        service = AdminService()
        user_id = uuid4()
        new_role = 'MANAGER'
        
        await service.update_user_role(mock_db_conn, user_id, new_role)
        
        # Verificar que se ejecutó el UPDATE correcto
        assert mock_db_conn.execute_called_with_pattern('UPDATE tb_usuarios SET rol_sistema')
        assert mock_db_conn.execute_called_with_params(new_role, user_id)
    
    @pytest.mark.asyncio
    async def test_update_user_modules(self, mock_db_conn):
        """Verifica que reemplace correctamente permisos de módulos."""
        service = AdminService()
        user_id = uuid4()
        module_roles = {
            'comercial': 'editor',
            'admin': 'viewer'
        }
        
        await service.update_user_modules(mock_db_conn, user_id, module_roles)
        
        # Verificar que primero borró permisos anteriores
        assert mock_db_conn.execute_called_with_pattern('DELETE FROM tb_permisos_modulos')
        # Verificar que insertó nuevos permisos
        assert mock_db_conn.execute_called_with_pattern('INSERT INTO tb_permisos_modulos')
    
    @pytest.mark.asyncio
    async def test_add_email_rule(self, mock_db_conn):
        """Verifica que se agregue correctamente una regla de email."""
        service = AdminService()
        
        await service.add_email_rule(
            mock_db_conn,
            modulo='COMERCIAL',
            trigger_field='tipo_tecnologia',
            trigger_value='BESS',
            email_to_add='experto.bess@enertika.mx',
            type='CC'
        )
        
        # Verificar INSERT
        assert mock_db_conn.execute_called_with_pattern('INSERT INTO tb_config_emails')
    
    @pytest.mark.asyncio
    async def test_delete_email_rule(self, mock_db_conn):
        """Verifica que se elimine una regla de email."""
        service = AdminService()
        rule_id = 123
        
        await service.delete_email_rule(mock_db_conn, rule_id)
        
        # Verificar DELETE
        assert mock_db_conn.execute_called_with_pattern('DELETE FROM tb_config_emails')
        assert mock_db_conn.execute_called_with_params(rule_id)
    
    @pytest.mark.asyncio
    async def test_get_catalogos_reglas(self, mock_db_conn):
        """Verifica que obtenga catálogos dinámicos para formularios."""
        service = AdminService()
        
        # Mock de catálogos
        mock_db_conn.set_fetch_result_nth(0, [
            {'id': 1, 'nombre': 'BESS'},
            {'id': 2, 'nombre': 'Solar'}
        ])
        mock_db_conn.set_fetch_result_nth(1, [
            {'id': 1, 'nombre': 'PREOFERTA'},
            {'id': 2, 'nombre': 'COTIZACIÓN'}
        ])
        
        result = await service.get_catalogos_reglas(mock_db_conn)
        
        assert 'tecnologias' in result
        assert 'tipos_solicitud' in result
        assert len(result['tecnologias']) == 2
        assert len(result['tipos_solicitud']) == 2
