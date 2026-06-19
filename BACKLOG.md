# Backlog — Enertika Ops Core

Items diferidos. NO implementar sin decisión explícita del equipo.

---

- **Levantamientos — Mapa de sitios:** integración Google Maps para visualizar ubicaciones de levantamientos.
- **Dashboards / Alertas — Fase 6:** dashboards operativos y sistema de alertas configurable.
- **BOM SSE:** notificaciones en tiempo real (Server-Sent Events) para cambios de estatus en BOM.
- **Traspasos — Badge status en tab Ganadas (Comercial):** mostrar indicador de traspaso/proyecto en cards del tab Ganadas. `templates/comercial/partials/cards.html`.
- **Traspasos — UI polish:** contador de docs en modal, tooltip días en área, filtros URL en proyectos.
- **Compras — Bug OOB stats staging modal:** vincular XML muestra ceros hasta F5. Triple nesting de `<div id="stats-container">` en `estadisticas.html` + `content.html` + `router.py:392`. Fix: quitar el wrapper extra en `content.html`.
- **PDF Simulación — Gráficas automáticas:** `ReportesSimulacionService.get_graficas_pdf()` no existe. El endpoint `/pdf/generar-automatico` pasa `charts={}`. Implementar para que el PDF incluya gráficas vía QuickChart (`core/charts/service.py`).
- **`tb_usuarios.es_rh` — columna muerta:** se carga en `core/security.py` (`context["es_rh"]`) pero ningún módulo la consume. El acceso real a RH/vacaciones ya usa RBAC estándar (`user_has_module_access("rrhh", ...)` en `modules/vacaciones/router.py:380`). Verificado en PROD: el único usuario con permiso sobre el slug `rrhh` tiene `es_rh=false` — confirma que están desincronizados. No expuesta en Admin UI. Candidato a eliminar (columna + carga en `core/security.py` + migración de drop) tras confirmar que no hay otro consumidor oculto.
- **SharePoint — `import re` dentro de método estático:** `core/integrations/sharepoint.py` l.236. `_sanitize_filename` hace `import re` en el cuerpo del método en lugar del top del módulo. Mover al encabezado del archivo.
