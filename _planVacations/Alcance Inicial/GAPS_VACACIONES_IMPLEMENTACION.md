# Gaps - Vacaciones, Perfil y RRHH

> Fecha de analisis: 2026-05-12  
> Branch revisado: `feature/vacaciones`  
> Actualizacion: 2026-05-13  
> Plan base: `_planVacations/PLAN_VACACIONES_Y_PERFIL.md`, `_planVacations/VACACIONES_REFINAMIENTOS.md`, `_planVacations/BIOTIME_ASISTENCIA_VACACIONES.md` y `_planVacations/BIOTIME_PRO_API.md`  
> Migraciones reportadas como ejecutadas por el usuario: `066`, `067`, `068`, `069`, `070` y `071`.

## Resumen ejecutivo

La implementacion actual cierra los gaps funcionales principales del plan base de vacaciones/perfil: perfil de vacaciones, solicitudes, firma por archivo y dibujo, PDF, RRHH operativo, tab `Admin`, CRUD de catalogos, generacion/edicion de feriados, fallback de aprobador, adjunto PDF en correos finales, export Excel, validacion de firma y tareas worker.

La revision del 2026-05-13 agrega BioTime/asistencia y arquitectura de RRHH. Se corrigio el SQL directo que habia quedado en `modules/rrhh/service.py`, moviendo esas consultas a `modules/rrhh/db_service.py`. Tambien se alinearon permisos RRHH a RBAC, se agrego mapeo automatico BioTime por correo/codigo, recalc de asistencia al resolver vacaciones, fecha MX parametrizada en solicitudes vencidas y textos BioTime en espanol.

Actualizacion BioTime PRO: `_planVacations/BIOTIME_PRO_API.md` confirma que la instancia objetivo es BioTime PRO 1.0.6.5. Por eso el conector ya no debe usar `BIOTIME_ACCESS_KEY` ni endpoints `api/v2`; debe usar login Django con CSRF/cookies, `GET /iclock/transaction/table/` y `GET /personnel/employee/table/`.

## Actualizacion 2026-05-13

### Gaps corregidos en codigo

| Gap | Evidencia previa | Correccion | Estado |
|---|---|---|---|
| SQL directo en `modules/rrhh/service.py` | El service ejecutaba `conn.fetchrow`, `conn.execute` y `conn.fetch` con SQL embebido | Se creo `modules/rrhh/db_service.py` y `service.py` ahora solo orquesta llamadas a `rrhh_db`, `vac_db` y `asistencia_db` | Cerrado |
| Configuracion `VACACIONES_MESES_EXPIRACION` | La logica leia la clave, pero no habia valor inicial ni UI Admin | `071_vacaciones_config_meses_expiracion.sql`, endpoint Admin y formulario RRHH | Cerrado |
| Vista HTML de asistencia | Solo habia endpoint JSON/export Excel | Tab `RRHH > Asistencia` con filtros y tabla | Cerrado |
| Reglas de negocio BioTime/asistencia | Faltaba confirmar sucursal, mapeo, comida, horas extra y checadas en vacaciones | Decisiones documentadas en `BIOTIME_ASISTENCIA_VACACIONES.md`: sucursal manual, mapeo por correo/codigo, sin descuento de comida, horas extra con aprobacion, checada en vacaciones sin extra | Cerrado |
| `tb_cat_sucursales.activa` vs consulta `is_active` | `modules/asistencia/db_service.py:get_sucursales()` consultaba una columna inexistente en la migracion 070 | La consulta ahora usa `activa = true` y la edicion de empleado consume el catalogo para dropdown | Cerrado |
| Feedback visual en `Mi Perfil > Mi Equipo` | El jefe no veia vacaciones aprobadas del equipo, quien esta de vacaciones ni horas extra pendientes | Se agrego vista visual con vacaciones actuales, proximas aprobadas, horas extra calculadas pendientes de aprobacion y balances del equipo | Cerrado |
| Mapeo automatico BioTime/ECO | Solo se resolvia por codigo/PIN ya configurado | `BioTimeClient` consulta empleados BioTime PRO en `/personnel/employee/table/`; el sync mapea por email exacto y cae a codigo/PIN contra datos de empleado | Cerrado |
| Adaptacion cliente BioTime PRO 1.0.x | El supuesto inicial usaba API key y endpoints `api/v2` | El cliente actual usa usuario/contrasena, login Django con CSRF/cookies, `/iclock/transaction/table/` y `/personnel/employee/table/` | Cerrado en cliente |
| Permisos RRHH con `es_rh` | Vacaciones, worker y workflow mezclaban bandera legacy con RBAC | Se migro a `user_has_module_access("rrhh", viewer/editor)` y consultas por `tb_permisos_modulos` | Cerrado |
| Recalculo asistencia al resolver vacaciones | Aprobar/cancelar/rechazar no refrescaba `tb_asistencia_diaria` | El servicio recalcula el rango de la solicitud cuando cambia estado | Cerrado |
| Solicitudes vencidas y timezone | Worker usaba fecha SQL calculada en BD | Ahora usa `today_mx()` como parametro bound | Cerrado |
| Textos Admin BioTime en ingles | UI visible tenia `Access key`, `Sync activo`, `Lookback`, `Timeout` | Labels y placeholders traducidos a espanol | Cerrado |

