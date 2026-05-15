# PLAN: Módulo de Vacaciones, Perfil, Firmas y RRHH

> **Fecha:** 2026-05-11
> **Estado:** Implementado en `feature/vacaciones`; pendiente QA/pruebas no funcionales
> **Migraciones:** 066, 067, 068, 069
> **Contexto:** Sistema de vacaciones y ausencias con firmas digitales (imagen), modulo RRHH dedicado en sidebar, y perfil de empleado accesible desde avatar.
> **Actualizacion 2026-05-12:** Las migraciones 066-069 fueron reportadas como ejecutadas. La matriz final de permisos RRHH queda documentada en este plan y en `rules/02-permisos.md`.

---

## 0. Resumen Ejecutivo

El sistema ya cuenta con gestion de vacaciones, perfil de empleado y modulo RRHH. Este documento queda como plan base y bitacora de implementacion:

1. **Modulo RRHH** en sidebar (slug `rrhh`) — visible para usuarios con modulo `rrhh` asignado; permisos por rol de modulo
2. **Mi Perfil** accesible desde el avatar del usuario (dropdown en sidebar, sin modulo sidebar)
3. **Home por defecto**: si el usuario no tiene `modulo_preferido` configurado, redirigir a `/perfil/ui`
4. **Solicitudes de ausencia** con 8 tipos (vacaciones, incapacidad, permisos, home office)
5. **Logica de periodos de vacaciones** con expiracion por periodo (aniversario + 1.5 anos), consumo FIFO, saldo negativo
6. **Progreso dinamico** de dias ganados proporcionalmente desde el ultimo aniversario — se actualiza al vuelo
7. **Firmas digitales con imagen** — reemplaza el flujo Adobe Sign/Power Automate
8. **Multiples jefes** por empleado (tabla muchos-a-muchos `tb_empleados_jefes`), pero un **solo aprobador**
9. **PDF generado** con firmas embebidas, enviado por email a solicitante + CC a RH
10. **Notificaciones** con boton CTA, recordatorio cada 24h al aprobador si no actua
11. **Dias habiles** (L-V) + catalogo de festivos administrado por RH
12. **Dias Enertika = LFT + 3**

---

## 1. Firmas Digitales — Reemplazo de Adobe Sign

### 1.1 Flujo actual (Power Automate + Adobe Sign)

```
Usuario -> formulario -> genera PDF -> envia a Adobe Sign ->
email al usuario -> firma en Adobe -> email al aprobador -> firma en Adobe -> PDF firmado
```

**Problema:** Lento, depende de servicio externo, multiples correos.

### 1.2 Flujo propuesto

```
Usuario -> formulario en app -> click "Enviar solicitud" ->
  |
  +-> Tiene firma guardada?
  |     SI -> firma se coloca automaticamente en PDF, se registra en tb_solicitudes_firmas
  |     NO -> redirigir a seccion "Mi Firma" para crearla, luego continuar envio
  |
  +-> Notificacion al aprobador (email con boton CTA + in-app)
  +-> Recordatorio cada 24h si no ha actuado
  |
Aprobador revisa en app -> click en "Firmar y aprobar" ->
  +-> Su firma (imagen) se coloca en el PDF
  +-> PDF final se genera
  +-> Notificacion al solicitante + CC a RH con PDF adjunto
```

### 1.3 Gestion de firmas (imagen)

**Seccion "Mi Firma" en Mi Perfil:**
- Dos opciones para crear/actualizar firma:
  - **Subir imagen** (PNG, fondo transparente, max 500x200px)
  - **Dibujar firma** (HTML5 Canvas con `signature_pad.js`)
- Si **ya tiene firma guardada**: muestra vista previa + boton "Actualizar firma"
- Si **no tiene firma**: formulario de creacion
- Se guarda como BYTEA en `tb_usuarios_firmas.firma_data` (sin archivos en filesystem)
- Los usuarios con firma en Adobe Sign pueden exportarla como PNG y subirla

**Uso en PDF:**
- Al generar el PDF, la firma se recupera de `tb_usuarios_firmas.firma_data` (BYTEA) y se embebe como `data:image/png;base64,...` directamente en el HTML antes de WeasyPrint
- Si un usuario no tiene firma cargada, se muestra solo la linea con nombre y fecha
- Campos de firma en el PDF:
  ```
  _________________________     _________________________
  Firma del Solicitante         Firma del Aprobador
  Nombre Apellido               Nombre Aprobador
  Fecha: dd/mm/aaaa HH:MM       Fecha: dd/mm/aaaa HH:MM
  ```

**Tabla de firmas (`tb_usuarios_firmas`):**

| Columna | Tipo | Descripcion |
|---|---|---|
| `usuario_id` | UUID PK FK -> tb_usuarios | |
| `firma_data` | BYTEA | Imagen PNG en bytes (embebida como base64 en PDF) |
| `fecha_carga` | TIMESTAMPTZ | Fecha de ultima actualizacion |
| `tipo_firma` | VARCHAR(20) | `subida` / `dibujada` |

---

## 2. Arquitectura General

### 2.1 Ubicacion en el sistema

```
Dos puntos de acceso:

1. SIDEBAR: Modulo RRHH (usuarios con modulo `rrhh` asignado)
   Sidebar -> RRHH -> Dashboard con: personas de vacaciones hoy,
   aprobaciones pendientes, gestion empleados, catalogo festivos y tab Admin

2. DROPDOWN AVATAR: Mi Perfil (todos los usuarios)
   Click en avatar/nombre -> dropdown -> "Mi Perfil"

En base.html (sidebar footer):
  +------------------------+
  | [avatar] Nombre  v     |
  |   +-- Mi Perfil        |  <- GET /perfil/ui
  |   +-- Ayuda            |
  |   +-- Cerrar sesion    |
  +------------------------+
```

### 2.2 Home por defecto

Si el usuario no tiene `modulo_preferido` configurado en `tb_usuarios`, la redireccion post-login o landing por defecto es `/perfil/ui`.

### 2.3 Estructura de archivos

```
modules/rrhh/                        <- NUEVO modulo sidebar
+-- __init__.py
+-- router.py                        # /rrhh/ui, /rrhh/empleados, /rrhh/festivos, /rrhh/admin
+-- service.py
+-- db_service.py
+-- schemas.py
+-- constants.py

modules/vacaciones/                  <- Logica compartida + perfil
+-- __init__.py
+-- router.py                        # /perfil/ui, /perfil/solicitudes, etc.
+-- service.py                       # Orquestacion de negocio
+-- db_service.py                    # Queries SQL puras (asyncpg)
+-- schemas.py                       # Pydantic models
+-- logic.py                         # Logica pura: periodos, FIFO, progreso
+-- constants.py                     # Estados, tipos, prefijos

templates/rrhh/
+-- dashboard.html                   # Pagina completa del modulo RRHH
+-- partials/
    +-- resumen_vacaciones.html      # Personas de vacaciones hoy
    +-- aprobaciones_pendientes.html # Solicitudes por aprobar (global)
    +-- empleados_lista.html         # Tabla empleados (load-more)
    +-- empleado_editar.html         # Formulario editar datos empleado
    +-- festivos_lista.html          # Catalogo festivos
    +-- festivos_form.html           # Formulario agregar/editar festivo
    +-- admin.html                   # Configuracion global RRHH/vacaciones

templates/vacaciones/
+-- perfil.html                      # Pagina completa de Mi Perfil
+-- partials/
    +-- balance.html                 # Periodos + barra progreso + alertas
    +-- mis_solicitudes.html         # Tabla solicitudes del usuario
    +-- form_solicitud.html          # Formulario nueva solicitud
    +-- detalle_solicitud.html       # Detalle con acciones (cancelar, PDF)
    +-- form_firma.html              # Carga/dibujo de firma
    +-- equipo.html                  # Vista aprobador/jefe: balances del equipo
    +-- aprobaciones.html            # Solicitudes pendientes de aprobar (personales)

templates/pdf/
+-- solicitud_vacaciones.html        # Plantilla PDF con lineas de firma

-- NOTA: NO existe static/firmas/ -- las firmas se almacenan como BYTEA en tb_usuarios_firmas.firma_data
```

