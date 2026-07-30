# modules/cfe/router.py
from __future__ import annotations

import base64
import logging
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from core.config import settings
from core.database import get_db_connection
from core.jinja_filters import register_timezone_filters
from core.permissions import get_user_module_role, require_any_module_access, user_has_module_access
from core.security import get_current_user_context
from modules.shared.services.cfe import generar_excel_cfe_desde_uploads

from .constants import CFE_MODULE_SLUGS, CFE_PUBLIC_FORM_DEFAULTS, ZONAS_OYM
from .launcher_ticket_repository import LauncherTicketRepositoryUnavailable
from .service import CfeLauncherIntegrityError, CfeZipFaltantesError, get_cfe_service

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


def _puede_emitir_ticket_lanzador(user: dict) -> bool:
    """Limita las credenciales CFE al administrador global que ya puede gestionarlas."""
    return user.get("role") == "ADMIN"


async def _zona_selector_ctx(svc, conn, user: dict, modulo_activo: str | None) -> dict:
    """zonas_oym (botones a mostrar) + zona_propia (para resaltar 'Mi zona'
    por comparacion directa) del selector conmutable de lista_servicios.html.
    Solo aplica al contexto oym; en otros modulos el bloque ni se renderiza."""
    if modulo_activo != "oym":
        return {"zonas_oym": ZONAS_OYM, "zona_propia": None}
    zonas_oym, zona_propia = await svc.get_zonas_oym_selector(conn, user)
    return {"zonas_oym": zonas_oym, "zona_propia": zona_propia}


def _zip_faltantes_response(exc: CfeZipFaltantesError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"ok": False, "message": str(exc), "faltantes": exc.faltantes},
    )


async def _get_servicio_accesible(svc, conn, servicio_id: UUID, user: dict) -> dict:
    """Raises 404 if service not found or not visible to the user.
    oym: basta con compartir el modulo (paridad con el comportamiento previo).
    simulacion (sin oym en la interseccion): requiere ser registrador o admin de simulacion."""
    _, modulos_accesibles = _resolver_modulos(user, None)
    servicio = await svc.db.get_servicio_by_id(conn, servicio_id)
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    interseccion = set(servicio.get("modulos") or []) & set(modulos_accesibles)
    if not interseccion:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if "oym" in interseccion:
        return servicio
    # Solo queda simulacion: visibilidad estricta por registrador.
    if get_user_module_role("simulacion", user) == "admin":
        return servicio
    usuario_id = user.get("user_db_id")
    if usuario_id and await svc.db.es_registrador(conn, servicio_id, usuario_id, "simulacion"):
        return servicio
    raise HTTPException(status_code=404, detail="Servicio no encontrado")


# ── UI principal ──────────────────────────────────────────────────────────────

@router.get("/ui", response_class=HTMLResponse)
async def cfe_ui(
    request: Request,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    await svc.limpiar_errores_invalidos(conn)
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona
    )
    estado_sesion = await svc.get_estado_sesion(conn)
    is_htmx = request.headers.get("hx-request")
    is_restore = request.headers.get("hx-history-restore-request")
    ctx = {
        "servicios": servicios,
        "estado_sesion": estado_sesion,
        "modulo": modulo_activo,
        "modulos_accesibles": modulos_accesibles,
        "zona_activa": zona,
        **await _zona_selector_ctx(svc, conn, user, modulo_activo),
        "user": user,
        "user_name": user.get("user_name"),
        "role": user.get("role"),
        "module_roles": user.get("module_roles", {}),
        "ocultos_count": ocultos_count,
    }
    template = "cfe/partials/lista_servicios.html" if (is_htmx and not is_restore) else "cfe/index.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/servicios/{servicio_id}/analisis", response_class=HTMLResponse)