### Nuevos gaps y pendientes funcionales

| Gap | Impacto | Estado |
|---|---|---|
| Falta CRUD Admin para catalogos BioTime/asistencia | Sin UI para sucursales, horarios y mapeo empleado-BioTime, el worker no puede operar completo para RH | Pendiente |
| Aprobacion persistida de horas extra | `Mi Equipo` muestra horas extra calculadas como pendientes, pero aun falta schema/flujo para aprobar o rechazar | Pendiente |
| Tolerancias entrada/salida | `tolerancia_entrada_min` y `tolerancia_salida_min` estan documentadas para fase posterior, sin uso actual | Pendiente |
| Incapacidad sin comprobante medico | El plan pide adjunto/evidencia para incapacidad; no hay schema ni upload | Pendiente |
| Validacion BioTime PRO en servidor real | Falta confirmar que `personnel/employee/table/` entregue `email`, `last_name` y `department_id`; tambien falta lookup de `personnel_department` si se requieren nombres de departamento | Pendiente |
| Vista de revision de checadas sin mapear | El sync puede guardar checadas sin `usuario_id`; RH necesita una cola visible para corregir mapeos manualmente | Pendiente |

## Matriz final de permisos RRHH

| Usuario | Permiso modulo `rrhh` | Alcance |
|---|---|---|
| `USER` | `viewer` | Entra a RRHH, consulta informacion y descarga Excel. No modifica. |
| `USER` | `editor` | Edita operacion diaria de RH: empleados, aprobaciones, solicitudes y festivos operativos. |
| `MANAGER` | `editor` | Edita operacion diaria y configuracion global desde `RRHH > Admin`. |
| `USER` o `MANAGER` | `admin` | Acceso total al modulo RRHH. |
| `ADMIN` global | cualquiera | Acceso total por bypass global. |

Regla aplicada:
- Lectura y descargas: `require_module_access("rrhh", "viewer")`.
- Operacion diaria: `require_module_access("rrhh", "editor")`.
- Configuracion global en `RRHH > Admin`: `require_manager_access("rrhh", "editor")`.

## Respuestas directas a las dudas

### 1. Se puede actualizar dinamicamente year with year los feriados?

Estado actual: si.

La tabla `tb_cat_festivos` sigue siendo la fuente dinamica para el calculo de dias habiles. La implementacion agrega generacion anual de feriados oficiales mexicanos para anos futuros y permite ejecutarla desde `RRHH > Admin` cuando RH detecte inconsistencias o necesite precargar un ano.

La actualizacion anual queda cubierta por worker y por accion manual. Si la regla oficial cambia, RH puede corregir manualmente el catalogo sin migracion.

### 2. RH puede actualizar manualmente estas fechas?

Estado actual: si.

RH con permisos suficientes puede crear, editar y eliminar festivos desde RRHH. Para configuracion global dentro de `Admin` se requiere `MANAGER + rrhh editor`, `rrhh admin` o `ADMIN` global. La vista operativa de festivos se mantiene para uso diario.

### 3. RH puede actualizar los tipos de permisos?

Estado actual: si.

Los tipos de ausencia existen en `tb_cat_tipos_ausencia`, el formulario los lee dinamicamente y `RRHH > Admin` permite administrarlos. Los tipos base usados por la logica de negocio, como vacaciones y extraordinaria, deben tratarse como catalogos protegidos para no romper reglas especiales.

### 4. RH puede actualizar dias por antiguedad?

Estado actual: si.

Los dias por antiguedad existen en `tb_cat_dias_vacaciones`, la logica de balance los lee dinamicamente y `RRHH > Admin` permite modificar la politica sin una nueva migracion. Como los periodos se calculan al vuelo, los cambios aplican al recalcular balances.

### 5. Incluir una tab llamada Admin dentro de RH para estas modificaciones

Estado actual: implementado.

RRHH cuenta con tab `Admin` para concentrar configuracion global:
- Festivos y generacion anual.
- Tipos de permisos.
- Dias por antiguedad.
- Parametros de vacaciones y alertas agregados por migraciones posteriores.

### 6. Solo Manager editor podra entrar y editar Admin

Estado actual: implementado con la regla final acordada.

La tab `Admin` usa `require_manager_access("rrhh", "editor")`, que permite:
- `ADMIN` global.
- `rrhh admin`.
- `MANAGER + rrhh editor`.

