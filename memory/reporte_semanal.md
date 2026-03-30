---
name: Reporte Semanal - Configuración y Pendientes
description: Estado de configuración del reporte semanal automático (GitHub Actions + Railway + BD)
type: project
---

## Reporte Semanal Automático

**Cron:** viernes 3pm MX (21:00 UTC)
**Endpoint:** `POST /admin/reportes/cron/reporte-semanal`
**UI manual:** `/admin/ui/reporte-semanal` — botón "Enviar correo ahora"

### Estado de configuración (verificado 2026-03-17)

| Componente | Estado |
|---|---|
| GitHub Actions workflow | ✅ `.github/workflows/reporte-semanal.yml` pusheado |
| GitHub secret `CRON_SECRET` | ✅ usuario confirmó configurado |
| GitHub secret `APP_URL` | ✅ usuario confirmó configurado |
| Railway env var `CRON_SECRET` | ✅ usuario confirmó configurado |
| `tb_configuracion_global.reporte_semanal_destinatarios` | ✅ `sistemas@enertika.mx` |

### Notas
- Los secrets de GitHub y Railway no son verificables desde el código — el usuario los confirmó manualmente.
- Si el cron falla, revisar logs en GitHub Actions y en Railway.
