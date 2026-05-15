# BioTime PRO 1.0.x — Documentación de API

Versión confirmada: **BioTime PRO 1.0.6.5 (Build: 20220507.14313)**  
Host local: `http://192.168.0.200:8082`

---

## Autenticación — Sesión Django

BioTime PRO **no tiene API key**. Usa autenticación por sesión Django estándar.

### Flujo completo

```
1. GET  /login/
        ← Set-Cookie: csrftoken=<TOKEN>

2. POST /login/
        Content-Type: application/x-www-form-urlencoded
        X-CSRFToken: <TOKEN>          ← header
        X-Requested-With: XMLHttpRequest
        Body: csrfmiddlewaretoken=<TOKEN>&username=<USER>&password=<PASS>
        ← 200 OK  (respuesta AJAX, no redirect)

3. GET  /login/?next=/
        ← 302 Found
        ← Set-Cookie: sessionid=<SESSION>   ← esta es la sesión autenticada

4. Todas las requests siguientes:
        Cookie: csrftoken=<TOKEN>; sessionid=<SESSION>
        X-CSRFToken: <TOKEN>          ← requerido en POSTs
```

### Notas importantes
- El POST de login retorna **200** (no 302). Es un endpoint AJAX.
- El `sessionid` se obtiene del `Set-Cookie` del GET posterior (`/login/?next=/`).
- Con `httpx` se debe usar `follow_redirects=True` y persistir el `CookieJar` entre requests.
- La sesión expira — el cliente debe detectar el redirect a `/login/` (302) y re-autenticar.
- La clave de configuración `BIOTIME_ACCESS_KEY` se elimina; se reemplaza por `BIOTIME_USERNAME` + `BIOTIME_PASSWORD`.

---

## Endpoints de datos

### Fichadas (transacciones crudas)

```
GET /iclock/transaction/table/
    ?page=1
    &limit=200
    &_p1_punch_time__gte=2026-05-13    ← fecha inicio (inclusive)
    &_p1_punch_time__lt=2026-05-14     ← fecha fin (exclusiva)
```

Respuesta esperada:
```json
{
  "total": 450,
  "rows": [
    {
      "id": 12345,
      "emp_code": "001",
      "punch_time": "2026-05-13 08:32:11",
      "punch_state": "0",
      "verify_type": "1",
      "terminal_sn": "XXXX",
      "terminal_alias": "Entrada principal",
      "deptnumber": "01",
      "deptname": "Ingenieria"
    }
  ]
}
```

**Paginación:** iterar `page=1, 2, 3...` hasta que `rows` esté vacío o `len(rows) < limit`.

### Empleados

```
GET /personnel/employee/table/
    ?page=1
    &limit=200
    &_p1_company__id__exact=1
```

Retorna todos los empleados de la compañía. No filtrar por `emp_code` — se obtienen todos y se mapean en memoria.

### Reporte First-In / Last-Out (solo lectura, no usado en sync)

```
GET /att/api/firstInLastOutReport/
    ?page=1
    &page_size=20
    &start_date=2026-05-01
    &end_date=2026-05-13
    &time_table=0
    &departments=1,2,3,...
    &employees=-1    ← -1 = todos
```

---

## Schema de BioTime PRO — Tablas relevantes

### `iclock_transaction` — Fichadas crudas

| Columna | Tipo | Nullable | Notas |
|---|---|---|---|
| `id` | integer | NO | PK autoincremental — usar como `biotime_transaction_id` |
| `emp_code` | varchar(20) | NO | Código del empleado — FK lógica a `personnel_employee.emp_code` |
| `punch_time` | timestamptz | NO | Hora de fichada con zona horaria |
| `punch_state` | varchar(5) | NO | Ver catálogo abajo |
| `verify_type` | integer | NO | Ver catálogo abajo |
| `terminal_sn` | varchar(50) | YES | Serial del dispositivo |
| `terminal_alias` | varchar(50) | YES | Nombre del dispositivo |
| `area_alias` | varchar(100) | YES | Alias del área |
| `is_attendance` | smallint | YES | 1 = registra asistencia |
| `source` | smallint | YES | 0=dispositivo, 1=manual, 2=app |
| `purpose` | smallint | YES | Propósito del registro |
| `temperature` | numeric | YES | Temperatura (si aplica) |
| `emp_id` | integer | YES | FK a `personnel_employee.id` |
| `terminal_id` | integer | YES | FK a `iclock_terminal.id` |
| `upload_time` | timestamptz | YES | Hora en que se subió al servidor |