El usuario `USER + rrhh editor` mantiene capacidad de editar operacion diaria, pero no configuracion global. El usuario `USER + rrhh viewer` puede ver y descargar informacion, sin modificar.

### 7. Donde RH puede editar el jefe que autoriza a cada empleado?

Estado actual: en `RRHH > Empleados > Editar`.

La edicion del empleado permite definir:
- `Aprobador de vacaciones`: autorizador principal.
- `Jefes directos`: tambien se consideran para aprobaciones y visibilidad de equipo.

La notificacion de nueva solicitud usa fallback: aprobador designado, despues jefes directos y finalmente RH/Admin cuando no exista responsable especifico.

### 8. Para cargar la firma solo es con archivos o el usuario tiene dibujo a mano alzada?

Estado actual: ambas opciones.

En `Mi Perfil > Mi Firma` el usuario puede:
- Subir archivo de firma.
- Dibujar firma a mano alzada.

La validacion de subida queda restringida a PNG real, con limite de dimensiones y tamano. `signature_pad` se sirve localmente desde `static/vendor/signature_pad.min.js`, sin depender de CDN.

## Comparacion plan vs implementacion

| Area | Plan | Implementacion actual | Estado |
|---|---|---|---|
| Migracion 066 | Tablas base vacaciones/RRHH | Ejecutada segun usuario | Cerrado |
| Migracion 067 | Modulo RRHH en catalogo | Ejecutada segun usuario | Cerrado |
| Migracion 068 | Configuracion admin vacaciones/RRHH | Ejecutada segun usuario | Cerrado |
| Migracion 069 | Worker y notificaciones adicionales | Ejecutada segun usuario | Cerrado |
| Perfil | `/perfil/ui` para todos | Implementado | Cerrado |
| Home default | Si no hay `modulo_preferido`, ir a `/perfil/ui` | Ajustado para caer a perfil cuando no hay preferencia | Cerrado |
| Balance vacaciones | Periodos al vuelo, expiracion configurable, FIFO | Implementado con catalogos dinamicos | Cerrado |
| Dias habiles | L-V menos festivos | Implementado contra `tb_cat_festivos` | Cerrado |
| Solicitudes | CRUD, solapamiento, firma, notificacion | Implementado con bloqueo de firma antes de envio | Cerrado |
| Tipos de ausencia | Catalogo DB | Lectura dinamica + CRUD Admin | Cerrado |
| Dias por antiguedad | Catalogo DB | Lectura dinamica + CRUD Admin | Cerrado |
| Festivos | Admin RH | CRUD, generacion anual y edicion | Cerrado |
| RRHH dashboard | Hoy, aprobaciones, empleados, festivos, solicitudes | Implementado + tab Admin | Cerrado |
| Empleados | RH edita datos, aprobador, jefes, ajuste | Implementado | Cerrado |
| Equipo | Jefes/aprobadores ven balances | Implementado | Cerrado |
| Firmas | BYTEA, upload y canvas | Implementado con validacion PNG y libreria local | Cerrado |
| PDF | PDF con firmas | Implementado | Cerrado |
| Email final | Solicitante + CC RH con PDF adjunto | Implementado | Cerrado |
| Recordatorios 24h | Worker | Implementado | Cerrado |
| Periodos por expirar | Worker email + in-app, empleado + RH | Implementado con control de envio | Cerrado |
| Solicitudes vencidas | Worker RH + aprobador | Implementado con control anti-duplicados | Cerrado |
| Excel RH | `/rrhh/empleados/exportar-excel` | Implementado para `rrhh viewer` o superior | Cerrado |

## Pendientes no funcionales

1. Pruebas automatizadas.
   - Cubrir logic pura de vacaciones, permisos RRHH, creacion/cancelacion/aprobacion, validacion de firma y worker.

2. Validacion visual/browser.
   - Revisar `Mi Perfil`, solicitudes, firma, RRHH y `RRHH > Admin` en desktop y mobile.

3. Encoding.
   - Confirmar que los archivos nuevos estan guardados en UTF-8 y que la app renderiza acentos correctamente.

4. QA de permisos con usuarios reales.
   - Validar manualmente los cinco perfiles de la matriz final: `USER viewer`, `USER editor`, `MANAGER editor`, modulo `admin` y `ADMIN` global.

## Notas de implementacion

- Las migraciones `066`, `067`, `068` y `069` ya fueron reportadas como ejecutadas; cualquier cambio de schema posterior debe ir en una nueva migracion.
- La tab `Admin` vive dentro del modulo RRHH, no en el modulo global `admin`.
- La descarga Excel queda permitida a `rrhh viewer`, porque la matriz final permite que personal de apoyo consulte y descargue informacion sin modificarla.
- La configuracion global de vacaciones/RRHH queda reservada a `require_manager_access("rrhh", "editor")`.
