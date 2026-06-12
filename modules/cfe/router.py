# modules/cfe/router.py
from __future__ import annotations

import logging
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.jinja_filters import register_timezone_filters
from core.permissions import require_any_module_access, user_has_module_access
from core.security import get_current_user_context
from modules.shared.services.cfe import generar_excel_cfe_desde_uploads

from .constants import CFE_MODULE_SLUGS, CFE_PUBLIC_FORM_DEFAULTS
from .service import get_cfe_service

logger = logging.getLogger("CfeRouter")

router = APIRouter(prefix="/cfe", tags=["CFE"])
templates = Jinja2Templates(directory="templates")
register_timezone_filters(templates.env)

# require_any_module_access YA retorna Depends() (core/permissions.py). NO envolver en Depends().
_viewer = require_any_module_access(CFE_MODULE_SLUGS, min_role="viewer")

# Tope del body en /sesion/subir: un storage_state real son pocos KB; 2 MB es holgado.
_MAX_SESION_BODY_BYTES = 2 * 1024 * 1024


def _resolver_modulos(user: dict, modulo_param: str | None) -> tuple[str | None, list[str]]:
    """
    Devuelve (modulo_activo, modulos_accesibles).

    modulo_activo es el slug a usar como contexto de navegacion (None = ve todo).
    modulos_accesibles es la lista de slugs que el usuario puede ver.
    """
    accesibles = [m for m in CFE_MODULE_SLUGS if user_has_module_access(m, user, min_role="viewer")]

    if not accesibles:
        return None, []

    if modulo_param and modulo_param in CFE_MODULE_SLUGS:
        activo = modulo_param if modulo_param in accesibles else accesibles[0]
    elif len(accesibles) == 1:
        activo = accesibles[0]
    else:
        activo = None  # tiene ambos → ve todo

    return activo, accesibles


async def _get_servicio_accesible(svc, conn, servicio_id: UUID, user: dict) -> dict:
    """Raises 404 if service not found or not in any module the user can access."""
    _, modulos_accesibles = _resolver_modulos(user, None)
    servicio = await svc.db.get_servicio_by_id(conn, servicio_id)
    if not servicio or not (set(servicio.get("modulos") or []) & set(modulos_accesibles)):
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return servicio


# ── UI principal ──────────────────────────────────────────────────────────────

@router.get("/ui", response_class=HTMLResponse)
async def cfe_ui(
    request: Request,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    await svc.limpiar_errores_invalidos(conn)
    servicios = await svc.listar_servicios(conn, modulos=[modulo_activo] if modulo_activo else modulos_accesibles)
    estado_sesion = await svc.get_estado_sesion(conn)
    is_htmx = request.headers.get("hx-request")
    is_restore = request.headers.get("hx-history-restore-request")
    ctx = {
        "servicios": servicios,
        "estado_sesion": estado_sesion,
        "modulo": modulo_activo,
        "modulos_accesibles": modulos_accesibles,
        "user": user,
        "user_name": user.get("user_name"),
        "role": user.get("role"),
        "module_roles": user.get("module_roles", {}),
    }
    template = "cfe/partials/lista_servicios.html" if (is_htmx and not is_restore) else "cfe/index.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/servicios/{servicio_id}/analisis", response_class=HTMLResponse)
async def analisis_servicio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    await _get_servicio_accesible(svc, conn, servicio_id, user)
    try:
        analisis = await svc.get_analisis_servicio(conn, servicio_id)
    except ValueError as exc:
        if str(exc) == "Servicio no encontrado.":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD generando analisis CFE para %s: %s", servicio_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al generar el análisis.") from exc

    is_htmx = request.headers.get("hx-request")
    is_restore = request.headers.get("hx-history-restore-request")
    ctx = {
        "analisis": analisis,
        "modulo": modulo_activo,
        "user": user,
        "user_name": user.get("user_name"),
        "role": user.get("role"),
        "module_roles": user.get("module_roles", {}),
    }
    template = "cfe/partials/analisis_servicio.html" if (is_htmx and not is_restore) else "cfe/analisis.html"
    return templates.TemplateResponse(request, template, ctx)


# ── Modal agregar ─────────────────────────────────────────────────────────────

@router.get("/ui/modal-agregar", response_class=HTMLResponse)
async def modal_agregar(
    request: Request,
    modulo: str | None = Query(default=None),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    _, modulos_accesibles = _resolver_modulos(user, modulo)
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_agregar_servicio.html",
        {
            "contacto_defaults": CFE_PUBLIC_FORM_DEFAULTS,
            "modulo": modulo,
            "modulos_accesibles": modulos_accesibles,
        },
    )


