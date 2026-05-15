# Migracion de Historial de Vacaciones - Plan de Implementacion

**Fecha:** 2026-05-14  
**Estado:** Actualizado con validacion contra el repositorio  
**Spec base:** `_planVacations/2026-05-14-migracion-vacaciones-design.md`

## Objetivo

Permitir a RH registrar dias de vacaciones tomados antes del sistema, de forma masiva por Excel y de forma individual por empleado, para que el saldo inicial sea correcto y el historial quede visible como registro historico.

## Estado de Implementacion

**Estado codigo:** implementado y compilado el 2026-05-14. Migracion SQL aplicada en Supabase.

- [x] Migracion SQL `075_migracion_vacaciones.sql` creada.
- [x] Capa DB de vacaciones/asistencia actualizada para migracion historica y exclusiones operativas.
- [x] Servicio RRHH implementado: plantilla Excel, validacion, token firmado, confirmacion masiva e individual.
- [x] Router RRHH implementado: `/rrhh/migracion`, plantilla, importar, confirmar y ajuste por empleado.
- [x] Templates RRHH creados/ajustados para vista dedicada, preview y seccion individual.
- [x] Historial de vacaciones ajustado para mostrar registros historicos sin acciones/PDF.
- [x] PDF de registros historicos bloqueado.
- [x] Compilacion Python ejecutada con `py_compile`.
- [x] Simplify ejecutado sobre la implementacion de migracion.
- [x] Verificacion Supabase: migracion 075 aplicada.
- [ ] Verificacion manual UI pendiente: descargar plantilla, importar preview, confirmar, reimportar, guardar/limpiar individual.

## Decisiones Ajustadas

- La siguiente migracion disponible es `075`; crear `migrations/075_migracion_vacaciones.sql`.
- Los registros migrados viven en `tb_solicitudes_ausencia` y consumen saldo mediante `tb_vacaciones_consumo`, igual que una solicitud normal.
- Se agrega `es_migracion BOOLEAN NOT NULL DEFAULT FALSE` y tambien `migrado_por UUID` porque `tb_solicitudes_ausencia` no tiene `created_by`.
- Para registros migrados, setear `estado='aprobado'`, `firma_solicitante_pendiente=false`, `aprobado_por=<RH>`, `migrado_por=<RH>` y `fecha_resolucion=now()`.
- Los registros migrados afectan balances y consumos, pero no deben afectar vistas operativas: vacaciones de hoy, vacaciones de equipo, asistencia ni validacion de solapamiento.
- Resolver contradiccion del diseno sobre periodos expirados: se permite migrarlos para historial completo; no afectan disponibilidad porque el balance ya excluye periodos expirados. Se bloquean solo periodos futuros o periodos inexistentes para el empleado.
- No usar `_PREVIEWS` en memoria. En Railway multi-worker puede fallar. Usar un token firmado y autocontenido con `settings.SECRET_KEY`, expiracion corta y revalidacion completa al confirmar.
- En router usar siempre `context["user_db_id"]`, no `context["user_id"]`.
- La vista real del historial del empleado esta en `templates/vacaciones/partials/mis_solicitudes.html`; tambien se debe ajustar el detalle/PDF para registros historicos.
- La ruta full-page `/rrhh/migracion` no debe renderizar `rrhh/dashboard.html` sin cambios, porque ese template incluye siempre el dashboard principal. Crear un wrapper dedicado o soportar un partial inicial.
- Antes de cualquier commit, correr `/simplify` segun `AGENTS.md`.

## Mapa de Archivos

