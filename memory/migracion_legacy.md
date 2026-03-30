# Migración Legacy — Referencia

## Scripts
- **Activo:** `scripts/_migrate_data.py` (lee Excel `._UPDATE/_primera_carga.xlsx` hoja "data")
- **Descartado:** `scripts/migrate_legacy_data.py` (JSON, no usar)

## Estructura del Excel (_primera_carga.xlsx)

### Columnas clave de control (hoja "data")
| Campo | Rol | Alcance |
|---|---|---|
| `ciclo_id` | Agrupa todas las filas del mismo proyecto/cadena | Igual valor en todas las filas del mismo proyecto |
| `grupo_id` | En ciclo: distingue cada OP (distinto = follow-up). En standalone: vincula PADRE con sus SITIOS | **GLOBAL — único en todo el archivo** |
| `tipo_fila` | `SITIO` = fila de sitio extra (multisitio). Vacío / `PADRE` = fila principal | — |

### REGLA CRÍTICA: grupo_id debe ser único en TODO el Excel
`pre_calculate_hijos_validos` filtra las filas SITIO por `grupo_id` en TODO el dataframe, no solo dentro del cliente/ciclo.
Si G001 aparece en dos clientes distintos, el segundo cliente robará los SITIO del primero → bug silencioso.
**Usar IDs secuenciales globales: G001, G002, G003... sin repetir nunca el mismo valor.**

### Ejemplo verificado (primera carga exitosa 2026-02-24)
```
cliente          | ciclo_id | grupo_id | tipo_fila | tipo_solicitud
-----------------+----------+----------+-----------+---------------
GLN MEXICO       | C001     | G001     |           | PRE OFERTA      ← OP raíz
GLN MEXICO       | C001     | G002     |           | LEVANTAMIENTO   ← follow-up (parent_id=OP raíz)

CATOEX Y EXCAMEX |          | G003     | PADRE     | ACTUALIZACION   ← OP standalone
CATOEX Y EXCAMEX |          | G003     | SITIO     |                 ← sitio Excamex
CATOEX Y EXCAMEX |          | G003     | SITIO     |                 ← sitio Catoex principal
```
- G001/G002 distintos dentro de C001 → `detect_ciclo_mode` = 'followup' → 2 OPs con parent_id
- G003 para CATOEX (no G001) porque G001 y G002 ya están en uso → evita colisión
- G003 igual en PADRE+SITIOs → `pre_calculate_hijos_validos` vincula los 2 sitios → multisitio

### Cómo asignar grupo_id en una carga nueva
- `grupo_id` **nunca se escribe en BD** — es solo un campo de control del Excel
- Solo necesita ser único **dentro del mismo archivo Excel**
- Cada nueva carga puede empezar desde G001 sin conflicto con cargas anteriores
- Reglas dentro del archivo:
  1. Cada fila principal (o conjunto PADRE+SITIOs) recibe un grupo_id único
  2. Las filas SITIO comparten el grupo_id de su PADRE
  3. Las filas de follow-up dentro de un ciclo reciben grupo_ids distintos entre sí

### Tipos de solicitud en el Excel → catálogo
- `PRE OFERTA` / `PRE-OFERTA` / `PREOFERTA` → alias de `PRE_OFERTA`
- `LEVANTAMIENTO` → crea también registro en `tb_levantamientos`
- `ACTUALIZACION` / `ACTUALIZACION DE OFERTA` → alias de `ACTUALIZACION`
- `OFERTA FINAL` → alias de `OFERTA_FINAL`

## Arquitectura de _migrate_data.py (2026-02-24)
- **Input:** Excel pandas, hoja `data`, columnas ya mapeadas por el usuario
- **Ciclos** (`ciclo_id`): `detect_ciclo_mode(rows)` determina si es `historial` o `followup`.
  - **Historial:** todas las filas del ciclo comparten el mismo `grupo_id` (o ninguno) → 1 OP + N historial (`process_ciclo_historial`)
  - **Follow-up:** filas con distintos `grupo_id` → N OPs encadenadas con `parent_id` (`process_ciclo_followup`). Cada grupo genera 1 OP + 1 historial. `MigrationStats.followups` contabiliza las OPs hijas.
- **Multi-sitio** (`tipo_fila` + `grupo_id`): filas con `tipo_fila=SITIO` son sitios extra; se vinculan a la OP padre por `grupo_id`. `pre_calculate_hijos_validos()` cuenta los hijos → `cantidad_sitios`.
- **`insert_followup`**: igual que `insert_oportunidad` pero añade `parent_id` al INSERT. Hereda `cliente`, `nombre_proyecto`, `canal_venta`, `id_tecnologia`, `es_licitacion`, `id_interno_simulacion`, `solicitado_por` del padre cuando la fila actual no los tiene.
- **Standalone:** filas sin `ciclo_id` → oportunidad directa.
- **Levantamientos:** si alguna fila del ciclo/grupo tiene `id_tipo_solicitud=LEVANTAMIENTO` → crea `tb_levantamientos`.
- **Catálogos cargados:** tecnologias, tipos_solicitud, estatus_oportunidades, estatus_levantamiento, usuarios, motivos_cierre, motivos_retrabajo.
