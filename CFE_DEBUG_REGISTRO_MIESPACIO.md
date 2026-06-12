# CFE — Debug: registro de servicio nuevo en MiEspacio no funciona

> Documento de contexto para retomar este trabajo en cualquier chat.
> Fecha de apertura: **2026-06-12**. Estado: **diagnóstico en curso** (esperando volcado del DOM real).

---

## 1. Problema

Al dar de alta un **servicio nuevo** (que no existe en el portal MiEspacio de CFE), el scraper
**no logra registrarlo** en MiEspacio. Solo trae los XML del portal público; los PDF (que viven en
MiEspacio) nunca se obtienen porque el servicio nunca queda dado de alta.

### Caso concreto observado
- **Servicio nuevo:** `520991114355` — **SATELITES MEXICANOS** (no existe en MiEspacio).
- **Servicio ya registrado (contexto):** `040050503609` — **MORAN**.

### Bug histórico (ya corregido — NO es el problema actual)
Antes del último fix: al registrar un servicio nuevo, CFE tarda unos segundos en mostrarlo en el
dropdown ("propagación pendiente"). El código esperaba 3s, intentaba seleccionarlo, y si no aparecía
**retornaba silenciosamente** en vez de abortar. El scraper entonces descargaba los periodos del
servicio que **ya estaba seleccionado** en la página (MORAN) y los guardaba **como si fueran del
servicio nuevo** (SATELITES). Resultado: 2 recibos reales de SATELITES + 10 contaminados de MORAN.

**Fix aplicado** (commit `d019387`): una línea — `raise` después del warning en
`_ensure_service_miespacio` (`modules/cfe/scraper.py:1354/1355`). Cuando el servicio no propaga a
tiempo, la excepción sube a `descargar_periodos_busqueda`, que la captura, marca `pdf_error` en los
periodos y deja correr el fallback al portal público. **Ya no contamina datos.** ✅

### Problema que QUEDA (lo que estamos depurando)
Tras el fix, al dar click en "descargar periodos" desde la UI:
- ✅ Trae correctamente los XML del portal público (verificado físicamente).
- ❌ **Sigue sin registrar el servicio en MiEspacio.**

El mensaje *"registrado en MiEspacio pero aun no visible (propagacion pendiente)"* es **engañoso**:
el alta realmente **falla**, no es que CFE tarde en propagar.

### Log real del caso (2026-06-12 13:38)
```
13:38:00 [CFE] Busqueda reclamada busqueda_id=9d080d7a... servicio_id=d63ad723... max_periodos=12
13:38:00 [CFE] Usando proxy http://201.158.1.231:3128
13:38:09 Descargando XML portal publico CFE servicio=520991114355 periodo=2026-05 ...  (seed para total)
13:38:19 Registrando servicio 520991114355 en MiEspacio...
13:38:27 Servicio 520991114355 registrado en MiEspacio pero aun no visible (propagacion pendiente)
13:38:27 Fase MiEspacio fallo servicio=520991114355: Servicio 520991114355 no registrado en MiEspacio.
13:38:27 Descargando XML portal publico CFE servicio=520991114355 periodo=2026-04 ... (fallback)
... (sigue bajando XML públicos 2026-03 ... 2025-12) ...
13:38:31 Subiendo BH-000050340014.xml ... /_staging/9d080d7a.../520991114355/2026-05/...
```

**Evidencia clave del timing:** el "registro" tomó solo **8 segundos** (13:38:19 → 13:38:27).
Los `wait` fijos del código de registro ya suman ~7s (`wait 2000` + `wait 3000` + `wait 2000`) más
3-4 `goto`. **No hay margen para que un `__doPostBack` real de guardado haya ocurrido.** Conclusión:
el click "Guardar" no produjo un guardado efectivo.

---

## 2. Flujo actual (paso a paso)

### Alta del servicio en la app (hoy)
`POST /cfe/servicios` → `service.py:crear_servicio()`. Solo inserta fila en `tb_cfe_servicios`
(con el módulo). **No toca MiEspacio.** El botón de UI "Agregar servicio" hoy = solo alta en ECO.