@router.get("/ui/modal-xml-excel", response_class=HTMLResponse)
async def modal_xml_excel(
    request: Request,
    user=Depends(get_current_user_context),
    _=_viewer,
):
    return templates.TemplateResponse(
        request,
        "shared/modals/cfe_upload_modal.html",
        {
            "module_slug": "cfe",
            "module_label": "XML a Excel",
            "post_url": "/cfe/xml-excel",
            "accent": "blue",
        },
    )


@router.get("/ui/modal-renovar-sesion", response_class=HTMLResponse)
async def modal_renovar_sesion(
    request: Request,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    estado_sesion = await svc.get_estado_sesion(conn)
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_renovar_sesion.html",
        {"estado_sesion": estado_sesion, "modulo": modulo_activo, "user": user},
    )


@router.get("/servicios/{servicio_id}/modal-buscar-periodos", response_class=HTMLResponse)
async def modal_buscar_periodos(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_buscar_periodos.html",
        {"servicio": servicio, "modulo": modulo_activo, "user": user},
    )


# ── Servicios ─────────────────────────────────────────────────────────────────

@router.get("/servicios/{servicio_id}/modal-busqueda-activa", response_class=HTMLResponse)
async def modal_busqueda_activa(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    busqueda, items = await svc.get_busqueda_activa_periodos(conn, servicio_id)
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_buscar_periodos.html",
        {"servicio": servicio, "busqueda": busqueda, "items": items, "modulo": modulo_activo, "user": user},
    )


@router.post("/servicios", response_class=HTMLResponse)
async def crear_servicio(
    request: Request,
    numero_servicio: str = Form(...),
    nombre: str = Form(...),
    alias: str = Form(""),
    modulo_form: str = Form("oym", alias="modulo"),
    lada: str = Form(CFE_PUBLIC_FORM_DEFAULTS["lada"]),
    telefono: str = Form(CFE_PUBLIC_FORM_DEFAULTS["telefono"]),
    email: str = Form(CFE_PUBLIC_FORM_DEFAULTS["email"]),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    if modulo_form not in CFE_MODULE_SLUGS:
        modulo_form = CFE_MODULE_SLUGS[0]
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo_form)
    modulo_guardado = modulo_activo or modulo_form
    toast_type = "success"
    toast_msg = ""
    status_code = 200
    try:
        _, fue_nuevo = await svc.crear_servicio(
            conn, numero_servicio=numero_servicio.strip(), nombre=nombre.strip(),
            alias=alias.strip() or None, lada=lada.strip(), telefono=telefono.strip(),
            email=email.strip(), usuario_id=user["user_db_id"], modulo=modulo_guardado,
        )
        toast_msg = (
            f"Servicio {numero_servicio} registrado."
            if fue_nuevo
            else f"Módulo añadido al servicio {numero_servicio} existente."
        )
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD creando servicio CFE: {exc}")
        toast_msg = "Error interno al registrar el servicio."
        toast_type = "error"
        status_code = 500
    servicios = await svc.listar_servicios(
        conn, modulos=[modulo_activo] if modulo_activo else modulos_accesibles
    )
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
        },
        status_code=status_code,
    )


@router.post("/servicios/{servicio_id}/reintentar-alta", response_class=HTMLResponse)
async def reintentar_alta_miespacio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    await _get_servicio_accesible(svc, conn, servicio_id, user)
    toast_type = "success"
    toast_msg = ""
    status_code = 200
    try:
        toast_msg, _servicio = await svc.reintentar_alta_miespacio(conn, servicio_id)
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD reencolando alta MiEspacio CFE para {servicio_id}: {exc}")
        toast_msg = "Error interno al reencolar el registro."
        toast_type = "error"
        status_code = 500
    servicios = await svc.listar_servicios(
        conn, modulos=[modulo_activo] if modulo_activo else modulos_accesibles
    )
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
        },
        status_code=status_code,
    )


# ── Descargas ─────────────────────────────────────────────────────────────────