| Archivo | Accion | Responsabilidad |
|---|---|---|
| `migrations/075_migracion_vacaciones.sql` | Crear | Agrega flags/auditoria para registros historicos |
| `modules/vacaciones/db_service.py` | Modificar | Funciones DB de migracion, selects con `es_migracion`, filtros operativos |
| `modules/asistencia/db_service.py` | Modificar | Excluir registros migrados de vacaciones aprobadas para asistencia |
| `modules/rrhh/service.py` | Modificar | Excel, validacion, token firmado, confirmacion transaccional, ajuste individual |
| `modules/rrhh/router.py` | Modificar | Endpoints `/rrhh/migracion` e individual por empleado |
| `templates/rrhh/migracion_page.html` | Crear | Wrapper full-page para `/rrhh/migracion` |
| `templates/rrhh/partials/migracion.html` | Crear | Vista dedicada de migracion |
| `templates/rrhh/partials/migracion_preview.html` | Crear | Preview antes de confirmar |
| `templates/rrhh/partials/migracion_empleado.html` | Crear | Seccion individual en edicion de empleado |
| `templates/rrhh/partials/content.html` | Modificar | Boton "Migracion historica" con progreso |
| `templates/rrhh/partials/empleado_editar.html` | Modificar | Carga lazy de ajuste individual |
| `templates/rrhh/partials/solicitudes_lista.html` | Modificar | Etiqueta visual para historicos en vista RH |
| `templates/vacaciones/partials/mis_solicitudes.html` | Modificar | Etiqueta y bloqueo de acciones para historicos |
| `templates/vacaciones/partials/detalle_solicitud.html` | Modificar | Mostrar historico y ocultar acciones/PDF |
| `modules/vacaciones/router.py` | Modificar | Bloquear PDF de registros historicos |
| `tests/test_vacaciones_migracion.py` | Crear si aplica | Pruebas unitarias de token/validacion sin BD real |

## Task 1: Migracion SQL 075

- [ ] Crear `migrations/075_migracion_vacaciones.sql`.

```sql
-- Agrega soporte para registros historicos de vacaciones cargados por RH.

ALTER TABLE tb_solicitudes_ausencia
  ADD COLUMN IF NOT EXISTS es_migracion BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tb_solicitudes_ausencia
  ADD COLUMN IF NOT EXISTS migrado_por UUID;

DO $$
BEGIN
  ALTER TABLE tb_solicitudes_ausencia
    ADD CONSTRAINT fk_solicitudes_migrado_por
    FOREIGN KEY (migrado_por) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_solicitudes_ausencia_migracion
  ON tb_solicitudes_ausencia (usuario_id, es_migracion)
  WHERE es_migracion = TRUE;

CREATE INDEX IF NOT EXISTS idx_solicitudes_ausencia_migrado_por
  ON tb_solicitudes_ausencia (migrado_por)
  WHERE migrado_por IS NOT NULL;

COMMENT ON COLUMN tb_solicitudes_ausencia.es_migracion IS
  'TRUE = registro historico cargado por RH antes del sistema';

COMMENT ON COLUMN tb_solicitudes_ausencia.migrado_por IS
  'Usuario RH que cargo o confirmo el registro historico';
```

- [ ] Verificar contra Supabase antes/despues de aplicar:

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'tb_solicitudes_ausencia'
  AND column_name IN ('es_migracion', 'migrado_por');
