import asyncio
import logging
from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import require_module_access
from core.security import get_current_user_context
from modules.compras import sat_service
from modules.compras import sat_db_service

logger = logging.getLogger("ComprasSATRouter")

router = APIRouter(prefix="/compras/sat", tags=["SAT Inbox"])

templates = Jinja2Templates(directory="templates")


@router.get("/ui", response_class=HTMLResponse)
async def sat_inbox_ui(
    request: Request,
    page: int = 1,
    estado: str = "pendiente",
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=Depends(require_module_access("compras", "editor")),
):
    is_htmx = request.headers.get("hx-request")
    is_history_restore = request.headers.get("hx-history-restore-request")

    items, total = await sat_service.listar_inbox(conn, estado=estado, page=page)
    ultimo_job = await sat_service.obtener_ultimo_job(conn)

    ctx = {
        "items": items,
        "total": total,
        "page": page,
        "page_size": 50,
        "estado_filtro": estado,
        "ultimo_job": ultimo_job,
        "user": user,
    }

    if is_htmx and not is_history_restore:
        return templates.TemplateResponse(request, "compras/sat_inbox.html", ctx)
    return templates.TemplateResponse(request, "compras/sat_inbox.html", {**ctx, "full_page": True})


@router.post("/jobs", response_class=HTMLResponse)
async def iniciar_job(
    request: Request,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=Depends(require_module_access("compras", "editor")),
):
    form = await request.form()
    try:
        fecha_inicio = date.fromisoformat(form.get("fecha_inicio", ""))
        fecha_fin = date.fromisoformat(form.get("fecha_fin", ""))
    except ValueError:
        return templates.TemplateResponse(
            request,
            "compras/partials/sat_job_status.html",
            {"error": "Fechas invalidas. Usa el formato YYYY-MM-DD."},
            status_code=400,
        )

    if fecha_fin < fecha_inicio:
        return templates.TemplateResponse(
            request,
            "compras/partials/sat_job_status.html",
            {"error": "La fecha fin no puede ser anterior a la fecha inicio."},
            status_code=400,
        )

    if await sat_service.hay_job_activo(conn):
        return templates.TemplateResponse(
            request,
            "compras/partials/sat_job_status.html",
            {"error": "Ya hay un job activo. Espera a que termine antes de iniciar otro."},
            status_code=409,
        )

    job_id = await sat_service.crear_job(conn, fecha_inicio, fecha_fin, user["user_db_id"])
    asyncio.create_task(sat_service.ejecutar_descarga(job_id, fecha_inicio, fecha_fin))

    job = await sat_service.obtener_job_status(conn, job_id)
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_job_status.html",
        {"job": job},
    )


@router.get("/jobs/{job_id}/status", response_class=HTMLResponse)
async def job_status(
    request: Request,
    job_id: UUID,
    conn=Depends(get_db_connection),
    _=Depends(get_current_user_context),
):
    try:
        job = await sat_service.obtener_job_status(conn, job_id)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "compras/partials/sat_job_status.html",
            {"error": "Job no encontrado."},
            status_code=404,
        )
    except asyncpg.PostgresError:
        logger.exception("Error de BD al obtener estado del job %s", job_id)
        return templates.TemplateResponse(
            request,
            "compras/partials/sat_job_status.html",
            {"error": "Error de base de datos. Intenta de nuevo."},
            status_code=500,
        )
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_job_status.html",
        {"job": job},
    )


@router.post("/inbox/{inbox_id}/descartar", response_class=HTMLResponse)
async def descartar_item(
    request: Request,
    inbox_id: UUID,
    estado: str = "pendiente",
    conn=Depends(get_db_connection),
    _=Depends(require_module_access("compras", "editor")),
):
    try:
        await sat_service.descartar_inbox_item(conn, inbox_id)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": str(e), "tipo": "error"},
            status_code=404,
            headers={"HX-Reswap": "none"},
        )
    except asyncpg.PostgresError:
        logger.exception("Error de BD al descartar item %s", inbox_id)
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": "Error de base de datos. Intenta de nuevo.", "tipo": "error"},
            status_code=500,
            headers={"HX-Reswap": "none"},
        )
    items, total = await sat_service.listar_inbox(conn, estado=estado)
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_inbox_table.html",
        {"items": items, "total": total, "estado_filtro": estado},
    )


@router.get("/buscar-comprobantes", response_class=HTMLResponse)
async def buscar_comprobantes(
    request: Request,
    q: str = "",
    conn=Depends(get_db_connection),
    _=Depends(require_module_access("compras", "editor")),
):
    if len(q.strip()) < 2:
        return HTMLResponse('<p class="text-xs text-gray-400 py-2 px-1">Escribe al menos 2 caracteres...</p>')
    results = await sat_service.buscar_comprobantes_match(conn, q.strip())
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_match_results.html",
        {"results": results},
    )


@router.post("/inbox/{inbox_id}/match", response_class=HTMLResponse)
async def confirmar_match(
    request: Request,
    inbox_id: UUID,
    conn=Depends(get_db_connection),
    _=Depends(require_module_access("compras", "editor")),
):
    form = await request.form()
    comprobante_id_str = (form.get("comprobante_id") or "").strip()
    try:
        comprobante_id = UUID(comprobante_id_str)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": "Selecciona un comprobante antes de confirmar", "tipo": "error"},
            status_code=400,
            headers={"HX-Reswap": "none"},
        )

    try:
        await sat_service.marcar_matcheado(conn, inbox_id, comprobante_id)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": str(e), "tipo": "error"},
            status_code=400,
            headers={"HX-Reswap": "none"},
        )
    except asyncpg.PostgresError:
        logger.exception("Error de BD al confirmar match inbox %s", inbox_id)
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": "Error de base de datos. Intenta de nuevo.", "tipo": "error"},
            status_code=500,
            headers={"HX-Reswap": "none"},
        )

    items, total = await sat_service.listar_inbox(conn, estado="pendiente")
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_inbox_table.html",
        {"items": items, "total": total, "estado_filtro": "pendiente"},
    )


@router.post("/inbox/{inbox_id}/procesar", response_class=HTMLResponse)
async def procesar_item(
    request: Request,
    inbox_id: UUID,
    conn=Depends(get_db_connection),
    _=Depends(require_module_access("compras", "editor")),
):
    try:
        cfdi = await sat_service.obtener_cfdi_inbox(conn, inbox_id)
        tipo = cfdi.tipo_factura.value if cfdi.tipo_factura else "NORMAL"
        if tipo == "CIERRE_ANTICIPO":
            comprobantes = await sat_db_service.listar_comprobantes_anticipo(conn, cfdi.emisor_rfc)
        else:
            comprobantes = await sat_db_service.listar_comprobantes_pendientes(conn)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": str(e), "tipo": "error"},
            status_code=400,
            headers={"HX-Reswap": "none"},
        )
    except asyncpg.PostgresError:
        logger.exception("Error de BD al procesar inbox item %s", inbox_id)
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": "Error de base de datos. Intenta de nuevo.", "tipo": "error"},
            status_code=500,
            headers={"HX-Reswap": "none"},
        )

    return templates.TemplateResponse(
        request,
        "compras/partials/sat_match_modal.html",
        {"cfdi": cfdi, "inbox_id": inbox_id, "comprobantes": comprobantes},
    )
