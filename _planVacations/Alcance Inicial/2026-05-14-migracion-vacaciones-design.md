# Diseño: Migración de Historial de Vacaciones

**Fecha:** 2026-05-14  
**Branch:** feature/vacaciones  
**Estado:** Aprobado — pendiente plan de implementación

---

## Contexto

El módulo de vacaciones calcula periodos al vuelo desde `fecha_contratacion`. Empleados con historial previo al sistema arrancarían con saldo incorrecto (como si nunca hubieran tomado días). Esta feature permite a RH registrar los días ya consumidos antes del lanzamiento.

---

## Alcance

**Opción C — Excel masivo + ajuste individual por empleado**

### Punto de entrada

Un botón **"Migración histórica"** en la pantalla principal de RRHH (no una pestaña nueva). Al hacer clic navega a una **vista dedicada** (`/rrhh/migracion`) con dos secciones: carga masiva y ajuste individual. Usa el patrón HTMX estándar con `hx-target="#main-content"` y `hx-push-url="true"`.

**Permiso:** `require_manager_access("rrhh")` — RRHH manager editor o superior.

**Badge de progreso** en el botón: muestra cuántos empleados ya tienen migración registrada vs total de empleados con fecha de contratación.

---

## Modelo de Datos

### Migración SQL: 075

Agregar campo a `tb_solicitudes_ausencia`:

```sql
ALTER TABLE tb_solicitudes_ausencia
  ADD COLUMN IF NOT EXISTS es_migracion BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_solicitudes_ausencia_migracion
  ON tb_solicitudes_ausencia (usuario_id, es_migracion)
  WHERE es_migracion = TRUE;
```

**Por qué este campo y no una tabla separada:**  
Los registros migrados participan en el mismo cálculo FIFO que las solicitudes normales — el balance los consume igual. El flag solo cambia cómo se muestran en el historial y permite borrarlos al re-importar sin afectar solicitudes reales.

**Re-import limpio:**
```sql
-- Borra consumos → luego solicitudes (FK)
DELETE FROM tb_vacaciones_consumo
  WHERE solicitud_id IN (
    SELECT id FROM tb_solicitudes_ausencia
    WHERE usuario_id = $1 AND es_migracion = TRUE
  );
DELETE FROM tb_solicitudes_ausencia
  WHERE usuario_id = $1 AND es_migracion = TRUE;
```

---

## Flujo A — Carga Masiva (Excel)

### Descarga de plantilla

Endpoint: `GET /rrhh/migracion/plantilla`

- Incluye **solo empleados con `fecha_contratacion` definida**
- Columnas fijas: `usuario_id` (oculta, para import), `Nombre`, `Email`, `Fecha contratación`, `Periodos calculados`
- Columnas dinámicas: una por cada periodo disponible hasta hoy, basadas en el empleado con más periodos
  - Encabezado: `Periodo N (máx X días)` — ej. `Periodo 1 (máx 15 días)`
  - Periodos expirados: celda bloqueada con fondo gris (no tiene sentido migrar)
  - Periodos que el empleado aún no tiene (columnas de otros empleados): celda vacía bloqueada
- Columna `Ya migrado`: `Sí/No` — referencia visual para RH

### Importación

Endpoint: `POST /rrhh/migracion/importar`

**Validaciones por fila:**
- Días ingresados ≥ 0
- Días ingresados ≤ días máximos del periodo (según catálogo + antigüedad)
- `usuario_id` existe y tiene `fecha_contratacion`
- Suma total de días no excede total de días otorgados en todos sus periodos

**Respuesta previa a confirmación:**  
El backend devuelve un preview con filas OK (verde) y filas con error (rojo + mensaje). El frontend muestra la tabla antes de confirmar.

**Confirmación:** `POST /rrhh/migracion/confirmar` con token del preview

**Al confirmar (por empleado, en transacción):**
1. Borrar migración anterior del empleado (si existe)
2. Para cada periodo con días > 0:
   - Insertar en `tb_solicitudes_ausencia`: `es_migracion=TRUE`, `estado='aprobado'`, `tipo_ausencia` = slug vacaciones, `fecha_inicio = fecha_aniversario_periodo`, `fecha_fin = fecha_aniversario_periodo`, `dias_solicitados = días del periodo`
   - Insertar en `tb_vacaciones_consumo`: `solicitud_id`, `num_periodo`, `dias_consumidos`, `fecha_aniversario_periodo`

---

## Flujo B — Ajuste Individual

En la vista de detalle de empleado en RRHH, sección colapsable **"Historial previo al sistema"**:

- Muestra los periodos calculados del empleado con un input numérico por periodo
- Encabezado por periodo: `Periodo N — Del DD/MM/YYYY al DD/MM/YYYY — Otorgados: X días`
- Periodos expirados: input solo lectura (mostrar valor migrado si existe, no editable)
- Periodos futuros: no se muestran
- Botón **"Guardar historial"**: misma lógica transaccional que la importación masiva
- Botón **"Limpiar migración"**: elimina solo los registros migrados del empleado (con confirmación)

---

## Display en Historial del Empleado

En `templates/vacaciones/partials/historial.html`, los registros con `es_migracion = TRUE` muestran:

```
Vacaciones tomadas (antes del sistema) — N días — Periodo N
[etiqueta gris "Registro histórico"]
```

Los registros normales no cambian.

---

## Archivos a Crear / Modificar

| Archivo | Acción | Descripción |
|---|---|---|
| `migrations/075_migracion_vacaciones.sql` | Crear | Campo `es_migracion` en `tb_solicitudes_ausencia` |
| `modules/rrhh/router.py` | Modificar | Endpoints migración: plantilla, importar, confirmar, individual |
| `modules/rrhh/service.py` | Modificar | Lógica de generación Excel, validación, inserción transaccional |
| `modules/vacaciones/db_service.py` | Modificar | Queries: borrar migración, insertar solicitud+consumo migrados |
| `templates/rrhh/partials/content.html` | Modificar | Botón "Migración histórica" + badge |
| `templates/rrhh/partials/migracion.html` | Crear | Vista dedicada `/rrhh/migracion` con carga masiva + estado |
| `templates/rrhh/partials/empleado_editar.html` | Modificar | Sección "Historial previo al sistema" |
| `templates/vacaciones/partials/historial.html` | Modificar | Etiqueta especial para registros migrados |

---

## Consideraciones Adicionales

- **Empleados sin fecha de contratación:** excluidos de la plantilla y del ajuste individual (se muestra aviso)
- **Periodos expirados:** se pueden migrar para que el historial sea completo, pero no afectan el saldo disponible (ya expiró)
- **Idempotencia:** re-importar el mismo Excel dos veces produce el mismo resultado
- **Auditoría:** los registros migrados tienen `created_by` = usuario RH que ejecutó la migración
- **Librería Excel:** `openpyxl` — ya usada en el proyecto para otros reportes
