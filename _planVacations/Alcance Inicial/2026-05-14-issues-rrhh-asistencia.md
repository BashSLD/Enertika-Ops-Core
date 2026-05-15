# Revision de issues RRHH / Asistencia

Fecha: 2026-05-14

Alcance: revision de codigo sin aplicar correcciones. Este documento resume causa documentada, impacto y correccion recomendada para los issues reportados.

## 1. Horario que cruza medianoche y check por dia

### Comportamiento actual

El checkbox `cruza_medianoche` se recibe desde el formulario de horarios y se guarda por cada dia de la semana.

Referencias:
- `modules/rrhh/router.py` - `_build_horario_dias_form`
- `modules/rrhh/service.py` - `_normalizar_dias_horario`
- `modules/asistencia/logic.py` - `build_labor_window`

El dia marcado se interpreta como el dia de inicio del turno. Por ejemplo, un horario de lunes 22:00 a 06:00 con `cruza_medianoche=true` queda asignado al dia laboral lunes, aunque la salida ocurra el martes.

La ventana laboral se construye desde la fecha laboral y, si el horario cruza medianoche, extiende la salida al dia siguiente. Por eso una checada posterior a medianoche puede pertenecer al resumen del dia anterior.

### Causa

El backend permite marcar `cruza_medianoche` sin validar que la salida sea menor o igual a la entrada. La duracion programada solo suma 24 horas cuando `hora_salida <= hora_entrada`, pero la ventana laboral tambien se extiende si `cruza_medianoche=true`.

Esto significa que un horario normal como 08:00-17:00 con el check marcado puede mantener una duracion programada normal, pero abrir una ventana de checadas hasta el dia siguiente.

### Riesgo

Si se marca el check en un dia que no deberia cruzar medianoche:

- Puede absorber checadas del dia siguiente.
- Puede generar registros diarios incorrectos.
- Puede producir estados `incompleto` por empalme de ventanas.
- Puede afectar calculo de horas trabajadas y horas extra.

Si se marca en un dia no laboral, el backend lo ignora porque `_normalizar_dias_horario` fuerza `cruza_medianoche=false` cuando `es_laboral=false`.

### Correccion recomendada

Validar en backend:

- Si `cruza_medianoche=true`, exigir `hora_salida <= hora_entrada`.
- Si `hora_salida <= hora_entrada`, exigir `cruza_medianoche=true`.
- Si el dia no es laboral, ignorar o limpiar explicitamente horas y `cruza_medianoche`.

Validar en UI:

- Deshabilitar el checkbox `Cruza medianoche` cuando el dia no este marcado como laboral.
- Opcionalmente autoseleccionarlo cuando `hora_salida <= hora_entrada`.
- Mostrar ayuda breve: "El dia seleccionado es el dia de inicio del turno".

## 2. En `/rrhh/admin`, la seccion de feriados debe ser colapsable

### Comportamiento actual

La seccion de feriados ya esta construida como colapsable con Alpine.js.

Referencia:
- `templates/rrhh/partials/admin.html`

El bloque usa `x-data="{ open: true }"` y el contenido se muestra con `x-show="open"`.

### Causa

La seccion inicia abierta por defecto. Aunque tecnicamente es colapsable, visualmente no cumple la expectativa de aparecer colapsada al entrar a Admin.

### Riesgo

- Ocupa demasiado espacio inicial dentro de Admin RRHH.
- Empuja hacia abajo secciones de configuracion que probablemente se usan con mas frecuencia.
- Puede dar la impresion de que no es colapsable si el usuario no interactua con el encabezado.

### Correccion recomendada

Cambiar el estado inicial:

```html
<section x-data="{ open: false }" ...>
```

Tambien conviene agregar `x-cloak` al contenedor que depende de `x-show` para evitar parpadeo visual antes de que Alpine inicialice.

## 3. En la tab de asistencia, el default debe ser el dia en curso

### Comportamiento actual

El endpoint `/rrhh/asistencia` usa por defecto un rango de 7 dias:

```python
fi = fecha_inicio or (hoy - timedelta(days=6))
ff = fecha_fin or hoy
```

Referencia:
- `modules/rrhh/router.py` - `asistencia_panel`

La plantilla solo muestra los valores enviados por el endpoint.

Referencia:
- `templates/rrhh/partials/asistencia.html`

### Causa

El default fue definido como ventana semanal reciente, no como dia actual.

### Riesgo

- Al entrar a la pestaña, el usuario ve registros historicos en lugar de la operacion del dia.
- El volumen de datos inicial puede dificultar la revision diaria.
- Puede confundirse con el comportamiento esperado de reportes.

### Correccion recomendada

Cambiar el default solo para la vista de asistencia:

```python
fi = fecha_inicio or hoy
ff = fecha_fin or hoy
```

