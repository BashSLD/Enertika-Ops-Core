# Archivo: modules/simulacion/router.py

from fastapi import APIRouter, Depends, status, HTTPException
from typing import List
from datetime import datetime
from uuid import UUID

# Importamos los modelos Pydantic
from .schemas import SimulacionCreate, SimulacionUpdate, SimulacionRead
# Importamos la conexión (la cual asumimos funcionará pronto)
# Importamos los modelos Pydantic
from .schemas import SimulacionCreate, SimulacionUpdate, SimulacionRead
# Importamos la conexión (la cual asumimos funcionará pronto)
from core.database import get_db_connection
from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/simulacion",
    tags=["Módulo Simulación"],
    # Se asumiría una dependencia para verificar rol Simulación
)

# --- Capa de Servicio (Service Layer) ---

class SimulacionService:
    """Maneja la lógica de la cola de trabajo y la validación de KWp."""

    # Simulación de la función de lectura (Dashboard)
    async def get_queue(self, conn) -> List[SimulacionRead]:
        """Obtiene la lista completa o filtrada de tareas para el Dashboard."""
        # Query de ejemplo: SELECT * FROM tb_simulaciones_trabajo ORDER BY fecha_solicitud
        # Esto retornaría una lista de SimulacionRead
        return [] # Retorno vacío hasta que la DB funcione

    async def update_simulacion(self, conn, simulacion_id: UUID, data: SimulacionUpdate) -> SimulacionRead:
        """
        Actualiza una tarea y aplica la validación de la Potencia Simulada (KWp).
        """
        # --- REGLA DE NEGOCIO CRÍTICA ---
        if data.status_simulacion == "Entregado":
            if data.potencia_simulada_kwp is None or data.potencia_simulada_kwp <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El dato CRÍTICO 'Potencia Simulada (KWp)' DEBE ser capturado para marcar como Entregado."
                )
            
            # Si se marca como entregado, se registra la fecha real
            data.fecha_entrega_real = datetime.now()
        # ----------------------------------

        # LÓGICA DE ACTUALIZACIÓN DE DB AQUÍ (usando asyncpg y conn)
        # await conn.execute(UPDATE_QUERY, data.potencia_simulada_kwp, ...)

        # Simulación de respuesta de la DB
        return SimulacionRead(
            id_simulacion=simulacion_id,
            id_oportunidad=data.id_oportunidad or UUID('00000000-0000-0000-0000-000000000000'),
            tecnico_asignado_id=data.tecnico_asignado_id,
            fecha_solicitud=datetime.now(),
            status_simulacion=data.status_simulacion,
            potencia_simulada_kwp=data.potencia_simulada_kwp
        )


def get_simulacion_service():
    """Dependencia para inyectar la capa de servicio."""
    return SimulacionService()
def get_simulacion_service():
    """Dependencia para inyectar la capa de servicio."""
    return SimulacionService()

# ----------------------------------------
# ENDPOINTS DE UI (JINJA2/HTMX)
# ----------------------------------------

@router.get("/ui", include_in_schema=False)
async def get_simulacion_ui(request: Request):
    """
    Renderiza la vista inicial del Módulo Simulación (Dashboard de cola de trabajo).
    """
    return templates.TemplateResponse(
        "simulacion/dashboard.html",
        {"request": request, "page_title": "Módulo Simulación: Cola de Trabajo"}
    )

@router.get("/", response_model=List[SimulacionRead])
async def get_simulacion_queue(
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection) # Inyectamos la conexión activa
):
    """Dashboard: Muestra la cola de trabajo y el estado de las simulaciones."""
    # Nota: get_db_connection retorna un Context Manager, necesitas adaptarlo si usas Depends.
    # Alternativa simple: async with get_db_connection() as conn:
    return await service.get_queue(conn)


@router.patch("/{simulacion_id}", response_model=SimulacionRead)
async def update_simulacion_task(
    simulacion_id: UUID,
    data: SimulacionUpdate,
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection)
):
    """
    Actualiza el status, asignación o el dato KWp. 
    Aplica la validación crítica de KWp al marcar como Entregado.
    """
    return await service.update_simulacion(conn, simulacion_id, data)