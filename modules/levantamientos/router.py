# Archivo: modules/levantamientos/router.py

from fastapi import APIRouter, Depends, status, HTTPException
from typing import List
from datetime import datetime
from uuid import UUID

# Importamos los modelos Pydantic
from .schemas import LevantamientoCreate, LevantamientoUpdate, LevantamientoRead
# Importamos la conexión (que usaremos cuando se resuelva el timeout)
from core.database import get_db_connection

router = APIRouter(
    prefix="/levantamientos",
    tags=["Módulo Levantamientos"],
    # Se asumiría una dependencia para verificar roles Ing/Const/Comercial
)

# --- Capa de Servicio (Service Layer) ---

class LevantamientosService:
    """Maneja la cola de trabajo de Levantamientos y la notificación."""

    async def create_levantamiento(self, conn, data: LevantamientoCreate) -> LevantamientoRead:
        """Comercial solicita un nuevo levantamiento (insert en tb_levantamientos)."""
        # Lógica de inserción de DB
        # Retorna el objeto LevantamientoRead (Status='Solicitado')
        pass # Implementación de DB pendiente

    async def update_tarea_ejecutada(self, conn, levantamiento_id: UUID, data: LevantamientoUpdate) -> LevantamientoRead:
        """
        Ingeniería/Construcción completa la tarea. Debe contener URL de evidencia.
        """
        if data.status_tarea == "Ejecutado":
            if not data.evidencia_docs_url:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="La entrega de Levantamiento DEBE incluir la URL de la evidencia (Fotos/Docs)."
                )
            
            # --- NOTIFICACIÓN CRÍTICA ---
            # 1. Notificar a Simulación (para ajustar modelo)
            # 2. Notificar a Comercial (para solicitar Actualización de Oferta)
            # Esto se haría llamando a un servicio de Notificaciones/Correo.
            print(f"NOTIFICACIÓN: Levantamiento {levantamiento_id} EJECUTADO. Disparando correos a Simulación y Comercial.")

        # Lógica de actualización de DB aquí
        pass # Implementación de DB pendiente

    async def get_queue_solicitada(self, conn) -> List[LevantamientoRead]:
        """Vista principal para Ing/Const: Tareas con status 'Solicitado' o 'Asignado'."""
        # Query: SELECT * FROM tb_levantamientos WHERE status_tarea IN ('Solicitado', 'Asignado')
        return [] # Retorno vacío hasta que la DB funcione

def get_levantamientos_service():
    return LevantamientosService()

# --- Endpoints ---

@router.post("/", response_model=LevantamientoRead, status_code=status.HTTP_201_CREATED)
async def solicitar_levantamiento(
    data: LevantamientoCreate,
    service: LevantamientosService = Depends(get_levantamientos_service),
    conn = Depends(get_db_connection)
):
    """Comercial solicita un nuevo levantamiento para un sitio específico."""
    return await service.create_levantamiento(conn, data)


@router.patch("/{levantamiento_id}", response_model=LevantamientoRead)
async def actualizar_levantamiento(
    levantamiento_id: UUID,
    data: LevantamientoUpdate,
    service: LevantamientosService = Depends(get_levantamientos_service),
    conn = Depends(get_db_connection)
):
    """Actualiza asignación o marca como ejecutado (dispara notificaciones)."""
    return await service.update_tarea_ejecutada(conn, levantamiento_id, data)

@router.get("/", response_model=List[LevantamientoRead])
async def get_levantamientos_pendientes(
    service: LevantamientosService = Depends(get_levantamientos_service),
    conn = Depends(get_db_connection)
):
    """Muestra la cola de Levantamientos pendientes para Ing/Const."""
    return await service.get_queue_solicitada(conn)