Mantener separado el default de reportes, que actualmente usa 30 dias en `get_reportes_ctx`.

## 4. Por que en la seccion empleado aparece la etiqueta `estado incompleto`

### Comportamiento actual

La etiqueta `incompleto` no viene de la tabla de empleados ni de datos laborales del empleado. Viene del resumen de asistencia diaria.

Referencias:
- `modules/asistencia/logic.py` - `calcular_resumen_dia`
- `templates/rrhh/partials/asistencia.html`

La logica marca `estado = "incompleto"` cuando:

- Hay menos de dos checadas dentro de la ventana laboral.
- La ultima salida no es posterior a la primera entrada.

Tambien registra observaciones cuando faltan estados confiables de entrada o salida.

### Causa

Para un dia en curso, es normal que exista una sola checada de entrada y aun no exista salida. La logica actual no distingue entre "jornada incompleta porque aun esta en curso" y "registro incompleto definitivo".

Tambien puede aparecer por:

- Salida fuera de la ventana laboral configurada.
- Turno nocturno mal configurado.
- Checada sincronizada sin estado confiable de entrada/salida.
- Solo una checada registrada en BioTime.

### Riesgo

- Durante el dia, empleados activos pueden aparecer como `incompleto` aunque no haya error.
- El usuario puede interpretar el estado como incidencia definitiva antes del cierre de jornada.
- En turnos nocturnos, una mala configuracion de `cruza_medianoche` puede multiplicar falsos `incompleto`.

### Correccion recomendada

Opcion simple de UI:

- Si `fecha_laboral` es hoy y la jornada aun no termina, mostrar `En curso` en la UI aunque el estado guardado siga siendo `incompleto`.

Opcion mas correcta de modelo:

- Agregar un estado real `en_curso` en `tb_asistencia_diaria.estado`.
- Requiere migracion SQL para ampliar el constraint `ck_asistencia_estado`.
- Ajustar `ASISTENCIA_ESTADOS`.
- Ajustar `calcular_resumen_dia` para devolver `en_curso` cuando aplique.
- Ajustar la plantilla de asistencia y reportes para mostrarlo en espanol.

## 5. Modal `Editar datos de empleado`

### Comportamiento actual

El modal de empleados se abre desde `templates/rrhh/partials/empleados_lista.html` y carga el formulario `templates/rrhh/partials/empleado_editar.html`.

Referencias:
- `templates/rrhh/partials/empleados_lista.html` - modal `#empleado-modal`
- `templates/rrhh/partials/empleado_editar.html` - formulario de edicion
- `modules/rrhh/router.py` - `empleado_editar_form` y `empleado_guardar`
- `modules/rrhh/service.py` - `get_empleado_edit_ctx` y `guardar_empleado`
- `modules/vacaciones/db_service.py` - `get_empleado_datos` y `upsert_empleado_datos`

El modal se cierra al hacer click fuera porque el contenedor interno tiene `@click.outside="open = false"`. El requerimiento es cerrarlo solamente desde la X.

El boton `Guardar cambios` no esta completando correctamente en navegador. En consola aparece `htmx:targetError`.

### Causa del `htmx:targetError`

El formulario usa:

```html
hx-target="#toast-container"
```

Pero el layout global no tiene un nodo con id `toast-container`. El contenedor real de toasts es:

```html
<div id="global-toast-container" ...></div>
```

Ademas, `templates/shared/toast.html` ya responde con OOB hacia `#global-toast-container`:

```html
<div hx-swap-oob="afterbegin:#global-toast-container">
```

Por eso HTMX no encuentra el target solicitado por el formulario y dispara `htmx:targetError`.

### Correccion recomendada para guardado

Usar un target existente o no usar target visible para el formulario:

```html
hx-target="this"
hx-swap="none"
```

La respuesta puede seguir usando `shared/toast.html` porque ya inserta el toast por OOB en `#global-toast-container`.

Tambien se recomienda capturar errores de base de datos especificos en `empleado_guardar`, especialmente duplicados por `biotime_emp_code`, para devolver un toast claro en lugar de un error generico.

### Overlay al guardar

Actualmente no hay overlay local en el modal. El usuario no recibe feedback claro durante el POST.

Correccion recomendada:

- Agregar estado Alpine local, por ejemplo `saving`.
- Activarlo con `@htmx:before-request="saving = true"`.
- Desactivarlo con `@htmx:after-request="saving = false"`.
- Mostrar una capa absoluta sobre el formulario o el cuerpo del modal con texto en espanol, por ejemplo `Guardando cambios...`.
- Deshabilitar el boton mientras `saving` sea `true`.

### Cierre solo con X

Comportamiento actual:

- Click fuera del panel cierra el modal.
- X tambien cierra el modal.

Correccion recomendada:

- Quitar `@click.outside="open = false"` del panel.
- Mantener el boton X como unico cierre explicito.
- Opcionalmente limpiar el contenido del modal al cerrar para evitar mostrar datos del empleado anterior al reabrir.

### Puesto debe priorizar Microsoft

El login y la sincronizacion Microsoft ya guardan `jobTitle` en `tb_usuarios.puesto`.

Referencias:
- `modules/auth/router.py` - sincroniza `profile.get("jobTitle")`
- `modules/admin/service.py` - `sync_ms_profiles`
- `migrations/074_ubicaciones_y_puesto.sql` - agrega `tb_usuarios.puesto`

Pero el formulario de empleado solo usa fallback de Microsoft para `departamento`:

```html
value="{{ empleado.departamento if (empleado and empleado.departamento) else (usuario.get('department') or '') }}"
```

Para `puesto`, solo usa `empleado.puesto`:

```html
value="{{ empleado.puesto if empleado else '' }}"
```

Ademas, `modules/rrhh/db_service.py` trae `department` desde `tb_usuarios`, pero no trae `puesto` en `get_usuario_simple_by_id`.

Regla de negocio actualizada:

- El puesto obtenido desde Microsoft Graph (`tb_usuarios.puesto`) debe tener prioridad.
- `tb_empleados_datos.puesto` debe quedar como respaldo local solo cuando Microsoft no tenga puesto.
- Si Microsoft trae un puesto nuevo, el modal debe mostrar ese valor aunque exista un valor anterior en `tb_empleados_datos.puesto`.

Correccion recomendada:

- Incluir `puesto` en `get_usuario_simple_by_id`.
- En el input `Puesto`, usar prioridad Microsoft:

```html
value="{{ usuario.get('puesto') or (empleado.puesto if empleado else '') }}"
```

### `No. de empleado`: interno vs BioTime

Actualmente el campo visible `No. Empleado` guarda en `tb_empleados_datos.numero_empleado`.

Riesgo: el nombre es ambiguo. Puede entenderse como numero interno de RH o como codigo BioTime, pero esos valores pueden ser diferentes.

En asistencia, el mapeo de BioTime usa primero `tb_biotime_empleado_map`, y tambien permite fallback por `tb_empleados_datos.biotime_emp_code` o `tb_empleados_datos.numero_empleado`.

Referencias:
- `modules/asistencia/db_service.py` - `get_employee_map`
- `migrations/070_asistencia_biotime.sql` - agrega `tb_empleados_datos.biotime_emp_code`
- `modules/vacaciones/db_service.py` - actualmente guarda `numero_empleado`, pero no expone `biotime_emp_code` en el modal

Correccion recomendada:

- Renombrar visualmente `No. Empleado` a `No. interno` o `No. interno de empleado`.
- No pedir `Codigo BioTime` como captura manual principal.
- Extraer `biotime_emp_code` desde BioTime mediante la sincronizacion de empleados.
- Mostrar `Codigo BioTime` en el modal como dato informativo de solo lectura cuando exista.
- Guardar o actualizar `tb_empleados_datos.biotime_emp_code` desde el mapeo BioTime, no desde entrada manual del usuario.
- Mantener `numero_empleado` como identificador interno, no como identificador BioTime.

Esto no requiere migracion porque `biotime_emp_code` ya existe. Requiere ajustar query, service de sincronizacion BioTime y template para mostrar el codigo como dato proveniente de BioTime.

### Explicar `Dias de ajuste de vacaciones`

Comportamiento actual:

El texto dice:

```text
Suma o resta dias al calculo base segun LFT.
```

La explicacion es correcta, pero puede ser insuficiente para usuarios no tecnicos.

Correccion recomendada:

```text
Ajuste manual al saldo calculado por antiguedad. Usa valores positivos para otorgar dias adicionales y negativos para descontar dias. Normalmente debe quedarse en 0.
```

Tambien conviene indicar que este ajuste impacta el balance de vacaciones, no la asistencia.

### Como funcionan aprobador y jefes directos

El sistema maneja dos relaciones para vacaciones:

- `Aprobador de vacaciones`: se guarda en `tb_empleados_datos.id_aprobador_vacaciones`.
- `Jefes directos`: se guardan en `tb_empleados_jefes`.

Para aprobar solicitudes pendientes, `get_solicitudes_pendientes_para_aprobador` devuelve solicitudes donde el usuario actual es el aprobador designado o uno de los jefes directos.

Para notificaciones, `get_aprobador_emails` prioriza:

1. Aprobador de vacaciones designado.
2. Jefes directos.
3. Correos de RH como fallback.

Correccion recomendada:

- `Aprobador de vacaciones`: `Recibe primero las solicitudes y puede aprobarlas.`
- `Jefes directos`: `Tambien pueden ver y aprobar solicitudes; se usan como respaldo o equipo de aprobacion.`