**Catálogo `punch_state`:**
| Valor | Significado |
|---|---|
| `0` | Check In (entrada) |
| `1` | Check Out (salida) |
| `2` | Break Out (salida a descanso) |
| `3` | Break In (regreso de descanso) |
| `4` | Overtime In (entrada tiempo extra) |
| `5` | Overtime Out (salida tiempo extra) |

**Catálogo `verify_type`:**
| Valor | Significado |
|---|---|
| `0` | Contraseña |
| `1` | Huella digital |
| `2` | Tarjeta |
| `3` | Reconocimiento facial |
| `4` | Vena del dedo |
| `5` | Palma |

> **IMPORTANTE — campos confirmados en producción:**
> - La fecha y hora vienen **separadas**: `transaction_punch_date = '2026-05-11'` y `transaction_punch_time = '07:13:48'` (solo hora, sin fecha). El campo `punch_time` de la tabla NO se expone directamente en la API.
> - El departamento viene como `employee_department` (nombre), no como `deptnumber`.
> - También vienen: `employee_name`, `employee_last_name`, `employee_position`, `area_alias`, `get_temperature`, `get_is_mask`.
> - `deptnumber` y `deptname` (nombres legacy) NO están presentes — usar `employee_department`.

---

### `personnel_employee` — Empleados

| Columna | Tipo | Nullable | Notas |
|---|---|---|---|
| `id` | integer | NO | PK |
| `emp_code` | **bigint** | NO | Código único del empleado — viene como número, convertir a string al mapear |
| `first_name` | varchar(50) | YES | Nombre |
| `last_name` | varchar(25) | YES | Apellido |
| `email` | varchar(50) | YES | Email — campo clave para mapear con `tb_usuarios` |
| `mobile` | varchar(30) | YES | Teléfono |
| `national_num` | varchar(50) | YES | CURP / número nacional |
| `payroll_num` | varchar(50) | YES | Número de nómina |
| `hire_date` | date | YES | Fecha de contratación |
| `department_id` | integer | YES | FK a `personnel_department.id` |
| `status` | smallint | NO | 1=activo |
| `enable_att` | boolean | NO | Habilitado para asistencia |
| `deleted` | boolean | NO | Marcado como eliminado |
| `is_active` | boolean | NO | Activo en el sistema |
| `company_id` | integer | YES | FK a compañía |

**Campos a ignorar:** `self_password`, `device_password`, `photo`, biometría (`fp_*`, `face_*`), `acc_group`, etc.

---

### `personnel_department` — Departamentos

| Columna | Tipo | Nullable | Notas |
|---|---|---|---|
| `id` | integer | NO | PK |
| `dept_code` | varchar(50) | NO | Código del departamento |
| `dept_name` | varchar(100) | NO | Nombre |
| `company_id` | integer | YES | FK a compañía |
| `parent_dept_id` | integer | YES | Para jerarquía de departamentos |

---

### `iclock_terminal` — Dispositivos

| Columna | Tipo | Notas |
|---|---|---|
| `id` | integer | PK |
| `sn` | varchar(50) | Serial — coincide con `iclock_transaction.terminal_sn` |
| `alias` | varchar(50) | Nombre amigable |
| `ip_address` | inet | IP del dispositivo |
| `is_attendance` | smallint | 1 = registra asistencia |
| `company_id` | integer | FK compañía |

---

## Mapping BioTime PRO → ECO

### `iclock_transaction` → `tb_biotime_checks`

| BioTime (`iclock_transaction`) | ECO (`tb_biotime_checks`) | Transformación |
|---|---|---|
| `id` | `biotime_transaction_id` | Directo (integer) |
| `emp_code` | `biotime_emp_code` | Convertir a string |
| `punch_time` | `check_time` | Ya es timestamptz — guardar tal cual |
| `punch_state` | `punch_state` | Directo (string) |
| `verify_type` | `verify_type` | Convertir a string |
| `terminal_sn` | `terminal_sn` | Directo |
| `terminal_alias` | `terminal_alias` | Directo |
| *(no existe)* | `deptnumber` | Siempre `null` desde esta tabla |
| *(no existe)* | `deptname` | Siempre `null` desde esta tabla |
| *(lookup)* | `usuario_id` | Via `tb_biotime_empleado_map` por `emp_code` |
| *(objeto completo)* | `raw_payload` | JSON del item completo |

### `personnel_employee` → `tb_biotime_empleado_map`

