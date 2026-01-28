# Archivo: core/projects/__init__.py
"""
Módulo compartido para gestión de Proyectos Gate.

Uso:
    from core.projects.router import router as projects_router
    from core.projects.service import get_projects_gate_service
"""

from .router import router
from .service import ProjectsGateService, get_projects_gate_service
from .schemas import (
    ProyectoGateCreate,
    ProyectoGateRead,
    ProyectoGateListItem,
    OportunidadGanadaItem,
    TecnologiaItem
)

__all__ = [
    "router",
    "ProjectsGateService",
    "get_projects_gate_service",
    "ProyectoGateCreate",
    "ProyectoGateRead",
    "ProyectoGateListItem",
    "OportunidadGanadaItem",
    "TecnologiaItem"
]
