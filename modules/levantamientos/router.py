"""
Router del Módulo Levantamientos
"""

from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List, Optional
from uuid import UUID
from datetime import datetime

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access

# Database connection
from core.database import get_db_connection

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/levantamientos",
    tags=["Módulo Levantamientos"]
)

# ========================================
# CAPA DE SERVICIO (Service Layer)
# ========================================
class LevantamientoService:
    """
    Lógica de negocio del módulo levantamientos.
    
    Maneja:
    - Sistema Kanban de oportunidades
    - Queries complejas con JOINs a múltiples tablas
    - Lógica de cambio de estado de tarjetas
    """
    
    async def get_kanban_data(self, conn) -> dict:
        """
        Obtiene datos del tablero Kanban desde la BD.
        
        Query compleja con JOINs para obtener info de técnico y jefe.
        Usa DISTINCT ON para evitar duplicados si hay múltiples sitios/levantamientos.
        """
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
            -- Join para filtrar por tipo de solicitud
            JOIN tb_cat_tipos_solicitud tipo_cat ON op.id_tipo_solicitud = tipo_cat.id
            -- Joins para llegar al técnico asignado en tb_levantamientos
            LEFT JOIN tb_sitios_oportunidad s ON s.id_oportunidad = op.id_oportunidad
            LEFT JOIN tb_levantamientos l ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT JOIN tb_permisos_usuarios perm_tec ON perm_tec.usuario_id = u_tec.id_usuario
            LEFT JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            
            WHERE tipo_cat.codigo_interno = 'LEVANTAMIENTO'
            AND op.status_global NOT IN ('Cancelado', 'Perdida')
            ORDER BY op.id_oportunidad, op.prioridad DESC, op.fecha_solicitud ASC
        """
        rows = await conn.fetch(query)
        
        # Organizar en columnas del Kanban
        kanban = {"pendientes": [], "agendados": [], "realizados": []}
        
        for row in rows:
            item = dict(row)
            st = item['status_global']
            if st == 'Pendiente':
                kanban['pendientes'].append(item)
            elif st == 'Agendado':
                kanban['agendados'].append(item)
            elif st in ['Realizado', 'Entregado']:
                kanban['realizados'].append(item)
            else:
                kanban['pendientes'].append(item)
        
        return kanban

    async def mover_tarjeta(self, conn, id_oportunidad: UUID, nuevo_status: str):
        """
        Mueve una tarjeta entre columnas del Kanban.
        
        Valida que el nuevo status sea válido y actualiza en BD.
        """
        validos = ['Pendiente', 'Agendado', 'Realizado', 'Entregado']
        if nuevo_status not in validos:
            raise ValueError(f"Estado inválido: {nuevo_status}")
        
        await conn.execute(
            "UPDATE tb_oportunidades SET status_global = $1 WHERE id_oportunidad = $2",
            nuevo_status,
            id_oportunidad
        )

def get_service():
    """Dependencia para inyectar la capa de servicio."""
    return LevantamientoService()

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.get("/ui", include_in_schema=False)
async def get_levantamientos_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos")
):
    """
    Dashboard principal del módulo levantamientos con tablero Kanban.
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna partial del Kanban
    - Si es carga directa (F5/URL): retorna dashboard completo
    """
    # HTMX Detection
    if request.headers.get("hx-request"):
        # Carga parcial desde sidebar
        return templates.TemplateResponse("levantamientos/partials/kanban.html", {
            "request": request,
            "pendientes": [],
            "agendados": [],
            "realizados": []
        })
    else:
        # Carga completa de página
        return templates.TemplateResponse("levantamientos/dashboard.html", {
            "request": request,
            "user_name": context.get("user_name"),
            "role": context.get("role"),
            "module_roles": context.get("module_roles", {}),
            "current_module_role": context.get("module_roles", {}).get("levantamientos", "viewer")
        })

# ========================================
# ENDPOINTS PARCIALES (HTMX)
# ========================================
@router.get("/partials/kanban", include_in_schema=False)
async def get_kanban_partial(
    request: Request,
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service)
):
    """Partial: Tablero Kanban con datos reales de BD."""
    data = await service.get_kanban_data(conn)
    return templates.TemplateResponse("levantamientos/partials/kanban.html", {
        "request": request,
        "pendientes": data['pendientes'],
        "agendados": data['agendados'],
        "realizados": data['realizados']
    })

# ========================================
# ENDPOINTS DE API (Acciones del Kanban)
# ========================================
@router.post("/move/{id_oportunidad}")
async def mover_tarjeta_endpoint(
    request: Request,
    id_oportunidad: UUID,
    status: str = Form(...),
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service)
):
    """API: Mueve una tarjeta entre columnas del Kanban."""
    try:
        await service.mover_tarjeta(conn, id_oportunidad, status)
        # Retorna success y dispara recarga del Kanban
        return HTMLResponse(
            status_code=200,
            headers={"HX-Trigger": "reloadKanban"}
        )
    except Exception as e:
        return HTMLResponse(
            f"<div class='text-red-500'>Error: {e}</div>",
            status_code=500
        )