### 2.4 Archivos a modificar

| Archivo | Cambio |
|---|---|
| `main.py` | `import modules.vacaciones.router` + `import modules.rrhh.router` + `app.include_router()` para ambos + agregar `"rrhh"` a `VALID_MODULES` + logica de redireccion default a `/perfil/ui` |
| `templates/base.html` | Convertir avatar en dropdown con "Mi Perfil", ayuda, logout (sidebar desktop + mobile) + agregar modulo RRHH segun permisos de modulo `rrhh` + agregar icono `rrhh` en `module_icon()` |
| `core/security.py` | Propagar `module_roles` y mantener `es_rh` solo como compatibilidad historica; autorizacion RRHH por `tb_permisos_modulos` |
| `core/tasks.py` | Agregar 3 tareas periodicas: `verificar_recordatorios_aprobacion_periodically`, `verificar_periodos_por_expirar_periodically`, `verificar_solicitudes_vencidas_periodically` |
| `worker.py` | Importar y registrar las 3 nuevas tareas en `asyncio.create_task()` |

---

## 3. Base de Datos

### 3.1 Nuevas columnas en `tb_usuarios`

```sql
ALTER TABLE tb_usuarios ADD COLUMN IF NOT EXISTS es_rh BOOLEAN DEFAULT false;
```

### 3.2 `tb_empleados_datos` — Datos laborales (extiende tb_usuarios)

Un empleado puede tener **multiples jefes** (relacion muchos-a-muchos en tabla aparte). El **aprobador de vacaciones es uno solo**.

```sql
CREATE TABLE IF NOT EXISTS tb_empleados_datos (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL,
    numero_empleado VARCHAR(20),
    fecha_contratacion DATE,
    puesto VARCHAR(100),
    departamento VARCHAR(50),
    id_aprobador_vacaciones UUID,
    dias_vacaciones_ajuste INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    updated_by UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_empleados_datos_usuario UNIQUE (usuario_id),
    CONSTRAINT fk_empleados_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_empleados_aprobador FOREIGN KEY (id_aprobador_vacaciones)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    CONSTRAINT fk_empleados_updated_by FOREIGN KEY (updated_by)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL
);
```

### 3.2b `tb_empleados_jefes` — Relacion muchos-a-muchos empleado-jefe

```sql
CREATE TABLE IF NOT EXISTS tb_empleados_jefes (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    empleado_id UUID NOT NULL,
    jefe_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_empleado_jefe UNIQUE (empleado_id, jefe_id),
    CONSTRAINT fk_ej_empleado FOREIGN KEY (empleado_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_ej_jefe FOREIGN KEY (jefe_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_empleados_jefes_jefe ON tb_empleados_jefes(jefe_id);
CREATE INDEX IF NOT EXISTS idx_empleados_jefes_empleado ON tb_empleados_jefes(empleado_id);
```

**Reglas de aprobador:**
- Si `id_aprobador_vacaciones` es NOT NULL -> esa persona aprueba
- Si es NULL -> se usa cualquiera de los jefes en `tb_empleados_jefes`
- Si no tiene jefes -> cualquier admin/RH puede aprobar
- RH puede configurar ambos campos libremente

**Validacion de aprobador:**
```python
es_aprobador_designado = (empleado.id_aprobador_vacaciones == current_user_id)
es_jefe = current_user_id in empleado.jefes_ids  # desde tb_empleados_jefes
es_aprobador = es_aprobador_designado or es_jefe
```

### 3.3 `tb_cat_tipos_solicitud` — Catalogo de tipos de ausencia

```sql
CREATE TABLE IF NOT EXISTS tb_cat_tipos_solicitud (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    nombre VARCHAR(50) NOT NULL,
    slug VARCHAR(30) NOT NULL,
    abreviatura VARCHAR(5) NOT NULL,
    afecta_saldo BOOLEAN DEFAULT true,
    requiere_aprobacion BOOLEAN DEFAULT true,
    is_active BOOLEAN DEFAULT true,
    orden INTEGER DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT uq_tipos_solicitud_slug UNIQUE (slug)
);

-- Seed data
INSERT INTO tb_cat_tipos_solicitud (nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion, orden)
VALUES
    ('Vacaciones',                  'vacaciones',           'VAC', true,  true,  1),
    ('Extraordinaria / Urgencia',   'extraordinaria',       'EXT', true,  true,  2),
    ('Home Office',                 'home_office',          'HO',  false, true,  3),
    ('Incapacidad',                 'incapacidad',          'INC', false, false, 4),
    ('Permiso con goce',            'permiso_con_goce',     'PCG', false, true,  5),
    ('Permiso para llegar tarde',   'permiso_llegar_tarde', 'PLT', false, true,  6),
    ('Permiso para salir temprano', 'permiso_salir_temprano','PST', false, true,  7),
    ('Permiso sin goce',            'permiso_sin_goce',     'PSG', false, true,  8)
ON CONFLICT (slug) DO NOTHING;
```

### 3.4 `tb_solicitudes_ausencia` — Solicitudes

```sql
CREATE TABLE IF NOT EXISTS tb_solicitudes_ausencia (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL,
    tipo_solicitud_id UUID NOT NULL,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    dias_solicitados INTEGER NOT NULL,
    fecha_presentarse DATE NOT NULL,
    observaciones TEXT,
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    aprobado_por UUID,
    motivo_rechazo TEXT,
    fecha_solicitud TIMESTAMPTZ DEFAULT now(),
    fecha_resolucion TIMESTAMPTZ,
    ultima_notificacion_aprobador TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT fk_solicitudes_usuario FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_solicitudes_tipo FOREIGN KEY (tipo_solicitud_id)
        REFERENCES tb_cat_tipos_solicitud(id) ON DELETE RESTRICT,
    CONSTRAINT fk_solicitudes_aprobador FOREIGN KEY (aprobado_por)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    CONSTRAINT ck_solicitudes_estado CHECK (
        estado IN ('pendiente', 'aprobado', 'rechazado', 'cancelado')
    ),
    CONSTRAINT ck_solicitudes_fechas CHECK (fecha_fin >= fecha_inicio)
);

CREATE INDEX IF NOT EXISTS idx_solicitudes_usuario_estado
    ON tb_solicitudes_ausencia(usuario_id, estado);
CREATE INDEX IF NOT EXISTS idx_solicitudes_pendientes
    ON tb_solicitudes_ausencia(estado) WHERE estado = 'pendiente';
CREATE INDEX IF NOT EXISTS idx_solicitudes_fechas
    ON tb_solicitudes_ausencia(fecha_inicio, fecha_fin);
```

### 3.5 `tb_vacaciones_consumo` — Consumo FIFO por periodo

Solo aplica para solicitudes de tipo `vacaciones` o `extraordinaria`.

```sql
CREATE TABLE IF NOT EXISTS tb_vacaciones_consumo (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    solicitud_id UUID NOT NULL,
    num_periodo INTEGER NOT NULL,       -- 1 = 1er aniversario, 2 = 2do, etc.
    dias_consumidos INTEGER NOT NULL,    -- positivo = consume, negativo = adelanto
    fecha_aniversario_periodo DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT fk_consumo_solicitud FOREIGN KEY (solicitud_id)
        REFERENCES tb_solicitudes_ausencia(id) ON DELETE CASCADE,
    CONSTRAINT ck_consumo_num_periodo CHECK (num_periodo > 0)
);

CREATE INDEX IF NOT EXISTS idx_consumo_solicitud
    ON tb_vacaciones_consumo(solicitud_id);
```

### 3.6 `tb_cat_dias_vacaciones` — Dias por antiguedad (LFT + 3)

