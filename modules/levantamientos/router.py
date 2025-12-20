from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from core.database import get_db_connection

router = APIRouter(prefix="/levantamientos", tags=["Módulo Levantamientos"])
templates = Jinja2Templates(directory="templates")

class LevantamientoService:
    async def get_kanban_data(self, conn) -> dict:
        # Consulta mejorada con JOINs para obtener info de técnico y jefe (Task Picking logic)
        # Usamos DISTINCT ON para evitar duplicados si hay múltiples sitios/levantamientos por oportunidad.
        # Priorizamos mostrar la info del primer levantamiento encontrado.
        query = """
            SELECT DISTINCT ON (op.id_oportunidad)
                   op.id_oportunidad, op.titulo_proyecto, op.nombre_proyecto, 
                   op.cliente_nombre, op.direccion_obra, op.fecha_solicitud, 
                   op.status_global, op.cantidad_sitios, op.prioridad,
                   -- Info Técnico y Area (Join anidado)
                   u_tec.nombre as tecnico_nombre,
                   perm_tec.departamento_rol as tecnico_area,
                   u_jefe.nombre as jefe_nombre
            FROM tb_oportunidades op
            -- Joins para llegar al técnico asignado en tb_levantamientos
            LEFT JOIN tb_sitios_oportunidad s ON s.id_oportunidad = op.id_oportunidad
            LEFT JOIN tb_levantamientos l ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT JOIN tb_permisos_usuarios perm_tec ON perm_tec.usuario_id = u_tec.id_usuario
            LEFT JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            
            WHERE op.tipo_solicitud = 'SOLICITUD DE LEVANTAMIENTO'
            AND op.status_global NOT IN ('Cancelado', 'Perdida')
            ORDER BY op.id_oportunidad, op.prioridad DESC, op.fecha_solicitud ASC
        """
        rows = await conn.fetch(query)
        kanban = {"pendientes": [], "agendados": [], "realizados": []}
        
        for row in rows:
            item = dict(row)
            st = item['status_global']
            if st == 'Pendiente': kanban['pendientes'].append(item)
            elif st == 'Agendado': kanban['agendados'].append(item)
            elif st in ['Realizado', 'Entregado']: kanban['realizados'].append(item)
            else: kanban['pendientes'].append(item)
        return kanban

    async def mover_tarjeta(self, conn, id_oportunidad: UUID, nuevo_status: str):
        validos = ['Pendiente', 'Agendado', 'Realizado', 'Entregado']
        if nuevo_status not in validos: raise ValueError(f"Estado inválido: {nuevo_status}")
        await conn.execute("UPDATE tb_oportunidades SET status_global = $1 WHERE id_oportunidad = $2", nuevo_status, id_oportunidad)

def get_service(): return LevantamientoService()

from core.security import get_current_user_context

@router.get("/ui", include_in_schema=False)
async def get_levantamientos_ui(
    request: Request,
    context = Depends(get_current_user_context)
):
    return templates.TemplateResponse("levantamientos/dashboard.html", {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role")
    })

@router.get("/partials/kanban", include_in_schema=False)
async def get_kanban_partial(request: Request, conn=Depends(get_db_connection), service: LevantamientoService=Depends(get_service)):
    data = await service.get_kanban_data(conn)
    return templates.TemplateResponse("levantamientos/partials/kanban.html", 
        {"request": request, "pendientes": data['pendientes'], "agendados": data['agendados'], "realizados": data['realizados']})

@router.post("/move/{id_oportunidad}")
async def mover_tarjeta_endpoint(request: Request, id_oportunidad: UUID, status: str = Form(...), conn=Depends(get_db_connection), service: LevantamientoService=Depends(get_service)):
    try:
        await service.mover_tarjeta(conn, id_oportunidad, status)
        # Retorna el tablero actualizado automáticamente
        return HTMLResponse(status_code=200, headers={"HX-Trigger": "reloadKanban"}) 
    except Exception as e:
        return HTMLResponse(f"<div class='text-red-500'>Error: {e}</div>", status_code=500)