### Búsqueda/descarga de periodos (donde ocurre el alta en MiEspacio hoy)
1. `POST /cfe/servicios/{id}/buscar-periodos` → `service.py:iniciar_busqueda_periodos()` — encola fila
   `pendiente`, retorna inmediato.
2. Worker (`procesar_descargas_cfe_periodically`, cada ~30s, semáforo global `_scrape_lock=1`) reclama
   la búsqueda → `_ejecutar_busqueda_periodos()` → `scraper.py:descargar_periodos_busqueda()`.
3. Dentro del scraper:
   - **FASE 1** portal público: detecta periodos, baja el **XML más reciente** y extrae el
     **total** (`_total_recibo_sin_decimales`) → necesario para el alta en MiEspacio.
   - **FASE 2** MiEspacio (`_fase_miespacio_otras`): `_setup_miespacio_page` → `_detect_block` →
     `_is_logged_in` → `_select_service_miespacio`. Si `MiEspacioServiceNotFound` →
     **`_ensure_service_miespacio`** (← aquí se intenta el alta) → abre OtrasFacturas → baja XML+PDF.
   - **FASE 3** fallback XML público para periodos sin XML.

### El alta en MiEspacio — `_ensure_service_miespacio` (`scraper.py:1325`)
```python
try: await _select_service_miespacio(page, cfg); return        # ya existe → listo
except MiEspacioServiceNotFound: pass
# Registrar:
await page.goto(CFE_MIESPACIO_ADD_URL, ...)                    # goto DIRECTO (no pasa por AdministrarServicios)
await _fill_first_matching(page, ["numero de servicio","número de servicio","rpu"], cfg.numero_servicio)
await _fill_first_matching(page, ["nombre del servicio","nombre servicio"], cfg.nombre)
await _fill_first_matching(page, ["total a pagar","sin decimales","total"], total_sin_dec)
await _fill_first_matching(page, ["nombre corto","alias","corto"], cfg.alias or cfg.numero_servicio[:20])
await _click_first_matching(page, ["guardar","agregar","aceptar"])
# espera + reintenta select; si no aparece → warning + raise
```
- `_fill_first_matching` (`scraper.py:1178`): scoring **heurístico por texto**, setea `.value` por JS
  + dispara `input`/`change`.
- `_click_first_matching` (`scraper.py:1204`): clickea el **primer** `button,input,a` en orden DOM cuyo
  id/name/value/innerText contenga *cualquiera* de los labels.

---

## 2.bis — DOM REAL capturado (2026-06-12, `dom_dump_20260612_082015`)

Volcado con `tools/cfe/volcar_dom.py`. **Resultado que cambia el diagnóstico.**

### Selectores reales de `AgregarServicio.aspx` (ASP.NET WebForms)
| Campo | id real | name |
|---|---|---|
| Número de servicio | `ctl00_MainContent_txtRpu` | `ctl00$MainContent$txtRpu` |
| Nombre del servicio | `ctl00_MainContent_txtNombreServicio` | `ctl00$MainContent$txtNombreServicio` |
| **Total a pagar (SIN DECIMALES)** | `ctl00_MainContent_txtTotalAPagar` | `ctl00$MainContent$txtTotalAPagar` |
| Nombre corto | `ctl00_MainContent_txtNombreCorto` | `ctl00$MainContent$txtNombreCorto` |
| **Botón Guardar** (`input[type=submit]`) | `ctl00_MainContent_btnGuardar` | `ctl00$MainContent$btnGuardar` |
| Botón Cancelar | `ctl00_MainContent_btnCancelar` | — |

- La página trae `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION` → **postback WebForms clásico**.
- Navegación real: en `AdministrarServicios.aspx` el acceso es un `<a href="AgregarServicio.aspx">AGREGA
  NUEVO RECIBO</a>` (GET directo, **no** postback) → `page.goto(AgregarServicio.aspx)` es equivalente.

### Lo que el DOM DESCARTA
- **H2 (click equivocado): DESCARTADA.** En `AgregarServicio.aspx`, el único elemento cuyo texto/value
  contiene "guardar/agregar/aceptar" es `btnGuardar` (value="Guardar"). Ningún `<a>` del navbar matchea.
  El `_click_first_matching` actual SÍ acierta en este form.