async def analisis_servicio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
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
        "zona_activa": zona,
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
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    _, modulos_accesibles = _resolver_modulos(user, modulo)
    # Default del <select name="zona"> del modal: resuelve la MISMA zona que el
    # usuario esta viendo ahora mismo (incluida "mi zona" -> zona propia), no el
    # query param crudo — si no, con el filtro por defecto (sin ?zona=) el select
    # cae en "Sin zona" aunque el usuario tenga zona asignada.
    zona_default_alta = None
    if "oym" in modulos_accesibles:
        svc = get_cfe_service()
        zona_default_alta, _ = await svc.resolver_filtro_visibilidad(conn, user, "oym", zona)
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_agregar_servicio.html",
        {
            "contacto_defaults": CFE_PUBLIC_FORM_DEFAULTS,
            "modulo": modulo,
            "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona,
            "zona_default_alta": zona_default_alta,
            "zonas_oym": ZONAS_OYM,
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
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    estado_sesion = await svc.get_estado_sesion(conn)
    ticket = ""
    ticket_error = ""
    renovacion_autorizada = _puede_emitir_ticket_lanzador(user)
    if (
        renovacion_autorizada
        and estado_sesion["renovacion_habilitada"]
        and estado_sesion["lanzador_disponible"]
    ):
        try:
            ticket = await svc.crear_ticket_lanzador(
                user_id=user["user_db_id"],
                user_email=user["email"],
            )
        except LauncherTicketRepositoryUnavailable as exc:
            ticket_error = str(exc)
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_renovar_sesion.html",
        {
            "estado_sesion": estado_sesion,
            "ticket": ticket,
            "ticket_error": ticket_error,
            "renovacion_autorizada": renovacion_autorizada,
            "ticket_ttl_minutos": max(
                1,
                settings.CFE_LAUNCHER_TICKET_TTL_SECONDS // 60,
            ),
            "modulo": modulo_activo,
            "zona_activa": zona,
            "user": user,
        },
        headers={"Cache-Control": "no-store"},
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
    zona: str | None = Form(default=None),
    zona_filtro: str | None = Query(default=None),
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
        _, estado = await svc.crear_servicio(
            conn, numero_servicio=numero_servicio.strip(), nombre=nombre.strip(),
            alias=alias.strip() or None, lada=lada.strip(), telefono=telefono.strip(),
            email=email.strip(), usuario_id=user["user_db_id"], modulo=modulo_guardado,
            zona=zona,
        )
        toast_msg = {
            "creado": f"Servicio {numero_servicio} registrado.",
            "modulo_agregado": f"Módulo añadido al servicio {numero_servicio} existente.",
            "visibilidad_otorgada": f"El servicio {numero_servicio} ya existía; ahora también lo verás en tu lista.",
            "ya_visible": f"El servicio {numero_servicio} ya estaba en tu lista.",
        }[estado]
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD creando servicio CFE: {exc}")
        toast_msg = "Error interno al registrar el servicio."
        toast_type = "error"
        status_code = 500
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona_filtro
    )
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona_filtro,
            **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
            "ocultos_count": ocultos_count,
        },
        status_code=status_code,
    )