```sql
CREATE TABLE IF NOT EXISTS tb_cat_dias_vacaciones (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    antiguedad_anios INTEGER NOT NULL,
    antiguedad_anios_fin INTEGER,       -- NULL = "en adelante"
    dias_lft INTEGER NOT NULL,           -- Dias segun LFT
    dias_enertika INTEGER NOT NULL,       -- Dias Enertika (LFT + 3)
    PRIMARY KEY (id),
    CONSTRAINT uq_cat_dias UNIQUE (antiguedad_anios)
);

-- Datos: LFT + 3 para todos los niveles
INSERT INTO tb_cat_dias_vacaciones (antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika)
VALUES
    (1,  1,   12, 15),
    (2,  2,   14, 17),
    (3,  3,   16, 19),
    (4,  4,   18, 21),
    (5,  5,   20, 23),
    (6,  10,  22, 25),
    (11, 15,  24, 27),
    (16, 20,  26, 29),
    (21, 25,  28, 31),
    (26, 30,  30, 33),
    (31, NULL, 32, 35)
ON CONFLICT (antiguedad_anios) DO NOTHING;
```

### 3.7 `tb_cat_festivos` — Dias festivos oficiales

Administrado por RH. Afecta el calculo de dias habiles.

```sql
CREATE TABLE IF NOT EXISTS tb_cat_festivos (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    fecha DATE NOT NULL,
    descripcion VARCHAR(100) NOT NULL,
    es_oficial BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    created_by UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_festivos_fecha UNIQUE (fecha),
    CONSTRAINT fk_festivos_created_by FOREIGN KEY (created_by)
        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL
);

-- Seed data: festivos oficiales Mexico 2026 validar fechas correctas
INSERT INTO tb_cat_festivos (fecha, descripcion, es_oficial)
VALUES
    ('2026-01-01', 'Ano Nuevo', true),
    ('2026-02-02', 'Dia de la Constitucion', true),
    ('2026-03-16', 'Natalicio de Benito Juarez', true),
    ('2026-05-01', 'Dia del Trabajo', true),
    ('2026-09-16', 'Dia de la Independencia', true),
    ('2026-11-16', 'Revolucion Mexicana', true),
    ('2026-12-25', 'Navidad', true)
ON CONFLICT (fecha) DO NOTHING;
```

### 3.8 `tb_solicitudes_firmas` — Registro de firmas por solicitud

```sql
CREATE TABLE IF NOT EXISTS tb_solicitudes_firmas (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    solicitud_id UUID NOT NULL,
    firmante_id UUID NOT NULL,
    rol_firma VARCHAR(20) NOT NULL,      -- 'solicitante' / 'aprobador'
    fecha_firma TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT fk_firmas_solicitud FOREIGN KEY (solicitud_id)
        REFERENCES tb_solicitudes_ausencia(id) ON DELETE CASCADE,
    CONSTRAINT fk_firmas_usuario FOREIGN KEY (firmante_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT ck_firmas_rol CHECK (rol_firma IN ('solicitante', 'aprobador')),
    CONSTRAINT uq_firmas_solicitud_rol UNIQUE (solicitud_id, rol_firma)
);
```

### 3.9 `tb_usuarios_firmas` — Firma precargada del usuario

```sql
CREATE TABLE IF NOT EXISTS tb_usuarios_firmas (
    usuario_id UUID NOT NULL,
    firma_data BYTEA NOT NULL,
    tipo_firma VARCHAR(20) DEFAULT 'subida',  -- 'subida' / 'dibujada'
    fecha_carga TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (usuario_id),
    CONSTRAINT fk_usuarios_firmas FOREIGN KEY (usuario_id)
        REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE
);

-- IMPORTANTE: Las firmas se almacenan como BYTEA en BD, no en filesystem.
-- Railway tiene filesystem efimero — static/ se borra en cada redeploy.
```

---

## 4. Logica de Negocio (`logic.py`)

Funciones puras — sin acceso a DB, solo matematicas y fechas.

### 4.1 `calcular_periodos(fecha_contratacion, hoy, catalogo_dias, ajuste_dias)`

```python
def calcular_periodos(
    fecha_contratacion: date,
    hoy: date,
    catalogo_dias: list[dict],  # [{antiguedad_anios, antiguedad_anios_fin, dias_enertika}]
    ajuste_dias: int = 0
) -> list[dict]:
    """
    Calcula todos los periodos de vacaciones para un empleado.

    Cada aniversario genera un periodo con su propia fecha de expiracion
    (aniversario + relativedelta(months=VACACIONES_MESES_EXPIRACION), default 18 meses).

    Returns:
        [{num_periodo, periodo, fecha_aniversario, fecha_expiracion, dias_otorgados}]
    """
```

**Reglas:**
- Periodo 1 -> fecha_aniversario = fecha_contratacion + 1 ano
- Periodo 2 -> fecha_aniversario = fecha_contratacion + 2 anos
- ...
- Periodo N -> fecha_aniversario = fecha_contratacion + N anos
- fecha_expiracion = fecha_aniversario + relativedelta(months=VACACIONES_MESES_EXPIRACION)
  donde VACACIONES_MESES_EXPIRACION se lee de tb_configuracion_global via ConfigService (default: 18)
- Solo se generan periodos con fecha_aniversario <= hoy + 1 ano (para prever el proximo)
- El ajuste de RH se aplica al periodo mas reciente

**Ejemplo:** Contratacion 2024-01-01, hoy 2026-05-11
```
Periodo 1: aniversario 2025-01-01, expira 2026-07-01, 15 dias
Periodo 2: aniversario 2026-01-01, expira 2027-07-01, 17 dias
Periodo 3 (proximo): aniversario 2027-01-01, expira 2028-07-01, 19 dias
```

### 4.2 `calcular_balance(periodos, consumos)`

```python
def calcular_balance(
    periodos: list[dict],
    consumos: list[dict]  # [{num_periodo, dias_consumidos}]
) -> list[dict]:
    """
    Calcula el saldo de cada periodo considerando los consumos.

    Returns:
        [{num_periodo, periodo, dias_otorgados, dias_usados, dias_restantes,
          fecha_expiracion, dias_para_expiracion, alerta, es_proximo}]

    - dias_restantes puede ser negativo (adelanto en ultimo periodo)
    - alerta = True si dias_para_expiracion <= 30 y dias_restantes > 0
    - es_proximo = True si es el periodo aun no generado (progreso)
    """
```

### 4.3 `asignar_consumo_fifo(periodos_con_saldo, dias_solicitados)`

```python
def asignar_consumo_fifo(
    periodos_con_saldo: list[dict],
    dias_solicitados: int
) -> list[dict]:
    """
    Asigna los dias solicitados a los periodos usando FIFO por expiracion.

    Algoritmo:
    1. Ordenar periodos por fecha_expiracion ASC
    2. Consumir del periodo que expira primero hasta agotarlo
    3. Si aun faltan dias, pasar al siguiente periodo
    4. Si se acaban los periodos con saldo positivo, el resto va al
       periodo mas reciente como saldo negativo (adelanto)

    Returns:
        [{num_periodo, dias_consumir}]  -- lista para insertar en tb_vacaciones_consumo
    """
```

**Ejemplo FIFO:**
```
Periodos: [P1: 9 dias (expira Jul 2026), P2: 17 dias (expira Jul 2027)]
Solicita: 30 dias

-> P1: consume 9 (agotado)
-> P2: consume 17 (agotado)
-> Faltan 4 -> P3 (proximo periodo): -4 (adelanto)
```

### 4.4 `calcular_progreso(fecha_contratacion, hoy, catalogo_dias)`

