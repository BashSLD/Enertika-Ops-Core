# Integracion BioTime, asistencia y vacaciones

## Requerimiento inicial

Se esta implementando el modulo de vacaciones y se quiere conectar Enertika Ops Core con el servidor BioTime/ZKTeco.

Contexto planteado:

- BioTime corre en un servidor con IP publica.
- El puerto `8082` esta abierto para la conexion de dispositivos ZKTeco.
- Actualmente se consulta informacion directamente en el servidor con el script `_planVacations/Script para consultar asistencia.txt`.
- Se requiere descargar o reconstruir el reporte de asistencia llamado en BioTime: **primera entrada, ultima salida**.
- El reporte debe incluir horas trabajadas.
- El reporte debe cruzarse con dias de vacaciones aprobadas.
- Si un usuario no tiene checada en un dia y pidio vacaciones aprobadas, el sistema debe mostrar ese dia como **Vacaciones**.
- Se requiere saber si puede configurarse sucursal del empleado.
- La idea es configurar horario por sucursal.
- Se requiere calcular horas extra con base en la asistencia.
- Se deben considerar casos donde los empleados hacen checadas despues de medianoche, es decir, en el dia calendario siguiente.

Decision de negocio/tecnica:

> Las horas extra se calcularan en Enertika Ops Core. No se obtendran como dato final desde BioTime.

BioTime puede usarse como referencia o auditoria, pero Enertika debe ser la fuente de verdad para calculo de horas trabajadas, fecha laboral, vacaciones y horas extra.

## Hallazgos sobre BioTime

La carpeta `_planVacations/BioTime` contiene una instalacion completa de BioTime, no solo codigo fuente. Incluye Apache, PostgreSQL local, Python 2.7, aplicacion Django, respaldos, archivos subidos y configuracion del servicio.

Archivos relevantes revisados:

- `_planVacations/BioTime/attsite.ini`
- `_planVacations/BioTime/appconfig.ini`
- `_planVacations/BioTime/mysite/local_settings.py`
- `_planVacations/BioTime/mysite/api/doc/api_data.json`
- `_planVacations/BioTime/mysite/att/templates/att/report/first_in_last_out.html`
- `_planVacations/BioTime/mysite/att/templates/att/report/firstlastreport.html`
- `_planVacations/BioTime/mysite/att/templates/att/report/totaltimecardreport.html`
- `_planVacations/BioTime/mysite/att/templates/att/report/overtimereport.html`
- `_planVacations/BioTime/mysite/att/sql/sql.xml`
- `_planVacations/BioTime/mysite/iclock/migrations/0001_initial.py`
- `_planVacations/BioTime/mysite/personnel/migrations/0001_initial.py`
- `_planVacations/BioTime/mysite/att/migrations/0002_auto_20200407_1022.py`
- `_planVacations/BIOTIME_PRO_API.md`

Nota de seguridad: en la instalacion local existen credenciales, llaves y configuraciones sensibles. No deben copiarse al repositorio, al frontend ni a logs. Cualquier acceso desde Enertika debe configurarse mediante variables de entorno o `ConfigService`.

### Actualizacion 2026-05-13: BioTime PRO 1.0.6.5

El documento `_planVacations/BIOTIME_PRO_API.md` confirma que la instancia objetivo es
**BioTime PRO 1.0.6.5 (Build 20220507.14313)**.

Este cambio invalida el supuesto anterior de BioTime 8/9:

- Ya no aplica `BIOTIME_ACCESS_KEY`.
- La autenticacion es por sesion Django con `csrftoken` y `sessionid`.
- La configuracion operativa usa `BIOTIME_USERNAME` y `BIOTIME_PASSWORD`.
- Las checadas se consultan con `GET /iclock/transaction/table/`.
- Los empleados se consultan con `GET /personnel/employee/table/`.
- Las respuestas vienen en formato de tabla (`total`, `rows`), no en `data.items`.
- `emp_code` sustituye al uso operativo de `pin`; se normaliza a string para ECO.
- Las transacciones no traen correo ni departamento directo confiable; el correo sale de
  `personnel_employee.email` y el departamento requiere lookup contra `personnel_department`.

El codigo actual de `modules/asistencia/biotime_client.py` ya sigue este modelo de BioTime PRO.

