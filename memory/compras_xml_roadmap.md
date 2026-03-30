# Roadmap Compras - XMLs, Materiales y Proveedores

## Estado Actual

### Lo que funciona
- Parser XML CFDI 3.3/4.0 (15 items extraidos correctamente del XML de prueba)
- Matching 3 niveles: relacion conocida → monto → sin match
- Guardado de conceptos/items en `tb_materiales_historial`
- Validacion de items vs subtotal (tolerancia $0.50)
- Prevencion de duplicados XML por UUID
- Sistema de materiales compartido (`core/materials/`) con filtros, analisis precios, Excel
- Relacion beneficiario-proveedor se guarda al confirmar match
- Drop zone se oculta despues de procesar XMLs
- XML solo se sube a SharePoint al confirmar match (no antes)

### Bugs pendientes
- **BUG-1:** Error SharePoint post-confirm: `property 'content_type' of 'UploadFile' object has no setter`
- **BUG-2:** PDFs de comprobantes de pago NO se suben a SharePoint (solo se extraen datos)

---

## FASE 1: Bug Fixes Criticos

### 1.1 Fix upload SharePoint XML (BUG-1) - COMPLETADO
**Problema:** `UploadFile.content_type` es read-only en Starlette moderno.
**Archivo:** `modules/compras/router.py` (endpoint `confirm_xml_match`)
**Solucion:** Pasar `headers=Headers({"content-type": "application/xml"})` en constructor de UploadFile.
**Estado:** COMPLETADO - import `Headers` de starlette.datastructures + constructor con headers

### 1.2 Upload PDFs a SharePoint (BUG-2) - COMPLETADO
**Problema:** Al cargar comprobantes PDF bancarios, solo se extraen datos y se guardan en BD. Los archivos PDF no se persisten en SharePoint.
**Archivo:** `modules/compras/service.py` (metodo `process_and_save_pdfs`)
**Solucion:** Despues de insertar comprobante en BD, se sube PDF a SharePoint y se registra en `tb_documentos_attachments`.
**Estado:** COMPLETADO - Captura `new_id` de insert, seek(0) del file, upload con metadata (beneficiario, monto, moneda), try-except independiente para no afectar el insert

---

## FASE 2: Mejoras al Historial de Materiales

### 2.1 Revision de campos guardados
**Estado actual:** Se guardan `cantidad`, `precio_unitario`, `importe`, `unidad`, `clave_prod_serv`, `clave_unidad`.
**Observacion del usuario:** Para historicos de precios, el `precio_unitario` es el dato clave (precio por unidad). El `importe` (= cantidad * precio_unitario) es util para totales pero puede recalcularse.

**Pregunta de decision:**
- **Opcion A (actual):** Guardar ambos (precio_unitario + importe). Permite validacion cruzada y consultas directas de totales sin recalcular.
- **Opcion B:** Guardar solo precio_unitario y cantidad, calcular importe en queries.
- **Recomendacion:** Mantener ambos (Opcion A). El importe sirve para validacion (suma vs subtotal) y para reportes agregados sin recalcular. El espacio en BD es negligible.

### 2.2 Analisis de precios historicos
**Estado actual:** `core/materials/db_service.py:get_material_precios()` ya hace:
- Busca por descripcion EXACTA del proveedor
- Agrupa por proveedor: min/max/avg precio, total compras, ultima compra
- Excluye un proveedor para comparacion

**Limitacion:** Solo funciona con descripcion textual identica. "TORN. HEX. NC GALV., 3/8 * 2 1/2" vs "TORNILLO HEXAGONAL NC GALVANIZADO 3/8 X 2.5" NO matchea.

**Mejora propuesta:** Ver Fase 3 (busqueda fuzzy).

---

## FASE 3: Busqueda de Coincidencia de Productos

### 3.1 Matching por clave SAT (ClaveProdServ) - COMPLETADO
**Concepto:** Cada concepto CFDI tiene una `clave_prod_serv` del catalogo SAT. Agrupar items por esta clave permite encontrar productos similares entre proveedores.

**Estado:** COMPLETADO
- `core/materials/db_service.py`: nuevo metodo `get_precios_por_clave_sat()` — agrupa por proveedor+descripcion, excluye descripcion exacta actual
- `core/materials/service.py`: `get_material_precios()` ahora retorna 3 valores (material, precios, precios_sat)
- `core/materials/router.py`: pasa `precios_sat` al template
- `templates/materials/partials/modal_precios.html`: nueva seccion "Productos similares" con badge clave SAT, tabla comparativa con descripcion+proveedor+precios