```python
def calcular_progreso(
    fecha_contratacion: date,
    hoy: date,
    catalogo_dias: list[dict]
) -> dict:
    """
    Calcula el progreso de dias ganados proporcionalmente
    desde el ultimo aniversario.

    Formula: (dias_transcurridos / 365) * dias_siguiente_periodo

    Se actualiza dinamicamente al vuelo: si se aprueban vacaciones se descuentan,
    si se cumple un aniversario aparecen los nuevos dias.

    Returns:
        {
            "dias_transcurridos": int,
            "dias_totales_anio": int,         # 365
            "dias_proximo_periodo": int,       # dias del siguiente periodo
            "dias_proporcionales": float,       # dias ganados proporcionalmente
            "porcentaje": float,               # 0-100
            "fecha_ultimo_aniversario": date,
            "fecha_proximo_aniversario": date,
            "numero_periodo_actual": int       # 1, 2, 3...
        }
    """
```

**Ejemplo:**
```
Contratacion: 2024-01-01
Hoy: 2026-05-11
Ultimo aniversario: 2026-01-01
Proximo aniversario: 2027-01-01
Dias transcurridos: 130
Dias proximo periodo (3er): 19

Progreso: (130/365) * 19 = 6.77 dias -> 35.6%
```

### 4.5 `obtener_dias_por_antiguedad(anios_cumplidos, catalogo_dias)`

```python
def obtener_dias_por_antiguedad(
    anios_cumplidos: int,
    catalogo_dias: list[dict]
) -> int:
    """
    Busca en el catalogo cuantos dias Enertika corresponden segun anos de antiguedad.
    Si anios_cumplidos > maximo con limite finito, usa el registro con fin=NULL.
    """
```

### 4.6 `contar_dias_habiles(inicio, fin, festivos)`

```python
def contar_dias_habiles(
    inicio: date,
    fin: date,
    festivos: set[date]
) -> int:
    """
    Cuenta dias habiles (L-V) en un rango, excluyendo fines de semana
    y dias festivos del catalogo.

    Las vacaciones en Mexico son en dias habiles.

    Returns:
        int: numero de dias habiles en el rango
    """
```

---

## 5. Endpoints

### 5.1 Modulo RRHH (sidebar, usuarios con permiso `rrhh`)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/rrhh/ui` | Dashboard RRHH: personas de vacaciones hoy, aprobaciones pendientes, tabla empleados |
| `GET` | `/rrhh/vacaciones-hoy` | HTMX partial: personas que estan de vacaciones en la fecha actual |
| `GET` | `/rrhh/aprobaciones` | HTMX partial: todas las solicitudes pendientes (global) |
| `GET` | `/rrhh/empleados` | HTMX partial: tabla empleados (N inicial + load-more) |
| `GET` | `/rrhh/empleados/{usuario_id}/editar` | HTMX partial: formulario editar datos empleado |
| `POST` | `/rrhh/empleados/{usuario_id}` | Guardar: fecha_contratacion, jefes, aprobador, ajuste dias, puesto, depto, no. empleado |
| `GET` | `/rrhh/festivos` | HTMX partial: catalogo de festivos |
| `POST` | `/rrhh/festivos` | Agregar festivo |
| `DELETE` | `/rrhh/festivos/{id}` | Eliminar festivo |
| `GET` | `/rrhh/empleados/exportar-excel` | Descargar Excel con todos los empleados: periodo, dias otorgados, dias tomados, dias restantes, fecha expiracion, dias para renovar |
| `GET` | `/rrhh/solicitudes` | HTMX partial: todas las solicitudes (filtrable por estado, tipo, empleado) |
| `POST` | `/rrhh/solicitudes/{id}/aprobar` | RH aprueba cualquier solicitud |
| `POST` | `/rrhh/solicitudes/{id}/rechazar` | RH rechaza cualquier solicitud |
| `GET` | `/rrhh/admin` | Tab Admin: configuracion global de vacaciones/RRHH |
| `POST/PATCH/DELETE` | `/rrhh/admin/festivos` | CRUD avanzado de festivos y generacion anual |
| `POST/PATCH/DELETE` | `/rrhh/admin/tipos-ausencia` | CRUD de tipos de permisos |
| `POST/PATCH/DELETE` | `/rrhh/admin/dias-vacaciones` | CRUD de dias por antiguedad |

### 5.2 Perfil y balance (acceso desde avatar, todos los usuarios)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/perfil/ui` | Pagina completa de Mi Perfil (balance + solicitudes + firma) |
| `GET` | `/perfil/balance` | HTMX partial: periodos, progreso, alertas expiracion |
| `GET` | `/perfil/firma` | HTMX partial: formulario carga/dibujo/actualizacion de firma |
| `POST` | `/perfil/firma/upload` | Subir imagen de firma (PNG) |
| `POST` | `/perfil/firma/draw` | Guardar firma dibujada (base64 desde canvas) |

### 5.3 Solicitudes (usuario)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/perfil/solicitudes` | HTMX partial: tabla de mis solicitudes |
| `GET` | `/perfil/solicitudes/nueva` | HTMX partial: formulario nueva solicitud |
| `POST` | `/perfil/solicitudes` | Crear solicitud (si no tiene firma -> redirigir a /perfil/firma) |
| `GET` | `/perfil/solicitudes/{id}` | HTMX partial: detalle de solicitud |
| `POST` | `/perfil/solicitudes/{id}/cancelar` | Cancelar solicitud propia (solo pendiente) |
| `GET` | `/perfil/solicitudes/{id}/pdf` | Descargar PDF de la solicitud |

### 5.4 Aprobacion (aprobador/jefe)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/perfil/aprobaciones` | HTMX partial: solicitudes pendientes que este usuario debe aprobar |
| `POST` | `/perfil/solicitudes/{id}/aprobar` | Aprobar + firmar + generar PDF final + notificar a solicitante y RH |
| `POST` | `/perfil/solicitudes/{id}/rechazar` | Rechazar con motivo + notificar a solicitante y RH |

### 5.5 Vista Equipo (jefes y aprobadores)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/perfil/equipo` | HTMX partial: balances de las personas que este usuario gerencia (como jefe o aprobador) |
| `GET` | `/perfil/equipo/{usuario_id}` | HTMX partial: detalle de balance de una persona del equipo |

**Quien puede ver Equipo:**
- Usuarios que son jefes de alguien (`tb_empleados_jefes.jefe_id = current_user.id`)
- Usuarios que son aprobadores de alguien (`tb_empleados_datos.id_aprobador_vacaciones = current_user.id`)
- RH y ADMIN

---

## 6. Flujos de Usuario

### 6.1 Solicitar vacaciones

```
1. Usuario click en avatar -> "Mi Perfil"
2. Ve su dashboard: barra de progreso + periodos + mis solicitudes
3. Click en [+ Nueva Solicitud]
4. Selecciona tipo: "Vacaciones"
5. Ingresa:
   - Periodo: [15/06/2026] a [20/06/2026]  <- date range picker
   - El sistema calcula automaticamente los dias habiles en ese rango
   - Fecha presentarse (regreso): [21/06/2026]
   - Observaciones: [opcional]
6. Click en [Enviar solicitud]
7. Validaciones:
   - ¿Tiene suficientes dias habiles disponibles? (incluyendo adelanto)
   - Si pide mas de lo disponible -> confirmacion de saldo negativo
   - ¿Hay solapamiento con otras solicitudes activas?
   - ¿Tiene firma guardada?
8. Si pasa validaciones:
   - Se crea registro en tb_solicitudes_ausencia (estado: pendiente)
   - Se calcula consumo FIFO -> registros en tb_vacaciones_consumo
   - Si tiene firma: se registra en tb_solicitudes_firmas y se incrusta en PDF
   - Si NO tiene firma: redirigir a /perfil/firma, al guardar continua el envio
   - Se notifica al aprobador por email (con boton CTA) + notificacion in-app
   - Se inicia recordatorio cada 24h si no hay accion
   - Se muestra confirmacion + balance actualizado (HTMX refresh)
```

### 6.2 Aprobar solicitud (flujo del aprobador)