```

## Task 2: Capa DB de Vacaciones y Asistencia

### Nuevas funciones en `modules/vacaciones/db_service.py`

- [ ] `get_empleados_para_migracion(conn) -> list[dict]`
  - Solo usuarios activos.
  - `JOIN tb_empleados_datos`.
  - Requiere `fecha_contratacion IS NOT NULL`.
  - Incluir `COALESCE(e.dias_vacaciones_ajuste, 0)`.
  - Incluir `ya_migrado` via `EXISTS`.

- [ ] `count_empleados_migrados(conn) -> dict`
  - Total de empleados activos con fecha de contratacion.
  - Total con al menos un registro `es_migracion = TRUE`.

- [ ] `limpiar_migracion_usuario(conn, usuario_id: UUID) -> int`
  - Borrar solo solicitudes `es_migracion = TRUE`.
  - La FK `ON DELETE CASCADE` elimina consumos, pero se puede borrar consumo explicitamente si se prefiere.
  - Retornar conteo con CTE, no parseando `"DELETE n"`.

- [ ] `insertar_solicitud_migracion(...) -> UUID`
  - Insertar `es_migracion=true`.
  - Setear `aprobado_por`, `migrado_por`, `fecha_resolucion=now()`.
  - `observaciones`: `Registro historico previo al sistema - Periodo N`.
  - No insertar firmas.

- [ ] `get_migracion_usuario(conn, usuario_id: UUID) -> list[dict]`
  - Retornar solicitud, consumo, periodo y usuario migrador.

### Queries existentes que deben incluir `es_migracion`

- [ ] `get_solicitud`: seleccionar `sa.es_migracion`, `sa.migrado_por`.
- [ ] `get_solicitudes_usuario`: seleccionar `sa.es_migracion` y periodo migrado via `tb_vacaciones_consumo`.
- [ ] `get_todas_solicitudes`: seleccionar `sa.es_migracion` para vista global RH.
- [ ] `get_solicitudes_activas_en_rango`: excluir historicos con `COALESCE(sa.es_migracion, false) = false` para no bloquear solicitudes reales en la fecha de aniversario.
- [ ] `get_vacaciones_hoy`: excluir historicos.
- [ ] `get_vacaciones_aprobadas_equipo`: excluir historicos.
- [ ] `modules/asistencia/db_service.py::get_vacaciones_aprobadas`: excluir historicos para no marcar asistencia como vacaciones por un registro historico.
- [ ] No excluir historicos en `get_consumos_usuario` ni `get_consumos_bulk`; ahi si deben afectar saldo.

## Task 3: Servicio RRHH

### Imports y helpers

- [ ] En `modules/rrhh/service.py`, agregar lo necesario:
  - `base64`, `hashlib`, `hmac`, `json`, `time`, `zlib`
  - `BytesIO`
  - `Any`
  - `UUID`
  - `settings` desde `core.config`

- [ ] Crear helpers privados:
  - `_firmar_preview(rows: list[dict], ttl_seconds: int = 1200) -> str`
  - `_leer_preview_firmado(token: str) -> list[dict]`
  - `_normalizar_header_excel(value: object) -> str`
  - `_parse_dias_excel(value: object) -> int`

El token debe contener solo datos necesarios para confirmar:

```python
{
    "exp": 1778790000,
    "rows": [
        {
            "usuario_id": "...",
            "periodos": [
                {"num_periodo": 1, "dias": 10}
            ]
        }
    ]
}
```

El token no se debe confiar ciegamente: al confirmar, reconsultar empleado, catalogo, consumos y validar otra vez.

### Plantilla Excel

- [ ] `generar_plantilla_migracion(conn) -> BytesIO`
  - Usar `openpyxl`.
  - Incluir solo empleados activos con `fecha_contratacion`.
  - Columnas fijas:
    - `usuario_id` oculta.
    - `Nombre`.
    - `Email`.
    - `Fecha contratacion`.
    - `Periodos calculados`.
    - `Ya migrado`.
  - Columnas dinamicas:
    - `Periodo N (max X dias)`.
    - Usar el maximo de periodos calculados entre empleados.
    - Para cada empleado, calcular periodos con `dias_vacaciones_ajuste` para coincidir con el balance real.
  - Bloquear/proteger celdas futuras o inexistentes.
  - Permitir captura en periodos expirados, marcandolos con color gris y nota "Vencido".
  - Resaltar empleados ya migrados, sin impedir reimportacion.

### Validacion de importacion

- [ ] `validar_importacion_migracion(conn, file_bytes: bytes) -> dict`
  - Aceptar `.xlsx` y `.xlsm`; rechazar otros.
  - Validar tamano maximo razonable antes de parsear.
  - Manejar errores especificos de Excel/zip/openpyxl; no usar `except Exception`.
  - Detectar columnas por regex de `Periodo N`, tolerando acentos y variaciones menores.
  - Validar por fila:
    - `usuario_id` existe, activo y tiene `fecha_contratacion`.
    - Dias numericos enteros.
    - Dias `>= 0`.
    - Periodo existe y no es futuro.
    - Dias del periodo `<= dias_otorgados`.
    - `dias_migrados + consumos_no_migrados_del_periodo <= dias_otorgados`.
    - Suma total no excede total otorgado para periodos incluidos.
  - Retornar preview con:
    - filas OK.
    - filas con errores.
    - total de empleados con dias a registrar.
    - token firmado solo si no hay errores.

### Confirmacion masiva

- [ ] `ejecutar_migracion(conn, token: str, ejecutado_por: UUID) -> dict`
  - Leer token firmado.
  - Revalidar todo contra BD actual.
  - Ejecutar en `async with conn.transaction():`.
  - Por cada empleado con dias:
    - limpiar migracion anterior.
    - insertar solicitud historica por periodo.
    - insertar consumo para el mismo periodo.
  - Idempotencia: importar el mismo archivo dos veces debe dejar el mismo estado logico, sin duplicados.

### Ajuste individual

- [ ] `get_migracion_ctx(conn) -> dict`
  - Empleados para estado general.
  - Conteo para badge/progreso.

- [ ] `get_migracion_empleado_ctx(conn, usuario_id: UUID) -> dict`
  - Si no tiene fecha de contratacion, retornar aviso.
  - Calcular periodos no futuros con `dias_vacaciones_ajuste`.
  - Incluir `dias_migrados`, `expirado`, `fecha_aniversario`, `fecha_expiracion`.
  - Permitir editar vencidos, pero marcarlos visualmente.

- [ ] `guardar_migracion_individual(conn, usuario_id, periodos_dias, ejecutado_por)`
  - Reusar las mismas validaciones que la carga masiva.
  - Transaccion obligatoria.
  - Limpiar e insertar de forma idempotente.

## Task 4: Router RRHH

- [ ] Actualizar imports en `modules/rrhh/router.py`:
  - `File`, `UploadFile`.
  - `BadZipFile` si se maneja en router.

- [ ] Agregar endpoints con `require_manager_access("rrhh", "editor")`:
  - `GET /rrhh/migracion`
  - `GET /rrhh/migracion/plantilla`
  - `POST /rrhh/migracion/importar`
  - `POST /rrhh/migracion/confirmar`
  - `GET /rrhh/empleados/{usuario_id}/migracion-historial`
  - `POST /rrhh/empleados/{usuario_id}/migracion-historial`
  - `DELETE /rrhh/empleados/{usuario_id}/migracion-historial`

- [ ] Usar `UUID(str(context["user_db_id"]))` para el usuario RH ejecutor.
- [ ] Manejar `ValueError` como 400/toast.
- [ ] Manejar `asyncpg.PostgresError` como 500/toast y log estructurado.
- [ ] No usar `except Exception`.
- [ ] Para `/rrhh/migracion`:
  - Si es HTMX, retornar `rrhh/partials/migracion.html`.
  - Si no es HTMX, retornar `rrhh/migracion_page.html`, que extiende `base.html` e incluye el partial de migracion.

## Task 5: Templates RRHH

- [ ] Crear `templates/rrhh/migracion_page.html`.
- [ ] Crear `templates/rrhh/partials/migracion.html`.
  - Dos secciones: carga masiva y estado por empleado.
  - Boton de descarga de plantilla.
  - Form upload con `hx-encoding="multipart/form-data"`.
  - Zona `#migracion-preview`.
  - Progreso: `migrados / total con fecha de contratacion`.

