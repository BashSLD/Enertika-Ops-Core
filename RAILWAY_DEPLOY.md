# Railway Deploy — QuickChart + Worker + Redis

Ejecutar en este orden exacto.

---

## PASO 1 — Agregar QuickChart

1. Ir al proyecto en [railway.app](https://railway.app)
2. Click **+ New** → **Docker Image**
3. Imagen: `ianw/quickchart`
4. Confirmar — Railway descarga y levanta el contenedor
5. En el servicio creado → **Settings** → **Networking**:
   - Desactivar **Public networking** (no necesita dominio público)
   - Verificar que el puerto interno sea `3400` (QuickChart lo expone por defecto)
   - Si Railway no lo detecta automáticamente: **Variables** → agregar `PORT=3400`
6. Verificar en **Logs** del servicio que aparezca:
   ```
   Listening on port 3400
   ```

---

## PASO 2 — Agregar Redis

1. Click **+ New** → **Database** → **Add Redis**
2. Railway provisiona Redis automáticamente y genera la variable `REDIS_URL`
3. No se requiere configuración adicional

---

## PASO 3 — Configurar variables en el servicio FastAPI

En el servicio principal (FastAPI/Gunicorn) → pestaña **Variables**:

**Agregar manualmente:**
```
QUICKCHART_URL=http://quickchart.railway.internal:3400
```

> El hostname `quickchart.railway.internal` lo genera Railway con el nombre del servicio.
> Si renombraste el servicio de QuickChart, ajustar el hostname.

**Agregar via referencia:**
- Click **Add Reference** → seleccionar `REDIS_URL` del servicio Redis

Guardar → Railway hace redeploy automático del servicio FastAPI.

---

## PASO 4 — Agregar Worker

1. Click **+ New** → **GitHub Repo** → seleccionar el mismo repo de Enertika Ops Core
2. En el servicio creado → **Settings** → **Deploy** → **Start Command**:
   ```
   python worker.py
   ```
3. En **Variables** del Worker, agregar las siguientes (copiar del servicio FastAPI):

   | Variable | Nota |
   |---|---|
   | `DB_HOST` | |
   | `DB_USER` | |
   | `DB_PASSWORD` | |
   | `DB_PORT` | |
   | `DB_PORT_SSE` | |
   | `SECRET_KEY` | |
   | `CLIENT_ID` | |
   | `CLIENT_SECRET` | |
   | `TENANT_ID` | |
   | `APP_BASE_URL` | |
   | `BANXICO_TOKEN` | |
   | `GITHUB_TOKEN` | |
   | `GITHUB_REPO` | |
   | `GITHUB_BRANCH` | |

4. Agregar via referencia:
   - Click **Add Reference** → seleccionar `REDIS_URL` del servicio Redis

5. **NO** agregar al Worker: `REDIRECT_URI`, `CRON_SECRET`, `SESSION_MAX_AGE`, `QUICKCHART_URL`

---

## Verificación

### Worker arrancó correctamente
En **Logs** del servicio Worker deben aparecer:
```
[WORKER] Iniciando worker de tareas periodicas
[WORKER] 6 tareas activas
[CEO_REPORT] Tarea inicializada
[TIPO_CAMBIO] Tarea periodica inicializada (intervalo: 1h)
```

### FastAPI ya no corre las tareas periódicas
En **Logs** del servicio FastAPI al iniciar **NO** deben aparecer:
```
[CEO_REPORT] ...
[TIPO_CAMBIO] ...
[LEV_REMINDER] ...
```

### Redis recibiendo claves
En el servicio Redis → pestaña **Data** → tras navegar en la app deben aparecer
claves con prefijo `eco:config:` y TTL de 30 segundos.

### QuickChart responde
El endpoint `/simulacion/reportes/pdf/generar-automatico` (POST con `fecha_inicio`)
debe devolver un PDF descargable.

---

## Resumen de servicios en el proyecto Railway

| Servicio | Tipo | Start Command |
|---|---|---|
| FastAPI (existente) | GitHub repo | `gunicorn main:app -c gunicorn.conf.py` |
| QuickChart | Docker image `ianw/quickchart` | — |
| Redis | Database plugin | — |
| Worker | GitHub repo (mismo) | `python worker.py` |
