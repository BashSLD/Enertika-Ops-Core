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
            SELECT id, nombre, zona, potencia_kw, num_paneles, cliente, direccion, es_externa
            FROM tb_calculadora_plantas
            WHERE activa = TRUE
            ORDER BY nombre
        """)
        return [dict(r) for r in rows]

    async def get_plantas_list(self, conn, q: Optional[str] = None) -> list:
        filter_clause = ""
        params: list = []
        if q:
            params.append(f"%{q}%")
            filter_clause = (
                "WHERE p.nombre ILIKE $1 OR p.zona ILIKE $1 "
                "OR p.id ILIKE $1 OR p.cliente ILIKE $1"
            )

        query = f"""
            SELECT
                p.id, p.nombre, p.zona, p.potencia_kw, p.num_paneles, p.cliente, p.direccion,
                p.es_externa, p.activa, p.created_at, p.updated_at,
                -- Póliza con cobertura hoy (ACEPTADA o TERMINADA dentro de su rango de fechas)
                vig.id::text              AS poliza_vigente_id,
                vig.estatus               AS poliza_vigente_estatus,
                vig.tipo_poliza           AS poliza_vigente_tipo,
                vig.fecha_fin_poliza      AS poliza_vigente_fin,
                (vig.fecha_fin_poliza - CURRENT_DATE)::int AS poliza_vigente_dias,
                -- Próxima póliza programada (ACEPTADA con inicio futuro)
                prox.id::text             AS poliza_proxima_id,
                prox.fecha_inicio_poliza  AS poliza_proxima_inicio
            FROM tb_calculadora_plantas p
            LEFT JOIN LATERAL (
                SELECT id, estatus, tipo_poliza, fecha_inicio_poliza, fecha_fin_poliza
                FROM tb_calculadora_cotizaciones
                WHERE planta_id = p.id
                  AND estatus IN ('ACEPTADA', 'TERMINADA')
                  AND fecha_inicio_poliza <= CURRENT_DATE
                  AND (fecha_fin_poliza IS NULL OR fecha_fin_poliza >= CURRENT_DATE)
                ORDER BY fecha_fin_poliza DESC NULLS LAST
                LIMIT 1
            ) vig ON TRUE
            LEFT JOIN LATERAL (
                SELECT id, fecha_inicio_poliza
                FROM tb_calculadora_cotizaciones
                WHERE planta_id = p.id
                  AND estatus = 'ACEPTADA'
                  AND fecha_inicio_poliza > CURRENT_DATE
                ORDER BY fecha_inicio_poliza ASC
                LIMIT 1
            ) prox ON TRUE
            {filter_clause}
            ORDER BY p.nombre
            LIMIT 500
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_planta_by_id(self, conn, planta_id: str) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT id, nombre, zona, potencia_kw, num_paneles, cliente, direccion,
                   es_externa, activa, created_at, updated_at
            FROM tb_calculadora_plantas
            WHERE id = $1
        """, planta_id)
        return dict(row) if row else None

    async def upsert_planta(self, conn, planta: dict) -> bool:
        """Inserta o actualiza una planta. Retorna True si fue un INSERT nuevo, False si fue UPDATE."""
        row = await conn.fetchrow("""
            INSERT INTO tb_calculadora_plantas
                (id, nombre, zona, potencia_kw, num_paneles, cliente, direccion, es_externa, activa, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (id) DO UPDATE SET
                nombre      = EXCLUDED.nombre,
                zona        = EXCLUDED.zona,
                potencia_kw = EXCLUDED.potencia_kw,
                num_paneles = EXCLUDED.num_paneles,
                cliente     = EXCLUDED.cliente,
                direccion   = EXCLUDED.direccion,
                es_externa  = EXCLUDED.es_externa,
                activa      = EXCLUDED.activa,
                updated_at  = NOW()
            RETURNING (xmax = 0) AS was_insert
        """, planta["id"], planta["nombre"], planta["zona"],
             planta.get("potencia_kw"), planta.get("num_paneles"),
             planta.get("cliente"), planta.get("direccion"),
             planta.get("es_externa", False),
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

    async def update_costo_fijo(self, conn, concepto: str, valor: float, notas: Optional[str] = None) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_costos_fijos
            SET valor = $2, notas = $3, updated_at = NOW()
            WHERE concepto = $1
        """, concepto, valor, notas)
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
                 creado_por, solicitante_id, descuento_pct, descuento_anios,
                 fecha_inicio_poliza, fecha_fin_poliza,
                 poliza_anterior_id, fecha_fin_poliza_anterior,
                 descuento_pct_1, descuento_pct_3, descuento_pct_5,
                 vigencia_cotizacion_dias)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
        """, new_id,
             data.get("planta_id"), data["nombre_planta"], data["tipo_poliza"],
             data["utilidad"], data["sub_total"], data["sub_total_utilidad"],
             data["total_final"], json.dumps(data["resultado_json"]),
             data.get("creado_por"), data.get("solicitante_id"),
             data.get("descuento_pct"), data.get("descuento_anios"),
             data.get("fecha_inicio_poliza"), data.get("fecha_fin_poliza"),
             data.get("poliza_anterior_id"), data.get("fecha_fin_poliza_anterior"),
             data.get("descuento_pct_1"), data.get("descuento_pct_3"), data.get("descuento_pct_5"),
             data.get("vigencia_cotizacion_dias"))
        return new_id

    async def get_cotizaciones(self, conn, limit: int = 15,
                               estatus_filter: Optional[str] = None,
                               planta_filter: Optional[str] = None,
                               tipo_filter: Optional[str] = None,
                               solicitante_id_filter: Optional[str] = None) -> list:
        query = """
            SELECT
                c.id, c.planta_id, c.nombre_planta, c.tipo_poliza, c.utilidad,
                c.sub_total, c.sub_total_utilidad, c.total_final,
                c.resultado_json, c.creado_por, c.created_at,
                c.estatus, c.estatus_updated_at, c.solicitante_id,
                c.fecha_inicio_poliza, c.fecha_fin_poliza,
                c.vigencia_cotizacion_dias,
                (c.created_at::date + COALESCE(c.vigencia_cotizacion_dias, 30) * INTERVAL '1 day')::date
                    AS fecha_vencimiento_cotizacion,
                u.nombre AS creado_por_nombre,
                s.nombre AS solicitante_nombre
            FROM tb_calculadora_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            LEFT JOIN tb_usuarios s ON s.id_usuario = c.solicitante_id
            WHERE ($1::text IS NULL 
                   OR ($1::text = 'COT_VENCE' AND c.estatus IN ('CREADA', 'ENVIADA', 'EN_NEGOCIACION') 
                       AND (c.created_at::date + COALESCE(c.vigencia_cotizacion_dias, 30) * INTERVAL '1 day')::date >= CURRENT_DATE 
                       AND (c.created_at::date + COALESCE(c.vigencia_cotizacion_dias, 30) * INTERVAL '1 day')::date <= CURRENT_DATE + INTERVAL '7 days')
                   OR c.estatus = $1)
              AND ($2::text IS NULL OR c.nombre_planta = $2)
              AND ($3::text IS NULL OR c.tipo_poliza = $3)
              AND ($4::text IS NULL OR c.solicitante_id::text = $4)
            ORDER BY c.created_at DESC
        """
        if limit > 0:
            query += f" LIMIT {limit}"
        rows = await conn.fetch(query, estatus_filter, planta_filter, tipo_filter, solicitante_id_filter)
        return [dict(r) for r in rows]

    async def get_polizas_filter_options(self, conn) -> dict:
        plantas = await conn.fetch("""
            SELECT DISTINCT nombre_planta
            FROM tb_calculadora_cotizaciones
            WHERE nombre_planta IS NOT NULL
            ORDER BY nombre_planta
        """)
        solicitantes = await conn.fetch("""
            SELECT DISTINCT c.solicitante_id::text, s.nombre AS solicitante_nombre
            FROM tb_calculadora_cotizaciones c
            JOIN tb_usuarios s ON s.id_usuario = c.solicitante_id
            WHERE s.nombre IS NOT NULL
            ORDER BY s.nombre
        """)
        return {
            "plantas": [r["nombre_planta"] for r in plantas],
            "solicitantes": [{"id": r["solicitante_id"], "nombre": r["solicitante_nombre"]} for r in solicitantes],
        }

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
                c.fecha_inicio_poliza, c.fecha_fin_poliza,
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

    async def count_cotizaciones(self, conn, estatus_filter: Optional[str] = None,
                                planta_filter: Optional[str] = None,
                                tipo_filter: Optional[str] = None,
                                solicitante_id_filter: Optional[str] = None) -> int:
        return await conn.fetchval("""
            SELECT COUNT(*)
            FROM tb_calculadora_cotizaciones c
            LEFT JOIN tb_usuarios s ON s.id_usuario = c.solicitante_id
            WHERE ($1::text IS NULL OR c.estatus = $1)
              AND ($2::text IS NULL OR c.nombre_planta = $2)
              AND ($3::text IS NULL OR c.tipo_poliza = $3)
              AND ($4::text IS NULL OR c.solicitante_id::text = $4)
        """, estatus_filter, planta_filter, tipo_filter, solicitante_id_filter)

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

    async def get_alertas_vencimiento(self, conn) -> dict:
        """Cuenta pólizas ACEPTADAS que vencen en ≤30 días y cotizaciones activas
        cuya validez expira en ≤7 días. Una sola query para máxima eficiencia."""
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (
                    WHERE estatus = 'ACEPTADA'
                      AND fecha_fin_poliza IS NOT NULL
                      AND fecha_fin_poliza >= CURRENT_DATE
                      AND fecha_fin_poliza <= CURRENT_DATE + INTERVAL '30 days'
                ) AS polizas_por_vencer,
                COUNT(*) FILTER (
                    WHERE estatus IN ('CREADA', 'ENVIADA', 'EN_NEGOCIACION')
                      AND (created_at::date
                           + COALESCE(vigencia_cotizacion_dias, 30) * INTERVAL '1 day'
                          )::date >= CURRENT_DATE
                      AND (created_at::date
                           + COALESCE(vigencia_cotizacion_dias, 30) * INTERVAL '1 day'
                          )::date <= CURRENT_DATE + INTERVAL '7 days'
                ) AS cotizaciones_por_vencer
            FROM tb_calculadora_cotizaciones
        """)
        return {
            "polizas_por_vencer":    int(row["polizas_por_vencer"])    if row else 0,
            "cotizaciones_por_vencer": int(row["cotizaciones_por_vencer"]) if row else 0,
        }

    async def get_cotizacion_by_id(self, conn, cotizacion_id) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT c.id, c.planta_id, c.nombre_planta, c.tipo_poliza, c.utilidad,
                   c.sub_total, c.sub_total_utilidad, c.total_final,
                   c.resultado_json, c.creado_por, c.created_at,
                   c.estatus, c.estatus_updated_at, c.updated_at,
                   c.solicitante_id, c.descuento_pct, c.descuento_anios,
                   c.descuento_pct_1, c.descuento_pct_3, c.descuento_pct_5,
                   c.fecha_inicio_poliza, c.fecha_fin_poliza,
                   c.poliza_anterior_id, c.fecha_fin_poliza_anterior,
                   c.anios_contratados, c.vigencia_cotizacion_dias,
                   ant.fecha_fin_poliza AS anterior_fecha_fin,
                   u.nombre AS creado_por_nombre,
                   s.nombre AS solicitante_nombre
            FROM tb_calculadora_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            LEFT JOIN tb_usuarios s ON s.id_usuario = c.solicitante_id
            LEFT JOIN tb_calculadora_cotizaciones ant ON ant.id = c.poliza_anterior_id
            WHERE c.id = $1
        """, cotizacion_id)
        return dict(row) if row else None

    async def update_cotizacion_full(self, conn, cotizacion_id, data: dict) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_cotizaciones
            SET planta_id                 = $2,
                nombre_planta             = $3,
                tipo_poliza               = $4,
                utilidad                  = $5,
                sub_total                 = $6,
                sub_total_utilidad        = $7,
                total_final               = $8,
                resultado_json            = $9,
                solicitante_id            = $10,
                descuento_pct             = $11,
                descuento_anios           = $12,
                fecha_inicio_poliza       = $13,
                fecha_fin_poliza          = $14,
                poliza_anterior_id        = $15,
                fecha_fin_poliza_anterior = $16,
                descuento_pct_1           = $17,
                descuento_pct_3           = $18,
                descuento_pct_5           = $19,
                updated_at                = NOW()
            WHERE id = $1
        """, cotizacion_id,
             data.get("planta_id"), data["nombre_planta"], data["tipo_poliza"],
             data["utilidad"], data["sub_total"], data["sub_total_utilidad"],
             data["total_final"], json.dumps(data["resultado_json"]),
             data.get("solicitante_id"),
             data.get("descuento_pct"), data.get("descuento_anios"),
             data.get("fecha_inicio_poliza"), data.get("fecha_fin_poliza"),
             data.get("poliza_anterior_id"), data.get("fecha_fin_poliza_anterior"),
             data.get("descuento_pct_1"), data.get("descuento_pct_3"), data.get("descuento_pct_5"))
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

    async def update_cotizacion_estatus(self, conn, cotizacion_id, estatus: str, user_id,
                                        fecha_inicio=None, fecha_fin=None,
                                        anios_contratados=None,
                                        motivo_cancelacion=None) -> bool:
        result = await conn.execute("""
            UPDATE tb_calculadora_cotizaciones
            SET estatus              = $2,
                estatus_updated_at   = NOW(),
                estatus_updated_by   = $3,
                fecha_inicio_poliza  = COALESCE($4, fecha_inicio_poliza),
                fecha_fin_poliza     = COALESCE($5, fecha_fin_poliza),
                anios_contratados    = COALESCE($6, anios_contratados),
                motivo_cancelacion   = COALESCE($7, motivo_cancelacion)
            WHERE id = $1
        """, cotizacion_id, estatus, user_id, fecha_inicio, fecha_fin,
             anios_contratados, motivo_cancelacion)
        return result != "UPDATE 0"

    async def terminar_poliza_anterior(self, conn, poliza_anterior_id, user_id) -> None:
        """Marca la póliza anterior como TERMINADA al aceptar una renovación."""
        await conn.execute("""
            UPDATE tb_calculadora_cotizaciones
            SET estatus            = 'TERMINADA',
                estatus_updated_at = NOW(),
                estatus_updated_by = $2
            WHERE id = $1 AND estatus = 'ACEPTADA'
        """, poliza_anterior_id, user_id)

    async def check_solapamiento_poliza(self, conn, planta_id: str,
                                         fecha_inicio, fecha_fin,
                                         exclude_id=None) -> Optional[str]:
        """
        Retorna el id de una póliza existente (ACEPTADA o TERMINADA) cuyo rango
        de fechas se solapa con [fecha_inicio, fecha_fin]. None si no hay solapamiento.
        """
        if exclude_id:
            row = await conn.fetchrow("""
                SELECT id::text
                FROM tb_calculadora_cotizaciones
                WHERE planta_id = $1
                  AND estatus IN ('ACEPTADA', 'TERMINADA')
                  AND id != $2
                  AND fecha_inicio_poliza IS NOT NULL
                  AND fecha_fin_poliza    IS NOT NULL
                  AND fecha_inicio_poliza <= $4
                  AND fecha_fin_poliza    >= $3
                LIMIT 1
            """, planta_id, exclude_id, fecha_inicio, fecha_fin)
        else:
            row = await conn.fetchrow("""
                SELECT id::text
                FROM tb_calculadora_cotizaciones
                WHERE planta_id = $1
                  AND estatus IN ('ACEPTADA', 'TERMINADA')
                  AND fecha_inicio_poliza IS NOT NULL
                  AND fecha_fin_poliza    IS NOT NULL
                  AND fecha_inicio_poliza <= $3
                  AND fecha_fin_poliza    >= $2
                LIMIT 1
            """, planta_id, fecha_inicio, fecha_fin)
        return row["id"] if row else None
