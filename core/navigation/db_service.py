from typing import Iterable, List, Optional


class NavigationDBService:
    """Acceso a datos para resolver rutas de navegacion desde catalogos."""

    async def get_module_route(self, conn, slug: str) -> Optional[str]:
        return await conn.fetchval(
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

