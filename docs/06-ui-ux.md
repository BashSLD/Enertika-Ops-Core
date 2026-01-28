# 6. Estándares UI/UX y Diseño

## Iconografía (NO EMOJIS)

### PROHIBIDO: Emojis en UI

**No usar emojis** (❌, ✅, ⚠️, 🗑️) como iconos principales de interfaz.
- ❌ Se ven diferentes en cada SO (Windows/Mac/Android).
- ❌ Parecen informales o poco profesionales.
- ❌ Difícil control de color y tamaño.

**⚠️ CRÍTICO - Backend Python**: Emojis **TOTALMENTE PROHIBIDOS** en archivos `.py`:
- ❌ router.py, service.py, handlers, schemas
- ❌ Logging (`logger.info()`, `logger.debug()`)  
- ❌ Mensajes de error o respuestas
- ❌ Comentarios de código (usar texto descriptivo como "OK -", "CACHE -")

**CRITERIO: ¿Emoji o SVG?**

| Ubicación | Permitido | Razón |
|-----------|-----------|-------|
| **base.html sidebar** | ✅ Emojis | Novedad visual, UX general, decisión de diseño |
| **Templates de módulos** | ⚠️ Iconos SVG | Profesionalismo, funcionalidad crítica |
| **Backend Python (.py)** | ❌ NUNCA | Código limpio, debugging |

**Ejemplo correcto**:
```html
<!-- base.html - OK: Navegación general -->
{"slug": "comercial", "icon": "💼"}

<!-- comercial/cards.html - OK: Icono SVG -->
<svg class="w-4 h-4"><path d="M9 12l2 2..."/></svg> Entregado
```

### OBLIGATORIO: Iconos SVG (Heroicons)

Usar **Heroicons Outline** (SVG integrado) con clases Tailwind.

**Ejemplo correcto:**
```html
<!-- BIEN - SVG Controlable -->
<svg class="w-5 h-5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
</svg>
```

**Beneficios:**
- Consistencia visual perfecta.
- Heredan color del texto (`currentColor`).
- Escalables y nítidos.

## Paleta de Colores Corporativos Enertika

### Variables CSS (Definidas en `base.html`)

```css
:root {
    --enertika-primary: #123456;           /* Azul oscuro corporativo */
    --enertika-secondary: #00BABB;         /* Turquesa corporativo (color principal) */
    --enertika-secondary-dark: #009999;    /* Turquesa oscuro (hover) */
    --enertika-dark: #0E2A47;             /* Azul muy oscuro (sidebar) */
    --enertika-secondary-light: #E0F7F7;   /* Turquesa claro (fondos) */
}
```

### Uso de Colores

| Elemento | Color | CSS Class / Valor | Cuándo Usar |
|----------|-------|-------------------|-------------|
| **Títulos principales** | Azul oscuro | `text-[#123456]` | H1, H2, headings importantes |
| **Botones primarios** | Turquesa | `bg-[#00BABB]` | Acciones principales (Crear, Guardar) |
| **Hover botones** | Turquesa oscuro | `hover:bg-[#009999]` | Estado hover de botones |
| **Bordes de tarjetas** | Turquesa | `border-[#00BABB]` | Bordes superiores, laterales |
| **Fondos suaves** | Turquesa claro | `bg-[#E0F7F7]` | Fondos de badges, cards |
| **Sidebar** | Azul muy oscuro | `bg-[#0E2A47]` | Barra lateral |
| **Focus inputs** | Turquesa | `focus:ring-[#00BABB]` | Inputs, selects en focus |

### NUNCA Usar

```html
<!-- ❌ PROHIBIDO - Colores genéricos de Tailwind -->
<button class="bg-blue-600">...</button>      <!-- Usar bg-[#00BABB] -->
<h1 class="text-blue-800">...</h1>            <!-- Usar text-[#123456] -->
<div class="border-indigo-500">...</div>      <!-- Usar border-[#00BABB] -->
```

## 🎭 Sistema de Animaciones

### Animaciones Disponibles (CSS Keyframes)

