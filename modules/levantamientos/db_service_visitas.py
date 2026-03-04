# ==============================================================
# modules/levantamientos/db_service_visitas.py
# Capa de queries para el sub-módulo Visitas de Campo.
# Consume tb_visitas_campo, tb_visita_campo_levantamientos,
# tb_visita_campo_viaticos y tb_visita_campo_envios.
# ==============================================================

import json
import logging
from typing import List, Optional
from uuid import UUID

logger = logging.getLogger("Levantamientos.VisitasCampoDBService")


class VisitasCampoDBService:
    """
    Queries SQL para el módulo Visitas de Campo.
    Todos los métodos reciben `conn` como primer argumento
    (conexión asyncpg obtenida via get_db_connection).
    """

    # ----------------------------------------------------------
    # CREAR VISITA
    # ----------------------------------------------------------

    async def create_visita(
        self,
        conn,
        nombre: Optional[str],
        fecha_inicio,
        fecha_fin,
        levantamiento_ids: List[UUID],
        creado_por_id: UUID,
    ) -> dict:
        """
        INSERT en tb_visitas_campo y luego INSERT batch en el pivot.
        Retorna el registro completo de la visita recién creada.
        """
        row = await conn.fetchrow("""
            INSERT INTO tb_visitas_campo (nombre, fecha_inicio, fecha_fin, creado_por_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id_visita, nombre, fecha_inicio, fecha_fin, creado_por_id, created_at
        """, nombre or None, fecha_inicio, fecha_fin, creado_por_id)

        id_visita = row["id_visita"]

        # Batch insert de levantamientos en el pivot
        if levantamiento_ids:
            await conn.executemany("""
                INSERT INTO tb_visita_campo_levantamientos (id_visita, id_levantamiento)
                VALUES ($1, $2)
                ON CONFLICT (id_visita, id_levantamiento) DO NOTHING
            """, [(id_visita, lev_id) for lev_id in levantamiento_ids])

        return dict(row)

    # ----------------------------------------------------------
    # LEER VISITA
    # ----------------------------------------------------------

    async def get_visita(self, conn, id_visita: UUID) -> Optional[dict]:
        """
        Datos de la visita con conteo de levantamientos y total de viáticos.
        """
        row = await conn.fetchrow("""
            SELECT
                v.id_visita,
                v.nombre,
                v.fecha_inicio AT TIME ZONE 'America/Mexico_City' AS fecha_inicio,
                v.fecha_fin    AT TIME ZONE 'America/Mexico_City' AS fecha_fin,
                v.created_at   AT TIME ZONE 'America/Mexico_City' AS created_at,
                u.nombre AS creado_por_nombre,
                COUNT(DISTINCT vcl.id_levantamiento)  AS num_levantamientos,
                COALESCE(SUM(vcv.monto), 0)           AS total_viaticos
            FROM tb_visitas_campo v
            LEFT JOIN tb_usuarios u
                ON v.creado_por_id = u.id_usuario
            LEFT JOIN tb_visita_campo_levantamientos vcl
                ON v.id_visita = vcl.id_visita
            LEFT JOIN tb_visita_campo_viaticos vcv
                ON v.id_visita = vcv.id_visita
            WHERE v.id_visita = $1
            GROUP BY v.id_visita, v.nombre, v.fecha_inicio, v.fecha_fin,
                     v.created_at, u.nombre
        """, id_visita)
        return dict(row) if row else None

    async def get_levantamientos_en_visita(self, conn, id_visita: UUID) -> List[dict]:
        """
        Lista de levantamientos vinculados a la visita con datos de
        oportunidad, sitio y estatus. Incluye info de tecnicos asignados.
        """
        rows = await conn.fetch("""
            SELECT
                l.id_levantamiento,
                l.id_oportunidad,
                l.fecha_visita_programada AT TIME ZONE 'America/Mexico_City' AS fecha_visita_programada,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                o.direccion_obra,
                s.nombre_sitio,
                s.direccion AS sitio_direccion,
                est.nombre  AS estatus_nombre,
                est.color_hex AS estatus_color,
                COALESCE(techs.nombres, u_tec.nombre) AS tecnico_nombre
            FROM tb_visita_campo_levantamientos vcl
            JOIN tb_levantamientos l
                ON vcl.id_levantamiento = l.id_levantamiento
            JOIN tb_oportunidades o
                ON l.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_sitios_oportunidad s
                ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_usuarios u_tec
                ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT JOIN tb_cat_estatus_levantamiento est
                ON l.id_estatus_global = est.id
            LEFT JOIN LATERAL (
                SELECT string_agg(u.nombre, ', ') AS nombres
                FROM tb_levantamiento_asignaciones la
                JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
                WHERE la.id_levantamiento = l.id_levantamiento
            ) techs ON true
            WHERE vcl.id_visita = $1
            ORDER BY o.op_id_estandar, s.nombre_sitio
        """, id_visita)
        return [dict(r) for r in rows]

    async def get_visitas_for_levantamiento(self, conn, id_levantamiento: UUID) -> List[dict]:
        """
        Retorna las visitas de campo que contienen este levantamiento.
        Útil para mostrar el indicador en el modal de viáticos individuales.
        """
        rows = await conn.fetch("""
            SELECT
                v.id_visita,
                v.nombre,
                v.fecha_inicio AT TIME ZONE 'America/Mexico_City' AS fecha_inicio,
                v.fecha_fin    AT TIME ZONE 'America/Mexico_City' AS fecha_fin,
                COUNT(DISTINCT vcl2.id_levantamiento) AS num_levantamientos,
                COALESCE(SUM(vcv.monto), 0)           AS total_viaticos
            FROM tb_visita_campo_levantamientos vcl
            JOIN tb_visitas_campo v
                ON vcl.id_visita = v.id_visita
            LEFT JOIN tb_visita_campo_levantamientos vcl2
                ON v.id_visita = vcl2.id_visita
            LEFT JOIN tb_visita_campo_viaticos vcv
                ON v.id_visita = vcv.id_visita
            WHERE vcl.id_levantamiento = $1
            GROUP BY v.id_visita, v.nombre, v.fecha_inicio, v.fecha_fin
            ORDER BY v.fecha_inicio DESC
        """, id_levantamiento)
        return [dict(r) for r in rows]

    async def get_levantamientos_disponibles(
        self, conn, search: Optional[str] = None
    ) -> List[dict]:
        """
        Levantamientos activos para el selector multi-check del modal de nueva visita.
        Filtra por búsqueda de texto en op_id_estandar, cliente, proyecto o nombre_sitio.
        """
        params: list = []
        where_conditions = ["o.email_enviado = true", "est.es_estatus_final = FALSE"]

        if search:
            params.append(f"%{search.strip()}%")
            idx = len(params)
            where_conditions.append(f"""(
                o.op_id_estandar ILIKE ${idx}
                OR o.cliente_nombre ILIKE ${idx}
                OR o.nombre_proyecto ILIKE ${idx}
                OR s.nombre_sitio ILIKE ${idx}
            )""")

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT
                l.id_levantamiento,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                s.nombre_sitio,
                est.nombre    AS estatus_nombre,
                est.color_hex AS estatus_color,
                est.codigo    AS estatus_codigo
            FROM tb_levantamientos l
            JOIN tb_oportunidades o
                ON l.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_sitios_oportunidad s
                ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_cat_estatus_levantamiento est
                ON l.id_estatus_global = est.id
            WHERE {where_clause}
            ORDER BY o.op_id_estandar, s.nombre_sitio
            LIMIT 200
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    # ----------------------------------------------------------
    # VIÁTICOS DE LA VISITA — CRUD
    # ----------------------------------------------------------

    async def create_viatico_visita(
        self,
        conn,
        id_visita: UUID,
        usuario_id: Optional[UUID],
        concepto: str,
        monto: float,
        created_by_id: UUID,
    ) -> dict:
        """
        Inserta un viático en la visita y retorna la fila con nombre de usuario.
        """
        row = await conn.fetchrow("""
            WITH nuevo AS (
                INSERT INTO tb_visita_campo_viaticos
                    (id_visita, usuario_id, concepto, monto, created_by_id)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
            )
            SELECT
                nuevo.id,
                nuevo.usuario_id,
                u.nombre AS usuario_nombre,
                nuevo.concepto,
                nuevo.monto,
                nuevo.created_at
            FROM nuevo
            LEFT JOIN tb_usuarios u ON nuevo.usuario_id = u.id_usuario
        """, id_visita, usuario_id, concepto, monto, created_by_id)
        return dict(row) if row else None

    async def delete_viatico_visita(
        self, conn, id_visita: UUID, id_viatico: UUID
    ) -> bool:
        """Elimina un viático de la visita. Retorna True si existió y se borró."""
        status = await conn.execute("""
            DELETE FROM tb_visita_campo_viaticos
            WHERE id = $1 AND id_visita = $2
        """, id_viatico, id_visita)
        return status == "DELETE 1"

    async def get_viaticos_visita(self, conn, id_visita: UUID) -> List[dict]:
        """Lista de viáticos activos de la visita, orden por fecha de creación."""
        rows = await conn.fetch("""
            SELECT
                v.id,
                v.usuario_id,
                u.nombre AS usuario_nombre,
                v.concepto,
                v.monto,
                v.created_at
            FROM tb_visita_campo_viaticos v
            LEFT JOIN tb_usuarios u ON v.usuario_id = u.id_usuario
            WHERE v.id_visita = $1
            ORDER BY v.created_at ASC
        """, id_visita)
        return [dict(r) for r in rows]

    async def get_usuarios_para_visita(self, conn, id_visita: UUID) -> List[dict]:
        """
        Usuarios técnicos de los levantamientos vinculados a la visita.
        Fallback a todos los activos si no hay asignaciones.
        """
        rows = await conn.fetch("""
            SELECT DISTINCT u.id_usuario, u.nombre, u.email
            FROM tb_usuarios u
            WHERE u.id_usuario IN (
                SELECT la.tecnico_id
                FROM tb_levantamiento_asignaciones la
                JOIN tb_visita_campo_levantamientos vcl
                    ON la.id_levantamiento = vcl.id_levantamiento
                WHERE vcl.id_visita = $1
                UNION
                SELECT l.jefe_area_id
                FROM tb_levantamientos l
                JOIN tb_visita_campo_levantamientos vcl
                    ON l.id_levantamiento = vcl.id_levantamiento
                WHERE vcl.id_visita = $1
                  AND l.jefe_area_id IS NOT NULL
            ) AND u.is_active = true
            ORDER BY u.nombre ASC
        """, id_visita)

        return [dict(r) for r in rows]

    # ----------------------------------------------------------
    # HISTORIAL DE ENVÍOS
    # ----------------------------------------------------------

    async def insert_envio_visita(
        self,
        conn,
        id_visita: UUID,
        enviado_por_id: UUID,
        enviado_por_nombre: str,
        to_destinatarios: List[str],
        cc_destinatarios: List[str],
        snapshot: dict,
        total_monto: float,
        estatus: str = "enviado",
        error_detalle: Optional[str] = None,
    ) -> dict:
        """Registra un envío en el historial con snapshot completo."""
        row = await conn.fetchrow("""
            INSERT INTO tb_visita_campo_envios (
                id_visita,
                enviado_por_id,
                enviado_por_nombre,
                fecha_envio,
                to_destinatarios,
                cc_destinatarios,
                snapshot,
                total_monto,
                estatus,
                error_detalle
            )
            VALUES ($1, $2, $3, now(), $4, $5, $6::jsonb, $7, $8, $9)
            RETURNING *
        """,
            id_visita,
            enviado_por_id,
            enviado_por_nombre,
            to_destinatarios,
            cc_destinatarios,
            json.dumps(snapshot),
            total_monto,
            estatus,
            error_detalle,
        )
        return dict(row) if row else None

    async def get_envios_visita(self, conn, id_visita: UUID) -> List[dict]:
        """Historial de envíos de la visita, más reciente primero."""
        rows = await conn.fetch("""
            SELECT
                id,
                enviado_por_nombre,
                fecha_envio AT TIME ZONE 'America/Mexico_City' AS fecha_envio,
                to_destinatarios,
                cc_destinatarios,
                snapshot,
                total_monto,
                estatus,
                error_detalle
            FROM tb_visita_campo_envios
            WHERE id_visita = $1
            ORDER BY fecha_envio DESC
        """, id_visita)
        return [dict(r) for r in rows]

    # ----------------------------------------------------------
    # ELIMINAR VISITA (cambio 3)
    # ----------------------------------------------------------

    async def delete_visita(self, conn, id_visita: UUID) -> bool:
        """
        Elimina la visita y todo lo relacionado por CASCADE:
        tb_visita_campo_levantamientos, tb_visita_campo_viaticos,
        tb_visita_campo_envios.
        Retorna True si existia y se borro.
        """
        status = await conn.execute("""
            DELETE FROM tb_visitas_campo WHERE id_visita = $1
        """, id_visita)
        return status == "DELETE 1"

    # ----------------------------------------------------------
    # EDITAR PERIODO (cambio 4)
    # ----------------------------------------------------------

    async def update_periodo_visita(
        self, conn, id_visita: UUID, fecha_inicio, fecha_fin
    ) -> bool:
        """
        Actualiza fecha_inicio y fecha_fin de la visita.
        Retorna True si la visita existia y se actualizo.
        """
        status = await conn.execute("""
            UPDATE tb_visitas_campo
            SET fecha_inicio = $2,
                fecha_fin    = $3,
                updated_at   = NOW()
            WHERE id_visita = $1
        """, id_visita, fecha_inicio, fecha_fin)
        return status == "UPDATE 1"

    # ----------------------------------------------------------
    # AGREGAR LEVANTAMIENTOS A VISITA EXISTENTE (cambio 2)
    # ----------------------------------------------------------

    async def get_levantamientos_disponibles_para_agregar(
        self, conn, id_visita: UUID, search: Optional[str] = None
    ) -> List[dict]:
        """
        Igual que get_levantamientos_disponibles() pero excluye los
        levantamientos que ya estan vinculados a esta visita.
        Tambien excluye estatus finales (completado, entregado, cancelado).
        """
        params: list = [id_visita]
        where_conditions = [
            "o.email_enviado = true",
            "est.es_estatus_final = FALSE",
            """l.id_levantamiento NOT IN (
                SELECT id_levantamiento
                FROM tb_visita_campo_levantamientos
                WHERE id_visita = $1
            )""",
        ]

        if search:
            params.append(f"%{search.strip()}%")
            idx = len(params)
            where_conditions.append(f"""(
                o.op_id_estandar ILIKE ${idx}
                OR o.cliente_nombre ILIKE ${idx}
                OR o.nombre_proyecto ILIKE ${idx}
                OR s.nombre_sitio ILIKE ${idx}
            )""")

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT
                l.id_levantamiento,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                s.nombre_sitio,
                est.nombre    AS estatus_nombre,
                est.color_hex AS estatus_color,
                est.codigo    AS estatus_codigo
            FROM tb_levantamientos l
            JOIN tb_oportunidades o
                ON l.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_sitios_oportunidad s
                ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_cat_estatus_levantamiento est
                ON l.id_estatus_global = est.id
            WHERE {where_clause}
            ORDER BY o.op_id_estandar, s.nombre_sitio
            LIMIT 200
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def add_levantamientos_to_visita(
        self, conn, id_visita: UUID, levantamiento_ids: List[UUID]
    ) -> int:
        """
        Agrega nuevos levantamientos a una visita existente.
        Usa ON CONFLICT DO NOTHING para evitar duplicados.
        Retorna el numero de filas insertadas.
        """
        if not levantamiento_ids:
            return 0
        await conn.executemany("""
            INSERT INTO tb_visita_campo_levantamientos (id_visita, id_levantamiento)
            VALUES ($1, $2)
            ON CONFLICT (id_visita, id_levantamiento) DO NOTHING
        """, [(id_visita, lev_id) for lev_id in levantamiento_ids])
        return len(levantamiento_ids)


# ----------------------------------------------------------
# Helper función: prorrateo por división igual
# ----------------------------------------------------------

def calcular_prorrateo(total_monto: float, levantamientos: List[dict]) -> dict:
    """
    División igual del total entre los levantamientos de la visita.
    Retorna {str(id_levantamiento): monto_prorrateado}.
    El último levantamiento absorbe el ajuste de centavos.
    """
    n = len(levantamientos)
    if n == 0:
        return {}
    monto_por_lev = round(total_monto / n, 2)
    ajuste = round(total_monto - monto_por_lev * n, 2)
    result = {
        str(lev["id_levantamiento"]): monto_por_lev for lev in levantamientos
    }
    if levantamientos:
        last_key = str(levantamientos[-1]["id_levantamiento"])
        result[last_key] = round(result[last_key] + ajuste, 2)
    return result


# ----------------------------------------------------------
# Dependency injection
# ----------------------------------------------------------

def get_visitas_db_service() -> VisitasCampoDBService:
    return VisitasCampoDBService()
