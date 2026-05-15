# Correcciones de Gaps — Módulo Vacaciones/RRHH

Fecha: 2026-05-13  
Branch: feature/vacaciones

---

## GAP 1: VACACIONES_MESES_EXPIRACION no era configurable desde Admin

**Problema:**  
La lógica de expiración de periodos en `modules/vacaciones/logic.py:calcular_periodos()` lee
`VACACIONES_MESES_EXPIRACION` vía `ConfigService` con fallback 18. La clave nunca fue insertada
en `tb_configuracion_global` y no había UI para cambiarla.

**Archivos modificados:**

| Archivo | Cambio |
|---------|--------|
| `migrations/071_vacaciones_config_meses_expiracion.sql` | INSERT inicial del valor 18 en `tb_configuracion_global` |
| `modules/rrhh/service.py` | Agrega `from core.config_service import ConfigService`; `get_admin_ctx` ahora expone `vacaciones_meses_expiracion`; nueva función `guardar_config_vacaciones()` con validación 1–120 |
| `modules/rrhh/router.py` | Nuevo endpoint `POST /rrhh/admin/config` (requiere manager+editor); llama `service.guardar_config_vacaciones` y refresca admin.html |
| `templates/rrhh/partials/admin.html` | Nueva sección "Parametros de vacaciones" al final con input numérico y submit |

**Flujo resultante:**  
Admin RRHH → pestaña Admin → sección "Parametros de vacaciones" → cambiar meses → Guardar →
el valor se persiste en `tb_configuracion_global` y `ConfigService` lo devuelve en las siguientes
llamadas a `calcular_periodos`.

---

## GAP 2: Vista HTML de Asistencia inexistente

**Problema:**  
El plan `BIOTIME_ASISTENCIA_VACACIONES.md` §Fase 6 especificaba una vista HTML para monitorear
asistencia desde RRHH. Solo existían un endpoint JSON (`GET /asistencia/api/reporte`) y tres
exportaciones Excel en `GET /rrhh/reportes/*.xlsx`. No había pestaña de Asistencia en la UI de RRHH.

**Archivos modificados/creados:**

| Archivo | Cambio |
|---------|--------|
| `modules/rrhh/router.py` | Agrega import `timedelta` y `ASISTENCIA_ESTADOS`; nuevo endpoint `GET /rrhh/asistencia` (requiere rrhh viewer); aplica `ensure_mx()` a las timestamps antes de pasar al template |
| `templates/rrhh/partials/content.html` | Nuevo tab "Asistencia" entre Solicitudes y Reportes |
| `templates/rrhh/partials/asistencia.html` | Template nuevo: filtros (fecha inicio/fin, empleado, sucursal, estado) + tabla con fecha, empleado, sucursal, entrada, salida, horas, extra, estado + enlace "Exportar Excel" |

**Rango por defecto:** últimos 7 días (hoy - 6 días a hoy).

**Columnas de la tabla:**
- Fecha, Empleado (nombre + email), Sucursal
- Entrada / Salida (hora en zona Mexico City vía `ensure_mx`)
- Horas trabajadas / Extra (formato `H:MM`)
- Estado (badge con colores por estado) + indicador "vac" si `tiene_vacaciones`

**Permisos:** igual que el resto de tabs, requiere `rrhh viewer`.

---

## GAP 4: Sin UI para administrar catálogos de BioTime/Asistencia

**Estado:** ⚠️ PENDIENTE

**Problema:**  
La migración 070 creó las tablas necesarias para el módulo de asistencia, pero no existe ningún
CRUD para administrarlas. Sin estos catálogos poblados, el worker `sync_biotime_periodically`
sincroniza checadas crudas pero no puede calcular asistencia correctamente.