```css
/* Entrada desde arriba */
.animate-fade-in-down { animation: fadeInDown 0.5s ease-out; }

/* Entrada desde abajo */
.animate-fade-in-up { animation: fadeInUp 0.4s ease-out; }

/* Pulso sutil continuo */
.animate-pulse-subtle { animation: pulse-subtle 2s ease-in-out infinite; }

/* Deslizamiento desde derecha */
.animate-slide-in { animation: slideInRight 0.3s ease-out; }

/* Efecto ripple en botones */
.ripple-effect { /* Se activa al hacer click */ }

/* Skeleton loader */
.skeleton { /* Efecto shimmer para loading */ }

/* Spinner corporativo */
.spinner-enertika { /* Spinner turquesa animado */ }
```

### Cuándo Usar Cada Animación

| Animación | Uso Recomendado | Ejemplo |
|-----------|----------------|---------|
| `animate-fade-in-down` | Contenedores principales | `<div class="container animate-fade-in-down">` |
| `animate-fade-in-up` | Tarjetas/Cards en lista | `<tr class="animate-fade-in-up">` |
| `animate-pulse-subtle` | Números importantes (KPIs) | `<p class="animate-pulse-subtle">24</p>` |
| `ripple-effect` | Botones de acción principal | `<button class="ripple-effect">` |
| `spinner-enertika` | Loading states | `<div class="spinner-enertika"></div>` |

## Componentes UI Estándar

### 1. Botones Principales

#### Botón Activo (Con permisos)

```html
<button hx-get="/modulo/form" 
        hx-target="#main-content" 
        hx-swap="innerHTML" 
        hx-push-url="true"
        class="ripple-effect bg-[#00BABB] hover:bg-[#009999] text-white font-bold py-2.5 px-5 rounded-lg shadow-lg shadow-[#00BABB]/30 flex items-center gap-2 transition-all duration-200 ease-in-out transform hover:scale-105">
    <svg>...</svg>
    Nuevo Registro
</button>
```

**Características:**
- Color turquesa corporativo (`#00BABB`)
- Hover más oscuro (`#009999`)
- Shadow con color corporativo (transparencia 30%)
- Efecto ripple al click
- Scale 105% en hover
- Transición 200ms

#### Botón Deshabilitado (Sin permisos)

```html
<div class="relative group">
    <button disabled
        class="bg-gray-300 text-gray-500 font-bold py-2.5 px-5 rounded-lg shadow cursor-not-allowed opacity-50 flex items-center gap-2">
        <svg>...</svg>
        Nuevo Registro 🔒
    </button>
    <div class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg shadow-lg whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none z-50">
        ⚠️ Solo lectura - Requiere permisos de edición
    </div>
</div>
```

**Características:**
- Gris para indicar deshabilitado
- Icono de candado (🔒)
- Tooltip explicativo al hover
- `cursor-not-allowed` para UX clara

### 2. Badges de Estado

#### Badge Corporativo (Estado en Proceso)

```html
<span class="px-3 py-1 inline-flex text-xs leading-5 font-bold rounded-lg bg-[#E0F7F7] text-[#123456] border border-[#00BABB] shadow-sm">
    ⚙️ En Proceso
</span>
```

#### Badge de Éxito

```html
<span class="px-3 py-1 inline-flex text-xs leading-5 font-bold rounded-lg bg-green-100 text-green-800 border border-green-300 shadow-sm">
    ✅ Entregado
</span>
```

#### Badge Pendiente

```html
<span class="px-3 py-1 inline-flex text-xs leading-5 font-bold rounded-lg bg-yellow-100 text-yellow-800 border border-yellow-300 shadow-sm">
    ⏳ Pendiente
</span>
```

**Estándar de Badges:**
- `rounded-lg` (no `rounded-full`)
- `font-bold` para mejor legibilidad
- Borde del mismo color (más oscuro)
- Shadow sutil (`shadow-sm`)
- Emoji/icono al inicio

### 3. KPIs (Tarjetas de Métricas)

```html
<div class="bg-white p-4 rounded-lg shadow-md border-l-4 border-[#00BABB] flex items-center hover:shadow-lg transition-shadow duration-200">
    <div class="p-3 rounded-full bg-[#E0F7F7] text-[#00BABB] mr-4">
        <svg class="h-6 w-6">...</svg>
    </div>
    <div>
        <p class="text-sm text-gray-500 font-medium">Total Registros</p>
        <p class="text-2xl font-bold text-gray-800 animate-pulse-subtle">24</p>
    </div>
</div>
```