| BioTime (`personnel_employee`) | ECO (`tb_biotime_empleado_map`) | Transformación |
|---|---|---|
| `emp_code` | `biotime_emp_code` | Convertir bigint → string |
| `emp_code` | `biotime_pin` | Igual que `emp_code` |
| `id` | `biotime_emp_id` | Directo (integer) |
| `email` | `biotime_email` | Normalizar a minusculas |
| `first_name` + `last_name` | `nombre` | Concatenar con espacio |
| `department_id` (via JOIN) | `biotime_deptnumber` | `dept_code` del departamento |
| `department_id` (via JOIN) | `biotime_deptname` | `dept_name` del departamento |
| *(lookup por email unico)* | `usuario_id` | Buscar en `tb_usuarios` por email normalizado y usuario activo |
| *(regla ECO)* | `match_source` | Siempre `email` |
| *(timestamp ECO)* | `last_seen_at` | Fecha de ultimo sync exitoso del empleado |

Regla vigente de mapeo:

- El unico match automatico permitido es `LOWER(TRIM(personnel_employee.email)) = LOWER(TRIM(tb_usuarios.email))`.
- Si el correo no existe, no coincide o esta duplicado entre usuarios activos, no se crea mapping.
- `numero_empleado` no se usa como fallback para BioTime.
- Despues del match por email, ECO actualiza `tb_empleados_datos.biotime_emp_code` como dato sincronizado de solo lectura.

---

## Cambios de configuración en ECO

| Config key anterior | Config key nueva | Descripción |
|---|---|---|
| `BIOTIME_ACCESS_KEY` | ~~eliminada~~ | Ya no aplica |
| *(nuevo)* | `BIOTIME_USERNAME` | Usuario de BioTime PRO |
| *(nuevo)* | `BIOTIME_PASSWORD` | Contraseña de BioTime PRO |
| `BIOTIME_BASE_URL` | `BIOTIME_BASE_URL` | Sin cambio |
| `BIOTIME_SYNC_ACTIVO` | `BIOTIME_SYNC_ACTIVO` | Sin cambio |
| demás keys | sin cambio | Sin cambio |

---

## Diferencias vs BioTime 8/9 (versión original del cliente)

| Aspecto | BioTime 8/9 (anterior) | BioTime PRO 1.0.x (actual) |
|---|---|---|
| Auth | `?key=<API_KEY>` en query param | Sesión Django (cookie) |
| Login | No requiere | `POST /login/` con CSRF |
| Transacciones | `POST /api/v2/transaction/get/` | `GET /iclock/transaction/table/` |
| Empleados | `POST /api/v2/employee/get/` | `GET /personnel/employee/table/` |
| Paginación | Cursor por `id` | Cursor por `page` |
| Filtro fecha | `starttime` / `endtime` en body | `_p1_punch_time__gte/lt` en query |

---

## Estado de implementación en ECO

El código actual ya está alineado con BioTime PRO en los puntos principales:

1. `modules/asistencia/biotime_client.py` usa login Django con CSRF/cookies.
2. `modules/asistencia/biotime_client.py` consulta `/iclock/transaction/table/`.
3. `modules/asistencia/biotime_client.py` consulta `/personnel/employee/table/`.
4. `modules/asistencia/constants.py` define `BIOTIME_USERNAME` y `BIOTIME_PASSWORD`.
5. `modules/admin/service.py` lee/guarda usuario y contraseña BioTime.
6. `modules/admin/router.py` recibe usuario/contraseña en guardar y probar conexión.
7. `templates/admin/partials/global_config.html` muestra campos de usuario y contraseña.
8. `migrations/077_biotime_email_mapping.sql` agrega metadata de match por correo y soporte para excepciones de checadas sin mapear.
9. `modules/asistencia/db_service.py` crea mappings solo por correo unico contra usuarios activos.
10. `RRHH > Asistencia` y el Excel de asistencia muestran codigos BioTime con checadas sin mapear.

Pendiente de validación:

- Probar contra el servidor real que el login entregue `sessionid` con el flujo documentado.
- Confirmar que `/personnel/employee/table/` incluya `email`, `last_name` y `department_id` en `rows`.
- Si RH necesita ver departamento BioTime, agregar lookup contra `personnel_department`.
- Dejar `BIOTIME_ACCESS_KEY` como clave obsoleta; no debe usarse en el cliente actual.
- Confirmar en DEV que todos los empleados BioTime tengan correo actualizado para evitar excepciones sin mapear.
