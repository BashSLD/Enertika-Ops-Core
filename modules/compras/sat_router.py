import asyncio
import logging
from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import require_module_access
from core.security import get_current_user_context
from core.timezone import now_mx
from modules.compras import sat_service, sat_db_service

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
    _=require_module_access("compras", "editor"),
):
    is_htmx = request.headers.get("hx-request")
    is_history_restore = request.headers.get("hx-history-restore-request")

    items, total = await sat_db_service.listar_inbox(conn, estado=estado, page=page)
    ultimo_job = await sat_db_service.obtener_ultimo_job(conn)

    ctx = {
        "items": items,
        "total": total,
        "page": page,
        "page_size": 50,
        "estado_filtro": estado,
        "ultimo_job": ultimo_job,
        "user": user,
        "user_name": user.get("user_name"),
        "role": user.get("role"),
        "module_roles": user.get("module_roles", {}),
    }

    if is_htmx and not is_history_restore:
        return templates.TemplateResponse(request, "compras/partials/sat_inbox_content.html", ctx)
    return templates.TemplateResponse(request, "compras/sat_inbox.html", ctx)


@router.post("/jobs", response_class=HTMLResponse)
async def iniciar_job(
    request: Request,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=require_module_access("compras", "editor"),
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

    if await sat_db_service.hay_job_activo(conn):
        return templates.TemplateResponse(
            request,
            "compras/partials/sat_job_status.html",
            {"error": "Ya hay un job activo. Espera a que termine antes de iniciar otro."},
            status_code=409,
        )

    rfc_emisor = (form.get("rfc_emisor") or "").strip() or None

    job_id = await sat_db_service.crear_job(conn, fecha_inicio, fecha_fin, user["user_db_id"])
    asyncio.create_task(sat_service.ejecutar_descarga(job_id, fecha_inicio, fecha_fin, rfc_emisor))

    job = await sat_db_service.obtener_job_status(conn, job_id)
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_job_status.html",
        {"job": job},
    )


@router.get("/jobs/banner", response_class=HTMLResponse)
async def job_banner(
    request: Request,
    conn=Depends(get_db_connection),
    _=Depends(get_current_user_context),
):
    try:
        job = await sat_db_service.obtener_ultimo_job(conn)
    except asyncpg.PostgresError:
        job = None
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_global_banner.html",
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
        job = await sat_db_service.obtener_job_status(conn, job_id)
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
    _=require_module_access("compras", "editor"),
):
    try:
        await sat_db_service.descartar_inbox_item(conn, inbox_id)
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
    items, total = await sat_db_service.listar_inbox(conn, estado=estado)
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_inbox_table.html",
        {"items": items, "total": total, "estado_filtro": estado},
    )


@router.post("/inbox/bulk-descartar", response_class=HTMLResponse)
async def bulk_descartar(
    request: Request,
    inbox_ids: list[str] = Form(default=[]),
    estado: str = Form("pendiente"),
    conn=Depends(get_db_connection),
    _=require_module_access("compras", "editor"),
):
    if not inbox_ids:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "No se seleccionaron elementos", "type": "warning"},
            status_code=200,
            headers={"HX-Reswap": "none"},
        )

    try:
        uuids = [UUID(id_str) for id_str in inbox_ids]
        count = await sat_db_service.descartar_inbox_item_bulk(conn, uuids)
    except Exception as e:
        logger.exception("Error en bulk-descartar: %s", e)
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "Error procesando descarte", "type": "error"},
            status_code=200,
            headers={"HX-Reswap": "none"},
        )

    items, total = await sat_db_service.listar_inbox(conn, estado=estado)

    table_html = templates.TemplateResponse(
        request,
        "compras/partials/sat_inbox_table.html",
        {"items": items, "total": total, "estado_filtro": estado},
    ).body.decode("utf-8")

    toast_html = templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": f"{count} elementos descartados", "type": "success"},
    ).body.decode("utf-8")

    return HTMLResponse(content=table_html + toast_html)


@router.post("/inbox/{inbox_id}/restaurar", response_class=HTMLResponse)
async def restaurar_item(
    request: Request,
    inbox_id: UUID,
    estado: str = "pendiente",
    conn=Depends(get_db_connection),
    _=require_module_access("compras", "editor"),
):
    try:
        await sat_db_service.restaurar_inbox_item(conn, inbox_id)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": str(e), "tipo": "error"},
            status_code=400,
            headers={"HX-Reswap": "none"},
        )
    except asyncpg.PostgresError:
        logger.exception("Error de BD al restaurar item %s", inbox_id)
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": "Error de base de datos. Intenta de nuevo.", "tipo": "error"},
            status_code=500,
            headers={"HX-Reswap": "none"},
        )
    items, total = await sat_db_service.listar_inbox(conn, estado=estado)
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
    _=require_module_access("compras", "editor"),
):
    if len(q.strip()) < 2:
        return HTMLResponse('<p class="text-xs text-gray-400 py-2 px-1">Escribe al menos 2 caracteres...</p>')
    results = await sat_db_service.buscar_comprobantes_match(conn, q.strip())
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_match_results.html",
        {"results": results},
    )