| Tabla | Impacto sin CRUD |
|-------|-----------------|
| `tb_cat_sucursales` | Todos los empleados quedan sin sucursal asignada. El filtro de sucursal en `/rrhh/asistencia` no muestra opciones. |
| `tb_horarios_sucursal` + `tb_horarios_sucursal_dias` | El cálculo de asistencia (`ScheduleConfig` en `modules/asistencia/logic.py`) no puede determinar hora esperada de entrada/salida, minutos programados ni tolerancias. |
| `tb_biotime_empleado_map` | El worker no puede atribuir checadas de BioTime a usuarios de Enertika. Sin el campo `biotime_pin`/`biotime_emp_code`, los registros de `tb_biotime_checks` quedan huérfanos. |

**Implementación sugerida:**  
Agregar en RRHH un tab "BioTime / Sucursales" con:
- CRUD de `tb_cat_sucursales`
- CRUD de `tb_horarios_sucursal` (con detalle inline de `tb_horarios_sucursal_dias` por día de semana)
- Mapeo `tb_biotime_empleado_map` editable desde `RRHH > Empleados > Editar` (campo `biotime_pin`)

**Precondición:**  
Resolver primero el GAP B (preguntas de negocio) de `BIOTIME_ASISTENCIA_VACACIONES.md §Preguntas pendientes`
antes de implementar los horarios — las tolerancias y reglas de descuento de comida afectan el schema.

---

## GAP 5: SQL directo en service de RRHH

**Estado:** Cerrado el 2026-05-13

**Problema:**
`modules/rrhh/service.py` tenia consultas SQL directas con `conn.fetchrow`, `conn.execute` y
`conn.fetch`. Esto rompia la regla de arquitectura `Router -> Service -> DB Service`.

**Archivos modificados/creados:**

| Archivo | Cambio |
|---------|--------|
| `modules/rrhh/db_service.py` | Nuevo db service para consultas propias de RRHH: usuario simple, upsert de configuracion de vacaciones y reporte de vacaciones |
| `modules/rrhh/service.py` | Elimina SQL embebido y consume `modules.rrhh.db_service` |

**Verificacion:**
`rg` ya no encuentra `conn.fetch`, `conn.fetchrow`, `conn.execute` ni SQL embebido en
`modules/rrhh/service.py`.

---

## Pendientes consolidados detectados el 2026-05-13

| Pendiente | Motivo |
|-----------|--------|
| Agregar CRUD Admin de BioTime/asistencia | Faltan sucursales, horarios y mapeo empleado-BioTime desde UI |
| Aprobacion persistida de horas extra | `Mi Equipo` muestra calculo de horas extra, pero aun no existe schema/flujo para aprobar o rechazar |
| Tolerancias entrada/salida | Columnas/reglas preparadas para fase posterior, sin uso actual |
| Implementar comprobante medico en incapacidad | Falta schema/upload/validacion para adjunto |
| Validar BioTime PRO en servidor real | Confirmar login Django, cookies, `rows` de empleados, email, nombre completo y departamento |
| Vista de revision de checadas sin mapear | Las checadas sin usuario deben quedar visibles para correccion manual de RH |

---

## GAP 6: Reglas de negocio BioTime/asistencia

**Estado:** Documentado el 2026-05-13

**Decisiones acordadas:**

| Regla | Decision |
|-------|----------|
| Fuente de sucursal | Manual en Enertika Ops Core |
| Mapeo Enertika/BioTime | Automatico por correo si BioTime lo expone y coincide exactamente; si no, por codigo/PIN; nombre solo como sugerencia |
| Comida | No se descuenta automaticamente |
| Horas extra | Se calculan automaticamente, pero pago/validacion requiere aprobacion |
| Aprobador de horas extra | Jefe directo o aprobador asignado; RH/Admin puede revisar y aprobar por excepcion |
| Checada en vacaciones | Estado `checada_en_vacaciones`, sin horas extra |
| Tolerancias entrada/salida | Se documentan/preparan columnas, pero no se usan todavia |

**Hallazgo BioTime:**
En BioTime PRO, la API de empleados es `GET /personnel/employee/table/` y expone el correo desde
`personnel_employee.email`. La API de transacciones `GET /iclock/transaction/table/` no trae correo,
por lo que el mapeo automatico por correo requiere consultar/sincronizar empleados BioTime ademas
de checadas.

