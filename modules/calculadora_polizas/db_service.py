# modules/calculadora/db_service.py
from uuid import UUID, uuid4
from typing import Optional
import logging

logger = logging.getLogger("CalculadoraPolizas.DBService")


class CalculadoraDBService:

    # ----------------------------------------
    # PLANTAS
    # ----------------------------------------

    async def get_plantas_dropdown(self, conn) -> list:
        rows = await conn.fetch("""
            SELECT id, nombre, zona, potencia_kw, num_paneles
            FROM tb_calculadora_plantas
            WHERE activa = TRUE
            ORDER BY nombre
        """)
        return [dict(r) for r in rows]

    async def get_plantas_list(self, conn, q: Optional[str] = None) -> list:
        if q:
            rows = await conn.fetch("""
                SELECT id, nombre, zona, potencia_kw, num_paneles, activa, created_at, updated_at
                FROM tb_calculadora_plantas
                WHERE nombre ILIKE $1 OR zona ILIKE $1 OR id ILIKE $1
                ORDER BY nombre
                LIMIT 200
            """, f"%{q}%")
        else:
            rows = await conn.fetch("""
                SELECT id, nombre, zona, potencia_kw, num_paneles, activa, created_at, updated_at
                FROM tb_calculadora_plantas
                ORDER BY nombre
                LIMIT 500
            """)
        return [dict(r) for r in rows]

    async def get_planta_by_id(self, conn, planta_id: str) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT id, nombre, zona, potencia_kw, num_paneles, activa, created_at, updated_at
            FROM tb_calculadora_plantas
            WHERE id = $1
        """, planta_id)
        return dict(row) if row else None

    async def upsert_planta(self, conn, planta: dict) -> str:
        await conn.execute("""
            INSERT INTO tb_calculadora_plantas (id, nombre, zona, potencia_kw, num_paneles, activa, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (id) DO UPDATE SET
                nombre      = EXCLUDED.nombre,
                zona        = EXCLUDED.zona,
                potencia_kw = EXCLUDED.potencia_kw,
                num_paneles = EXCLUDED.num_paneles,
                activa      = EXCLUDED.activa,
                updated_at  = NOW()
        """, planta["id"], planta["nombre"], planta["zona"],
             planta.get("potencia_kw"), planta.get("num_paneles"),
             planta.get("activa", True))
        return planta["id"]

    async def update_planta(self, conn, planta_id: str, campos: dict) -> bool:
        sets, params = [], [planta_id]
        for key, val in campos.items():
            params.append(val)
            sets.append(f"{key} = ${len(params)}")
        if not sets:
            return False
        sets.append("updated_at = NOW()")
        await conn.execute(
            f"UPDATE tb_calculadora_plantas SET {', '.join(sets)} WHERE id = $1",
            *params
        )
        return True

    async def toggle_planta_activa(self, conn, planta_id: str) -> Optional[bool]:
        row = await conn.fetchrow("""
            UPDATE tb_calculadora_plantas
            SET activa = NOT activa, updated_at = NOW()
            WHERE id = $1
            RETURNING activa
        """, planta_id)
        return row["activa"] if row else None

    # ----------------------------------------
    # CATÁLOGOS DE PRECIOS
    # ----------------------------------------

    async def get_precios_zona(self, conn) -> dict:
        rows = await conn.fetch("SELECT zona, precio_por_panel_mxp FROM tb_calculadora_precios_zona ORDER BY zona")
        return {r["zona"]: float(r["precio_por_panel_mxp"]) for r in rows}

    async def get_wattabit_para_kwp(self, conn, kwp: float) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT id, nombre, precio_anual_mxp
            FROM tb_calculadora_wattabit
            WHERE $1 > rango_min_kwp AND $1 <= rango_max_kwp
            LIMIT 1
        """, kwp)
        return dict(row) if row else None

    async def get_costos_fijos(self, conn) -> dict:
        rows = await conn.fetch("SELECT concepto, valor FROM tb_calculadora_costos_fijos")
        return {r["concepto"]: float(r["valor"]) for r in rows}

    async def get_precios_zona_list(self, conn) -> list:
        rows = await conn.fetch(
            "SELECT zona, precio_por_panel_mxp, updated_at FROM tb_calculadora_precios_zona ORDER BY zona"
        )
        return [dict(r) for r in rows]

    async def get_wattabit_list(self, conn) -> list:
        rows = await conn.fetch(
            "SELECT id, nombre, rango_min_kwp, rango_max_kwp, precio_anual_mxp, updated_at "
            "FROM tb_calculadora_wattabit ORDER BY rango_min_kwp"
        )
        return [dict(r) for r in rows]

    async def get_costos_fijos_list(self, conn) -> list:
        rows = await conn.fetch(
            "SELECT concepto, valor, notas, updated_at FROM tb_calculadora_costos_fijos ORDER BY concepto"
        )
        return [dict(r) for r in rows]

    async def update_precio_zona(self, conn, zona: str, precio: float) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_precios_zona
            SET precio_por_panel_mxp = $2, updated_at = NOW()
            WHERE zona = $1
        """, zona, precio)
        return result != "UPDATE 0"

    async def update_wattabit(self, conn, wattabit_id: int, precio: float) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_wattabit
            SET precio_anual_mxp = $2, updated_at = NOW()
            WHERE id = $1
        """, wattabit_id, precio)
        return result != "UPDATE 0"

    async def update_costo_fijo(self, conn, concepto: str, valor: float) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_costos_fijos
            SET valor = $2, updated_at = NOW()
            WHERE concepto = $1
        """, concepto, valor)
        return result != "UPDATE 0"

    # ----------------------------------------
    # COTIZACIONES
    # ----------------------------------------

    async def save_cotizacion(self, conn, data: dict) -> UUID:
        import json
        new_id = uuid4()
        await conn.execute("""
            INSERT INTO tb_calculadora_cotizaciones
                (id, planta_id, nombre_planta, tipo_poliza, utilidad,
                 sub_total, sub_total_utilidad, total_final, resultado_json, creado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, new_id,
             data.get("planta_id"), data["nombre_planta"], data["tipo_poliza"],
             data["utilidad"], data["sub_total"], data["sub_total_utilidad"],
             data["total_final"], json.dumps(data["resultado_json"]), data.get("creado_por"))
        return new_id

    async def get_cotizaciones(self, conn, limit: int = 100, offset: int = 0) -> list:
        rows = await conn.fetch("""
            SELECT
                c.id, c.planta_id, c.nombre_planta, c.tipo_poliza, c.utilidad,
                c.sub_total, c.sub_total_utilidad, c.total_final,
                c.resultado_json, c.creado_por, c.created_at,
                u.nombre AS creado_por_nombre
            FROM tb_calculadora_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            ORDER BY c.created_at DESC
            LIMIT $1 OFFSET $2
        """, limit, offset)
        return [dict(r) for r in rows]

    async def count_cotizaciones(self, conn) -> int:
        return await conn.fetchval("SELECT COUNT(*) FROM tb_calculadora_cotizaciones")