Si la regla de negocio deseada es que solo el aprobador designado pueda aprobar y los jefes solo reciban copia, habria que cambiar la logica de `get_solicitudes_pendientes_para_aprobador` y `puede_aprobar`.

## 6. Tab empleados: boton `Exportar Excel` es ambiguo

### Comportamiento actual

En la tab de empleados existe un enlace con texto generico:

```html
Exportar Excel
```

Referencia:
- `templates/rrhh/partials/empleados_lista.html` - enlace `/rrhh/empleados/exportar-excel`

Ese endpoint no exporta una lista generica de empleados. Llama a `build_empleados_vacaciones_export`, que construye un reporte enfocado en vacaciones.

Referencias:
- `modules/rrhh/router.py` - `empleados_exportar_excel`
- `modules/rrhh/service.py` - `build_empleados_vacaciones_export`

El Excel incluye datos como periodo, dias otorgados, dias tomados, dias restantes, fecha de expiracion, dias para expirar y aprobador.

### Causa

El texto del boton describe el formato del archivo, pero no el contenido ni el proposito del reporte.

### Riesgo

- El usuario puede esperar un catalogo general de empleados.
- No queda claro que el archivo es de vacaciones.
- Se confunde con otros reportes Excel de asistencia, vacaciones y horas extra.

### Correccion recomendada

Cambiar el texto visible a una etiqueta especifica. Opciones:

```text
Exp. reporte vacaciones
```

o, si hay espacio suficiente:

```text
Exportar reporte de vacaciones
```

Agregar `title` o texto auxiliar breve:

```text
Incluye saldos, periodos, dias tomados, dias restantes, expiracion y aprobador.
```

Tambien conviene que el nombre del archivo siga alineado con el contenido. Actualmente ya usa:

```text
empleados_vacaciones_YYYYMMDD.xlsx
```

## 7. Reporte de asistencia del 01 al 14 descarga solo del 08 al 14

### Comportamiento actual

El endpoint del Excel de asistencia consulta directamente `tb_asistencia_diaria`:

```python
rows = await asistencia_db.get_reporte_asistencia(...)
```

Referencias:
- `modules/rrhh/router.py` - `reporte_asistencia_excel`
- `modules/asistencia/db_service.py` - `get_reporte_asistencia`

La consulta filtra por `ad.fecha_laboral` entre `fecha_inicio` y `fecha_fin`. No consulta BioTime en vivo y no recalcula automaticamente todo el rango solicitado.

La sincronizacion BioTime inserta checadas y despues recalcula:

- Dias afectados por checadas insertadas.
- Dias recientes definidos por `ASISTENCIA_RECALC_DIAS`.

Referencia:
- `modules/asistencia/service.py` - `sync_biotime_once`
- `modules/asistencia/service.py` - `recalcular_asistencia_reciente`
- `migrations/070_asistencia_biotime.sql` - `ASISTENCIA_RECALC_DIAS = 7`

Con fecha actual 2026-05-14, una ventana de 7 dias explica que existan resumenes desde 2026-05-08 hasta 2026-05-14.

### Causa validada en BD

El Excel no esta exportando directamente los registros crudos de BioTime. Exporta el resumen diario previamente calculado en `tb_asistencia_diaria`.

Se ejecuto una consulta read-only contra la BD para cruzar, por dia, estas fuentes:

- `tb_biotime_checks`: checadas crudas importadas desde BioTime.
- `tb_biotime_checks.usuario_id`: checadas ya mapeadas a usuarios ECO.
- `tb_asistencia_diaria`: resumen diario que usa el Excel.
- `tb_asistencia_sync_runs`: ventanas reales de sincronizacion BioTime.

Resultado del diagnostico para `2026-05-01` a `2026-05-14`:

- `2026-05-01` a `2026-05-07`: no hay checadas en `tb_biotime_checks` y tampoco hay filas en `tb_asistencia_diaria`. Por eso esos dias no aparecen en el Excel.
- `2026-05-08` a `2026-05-11`: hay 20 filas por dia en `tb_asistencia_diaria`, pero todas sin checadas y sin horas; tampoco hay checadas crudas importadas en `tb_biotime_checks`.
- `2026-05-12` a `2026-05-14`: si hay checadas crudas importadas. Por eso solo esos dias empiezan a mostrar datos reales.
- Config actual: `BIOTIME_SYNC_LOOKBACK_HRS=48` y `ASISTENCIA_RECALC_DIAS=7`.
- Los ultimos syncs revisados cubren ventanas desde `2026-05-12` hasta `2026-05-14`, no el historico desde `2026-05-01`.

Conclusiones:

- La causa exacta del corte es que ECO no tiene importado el historico BioTime del `2026-05-01` al `2026-05-11`.
- El Excel no esta incompleto por un filtro de fecha del endpoint; esta exportando fielmente lo que existe en `tb_asistencia_diaria`.
- La ventana de 48 horas de BioTime explica por que se importaron datos recientes, pero no el historico del 01 al 11.

Problemas secundarios detectados:

- Del `2026-05-12` al `2026-05-14` hay checadas sin `usuario_id` mapeado:
  - `2026-05-12`: 6 checadas sin usuario.
  - `2026-05-13`: 13 checadas sin usuario.
  - `2026-05-14`: 8 checadas sin usuario.
- Los resumenes del `2026-05-08` al `2026-05-11` quedaron como `sin_horario` sin checadas.
- Del `2026-05-12` al `2026-05-14` aparecen estados `incompleto` y `sin_horario`, lo que apunta a revisar mapeos, horarios por sucursal y ventanas laborales despues del backfill.

### Riesgo

- El usuario interpreta el Excel como reporte BioTime completo, pero realmente es un reporte de resumen ECO.
- Se generan reportes parciales si no existe backfill de `tb_asistencia_diaria`.
- La descarga puede ocultar datos que si existen en BioTime pero todavia no estan normalizados o recalculados en ECO.

### Correccion recomendada

Definir un flujo explicito de backfill/recalculo por rango:

- Agregar una accion administrativa `Recalcular asistencia por rango`.
- Permitir fecha inicio, fecha fin, empleado y sucursal opcionales.
- Consultar/insertar checadas BioTime del rango cuando se requiere historico.
- Recalcular `tb_asistencia_diaria` para todo el rango seleccionado antes de descargar o mediante una tarea previa.
- Reportar cuantos empleados/dias fueron recalculados y cuantas checadas quedaron sin mapear.

Para el Excel, hay dos opciones:

1. Mantenerlo como export de `tb_asistencia_diaria`, pero mostrar una advertencia si faltan dias calculados en el rango.
2. Antes de generar el Excel, recalcular el rango solicitado para los usuarios filtrados. Esta opcion puede ser mas lenta y conviene limitarla por rango maximo.

Tambien se recomienda revisar el panel de configuracion BioTime:

- `Horas hacia atras` (`BIOTIME_SYNC_LOOKBACK_HRS`)
- `Dias a recalcular` (`ASISTENCIA_RECALC_DIAS`)

Estos parametros no sustituyen un backfill historico si el usuario necesita reportar fechas anteriores.

## 8. Descarga de horas extra responde JSON por `usuario_id` y `sucursal_id` vacios

### Comportamiento actual

El formulario de reportes tiene selects con opcion vacia:

```html
<option value="">Todos</option>
<option value="">Todas</option>
```

Referencia:
- `templates/rrhh/partials/reportes.html`

Al descargar horas extra, el navegador envia:

```text
usuario_id=&sucursal_id=
```

El endpoint de horas extra tipa esos parametros como UUID opcional:

```python
usuario_id: Optional[UUID] = None
sucursal_id: Optional[UUID] = None
```

Referencia:
- `modules/rrhh/router.py` - `reporte_horas_extra_excel`

FastAPI intenta convertir la cadena vacia a UUID antes de entrar al handler y responde con error de validacion:

```json
{
  "type": "uuid_parsing",
  "loc": ["query", "usuario_id"],
  "input": ""
}
```

### Causa

Hay inconsistencia entre endpoints:

- Asistencia recibe `usuario_id` y `sucursal_id` como `Optional[str]` y solo convierte a UUID si tienen valor.
- Horas extra los recibe como `Optional[UUID]`, por lo que una cadena vacia falla en validacion.

Referencia:
- `modules/rrhh/router.py` - `reporte_asistencia_excel`
- `modules/rrhh/router.py` - `reporte_horas_extra_excel`

El endpoint de vacaciones tambien recibe `usuario_id: Optional[UUID]`; podria tener el mismo problema si el formulario manda `usuario_id=`.

### Correccion recomendada

Homologar horas extra y vacaciones con asistencia:

```python
usuario_id: Optional[str] = None
sucursal_id: Optional[str] = None

uid = UUID(usuario_id) if usuario_id else None
sid = UUID(sucursal_id) if sucursal_id else None
```

Agregar manejo de `ValueError` para devolver un error claro si llega un UUID invalido.

Alternativa complementaria en UI:

- Antes de enviar el formulario, omitir parametros vacios.

La correccion de backend es necesaria porque el endpoint debe tolerar filtros vacios aunque el formulario cambie.

## 9. Hora de comida en viernes con jornada menor

### Comportamiento actual

El modelo de horarios tiene `descuento_comida_min` a nivel de horario de sucursal, no por dia.