async def _procesar_match_unico(conn: asyncpg.Connection, inbox_id: UUID, comprobante_id: UUID, user_id: UUID):
    from modules.compras.sat_service import descargar_xml_de_inbox
    from modules.compras.xml_extractor import parse_cfdi_xml
    from modules.compras.service import ComprasService

    xml_bytes, uuid_cfdi = await descargar_xml_de_inbox(conn, inbox_id)
    cfdi = parse_cfdi_xml(xml_bytes, f"{uuid_cfdi}.xml")

    cfdi_data = {
        "uuid": cfdi.uuid,
        "emisor_rfc": cfdi.emisor_rfc,
        "emisor_nombre": cfdi.emisor_nombre,
        "total": str(cfdi.total) if cfdi.total else "0",
        "subtotal": str(cfdi.subtotal) if cfdi.subtotal else "0",
        "moneda": cfdi.moneda,
        "fecha": cfdi.fecha,
        "tipo_factura": cfdi.tipo_factura.value if cfdi.tipo_factura else "NORMAL",
        "tipo_comprobante": cfdi.tipo_comprobante,
        "metodo_pago": cfdi.metodo_pago,
        "forma_pago": cfdi.forma_pago,
        "conceptos": [c.model_dump() for c in cfdi.conceptos] if cfdi.conceptos else [],
        "relacionados": [r.model_dump() for r in cfdi.relacionados] if cfdi.relacionados else [],
    }

    compras_service = ComprasService()

    # Marcar matcheado en SAT Inbox
    await sat_db_service.marcar_matcheado(conn, inbox_id, comprobante_id)

    # Confirmar match en modulo Compras (vincula comprobante, proveedor, historial)
    async with conn.transaction():
        await compras_service.confirmar_match_xml(
            conn, cfdi_data, comprobante_id, user_id,
            guardar_relacion=True
        )

    # Copiar el XML a la carpeta de facturas en SharePoint
    from fastapi import UploadFile
    from io import BytesIO
    from starlette.datastructures import Headers

    xml_file = UploadFile(
        filename=f"{cfdi.uuid[:8]}_factura.xml",
        file=BytesIO(xml_bytes),
        headers=Headers({"content-type": "application/xml"}),
    )
    now = now_mx()
    subcarpeta = f"compras/facturas_xml/{now.strftime('%Y-%m')}"

    await compras_service.upload_archivo_sharepoint(
        conn, xml_file, subcarpeta,
        comprobante_id, "factura_xml", user_id,
        metadata_extra={
            "uuid_factura": cfdi.uuid,
            "emisor_rfc": cfdi.emisor_rfc,
            "tipo_factura": cfdi.tipo_factura.value if cfdi.tipo_factura else "NORMAL",
        }
    )


@router.post("/inbox/{inbox_id}/match", response_class=HTMLResponse)
async def confirmar_match(
    request: Request,
    inbox_id: UUID,
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=require_module_access("compras", "editor"),
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
        await _procesar_match_unico(conn, inbox_id, comprobante_id, user["user_db_id"])
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
    except Exception as e:
        logger.exception("Error inesperado procesando XML %s", inbox_id)
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"mensaje": "Error procesando XML", "tipo": "error"},
            status_code=500,
            headers={"HX-Reswap": "none"},
        )

    items, total = await sat_db_service.listar_inbox(conn, estado="pendiente")
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
    _=require_module_access("compras", "editor"),
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


@router.get("/inbox/auto-match", response_class=HTMLResponse)
async def get_auto_match(
    request: Request,
    conn=Depends(get_db_connection),
    _=require_module_access("compras", "editor"),
):
    matches = await sat_db_service.buscar_coincidencias_auto(conn)
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_auto_match_modal.html",
        {"matches": matches},
    )


@router.post("/inbox/auto-match/confirm", response_class=HTMLResponse)
async def confirm_auto_match(
    request: Request,
    matches: list[str] = Form(default=[]),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=require_module_access("compras", "editor"),
):
    if not matches:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "No se seleccionaron coincidencias", "type": "warning"},
            status_code=200,
            headers={"HX-Reswap": "none"},
        )

    user_id = user["user_db_id"]
    procesados = 0
    errores = 0

    for match_str in matches:
        try:
            inbox_id_str, comprobante_id_str = match_str.split("|")
            inbox_id = UUID(inbox_id_str)
            comprobante_id = UUID(comprobante_id_str)
            await _procesar_match_unico(conn, inbox_id, comprobante_id, user_id)
            procesados += 1
        except Exception as e:
            logger.exception("Error en auto-match para %s: %s", match_str, e)
            errores += 1

    msg = f"{procesados} coincidencias procesadas correctamente."
    if errores > 0:
        msg += f" Hubo {errores} errores (ver logs)."

    toast_type = "success" if errores == 0 else "warning"

    items, total = await sat_db_service.listar_inbox(conn, estado="pendiente")

    table_html = templates.TemplateResponse(
        request,
        "compras/partials/sat_inbox_table.html",
        {"items": items, "total": total, "estado_filtro": "pendiente"},
    ).body.decode("utf-8")

    table_oob = table_html.replace(
        'id="sat-inbox-table"',
        'id="sat-inbox-table" hx-swap-oob="outerHTML"',
        1,
    )

    toast_html = templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": msg, "type": toast_type},
    ).body.decode("utf-8")

    return HTMLResponse(content=table_oob + toast_html)
