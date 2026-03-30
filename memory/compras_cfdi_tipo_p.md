---
name: Compras — CFDI Tipo P (Complemento de Pago)
description: Análisis, implementación y pendientes del soporte para CFDI tipo P en el módulo compras
type: project
---

## Contexto

Al subir `Analizar.xml` (proveedor EXEL SOLAR, RFC ESO140130IU1) el sistema reportaba `Total = 0`.
La causa: CFDI con `TipoDeComprobante="P"` tiene siempre `SubTotal="0"` y `Total="0"` en el nodo raíz por especificación SAT CFDI 4.0. El monto real está en `pago20:Pagos`.

**Por:** Bug estructural — el extractor leía `@Total` del nodo raíz sin verificar el tipo de comprobante.

**How to apply:** Al parsear cualquier CFDI verificar primero `TipoDeComprobante` antes de leer montos.

---

## XMLs de referencia (en raíz del proyecto)

| Archivo | Tipo | UUID | Descripción |
|---------|------|------|-------------|
| `Analizar.xml` | P (complemento de pago) | f967f048-... (REQR-1653) | Pago $30,760.41 USD — cubre QR-48678 completa + QR-48679 parcial |
| `Analizar1.xml` | I (factura normal) | c28f48d4-... (QR-48678) | $26,517.60 USD — cable fotovoltaico — MetodoPago PPD |

### Datos del complemento (Analizar.xml)
- Fecha pago: 2026-01-07
- Moneda: USD, TipoCambioP: 17.9697
- Monto total: $30,760.41 USD
- DoctoRelacionado 1: QR-48678 — ImpPagado $26,517.60 / ImpSaldoInsoluto $0.00 (liquidada)
- DoctoRelacionado 2: QR-48679 — ImpPagado $4,242.81 / ImpSaldoInsoluto $224,980.54 (parcial)
- MontoTotalPagos SAT: $552,755.34 MXN (conversión interna SAT, NO usar como monto del comprobante)

### Hallazgo: discrepancia vs $70,000 USD esperados
El usuario esperaba que estos XMLs cubrieran $70,000 USD. El complemento solo acredita $30,760.41 USD.
Probable causa: falta otro complemento de pago de EXEL SOLAR por el saldo restante (~$39,239.59 USD),
o el proveedor emitió el complemento por monto incorrecto. Pendiente conseguir más XMLs para confirmar.

---

## Implementación realizada (2026-03-20)

### Archivos modificados
- `modules/compras/xml_extractor.py`
- `modules/compras/schemas.py`
- `modules/compras/service.py`

### 1. schemas.py — TipoFactura.PAGO
```python
class TipoFactura(str, Enum):
    PAGO = "PAGO"  # CFDI complemento de pago (TipoDeComprobante="P")
```

### 2. xml_extractor.py — Nueva función _extract_pago_info()
Extrae (monto, moneda) reales del pago desde nodos `pago20:Pago`:
- Lee `MonedaP` y suma `Monto` de todos los nodos Pago
- Si todos los pagos son en la misma moneda → devuelve (total, moneda) en esa moneda (ej. USD)
- Si hay monedas mixtas → fallback a `pago20:Totales/@MontoTotalPagos` en MXN
- **NO usar MontoTotalPagos como monto principal** — siempre está en MXN (conversión SAT)

### 3. xml_extractor.py — parse_cfdi_xml()
- Extrae `TipoDeComprobante` ANTES del bloque de total
- Bifurca: tipo P → `_extract_pago_info()`, otros → `@Total` del nodo raíz
- La `moneda` del CfdiData viene de `MonedaP` (no de `@Moneda` que es "XXX" en tipo P)

### 4. xml_extractor.py — _detect_tipo_factura()
- Nuevo check al inicio: `if tipo_comprobante == "P": return TipoFactura.PAGO`

### 5. service.py — confirmar_match_xml()
- Validación anti-sobrefacturación excluye `'PAGO'` además de `'NOTA_CREDITO'` y `'ANTICIPO'`
- Un complemento de pago es evidencia de pago ya realizado, no suma al monto facturado

---

## Pendientes (backlog — esperar más ejemplos de EXEL SOLAR)

### A. DoctoRelacionado para tipo P
`_extract_relacionados()` busca `cfdi:CfdiRelacionados` — NO extrae `pago20:DoctoRelacionado`.
Para tipo P, las facturas pagadas están en una estructura distinta con más datos:
`ImpSaldoAnt`, `ImpPagado`, `ImpSaldoInsoluto`, `NumParcialidad`.

**Viabilidad:** media-baja si es caso particular de un proveedor. Backlog hasta confirmar patrón.
**Lo que requeriría:** nueva función de extracción + mostrar en UI del upload (sin BD necesariamente).

### B. TipoCambio del XML vs DOF
El XML ya trae el tipo de cambio SAT-certificado (`@TipoCambio` para tipo I, `TipoCambioP` para tipo P).
Actualmente `CfdiData` no tiene campo `tipo_cambio` — se ignora y se usa el DOF.

**Propuesta:** agregar `tipo_cambio_xml` a `CfdiData` + guardarlo en `tb_comprobante_facturas`.

| Campo | Fuente | Uso |
|-------|--------|-----|
| `tipo_cambio_xml` | XML (SAT-certificado, al momento de timbrar) | Contabilidad, auditoría |
| `tipo_cambio_dof` | DOF (fetch dinámico) | Referencia de mercado |

**Lo que requeriría:**
1. Campo `tipo_cambio_xml: Optional[Decimal]` en `CfdiData`
2. Extracción en `parse_cfdi_xml` (raíz para tipo I/E, `TipoCambioP` del nodo Pago para tipo P)
3. Columna nueva en `tb_comprobante_facturas` → migración 025 (o la siguiente disponible)
4. Guardarlo en `confirmar_match_xml`

---

## Regla de negocio confirmada (SAT CFDI 4.0)
- Tipo P: `@Moneda="XXX"`, `@Total="0"`, `@SubTotal="0"` — siempre, por spec
- Tipo P: `pago20:Totales/@MontoTotalPagos` — siempre en MXN (moneda de reporte), NO en moneda del pago
- Tipo P: `pago20:Pago/@MonedaP` + `@Monto` — moneda y monto reales del pago
- Tipo I USD: `@TipoCambio` en raíz — tipo de cambio SAT al momento de timbrar