## Como obtener informacion de BioTime

### Opcion recomendada: API BioTime PRO por sesion Django

BioTime PRO no usa API key. El cliente debe iniciar sesion contra `/login/`, conservar
`csrftoken` y `sessionid`, y reautenticar cuando BioTime redirija a `/login/`.

Flujo de autenticacion:

```text
GET  /login/                 -> obtiene csrftoken
POST /login/                 -> envia username, password y csrfmiddlewaretoken
GET  /login/?next=/          -> obtiene sessionid autenticado
GET  endpoints de datos      -> usa cookies csrftoken/sessionid
```

Fuente principal de checadas crudas:

```text
GET /iclock/transaction/table/
    ?page=1
    &limit=200
    &_p1_punch_time__gte=2026-05-13
    &_p1_punch_time__lt=2026-05-14
```

Campos utiles de respuesta:

- `id`
- `emp_code`
- `punch_time`
- `punch_state`
- `verify_type`
- `terminal_sn`
- `terminal_alias`
- `emp_id`
- `terminal_id`
- `upload_time`

Paginacion: iterar `page=1, 2, 3...` hasta que `rows` este vacio, `len(rows) < limit`
o se alcance `total`.

Fuente de empleados para mapeo automatico:

```text
GET /personnel/employee/table/
    ?page=1
    &limit=200
    &_p1_company__id__exact=1
```

Campos utiles:

- `id`
- `emp_code`
- `first_name`
- `last_name`
- `email`
- `department_id`
- `status`
- `enable_att`
- `deleted`
- `is_active`

Para esta version queda descartado usar `POST /api/v2/transaction/get/?key=...` y
`POST /api/v2/employee/get/?key=...`.

### Opcion alternativa: sync local en el servidor BioTime

Si la API publica no debe exponerse a Railway, o si no hay una IP fija confiable para permitir acceso, se recomienda instalar un pequeno proceso en el servidor BioTime que:

1. Consulte BioTime localmente.
2. Transforme los datos al formato requerido.
3. Envie las checadas a Enertika mediante un endpoint seguro.

Esta opcion evita exponer PostgreSQL o endpoints internos hacia internet.

### Opcion no recomendada: conexion directa a base de datos BioTime

No se recomienda conectar Enertika directamente al PostgreSQL interno de BioTime desde Railway.

Razones:

- El puerto `8082` es web/aplicacion, no base de datos.
- Exponer PostgreSQL publicamente incrementa el riesgo de seguridad.
- BioTime es una aplicacion de terceros; conviene tratar su base como interna.
- La estructura puede cambiar con actualizaciones.

## Reportes encontrados en BioTime

BioTime contiene reportes internos que ayudan a entender su logica:

### Primera entrada / ultima salida

Template:

```text
_planVacations/BioTime/mysite/att/templates/att/report/first_in_last_out.html
```

Endpoint UI interno:

```text
/att/api/firstInLastOutReport/
```

Columnas observadas:

- codigo de empleado
- nombre
- departamento
- fecha de asistencia
- dia de semana
- entrada
- salida
- tiempo total

### Primer y ultimo punch

Template:

```text
_planVacations/BioTime/mysite/att/templates/att/report/firstlastreport.html
```

Endpoint UI interno:

```text
/att/api/firstLastReport/
```

### Tarjeta de tiempo total

Template:

```text
_planVacations/BioTime/mysite/att/templates/att/report/totaltimecardreport.html
```

Endpoint UI interno:

```text
/att/api/totalTimeCardReport/
```

Incluye campos como:

- entrada
- salida
- entrada valida
- salida valida
- tiempo total
- tiempo trabajado
- retardos
- salida temprana
- ausencia
- permisos/licencias
- overtime normal
- overtime fin de semana
- overtime feriado

### Reporte de overtime

Template:

```text
_planVacations/BioTime/mysite/att/templates/att/report/overtimereport.html
```

Endpoint UI interno:

```text
/att/api/overtimeReport/
```

Este reporte existe, pero no debe ser usado como fuente final para Enertika. Puede servir como referencia durante validacion.

## Limitacion del reporte nativo de BioTime

El SQL interno del reporte `firstlast` agrupa las checadas por fecha calendario:

