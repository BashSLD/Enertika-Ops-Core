import logging
from uuid import UUID, uuid4
from typing import Optional

logger = logging.getLogger("SharedServices")

class SiteService:
    """
    Servicio compartido para gestión de Sitios.
    Centraliza la creación de sitios únicos y masivos.
    """

    @staticmethod
    async def create_single_site(
        conn, 
        id_oportunidad: UUID, 
        nombre_sitio: str, 
        direccion: str, 
        google_maps_link: Optional[str], 
        id_tipo_solicitud: int
    ):
        """
        Crea automáticamente un sitio único (Sitio 01).
        Utilizado en flujos unisitio de Comercial y Simulación.
        """
        try:
            query = """
                INSERT INTO tb_sitios_oportunidad (
                    id_sitio, id_oportunidad, nombre_sitio, 
                    direccion, google_maps_link, 
                    id_tipo_solicitud, id_estatus_global
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, 1
                )
            """
            await conn.execute(query, 
                uuid4(), 
                id_oportunidad, 
                nombre_sitio, 
                direccion, 
                google_maps_link, 
                id_tipo_solicitud
            )
        except Exception as e:
            logger.error(f"Error en SiteService.create_single_site: {e}")
            raise e
