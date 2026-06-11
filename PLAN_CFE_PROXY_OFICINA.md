# Plan: Proxy de Oficina para CFE Scraping en Railway

## Contexto

El portal público CFE (`app.cfe.mx`) bloquea IPs de datacenters (Railway corre en AWS).
Confirmado en logs Railway 2026-06-11:

```
[CFE] Portal sin filas servicio=XXX body_len=~0
[CFE] Busqueda fallo ... error=Portal CFE devolvió página vacía.
Probable bloqueo por IP de servidor (Railway).
```

La solución: un proxy HTTP corriendo en la PC de oficina, usando la IP pública estática
contratada. Playwright en Railway enruta el tráfico CFE a través de ese proxy.

---

## Paso 1 — Instalar 3proxy en la PC de oficina (Windows)

1. Descargar el ejecutable desde: https://github.com/3proxy/3proxy/releases
   - Archivo: `3proxy-VERSION-win64.zip` → extraer en `C:\3proxy\`

2. Crear `C:\3proxy\3proxy.cfg`:

```
nserver 8.8.8.8
nserver 8.8.4.4
auth strong
users cfe:CL5:PASSWORD_SEGURO_AQUI
allow *
proxy -p3128
```

   > Cambiar `PASSWORD_SEGURO_AQUI` por una contraseña real.

3. Probar manualmente:
```
C:\3proxy\3proxy.exe C:\3proxy\3proxy.cfg
```

4. Registrar como servicio de Windows para que inicie automáticamente:
```cmd
sc create 3proxy binPath= "C:\3proxy\3proxy.exe C:\3proxy\3proxy.cfg" start= auto
sc start 3proxy
```

---

## Paso 2 — Abrir puerto en el router de oficina

- Protocolo: **TCP**
- Puerto externo: `3128`
- Puerto interno: `3128`
- IP destino: IP local de la PC donde corre 3proxy (ej. `192.168.1.X`)

Verificar que el firewall de Windows también permita el puerto 3128 entrante:
```cmd
netsh advfirewall firewall add rule name="3proxy CFE" dir=in action=allow protocol=TCP localport=3128
```

---

## Paso 3 — Variable de entorno en Railway

En Railway → servicio **Worker** → Variables:

```
CFE_PROXY_URL=http://cfe:PASSWORD_SEGURO_AQUI@IP_PUBLICA_OFICINA:3128
```

> Reemplazar `IP_PUBLICA_OFICINA` con la IP estática contratada.
> Reemplazar `PASSWORD_SEGURO_AQUI` con la misma contraseña del Paso 1.

---

## Paso 4 — Cambio de código en `modules/cfe/scraper.py`

**PENDIENTE DE IMPLEMENTAR.**

Leer `CFE_PROXY_URL` del entorno y pasarlo a Playwright en los 3 puntos de `launch()`.

Cambio estimado: ~15 líneas. Pedir a Claude: _"implementa el Paso 4 del PLAN_CFE_PROXY_OFICINA.md"_.

El cambio agrega algo como esto en los 3 `launch_kwargs` del scraper:

```python
import os
from urllib.parse import urlparse

def _build_proxy_kwargs() -> dict:
    raw = os.environ.get("CFE_PROXY_URL", "").strip()
    if not raw:
        return {}
    parsed = urlparse(raw)
    proxy: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return {"proxy": proxy}

# En cada launch_kwargs:
launch_kwargs.update(_build_proxy_kwargs())
```

---

## Verificación final

Después de deploy en Railway, buscar en logs del Worker:

```
[CFE] Busqueda reclamada busqueda_id=... max_periodos=12
[CFE] Scraper finalizó ...   ← debe aparecer este, sin el error de página vacía
```

Si sigue fallando con `body_len=0` → verificar que el proxy esté corriendo
y que el puerto sea accesible desde internet (`telnet IP_PUBLICA 3128`).
