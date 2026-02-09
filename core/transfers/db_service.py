"""
Data Access Layer para el sistema de traspasos de proyectos.
Centraliza queries SQL para separar logica de acceso a datos.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

logger = logging.getLogger("TransferDBService")


class TransferDBService:

    async def get_proyectos_by_area(
        self, conn, area: str,
        q: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id_proyecto,
                p.proyecto_id_estandar,
                p.nombre_corto,
                p.status_fase,
                p.area_actual,
                p.fecha_inicio_area,
                p.created_at,
                p.consecutivo,
                t.nombre as tecnologia_nombre,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.op_id_estandar,
                u.nombre as creado_por_nombre,
                EXTRACT(DAY FROM NOW() - COALESCE(p.fecha_inicio_area, p.created_at))::int as dias_en_area,
                (
                    SELECT status FROM tb_traspasos_proyecto tp
                    WHERE tp.id_proyecto = p.id_proyecto
                    ORDER BY tp.fecha_envio DESC LIMIT 1
                ) as ultimo_traspaso_status
            FROM tb_proyectos_gate p
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            LEFT JOIN tb_oportunidades o ON p.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_usuarios u ON p.created_by_id = u.id_usuario
            WHERE p.area_actual = $1
            AND p.aprobacion_direccion = true
        """
        params: list = [area]

        if q:
            query += """ AND (
                p.proyecto_id_estandar ILIKE $2
                OR o.nombre_proyecto ILIKE $2
                OR o.cliente_nombre ILIKE $2
            )"""
            params.append(f"%{q}%")

        query += " ORDER BY p.created_at DESC"

        if limit > 0:
            query += f" LIMIT {limit}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_proyectos_pendientes_recepcion(
        self, conn, area_destino: str
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id_proyecto,
                p.proyecto_id_estandar,
                p.nombre_corto,
                p.area_actual,
                p.fecha_inicio_area,
                t.nombre as tecnologia_nombre,
                o.nombre_proyecto,
                o.cliente_nombre,
                tr.id_traspaso,
                tr.area_origen,
                tr.enviado_por_nombre,
                tr.fecha_envio,
                tr.comentario_envio,
                EXTRACT(DAY FROM NOW() - tr.fecha_envio)::int as dias_pendiente
            FROM tb_traspasos_proyecto tr
            JOIN tb_proyectos_gate p ON tr.id_proyecto = p.id_proyecto
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            LEFT JOIN tb_oportunidades o ON p.id_oportunidad = o.id_oportunidad
            WHERE tr.area_destino = $1
            AND tr.status = 'ENVIADO'
            ORDER BY tr.fecha_envio ASC
        """
        rows = await conn.fetch(query, area_destino)
        return [dict(r) for r in rows]

    async def get_all_proyectos(
        self, conn,
        area_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id_proyecto,
                p.proyecto_id_estandar,
                p.nombre_corto,
                p.status_fase,
                p.area_actual,
                p.fecha_inicio_area,
                p.created_at,
                p.consecutivo,
                t.nombre as tecnologia_nombre,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.op_id_estandar,
                u.nombre as creado_por_nombre,
                EXTRACT(DAY FROM NOW() - COALESCE(p.fecha_inicio_area, p.created_at))::int as dias_en_area,
                (
                    SELECT status FROM tb_traspasos_proyecto tp
                    WHERE tp.id_proyecto = p.id_proyecto
                    ORDER BY tp.fecha_envio DESC LIMIT 1
                ) as ultimo_traspaso_status
            FROM tb_proyectos_gate p
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            LEFT JOIN tb_oportunidades o ON p.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_usuarios u ON p.created_by_id = u.id_usuario
            WHERE p.aprobacion_direccion = true
        """
        params: list = []

        if area_filter:
            params.append(area_filter)
            query += f" AND p.area_actual = ${len(params)}"

        if status_filter:
            params.append(status_filter)
            query += f""" AND EXISTS (
                SELECT 1 FROM tb_traspasos_proyecto tp2
                WHERE tp2.id_proyecto = p.id_proyecto
                AND tp2.status = ${len(params)}
            )"""

        if q:
            params.append(f"%{q}%")
            ph = f"${len(params)}"
            query += f""" AND (
                p.proyecto_id_estandar ILIKE {ph}
                OR o.nombre_proyecto ILIKE {ph}
                OR o.cliente_nombre ILIKE {ph}
            )"""

        query += " ORDER BY p.created_at DESC"

        if limit > 0:
            query += f" LIMIT {limit}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_proyecto_detalle(self, conn, id_proyecto: UUID) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow("""
            SELECT
                p.*,
                t.nombre as tecnologia_nombre,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.op_id_estandar,
                u.nombre as creado_por_nombre,
                EXTRACT(DAY FROM NOW() - COALESCE(p.fecha_inicio_area, p.created_at))::int as dias_en_area
            FROM tb_proyectos_gate p
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            LEFT JOIN tb_oportunidades o ON p.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_usuarios u ON p.created_by_id = u.id_usuario
            WHERE p.id_proyecto = $1
        """, id_proyecto)
        return dict(row) if row else None

    async def get_documentos_checklist(
        self, conn, area_origen: str, area_destino: str
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT id, nombre_documento, descripcion, es_obligatorio, orden
            FROM tb_cat_documentos_traspaso
            WHERE area_origen = $1 AND area_destino = $2 AND activo = true
            ORDER BY orden
        """, area_origen, area_destino)
        return [dict(r) for r in rows]

    async def get_motivos_rechazo(self, conn, area: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT id, motivo
            FROM tb_cat_motivos_rechazo
            WHERE area = $1 AND activo = true
            ORDER BY id
        """, area)
        return [dict(r) for r in rows]

    async def crear_traspaso(
        self, conn, id_traspaso: UUID, id_proyecto: UUID,
        area_origen: str, area_destino: str,
        user_id: UUID, user_name: str,
        comentario: Optional[str] = None
    ) -> Dict[str, Any]:
        await conn.execute("""
            INSERT INTO tb_traspasos_proyecto (
                id_traspaso, id_proyecto, area_origen, area_destino,
                status, enviado_por, enviado_por_nombre,
                fecha_envio, comentario_envio
            ) VALUES ($1, $2, $3, $4, 'ENVIADO', $5, $6, NOW(), $7)
        """, id_traspaso, id_proyecto, area_origen, area_destino,
            user_id, user_name, comentario)

        row = await conn.fetchrow(
            "SELECT * FROM tb_traspasos_proyecto WHERE id_traspaso = $1",
            id_traspaso
        )
        return dict(row) if row else {}

    async def registrar_documentos_traspaso(
        self, conn, id_traspaso: UUID, docs_ids: List[int], user_id: UUID
    ):
        for doc_id in docs_ids:
            await conn.execute("""
                INSERT INTO tb_traspaso_documentos (
                    id_traspaso, id_documento_catalogo, verificado,
                    verificado_por, fecha_verificacion
                ) VALUES ($1, $2, true, $3, NOW())
            """, id_traspaso, doc_id, user_id)

    async def actualizar_area_proyecto(
        self, conn, id_proyecto: UUID, nueva_area: str
    ):
        await conn.execute("""
            UPDATE tb_proyectos_gate
            SET area_actual = $1, fecha_inicio_area = NOW()
            WHERE id_proyecto = $2
        """, nueva_area, id_proyecto)

    async def aceptar_traspaso(
        self, conn, id_traspaso: UUID, user_id: UUID, user_name: str
    ):
        await conn.execute("""
            UPDATE tb_traspasos_proyecto
            SET status = 'ACEPTADO',
                recibido_por = $1,
                recibido_por_nombre = $2,
                fecha_recepcion = NOW()
            WHERE id_traspaso = $3
        """, user_id, user_name, id_traspaso)

    async def rechazar_traspaso(
        self, conn, id_traspaso: UUID, user_id: UUID, user_name: str,
        comentario: Optional[str] = None
    ):
        await conn.execute("""
            UPDATE tb_traspasos_proyecto
            SET status = 'RECHAZADO',
                rechazado_por = $1,
                rechazado_por_nombre = $2,
                fecha_rechazo = NOW(),
                comentario_rechazo = $3
            WHERE id_traspaso = $4
        """, user_id, user_name, comentario, id_traspaso)

    async def registrar_motivos_rechazo(
        self, conn, id_traspaso: UUID, motivos_ids: List[int]
    ):
        for motivo_id in motivos_ids:
            await conn.execute("""
                INSERT INTO tb_traspaso_rechazos (id_traspaso, id_motivo)
                VALUES ($1, $2)
            """, id_traspaso, motivo_id)

    async def get_traspaso_by_id(self, conn, id_traspaso: UUID) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow("""
            SELECT tr.*, p.proyecto_id_estandar, p.area_actual
            FROM tb_traspasos_proyecto tr
            JOIN tb_proyectos_gate p ON tr.id_proyecto = p.id_proyecto
            WHERE tr.id_traspaso = $1
        """, id_traspaso)
        return dict(row) if row else None

    async def get_historial_traspasos(
        self, conn, id_proyecto: UUID
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT
                tr.id_traspaso,
                tr.area_origen,
                tr.area_destino,
                tr.status,
                tr.enviado_por_nombre,
                tr.fecha_envio,
                tr.recibido_por_nombre,
                tr.fecha_recepcion,
                tr.rechazado_por_nombre,
                tr.fecha_rechazo,
                tr.comentario_envio,
                tr.comentario_rechazo
            FROM tb_traspasos_proyecto tr
            WHERE tr.id_proyecto = $1
            ORDER BY tr.fecha_envio DESC
        """, id_proyecto)
        return [dict(r) for r in rows]

    async def get_motivos_rechazo_traspaso(
        self, conn, id_traspaso: UUID
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT mr.motivo
            FROM tb_traspaso_rechazos trr
            JOIN tb_cat_motivos_rechazo mr ON trr.id_motivo = mr.id
            WHERE trr.id_traspaso = $1
        """, id_traspaso)
        return [dict(r) for r in rows]

    async def get_kpis_area(self, conn, area: str) -> Dict[str, int]:
        total = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_proyectos_gate
            WHERE area_actual = $1 AND aprobacion_direccion = true
        """, area)

        pendientes = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_traspasos_proyecto
            WHERE area_destino = $1 AND status = 'ENVIADO'
        """, area)

        enviados = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_traspasos_proyecto
            WHERE area_origen = $1 AND status = 'ENVIADO'
        """, area)

        rechazados = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_traspasos_proyecto
            WHERE area_destino = $1 AND status = 'RECHAZADO'
            AND fecha_rechazo >= NOW() - INTERVAL '30 days'
        """, area)

        return {
            "total_en_area": total or 0,
            "pendientes_recepcion": pendientes or 0,
            "enviados_pendientes": enviados or 0,
            "rechazados_recientes": rechazados or 0,
        }

    async def get_kpis_global(self, conn) -> Dict[str, Any]:
        total = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_proyectos_gate
            WHERE aprobacion_direccion = true
        """)

        por_area = await conn.fetch("""
            SELECT area_actual, COUNT(*) as total
            FROM tb_proyectos_gate
            WHERE aprobacion_direccion = true
            GROUP BY area_actual
        """)

        pendientes = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_traspasos_proyecto
            WHERE status = 'ENVIADO'
        """)

        return {
            "total_proyectos": total or 0,
            "por_area": {r['area_actual']: r['total'] for r in por_area},
            "traspasos_pendientes": pendientes or 0,
        }


def get_transfer_db_service() -> TransferDBService:
    return TransferDBService()
