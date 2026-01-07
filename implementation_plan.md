# Plan de Implementación: Notificación Automática para Registro Extraordinario

## Goal Description
Integrar el envío automático de correos electrónicos al crear una "Solicitud Extraordinaria" en el módulo Comercial. Los destinatarios (TO y CC) deben ser configurables desde el Dashboard de Admin.

## User Review Required
> [!IMPORTANT]
> Se utilizará la tabla `tb_configuracion_global` para almacenar los destinatarios (`EXTRAORDINARIA_EMAILS_TO`, `EXTRAORDINARIA_EMAILS_CC`). Esto añadirá nuevos campos en la sección de Configuración Global del Admin.

## Proposed Changes

### Admin Module
Habilitar la configuración de los correos destinatarios.

#### [MODIFY] [modules/admin/schemas.py](file:///c:/Users/SISTEMAS/OneDrive%20-%20ISAEM%20%281%29/Documents/Python/Enertika-Ops-Core/modules/admin/schemas.py)
- Actualizar `ConfiguracionGlobalUpdate` para incluir:
    - `extraordinaria_emails_to`: Optional[str]
    - `extraordinaria_emails_cc`: Optional[str]

#### [MODIFY] [modules/admin/service.py](file:///c:/Users/SISTEMAS/OneDrive%20-%20ISAEM%20%281%29/Documents/Python/Enertika-Ops-Core/modules/admin/service.py)
- `get_global_config`: Leer y retornar las nuevas claves.
- `update_global_config`: Guardar las nuevas claves en `tb_configuracion_global`.

#### [MODIFY] [templates/admin/dashboard.html](file:///c:/Users/SISTEMAS/OneDrive%20-%20ISAEM%20%281%29/Documents/Python/Enertika-Ops-Core/templates/admin/dashboard.html)
- Agregar campos de texto (Separado por comas) en el formulario de Configuración Global para editar los correos.

### Comercial Module
Implementar la lógica de envío.

#### [MODIFY] [modules/comercial/email_handler.py](file:///c:/Users/SISTEMAS/OneDrive%20-%20ISAEM%20%281%29/Documents/Python/Enertika-Ops-Core/modules/comercial/email_handler.py)
- Crear método `send_extraordinary_notification`:
    - Recibir connection y datos de oportunidad.
    - Leer destinatarios de `tb_configuracion_global` (reutilizando `ComercialService.get_configuracion_global` o query directa si necesario).
    - Validar Token Graph.
    - Construir cuerpo de correo simple (HTML).
    - Enviar usando `ms_auth.send_email_with_attachments`.

#### [MODIFY] [modules/comercial/router.py](file:///c:/Users/SISTEMAS/OneDrive%20-%20ISAEM%20%281%29/Documents/Python/Enertika-Ops-Core/modules/comercial/router.py)
- En `handle_oportunidad_extraordinaria`:
    - Instanciar/Inyectar `EmailHandler`.
    - Después de guardar la oportunidad y antes del redirect:
        - Llamar a `email_handler.send_extraordinary_notification`.
        - Registrar en log el resultado.
        - **Nota**: El fallo en envío NO debe bloquear la creación, pero sí loguear error (fail-safe).

## Verification Plan

### Manual Verification
1.  **Configuración**:
    - Ir a `/admin/ui`.
    - Ingresar correos de prueba en "Destinatarios Extraordinarios".
    - Guardar y recargar para verificar persistencia.
2.  **Ejecución**:
    - Ir a `/comercial/form-extraordinario` (como Admin/Manager).
    - Crear una solicitud.
    - Verificar que la UI redirige correctamente.
    - Verificar (vía logs o bandeja de entrada real) que el correo salió a los destinatarios configurados.