Referencias:
- `templates/rrhh/partials/admin_horarios.html` - campo `Comida`
- `modules/rrhh/service.py` - `guardar_horario_sucursal`
- `modules/rrhh/service.py` - `_normalizar_dias_horario`
- `modules/asistencia/logic.py` - `calcular_resumen_dia`

La normalizacion aplica el mismo descuento de comida a todos los dias laborales:

```python
minutos_programados = _calcular_minutos_programados(
    entrada, salida, cruza_medianoche, descuento_comida_min
)
```

Y el calculo de asistencia tambien descuenta el mismo valor del tiempo trabajado:

```python
descuento = schedule.descuento_comida_min if schedule else 0
minutos_trabajados = max(0, minutos_trabajados - descuento)
```

### Causa

La configuracion actual no puede expresar una regla como:

```text
Lunes a jueves: 07:00 a 17:00 con 60 min de comida
Viernes: 07:00 a 15:00 sin comida
```

Si se configura `Comida = 60`, el viernes 07:00 a 15:00 queda como 7 horas netas programadas.

Si se configura `Comida = 0`, lunes a jueves quedan como 10 horas netas programadas.

### Riesgo

- Viernes puede calcular menos horas programadas de las reales.
- Horas extra del viernes pueden inflarse o reducirse incorrectamente segun la configuracion.
- El usuario puede intentar compensarlo cambiando la hora de salida del viernes, pero eso falsea la ventana laboral.

### Correccion recomendada

Mover el descuento de comida a nivel de dia:

- Agregar `descuento_comida_min` a `tb_horarios_sucursal_dias`.
- Mantener el campo global como valor default opcional para llenar dias nuevos.
- En el formulario, mostrar columna `Comida` por cada dia laboral.
- Para viernes, permitir `0`.
- En `get_attendance_contexts`, leer el descuento por dia.
- En `ScheduleConfig`, usar el descuento del dia, no el global del horario.

Ejemplo de configuracion esperada:

```text
Lunes    07:00-17:00 comida 60 = 9:00 horas netas
Martes   07:00-17:00 comida 60 = 9:00 horas netas
Miercoles 07:00-17:00 comida 60 = 9:00 horas netas
Jueves   07:00-17:00 comida 60 = 9:00 horas netas
Viernes  07:00-15:00 comida 0  = 8:00 horas netas
```

Requiere migracion SQL porque el dato no existe actualmente por dia.

## 10. Mi perfil: no guarda firma dibujada

### Comportamiento actual

La firma dibujada se captura en `templates/vacaciones/partials/form_firma.html` con `SignaturePad` y se envia al endpoint:

```text
POST /perfil/firma/draw
```

Referencias:
- `templates/vacaciones/partials/form_firma.html`
- `modules/vacaciones/router.py` - `guardar_firma_dibujada`
- `modules/vacaciones/service.py` - `guardar_firma`
- `static/vendor/signature_pad.min.js`

El formulario usa:

```html
@submit.prevent="
  if (window._sigPad && !window._sigPad.isEmpty()) {
    const dataUrl = window._sigPad.toDataURL('image/png');
    $el.querySelector('[name=firma_b64]').value = dataUrl;
    htmx.trigger($el, 'submit');
  }
"
```

### Causa

Hay dos problemas en el flujo del canvas:

1. El handler de Alpine cancela el submit con `@submit.prevent` y luego dispara otro `submit` sobre el mismo formulario con `htmx.trigger($el, 'submit')`. Ese segundo submit vuelve a pasar por el mismo handler de Alpine, por lo que puede entrar en un ciclo o impedir que HTMX haga el POST real.
2. Si `SignaturePad` no esta cargado cuando corre `x-init`, el script se carga despues y crea `window._sigPad`, pero en ese camino no registra el listener `beginStroke` que cambia `canvasLimpio = false`. Resultado: el usuario puede dibujar, pero el boton puede quedarse deshabilitado o el estado visual no reflejar que ya hay firma.

### Riesgo

- El usuario dibuja la firma pero el POST no se ejecuta.
- El boton `Guardar firma` puede permanecer deshabilitado aun despues de dibujar.
- Si se re-renderiza el partial con HTMX, `window._sigPad` puede quedar apuntando a un canvas anterior si no se reinicializa de forma controlada.

### Correccion recomendada

Evitar disparar `submit` desde dentro de `@submit.prevent`.

Opciones:

- Usar `hx-on::config-request` para llenar `firma_b64` justo antes de que HTMX envie el formulario.
- O usar un boton `type="button"` y llamar `htmx.ajax('POST', '/perfil/firma/draw', { target: '#tab-content', swap: 'innerHTML', values: {...} })`.
- Encapsular la inicializacion del canvas en una funcion Alpine local, por ejemplo `initSignaturePad()`, y llamarla tanto en `x-init` como despues de cargar el script.
- No depender de una variable global `window._sigPad`; usar una referencia local del componente para evitar que apunte a canvases viejos.