- [ ] Crear `templates/rrhh/partials/migracion_preview.html`.
  - Mostrar errores en rojo.
  - Mostrar filas listas con periodo y dias.
  - Confirmar solo si no hay errores y hay al menos un periodo con dias.
  - El token firmado va en hidden input.

- [ ] Crear `templates/rrhh/partials/migracion_empleado.html`.
  - Seccion colapsable "Historial previo al sistema".
  - Inputs por periodo no futuro.
  - Vencidos editables pero marcados como "Vencido".
  - Botones "Guardar historial" y "Limpiar migracion".

- [ ] Modificar `templates/rrhh/partials/content.html`.
  - Agregar boton "Migracion historica" en encabezado.
  - `hx-get="/rrhh/migracion"`, `hx-target="#main-content"`, `hx-push-url="true"`.
  - Mostrar badge/progreso si faltan empleados por migrar.

- [ ] Modificar `templates/rrhh/partials/empleado_editar.html`.
  - Insertar carga lazy despues del formulario principal, no dentro del `<form>`.

```html
<div id="migracion-empleado-{{ usuario.id_usuario }}"
     hx-get="/rrhh/empleados/{{ usuario.id_usuario }}/migracion-historial"
     hx-trigger="load"
     hx-swap="outerHTML">
  <div class="mt-4 h-12 bg-gray-50 rounded-xl animate-pulse"></div>
</div>
```

