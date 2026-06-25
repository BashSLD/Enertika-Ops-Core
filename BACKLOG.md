# Backlog — Enertika Ops Core

Items diferidos. NO implementar sin decisión explícita del equipo.

---

- **Dashboards / Alertas — Fase 6:** dashboards operativos y sistema de alertas configurable.
- **Traspasos — Badge status en tab Ganadas (Comercial):** mostrar indicador de traspaso/proyecto en cards del tab Ganadas. `templates/comercial/partials/cards.html`.
- **Traspasos — UI polish:** contador de docs en modal, tooltip días en área, filtros URL en proyectos.
- **PDF Simulación — Gráficas automáticas:** `ReportesSimulacionService.get_graficas_pdf()` no existe. El endpoint `/pdf/generar-automatico` pasa `charts={}`. Implementar para que el PDF incluya gráficas vía QuickChart (`core/charts/service.py`).
