# 8. Sistema de Correos Configurables

## Propósito

Sistema centralizado para gestionar correos electrónicos en la aplicación, diferenciando entre:
- **Correos de negocio**: Gestión comercial, ventas, cotizaciones
- **Correos de notificación**: Alertas automáticas del sistema

## Implementación en Módulos

### NotificationService

Servicio centralizado para gestión de correos de notificación.

**Ubicación**: `core/notifications/service.py`

### Uso Básico

```python
from core.notifications import NotificationService

# En tu router o service
async def enviar_notificacion(...):
    notification_service = NotificationService()
    
    await notification_service.send_email(
        to_emails=["destinatario@example.com"],
        subject="Asunto del correo",
        body="Contenido del mensaje",
        departamento="COMERCIAL"
    )
```

## Mejores Prácticas

### 1. Usar Templates HTML

Crear templates reutilizables en `templates/shared/emails/`:

```html
<!-- templates/shared/emails/notificacion_base.html -->
<!DOCTYPE html>
<html>
<head>
    <style>
        /* Estilos corporativos */
    </style>
</head>
<body>
    <div style="background-color: #00BABB;">
        <h1>{{ titulo }}</h1>
    </div>
    <div>
        {{ contenido }}
    </div>
</body>
</html>
```

### 2. Validar Configuración

Siempre verificar que existe configuración de buzón antes de enviar:

```python
async def validate_email_config(self, conn, departamento: str):
    config = await conn.fetchrow(
        "SELECT email_from FROM tb_correos_notificaciones WHERE departamento = $1 AND is_active = true",
        departamento
    )
    if not config:
        raise ValueError(f"No hay configuración de correo para {departamento}")
    return config['email_from']
```

### 3. Logging de Envíos

Registrar todos los envíos para auditoría:

```python
logger.info(f"Enviando correo desde {email_from} a {to_emails}")
# ... envío de correo
logger.info(f"Correo enviado exitosamente")
```

> [!NOTE]
> **Esta sección está en desarrollo**. El contenido detallado será agregado próximamente.

## Tipos de Correos

### Correos de Negocio
- Envío de cotizaciones
- Comunicación con clientes
- Documentos comerciales
- Requieren buzón específico del departamento

### Correos de Notificación
- Alertas de sistema
- Cambios de estado
- Recordatorios automáticos
- Notificaciones de workflow

## Configuración de Buzones

### Tabla: `tb_correos_notificaciones`

Almacena la configuración de buzones compartidos por departamento.

**Campos clave**:
- `departamento`: Identificador del departamento
- `email_from`: Buzón de envío configurado
- `is_active`: Si el buzón está activo

### Ejemplo de Configuración

```sql
-- Buzón para departamento comercial
INSERT INTO tb_correos_notificaciones (departamento, email_from, is_active)
VALUES ('COMERCIAL', 'ventas@enertika.com', true);

-- Buzón para simulación
INSERT INTO tb_correos_notificaciones (departamento, email_from, is_active)
VALUES ('SIMULACION', 'simulacion@enertika.com', true);
```


## ✅ Checklist de Implementación

- [ ] Configurar buzón en `tb_correos_notificaciones`
- [ ] Crear template HTML para el correo
- [ ] Implementar validación de configuración
- [ ] Agregar logging apropiado
- [ ] Probar envío en ambiente de desarrollo
- [ ] Manejar errores de envío gracefully
- [ ] Documentar destinatarios y propósito

---

> [!IMPORTANT]
> Esta sección será expandida con ejemplos detallados de implementación en el módulo Comercial y otros casos de uso específicos.

---

[← Volver al Índice](README.md)