```
1. Aprobador recibe email con boton CTA: "Revisar solicitud" -> link directo a la solicitud
   + notificacion in-app en campanita
   + Si no actua en 24h -> recibe recordatorio por email

2. Entra a "Mi Perfil" -> pestana "Aprobaciones" (visible si es jefe/aprobador/RH/admin)
   O desde modulo RRHH si es RH

3. Ve lista de solicitudes pendientes

4. Click en una solicitud -> ve detalle:
   - Datos del empleado
   - Tipo, fechas, dias habiles, fecha de regreso
   - Balance actual del empleado (periodos afectados)
   - Observaciones

5. Opciones:
   - [Aprobar y firmar] ->
       a. Se registra firma del aprobador en tb_solicitudes_firmas
       b. Estado cambia a 'aprobado'
       c. Se genera PDF final con ambas firmas embebidas
       d. Se envia email al solicitante + CC a RH con PDF adjunto
       e. Notificacion in-app al solicitante
   - [Rechazar] ->
       a. Modal para ingresar motivo
       b. Estado cambia a 'rechazado', se guarda motivo_rechazo
       c. Se liberan los dias consumidos (delete de tb_vacaciones_consumo)
       d. Email al solicitante + CC a RH con motivo
       e. Notificacion in-app al solicitante
```

### 6.3 Gestion RH (modulo RRHH en sidebar)

```
1. Usuario con modulo `rrhh` asignado ve el modulo "RRHH" en el sidebar
2. Dashboard con 3 secciones:

   SECCION 1 - Hoy:
   +--------------------------------------------------------+
   | Personas de vacaciones hoy: 2                          |
   | Juan Perez      15-20 Jun (5 dias)   Regresa: 21 Jun   |
   | Ana Garcia      10-25 Jun (11 dias)  Regresa: 26 Jun   |
   +--------------------------------------------------------+

   SECCION 2 - Pendientes:
   +--------------------------------------------------------+
   | Aprobaciones pendientes: 3                             |
   | Carlos Ruiz     Vacaciones  5 dias  [Aprobar] [Rech.]  |
   | Maria Lopez     Permiso     1 dia   [Aprobar] [Rech.]  |
   +--------------------------------------------------------+

   SECCION 3 - Empleados (load-more, sin paginacion, incluir periodos de cada empleado):
   +--------------------------------------------------------+
   | Empleados (32)                            [Ver todos]  |
   | Nombre  | Depto | Fecha Cont | Jefes | Aprob. | Dias  |
   | ...     | ...   | ...        | ...   | ...    | ...   |
   | [Mostrar mas v]  <- carga siguientes N registros       |
   +--------------------------------------------------------+

   Pestanas adicionales:
   - [Festivos]: Catalogo de dias festivos (CRUD)
   - [Solicitudes]: Todas las solicitudes con filtros
   - [Admin]: Configuracion global, visible/editable solo con acceso elevado

3. Click en un empleado -> [Editar]:
   - Modificar fecha_contratacion
   - Gestionar jefes (agregar/quitar de tb_empleados_jefes)
   - Seleccionar aprobador_vacaciones (un solo usuario)
   - Ajuste manual de dias (+/-)
   - No. empleado, puesto, departamento
4. Guardar -> actualiza tb_empleados_datos y tb_empleados_jefes
5. Acceso a tab Admin:
   - `MANAGER + rrhh editor`
   - `USER/MANAGER + rrhh admin`
   - `ADMIN` global
```

### 6.4 Cancelacion de solicitud (flujo del usuario)

```
1. Usuario cancela solicitud propia (solo si estado = 'pendiente')
2. Backend:
   a. Estado cambia a 'cancelado'
   b. Se liberan los dias consumidos: DELETE FROM tb_vacaciones_consumo WHERE solicitud_id = id
   c. El saldo del periodo afectado se restaura automaticamente (periodos calculados al vuelo)
```

**Validacion de fechas vencidas (worker diario):**
Si una solicitud sigue `pendiente` y `fecha_inicio <= hoy`:
- Notifica a RH + aprobador: "La solicitud de [empleado] para [fecha_inicio - fecha_fin] sigue pendiente
  y las fechas ya estan en curso o han pasado. Por favor aprueba o cancela y verifica si el empleado
  tomo esos dias."
- Implementado en `verificar_solicitudes_vencidas_periodically()` en `worker.py` (ejecucion diaria)

---

## 7. UI / UX

### 7.1 Layout de "Mi Perfil" (RH debe poder ver y descargar excel con resuemn de los periodos de cada empleado, dias rrstantes, renovaciones.)

```
+-------------------------------------------------------------+
|  [sidebar] |  Mi Perfil                                     |
|            |                                                 |
|            |  [Mis Vacaciones] [Solicitudes] [Aprobaciones]  |
|            |  [Equipo] [Mi Firma]                           |
|            |  ------------------------------------------   |
|            |                                                 |
|            |  Progreso periodo 3 (2027)                      |
|            |  [========____] 35.6%                   |
|            |  6.8 de 19 dias ganados proporcionalmente       |
|            |  130 dias transcurridos desde tu ultimo         |
|            |  aniversario (01/01/2026)                       |
|            |                                                 |
|            |  Mis Periodos                                   |
|            |  +------+------+-------+--------+------------+ |
|            |  | Per  | Dias | Usado | Restan | Expira     | |
|            |  +------+------+-------+--------+------------+ |
|            |  | 1    | 15   | 6     | 9      | Jul 2026 ! | |
|            |  | 2    | 17   | 0     | 17     | Jul 2027   | |
|            |  | Av.3 | 6.8  | 0     | 6.8    | --         | |
|            |  +------+------+-------+--------+------------+ |
|            |                                                 |
|            |  [+ Nueva solicitud]                            |
|            |                                                 |
|            |  Mis Solicitudes                                |
|            |  +-----------+------+-----------+------------+ |
|            |  | Periodo   | Dias | Estado    | Accion     | |
|            |  +-----------+------+-----------+------------+ |
|            |  | 15-20 Jun | 5    | Pendiente | Cancelar   | |
|            |  | 01-05 Ene | 4    | Aprobado  | Ver PDF    | |
|            |  +-----------+------+-----------+------------+ |
+-------------------------------------------------------------+
```

**La barra de progreso se actualiza dinamicamente:**
- Al cargar la pagina: calculo al vuelo con `today_mx()`
- Al aprobarse vacaciones: se descuentan dias del periodo correspondiente, HTMX refresca
- Al cumplirse aniversario: el nuevo periodo aparece automaticamente en el calculo

### 7.2 Pestanas segun rol

| Pestana | Visible para | Contenido |
|---|---|---|
| Mis Vacaciones | Todos | Balance + progreso |
| Solicitudes | Todos | Lista de solicitudes propias |
| Aprobaciones | Aprobadores, jefes, RH, Admin | Solicitudes pendientes que debe aprobar |
| Equipo | Jefes, aprobadores, RH, Admin | Balances del equipo a cargo |
| Mi Firma | Todos | Carga/dibujo/actualizacion de firma |

**Nota sobre "Equipo":** Un usuario ve esta pestana si:
- Es jefe de alguien (existe en `tb_empleados_jefes.jefe_id`)
- Es aprobador designado de alguien (`tb_empleados_datos.id_aprobador_vacaciones`)
- Es RH o ADMIN

### 7.3 Barra de progreso (detalle, RH tambien cuenta como empleado asi que tambien debe poder ver su barra)

```html
<!-- Progreso dinamico con colores segun % -->
<div class="progress-container">
  <div class="progress-bar" style="width: 35.6%">
    <span>6.8 / 19 dias (35.6%)</span>
  </div>
</div>
<div class="progress-detail">
  Dias transcurridos desde tu ultimo aniversario (01/01/2026): 130 de 365
</div>
```

### 7.4 Indicador de alerta por expiracion

Se usa "Periodos" en la UI, no "Lotes".

```
!  Periodo 1: 9 dias restantes — expiran en 51 dias (01/07/2026)
   Usalos antes de que expiren!
```

Se muestra en amarillo/rojo segun urgencia:
- < 90 dias: amarillo
- < 30 dias: rojo

### 7.5 Formulario de solicitud