- **H3 (fill campo equivocado): DESCARTADA.** Verificado el scoring de `_fill_first_matching` contra los
  contextos reales ("NÚMERO DE SERVICIO:", "NOMBRE DEL SERVICIO:", "TOTAL A PAGAR (SIN DECIMALES):",
  "NOMBRE CORTO..."): cada label gana en su campo correcto, sin colisiones.
- **H5 (navegación directa rompe contexto): DESCARTADA.** El acceso oficial es un link GET a la misma URL.

### Lo que el DOM REFUERZA → causa raíz se concentra en H1 + falta de verificación
Como selectores/click/navegación están bien, lo que queda es el **VALOR del total** y que el código
**no verifica el resultado del submit**. `validadores` salió vacío porque la página se capturó limpia
(sin submit); el mensaje de error de CFE solo aparece DESPUÉS de un Guardar fallido.

**Matiz nuevo del extractor** (`modules/shared/services/cfe/extractor.py`): el XML CFE distingue
`cfdi.total` = `root.attrib["Total"]` (Total **fiscal** del CFDI, línea 135) de los importes del
**registro del recibo** (`IMPTE_TOT_REG_*`, línea 215). `_total_recibo_sin_decimales` usa
`cfdi.total`, que **puede no ser** el "Total a pagar" impreso que CFE valida en el alta.

## 3. Hipótesis de causa raíz (ordenadas por probabilidad)

> Tras el DOM real: **H2, H3, H5 DESCARTADAS.** Vigentes: **H1 (total)** como dominante y **H4** (menor).

> **Evidencia de campo (2026-06-12):** servicio registrado AVICOLA SAN ANDRES `301940156068` →
> "Total a pagar" del recibo = **17,799**, pero `cfdi.total` del XML = **17,798.93**. `round(17798.93)`
> = 17799 → coincide **por suerte** (los `.93` redondean arriba). Confirma que CFE valida el entero del
> **recibo**, no el del XML, y que `round(cfdi.total)` NO es una fórmula confiable: cuando el redondeo de
> CFE difiere (truncado, DAP, saldos), el alta se rechaza. Esto es lo que pasa con SATELITES.

