# core/tipo_cambio/service.py
"""
Service para tipo de cambio USD/MXN.
Consulta la API de Banxico (serie SF43718 — FIX interbancario).
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo
import logging

TZ_MX = ZoneInfo("America/Mexico_City")


def _hoy_mx():
    """Fecha actual en zona horaria México (no UTC del servidor)."""
    return datetime.now(TZ_MX).date()

import httpx

from .db_service import TipoCambioDBService

logger = logging.getLogger("TipoCambio.Service")

BANXICO_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43718/datos/oportuno"

# Cliente compartido entre instancias — evita crear un pool TCP por llamada
_http_client = httpx.AsyncClient(timeout=10.0)


class TipoCambioService:

    def __init__(self):
        self.db = TipoCambioDBService()

    async def _fetch_from_banxico(self, token: str) -> Optional[dict]:
        """
        Consulta la API de Banxico y retorna {fecha: date, tasa_mxn: Decimal}.
        Retorna None si el token no está configurado o la respuesta falla.
        """
        if not token:
            logger.warning("[TIPO_CAMBIO] BANXICO_TOKEN no configurado — omitiendo consulta")
            return None

        try:
            resp = await _http_client.get(
                BANXICO_URL,
                headers={"Bmx-Token": token, "Accept": "application/json"}
            )
            resp.raise_for_status()
            payload = resp.json()

            series = payload.get("bmx", {}).get("series", [])
            if not series:
                logger.error("[TIPO_CAMBIO] Respuesta Banxico sin series: %s", payload)
                return None

            datos = series[0].get("datos", [])
            if not datos:
                logger.error("[TIPO_CAMBIO] Serie SF43718 sin datos")
                return None

            ultimo = datos[-1]
            fecha_str = ultimo.get("fecha", "")   # formato: "DD/MM/YYYY"
            dato_str = ultimo.get("dato", "N/E")

            if dato_str == "N/E" or not dato_str:
                logger.warning("[TIPO_CAMBIO] Dato no disponible para fecha %s", fecha_str)
                return None

            fecha = datetime.strptime(fecha_str, "%d/%m/%Y").date()
            tasa = Decimal(dato_str)
            return {"fecha": fecha, "tasa_mxn": tasa}

        except httpx.HTTPError as exc:
            logger.error("[TIPO_CAMBIO] Error HTTP Banxico: %s", exc)
            return None
        except (KeyError, IndexError, ValueError) as exc:
            logger.error("[TIPO_CAMBIO] Error procesando respuesta Banxico: %s", exc)
            return None

    async def get_tasa_actual(self, conn) -> Optional[dict]:
        """
        Retorna la tasa más reciente de la BD.
        Formato: {fecha, tasa_mxn, fuente, dias_antiguedad}
        """
        registro = await self.db.get_tasa_mas_reciente(conn)
        if not registro:
            return None
        antiguedad = (_hoy_mx() - registro["fecha"]).days
        return {**registro, "dias_antiguedad": antiguedad}

    async def refresh_tasa(self, conn, token: str) -> dict:
        """
        Consulta Banxico y persiste la tasa en BD.
        Retorna {exito: bool, tasa_mxn, fecha, fuente}.

        Raises:
            ValueError: Si Banxico no retorna datos.
        """
        resultado = await self._fetch_from_banxico(token)
        if not resultado:
            raise ValueError("No se pudo obtener la tasa de Banxico. Verifica el token o reintenta.")

        await self.db.upsert_tasa(conn, resultado["fecha"], resultado["tasa_mxn"])
        logger.info("[TIPO_CAMBIO] Tasa actualizada: %s = $%s MXN", resultado["fecha"], resultado["tasa_mxn"])

        return {
            "exito": True,
            "fecha": resultado["fecha"],
            "tasa_mxn": float(resultado["tasa_mxn"]),
            "fuente": "BANXICO",
        }

    async def get_historial(self, conn, limit: int = 30) -> list:
        """Retorna historial de tasas."""
        return await self.db.get_historial(conn, limit)

    async def startup_refresh(self, conn, token: str) -> None:
        """
        Tarea de startup: actualiza la tasa del día si no existe aún.
        No lanza excepción para no bloquear el inicio de la app.
        """
        try:
            existente = await self.db.get_tasa_by_fecha(conn, _hoy_mx())
            if existente:
                logger.info("[TIPO_CAMBIO] Tasa del día ya registrada: $%s MXN", existente["tasa_mxn"])
                return

            resultado = await self._fetch_from_banxico(token)
            if resultado:
                await self.db.upsert_tasa(conn, resultado["fecha"], resultado["tasa_mxn"])
                logger.info("[TIPO_CAMBIO] Startup: tasa %s = $%s MXN", resultado["fecha"], resultado["tasa_mxn"])
            else:
                logger.warning("[TIPO_CAMBIO] Startup: no se pudo obtener tasa (token ausente o error Banxico)")
        except Exception as exc:
            logger.error("[TIPO_CAMBIO] Error en startup_refresh: %s", exc)
