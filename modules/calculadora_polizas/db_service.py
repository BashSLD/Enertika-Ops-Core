# modules/calculadora/db_service.py
from uuid import UUID, uuid4
from typing import Optional
import json
import logging

logger = logging.getLogger("CalculadoraPolizas.DBService")


class CalculadoraDBService:

    # ----------------------------------------
    # PLANTAS
    # ----------------------------------------

    async def get_plantas_dropdown(self, conn) -> list:
        rows = await conn.fetch("""
            SELECT id, nombre, zona, potencia_kw, num_paneles, cliente, direccion
            FROM tb_calculadora_plantas
            WHERE activa = TRUE
            ORDER BY nombre
        """)
        return [dict(r) for r in rows]

    async def get_plantas_list(self, conn, q: Optional[str] = None) -> list:
        if q:
            rows = await conn.fetch("""
                SELECT id, nombre, zona, potencia_kw, num_paneles, cliente, direccion, activa, created_at, updated_at
                FROM tb_calculadora_plantas
                WHERE nombre ILIKE $1 OR zona ILIKE $1 OR id ILIKE $1 OR cliente ILIKE $1
                ORDER BY nombre
                LIMIT 200
            """, f"%{q}%")
        else:
            rows = await conn.fetch("""
                SELECT id, nombre, zona, potencia_kw, num_paneles, cliente, direccion, activa, created_at, updated_at
                FROM tb_calculadora_plantas
                ORDER BY nombre
                LIMIT 500
            """)
        return [dict(r) for r in rows]

    async def get_planta_by_id(self, conn, planta_id: str) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT id, nombre, zona, potencia_kw, num_paneles, cliente, direccion, activa, created_at, updated_at
            FROM tb_calculadora_plantas
            WHERE id = $1
        """, planta_id)
        return dict(row) if row else None

    async def upsert_planta(self, conn, planta: dict) -> bool:
        """Inserta o actualiza una planta. Retorna True si fue un INSERT nuevo, False si fue UPDATE."""
        row = await conn.fetchrow("""
            INSERT INTO tb_calculadora_plantas (id, nombre, zona, potencia_kw, num_paneles, cliente, direccion, activa, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (id) DO UPDATE SET
                nombre      = EXCLUDED.nombre,
                zona        = EXCLUDED.zona,
                potencia_kw = EXCLUDED.potencia_kw,
                num_paneles = EXCLUDED.num_paneles,
                cliente     = EXCLUDED.cliente,
                direccion   = EXCLUDED.direccion,
                activa      = EXCLUDED.activa,
                updated_at  = NOW()
            RETURNING (xmax = 0) AS was_insert
        """, planta["id"], planta["nombre"], planta["zona"],
             planta.get("potencia_kw"), planta.get("num_paneles"),
             planta.get("cliente"), planta.get("direccion"),
             planta.get("activa", True))
        return bool(row["was_insert"])

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

    async def get_usuarios_comercial(self, conn) -> list:
        """Usuarios con acceso al módulo comercial (para dropdown de solicitante)."""
        rows = await conn.fetch("""
            SELECT DISTINCT u.id_usuario AS id, u.nombre
            FROM tb_usuarios u
            WHERE u.rol_sistema IN ('ADMIN', 'MANAGER')
               OR EXISTS (
                    SELECT 1 FROM tb_permisos_modulos pm
                    WHERE pm.usuario_id = u.id_usuario
                      AND pm.modulo_slug = 'comercial'
                )
            ORDER BY u.nombre
        """)
        return [dict(r) for r in rows]

    async def save_cotizacion(self, conn, data: dict) -> UUID:
        new_id = uuid4()
        await conn.execute("""
            INSERT INTO tb_calculadora_cotizaciones
                (id, planta_id, nombre_planta, tipo_poliza, utilidad,
                 sub_total, sub_total_utilidad, total_final, resultado_json,
                 creado_por, solicitante_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """, new_id,
             data.get("planta_id"), data["nombre_planta"], data["tipo_poliza"],
             data["utilidad"], data["sub_total"], data["sub_total_utilidad"],
             data["total_final"], json.dumps(data["resultado_json"]),
             data.get("creado_por"), data.get("solicitante_id"))
        return new_id

    async def get_cotizaciones(self, conn, limit: int = 100, offset: int = 0,
                               estatus_filter: Optional[str] = None) -> list:
        rows = await conn.fetch("""
            SELECT
                c.id, c.planta_id, c.nombre_planta, c.tipo_poliza, c.utilidad,
                c.sub_total, c.sub_total_utilidad, c.total_final,
                c.resultado_json, c.creado_por, c.created_at,
                c.estatus, c.estatus_updated_at, c.solicitante_id,
                u.nombre AS creado_por_nombre,
                s.nombre AS solicitante_nombre
            FROM tb_calculadora_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            LEFT JOIN tb_usuarios s ON s.id_usuario = c.solicitante_id
            WHERE ($3::text IS NULL OR c.estatus = $3)
            ORDER BY c.created_at DESC
            LIMIT $1 OFFSET $2
        """, limit, offset, estatus_filter)
        return [dict(r) for r in rows]

    async def get_cotizaciones_comercial(
        self, conn, limit: int = 50, offset: int = 0,
        ver_todas: bool = False, user_id=None,
        estatus_filter: Optional[str] = None,
    ) -> list:
        """Cotizaciones para la vista de Comercial. Si ver_todas=True muestra todas; si no, solo las del solicitante."""
        conditions = []
        params: list = [limit, offset]

        if not ver_todas and user_id:
            params.append(user_id)
            conditions.append(f"c.solicitante_id = ${len(params)}")

        if estatus_filter:
            params.append(estatus_filter)
            conditions.append(f"c.estatus = ${len(params)}")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        rows = await conn.fetch(f"""
            SELECT
                c.id, c.planta_id, c.nombre_planta, c.tipo_poliza, c.utilidad,
                c.sub_total, c.sub_total_utilidad, c.total_final,
                c.resultado_json, c.creado_por, c.created_at,
                c.estatus, c.estatus_updated_at, c.solicitante_id,
                u.nombre AS creado_por_nombre,
                s.nombre AS solicitante_nombre
            FROM tb_calculadora_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            LEFT JOIN tb_usuarios s ON s.id_usuario = c.solicitante_id
            {where}
            ORDER BY c.created_at DESC
            LIMIT $1 OFFSET $2
        """, *params)
        return [dict(r) for r in rows]

    async def count_cotizaciones_comercial(
        self, conn, ver_todas: bool = False, user_id=None,
        estatus_filter: Optional[str] = None,
    ) -> int:
        conditions = []
        params: list = []

        if not ver_todas and user_id:
            params.append(user_id)
            conditions.append(f"solicitante_id = ${len(params)}")

        if estatus_filter:
            params.append(estatus_filter)
            conditions.append(f"estatus = ${len(params)}")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return await conn.fetchval(
            f"SELECT COUNT(*) FROM tb_calculadora_cotizaciones {where}", *params
        )

    async def count_cotizaciones(self, conn, estatus_filter: Optional[str] = None) -> int:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM tb_calculadora_cotizaciones WHERE ($1::text IS NULL OR estatus = $1)",
            estatus_filter,
        )

    async def get_resumen_estatus(self, conn) -> dict:
        rows = await conn.fetch("""
            SELECT estatus, COUNT(*) AS total
            FROM tb_calculadora_cotizaciones
            GROUP BY estatus
        """)
        result: dict = {"total": 0}
        for r in rows:
            result[r["estatus"]] = int(r["total"])
            result["total"] += int(r["total"])
        return result

    async def get_cotizacion_by_id(self, conn, cotizacion_id) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT c.id, c.planta_id, c.nombre_planta, c.tipo_poliza, c.utilidad,
                   c.sub_total, c.sub_total_utilidad, c.total_final,
                   c.resultado_json, c.creado_por, c.created_at,
                   c.estatus, c.estatus_updated_at, c.updated_at,
                   c.solicitante_id,
                   u.nombre AS creado_por_nombre,
                   s.nombre AS solicitante_nombre
            FROM tb_calculadora_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            LEFT JOIN tb_usuarios s ON s.id_usuario = c.solicitante_id
            WHERE c.id = $1
        """, cotizacion_id)
        return dict(row) if row else None

    async def update_cotizacion_full(self, conn, cotizacion_id, data: dict) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_cotizaciones
            SET planta_id         = $2,
                nombre_planta     = $3,
                tipo_poliza       = $4,
                utilidad          = $5,
                sub_total         = $6,
                sub_total_utilidad = $7,
                total_final       = $8,
                resultado_json    = $9,
                solicitante_id    = $10,
                updated_at        = NOW()
            WHERE id = $1
        """, cotizacion_id,
             data.get("planta_id"), data["nombre_planta"], data["tipo_poliza"],
             data["utilidad"], data["sub_total"], data["sub_total_utilidad"],
             data["total_final"], json.dumps(data["resultado_json"]),
             data.get("solicitante_id"))
        return result != "UPDATE 0"

    async def update_cotizacion_asignacion(self, conn, cotizacion_id, solicitante_id, estatus: str, user_id) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_cotizaciones
            SET solicitante_id       = $2,
                estatus              = $3,
                estatus_updated_at   = NOW(),
                estatus_updated_by   = $4,
                updated_at           = NOW()
            WHERE id = $1
        """, cotizacion_id, solicitante_id, estatus, user_id)
        return result != "UPDATE 0"

    async def update_cotizacion_estatus(self, conn, cotizacion_id, estatus: str, user_id) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_cotizaciones
            SET estatus = $2, estatus_updated_at = NOW(), estatus_updated_by = $3
            WHERE id = $1
        """, cotizacion_id, estatus, user_id)
        return result != "UPDATE 0"