---

## GAP 7: Sucursal en edicion de empleado

**Estado:** Cerrado el 2026-05-13

**Problema:**
La tabla `tb_cat_sucursales` existia, pero `get_sucursales()` consultaba `is_active` aunque la
migracion 070 creo la columna `activa`. Ademas, la edicion de empleado no mostraba dropdown de
sucursal ni guardaba `tb_empleados_datos.sucursal_id`.

**Archivos modificados:**

| Archivo | Cambio |
|---------|--------|
| `modules/asistencia/db_service.py` | `get_sucursales()` ahora filtra por `activa = true` |
| `modules/vacaciones/db_service.py` | `get_empleado_datos()` y `upsert_empleado_datos()` leen/guardan `sucursal_id` |
| `modules/rrhh/service.py` | El contexto de edicion de empleado carga `sucursales` y guarda `sucursal_id` |
| `modules/rrhh/router.py` | El POST de empleado recibe `sucursal_id` |
| `templates/rrhh/partials/empleado_editar.html` | Agrega dropdown de sucursal |

---

## GAP 8: Feedback visual en Mi Equipo

**Estado:** Cerrado visualmente el 2026-05-13

**Problema:**
La seccion `Mi Perfil > Mi Equipo` mostraba balances y alertas, pero no mostraba vacaciones
aprobadas del equipo, quien esta actualmente de vacaciones ni horas extra pendientes de aprobacion.

**Archivos modificados:**

| Archivo | Cambio |
|---------|--------|
| `modules/vacaciones/db_service.py` | Nueva consulta para vacaciones aprobadas del equipo |
| `modules/asistencia/db_service.py` | Nueva consulta para horas extra calculadas del equipo |
| `modules/vacaciones/service.py` | Nuevo contexto `get_equipo_dashboard()` con vacaciones actuales, proximas y horas extra pendientes |
| `modules/vacaciones/router.py` | `/perfil/equipo` entrega el contexto visual completo |
| `templates/vacaciones/partials/equipo.html` | Rediseño visual con vacaciones del equipo, proximas aprobadas, horas extra pendientes y personas del equipo |

**Pendiente:**
Las horas extra se muestran como pendientes de aprobacion porque todavia no existe schema/flujo para
aprobar o rechazar. Ese flujo debe implementarse en un GAP posterior.

---

## GAP 9: Mapeo automatico BioTime/ECO

**Estado:** Cerrado el 2026-05-13

**Problema:**
El sync de checadas solo podia asignar `usuario_id` si ya existia un mapeo por `biotime_emp_code` o
si el codigo coincidia con `numero_empleado`. No aprovechaba el correo de BioTime.

**Archivos modificados:**

| Archivo | Cambio |
|---------|--------|
| `modules/asistencia/biotime_client.py` | Agrega `fetch_employees()` contra `/personnel/employee/table/` de BioTime PRO |
| `modules/asistencia/db_service.py` | Agrega upsert de `tb_biotime_empleado_map` por email exacto y fallback por codigo/PIN |
| `modules/asistencia/service.py` | El sync consulta empleados BioTime detectados en checadas antes de normalizar transacciones |

**Regla aplicada:**
Primero email exacto contra `tb_usuarios.email`; si no hay email valido, codigo/PIN contra
`tb_empleados_datos.biotime_emp_code` o `numero_empleado`. El nombre no se usa como match automatico.

**Actualizacion BioTime PRO:**
`_planVacations/BIOTIME_PRO_API.md` confirma que la version objetivo no usa `api/v2/employee/get`.
El cliente actual debe consultar empleados con `GET /personnel/employee/table/` y autenticar por
sesion Django.

---

## GAP 10: Permisos RRHH alineados a RBAC

**Estado:** Cerrado el 2026-05-13

**Problema:**
Flujos de vacaciones/RRHH y contactos RH del worker/workflow todavia dependian de `es_rh`.