@router.post("/xml-excel", response_class=StreamingResponse, include_in_schema=False)
async def generar_excel_desde_xml(
    files: list[UploadFile] = File(...),
    perfil: str = Form("oym"),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    try:
        buffer = await generar_excel_cfe_desde_uploads(
            files,
            perfil_slug=perfil,
            modo_calculo="calculado",
        )
    except ValueError as exc:
        logger.warning(
            "cfe_xml_excel_error usuario=%s error=%s",
            user.get("user_db_id"),
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="recibos_cfe.xlsx"'},
    )


@router.get("/servicios/{servicio_id}/descargas", response_class=HTMLResponse)
async def historial_descargas(
    request: Request,
    servicio_id: UUID,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    await svc.limpiar_errores_invalidos(conn, servicio_id)
    descargas = await svc.db.get_descargas_por_servicio(conn, servicio_id)
    tiene_activo = any(d["estatus"] in ("pendiente", "descargando") for d in descargas)
    return templates.TemplateResponse(
        request, "cfe/partials/historial_descargas.html",
        {"servicio": servicio, "descargas": descargas,
         "tiene_activo": tiene_activo, "user": user},
    )


@router.post("/servicios/{servicio_id}/descargar", response_class=HTMLResponse)
async def iniciar_descarga(
    request: Request,
    servicio_id: UUID,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    tiene_activo = False
    toast_type = "info"
    toast_msg = ""
    status_code = 200
    try:
        toast_msg, servicio = await svc.iniciar_descarga(conn, servicio_id, user["user_db_id"])
        tiene_activo = True
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD encolando descarga CFE para {servicio_id}: {exc}")
        toast_msg = "Error interno al encolar la descarga."
        toast_type = "error"
        status_code = 500
    descargas = await svc.db.get_descargas_por_servicio(conn, servicio_id)
    return templates.TemplateResponse(
        request, "cfe/partials/historial_descargas.html",
        {"servicio": servicio, "descargas": descargas, "tiene_activo": tiene_activo,
         "user": user, "_toast": {"message": toast_msg, "type": toast_type}},
        status_code=status_code,
    )


@router.post("/servicios/{servicio_id}/buscar-periodos", response_class=HTMLResponse)
async def iniciar_busqueda_periodos(
    request: Request,
    servicio_id: UUID,
    max_periodos: int = Form(12),
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    toast_type = "info"
    toast_msg = ""
    status_code = 200
    busqueda = None
    try:
        toast_msg, servicio, busqueda = await svc.iniciar_busqueda_periodos(
            conn, servicio_id, max_periodos, user["user_db_id"]
        )
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD encolando busqueda CFE para {servicio_id}: {exc}")
        toast_msg = "Error interno al encolar la busqueda."
        toast_type = "error"
        status_code = 500
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return templates.TemplateResponse(
        request,
        "cfe/partials/busqueda_periodos.html",
        {
            "servicio": servicio,
            "busqueda": busqueda,
            "items": [],
            "modulo": modulo_activo,
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
        },
        status_code=status_code,
    )


@router.get("/servicios/{servicio_id}/busquedas/{busqueda_id}", response_class=HTMLResponse)
async def ver_busqueda_periodos(
    request: Request,
    servicio_id: UUID,
    busqueda_id: UUID,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    try:
        busqueda, items = await svc.get_busqueda_periodos(conn, servicio_id, busqueda_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request,
        "cfe/partials/busqueda_periodos.html",
        {"servicio": servicio, "busqueda": busqueda, "items": items, "modulo": modulo_activo, "user": user},
    )


@router.post("/servicios/{servicio_id}/busquedas/{busqueda_id}/confirmar", response_class=HTMLResponse)
async def confirmar_busqueda_periodos(
    request: Request,
    servicio_id: UUID,
    busqueda_id: UUID,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    await _get_servicio_accesible(svc, conn, servicio_id, user)
    form = await request.form()
    periodos = [str(value) for value in form.getlist("periodos")]
    toast_type = "success"
    toast_msg = "Periodos seleccionados conservados."
    status_code = 200
    try:
        await svc.confirmar_busqueda_periodos(
            conn, servicio_id, busqueda_id, periodos, user["user_db_id"]
        )
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD confirmando busqueda CFE {busqueda_id}: {exc}")
        toast_msg = "Error interno al confirmar la busqueda."
        toast_type = "error"
        status_code = 500

    servicio = await svc.db.get_servicio_by_id(conn, servicio_id)
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    try:
        busqueda, items = await svc.get_busqueda_periodos(conn, servicio_id, busqueda_id)
    except ValueError:
        busqueda, items = None, []
    descargas = await svc.db.get_descargas_por_servicio(conn, servicio_id)
    tiene_activo = any(d["estatus"] in ("pendiente", "descargando") for d in descargas)
    return templates.TemplateResponse(
        request,
        "cfe/partials/busqueda_confirmada.html",
        {
            "servicio": servicio,
            "busqueda": busqueda,
            "items": items,
            "descargas": descargas,
            "tiene_activo": tiene_activo,
            "modulo": modulo_activo,
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
        },
        status_code=status_code,
    )


@router.post("/servicios/{servicio_id}/descargas/{periodo}/reintentar-pdf", response_class=HTMLResponse)
async def reintentar_pdf(
    request: Request,
    servicio_id: UUID,
    periodo: str,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    tiene_activo = False
    toast_type = "info"
    toast_msg = ""
    status_code = 200
    try:
        toast_msg, servicio = await svc.iniciar_descarga_pdf(
            conn, servicio_id, periodo, user["user_db_id"]
        )
        tiene_activo = True
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD encolando PDF CFE para {servicio_id}/{periodo}: {exc}")
        toast_msg = "Error interno al encolar la descarga del PDF."
        toast_type = "error"
        status_code = 500
    descargas = await svc.db.get_descargas_por_servicio(conn, servicio_id)
    return templates.TemplateResponse(
        request, "cfe/partials/historial_descargas.html",
        {"servicio": servicio, "descargas": descargas, "tiene_activo": tiene_activo,
         "user": user, "_toast": {"message": toast_msg, "type": toast_type}},
        status_code=status_code,
    )


# ── Renovacion de sesion (lanzador local) ──────────────────────────────────────

@router.post("/sesion/subir", include_in_schema=False)
async def subir_sesion(
    request: Request,
    x_cfe_token: str = Header("", alias="X-CFE-Token"),
    conn=Depends(get_db_connection),
):
    """
    Recibe el storage_state de MiEspacio desde el lanzador local que corre en la
    PC del usuario. NO usa sesion Azure AD: se autentica con un token compartido
    en la cabecera X-CFE-Token. El cuerpo es el JSON crudo del storage_state.
    """
    # Cota de tamano antes de leer el body: un storage_state real pesa pocos KB.
    # Evita que una peticion sin token cargue un cuerpo arbitrariamente grande.
    excede_413 = JSONResponse(status_code=413, content={"ok": False, "error": "El cuerpo excede el tamano permitido."})
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > _MAX_SESION_BODY_BYTES:
        return excede_413

    body_bytes = await request.body()
    if len(body_bytes) > _MAX_SESION_BODY_BYTES:
        return excede_413
    raw_body = body_bytes.decode("utf-8", errors="replace")
    svc = get_cfe_service()
    try:
        await svc.subir_sesion_con_token(conn, token=x_cfe_token, session_json=raw_body)
    except PermissionError as exc:
        logger.warning("cfe_subir_sesion_no_autorizado origen=%s", request.client.host if request.client else "?")
        return JSONResponse(status_code=403, content={"ok": False, "error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD guardando sesion CFE via lanzador: %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": "Error interno al guardar la sesion."})
    return JSONResponse(content={"ok": True, "mensaje": "Sesion CFE MiEspacio renovada correctamente."})


@router.get("/lanzador/descargar", include_in_schema=False)
async def descargar_lanzador_cfe(
    conn=Depends(get_db_connection),
    _=_viewer,
):
    svc = get_cfe_service()
    try:
        content, version = await svc.get_lanzador_bytes(conn)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (httpx.HTTPError, asyncpg.PostgresError) as exc:
        logger.error("Error descargando lanzador CFE de SharePoint: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo obtener el ejecutable. Intenta de nuevo.")
    filename = f"RenovarSesionCFE_{version}.exe" if version else "RenovarSesionCFE.exe"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Vista previa ──────────────────────────────────────────────────────────────

@router.get("/servicios/{servicio_id}/descargas/{descarga_id}/preview")
async def preview_descarga(
    servicio_id: UUID,
    descarga_id: UUID,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    await _get_servicio_accesible(svc, conn, servicio_id, user)
    url = await svc.get_url_preview(conn, descarga_id, servicio_id)
    if not url:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return RedirectResponse(url=url, status_code=303)


# ── Modal Excel ───────────────────────────────────────────────────────────────

@router.get("/servicios/{servicio_id}/modal-excel", response_class=HTMLResponse)
async def modal_excel(
    request: Request,
    servicio_id: UUID,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    descargas_xml = [
        d for d in await svc.db.get_descargas_por_servicio(conn, servicio_id)
        if d["tipo"] == "xml" and d["estatus"] == "completado"
    ]
    periodos = sorted({d["periodo"] for d in descargas_xml}, reverse=True)
    return templates.TemplateResponse(
        request, "cfe/partials/modal_excel.html",
        {"servicio": servicio, "periodos": periodos},
    )


# ── Excel ─────────────────────────────────────────────────────────────────────

@router.post("/servicios/{servicio_id}/excel")
async def generar_excel(
    servicio_id: UUID,
    periodos: list[str] = Form(...),
    perfil: str = Form("oym"),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    try:
        xlsx_bytes = await svc.generar_excel(conn, servicio_id, periodos, perfil)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    nombre = f"CFE_{servicio['numero_servicio']}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/servicios/{servicio_id}/zip")
async def descargar_zip_servicio(
    servicio_id: UUID,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    await _get_servicio_accesible(svc, conn, servicio_id, user)
    try:
        zip_bytes, nombre = await svc.generar_zip_servicio(conn, servicio_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("Error de SharePoint generando ZIP CFE para %s: %s", servicio_id, exc)
        raise HTTPException(status_code=503, detail="No se pudo obtener los archivos. Intenta de nuevo.") from exc
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD generando ZIP CFE para %s: %s", servicio_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al generar el ZIP.") from exc

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