**H1 — Total incorrecto (sospechoso #1, CONFIRMADO como mecanismo).** `_total_recibo_sin_decimales` (`scraper.py:724`):
```python
total_val = receipt.get("cfdi", {}).get("total", 0)
return str(round(float(total_val)))
```
- **`round()` vs truncar:** "Sin decimales" en CFE = parte entera (truncar). `12345.80 → round → 12346`
  ≠ `12345`. CFE valida ese total contra su registro como prueba de titularidad; si no es exacto,
  **rechaza el alta**.
- **`cfdi.total` ≠ "Total a pagar" del recibo:** el total del CFDI timbrado puede diferir del *Total a
  pagar* impreso (DAP/alumbrado, saldos anteriores, redondeo). Si difieren, alta rechazada.
- No hay log del valor enviado → pudo ir incluso `"0"`.

**H2 — Click en elemento equivocado.** `_click_first_matching(["guardar","agregar","aceptar"])` puede
impactar un `<a>` del navbar/menú ("**Agregar** servicio", "Administrar servicios") que aparece antes
en el DOM que el `<input type=submit>` del form. No vemos `ValueError` → clickeó *algo*, posiblemente
el equivocado.

**H3 — `_fill_first_matching` llena campo equivocado.** "nombre del servicio" y "nombre corto"
comparten "nombre"; "total a pagar"/"total" puede colisionar. Si un campo queda vacío/mal, los
validadores ASP.NET cancelan el submit.

**H4 — Validadores ASP.NET bloquean el submit.** Valores seteados por JS (`.value=`); si hay
`RequiredFieldValidator`/`RegularExpressionValidator`, el `__doPostBack` se aborta client-side.

**H5 — Navegación directa a `AgregarServicio.aspx`** sin pasar por `AdministrarServicios.aspx` (como el
flujo manual real). Menos probable sola, pero puede contribuir al estado del form/ViewState.

> **PRUEBA DEFINITIVA (2026-06-12, `alta_dump_20260612_083722`):** alta de SATELITES con monto `1` →
> CFE responde, sin navegar fuera de `AgregarServicio.aspx`, con la alerta literal:
> *"El total a pagar no coincide con nuestro registro, favor de validar la información con su último o
> penúltimo recibo."* **H1 confirmada al 100%.** Señales de rechazo detectables: (a) la alerta con ese
> texto; (b) `sigue_en_alta = /AgregarServicio/i.test(location.href) === true`. Además CFE acepta el
> total del **último O penúltimo** recibo (margen para reintentar). SATELITES sigue SIN registrar
> (solo se probó el monto incorrecto). El extractor (`extractor.py`) NO expone el "Total a pagar" del
> recibo; solo `cfdi.total` (Total fiscal) → hay que decidir la fórmula correcta del total (ver §4).

> **HALLAZGO QUE DEFINE EL FIX (2026-06-12, `alta_dump_20260612_084848`):** SATELITES con `244015`
> → *"Número Servicio agregado exitosamente."* **Registrado ✅.** Comparando los dos casos reales:
> | Servicio | `cfdi.total` | Total aceptado | Operación |
> |---|---|---|---|
> | AVICOLA `301940156068` | 17798.**93** | 17799 | round (↑) |
> | SATELITES `520991114355` | 244015.**57** | 244015 | trunc (↓) |
>
> `.93`→arriba pero `.57`→abajo: **NO es redondeo aritmético.** El "Total a pagar" del recibo es un
> número PROPIO de CFE, **no derivable de `cfdi.total`**. Conclusión: `round(cfdi.total)` (código actual)
> es incorrecto por diseño; acierta por casualidad. **El fix NO puede basarse en `cfdi.total`.**
>
> **SOLUCIÓN CONFIRMADA con XMLs reales (`tools/cfe/BH-...xml` SATELITES, `GI-...xml` AVICOLA):** el XML
> trae el "Total a pagar" como **campo entero propio del recibo**, distinto de `Total=` (cfdi fiscal):
> | Campo XML | SATELITES | AVICOLA | CFE acepta |
> |---|---|---|---|
> | `Total=` (cfdi) | 244015.57 | 17798.93 | ✗ |
> | `<IMPTOTAL>` | 244015 | 17799 | ✓ |
> | `<TOTAL_SIN_ADE>` | 244015 | 17799 | ✓ |
> | `<IMPTOTALXML>` | 244015 | 17799 | ✓ |
>
> **Fix correcto:** leer `IMPTOTAL` / `IMPTOTALXML` / `TOTAL_SIN_ADE` del XML (campos del bloque `reg`),
> NO `round(cfdi.total)`. Los tres coinciden sin adeudo (→ 1 intento). Si difieren (recibo con adeudo
> anterior: `IMPTOTAL` con adeudo vs `TOTAL_SIN_ADE` sin él), probarlos como **candidatos** del último y
> luego penúltimo recibo, deteniéndose en *"agregado exitosamente"* vs *"no coincide"*.

### Defecto de diseño transversal
`_ensure_service_miespacio` es **fire-and-forget**: llena, clickea, espera y reintenta el select.
**Nunca verifica el resultado del guardado ni lee los mensajes de error que CFE muestra.** Por eso
todo fallo de validación se reporta como "propagación pendiente".

---

## 4. Plan acordado

### Paso 1 — DEBUG CERTERO (en curso): volcar el DOM real de `AgregarServicio.aspx`
Para dejar de adivinar selectores. **Plan B = herramienta local Playwright** creada en
`tools/cfe/volcar_dom.py` (ver sección 5). Reutiliza el patrón de `tools/cfe/renovar_sesion.py`
(login manual en Edge, evita IP-block de Railway/proxy). Vuelca campos + botones + HTML de:
`Default.aspx` (dropdown `ddlServicios`), `AdministrarServicios.aspx`, `AgregarServicio.aspx`.

Alternativa rápida (Opción A): snippet de consola del navegador en `AgregarServicio.aspx`:
```javascript
copy(JSON.stringify({
  url: location.href, title: document.title,
  campos: [...document.querySelectorAll('input,select,textarea')].map(e => ({
    tag: e.tagName.toLowerCase(), type:(e.getAttribute('type')||'').toLowerCase(),
    id:e.id||'', name:e.name||'', placeholder:e.placeholder||'',
    contexto:(e.closest('tr,.form-group,.form-row,div')?.innerText||'').trim().slice(0,80),
    visible:!!(e.offsetParent) })),
  botones: [...document.querySelectorAll('button,input[type=submit],input[type=button],a')].map(e => ({
    tag:e.tagName.toLowerCase(), type:(e.getAttribute('type')||'').toLowerCase(),
    id:e.id||'', name:e.name||'', value:e.value||'', text:(e.innerText||'').trim().slice(0,40),
    href:e.getAttribute('href')||'' })).filter(b => /guardar|agregar|aceptar|servicio/i.test(b.id+b.name+b.value+b.text)),
}, null, 2));
```

### Paso 2 — Rediseño: SEPARAR alta-en-MiEspacio de descarga-XML/PDF
Idea del usuario (acordada): el botón **"Agregar servicio"** de la UI no solo lo agrega a ECO, sino
que **valida si existe en MiEspacio y, si no, lo registra**. La descarga de XML/PDF queda
**independiente**. Esto además **elimina la causa raíz** del bug de contaminación (el alta ya no ocurre
a media descarga).

**Matices a respetar en el diseño:**
1. **El alta NO es instantánea → job del worker, no síncrono en el request.** Requiere mini-scrape:
   portal público (XML reciente → total) → MiEspacio (validar/dar de alta). ~30s+, usa `_scrape_lock`,
   puede fallar por IP. Encolar tipo de job `alta_miespacio` en la cola existente. UI muestra estado.
2. **Estado de registro MiEspacio en `tb_cfe_servicios`.** Hoy solo sabe que existe en ECO. Agregar
   p.ej. `miespacio_estatus` (`no_verificado`/`registrando`/`registrado`/`no_aplica`/`error`) +
   `miespacio_error` + timestamp. La búsqueda de periodos lee el estado: si no está `registrado`,
   avisa "primero registra en MiEspacio" en vez de intentarlo a media descarga.
3. **Idempotente + separar "registrado" de "propagado".** Si ya existe → marca `registrado` sin
   re-alta. Si lo da de alta pero aún no aparece en dropdown → marca `registrado` (propagación pendiente
   es OK); la siguiente descarga ya lo encuentra. CON logging del total enviado y de errores de CFE.
4. **Quitar `_ensure_service_miespacio` del camino de descarga.** La descarga asume que ya existe y
   aborta limpio si no.

### Correcciones puntuales candidatas (confirmar con el DOM)
- Total: **truncar** en vez de `round()`; evaluar usar el "total a pagar" del recibo, no `cfdi.total`;
  reintentar con valor alterno si CFE responde "no coincide".
- Click "Guardar" por **selector específico** (id real del submit) en vez de heurística de texto.
- Fills por **id exacto** (como ya hace `_fill_public_form` con `#MainContent_txt...`).
- Leer y loguear los **mensajes de error/validación** de CFE tras el submit + screenshot.

---

## 5. Archivos y referencias clave

| Qué | Dónde |
|---|---|
| Router CFE | `modules/cfe/router.py` |
| Service (orquestación + worker) | `modules/cfe/service.py` |
| Scraper (Playwright) | `modules/cfe/scraper.py` |
| Alta MiEspacio | `scraper.py:_ensure_service_miespacio` (1325), `_ensure_service_miespacio_legacy` (1222) |
| Helpers fill/click heurísticos | `scraper.py:_fill_first_matching` (1178), `_click_first_matching` (1204) |
| Total para alta | `scraper.py:_total_recibo_sin_decimales` (724) |
| Select servicio | `scraper.py:_select_service_miespacio` (1255) |
| Fase MiEspacio | `scraper.py:_fase_miespacio_otras` (945) |
| Herramienta volcar DOM (Plan B) | `tools/cfe/volcar_dom.py` |
| Herramienta alta asistida (debug H1) | `tools/cfe/alta_asistida.py` |
| Herramienta renovar sesión (patrón base) | `tools/cfe/renovar_sesion.py` |
| Constantes / config keys | `modules/cfe/constants.py` |
| Schema servicios/descargas | `migrations/098_cfe_servicios_descargas.sql` |

### URLs MiEspacio (en `scraper.py`)
- Home / dropdown servicios: `https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio/Default.aspx`
  (`#ctl00_MainContent_ddlServicios`)
- Administrar servicios: `https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio/AdministrarServicios.aspx`
- Agregar servicio: `https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio/AgregarServicio.aspx`

### Tablas
- `tb_cfe_servicios` (mig 098, + 103 módulos): `numero_servicio` UNIQUE, `nombre`, `alias`, `lada`,
  `telefono`, `email`, `modulos[]`. ← aquí iría `miespacio_estatus`.
- `tb_cfe_descargas` (mig 098): `(servicio_id, periodo, tipo)` UNIQUE; `tipo IN (xml,pdf)`;
  `estatus IN (pendiente,descargando,completado,error)`.
- `tb_cfe_busqueda*` (mig 099-102): búsquedas + items de staging.

### Migraciones
- Última CFE confirmada: **103** `cfe_servicios_modulo`. Nueva columna de estado MiEspacio → **mig 104+**
  (verificar consecutivo real con `Glob migrations/*.sql` antes de crear).

### Config keys (`tb_configuracion_global`, ver `constants.py:CFE_CONFIG_KEYS`)
`CFE_MIESPACIO_USER`, `CFE_MIESPACIO_PASS`, `CFE_MIESPACIO_SESSION_JSON`, `CFE_SESSION_UPLOAD_TOKEN`,
`CFE_MIESPACIO_SESSION_INVALIDA`, `CFE_LANZADOR_ITEM_ID`, `CFE_LANZADOR_VERSION`.
Proxy: variable de entorno `CFE_PROXY_URL` (sortea bloqueo de IP de Railway).

---

## 6. Estado / próximos pasos

- [x] Fix de contaminación de datos aplicado (commit `d019387`).
- [x] Análisis del flujo y de hipótesis de causa raíz.
- [x] Herramienta `tools/cfe/volcar_dom.py` creada (Plan B).
- [x] DOM real capturado (`dom_dump_20260612_082015`). Selectores reales fijados (ver §2.bis).
- [x] H2/H3/H5 descartadas. Causa raíz concentrada en **H1 (total)** + falta de verificación post-submit.
- [ ] **SIGUIENTE — confirmar H1 con un alta REAL observada:** correr una prueba asistida que llene el
      form con el total real del último recibo de SATELITES y CAPTURE la respuesta de CFE (mensaje de
      error / navegación / screenshot). De paso registra SATELITES. Requiere del usuario: **total a
      pagar exacto (sin decimales) del último recibo** de `520991114355`.
- [ ] Comparar `cfdi.total` (lo que el código envía hoy) vs "Total a pagar" impreso del recibo → si
      difieren, H1 confirmada; usar el total del recibo, no `cfdi.total`.
- [x] Plan aprobado (todo, alta automática al agregar) e **IMPLEMENTADO** (ver §7).
- [ ] Ejecutar migración 104 en Supabase. Probar en Railway. Pipeline `/simplify` → `/code-review` → commit.

## 7. Implementación realizada (2026-06-12)

**Fase 0 — total correcto** · `modules/shared/services/cfe/extractor.py`
- `candidatos_total_a_pagar(content, filename) -> list[str]`: lee `IMPTOTAL`/`IMPTOTALXML`/`TOTAL_SIN_ADE`
  (enteros, sin duplicados, en prioridad). Verificado: SATELITES→`['244015']`, AVICOLA→`['17799']`.

**Fase 1 — alta robusta** · `modules/cfe/scraper.py`
- `registrar_servicio_miespacio(cfg) -> ResultadoAlta` (idempotente): baja último/penúltimo recibo
  público → candidatos; en MiEspacio valida si existe; si no, registra con **selectores reales**
  (`#ctl00_MainContent_txtRpu/txtNombreServicio/txtTotalAPagar/txtNombreCorto`, `btnGuardar`) probando
  candidatos; **lee el resultado** (`agregado exitosamente` / `no coincide` / sesión / bloqueo).
- `ResultadoAlta.estado`: `ya_existia|registrado|total_no_coincide|sesion_invalida|bloqueado|sin_total|error`.
- **Retirado el alta** de `descargar_periodos_busqueda` y `descargar_recibo` (abortan limpio si el servicio
  no está registrado). Eliminadas: `_ensure_service_miespacio(_legacy)`, `_fill_first_matching`,
  `_click_first_matching`, `_total_recibo_sin_decimales`.

**Fase 2 — separación (job + estado)** · migración + `db_service.py` + `service.py`
- `migrations/104_cfe_miespacio_estatus.sql`: `miespacio_estatus` (CHECK), `miespacio_error`,
  `miespacio_verificado_en` + índice parcial de cola. **Ejecutar en Supabase antes de desplegar.**
- `db_service`: `marcar_alta_miespacio_pendiente` (idempotente), `reclamar_alta_miespacio` (FOR UPDATE
  SKIP LOCKED), `marcar_miespacio_estatus`. `get_all_servicios` ahora trae `miespacio_estatus/_error`.
- `service`: `crear_servicio` encola el alta; worker (`procesar_pendientes`) reclama y ejecuta el alta
  primero (bajo `_scrape_lock`, timeout 240s); `_ejecutar_alta_miespacio` mapea estado→estatus y guarda
  sesión renovada; `reintentar_alta_miespacio` para el botón.

**Fase 3 — UI** · `router.py` + `templates/cfe/partials/lista_servicios.html`
- Endpoint `POST /cfe/servicios/{id}/reintentar-alta`. Chip "Registrando en MiEspacio…" / "No registrado"
  (con tooltip del error), botón "Reintentar registro" (si `error`), y polling mientras hay altas en curso.

**Verificación:** py_compile OK en todos; ruff F401/F811/F821 "All checks passed"; import de extractor+scraper
OK; `candidatos_total_a_pagar` devuelve los valores correctos.

**Pulido `/simplify`:** helper `_chromium_launch_kwargs()` (4 copias→1) y `_new_public_context()` (3→1);
inversión de orden en `registrar_servicio_miespacio` (verifica existencia ANTES de scrapear el portal
público → evita ese trabajo en el caso idempotente `ya_existia`); `next()` en `_leer_resultado_alta`;
guard temprano en `_ejecutar_alta_miespacio`; constante `_MSG_SERVICIO_NO_REGISTRADO`.

**Correcciones `/code-review`:**
1. **Reaper para `'registrando'`** (faltaba): `reclamar_alta_miespacio` ahora sella `miespacio_verificado_en`
   al reclamar; `reaper_alta_miespacio_colgada` (15 min) devuelve a `'pendiente'` altas colgadas por worker
   reiniciado; conectado en `reaper_colgados`. Sin esto, un servicio quedaba atascado en `'registrando'`.
2. **Fallback de detección frágil:** si `_registrar_servicio_con_candidatos` "falla" por copy de CFE no
   reconocido pero el servicio ya aparece en el dropdown, se re-verifica con `_select_service_miespacio`
   (fuente confiable) y se marca `registrado`. Evita falsos `total_no_coincide`.
- **No aplicado (decisión):** auto-reencolar `bloqueado`/`sesion_invalida` a `'pendiente'` → causaría retry
  storm contra IP bloqueada (justo lo que evitan los commits recientes). Se mantiene `'error'` + botón
  "Reintentar registro" manual.

**Notas / casos borde:**
- Servicios previos quedan `no_verificado` (benigno): la descarga sigue funcionando si ya estaban en
  MiEspacio; si no existen, aborta limpio (sin contaminar). SATELITES (registrado a mano) entra por aquí.
- El botón "Reintentar registro" solo aparece en estado `error`. Para un `no_verificado` que no esté en
  MiEspacio, re-agregar el servicio (mismo número) reencola el alta (idempotente).