**Correccion:**
Se migro a permisos de modulo:

| Caso | Regla |
|------|-------|
| Ver equipo/detalle global | `rrhh viewer` o superior |
| Aprobar/rechazar como RH | `rrhh editor` o superior |
| Contactos RH para recordatorios/notificaciones workflow | `rrhh editor/admin` o `ADMIN` global |

---

## GAP 11: Recalculo asistencia al resolver vacaciones

**Estado:** Cerrado el 2026-05-13

**Problema:**
Al aprobar, cancelar o rechazar vacaciones, `tb_asistencia_diaria` podia quedarse desfasada hasta un
recalculo posterior.

**Correccion:**
`modules/vacaciones/service.py` recalcula el rango completo de la solicitud cuando cambia el estado.

---

## GAP 12: Solicitudes vencidas y timezone

**Estado:** Cerrado el 2026-05-13

**Problema:**
La consulta de solicitudes vencidas calculaba la fecha desde SQL con
`CURRENT_DATE AT TIME ZONE 'America/Mexico_City'`.

**Correccion:**
`core/tasks.py` calcula `hoy = today_mx()` y `core/tasks_db_service.py` lo recibe como parametro SQL.

---

## GAP 13: Textos BioTime en Admin

**Estado:** Cerrado el 2026-05-13

**Problema:**
La UI Admin BioTime tenia textos visibles en ingles.

**Correccion:**
Se tradujeron labels/placeholders como `Access key`, `Sync activo`, `Lookback`, `Timeout` y
`Probar conexion`.

---

## GAP 14: Adaptacion cliente BioTime PRO 1.0.x

**Estado:** Cerrado en cliente; pendiente validacion contra servidor real

**Cambio detectado:**
El archivo `_planVacations/BIOTIME_PRO_API.md` confirma BioTime PRO 1.0.6.5. Esta version no usa
`BIOTIME_ACCESS_KEY` ni endpoints `api/v2`.

**Regla actualizada:**

| Aspecto | BioTime PRO |
|---------|-------------|
| Auth | Login Django con `csrftoken` y `sessionid` |
| Config | `BIOTIME_BASE_URL`, `BIOTIME_USERNAME`, `BIOTIME_PASSWORD` |
| Checadas | `GET /iclock/transaction/table/` |
| Empleados | `GET /personnel/employee/table/` |
| Paginacion | `page` + `limit`, respuesta `total` + `rows` |
| Mapeo empleado | `emp_code` como string; email desde tabla de empleados |

**Codigo alineado:**

| Archivo | Estado |
|---------|--------|
| `modules/asistencia/biotime_client.py` | Usa login Django, cookies, `/iclock/transaction/table/` y `/personnel/employee/table/` |
| `modules/asistencia/constants.py` | Usa `BIOTIME_USERNAME` y `BIOTIME_PASSWORD` |
| `modules/admin/service.py` | Lee/guarda usuario y contrasena BioTime |
| `templates/admin/partials/global_config.html` | Muestra campos de usuario y contrasena |

**Pendiente:**
Validar con el servidor real que los `rows` de empleados incluyan `email`, `last_name` y
`department_id`. Si RH requiere departamento visible, agregar lookup contra `personnel_department`.

---

## Notas de despliegue

1. Ejecutar `migrations/071_vacaciones_config_meses_expiracion.sql` en producción **antes** de desplegar el código.
2. La migración es idempotente (`ON CONFLICT (clave) DO NOTHING`) — si el valor ya fue insertado manualmente, no sobreescribe.
3. La tabla `tb_asistencia_diaria` debe estar populada por el worker (`sync_biotime_periodically`) para que la vista de asistencia muestre datos.
4. Para BioTime PRO, `BIOTIME_ACCESS_KEY` queda obsoleto. Guardar `BIOTIME_USERNAME` y
   `BIOTIME_PASSWORD` desde Admin o por configuracion global antes de activar el sync.