```
+----------------------------------------------+
|  Nueva Solicitud                             |
|                                               |
|  Tipo de solicitud *                         |
|  +--------------------------------------+    |
|  | Vacaciones                       v  |    |
|  +--------------------------------------+    |
|                                               |
|  Periodo de vacaciones *                      |
|  +--------------+  a  +--------------+        |
|  | 15/06/2026   |     | 20/06/2026   |        |
|  +--------------+     +--------------+        |
|  Dias habiles en el rango: 5                  |
|  (L-V, excluyendo festivos)                   |
|                                               |
|  Fecha en que debera presentarse *            |
|  +--------------+                             |
|  | 21/06/2026   |                             |
|  +--------------+                             |
|                                               |
|  Observaciones                                |
|  +--------------------------------------+    |
|  |                                      |    |
|  +--------------------------------------+    |
|                                               |
|  [Cancelar]           [Enviar solicitud]     |
+----------------------------------------------+
```

**¿Por que dias habiles?** Todos los tipos de solicitud se cuentan en dias habiles (L-V). Se excluyen fines de semana y festivos del catalogo `tb_cat_festivos`.

**Flujo de firma al enviar:**
- Si el usuario **ya tiene firma guardada**: se coloca automaticamente en el PDF
- Si **no tiene firma**: se redirige a "Mi Firma" para crearla; al guardar, continua el envio automaticamente

### 7.6 Widget de firma

```
+----------------------------------------------+
|  Mi Firma                                    |
|                                               |
|  (Si ya tiene firma guardada:)               |
|  +-- Vista previa --------------------------+|
|  |  [imagen de la firma actual]             ||
|  |  Guardada el 15/03/2026 (subida)         ||
|  +------------------------------------------+|
|  [Actualizar firma]                          |
|                                               |
|  (Al actualizar o crear por primera vez:)    |
|  +- Subir imagen ---+  +- Dibujar ----------+|
|  | [Seleccionar PNG] |  |                   ||
|  |                    |  |  +-------------+ ||
|  | Vista previa:      |  |  |             | ||
|  | +--------------+   |  |  |  (canvas)   | ||
|  | |   Firma.png  |   |  |  |             | ||
|  | +--------------+   |  |  +-------------+ ||
|  |                    |  |  [Limpiar]       ||
|  +--------------------+  +------------------+|
|                                               |
|  [Guardar firma]                              |
+----------------------------------------------+
```

Libreria recomendada: `signature_pad` (4KB, sin dependencias) para el canvas de dibujo.

---

## 8. PDF de Solicitud

### 8.1 Plantilla (`templates/pdf/solicitud_vacaciones.html`)

Usa el `_base.html` existente de PDFs. Contenido:

```
+------------------------------------------------------+
|  ENERTIKA                                            |
|  SOLICITUD DE VACACIONES / AUSENCIA                  |
|                                                       |
|  No. Solicitud: FO-ADM-002-VAC1105261423             |
|  Fecha de solicitud: 11/05/2026                      |
|                                                       |
|  DATOS DEL EMPLEADO                                  |
|  +------------------------------------------------+  |
|  | Nombre: Juan Perez Lopez                       |  |
|  | No. Empleado: EMP-0012                         |  |
|  | Departamento: Ingenieria                       |  |
|  | Puesto: Ingeniero de Proyectos                 |  |
|  | Fecha de Contratacion: 01/01/2024              |  |
|  +------------------------------------------------+  |
|                                                       |
|  DATOS DE LA SOLICITUD                               |
|  +------------------------------------------------+  |
|  | Tipo: Vacaciones                               |  |
|  | Periodo: 15/06/2026 al 20/06/2026              |  |
|  | Dias habiles solicitados: 5                    |  |
|  | Fecha de regreso: 21/06/2026                   |  |
|  | Observaciones: (texto)                         |  |
|  +------------------------------------------------+  |
|                                                       |
|  DETALLE DE PERIODOS AFECTADOS                       |
|  +------------------------------------------------+  |
|  | Periodo 1 (2025): 5 dias consumidos            |  |
|  | Saldo restante P1: 4 dias | P2: 17 dias        |  |
|  +------------------------------------------------+  |
|                                                       |
|  FIRMAS                                               |
|  +---------------------+ +-------------------------+ |
|  |                     | |                         | |
|  |   [firma_img.png]   | |   [firma_img.png]       | |
|  |                     | |                         | |
|  | ___________________ | | _____________________   | |
|  | Solicitante         | | Aprobador               | |
|  | Juan Perez Lopez    | | Maria Garcia Ruiz       | |
|  | Fecha: 11/05/2026   | | Fecha: 12/05/2026       | |
|  +---------------------+ +-------------------------+ |
|                                                       |
|  Este documento es un comprobante. Las firmas         |
|  digitales registradas en el sistema constituyen la   |
|  autorizacion oficial de esta solicitud.              |
|  CC: RH Enertika                                     |
+------------------------------------------------------+
```

### 8.2 Logica de generacion del PDF

```python
async def generar_pdf_solicitud(conn, solicitud_id, pdf_service):
    """
    Genera PDF al vuelo con WeasyPrint (no se almacena en ningun storage).

    - Al crear solicitud: PDF con solo firma del solicitante
    - Al aprobar: PDF con ambas firmas

    Las firmas se recuperan de tb_usuarios_firmas.firma_data (BYTEA) y se
    incrustan como data:image/png;base64,... en el HTML antes de WeasyPrint.
    Si un usuario no tiene firma cargada, se muestra solo la linea con nombre y fecha.

    Folio: FO-ADM-002-{abreviatura}{fecha_solicitud:ddmmaaHHMM}
    Ejemplo: FO-ADM-002-VAC1105261423
    """
```

El PDF final se envia por email al solicitante y a RH como adjunto.

---

## 9. Notificaciones

### 9.1 Eventos y destinatarios

| Evento | Disparador | Destinatario | CC | Medio | Recordatorio |
|---|---|---|---|---|---|
| `SOLICITUD_VACACIONES` | Usuario crea solicitud | Aprobador asignado | — | Email con boton CTA + in-app | Cada 24h si no actua |
| `VACACIONES_APROBADAS` | Aprobador firma | Solicitante | RH | Email con PDF adjunto + in-app | — |
| `VACACIONES_RECHAZADAS` | Aprobador rechaza | Solicitante | RH | Email con motivo + in-app | — |
| `PERIODO_POR_EXPIRAR` | Worker (diario) | Empleado | RH | Email + in-app | — |
| `SOLICITUD_VENCIDA` | Worker (diario) | Aprobador | RH | Email — solicitud pendiente con fechas ya en curso o pasadas | — |

### 9.2 Boton CTA en emails

Los emails de notificacion incluyen un boton Call-To-Action igual que las notificaciones actuales del sistema:

```html
<a href="{{ base_url }}/perfil/solicitudes/{{ solicitud_id }}"
   style="display:inline-block;padding:12px 24px;background:#00BABB;color:#fff;
          border-radius:8px;text-decoration:none;font-weight:600;">
    Revisar solicitud
</a>
```

### 9.3 Integracion con NotificationService

Se agregan nuevos metodos a `core/workflow/notification_service.py`:

```python
async def notify_vacation_request(conn, solicitud_id, aprobador_email, ...)
async def notify_vacation_approved(conn, solicitud_id, solicitante_email, ...)
async def notify_vacation_rejected(conn, solicitud_id, solicitante_email, motivo, ...)
async def notify_periodo_expira(conn, usuario_id, periodo_info, ...)
```

### 9.4 Worker — Recordatorios y expiraciones

Se agregan tareas periodicas en `core/tasks.py` (importadas y registradas en `worker.py`):