@router.post("/servicios/bulk", response_class=HTMLResponse)
async def crear_servicios_bulk(
    request: Request,
    numero_servicios: list[str] = Form(default=[]),
    nombres: list[str] = Form(default=[]),
    aliases: list[str] = Form(default=[]),
    modulo_form: str = Form("oym", alias="modulo"),
    lada: str = Form(CFE_PUBLIC_FORM_DEFAULTS["lada"]),
    telefono: str = Form(CFE_PUBLIC_FORM_DEFAULTS["telefono"]),
    email: str = Form(CFE_PUBLIC_FORM_DEFAULTS["email"]),
    zona: str | None = Form(default=None),
    zona_filtro: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    if modulo_form not in CFE_MODULE_SLUGS:
        modulo_form = CFE_MODULE_SLUGS[0]
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo_form)
    modulo_guardado = modulo_activo or modulo_form

    lada = lada.strip()
    telefono = telefono.strip()
    email = email.strip()
    aliases = list(aliases) + [""] * max(0, len(numero_servicios) - len(aliases))
    resultados = []
    for numero, nombre, alias_raw in zip(numero_servicios, nombres, aliases):
        alias = alias_raw.strip() or None
        numero = numero.strip()
        nombre = nombre.strip()
        if not numero or not nombre:
            resultados.append({"numero": numero, "nombre": nombre, "ok": False, "error": "Número y nombre son requeridos."})
            continue
        try:
            _, estado = await svc.crear_servicio(
                conn,
                numero_servicio=numero,
                nombre=nombre,
                alias=alias,
                lada=lada,
                telefono=telefono,
                email=email,
                usuario_id=user["user_db_id"],
                modulo=modulo_guardado,
                zona=zona,
            )
            msg = {
                "creado": "Registrado.",
                "modulo_agregado": "Módulo añadido (ya existía).",
                "visibilidad_otorgada": "Ya existía; ahora lo ves.",
                "ya_visible": "Ya estaba en tu lista.",
            }[estado]
            resultados.append({"numero": numero, "nombre": nombre, "ok": True, "msg": msg})
        except ValueError as exc:
            resultados.append({"numero": numero, "nombre": nombre, "ok": False, "error": str(exc)})
        except asyncpg.PostgresError as exc:
            logger.error("Error de BD en alta masiva CFE: %s", exc)
            resultados.append({"numero": numero, "nombre": nombre, "ok": False, "error": "Error interno al registrar."})

    total_ok = sum(1 for r in resultados if r["ok"])
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona_filtro
    )
    estado_sesion = await svc.get_estado_sesion(conn)
    return templates.TemplateResponse(
        request,
        "cfe/partials/bulk_resultado.html",
        {
            "resultados": resultados,
            "total_ok": total_ok,
            "servicios": servicios,
            "estado_sesion": estado_sesion,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona_filtro,
            **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "user": user,
            "user_name": user.get("user_name"),
            "role": user.get("role"),
            "module_roles": user.get("module_roles", {}),
            "ocultos_count": ocultos_count,
        },
    )


# ── Ocultos (preferencia personal, no borra nada) ──────────────────────────────

@router.post("/servicios/{servicio_id}/ocultar", response_class=HTMLResponse)
async def ocultar_servicio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    toast_type = "success"
    toast_msg = ""
    status_code = 200
    try:
        await svc.ocultar_servicio(
            conn, servicio, user["user_db_id"],
            modulos_usuario=[modulo_activo] if modulo_activo else modulos_accesibles,
        )
        toast_msg = "Servicio ocultado de tu lista. Puedes mostrarlo de nuevo desde \"Servicios ocultos\"."
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD ocultando servicio CFE %s: %s", servicio_id, exc)
        toast_msg = "Error interno al ocultar el servicio."
        toast_type = "error"
        status_code = 500
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona
    )
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios, "modulo": modulo_activo, "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona, **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "user": user, "_toast": {"message": toast_msg, "type": toast_type},
            "ocultos_count": ocultos_count,
        },
        status_code=status_code,
    )


@router.get("/ui/modal-ocultos", response_class=HTMLResponse)
async def modal_ocultos(
    request: Request,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    modulos_ctx = [modulo_activo] if modulo_activo else modulos_accesibles
    ocultos = await svc.listar_servicios_ocultos(conn, user["user_db_id"], modulos_ctx)
    return templates.TemplateResponse(
        request, "cfe/partials/modal_ocultos.html",
        {"ocultos": ocultos, "modulo": modulo_activo, "zona_activa": zona, "user": user},
    )


@router.post("/servicios/{servicio_id}/mostrar", response_class=HTMLResponse)
async def mostrar_servicio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    modulos_ctx = [modulo_activo] if modulo_activo else modulos_accesibles
    try:
        await svc.mostrar_servicio(conn, servicio_id, user["user_db_id"], modulos_ctx)
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD restaurando servicio CFE %s: %s", servicio_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al restaurar el servicio.")

    ocultos = await svc.listar_servicios_ocultos(conn, user["user_db_id"], modulos_ctx)
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona
    )
    return templates.TemplateResponse(
        request, "cfe/partials/modal_ocultos.html",
        {
            "ocultos": ocultos, "modulo": modulo_activo, "zona_activa": zona, "user": user,
            "_toast": {"message": "Servicio visible de nuevo.", "type": "success"},
            "servicios": servicios, "modulos_accesibles": modulos_accesibles,
            **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "ocultos_count": ocultos_count,
        },
    )


