from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from core.timezone import today_mx
from modules.asistencia.logic import ensure_mx

logger = logging.getLogger("asistencia.biotime_client")

_LOGIN_URL = "/login/"
_TRANSACTIONS_URL = "/iclock/transaction/table/"
_EMPLOYEES_URL = "/personnel/employee/table/"


class BioTimeClient:
    def __init__(self, base_url: str, username: str, password: str, timeout_seconds: int = 30):
        base = (base_url or "").strip().rstrip("/")
        user = (username or "").strip()
        pwd = password or ""
        if not base:
            raise ValueError("La URL base de BioTime no esta configurada")
        if not base.startswith(("http://", "https://")):
            raise ValueError("La URL base de BioTime debe incluir http:// o https://")
        if not user:
            raise ValueError("El usuario de BioTime no esta configurado")
        if not pwd:
            raise ValueError("La contraseña de BioTime no esta configurada")
        self.base_url = base
        self.username = user
        self.password = pwd
        self.timeout_seconds = timeout_seconds
        self._cookies: dict[str, str] = {}
        self._http_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BioTimeClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _login(self) -> None:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            get_resp = await client.get(f"{self.base_url}{_LOGIN_URL}")
            get_resp.raise_for_status()
            csrf = client.cookies.get("csrftoken") or get_resp.cookies.get("csrftoken")
            if not csrf:
                raise ValueError("BioTime no retorno csrftoken en la página de login")

            post_resp = await client.post(
                f"{self.base_url}{_LOGIN_URL}",
                data={
                    "username": self.username,
                    "password": self.password,
                    "csrfmiddlewaretoken": csrf,
                },
                headers={
                    "X-CSRFToken": csrf,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{self.base_url}{_LOGIN_URL}",
                },
            )
            post_resp.raise_for_status()

            session = client.cookies.get("sessionid") or post_resp.cookies.get("sessionid")
            new_csrf = client.cookies.get("csrftoken") or post_resp.cookies.get("csrftoken") or csrf

            if not session:
                session_resp = await client.get(f"{self.base_url}{_LOGIN_URL}?next=/")
                session_resp.raise_for_status()
                session = client.cookies.get("sessionid") or session_resp.cookies.get("sessionid")
                new_csrf = client.cookies.get("csrftoken") or session_resp.cookies.get("csrftoken") or csrf

            if not session:
                raise ValueError("BioTime no retorno sessionid; credenciales incorrectas o login fallido")

            self._cookies = {"csrftoken": new_csrf, "sessionid": session}
            logger.debug("[BIOTIME] Login exitoso")

        if self._http_client is not None:
            await self._http_client.aclose()
        self._http_client = httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            cookies=self._cookies,
        )

    def _is_authenticated(self) -> bool:
        return bool(self._cookies.get("sessionid"))

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._is_authenticated() or self._http_client is None:
            await self._login()
        if self._http_client is None:
            raise RuntimeError("No se pudo inicializar cliente HTTP BioTime")
        return self._http_client

    async def _get(self, path: str, params: dict) -> Any:
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}{path}", params=params)

        if resp.status_code in {301, 302} and "/login/" in (resp.headers.get("location") or ""):
            logger.info("[BIOTIME] Sesion expirada, re-autenticando")
            self._cookies = {}
            await self._login()
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}{path}", params=params)

        resp.raise_for_status()
        return resp.json()

    async def fetch_transactions(
        self,
        *,
        starttime: datetime,
        endtime: datetime,
        page_size: int = 200,
    ) -> list[dict[str, Any]]:
        start_str = ensure_mx(starttime).strftime("%Y-%m-%d")
        end_str = (ensure_mx(endtime).date() + timedelta(days=1)).strftime("%Y-%m-%d")
        safe_size = max(1, min(page_size, 1000))
        all_items: list[dict[str, Any]] = []
        page = 1

        while True:
            params = {
                "page": page,
                "limit": safe_size,
                "_p1_punch_time__gte": start_str,
                "_p1_punch_time__lt": end_str,
            }
            payload = await self._get(_TRANSACTIONS_URL, params)
            total = int(payload.get("total", 0)) if isinstance(payload, dict) else 0
            items = self._extract_rows(payload)
            if not items:
                break
            all_items.extend(items)
            if total > 0 and len(all_items) >= total:
                break
            if len(items) < safe_size:
                break
            page += 1

        return all_items

    async def ping(self) -> int:
        """Valida login y lee la primera pagina. Retorna total de registros de hoy."""
        today = today_mx()
        params = {
            "page": 1,
            "limit": 10,
            "_p1_punch_time__gte": today.strftime("%Y-%m-%d"),
            "_p1_punch_time__lt": (today + timedelta(days=1)).strftime("%Y-%m-%d"),
        }
        payload = await self._get(_TRANSACTIONS_URL, params)
        return int(payload.get("total", 0)) if isinstance(payload, dict) else 0

    async def fetch_employees(self, *, page_size: int = 200) -> list[dict[str, Any]]:
        safe_size = max(1, min(page_size, 500))
        all_items: list[dict[str, Any]] = []
        page = 1

        while True:
            params = {
                "page": page,
                "limit": safe_size,
            }
            try:
                payload = await self._get(_EMPLOYEES_URL, params)
            except httpx.HTTPStatusError as exc:
                logger.warning("[BIOTIME] No se pudieron obtener empleados: %s", exc)
                break
            total = int(payload.get("total", 0)) if isinstance(payload, dict) else 0
            items = self._extract_rows(payload)
            if not items:
                break
            all_items.extend(items)
            if total > 0 and len(all_items) >= total:
                break
            if len(items) < safe_size:
                break
            page += 1

        return all_items

    @staticmethod
    def _extract_rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            raise ValueError("Respuesta BioTime inválida")
        rows = payload.get("rows", payload.get("data", payload.get("items", [])))
        if not isinstance(rows, list):
            raise ValueError("Respuesta BioTime sin lista de registros")
        return [item for item in rows if isinstance(item, dict)]
