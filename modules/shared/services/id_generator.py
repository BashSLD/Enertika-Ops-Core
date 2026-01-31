from datetime import datetime
from typing import Optional

class IdGeneratorService:
    """
    Servicio compartido para la generación estandarizada de Identificadores.
    Centraliza la lógica de 'op_id_estandar' y 'id_interno' para Comercial y Simulación.
    """

    @staticmethod
    def generate_standard_op_id(timestamp: datetime) -> str:
        """
        Genera el ID estándar basado en fecha/hora.
        Formato: OP - YYMMDDHHMM (Sin guion intermedio)
        """
        return timestamp.strftime("OP - %y%m%d%H%M")

    @staticmethod
    def generate_internal_id(
        op_id_estandar: str, 
        cliente_nombre: str, 
        nombre_proyecto: str, 
        cantidad_sitios: int
    ) -> str:
        """
        Genera el ID Interno usado para carpetas y seguimiento.
        
        Regla de Negocio:
            - Multisitio (>1): ESTANDAR_CLIENTE_PROYECTO
            - Unisitio (1):    ESTANDAR_CLIENTE
            
        Args:
            op_id_estandar: El ID estándar generado previamente (ej. OP - 250129...)
            cliente_nombre: Nombre fiscal del cliente
            nombre_proyecto: Nombre del proyecto
            cantidad_sitios: Número de sitios de la oportunidad
            
        Returns:
            str: ID Interno normalizado (Upper, max 150 chars)
        """
        # Limpieza básica
        clean_cliente = (cliente_nombre or "").strip()
        clean_proyecto = (nombre_proyecto or "").strip()
        
        if cantidad_sitios > 1:
            base = f"{op_id_estandar}_{clean_cliente}_{clean_proyecto}"
        else:
            base = f"{op_id_estandar}_{clean_cliente}"
            
        return base.upper()[:150]

    @staticmethod
    def generate_project_title(
        tipo_nombre: str,
        cliente_nombre: str,
        proyecto_nombre: str,
        tecnologia_nombre: str,
        canal_venta: str
    ) -> str:
        """
        Genera el Título del Proyecto estandarizado.
        Formato: TIPO_CLIENTE_PROYECTO_TECNOLOGIA_CANAL
        """
        return f"{tipo_nombre}_{cliente_nombre}_{proyecto_nombre}_{tecnologia_nombre}_{canal_venta}".upper()