@router.get("/servicios/{servicio_id}/modal-editar", response_class=HTMLResponse)
async def modal_editar_servicio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    if servicio.get("miespacio_estatus") != "error":
        raise HTTPException(status_code=400, detail="Solo se puede editar un servicio con error de registro.")
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_editar_servicio.html",
        {"servicio": servicio, "modulo": modulo_activo, "zona_activa": zona, "user": user},
    )


@router.post("/servicios/{servicio_id}/editar", response_class=HTMLResponse)
async def editar_servicio(
    request: Request,
    servicio_id: UUID,
    numero_servicio: str = Form(...),
    nombre: str = Form(...),
    alias: str = Form(""),
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
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
        toast_msg, _servicio = await svc.editar_servicio(
            conn, servicio_id, numero_servicio=numero_servicio, nombre=nombre, alias=alias,
        )
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error(f"Error de BD editando servicio CFE {servicio_id}: {exc}")
        toast_msg = "Error interno al editar el servicio."
        toast_type = "error"
        status_code = 500
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona
    )
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona,
            **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
            "ocultos_count": ocultos_count,
        },
        status_code=status_code,
    )


@router.get("/servicios/{servicio_id}/modal-detalle-miespacio", response_class=HTMLResponse)
async def modal_detalle_miespacio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    return templates.TemplateResponse(
        request,
        "cfe/partials/modal_detalle_miespacio.html",
        {"servicio": servicio, "modulo": modulo_activo, "zona_activa": zona, "user": user},
    )


@router.post("/servicios/{servicio_id}/registrar-manual", response_class=HTMLResponse)
async def registrar_manual(
    request: Request,
    servicio_id: UUID,
    total: str = Form(...),
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
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
        toast_msg, _servicio = await svc.iniciar_registro_manual(conn, servicio_id, total)
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD en registro manual CFE para %s: %s", servicio_id, exc)
        toast_msg = "Error interno al encolar el registro."
        toast_type = "error"
        status_code = 500
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona
    )
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona,
            **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
            "ocultos_count": ocultos_count,
        },
        status_code=status_code,
    )


@router.post("/servicios/{servicio_id}/reintentar-alta", response_class=HTMLResponse)
async def reintentar_alta_miespacio(
    request: Request,
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
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
    servicios, ocultos_count = await svc.listar_servicios_visibles(
        conn, user, modulo_activo, modulos_accesibles, zona
    )
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona,
            **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
            "ocultos_count": ocultos_count,
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
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    await svc.limpiar_errores_invalidos(conn, servicio_id)
    descargas = await svc.db.get_descargas_por_servicio(conn, servicio_id)
    tiene_activo = any(d["estatus"] in ("pendiente", "descargando") for d in descargas)
    return templates.TemplateResponse(
        request, "cfe/partials/historial_descargas.html",
        {"servicio": servicio, "descargas": descargas,
         "tiene_activo": tiene_activo, "modulo": modulo_activo, "user": user},
    )


@router.post("/servicios/{servicio_id}/descargar", response_class=HTMLResponse)
async def iniciar_descarga(
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
         "modulo": modulo_activo, "user": user, "_toast": {"message": toast_msg, "type": toast_type}},
        status_code=status_code,
    )


