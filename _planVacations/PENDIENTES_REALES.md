# Pendientes reales - Vacaciones, RRHH, Asistencia y BioTime

Fecha de revision: 2026-05-15

Este documento reemplaza los planes parciales anteriores como lista unica de pendientes. La lista esta basada en revision directa del codigo, no solo en lo indicado por `_planVacations`.

`BIOTIME_PRO_API.md` queda en `_planVacations/` como documento de consulta funcional de BioTime PRO.

## Pendientes funcionales

### 1. Aprobacion persistente de horas extra

Estado actual:
- `tb_asistencia_diaria` guarda `minutos_extra`.
- La UI muestra "Horas extra pendientes de aprobacion".
- No existe estado persistente de aprobacion, ni endpoints para aprobar/rechazar horas extra.

Evidencia:
- `migrations/070_asistencia_biotime.sql`: `minutos_extra` existe, pero no hay columnas de estado/aprobador.
- `templates/vacaciones/partials/equipo.html`: muestra horas extra como pendientes.
- No hay tabla tipo `tb_horas_extra_aprobaciones` ni rutas de aprobacion de horas extra.

Pendiente:
- Definir schema de aprobacion.
- Agregar endpoints aprobar/rechazar.
- Agregar UI para jefes/RH.
- Ajustar reportes para separar calculadas vs aprobadas.

### 2. Auto-mapeo BioTime por correo y excepciones visibles

Estado actual: ✅ IMPLEMENTADO COMPLETO (validado 2026-05-15)
- Codigo y migracion 077 completamente aplicados en BD.
- `upsert_biotime_employee_mappings()` (`db_service.py:98`): match por email unico, upsert con `biotime_email`, `match_source`, `last_seen_at`.
- `assign_unmapped_checks_from_mappings()` (`db_service.py:276`): retroactivamente asocia checadas historicas con usuario_id NULL.
- `get_unmapped_biotime_checks_summary()` (`db_service.py:561`): resumen de codigos sin mapear.
- RRHH > Asistencia muestra aviso + tabla de codigos sin mapear.
- Reporte Excel incluye hoja "Checadas sin mapear".
- Migration 077: columnas `biotime_email`, `match_source`, `last_seen_at` + constraint + 2 indices — ✅ APLICADA en BD.

Pendiente (solo validacion externa):
- Confirmar en servidor real que BioTime expone el campo `email` con datos correctos para todos los empleados.
- Si hay excepciones persistentes: corregir correo en BioTime/ECO y volver a sincronizar.
- No implementar mapeo manual en esta fase.

### 3. Backfill/recalculo de asistencia por rango

Estado actual: ✅ IMPLEMENTADO COMPLETO (validado 2026-05-15)
- `backfill_biotime_chunk()` en `service.py:180`: descarga BioTime + inserta checadas + recalcula asistencia, maximo 31 dias por chunk.
- `GET /admin/asistencia/backfill` (`admin/router.py:513`): carga el panel HTML.
- `POST /admin/asistencia/backfill/chunk` (`admin/router.py:521`): ejecuta un chunk con manejo de errores HTTP/BD.
- `templates/admin/partials/biotime_backfill.html`: UI completa con Alpine.js, procesa por meses automaticamente.
- Boton "Importar historico" en `templates/admin/partials/global_config.html` (seccion BioTime).
- Migration 076: `tb_horarios_sucursal_dias.descuento_comida_min` + estado `en_curso` en constraint — ✅ APLICADA en BD.

Pendiente (solo validacion externa):
- Confirmar en servidor real que el backfill trae checadas correctas (depende del punto 2 — correos BioTime).

### 4. Horarios especiales por empleado

Estado actual:
- Existe documento de diseno archivado en `Alcance Inicial/Feature_Horarios_Especiales.md`.
- No hay tabla, service, router ni UI implementados.

Pendiente:
- Crear `tb_horarios_empleado_asignaciones`.
- Resolver prioridad: horario especial vigente > horario de sucursal > sin_horario.
- Agregar CRUD en RRHH Admin.
- Recalcular asistencia del rango afectado al crear/editar/desactivar asignaciones.

### 5. Comprobante medico para incapacidad

Estado actual:
- El tipo de ausencia `incapacidad` existe.
- No hay schema ni upload especifico de comprobante/evidencia medica para incapacidades.

Evidencia:
- `migrations/066_vacaciones_rrhh_base.sql`: tipo `incapacidad`.
- No hay campos, adjuntos ni rutas especificas de evidencia para incapacidades en `modules/vacaciones` o `modules/rrhh`.

Pendiente:
- Definir si incapacidad requiere adjunto obligatorio.
- Agregar modelo de adjunto o integrar con sistema existente de documentos.
- Validar en creacion de solicitud cuando el tipo sea incapacidad.
- Mostrar evidencia en detalle y reportes de RRHH.

## Pendientes de validacion externa

### 6. Validacion BioTime PRO contra servidor real

Estado actual:
- El cliente esta implementado para BioTime PRO con sesion Django.
- Falta confirmar en servidor real la forma exacta de campos y login.

Pendiente:
- Probar login real y obtencion de `sessionid`.
- Confirmar campos de `/personnel/employee/table/`: email, apellidos, departamento.
- Confirmar campos reales de `/iclock/transaction/table/`: fecha/hora separadas, departamento y codigos.
- Ajustar normalizacion si el payload productivo difiere.

### 7. QA manual end-to-end

Pendiente:
- Migracion historica de vacaciones: descargar plantilla, importar preview, confirmar, reimportar, ajuste individual y limpieza.
- Mi Perfil: firma subida y dibujada, solicitud pendiente que se activa tras firma.
- RRHH Admin: horarios, feriados, tipos, dias por antiguedad y parametros.
- Asistencia: vista diaria, reportes Excel, checada en vacaciones, horas extra calculadas y excepciones BioTime sin mapear.
- Permisos: validar viewer/editor/admin/manager/admin global con usuarios reales.

## Verificaciones ya realizadas

- `py_compile` de modulos `perfil`, `vacaciones`, `rrhh`, `asistencia`, `main.py` y `worker.py`: OK.
- Pruebas focalizadas ejecutadas:
  - `tests/test_biotime_sync.py`
  - `tests/test_asistencia_logic.py`
  - `tests/test_permissions.py`
  - `tests/test_timezone.py`
- Resultado actualizado: 35 passed.