**Características:**
- Borde lateral grueso (4px) en color corporativo
- Ícono en círculo con fondo turquesa claro
- Número con `animate-pulse-subtle` (pulso sutil)
- Hover eleva el shadow (`hover:shadow-lg`)
- Transición suave de 200ms

#### Colores de Bordes Semánticos

| Tipo KPI | Color Borde | Clase |
|----------|-------------|-------|
| Principal | Turquesa | `border-[#00BABB]` |
| Éxito | Verde | `border-green-500` |
| Advertencia | Naranja | `border-orange-500` |
| Error | Rojo | `border-red-500` |

### 4. Loading States

#### Spinner Corporativo

```html
<div class="flex justify-center items-center h-full">
    <div class="text-center">
        <div class="spinner-enertika mx-auto mb-4"></div>
        <p class="text-[#00BABB] font-medium animate-pulse-subtle">Cargando datos...</p>
    </div>
</div>
```

#### Skeleton Loader (Framework disponible)

```html
<div class="skeleton skeleton-title"></div>  <!-- Título -->
<div class="skeleton skeleton-text"></div>   <!-- Texto -->
<div class="skeleton skeleton-text"></div>
```

##  Mejores Prácticas de Diseño

### 1. Espaciado Consistente

```html
<!--  BIEN - Espaciado progresivo -->
<div class="p-4">      <!-- Contenedores pequeños -->
<div class="p-6">      <!-- Contenedores medianos -->
<div class="p-8">      <!-- Contenedores grandes -->

<div class="mb-4">     <!-- Espaciado entre elementos -->
<div class="mb-6">     <!-- Espaciado entre secciones -->
```

### 2. Jerarquía de Tipografía

```html
<!-- Títulos principales -->
<h1 class="text-3xl font-bold text-[#123456]">        <!-- 30px -->
<h2 class="text-2xl font-bold text-[#123456]">        <!-- 24px -->
<h3 class="text-lg font-semibold text-[#123456]">     <!-- 18px -->

<!-- Texto regular -->
<p class="text-sm text-gray-600">                      <!-- 14px -->
<span class="text-xs text-gray-500">                   <!-- 12px -->
```

### 3. Bordes y Sombras

```html
<!-- Bordes corporativos -->
<div class="border-t-4 border-[#00BABB]">    <!-- Borde superior -->
<div class="border-l-4 border-[#00BABB]">    <!-- Borde lateral -->

<!-- Sombras progresivas -->
<div class="shadow-sm">    <!-- Sutil -->
<div class="shadow-md">    <!-- Media -->
<div class="shadow-lg">    <!-- Pronunciada -->

<!-- Shadow corporativo -->
<button class="shadow-lg shadow-[#00BABB]/30">
```

### 4. Estados Interactivos

```html
<!-- Estados hover completos -->
<button class="bg-[#00BABB] hover:bg-[#009999] hover:shadow-lg hover:scale-105 transition-all duration-200">

<!-- Focus states -->
<input class="focus:ring-2 focus:ring-[#00BABB] focus:border-[#00BABB] transition-all">

<!-- Disabled states -->
<button disabled class="opacity-50 cursor-not-allowed">
```

## 🎯 Checklist de Validación UI

Antes de hacer commit de un nuevo componente, verificar:

- [ ] Usa colores corporativos (`#00BABB`, `#123456`)
- [ ] Tiene animación de entrada (`animate-fade-in-*`)
- [ ] Botones tienen ripple effect (`.ripple-effect`)
- [ ] Estados hover son claros (`hover:bg-[#009999]`)
- [ ] Loading states usan `spinner-enertika`
- [ ] Badges tienen bordes y son `rounded-lg`
- [ ] KPIs tienen borde lateral de 4px
- [ ] Transiciones son suaves (200ms)
- [ ] Tooltips en botones deshabilitados
- [ ] Responsive (grid cols responsive)

---

[← Volver al Índice](README.md)