@router.post("/servicios/descargar-todos", response_class=HTMLResponse)
async def descargar_todos(
    request: Request,
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    modulos = [modulo_activo] if modulo_activo else modulos_accesibles
    zona_filtro, servicio_ids = await svc.resolver_filtro_visibilidad(conn, user, modulo_activo, zona)
    toast_type = "success"
    toast_msg = ""
    status_code = 200
    try:
        encolados, omitidos = await svc.iniciar_descarga_masiva(
            conn, modulos=modulos, usuario_id=user["user_db_id"],
            zona=zona_filtro, servicio_ids=servicio_ids,
        )
        if encolados:
            toast_msg = f"{encolados} servicio(s) encolado(s) para descarga del último recibo."
            if omitidos:
                toast_msg += f" {omitidos} ya tenían una descarga en curso."
        elif omitidos:
            toast_msg = f"Los {omitidos} servicio(s) registrado(s) ya tienen una descarga en curso."
            toast_type = "info"
        else:
            toast_msg = "No hay servicios registrados en MiEspacio para descargar."
            toast_type = "error"
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD encolando descarga masiva CFE: %s", exc)
        toast_msg = "Error interno al encolar las descargas."
        toast_type = "error"
        status_code = 500
    excluir_ids = await svc.resolver_ocultos(conn, user, modulos)
    servicios = await svc.listar_servicios(
        conn, modulos=modulos, zona=zona_filtro, servicio_ids=servicio_ids,
        excluir_ids=excluir_ids,
    )
    estado_sesion = await svc.get_estado_sesion(conn)
    return templates.TemplateResponse(
        request, "cfe/partials/lista_servicios.html",
        {
            "servicios": servicios,
            "estado_sesion": estado_sesion,
            "modulo": modulo_activo,
            "modulos_accesibles": modulos_accesibles,
            "zona_activa": zona,
            **await _zona_selector_ctx(svc, conn, user, modulo_activo),
            "user": user,
            "_toast": {"message": toast_msg, "type": toast_type},
            "ocultos_count": len(excluir_ids or []),
        },
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
    zona: str | None = Query(default=None),
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
            "zona_activa": zona,
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
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
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
         "modulo": modulo_activo, "user": user, "_toast": {"message": toast_msg, "type": toast_type}},
        status_code=status_code,
    )


