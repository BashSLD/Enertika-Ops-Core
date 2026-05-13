from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from modules.asistencia.logic import ensure_mx


class BioTimeClient:
    def __init__(self, base_url: str, access_key: str, timeout_seconds: int = 30):
        base = (base_url or "").strip().rstrip("/")
        key = (access_key or "").strip()
        if not base:
            raise ValueError("La URL base de BioTime no esta configurada")
        if not key:
            raise ValueError("La llave de acceso de BioTime no esta configurada")
        self.base_url = base
        self.access_key = key
        self.timeout_seconds = timeout_seconds

    async def fetch_transactions(
        self,
        *,
        starttime: datetime,
        endtime: datetime,
        last_id: int | None = None,
        number: int = 1000,
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}/api/v2/transaction/get/"
        params = {"key": self.access_key}
        data: dict[str, Any] = {
            "starttime": ensure_mx(starttime).strftime("%Y-%m-%d %H:%M:%S"),
            "endtime": ensure_mx(endtime).strftime("%Y-%m-%d %H:%M:%S"),
            "number": max(1, min(number, 2000)),
        }
        if last_id is not None:
            data["id"] = last_id

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, params=params, data=data)
            response.raise_for_status()
            payload = response.json()

        return self._extract_items(payload)

    @staticmethod
    def _extract_items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            raise ValueError("Respuesta BioTime invalida")

        data = payload.get("data", payload)
        if isinstance(data, dict):
            items = data.get("items", data.get("rows", []))
        else:
            items = data

        if not isinstance(items, list):
            raise ValueError("Respuesta BioTime sin lista de transacciones")
        return [item for item in items if isinstance(item, dict)]
