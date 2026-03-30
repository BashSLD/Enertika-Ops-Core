---
name: Regla - Gestión de memoria y MEMORY.md
description: Cómo decidir dónde guardar nueva información en memoria sin saturar MEMORY.md
type: feedback
---

Al guardar cualquier información en memoria, analizar PRIMERO dónde corresponde:

1. **¿Ya existe un archivo de memoria para ese módulo/tema?** → Agregar ahí, NO en MEMORY.md
2. **¿Es una regla global, patrón técnico o convención que aplica a todo el proyecto?** → Sí va en MEMORY.md (sección correspondiente)
3. **¿Es detalle de implementación, bugs, correcciones, o roadmap?** → Crear/actualizar archivo específico (`memory/modulo_tema.md`) y poner solo un puntero en MEMORY.md
4. **¿Es agenda/agenda de próxima sesión?** → Actualizar sección "Próxima sesión — Agenda" en MEMORY.md (reemplazar, no acumular)

**Regla de oro:** MEMORY.md es un índice, no un log. Si una sección supera 6 líneas de detalle, moverla a archivo propio.

**Why:** MEMORY.md se trunca en 200 líneas en cada conversación. Contenido por encima de ese límite nunca se lee.

**How to apply:** Antes de escribir en MEMORY.md, preguntar "¿esto es un patrón global o un detalle de módulo?". Si es detalle → archivo propio.