@router.post("/servicios/{servicio_id}/descargas/{periodo}/reintentar-xml", response_class=HTMLResponse)
async def reintentar_xml(
    request: Request,
    servicio_id: UUID,
    periodo: str,
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    tiene_activo = False
    toast_type = "info"
    toast_msg = ""
    status_code = 200
    try:
        toast_msg, servicio = await svc.iniciar_descarga_xml(
            conn, servicio_id, periodo, user["user_db_id"]
        )
        tiene_activo = True
    except ValueError as exc:
        toast_msg = str(exc)
        toast_type = "error"
        status_code = 400
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD encolando XML CFE para %s/%s: %s", servicio_id, periodo, exc)
        toast_msg = "Error interno al encolar la descarga del XML."
        toast_type = "error"
        status_code = 500
    descargas = await svc.db.get_descargas_por_servicio(conn, servicio_id)
    return templates.TemplateResponse(
        request, "cfe/partials/historial_descargas.html",
        {"servicio": servicio, "descargas": descargas, "tiene_activo": tiene_activo,
         "modulo": modulo_activo, "user": user, "_toast": {"message": toast_msg, "type": toast_type}},
        status_code=status_code,
    )


# ── Renovacion de sesion (lanzador local) ──────────────────────────────────────

@router.post("/sesion/iniciar", include_in_schema=False)
async def iniciar_renovacion_sesion(
    request: Request,
    x_cfe_ticket: str = Header("", alias="X-CFE-Ticket"),
    conn=Depends(get_db_connection),
):
    """Canjea un ticket efimero por credenciales y un grant de subida."""
    svc = get_cfe_service()
    try:
        datos = await svc.iniciar_renovacion_con_ticket(conn, ticket=x_cfe_ticket)
    except LauncherTicketRepositoryUnavailable as exc:
        logger.error("Autorizacion temporal CFE no disponible: %s", exc)
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})
    except PermissionError as exc:
        logger.warning(
            "cfe_iniciar_sesion_no_autorizado origen=%s",
            request.client.host if request.client else "?",
        )
        return JSONResponse(status_code=403, content={"ok": False, "error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD iniciando renovacion CFE: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Error interno al iniciar la renovación."},
        )
    return JSONResponse(
        content={"ok": True, **datos},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/sesion/subir", include_in_schema=False)
async def subir_sesion(
    request: Request,
    x_cfe_grant: str = Header("", alias="X-CFE-Grant"),
    conn=Depends(get_db_connection),
):
    """
    Recibe el storage_state de MiEspacio desde el lanzador local que corre en la
    PC del usuario. Se autentica con un grant efimero y de un solo uso generado
    durante /sesion/iniciar. El cuerpo es el JSON crudo del storage_state.
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
        await svc.subir_sesion_con_grant(
            conn,
            upload_grant=x_cfe_grant,
            session_json=raw_body,
        )
    except LauncherTicketRepositoryUnavailable as exc:
        logger.error("Autorizacion temporal CFE no disponible: %s", exc)
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})
    except PermissionError as exc:
        logger.warning("cfe_subir_sesion_no_autorizado origen=%s", request.client.host if request.client else "?")
        return JSONResponse(status_code=403, content={"ok": False, "error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD guardando sesion CFE via lanzador: %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": "Error interno al guardar la sesion."})
    return JSONResponse(content={"ok": True, "mensaje": "Sesion CFE MiEspacio renovada correctamente."})


@router.get("/sesion/credenciales", include_in_schema=False)
async def credenciales_lanzador_legacy():
    """Retira explicitamente el endpoint del token compartido."""
    return JSONResponse(
        status_code=410,
        content={
            "ok": False,
            "error": "Este lanzador ya no es compatible. Descarga la versión actual.",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/lanzador/descargar", include_in_schema=False)
async def descargar_lanzador_cfe(
    conn=Depends(get_db_connection),
    _=_viewer,
):
    svc = get_cfe_service()
    try:
        content, version, sha256_hex = await svc.get_lanzador_bytes(conn)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CfeLauncherIntegrityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (httpx.HTTPError, asyncpg.PostgresError) as exc:
        logger.error("Error descargando lanzador CFE de SharePoint: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo obtener el ejecutable. Intenta de nuevo.")
    filename = f"RenovarSesionCFE_{version}.exe" if version else "RenovarSesionCFE.exe"
    digest_b64 = base64.b64encode(bytes.fromhex(sha256_hex)).decode("ascii")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "Digest": f"sha-256={digest_b64}",
            "X-Content-SHA256": sha256_hex,
        },
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
    modulo: str | None = Query(default=None),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    servicio = await _get_servicio_accesible(svc, conn, servicio_id, user)
    descargas_xml = [
        d for d in await svc.db.get_descargas_por_servicio(conn, servicio_id)
        if d["tipo"] == "xml" and d["estatus"] == "completado"
    ]
    periodos = sorted({d["periodo"] for d in descargas_xml}, reverse=True)
    return templates.TemplateResponse(
        request, "cfe/partials/modal_excel.html",
        {"servicio": servicio, "periodos": periodos, "perfil": modulo_activo or "oym"},
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


@router.get("/servicios/zip-global")
async def descargar_zip_global(
    modulo: str | None = Query(default=None),
    zona: str | None = Query(default=None),
    permitir_incompleto: bool = Query(default=False),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, modulos_accesibles = _resolver_modulos(user, modulo)
    modulos = [modulo_activo] if modulo_activo else modulos_accesibles
    zona_filtro, servicio_ids = await svc.resolver_filtro_visibilidad(conn, user, modulo_activo, zona)
    try:
        zip_bytes, nombre = await svc.generar_zip_global(
            conn, modulos=modulos, zona=zona_filtro,
            servicio_ids=servicio_ids, perfil_slug=modulo_activo or "oym",
            permitir_incompleto=permitir_incompleto,
        )
    except CfeZipFaltantesError as exc:
        return _zip_faltantes_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("Error de SharePoint generando ZIP global CFE: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo obtener los archivos. Intenta de nuevo.") from exc
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD generando ZIP global CFE: %s", exc)
        raise HTTPException(status_code=500, detail="Error interno al generar el ZIP.") from exc

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/servicios/{servicio_id}/zip")
async def descargar_zip_servicio(
    servicio_id: UUID,
    modulo: str | None = Query(default=None),
    permitir_incompleto: bool = Query(default=False),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=_viewer,
):
    svc = get_cfe_service()
    modulo_activo, _ = _resolver_modulos(user, modulo)
    await _get_servicio_accesible(svc, conn, servicio_id, user)
    try:
        zip_bytes, nombre = await svc.generar_zip_servicio(
            conn, servicio_id, perfil_slug=modulo_activo or "oym",
            permitir_incompleto=permitir_incompleto,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CfeZipFaltantesError as exc:
        return _zip_faltantes_response(exc)
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
