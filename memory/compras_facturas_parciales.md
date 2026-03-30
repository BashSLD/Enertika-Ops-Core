---
name: compras_facturas_parciales
description: Arquitectura y reglas de negocio del soporte de facturas parciales y cierre de remanente en módulo Compras
type: project
---

# Compras — Facturas Parciales y Remanentes (implementado 2026-03-17)

## Qué hace
Permite que un comprobante de pago (importado de PDF bancario) reciba N facturas XML hasta cubrir el monto total. Si el proveedor no emitirá más facturas, se puede cerrar el remanente con un motivo.

## Nuevos estatus de comprobante
- `PARCIALMENTE_FACTURADO` — tiene facturas vinculadas pero no cubren el total (± $0.50)
- `CERRADO` — cerrado manualmente; puede tener remanente sin facturar

Estatus completo: `PENDIENTE → PARCIALMENTE_FACTURADO → FACTURADO` o `PENDIENTE/PARCIALMENTE_FACTURADO → CERRADO`

## Schema — campos nuevos en tb_comprobantes_pago (migración 021)
- `monto_facturado NUMERIC NOT NULL DEFAULT 0` — acumulado denormalizado de facturas vinculadas
- `monto_remanente NUMERIC` — calculado al cerrar (monto - monto_facturado)
- `motivo_cierre TEXT` — texto libre requerido al cerrar
- `cerrado_por_id UUID FK tb_usuarios` — quién cerró
- `cerrado_at TIMESTAMPTZ`

## Junction table tb_comprobante_facturas
Ya existía. Es la fuente de verdad de todas las facturas vinculadas. `monto_facturado` en tb_comprobantes_pago es denormalizado de esta tabla.

## Lógica confirmar_match
- Insertar en junction table PRIMERO, luego llamar `confirmar_match()`
- `confirmar_match()` recibe `monto_factura` como parámetro
- `nuevo_monto_facturado = monto_facturado_actual + monto_factura`
- Si `nuevo_monto_facturado >= monto_pago - $0.50` → FACTURADO
- Si no → PARCIALMENTE_FACTURADO
- `uuid_factura` e `id_proveedor` en tb_comprobantes_pago se setean con `COALESCE(..., $val)` — solo si eran NULL (primera factura)
- Anti-sobrefacturación: si `monto_ya_facturado + monto_nueva > monto_pago + $0.50` → ValueError bloqueante

## Matching — nuevo nivel PARCIAL_MATCH
Se agrega entre MONTO_MATCH y NO_MATCH:
- Busca comprobantes PENDIENTE o PARCIALMENTE_FACTURADO del mismo proveedor (por RFC del XML)
- Donde `(monto - monto_facturado) >= monto_xml - $0.50`
- Retorna `match_type = "PARCIAL_MATCH"`
- NO permite AUTO_MATCH (requiere confirmación manual)

## Métodos nuevos en db_service.py
- `buscar_comprobantes_parciales_por_proveedor(id_proveedor, moneda, monto_xml, tolerancia)`
- `desvincular_factura(id_comprobante, uuid_factura)` — borra junction + historial materiales, recalcula estatus
- `cerrar_remanente(id_comprobante, motivo, user_id)` — solo sobre PENDIENTE o PARCIALMENTE_FACTURADO
- `reabrir_comprobante(id_comprobante)` — solo sobre CERRADO; calcula estatus anterior por monto_facturado

## Endpoints nuevos en router.py
- `GET  /compras/comprobante/{id}/facturas-vinculadas`
- `DELETE /compras/comprobante/{id}/factura/{uuid}`
- `POST /compras/comprobante/{id}/cerrar-remanente` (form: motivo)
- `POST /compras/comprobante/{id}/reabrir`

## Templates
- `row_comprobante.html` — badge naranja "Parcial X%" con montos, badge gris "Cerrado" con remanente; botón de ícono abre panel expansible en fila siguiente
- `comprobante_facturas_vinculadas.html` — panel con barra de progreso, tabla de facturas, botones desvincular/cerrar/reabrir, modal de cierre integrado
- `xml_upload_result.html` — sección PARCIAL_MATCH en naranja entre MULTIPLE_MATCH y NO_MATCH
- `xml_confirm_result.html` — diferencia visual verde (completo) vs naranja (parcial) con saldo restante
- `estadisticas.html` — contadores Parciales y Cerrados (aparecen solo si > 0)