### 3.2 Busqueda fuzzy de descripciones (opcional/futuro)
**Concepto:** Buscar materiales similares por texto de descripcion.
**Opciones tecnicas:**
- **PostgreSQL trigram:** `pg_trgm` extension + indice GIN para `similarity()` queries
- **ILIKE con tokens:** Extraer palabras clave de la descripcion y buscar con AND
- **Normalizacion:** Crear campo `descripcion_normalizada` (minusculas, sin abreviaciones comunes)

**Ejemplo:** "TORN. HEX. NC GALV. 3/8" → normalizado: "tornillo hexagonal nc galvanizado 3/8"

**Decision requerida:** Cual nivel de complejidad implementar? La clave SAT (3.1) cubre el 80% de los casos de uso con 20% del esfuerzo.

### 3.3 Categorizacion automatica de materiales - COMPLETADO
**Estado:** COMPLETADO
- `modules/compras/db_service.py`: nuevo metodo `get_categorias_by_claves_sat()` — batch lookup (evita N+1) de categorias para lista de claves SAT
- `guardar_conceptos_historial()`: extrae claves SAT unicas, hace batch lookup, asigna `id_categoria` en el INSERT
- Log: reporta cuantos items fueron auto-categorizados vs total

---

## FASE 4: Mejoras a Relacion Beneficiario-Proveedor

### 4.2 Matching bidireccional nombres - COMPLETADO
**Estado:** COMPLETADO
- `db_service.py`: nuevo `buscar_comprobantes_por_nombres_proveedor()` — busca comprobantes por razon_social/nombre_comercial del proveedor
- `service.py _buscar_match()`: nuevo Nivel 1.5 entre relaciones conocidas y monto — usa nombres del proveedor
- `service.py confirmar_match_xml()`: al confirmar, guarda hasta 3 relaciones: beneficiario_orig + razon_social + nombre_comercial (si son diferentes entre si)

### 4.3 Confianza progresiva - COMPLETADO
**Estado:** COMPLETADO
- `db_service.py guardar_relacion_beneficiario()`: cambio `ON CONFLICT DO NOTHING` a `ON CONFLICT DO UPDATE SET confianza = 'AUTO_CONFIRMADO'`
- Primera vez = MANUAL, subsecuente confirmacion = AUTO_CONFIRMADO

### 4.4 Vista de relaciones aprendidas - COMPLETADO
**Estado:** COMPLETADO
- `db_service.py`: `get_relaciones_all()` con busqueda por beneficiario/proveedor/RFC + `delete_relacion()`
- `service.py`: `get_relaciones()` + `delete_relacion()`
- `router.py`: `GET /compras/relaciones` + `DELETE /compras/relaciones/{id}`
- `templates/compras/partials/relaciones_beneficiario.html`: modal con tabla de relaciones, badges confianza, busqueda HTMX, eliminacion con confirmacion
- `content.html`: boton "Relaciones" (teal) + container `#relaciones-container`

---

## FASE 5: Reportes y Dashboards (futuro)

### 5.1 Dashboard de compras por proveedor
- Total comprado por proveedor (MXN/USD)
- Top productos por proveedor
- Comparacion de precios entre proveedores para mismo producto (clave SAT)

### 5.2 Alertas de precios
- Detectar si un proveedor subio precios vs historico
- Notificar si hay proveedor mas barato para el mismo producto

### 5.3 Reporte de materiales sin categorizar
- Lista de items en historial sin `id_categoria`
- Bulk categorization UI

---

## Resumen de Prioridades

| Fase | Descripcion | Esfuerzo | Impacto |
|------|-------------|----------|---------|
| 1.1 | Fix content_type SharePoint | Minimo | Critico |
| 1.2 | Upload PDFs a SharePoint | Medio | Alto |
| 2.1 | Mantener importe (decision) | Ninguno | Informativo |
| 3.1 | Matching por clave SAT | Bajo | Alto |
| 3.3 | Auto-categorizar por clave SAT | Bajo | Medio |
| 4.2 | Matching bidireccional nombres | Medio | Alto |
| 4.4 | Vista de relaciones aprendidas | Medio | Medio |
| 3.2 | Busqueda fuzzy descripciones | Alto | Medio |
| 4.3 | Confianza progresiva | Bajo | Bajo |
| 5.x | Reportes y dashboards | Alto | Medio |