## Task 6: Display de Historicos

- [ ] Modificar `templates/vacaciones/partials/mis_solicitudes.html`.
  - Si `s.es_migracion`, mostrar:
    - Tipo: `Historico`.
    - Texto: `Vacaciones tomadas antes del sistema`.
    - Periodo migrado si esta disponible.
    - Acciones: solo texto `Registro historico`; sin Ver/PDF/Firmar/Cancelar.

- [ ] Modificar `templates/vacaciones/partials/detalle_solicitud.html`.
  - Mostrar etiqueta `Registro historico`.
  - Ocultar PDF, cancelar, aprobar y rechazar.

- [ ] Modificar `templates/vacaciones/partials/mis_solicitudes.html` y `templates/rrhh/partials/solicitudes_lista.html` para que RH tambien vea la etiqueta historica.

- [ ] Modificar `modules/vacaciones/router.py`.
  - En endpoint PDF, si `solicitud["es_migracion"]` es true, responder 404 o 400 con mensaje claro. No generar PDF historico.

## Task 7: Validaciones y Pruebas

- [ ] Agregar pruebas unitarias si el patron del repo lo permite:
  - token firmado expira.
  - token manipulado falla.
  - parseo de columnas `Periodo N`.
  - validacion rechaza dias negativos/no numericos/exceso por periodo.

- [ ] Ejecutar compilacion:

```powershell
venv\Scripts\python.exe -m py_compile modules\rrhh\service.py modules\rrhh\router.py modules\vacaciones\db_service.py modules\vacaciones\router.py modules\asistencia\db_service.py
```

- [ ] Ejecutar pruebas focalizadas si se agregan:

```powershell
venv\Scripts\python.exe -m pytest tests\test_vacaciones_migracion.py -q
```

## Task 8: Verificacion Manual End-to-End

- [ ] Aplicar migracion 075 en Supabase y verificar columnas.
- [ ] Levantar servidor local.
- [ ] Entrar a `/rrhh/ui` como usuario con acceso manager/editor.
- [ ] Verificar boton "Migracion historica" y progreso.
- [ ] Abrir `/rrhh/migracion` por HTMX y por URL directa.
- [ ] Descargar plantilla y revisar:
  - `usuario_id` oculto.
  - solo empleados con fecha de contratacion.
  - periodos dinamicos.
  - maximos visibles.
  - periodos futuros/inexistentes bloqueados.
  - periodos vencidos marcados pero editables.
- [ ] Subir Excel valido y revisar preview.
- [ ] Subir Excel con error de exceso y confirmar que no aparece boton de confirmar.
- [ ] Confirmar carga valida.
- [ ] Reimportar el mismo Excel y verificar que no duplica registros.
- [ ] Verificar balance del empleado.
- [ ] Verificar que los historicos aparecen en "Mis Solicitudes" como registros historicos.
- [ ] Verificar que no aparecen como "vacaciones hoy" ni afectan asistencia.
- [ ] Probar ajuste individual: guardar y limpiar.

## Riesgos

- Si `migrado_por` no se desea en schema, se puede eliminar del SQL y usar `aprobado_por` como auditoria minima, pero eso mezcla aprobacion con migracion.
- El token firmado puede crecer si la plantilla tiene muchos empleados y periodos. Si supera limites practicos, cambiar a tabla temporal de previews o Redis con TTL explicito.
- Cualquier cambio en calculo de periodos debe respetar `VACACIONES_MESES_EXPIRACION` y `dias_vacaciones_ajuste` para no divergir del balance real.
