import asyncio
import base64
import logging
from datetime import date
from typing import Optional

from satcfdi.models import Signer
from satcfdi.pacs.sat import SAT, EstadoComprobante

logger = logging.getLogger("SATClient")

ESTADO_LISTO = 3
ESTADOS_ERROR = {4, 5, 6}
ESTADO_LABELS = {
    1: "Aceptada",
    2: "En proceso",
    3: "Terminada",
    4: "Error",
    5: "Rechazada",
    6: "Vencida",
}

POLL_INTERVAL_SECONDS = 30


class SATClient:
    def __init__(self, signer: Signer):
        self._sat = SAT(signer=signer)
        self.rfc = signer.rfc

    async def solicitar_descarga(
        self,
        fecha_inicio: date,
        fecha_fin: date,
    ) -> str:
        """
        Solicita descarga masiva de CFDIs recibidos en el rango de fechas.
        Retorna el IdSolicitud del SAT.
        """
        from datetime import datetime
        dt_inicio = datetime(fecha_inicio.year, fecha_inicio.month, fecha_inicio.day)
        dt_fin = datetime(fecha_fin.year, fecha_fin.month, fecha_fin.day, 23, 59, 59)

        respuesta = await asyncio.to_thread(
            self._sat.recover_comprobante_received_request,
            fecha_inicial=dt_inicio,
            fecha_final=dt_fin,
            rfc_receptor=self.rfc,
            estado_comprobante=EstadoComprobante.VIGENTE,
        )
        id_solicitud = respuesta.get("IdSolicitud")
        if not id_solicitud:
            raise ValueError(f"SAT no retorno IdSolicitud: {respuesta}")
        logger.info("Solicitud SAT aceptada — IdSolicitud: %s", id_solicitud)
        return id_solicitud

    async def esperar_paquetes(
        self,
        id_solicitud: str,
        on_poll: Optional[callable] = None,
    ) -> list[str]:
        """
        Hace polling hasta que el SAT tenga los paquetes listos (estado=3).
        on_poll: coroutine opcional llamada en cada ciclo con el estado actual.
        Retorna lista de IdsPaquetes.
        Lanza ValueError si el SAT rechaza o hay error.
        """
        while True:
            estado = await asyncio.to_thread(
                self._sat.recover_comprobante_status,
                id_solicitud=id_solicitud,
            )
            codigo = estado.get("EstadoSolicitud")
            label = ESTADO_LABELS.get(codigo, str(codigo))
            logger.info("SAT estado solicitud %s: %s — %s", id_solicitud, codigo, label)

            if on_poll:
                await on_poll(codigo, label)

            if codigo == ESTADO_LISTO:
                ids_paquetes = estado.get("IdsPaquetes", [])
                logger.info("Paquetes listos: %s — CFDIs: %s", ids_paquetes, estado.get("NumeroCFDIs"))
                return ids_paquetes

            if codigo in ESTADOS_ERROR:
                raise ValueError(f"SAT rechazo la solicitud — estado: {codigo} ({label})")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def descargar_paquete(self, id_paquete: str) -> bytes:
        """
        Descarga un paquete ZIP del SAT y retorna los bytes crudos (sin base64).
        """
        resultado = await asyncio.to_thread(
            self._sat.recover_comprobante_download,
            id_paquete=id_paquete,
        )
        zip_bytes = base64.b64decode(resultado[1])
        logger.info("Paquete %s descargado — %d bytes", id_paquete, len(zip_bytes))
        return zip_bytes
