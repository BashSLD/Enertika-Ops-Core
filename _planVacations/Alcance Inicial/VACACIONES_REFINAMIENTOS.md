# Refinamientos — Módulo Vacaciones, Perfil y RRHH

> **Fecha:** 2026-05-12
> **Documento base:** `PLAN_VACACIONES_Y_PERFIL.md` (actualizado con estos cambios)

---

## Decisiones de diseño tomadas

### C1 — Firmas: base64 en BD (no filesystem)
- **Campo:** `tb_usuarios_firmas.firma_data BYTEA NOT NULL`
- **Motivo:** Railway tiene filesystem efímero — `static/firmas/` se borra en cada redeploy
- **En PDF:** recuperar BYTEA → convertir a base64 → embeber como `data:image/png;base64,...`
- **Eliminar:** toda referencia a `firma_path VARCHAR(255)` y `static/firmas/{user_id}.png`

### C2 — `es_rh` en session context
- **Archivo:** `core/security.py`
- **Cambio:** agregar `es_rh` al `SELECT ... FROM tb_usuarios WHERE email = $1` y propagarlo en el dict de retorno
- **Fase:** 7 (junto con `main.py` y `base.html`)
- **Razón:** sin esto, `user_context.get('es_rh', False)` siempre retorna `False` y el módulo RRHH no es accesible

### M1 — Tracking de recordatorios 24h
- **Campo nuevo:** `tb_solicitudes_ausencia.ultima_notificacion_aprobador TIMESTAMPTZ`
- **Lógica worker:** enviar recordatorio si `estado = 'pendiente' AND (ultima_notificacion_aprobador IS NULL OR ultima_notificacion_aprobador < now() - interval '24h')`
- **Actualizar** el campo al momento de enviar cada recordatorio

### M2 — Cancelación libera saldo + validación fechas vencidas
- **Cancelar solicitud:** hacer `DELETE FROM tb_vacaciones_consumo WHERE solicitud_id = $1` igual que en rechazo
- **Nueva tarea worker diaria:** `verificar_solicitudes_vencidas_periodically()` en `core/tasks.py`
  - Condición: `estado = 'pendiente' AND fecha_inicio <= hoy`
  - Acción: notificar a RH + aprobador para que resuelvan y verifiquen si el empleado tomó los días

### M3 — PDF generado al vuelo
- WeasyPrint renderiza el PDF en cada request — no se almacena en ningún storage
- La firma siempre viene fresca de BD (BYTEA → base64)
- Sin gestión de versiones de PDF

### M4 — Folio de solicitud
- **Formato:** `FO-ADM-002-{ABREV}{fecha_solicitud:ddmmaaHHMM}`
- **Ejemplo:** `FO-ADM-002-VAC1205261423`
- **Calculado al vuelo** en el PDF — no requiere campo extra en BD ni SEQUENCE
- **Fuentes:** `tb_cat_tipos_solicitud.abreviatura` + `tb_solicitudes_ausencia.fecha_solicitud`
- **Abreviaturas:**

| Tipo | Slug | Abreviatura |
|---|---|---|
| Vacaciones | `vacaciones` | `VAC` |
| Extraordinaria / Urgencia | `extraordinaria` | `EXT` |
| Home Office | `home_office` | `HO` |
| Incapacidad | `incapacidad` | `INC` |
| Permiso con goce | `permiso_con_goce` | `PCG` |
| Permiso para llegar tarde | `permiso_llegar_tarde` | `PLT` |
| Permiso para salir temprano | `permiso_salir_temprano` | `PST` |
| Permiso sin goce | `permiso_sin_goce` | `PSG` |

- **Schema:** agregar columna `abreviatura VARCHAR(5) NOT NULL` a `tb_cat_tipos_solicitud`

### Me1 — Excel export de RH (en alcance)
- **Endpoint:** `GET /rrhh/empleados/exportar-excel`
- **Librería:** `openpyxl`
- **Columnas:** Empleado, No. Empleado, Depto, Fecha Contratación, Periodo, Días Otorgados, Días Tomados, Días Restantes, Fecha Expiración, Días para Renovar
- **Acceso:** solo RH / ADMIN

### Me2 — Módulo `perfil`/`vacaciones` NO va en `tb_cat_modulos`
- Acceso al perfil = cualquier usuario autenticado (solo sesión activa, sin RBAC)
- Solo `rrhh` se registra en `tb_cat_modulos` (migración 067)

### Me3 — Días hábiles para todos los tipos (eliminada distinción)
- **Antes:** vacaciones = días hábiles, permisos = días naturales
- **Ahora:** todos los tipos usan `contar_dias_habiles(inicio, fin, festivos)`
- El formulario siempre muestra "Días hábiles en el rango: N (L-V, excluyendo festivos)"

### Me4 — Expiración de periodos: configurable via ConfigService
- **Función:** `relativedelta(months=VACACIONES_MESES_EXPIRACION)` (no suma fija de días)
- **Config key:** `VACACIONES_MESES_EXPIRACION` en `tb_configuracion_global` (default: `18`)
- **Acceso:** `await ConfigService.get_config_value(conn, 'VACACIONES_MESES_EXPIRACION', default=18)`

---

## Cambios aplicados en `PLAN_VACACIONES_Y_PERFIL.md`

| Sección | Cambio |
|---|---|
| §1.3 | `firma_path` → `firma_data BYTEA`; uso en PDF actualizado a base64 |
| §3.3 | `tb_cat_tipos_solicitud` + columna `abreviatura` + seed con 8 abreviaturas |
| §3.4 | `tb_solicitudes_ausencia` + columna `ultima_notificacion_aprobador` |
| §3.9 | `tb_usuarios_firmas`: `firma_path VARCHAR` → `firma_data BYTEA NOT NULL` |
| §4.1 | Expiración: `relativedelta(months=VACACIONES_MESES_EXPIRACION)` configurable |
| §5.1 | Endpoint `GET /rrhh/empleados/exportar-excel` agregado |
| §6.4 | Nueva sección: cancelación libera consumo + tarea worker para fechas vencidas |
| §8.1 | Folio PDF actualizado a `FO-ADM-002-VAC1205261423` |
| §8.2 | PDF al vuelo; firma desde base64 BD; folio calculado al vuelo |
| §9.4 | Nueva tarea `verificar_solicitudes_vencidas_periodically()` |
| §10.1 | `perfil`/`vacaciones` NO va en `tb_cat_modulos` |
| §12 | Fase 7 incluye actualización de `security.py` |
| §13.2 | Distinción días hábiles/naturales eliminada |
| §13.8–13.11 | Notas técnicas nuevas: firmas BYTEA, folio, expiración configurable, `es_rh` |
| §14 | Q&A actualizado con las 10 decisiones confirmadas |

---

## Próximo paso

Implementar en el orden de las 15 fases definidas en `PLAN_VACACIONES_Y_PERFIL.md §12`.

**Fase 1** es la migración 066 — sin ella no hay código que funcione.