```sql
to_char(c.punch_time, 'yyyy-mm-dd')
```

Esto puede ser insuficiente para Enertika, porque si un empleado entra un dia y sale despues de medianoche, BioTime puede separar la salida en el dia calendario siguiente.

Para nuestro caso, el reporte debe calcularse por **fecha laboral**, no solamente por fecha calendario.

## Modelo recomendado en Enertika

BioTime debe ser tratado como fuente de checadas crudas. Enertika debe calcular la asistencia diaria.

Flujo recomendado:

1. Sincronizar empleados/departamentos de BioTime.
2. Mapear empleados BioTime con usuarios/empleados de Enertika.
3. Sincronizar checadas crudas por API.
4. Guardar checadas sin modificar.
5. Calcular asistencia diaria en Enertika.
6. Cruzar con vacaciones aprobadas.
7. Calcular horas trabajadas.
8. Calcular horas extra.
9. Mostrar el reporte consolidado.

## Sucursal

Si se puede configurar sucursal, pero conviene hacerlo de forma explicita en Enertika.

BioTime tiene entidades utiles:

- `personnel_department`
- `personnel_area`
- area asignada al dispositivo
- departamento asignado al empleado

Sin embargo, esas entidades no necesariamente representan la regla operativa de Enertika. Por eso se recomienda crear catalogo propio de sucursales y mapear BioTime hacia Enertika.

Modelo sugerido:

```text
tb_cat_sucursales
tb_biotime_empleado_map
tb_horarios_sucursal
tb_horarios_sucursal_dias
```

Opciones para mapeo:

- Mapear `deptnumber` de BioTime a sucursal.
- Mapear `area_code` de BioTime a sucursal.
- Mapear dispositivo/terminal a sucursal.
- Permitir asignacion manual de sucursal por empleado en Enertika.

La opcion mas flexible es permitir asignacion manual en Enertika y usar BioTime solo como ayuda inicial.

## Vacaciones

El modulo de vacaciones ya cuenta con las tablas necesarias para detectar vacaciones aprobadas:

- `tb_solicitudes_ausencia`
- `tb_cat_tipos_ausencia`

Regla:

```text
tipo_ausencia.slug = 'vacaciones'
estado = 'aprobado'
fecha_laboral BETWEEN fecha_inicio AND fecha_fin
```

Comportamiento esperado:

| Checadas | Vacaciones aprobadas | Estado sugerido |
| --- | --- | --- |
| No | Si | Vacaciones |
| No | No | Sin registro / Falta |
| Si | No | Asistencia |
| Si | Si | Checada en vacaciones / Trabajo en vacaciones |

El ultimo caso debe definirse con negocio: puede requerir alerta, ajuste manual o autorizacion.

## Calculo de primera entrada y ultima salida

La primera entrada y ultima salida deben calcularse desde las checadas crudas.

Reglas base:

1. Tomar las checadas del empleado dentro de la ventana de la fecha laboral.
2. Si `punch_state` es confiable:
   - estados de entrada: `0` o `I`
   - estados de salida: `1` u `O`
3. Si `punch_state` no es confiable:
   - primera entrada = primera checada de la ventana
   - ultima salida = ultima checada de la ventana
4. Guardar tambien inconsistencias:
   - solo entrada
   - solo salida
   - multiples entradas/salidas
   - checadas duplicadas
   - checada fuera de ventana

## Fecha laboral y checadas despues de medianoche

No debe usarse solamente la fecha calendario de la checada.

Cada sucursal debe tener un horario configurado. A partir de ese horario se calcula una ventana laboral.

Ejemplo:

```text
Sucursal: Planta A
Entrada: 08:00
Salida: 17:00
Margen antes de entrada: 120 min
Margen despues de salida: 360 min
```

Ventana para fecha laboral `2026-05-12`:

```text
2026-05-12 06:00 -> 2026-05-12 23:00
```

Ejemplo con turno que cruza medianoche:

```text
Entrada: 20:00
Salida: 05:00
Margen antes de entrada: 120 min
Margen despues de salida: 180 min
```

Ventana para fecha laboral `2026-05-12`:

```text
2026-05-12 18:00 -> 2026-05-13 08:00
```

