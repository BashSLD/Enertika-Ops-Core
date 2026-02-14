from typing import List, Optional, Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, ConfigDict

# --- Base Configuration ---
class AdminBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

# -----------------------------------------
# 1. GESTIÓN DE REGLAS DE NEGOCIO (Config Global)
# -----------------------------------------
class ConfiguracionGlobalUpdate(AdminBaseSchema):
    """Schema para actualizar parámetros globales."""
    hora_corte_l_v: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Formato HH:MM")
    dias_sla_default: int = Field(..., ge=1, le=30)
    # Recibimos una lista de enteros (ej: [5, 6] para Sábado y Domingo)
    dias_fin_semana: List[int] = Field(default_factory=list)
    
    # 2. Configuración SharePoint y Adjuntos (Robustez sin Hardcoding)
    sharepoint_site_id: Optional[str] = Field(None, description="ID del Sitio SharePoint")
    sharepoint_drive_id: Optional[str] = Field(None, description="ID del Drive (Librería)")
    sharepoint_base_folder: Optional[str] = Field(None, description="Carpeta Raíz (Opcional)")
    max_upload_size_mb: int = Field(500, ge=10, le=5000, description="Límite en MB (10MB - 5GB)")

    # 3. Configuración KPIs Simulación (Scores)
    # Porcentajes (Weights) 0.0 - 1.0 (o escalado según lógica)
    sim_peso_compromiso: Optional[float] = Field(0.50, ge=0.0, le=1.0)
    sim_peso_interno: Optional[float] = Field(0.35, ge=0.0, le=1.0)
    sim_peso_volumen: Optional[float] = Field(0.15, ge=0.0, le=1.0)
    
    # Umbrales y Factores
    sim_umbral_min_entregas: Optional[int] = Field(10, ge=1)
    sim_umbral_ratio_licitaciones: Optional[float] = Field(0.10)
    sim_umbral_verde: Optional[float] = Field(90.0, ge=0.0, le=100.0)
    sim_umbral_ambar: Optional[float] = Field(85.0, ge=0.0, le=100.0)
    sim_mult_licitaciones: Optional[float] = Field(0.20)
    sim_mult_actualizaciones: Optional[float] = Field(0.10)
    sim_penalizacion_retrabajos: Optional[float] = Field(-0.15)
    sim_volumen_max: Optional[int] = Field(100)

    # 4. Configuración Comercial (Targeted Popups)
    comercial_popup_targets: Optional[str] = Field("", description="Lista de emails separados por coma")

    @field_validator('dias_fin_semana')
    @classmethod
    def validar_dias(cls, v):
        for dia in v:
            if not (0 <= dia <= 6): # 0=Lunes, 6=Domingo
                raise ValueError("Los días deben ser entre 0 (Lunes) y 6 (Domingo)")
        return v

# -----------------------------------------
# 2. GESTIÓN DE CATÁLOGOS (ABM Generico)
# -----------------------------------------

# --- Tecnologías ---
class TecnologiaCreate(AdminBaseSchema):
    nombre: str = Field(..., min_length=2, max_length=100)
    activo: bool = True

class TecnologiaUpdate(TecnologiaCreate):
    id: int

# --- Orígenes de Adjuntos (Nuevo Catalog) ---
class OrigenAdjuntoCreate(AdminBaseSchema):
    slug: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-z0-9_]+$", description="Identificador único (slug)")
    descripcion: str = Field(..., min_length=5, max_length=200)
    activo: bool = True

# --- Tipos de Solicitud ---
class TipoSolicitudCreate(AdminBaseSchema):
    nombre: str = Field(..., min_length=2, max_length=100)
    # El código interno es crítico para lógica de backend, requiere cuidado
    codigo_interno: Optional[str] = Field(None, min_length=2, max_length=50)
    activo: bool = True
    es_seguimiento: bool = False

class TipoSolicitudUpdate(TipoSolicitudCreate):
    id: int

# --- Estatus Global (Con Color) ---
class EstatusGlobalCreate(AdminBaseSchema):
    nombre: str = Field(..., min_length=2)
    descripcion: Optional[str] = None
    color_hex: str = Field(..., pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    activo: bool = True

class EstatusGlobalUpdate(EstatusGlobalCreate):
    id: int

# -----------------------------------------
# 3. REGLAS DE CORREO (Mejorado)
# -----------------------------------------
class EmailRuleCreate(AdminBaseSchema):
    modulo: str
    trigger_field: str
    # Ahora validamos que trigger_value no esté vacío
    trigger_value: str = Field(..., min_length=1)
    email_to_add: str = Field(..., pattern=r"[^@]+@[^@]+\.[^@]+")
    type: Literal['TO', 'CC', 'CCO']

# -----------------------------------------
# 4. GESTIÓN DE CLIENTES (Simple)
# -----------------------------------------
class ClienteCreate(AdminBaseSchema):
    nombre_fiscal: str = Field(..., min_length=3)
    contacto_principal: Optional[str] = None
    direccion_fiscal: Optional[str] = None

class ClienteUpdate(ClienteCreate):
    id: UUID