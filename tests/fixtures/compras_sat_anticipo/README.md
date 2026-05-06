# Fixtures SAT Inbox - Anticipos

Estos XML son CFDI 4.0 sinteticos para reproducir pruebas del modulo Compras en `/compras/sat/ui`.

## Archivos

| Caso | Archivo | UUID | Tipo esperado por parser |
| --- | --- | --- | --- |
| 5 | `05_anticipo.xml` | `10000005-0000-4000-8000-000000000005` | `ANTICIPO` |
| 6 | `06_cierre_anticipo_relacion_07.xml` | `10000006-0000-4000-8000-000000000006` | `CIERRE_ANTICIPO` |
| 7 | `07_cierre_anticipo_sin_07.xml` | `10000007-0000-4000-8000-000000000007` | `CIERRE_ANTICIPO` |
| 8 | `08_cierre_anticipo_sin_07_pendiente.xml` | `10000008-0000-4000-8000-000000000008` | `CIERRE_ANTICIPO` |

Proveedor emisor comun: `PAT2605015A1` / `PROVEEDOR ANTICIPOS TEST SA DE CV`.

## Carga automatica para ambiente de prueba

El SAT Inbox descarga el XML desde SharePoint al abrir el modal. Por eso no basta con insertar filas en `tb_sat_inbox`: cada fila necesita un `sharepoint_item_id` real. El script sube estos XML al SharePoint SAT configurado (`SP_SAT_SITE_ID`, `SP_SAT_DRIVE_ID`, `SP_SAT_BASE_FOLDER`) y crea los comprobantes/inbox necesarios.

```powershell
venv\Scripts\python.exe tests\fixtures\compras_sat_anticipo\seed_inbox.py --user-email tu.usuario@enertika.com
```

Para reiniciar completamente los datos de estas pruebas antes de cargarlos de nuevo:

```powershell
venv\Scripts\python.exe tests\fixtures\compras_sat_anticipo\seed_inbox.py --user-email tu.usuario@enertika.com --reset
```

`--reset` limpia vinculos, materiales, relaciones CFDI, staging, inbox y adjuntos XML asociados a estos UUIDs/comprobantes fixture. Despues restaura los comprobantes iniciales y vuelve a cargar los XML al SAT Inbox.

El script crea o actualiza:

| ID comprobante | Uso | Estatus inicial | Monto |
| --- | --- | --- | --- |
| `30000005-0000-4000-8000-000000000005` | Caso 5, opcion PENDIENTE | `PENDIENTE` | `11600.00` |
| `30000015-0000-4000-8000-000000000015` | Caso 5, opcion PARCIALMENTE_FACTURADO | `PARCIALMENTE_FACTURADO` | `21600.00` |
| `30000025-0000-4000-8000-000000000025` | Caso 5, opcion ANTICIPO | `ANTICIPO` | `31600.00` |
| `30000006-0000-4000-8000-000000000006` | Caso 6, anticipo relacionado por UUID `10000006-0000-4000-8000-0000000000A6` | `ANTICIPO` | `6006.00` |
| `30000007-0000-4000-8000-000000000007` | Caso 7, rechazo esperado por exceder monto | `ANTICIPO` | `7007.00` |
| `30000008-0000-4000-8000-000000000008` | Caso 8, cierre parcial menor al anticipo | `ANTICIPO` | `11600.00` |

## Notas de reproduccion

Caso 5: abre `05_anticipo.xml` en SAT Inbox y procesa el modal. El selector debe incluir comprobantes en `PENDIENTE`, `PARCIALMENTE_FACTURADO` y `ANTICIPO`, priorizando el RFC del emisor.

Caso 6: abre `06_cierre_anticipo_relacion_07.xml` y selecciona el comprobante `30000006-0000-4000-8000-000000000006`. Ese comprobante tiene `uuid_factura = 10000006-0000-4000-8000-0000000000A6`, que coincide con la relacion `TipoRelacion="07"` del XML.

Caso 7: abre `07_cierre_anticipo_sin_07.xml` y selecciona el comprobante `30000007-0000-4000-8000-000000000007`. El XML totaliza `11600.00` contra un anticipo de `7007.00`; debe mostrar error por excedente y no vincular.

Caso 8: abre `08_cierre_anticipo_sin_07_pendiente.xml` y selecciona el comprobante `30000008-0000-4000-8000-000000000008`. El XML totaliza `5800.00` contra un anticipo de `11600.00`; debe permitir el match como parcial.