En este caso, una salida a `2026-05-13 00:30` pertenece a la fecha laboral `2026-05-12`.

## Horas trabajadas

Las horas trabajadas se calculan en Enertika:

```text
horas_trabajadas = ultima_salida - primera_entrada - descansos_no_pagados
```

Consideraciones:

- tolerancia de entrada
- tolerancia de salida
- comida/descanso fijo
- descanso registrado por checadas, si se requiere en el futuro
- checadas incompletas
- turnos que cruzan medianoche
- feriados
- descansos semanales
- vacaciones aprobadas

## Horas extra

Decision:

> Las horas extra se calculan en Enertika Ops Core y no se obtienen de BioTime.

Razon:

- Las reglas de horas extra dependen de sucursal.
- Las vacaciones y ausencias aprobadas viven en Enertika.
- Se necesita controlar la fecha laboral cuando hay salidas despues de medianoche.
- BioTime calcula overtime con su propia configuracion interna.
- El reporte BioTime puede servir para comparar, pero no debe ser fuente final.

Regla inicial sugerida:

```text
minutos_extra = max(0, minutos_trabajados - minutos_programados - tolerancia_extra)
```

Clasificaciones posibles:

- horas extra normales
- horas extra en descanso
- horas extra en feriado
- horas extra nocturnas, si aplica
- horas extra autorizadas
- horas extra no autorizadas

La autorizacion de horas extra puede ser una fase posterior.

## Tablas sugeridas

Estas tablas son propuesta preliminar. Deben implementarse con migracion usando la skill `/schema`.

### `tb_cat_sucursales`

Catalogo interno de sucursales.

Campos sugeridos:

- `id`
- `nombre`
- `codigo`
- `activa`
- `created_at`
- `updated_at`

### `tb_biotime_empleado_map`

Mapeo entre BioTime y Enertika.

Campos sugeridos:

- `id`
- `usuario_id`
- `empleado_datos_id`
- `biotime_emp_id`
- `biotime_emp_code`
- `biotime_pin`
- `biotime_deptnumber`
- `biotime_deptname`
- `sucursal_id`
- `activo`
- `created_at`
- `updated_at`

### `tb_biotime_checks`

Checadas crudas sincronizadas desde BioTime.

Campos sugeridos:

- `id`
- `biotime_transaction_id`
- `biotime_emp_code`
- `usuario_id`
- `check_time`
- `check_time_mx`
- `punch_state`
- `verify_type`
- `terminal_sn`
- `terminal_alias`
- `deptnumber`
- `deptname`
- `raw_payload`
- `created_at`

Restriccion sugerida:

```text
UNIQUE (biotime_transaction_id)
```

Fallback si no hay `id` confiable:

```text
UNIQUE (biotime_emp_code, check_time)
```

### `tb_horarios_sucursal`

Configuracion general del horario por sucursal.

Campos sugeridos:

- `id`
- `sucursal_id`
- `nombre`
- `activo`
- `margen_entrada_antes_min`
- `margen_salida_despues_min`
- `tolerancia_extra_min`
- `descuento_comida_min`
- `created_at`
- `updated_at`

### `tb_horarios_sucursal_dias`

Detalle por dia de semana.

Campos sugeridos:

- `id`
- `horario_sucursal_id`
- `dia_semana`
- `hora_entrada`
- `hora_salida`
- `minutos_programados`
- `cruza_medianoche`
- `es_laboral`

### `tb_asistencia_diaria`

Resultado calculado por Enertika.

Campos sugeridos:

- `id`
- `usuario_id`
- `sucursal_id`
- `fecha_laboral`
- `primera_entrada`
- `ultima_salida`
- `minutos_trabajados`
- `minutos_programados`
- `minutos_extra`
- `estado`
- `tiene_vacaciones`
- `solicitud_ausencia_id`
- `observaciones`
- `calculated_at`
- `created_at`
- `updated_at`

Estados sugeridos:

- `asistencia`
- `vacaciones`
- `sin_registro`
- `falta`
- `incompleto`
- `descanso`
- `feriado`
- `checada_en_vacaciones`

### `tb_asistencia_sync_runs`

Bitacora de sincronizacion.

Campos sugeridos:

- `id`
- `started_at`
- `finished_at`
- `status`
- `from_transaction_id`
- `to_transaction_id`
- `records_read`
- `records_inserted`
- `records_skipped`
- `error_message`

## Worker

Las tareas periodicas deben correr en `worker.py`, no en `main.py`.

Proceso sugerido:

1. `sync_biotime_transactions_periodically()`
2. Consultar BioTime por `id` incremental o por ventana de fechas.
3. Insertar checadas nuevas en `tb_biotime_checks`.
4. Identificar empleados y fechas afectadas.
5. Recalcular asistencia diaria.
6. Incluir dia anterior cuando haya checadas despues de medianoche.

## Seguridad

Recomendaciones:

- No exponer credenciales de BioTime.
- No guardar usuario, contrasena, cookies, `csrftoken` ni `sessionid` en frontend.
- Usar variables de entorno o `ConfigService`.
- Preferir HTTPS delante de BioTime si se consumira por IP publica.
- Restringir acceso por IP si es posible.
- No exponer PostgreSQL de BioTime hacia internet.
- Registrar errores con logging estructurado, sin secretos.

## Configuracion desde Admin

La configuracion operativa de BioTime se administra desde el modulo **Admin**, dentro de configuracion global. Esto evita ejecutar manualmente `UPDATE tb_configuracion_global` para los valores principales.

Campos configurables:

- `BIOTIME_BASE_URL`: URL base del servidor BioTime, ejemplo `http://IP_PUBLICA:8082`.
- `BIOTIME_USERNAME`: usuario de BioTime PRO.
- `BIOTIME_PASSWORD`: contrasena de BioTime PRO. En UI se captura como password y no se muestra el valor guardado.
- `BIOTIME_SYNC_ACTIVO`: activa o pausa la sincronizacion periodica.
- `BIOTIME_SYNC_INTERVAL_SEG`: intervalo del worker para consultar BioTime.
- `BIOTIME_SYNC_PAGE_SIZE`: cantidad maxima de transacciones por pagina.
- `BIOTIME_SYNC_LOOKBACK_HRS`: ventana de busqueda hacia atras para cubrir desfases o reintentos.
- `BIOTIME_SYNC_TIMEOUT_SEG`: timeout HTTP para la API BioTime.
- `ASISTENCIA_RECALC_DIAS`: dias recientes que se recalculan despues de cada sync.

La UI incluye accion de prueba de conexion. Esa prueba inicia sesion en BioTime PRO y consulta
`/iclock/transaction/table/` en una ventana reciente sin exponer credenciales.

## Reportes descargables en RH

El modulo **RH** incluye una pestana de reportes con filtros por rango de fechas y empleado. Para asistencia y horas extra tambien permite filtrar por sucursal y estado.

Reportes Excel disponibles:

- `GET /rrhh/reportes/asistencia.xlsx`: asistencia diaria con primera entrada, ultima salida, horas trabajadas, horas programadas, horas extra, estado y observaciones.
- `GET /rrhh/reportes/vacaciones.xlsx`: solicitudes de vacaciones cruzadas por rango, empleado y estado.
- `GET /rrhh/reportes/horas-extra.xlsx`: asistencia diaria filtrada a registros con minutos extra mayores a cero.

Los reportes salen desde las tablas calculadas de Enertika, no desde el reporte final de BioTime. BioTime solo alimenta checadas crudas.

## Implementacion actual

Archivos principales:

- `migrations/070_asistencia_biotime.sql`: tablas de sucursales, horarios, mapeo BioTime, checadas crudas, asistencia diaria, bitacora de sync y claves de configuracion.
- `modules/asistencia/`: cliente BioTime, servicio de sincronizacion, calculo de asistencia y endpoints API.
- `modules/rrhh/`: panel de reportes y exportaciones Excel.
- `modules/admin/`: configuracion BioTime y prueba de conexion.
- `worker.py`: tarea periodica de sincronizacion BioTime.

Estado funcional:

