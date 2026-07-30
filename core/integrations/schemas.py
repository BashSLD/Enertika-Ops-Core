from pydantic import BaseModel, Field


class SharePointMapeoManual(BaseModel):
    folder_id: str = Field(min_length=1)
    corregir_nombre: bool = False


class SharePointResolverStatus:
    """Valores del campo `status` que devuelve resolver_carpeta_proyecto (contrato con el JS de base.html)."""

    MAPEADO = "MAPEADO"
    SIN_MATCH = "SIN_MATCH"
    AMBIGUO = "AMBIGUO"