```python
async def verificar_recordatorios_aprobacion():
    """
    Ejecucion cada hora.
    Revisa solicitudes pendientes con mas de 24h sin accion
    y envia recordatorio al aprobador.
    """

async def verificar_periodos_por_expirar():
    """
    Ejecucion diaria.
    Revisa todos los empleados con periodos a punto de expirar
    (30, 15, 7, 1 dias) y envia notificaciones a empleado + CC a RH.
    """

async def verificar_solicitudes_vencidas_periodically():
    """
    Ejecucion diaria.
    Detecta solicitudes con estado='pendiente' y fecha_inicio <= hoy.
    Notifica a RH y al aprobador para que aprueben o cancelen, y
    verifiquen si el empleado tomo los dias sin autorizacion formal.
    """
```

---

## 10. Permisos y Seguridad

### 10.1 Roles de modulos (en tb_cat_modulos)

| slug | nombre | ruta | icono | sidebar |
|---|---|---|---|---|
| `rrhh` | RRHH | `/rrhh/ui` | `bi-people-fill` | Si, usuarios con permiso `rrhh` |

El modulo `perfil`/`vacaciones` **NO** se registra en `tb_cat_modulos`. El acceso al perfil lo tiene cualquier usuario autenticado (solo requiere sesion activa, no RBAC de modulo). Solo el modulo `rrhh` requiere entrada en el catalogo y control de permisos.

### 10.2 Control de acceso

Matriz final RRHH:

| Usuario | Permiso modulo `rrhh` | Alcance |
|---|---|---|
| `USER` | `viewer` | Ver RRHH y descargar informacion; sin modificar. |
| `USER` | `editor` | Editar operacion diaria de RH. |
| `MANAGER` | `editor` | Editar operacion diaria y configuracion global. |
| `USER`/`MANAGER` | `admin` | Acceso total al modulo. |
| `ADMIN` global | cualquiera | Acceso total. |

```python
# Ver perfil propio -> cualquier usuario autenticado
# No requiere permisos de modulo especificos

# Acceder a modulo RRHH -> viewer o superior
require_module_access("rrhh", "viewer")

# Descargar informacion RRHH -> viewer o superior
require_module_access("rrhh", "viewer")

# Operacion diaria RRHH -> editor o superior
require_module_access("rrhh", "editor")

# Configuracion global RRHH/Admin -> acceso elevado
require_manager_access("rrhh", "editor")

# Crear solicitud -> cualquier usuario autenticado
# Validacion extra: debe tener fecha_contratacion en tb_empleados_datos

# Aprobar solicitud -> solo el aprobador designado, o jefes, o RH, o admin
async def puede_aprobar(conn, solicitud_id, current_user_id, user_context):
    solicitud = await get_solicitud(conn, solicitud_id)
    empleado = await get_empleado_datos(conn, solicitud.usuario_id)
    jefes_ids = await get_jefes_ids(conn, solicitud.usuario_id)

    es_admin = user_context["role"] == "ADMIN"
    es_rh_editor = user_has_module_access("rrhh", user_context, "editor")
    es_aprobador_designado = empleado.id_aprobador_vacaciones == current_user_id
    es_jefe = current_user_id in jefes_ids

    return es_admin or es_rh_editor or es_aprobador_designado or es_jefe

# Gestionar empleados (RH) -> editor o superior
async def puede_gestionar_rh(user_context):
    return user_has_module_access("rrhh", user_context, "editor")

# Cancelar solicitud -> solo el dueno y solo si esta pendiente
async def puede_cancelar(solicitud, current_user_id):
    return solicitud.usuario_id == current_user_id and solicitud.estado == 'pendiente'
```

---

## 11. Plan de Migraciones

### 11.1 Migracion 066 — Tablas base

```sql
-- 066_vacaciones_rrhh_base.sql

-- 1. Nueva columna en tb_usuarios
ALTER TABLE tb_usuarios ADD COLUMN IF NOT EXISTS es_rh BOOLEAN DEFAULT false;

-- 2. Catalogos (sin dependencias)
-- tb_cat_dias_vacaciones (LFT + 3, 11 niveles)
-- tb_cat_tipos_solicitud (8 tipos)
-- tb_cat_festivos (seed con festivos oficiales Mexico)

-- 3. Tablas principales
-- tb_empleados_datos (FK -> tb_usuarios)
-- tb_empleados_jefes (muchos-a-muchos empleado-jefe)
-- tb_usuarios_firmas (FK -> tb_usuarios)

-- 4. Tablas transaccionales
-- tb_solicitudes_ausencia (FK -> tb_usuarios, tb_cat_tipos_solicitud)
-- tb_vacaciones_consumo (FK -> tb_solicitudes_ausencia)
-- tb_solicitudes_firmas (FK -> tb_solicitudes_ausencia, tb_usuarios)
```

### 11.2 Indices

```sql
CREATE INDEX IF NOT EXISTS idx_empleados_aprobador ON tb_empleados_datos(id_aprobador_vacaciones);
CREATE INDEX IF NOT EXISTS idx_empleados_jefes_jefe ON tb_empleados_jefes(jefe_id);
CREATE INDEX IF NOT EXISTS idx_empleados_jefes_empleado ON tb_empleados_jefes(empleado_id);
CREATE INDEX IF NOT EXISTS idx_solicitudes_usuario ON tb_solicitudes_ausencia(usuario_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_solicitudes_estado ON tb_solicitudes_ausencia(estado, created_at);
CREATE INDEX IF NOT EXISTS idx_solicitudes_aprobador ON tb_solicitudes_ausencia(aprobado_por);
CREATE INDEX IF NOT EXISTS idx_solicitudes_fechas ON tb_solicitudes_ausencia(fecha_inicio, fecha_fin);
```

### 11.3 Migracion 067 — Modulo RRHH en catalogo

```sql
-- 067_rrhh_modulo.sql

INSERT INTO tb_cat_modulos (nombre, slug, ruta, icono, descripcion, is_active, orden)
VALUES ('RRHH', 'rrhh', '/rrhh/ui', 'bi-people-fill', 'Gestion de recursos humanos, vacaciones y perfil de empleados', true, 12)
ON CONFLICT (slug) DO NOTHING;
```

### 11.4 Migracion 068 — Admin RRHH y configuracion de vacaciones

```sql
-- 068_rrhh_admin_vacaciones_config.sql
-- Extiende catalogos y configuracion para Admin RRHH.
-- Base para CRUD de festivos, tipos de permisos y dias por antiguedad.
-- Agrega campos de auditoria/configuracion necesarios para operacion sin nuevas migraciones.
```

### 11.5 Migracion 069 — Worker y notificaciones de vacaciones

```sql
-- 069_vacaciones_worker_notificaciones.sql
-- Soporta tareas periodicas, control anti-duplicados y notificaciones.
-- Cubre recordatorios de aprobacion, periodos por expirar y solicitudes vencidas.
```

---

## 12. Plan de Implementacion (orden sugerido)

| Fase | Entregable | Depende de |
|---|---|---|
| **Fase 1** | Migracion 066 (tablas base) | — |
| **Fase 2** | `logic.py` (logica pura: periodos, FIFO, progreso, dias habiles) | — |
| **Fase 3** | `db_service.py` + `schemas.py` para vacaciones | Fase 1 |
| **Fase 4** | `service.py` (orquestacion) | Fase 2, 3 |
| **Fase 5** | `router.py` para `/perfil/*` (balance, solicitudes CRUD) | Fase 4 |
| **Fase 6** | Templates perfil: `perfil.html`, `balance.html`, `form_solicitud.html`, `mis_solicitudes.html` | Fase 5 |
| **Fase 7** | Modificaciones `base.html` (dropdown perfil + home default) + `main.py` (registro routers) + `security.py` (permisos de modulo y compatibilidad `es_rh`) | Fase 6 |
| **Fase 8** | Flujo de aprobacion + templates aprobacion + equipo | Fase 4 |
| **Fase 9** | Firmas: carga/dibujo/actualizacion + widget canvas | Fase 4 |
| **Fase 10** | PDF: plantilla + generacion con firmas embebidas | Fase 5, 9 |
| **Fase 11** | Notificaciones: email con CTA + in-app + recordatorios 24h | Fase 5 |
| **Fase 12** | Worker: recordatorios + alertas de periodos por expirar | Fase 4 |
| **Fase 13** | Modulo RRHH: router, templates, dashboard | Fase 4 |
| **Fase 14** | Migracion 067 (modulo en catalogo) | Fase 13 |
| **Fase 15** | Tab Admin RRHH + CRUD catalogos + generacion anual de feriados | Fase 13, 14 |
| **Fase 16** | Migraciones 068 y 069 | Fase 15 |
| **Fase 17** | Pruebas integrales + ajustes | Fase 1-16 |

