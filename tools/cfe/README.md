# Lanzador local — Renovar sesión CFE MiEspacio

Permite al administrador del sistema **renovar la sesión de MiEspacio desde su PC**,
resolviendo el CAPTCHA una vez. El script captura la
sesión (`storage_state` de Playwright) y la sube automáticamente al app.

## Por qué existe

El portal público de CFE (XML) está 100% automatizado. **MiEspacio (PDF)** exige
resolver un CAPTCHA en el login, que no se puede automatizar. El servidor del app corre
sin pantalla (Railway), así que el navegador con el CAPTCHA tiene que abrirse en una
máquina con monitor: la PC del usuario. Este lanzador hace justamente eso y elimina el
copy-paste manual del `state.json`.

## Ejecución desde código fuente

1. **Python 3.12** instalado.
2. Instalar dependencias:
   ```
   pip install -r requirements.txt
   ```
3. Asegurar el navegador (usa el Microsoft Edge ya instalado en Windows; si no, instálalo):
   ```
   playwright install msedge
   ```

## Uso

```
python renovar_sesion.py
```

El administrador global abre
*Renovar sesión MiEspacio* en Enertika Ops Core y copia el código temporal.
El lanzador lo pedirá en cada renovación y mostrará un asterisco por cada
carácter pegado, sin revelar el código. El código:

- pertenece al usuario autenticado;
- expira en 10 minutos;
- funciona una sola vez;
- no se guarda en la computadora.

Una vez que el servidor canjea el código, deja de ser reutilizable. Como ante
un error no siempre puede saberse si alcanzó a consumirlo, cierra el modal de
renovación, vuelve a abrirlo y copia un código nuevo antes de reintentar.

Luego:
1. El código se canjea por una autorización efímera.
2. Se abre Edge en MiEspacio y las credenciales se autocompletan.
3. Resuelve el CAPTCHA y da clic en *Ingresar* (**único paso manual**).
4. **No cierres la ventana**: el script detecta el login solo.
5. Cuando veas *"Sesión renovada correctamente"*, listo.

La consola permanece abierta al terminar o si ocurre un error, para que el
usuario pueda leer el resultado antes de presionar ENTER y cerrarla.

El lanzador sólo se conecta a `https://eco.enertika.mx` y
`https://app.cfe.mx`. No ignora errores TLS, no sigue redirecciones del API y
sólo sube cookies u orígenes pertenecientes a `cfe.mx`.

Las instalaciones anteriores pueden eliminar
`%USERPROFILE%\.enertika\cfe_config.json`; la versión actual no lo utiliza.

## Generación de claves de release

La clave privada se conserva fuera del repositorio. En la máquina que prepara
releases, instala primero las dependencias de build y crea el par inicial:

```
python -m pip install -r requirements-build.txt
python sign_release.py generate-keypair --private-key C:\ruta-segura\cfe_launcher_private.pem --public-key C:\ruta-segura\cfe_launcher_public.pem
```

Pega únicamente la clave pública en:
*Admin → Configuración Global → Recibos CFE → Clave pública de firma*.

### Custodia y cambio de equipo

Los archivos `cfe_launcher_private.pem` y `cfe_launcher_public.pem` están
excluidos de Git. La clave pública también se conserva en PostgreSQL, dentro
de `tb_configuracion_global` con la llave
`CFE_LANZADOR_SIGNING_PUBLIC_KEY`, por lo que sobrevive a los deployments.

La clave privada es la identidad de firma del lanzador. Debe respaldarse
cifrada, junto con su contraseña guardada por separado, en un gestor de
secretos corporativo o medio externo cifrado. No debe enviarse por correo,
Teams ni almacenarse dentro del repositorio.

Al cambiar de equipo, el procedimiento preferido es:

1. Instalar Python 3.12 y `requirements-build.txt`.
2. Recuperar `cfe_launcher_private.pem` desde el respaldo seguro.
3. Conservar la misma contraseña y la misma clave pública configurada en el app.
4. Compilar una versión posterior y publicar juntos el EXE y su manifiesto.

### Rotación o pérdida de la clave privada

Si la clave privada se pierde o se sospecha que fue expuesta:

1. Genera un par nuevo con `sign_release.py generate-keypair`.
2. Sustituye la clave pública desde Administración.
3. Compila una versión posterior usando la nueva clave privada.
4. Publica juntos el nuevo EXE y su manifiesto.
5. Respalda la nueva clave privada y elimina de forma segura copias obsoletas.

No generes una clave distinta por cada equipo: se mantiene una sola identidad
de firma y sólo se rota ante pérdida, exposición o decisión administrativa.

## Build de release

El build usa un entorno aislado, versiones fijadas, PyInstaller sin UPX y un
manifiesto Ed25519 obligatorio.

Para uso interno sin certificado Authenticode, ejecútalo desde PowerShell:

```powershell
$env:CFE_LAUNCHER_VERSION = "2026.07.31.1"
$env:CFE_SIGNING_PRIVATE_KEY_FILE = "C:\ruta-segura\cfe_launcher_private.pem"
$env:CFE_ALLOW_UNSIGNED = "1"
.\build_exe.bat
```

`CFE_ALLOW_UNSIGNED=1` es deliberadamente explícito: evita omitir Authenticode
por accidente. Windows mostrará `Editor desconocido`, pero la aplicación
seguirá exigiendo y verificando la firma Ed25519 del release.

La versión usa `YYYY.MM.DD`. Si publicas otra compilación el mismo día,
incrementa la revisión (`2026.07.31.1`, `2026.07.31.2`, etc.). La aplicación
rechaza versiones repetidas o anteriores para impedir rollbacks.

Si posteriormente se obtiene un certificado Authenticode, omite
`CFE_ALLOW_UNSIGNED` y define su huella:

```powershell
$env:CFE_AUTHENTICODE_CERT_SHA1 = "HUELLA_DEL_CERTIFICADO"
Remove-Item Env:CFE_ALLOW_UNSIGNED -ErrorAction SilentlyContinue
.\build_exe.bat
```

El proceso pide el password de la clave privada sin mostrarlo. En automatización
puede proporcionarse mediante el secreto de entorno `CFE_SIGNING_KEY_PASSWORD`.

Resultado:

- `dist\RenovarSesionCFE.exe`
- `dist\RenovarSesionCFE.exe.manifest.json`

La pantalla de administración exige ambos archivos. Antes de publicarlo
verifica la firma Ed25519, el tamaño y el SHA-256. Cada descarga vuelve a
calcular el SHA-256 del archivo almacenado en SharePoint.

No añadas exclusiones permanentes del antivirus. Si el release estable sigue
marcado, envía esa muestra al fabricante para revisión como posible falso
positivo.