- BioTime se conecta por API HTTP usando `BIOTIME_BASE_URL`, `BIOTIME_USERNAME` y `BIOTIME_PASSWORD`.
- El cliente usa sesion Django, cookies y CSRF contra endpoints BioTime PRO.
- Las checadas de `/iclock/transaction/table/` se normalizan y se guardan como eventos crudos.
- Los empleados de `/personnel/employee/table/` se usan para alimentar `tb_biotime_empleado_map`.
- La asistencia diaria se recalcula por empleado/fecha laboral.
- Vacaciones aprobadas rellenan dias sin checada como `vacaciones`.
- Las horas extra se calculan de este lado, usando horarios por sucursal.
- La clave historica `BIOTIME_ACCESS_KEY` puede existir por la migracion 070, pero queda obsoleta
  para BioTime PRO y no debe usarse en el cliente actual.

## Preguntas originales revisadas

Estas fueron las preguntas de negocio que originaron el GAP. Las decisiones acordadas se documentan
en la siguiente seccion; lo que no quedo cerrado se mantiene como pendiente funcional.

1. Cual sera la fuente de sucursal: manual en Enertika, departamento BioTime, area BioTime o dispositivo.
2. Que tolerancia se aplicara para entrada y salida.
3. Si se descuenta comida automaticamente.
4. Si las horas extra requieren autorizacion.
5. Como se reporta una checada durante vacaciones aprobadas.
6. Que pasa con empleados sin mapeo BioTime.
7. Si se requieren feriados y descansos oficiales por sucursal.

## Decisiones acordadas 2026-05-13

### Sucursal

La sucursal oficial se define manualmente en Enertika Ops Core. BioTime puede aportar datos de
departamento, area o dispositivo como referencia, pero no debe ser la fuente final de sucursal.

Implementacion relacionada:

- Existe `tb_cat_sucursales` como catalogo.
- Existe `tb_empleados_datos.sucursal_id` para guardar la sucursal oficial del empleado.
- Existe `tb_biotime_empleado_map.sucursal_id` para conservar un mapeo operativo BioTime cuando aplique.
- La edicion de empleado en RRHH debe mostrar un dropdown de sucursales activas.

### Mapeo Enertika/BioTime

El usuario logueado en Enertika se identifica por `tb_usuarios.id_usuario` y correo Microsoft/Azure.
BioTime identifica empleados principalmente por `pin` / `emp_code`.

Regla de mapeo:

1. Usar match automatico por correo solo cuando BioTime exponga `email`, el correo no este vacio y
   coincida exactamente con `tb_usuarios.email`.
2. Si no hay correo, usar match por codigo/PIN contra `tb_empleados_datos.numero_empleado` o
   `tb_empleados_datos.biotime_emp_code`.
3. Usar coincidencia de nombre solo como sugerencia para RH, no como mapeo automatico definitivo.
4. Las checadas sin mapeo deben quedar disponibles para una cola de revision, no perderse.

Hallazgo BioTime:

- La API de transacciones de BioTime PRO es `GET /iclock/transaction/table/`.
- Las checadas llegan principalmente con `emp_code`, `punch_time`, `punch_state`,
  `verify_type`, `terminal_sn` y `terminal_alias`.
- La API de transacciones no trae correo y no trae `deptnumber`/`deptname` de forma directa.
- La API de empleados de BioTime PRO es `GET /personnel/employee/table/` y expone
  `emp_code`, `first_name`, `last_name`, `email` y `department_id`.
- El departamento debe resolverse via `department_id` contra `personnel_department` si se necesita
  guardar `biotime_deptnumber`/`biotime_deptname`.

Implementado:

- `BioTimeClient.fetch_employees()` consulta `/personnel/employee/table/`.
- El sync consulta empleados BioTime PRO y normaliza `emp_code` como string.
- Antes de insertar checadas, se actualiza `tb_biotime_empleado_map` por email exacto o fallback
  por codigo/PIN.

Pendiente posterior:

- Vista de revision para empleados/checadas sin mapear.
- Validar contra el servidor real si `personnel/employee/table/` entrega `last_name`, `email` y
  `department_id` en `rows`.
- Enriquecer el mapeo de nombre completo y departamento si RH requiere ver esos datos en ECO.

### Comida

No se descuenta comida automaticamente.

Aunque el schema actual tiene `tb_horarios_sucursal.descuento_comida_min` y la logica lo resta si es
mayor a cero, la regla de negocio acordada es mantenerlo en `0` y no exponerlo como configuracion
operativa por ahora.

