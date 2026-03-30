# Simulacion — Mejoras Modal Update Oportunidades

**Creado:** 2026-03-04
**Estado:** IMPLEMENTADO — pendiente prueba en app

---

## 1. Cambios en Reglas de Negocio del Modal (2026-03-04)

### Validaciones frontend + backend

| Regla | Detalle |
|-------|---------|
| Responsable requerido en **Entregado** | Bloquea submit si `responsable` vacío |
| Responsable requerido en **Perdido** | Igual — entra en métricas |
| **Cancelado** exento de responsable | No entra en métricas KPI |
| Potencia FV (KWp) **opcional** si BESS puro | `id_tecnologia == 2` |
| **Monto de Cierre (USD)** visible en panel Entregado | Columna `monto_cierre_usd` ya existía en BD |

### Archivos modificados
- `modules/simulacion/router.py` — agrega `is_bess_only` al contexto del modal
- `modules/simulacion/db_service.py` — `get_oportunidad_for_update()` incluye `id_tecnologia`
- `modules/simulacion/service.py` — validación potencia condicional + monto ya no se pisa de BD
- `templates/simulacion/modals/update_oportunidades.html` — lógica Alpine.js + UI

---

## 2. Feature: Simulaciones Adicionales (2026-03-04)

### Concepto
Al marcar Entregado o Perdido, se pregunta si se realizaron más de una simulación.
Cada simulación adicional es un **ticket independiente** para efectos de KPIs.
La simulación principal (#1) sigue en `tb_oportunidades`. Las adicionales en tabla nueva.

### BD — ✅ TABLA APLICADA EN SUPABASE
**Migración:** `migrations/007_simulaciones_adicionales.sql`

```
tb_simulaciones_adicionales
├── id UUID PK
├── id_oportunidad UUID FK → tb_oportunidades
├── numero INTEGER (2, 3, 4... — la principal es siempre #1)
├── potencia_cierre_fv_kwp NUMERIC nullable
├── capacidad_cierre_bess_kwh NUMERIC nullable
├── monto_cierre_usd NUMERIC nullable
├── kpi_status_interno VARCHAR(30)  — heredado del padre al cierre
├── kpi_status_compromiso VARCHAR(30) — heredado del padre al cierre
├── fecha_entrega TIMESTAMPTZ — igual que padre
└── creado_en TIMESTAMPTZ DEFAULT now()
UNIQUE (id_oportunidad, numero)
INDEX idx_sim_adicionales_op ON (id_oportunidad)
```

### Archivos modificados
| Archivo | Cambio |
|---------|--------|
| `modules/simulacion/schemas.py` | `SimulacionAdicionalItem` + campo en `SimulacionUpdate` |
| `modules/simulacion/db_service.py` | `insert_simulaciones_adicionales()` + `get_simulaciones_adicionales()` + UNION ALL en 3 queries KPI |
| `modules/simulacion/service.py` | Paso 4.5 en `update_simulacion_padre()` |
| `modules/simulacion/router.py` | Modal carga existentes; PUT parsea JSON |
| `templates/simulacion/modals/update_oportunidades.html` | Sección UI completa |

### Comportamiento UX
- Al re-abrir modal de oportunidad ya cerrada con adicionales → **banner read-only** (no editable)
- Input numérico: máx 99, bloquea `e E + - .`
- Si > 10 adicionales → alerta visual naranja "¿Estás seguro?"
- Validación por fila: misma lógica condicional (BESS puro, BESS híbrido)

### KPI — UNION ALL en 3 queries
Las 3 funciones de reporte incluyen adicionales vía `UNION ALL` en el CTE:
- `get_report_metricas_generales_row()`
- `get_report_metricas_tech()`
- `get_report_resumen_mensual()`

Métricas afectadas: `total_ofertas`, `entregas_a_tiempo/tarde` (interno y compromiso), `total_sitios_entregados`.
**Sin cambio:** `total_solicitudes` (por oportunidad), `tiempo_promedio_horas` (adicionales tienen NULL), `retrabajos`, `canceladas`.

### Reglas de negocio
- KPIs de adicionales = heredados del padre (mismo deadline, misma `fecha_entrega`)
- Solo se capturan al momento del cierre (Entregado o Perdido)
- Una vez guardadas, son inmutables (se muestran read-only en modal)
- Aplican a Entregado **y** Perdido
