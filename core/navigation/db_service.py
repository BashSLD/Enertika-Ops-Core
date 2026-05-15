import time
from typing import Iterable, List, Optional

_ROUTE_CACHE_TTL = 60.0


class NavigationDBService:
    """Acceso a datos para resolver rutas de navegacion desde catalogos."""

    _route_cache: dict[str, tuple[float, Optional[str]]] = {}

    async def get_module_route(self, conn, slug: str) -> Optional[str]:
        cached = self._route_cache.get(slug)
        if cached and time.time() - cached[0] < _ROUTE_CACHE_TTL:
            return cached[1]
        ruta = await conn.fetchval(
            """
            SELECT ruta
            FROM tb_cat_modulos
            WHERE slug = $1
              AND is_active = true
              AND ruta IS NOT NULL
              AND TRIM(ruta) <> ''
            LIMIT 1
            """,
            slug,
        )
        self._route_cache[slug] = (time.time(), ruta)
        return ruta

    async def get_module_routes(self, conn, slugs: Iterable[str]) -> List[dict]:
        slug_list = sorted({slug for slug in slugs if slug})
        if not slug_list:
            return []

        rows = await conn.fetch(
            """
            SELECT slug, ruta
            FROM tb_cat_modulos
            WHERE slug = ANY($1::text[])
              AND is_active = true
              AND ruta IS NOT NULL
              AND TRIM(ruta) <> ''
            ORDER BY orden, nombre, slug
            """,
            slug_list,
        )
        return [dict(row) for row in rows]


def get_navigation_db_service() -> NavigationDBService:
    return NavigationDBService()