### Horas extra

Las horas extra se calculan automaticamente en Enertika, pero para pago/validacion requieren
aprobacion.

Regla propuesta:

- Aprobador principal: jefe directo o aprobador asignado del empleado.
- RH/Admin: puede revisar, descargar reportes y corregir/aprobar por excepcion.
- La aprobacion de horas extra debe vivir en una fase posterior con estado propio; el reporte actual
  puede mostrar y exportar horas extra calculadas aunque todavia no esten aprobadas.

UI implementada como feedback inicial:

- `Mi Perfil > Mi Equipo` muestra vacaciones aprobadas del equipo, quien esta de vacaciones hoy,
  proximas vacaciones aprobadas y horas extra calculadas pendientes de aprobacion.
- RH ve el consolidado en `RRHH > Reportes` / `RRHH > Asistencia` y puede descargar Excel sin
  depender de que las horas extra esten aprobadas.

Pendiente funcional:

- Agregar estado persistido de aprobacion de horas extra y acciones de aprobar/rechazar.

### Checada en vacaciones

Si existe checada durante vacaciones aprobadas:

- El estado debe ser `checada_en_vacaciones`.
- No se deben contar horas extra.
- RH debe poder verlo como alerta en reportes.

### Tolerancias de entrada y salida

Quedan documentadas para una futura migracion, sin uso en el calculo actual:

- `tolerancia_entrada_min`
- `tolerancia_salida_min`

No se usaran en el calculo actual. Quedan preparadas para una fase posterior de retardos/salidas
tempranas.

Separacion conceptual:

- `margen_entrada_antes_min` y `margen_salida_despues_min` sirven para construir la ventana donde se
  buscan checadas.
- `tolerancia_entrada_min` y `tolerancia_salida_min` serviran para clasificar retardos o salidas
  tempranas cuando se implemente esa regla.

## Plan de implementacion propuesto

### Fase 1: Base de datos y configuracion

- Crear catalogo de sucursales.
- Crear mapeo empleado Enertika/BioTime.
- Crear tablas de checadas crudas.
- Crear tablas de horarios por sucursal.
- Crear tabla de asistencia diaria calculada.

### Fase 2: Sincronizacion BioTime

- Crear cliente BioTime.
- Configurar base URL, usuario y contrasena.
- Autenticar sesion Django con CSRF/cookies.
- Sincronizar transacciones por ventana de fechas y paginacion `page`/`limit`.
- Guardar payload crudo.
- Registrar bitacora de sync.

### Fase 3: Calculo de asistencia

- Calcular fecha laboral por horario de sucursal.
- Resolver primera entrada y ultima salida.
- Calcular minutos trabajados.
- Detectar checadas incompletas.
- Manejar turnos despues de medianoche.

### Fase 4: Cruce con vacaciones

- Consultar vacaciones aprobadas.
- Marcar dias sin checada como `vacaciones`.
- Detectar checadas en vacaciones.

### Fase 5: Horas extra

- Calcular horas extra en Enertika.
- Aplicar tolerancias por sucursal.
- Separar horas extra normales, descanso o feriado si negocio lo requiere.
- No depender del overtime calculado por BioTime.

### Fase 6: UI y reportes

- Crear vista de asistencia.
- Filtros por fecha, sucursal, empleado y estado.
- Mostrar primera entrada, ultima salida, horas trabajadas, vacaciones y horas extra.
- Exportar Excel de asistencia, vacaciones y horas extra desde RH.

### Fase 7: Administracion

- Gestionar URL base, usuario, contrasena y estado del sync desde Admin.
- Probar conexion con BioTime desde Admin.
- Mantener contrasena, cookies y CSRF fuera del HTML renderizado y de logs.

## Resumen de decision

BioTime sera usado como sistema receptor de dispositivos ZKTeco y fuente de checadas crudas.

Enertika Ops Core sera responsable de:

- mapear empleados
- definir sucursales
- configurar horarios por sucursal
- calcular fecha laboral
- calcular primera entrada y ultima salida
- calcular horas trabajadas
- cruzar con vacaciones aprobadas
- calcular horas extra
- generar el reporte operativo final

Las horas extra no se obtendran de BioTime como dato final.