## 11. Mi perfil: upload de firma responde 400

### Comportamiento actual

El upload de firma usa:

```text
POST /perfil/firma/upload
```

con:

```html
hx-encoding="multipart/form-data"
<input type="file" name="firma_file" accept="image/png" required>
```

Referencias:
- `templates/vacaciones/partials/form_firma.html`
- `modules/vacaciones/router.py` - `subir_firma`
- `modules/vacaciones/service.py` - `validar_firma_png`
- `modules/vacaciones/constants.py` - `FIRMA_MAX_BYTES = 500 * 1024`

El backend rechaza con 400 cuando:

- `content_type` no es exactamente `image/png`.
- El archivo no empieza con encabezado PNG valido.
- El PNG pesa mas de 500 KB.
- El PNG mide mas de 500 x 200 px.

### Causa

El error de consola:

```text
Response Status Error Code 400 from /perfil/firma/upload
```

es HTMX reportando una respuesta 400 del backend.

La validacion es estricta. Aunque el input tenga `accept="image/png"`, el navegador no garantiza que el archivo seleccionado sea realmente PNG ni que cumpla dimensiones/peso.

Tambien hay un problema de UX: `_toast_error` devuelve `shared/toast.html` con status 400, pero HTMX trata las respuestas 4xx como error y no hace swap normal. Por eso el usuario puede ver solo el error en consola y no el mensaje claro del backend.

### Correccion recomendada

- Mantener validacion en backend, pero mostrar el mensaje al usuario aunque la respuesta sea 400.
- Opciones:
  - Responder con status 200 para errores validables de formulario y mostrar toast de error.
  - O agregar manejo global `htmx:beforeSwap` para procesar HTML/toasts en respuestas 400 de formularios.
- Mejorar texto visible del upload:

```text
Solo PNG, maximo 500 KB y maximo 500 x 200 px.
```

- Opcionalmente validar en frontend dimensiones y peso antes de enviar, para evitar un request fallido.
- Si se quiere aceptar JPG/WEBP/HEIC, convertir del lado cliente o backend a PNG antes de guardar, manteniendo la validacion final sobre el PNG generado.

## 12. Sincronizacion Microsoft: `jobTitle` se guarda pero no se ve en UI

### Comportamiento actual

El login y el boton de Admin sincronizan `jobTitle` de Microsoft Graph hacia `tb_usuarios.puesto`.

Referencias:
- `modules/auth/router.py` - guarda `profile.get("jobTitle")` en `tb_usuarios.puesto`
- `modules/admin/service.py` - `sync_ms_profiles`
- `modules/admin/db_service.py` - `update_user_ms_profile`

El boton de Admin dice:

```text
Sincronizar departamento y puesto desde Microsoft 365 para usuarios sin estos datos.
```

Referencia:
- `templates/admin/dashboard.html`

Pero la UI actual no muestra `puesto` en los lugares principales:

- `Mi Perfil` solo muestra nombre de usuario y balance de vacaciones; no muestra puesto ni departamento.
- La tabla de Admin muestra departamento, modulos, inicio y rol, pero no columna de puesto.
- El modal `Editar datos de empleado` muestra `empleado.puesto`, pero no prioriza `tb_usuarios.puesto` de Microsoft.

Referencias:
- `templates/vacaciones/partials/content.html`
- `templates/vacaciones/partials/balance.html`
- `templates/admin/partials/user_row.html`
- `templates/rrhh/partials/empleado_editar.html`
- `modules/rrhh/db_service.py` - `get_usuario_simple_by_id` no incluye `puesto`

### Causa

El dato si puede quedar guardado en DB, pero no existe un espacio visible en `Mi Perfil` ni en la tabla de Admin para mostrarlo.

Ademas, la sincronizacion de Admin solo selecciona usuarios con `puesto IS NULL OR department IS NULL`. Si un usuario ya tiene ambos valores, el boton no refresca cambios posteriores de Microsoft Graph.

Referencia:
- `modules/admin/db_service.py` - `fetch_users_missing_profile`

### Riesgo

- El usuario cree que la sincronizacion no funciono aunque la DB si se haya actualizado.
- Cambios de puesto en Microsoft no se reflejan si ECO ya tenia un puesto previo.
- RRHH puede editar un puesto local distinto al de Microsoft porque el modal no prioriza `tb_usuarios.puesto`.

### Correccion recomendada

- Mostrar en `Mi Perfil` una ficha de datos laborales con:
  - Nombre.
  - Email.
  - Departamento.
  - Puesto Microsoft.
  - Fecha de contratacion si existe.
- En Admin, agregar columna o detalle visible para `Puesto`.
- En el modal de empleado, usar prioridad Microsoft:

```html
value="{{ usuario.get('puesto') or (empleado.puesto if empleado else '') }}"
```

- Ajustar `get_usuario_simple_by_id` para traer `puesto`.
- Definir si el boton de Admin debe sincronizar solo faltantes o tambien refrescar todos los perfiles. Si debe refrescar cambios de Microsoft, agregar modo `forzar sincronizacion` o cambiar el query para incluir usuarios activos con token, aunque ya tengan datos.

## 13. Observacion de arquitectura: desacoplar `Mi Perfil` de vacaciones

### Comportamiento actual

La pantalla `Mi Perfil` vive dentro de `modules/vacaciones`, aunque usa el prefijo global:

```python
router = APIRouter(prefix="/perfil", tags=["perfil"])
```

Referencias:
- `modules/vacaciones/router.py`
- `templates/vacaciones/perfil.html`
- `templates/vacaciones/partials/content.html`
- `templates/vacaciones/partials/form_firma.html`

Esto hace que funcionalidades generales del usuario queden acopladas al modulo de vacaciones:

- Datos de perfil.
- Firma digital.
- Puesto y departamento.
- Vista inicial `/perfil/ui`.

### Causa

La pantalla de perfil probablemente nacio junto con vacaciones porque el primer uso fuerte era el balance de vacaciones y la firma para solicitudes.

Pero el dominio real de `Mi Perfil` es transversal. No pertenece completamente a vacaciones.

### Riesgo

- Se dificulta mostrar datos generales sincronizados desde Microsoft, como `jobTitle`, porque la vista esta pensada como pantalla de vacaciones.
- La firma queda tratada como funcionalidad de vacaciones, aunque es una firma del usuario.
- El modulo vacaciones mezcla responsabilidades de identidad/perfil con reglas de ausencia.
- Futuros datos de perfil, preferencias o configuraciones personales podrian seguir acumulandose en el modulo equivocado.

### Correccion recomendada

Desacoplar gradualmente:

1. Crear `modules/perfil/` con estructura del patron del proyecto:
   - `router.py`
   - `service.py`
   - `db_service.py`
   - `schemas.py` si aplica
2. Mover al nuevo modulo lo transversal:
   - `/perfil/ui`
   - datos visibles del usuario
   - firma digital
   - carga/dibujo de firma
   - puesto/departamento sincronizados desde Microsoft
3. Mantener en `modules/vacaciones` lo especifico de vacaciones:
   - balance
   - solicitudes
   - aprobaciones
   - equipo
   - calculo de dias y consumos
4. La pantalla `Mi Perfil` puede seguir mostrando secciones de vacaciones, pero consumiendolas desde endpoints/parciales de `modules/vacaciones`.

No se recomienda hacerlo como refactor masivo en una sola entrega. Primer paso sugerido: mover firma y datos generales del perfil; despues separar balance/solicitudes si se decide que `Mi Perfil` sea solo un contenedor global.

## Resumen de acciones sugeridas

1. Validar `cruza_medianoche` contra horas de entrada/salida en backend y reforzar UX del formulario.
2. Inicializar Feriados en Admin como colapsado.
3. Cambiar default de Asistencia a fecha actual.
4. Diferenciar `incompleto` definitivo de jornada `en_curso`, idealmente con nuevo estado y migracion.
5. Corregir modal de empleados: cierre solo con X, target HTMX valido, overlay de guardado, prioridad de puesto desde Microsoft, `Codigo BioTime` extraido de BioTime como solo lectura, y textos claros para ajuste, aprobador y jefes.
6. Cambiar el texto `Exportar Excel` en Empleados a `Exp. reporte vacaciones` o `Exportar reporte de vacaciones`, con ayuda sobre el contenido del archivo.
7. Agregar backfill/recalculo por rango para que los reportes de asistencia no dependan solo de los dias recientes de `tb_asistencia_diaria`.
8. Corregir horas extra para aceptar filtros vacios sin error de UUID, igual que asistencia.
9. Cambiar el descuento de comida de global por horario a configurable por dia, especialmente para viernes sin comida.
10. Corregir firma dibujada evitando `htmx.trigger($el, 'submit')` dentro de `@submit.prevent` y reinicializando `SignaturePad` de forma local.
11. Mejorar upload de firma: validar/mostrar claramente PNG maximo 500 KB y 500 x 200 px, y evitar que el usuario solo vea un 400 en consola.
12. Exponer `puesto` sincronizado desde Microsoft en UI y definir si el boton de Admin sincroniza solo faltantes o tambien refresca cambios existentes.
13. Desacoplar `Mi Perfil` de `modules/vacaciones`, moviendo datos generales y firma a un modulo `perfil` y dejando en vacaciones solo balance, solicitudes y aprobaciones.
