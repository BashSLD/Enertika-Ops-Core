from typing import Iterable, Optional

from .db_service import NavigationDBService, get_navigation_db_service


class NavigationService:
    """Resuelve rutas UI de modulos usando el catalogo del sistema."""

    def __init__(self, db: NavigationDBService | None = None) -> None:
        self.db = db or get_navigation_db_service()

    async def get_module_route(self, conn, slug: str) -> Optional[str]:
        route = await self.db.get_module_route(conn, slug)
        return route if self._is_safe_internal_route(route) else None

    async def get_first_accessible_module_route(
        self,
        conn,
        module_slugs: Iterable[str],
    ) -> Optional[str]:
        rows = await self.db.get_module_routes(conn, module_slugs)
        for row in rows:
            route = row.get("ruta")
            if self._is_safe_internal_route(route):
                return route
        return None

    @staticmethod
    def _is_safe_internal_route(route: Optional[str]) -> bool:
        if not route:
            return False

        route = route.strip()
        return route.startswith("/") and not route.startswith("//")


def get_navigation_service() -> NavigationService:
    return NavigationService()