---

## 13. Notas Tecnicas

### 13.1 Timezone
- Todas las fechas se almacenan como `DATE` (sin hora) o `TIMESTAMPTZ`
- Para calculos de dias transcurridos usar `today_mx()` de `core/timezone.py`
- **Prohibido** `date.today()` y `datetime.now()` sin timezone

### 13.2 Dias habiles (confirmado)
- **Todos los tipos de solicitud** se cuentan en dias habiles (L-V) — sin distincion por tipo
- Se excluyen fines de semana + festivos del catalogo `tb_cat_festivos`
- RH administra el catalogo de festivos desde el modulo RRHH; la configuracion global queda en tab Admin con acceso elevado
- Funcion `contar_dias_habiles(inicio, fin, festivos)` en `logic.py`

### 13.3 Solapamiento de fechas
- Validar que no exista otra solicitud activa (pendiente o aprobada) para el mismo usuario en el mismo rango de fechas

### 13.4 Consistencia de periodos
- Los periodos se calculan al vuelo (no se persisten)
- Solo se persiste el CONSUMO (tb_vacaciones_consumo)
- Si RH cambia `fecha_contratacion`, el balance se recalcula automaticamente
- La barra de progreso se actualiza dinamicamente al aprobar/denegar solicitudes o al cumplir aniversario

### 13.5 Ajuste manual de dias (RH)
- `tb_empleados_datos.dias_vacaciones_ajuste` permite a RH sumar/restar dias manualmente
- El ajuste se aplica al periodo mas reciente al calcular el balance
- Util para casos especiales (ej. empleado que ya tomo vacaciones antes de entrar al sistema)

### 13.6 Multiples jefes
- Relacion muchos-a-muchos en `tb_empleados_jefes`
- La pestana "Equipo" muestra todas las personas donde el usuario actual es jefe O aprobador designado
- RH puede gestionar jefes desde el modulo RRHH

### 13.7 Tabla de empleados sin paginacion
- Carga inicial de N registros (ej. 20)
- Boton "Mostrar mas" que carga los siguientes N via HTMX
- Boton "Ver todos" que carga el listado completo
- Sin controles de paginacion numerica tradicional

### 13.8 Firmas digitales — almacenamiento BYTEA

- Las firmas se guardan como `BYTEA` en `tb_usuarios_firmas.firma_data`
- **Prohibido** guardar en filesystem (`static/firmas/`) — Railway tiene filesystem efimero y se borra en cada redeploy
- Al generar PDF: recuperar BYTEA, convertir a base64, embeber como `data:image/png;base64,...` en el HTML
- Al recibir firma dibujada (canvas): el cliente envia base64 → decodificar a bytes antes de insertar
- Al recibir firma subida (PNG upload): leer bytes del `UploadFile` directamente

### 13.9 Folio de solicitud

- Formato: `FO-ADM-002-{abreviatura}{fecha_solicitud:ddmmaaHHMM}`
- Ejemplo: `FO-ADM-002-VAC1105261423`
- Calculado al vuelo en el PDF a partir de `tb_cat_tipos_solicitud.abreviatura` + `tb_solicitudes_ausencia.fecha_solicitud`
- No requiere campo adicional en la tabla ni sequence

### 13.10 Expiracion de periodos — configurable

- Se usa `relativedelta(months=N)` de `python-dateutil` para calcular `fecha_expiracion`
- El valor N se lee de `tb_configuracion_global` con clave `VACACIONES_MESES_EXPIRACION` (default: 18)
- Para cambiar la politica de expiracion: actualizar el valor en admin sin tocar codigo

### 13.11 Session context y permisos RRHH

- La fuente principal de acceso a RRHH es `tb_permisos_modulos` con slug `rrhh`.
- `es_rh` puede existir por compatibilidad historica, pero no debe ser la regla principal de autorizacion.
- `core/security.py` debe propagar `module_roles` y los routers deben usar `require_module_access("rrhh", ...)` o `require_manager_access("rrhh", "editor")` segun el caso.

---

## 14. Preguntas y Respuestas

| Pregunta | Estado | Respuesta |
|---|---|---|
| Los dias de vacaciones son habiles o naturales? | ✅ Confirmado | Habiles (L-V, excluyendo festivos) |
| Se requiere catalogo de dias festivos oficiales? | ✅ Confirmado | Si, RH lo administra |
| El "periodo" en UI se refiere a ano de aniversario? | ✅ Confirmado | Si, ano laboral por aniversario |
| Dias Enertika: LFT+2 o LFT+3? | ✅ Confirmado | LFT + 3, tabla completa con 11 niveles (1-30+ anos) |
| El aprobador puede ver la seccion Equipo? | ✅ Confirmado | Si, tanto jefes como aprobadores designados |
| Copia a RH en notificaciones? | ✅ Confirmado | Si, en aprobado, rechazado y expiracion |
| Incapacidad requiere subir comprobante medico? | Fase 2 | Dejar para fase 2 |
| Los permisos requieren aprobacion del mismo jefe? | ✅ Si | Igual que vacaciones: aprobador designado o jefe |
| Multiple aprobadores? | ✅ Aclarado | Un solo aprobador por empleado; puede tener multiples jefes |
| Almacenamiento de firmas? | ✅ Confirmado | BYTEA en BD (`tb_usuarios_firmas.firma_data`) — filesystem Railway es efimero |
| PDF almacenado o al vuelo? | ✅ Confirmado | Al vuelo con WeasyPrint; firma desde base64 en BD |
| Formato folio solicitud? | ✅ Confirmado | `FO-ADM-002-{ABREV}{ddmmaaHHMM}` — calculado al vuelo |
| Distincion dias habiles/naturales por tipo? | ✅ Eliminada | Siempre dias habiles (L-V) para todos los tipos |
| Expiracion 18 meses configurable? | ✅ Confirmado | `VACACIONES_MESES_EXPIRACION` en `tb_configuracion_global` via ConfigService |
| Cancelacion libera saldo? | ✅ Confirmado | Si, DELETE en `tb_vacaciones_consumo` igual que rechazo |
| Solicitudes vencidas sin resolver? | ✅ Confirmado | Worker diario notifica a RH + aprobador si `pendiente` y `fecha_inicio <= hoy` |
| Excel export para RH? | ✅ Confirmado | Implementado en `GET /rrhh/empleados/exportar-excel`; disponible para `rrhh viewer` o superior |
| Feriados se actualizan cada ano? | ✅ Confirmado | Si, por generacion anual desde worker y accion manual en `RRHH > Admin` |
| RH puede corregir feriados manualmente? | ✅ Confirmado | Si, CRUD de festivos en RRHH/Admin |
| RH puede actualizar tipos de permisos? | ✅ Confirmado | Si, CRUD en `RRHH > Admin` sobre `tb_cat_tipos_ausencia` |
| RH puede actualizar dias por antiguedad? | ✅ Confirmado | Si, CRUD en `RRHH > Admin` sobre `tb_cat_dias_vacaciones` |
| Quien puede editar Admin RRHH? | ✅ Confirmado | `MANAGER + rrhh editor`, modulo `rrhh admin` o `ADMIN` global |
| Que puede hacer `rrhh viewer`? | ✅ Confirmado | Ver informacion y descargar Excel, sin modificar |
| `es_rh` en session context? | Actualizado | Permanece solo como compatibilidad; la autorizacion principal usa `tb_permisos_modulos` |

---

> **Proximo paso:** Completar QA funcional, pruebas automatizadas y validacion visual/browser del flujo implementado.
