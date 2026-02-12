# Archivo: core/materials/db_service.py
"""
Capa de Acceso a Datos para Materiales compartido.
Queries puras con asyncpg, recibe conn.
"""

from uuid import UUID
from typing import List, Optional, Tuple
from decimal import Decimal
import logging

logger = logging.getLogger("Materials.DBService")


class MaterialsDBService:
    """Queries SQL para modulo de Materiales."""

    async def get_materiales_filtered(
        self,
        conn,
        filtros: dict,
        page: int = 1,
        per_page: int = 50,
        count_only: bool = False
    ):
        """Builds dynamic query for filtering materiales with JOINs."""
        if count_only:
            base_query = """
                SELECT COUNT(*)
                FROM tb_materiales_historial m
                LEFT JOIN tb_comprobantes_pago c ON m.id_comprobante = c.id_comprobante
                WHERE 1=1
            """
        else:
            base_query = """
                SELECT
                    m.id,
                    m.uuid_factura,
                    m.id_comprobante,
                    m.id_proveedor,
                    m.descripcion_proveedor,
                    m.descripcion_interna,
                    m.cantidad,
                    m.precio_unitario,
                    m.importe,
                    m.unidad,
                    m.clave_prod_serv,
                    m.clave_unidad,
                    m.id_categoria,
                    m.origen,
                    m.fecha_factura,
                    p.razon_social as proveedor_nombre,
                    p.rfc as proveedor_rfc,
                    cat.nombre as categoria_nombre,
                    pr.proyecto_id_estandar as proyecto_nombre
                FROM tb_materiales_historial m
                LEFT JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
                LEFT JOIN tb_cat_categorias_compra cat ON m.id_categoria = cat.id
                LEFT JOIN tb_comprobantes_pago c ON m.id_comprobante = c.id_comprobante
                LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
                WHERE 1=1
            """

        params = []
        param_idx = 1

        if filtros.get('id_proveedor'):
            base_query += f" AND m.id_proveedor = ${param_idx}"
            params.append(filtros['id_proveedor'])
            param_idx += 1

        if filtros.get('id_categoria'):
            base_query += f" AND m.id_categoria = ${param_idx}"
            params.append(filtros['id_categoria'])
            param_idx += 1

        if filtros.get('id_proyecto'):
            base_query += f" AND c.id_proyecto = ${param_idx}"
            params.append(filtros['id_proyecto'])
            param_idx += 1

        if filtros.get('fecha_inicio'):
            base_query += f" AND m.fecha_factura >= ${param_idx}"
            params.append(filtros['fecha_inicio'])
            param_idx += 1

        if filtros.get('fecha_fin'):
            base_query += f" AND m.fecha_factura <= ${param_idx}"
            params.append(filtros['fecha_fin'])
            param_idx += 1

        if filtros.get('origen'):
            base_query += f" AND m.origen = ${param_idx}"
            params.append(filtros['origen'])
            param_idx += 1

        if filtros.get('q'):
            base_query += f" AND (m.descripcion_proveedor ILIKE ${param_idx} OR m.descripcion_interna ILIKE ${param_idx})"
            params.append(f"%{filtros['q']}%")
            param_idx += 1

        if count_only:
            return await conn.fetchval(base_query, *params)

        base_query += " ORDER BY m.fecha_factura DESC, m.created_at DESC"

        if per_page > 0:
            base_query += f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
            params.extend([per_page, (page - 1) * per_page])

        return await conn.fetch(base_query, *params)

    async def get_material_precios(
        self, conn, descripcion: str, id_proveedor: Optional[UUID] = None
    ) -> List[dict]:
        """Analisis de precios agrupado por proveedor para una descripcion."""
        query = """
            SELECT
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                MIN(m.precio_unitario) as min_precio,
                MAX(m.precio_unitario) as max_precio,
                AVG(m.precio_unitario) as avg_precio,
                COUNT(*) as total_compras,
                MAX(m.fecha_factura) as ultima_compra
            FROM tb_materiales_historial m
            JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
            WHERE m.descripcion_proveedor = $1
        """
        params = [descripcion]
        param_idx = 2

        if id_proveedor:
            query += f" AND m.id_proveedor != ${param_idx}"
            params.append(id_proveedor)
            param_idx += 1

        query += " GROUP BY p.razon_social, p.rfc ORDER BY avg_precio ASC"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_precios_por_clave_sat(
        self, conn, clave_prod_serv: str,
        exclude_descripcion: Optional[str] = None
    ) -> List[dict]:
        """Precios agrupados por proveedor+descripcion para misma clave SAT.

        Excluye la descripcion exacta del material actual para no duplicar
        datos con la comparativa por descripcion.
        """
        query = """
            SELECT
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                m.descripcion_proveedor,
                MIN(m.precio_unitario) as min_precio,
                MAX(m.precio_unitario) as max_precio,
                AVG(m.precio_unitario) as avg_precio,
                COUNT(*) as total_compras,
                MAX(m.fecha_factura) as ultima_compra
            FROM tb_materiales_historial m
            JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
            WHERE m.clave_prod_serv = $1
        """
        params = [clave_prod_serv]
        param_idx = 2

        if exclude_descripcion:
            query += f" AND m.descripcion_proveedor != ${param_idx}"
            params.append(exclude_descripcion)
            param_idx += 1

        query += """
            GROUP BY p.razon_social, p.rfc, m.descripcion_proveedor
            ORDER BY avg_precio ASC
        """

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_material_by_id(self, conn, material_id: UUID) -> Optional[dict]:
        """Obtiene un material por ID con JOINs."""
        row = await conn.fetchrow("""
            SELECT
                m.*,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                cat.nombre as categoria_nombre,
                pr.proyecto_id_estandar as proyecto_nombre
            FROM tb_materiales_historial m
            LEFT JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
            LEFT JOIN tb_cat_categorias_compra cat ON m.id_categoria = cat.id
            LEFT JOIN tb_comprobantes_pago c ON m.id_comprobante = c.id_comprobante
            LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
            WHERE m.id = $1
        """, material_id)
        return dict(row) if row else None

    async def update_material(self, conn, material_id: UUID, updates: dict) -> bool:
        """Actualiza solo descripcion_interna y/o id_categoria."""
        allowed_fields = ['descripcion_interna', 'id_categoria']
        set_clauses = []
        params = []
        param_idx = 1

        for field in allowed_fields:
            if field in updates:
                value = updates[field]
                if value is None or value == "" or value == "null":
                    set_clauses.append(f"{field} = NULL")
                else:
                    set_clauses.append(f"{field} = ${param_idx}")
                    params.append(value)
                    param_idx += 1

        if not set_clauses:
            return False

        params.append(material_id)
        query = f"""
            UPDATE tb_materiales_historial
            SET {', '.join(set_clauses)}
            WHERE id = ${param_idx}
        """
        result = await conn.execute(query, *params)
        return result == "UPDATE 1"

    async def get_estadisticas(self, conn, filtros: dict) -> dict:
        """Estadisticas de materiales con filtros."""
        base_query = """
            SELECT
                COUNT(*) as total,
                COUNT(DISTINCT m.id_proveedor) as proveedores_distintos,
                COUNT(*) FILTER (WHERE m.id_categoria IS NOT NULL) as categorizados,
                COUNT(*) FILTER (WHERE m.id_categoria IS NULL) as sin_categoria
            FROM tb_materiales_historial m
            LEFT JOIN tb_comprobantes_pago c ON m.id_comprobante = c.id_comprobante
            WHERE 1=1
        """
        params = []
        param_idx = 1

        if filtros.get('id_proveedor'):
            base_query += f" AND m.id_proveedor = ${param_idx}"
            params.append(filtros['id_proveedor'])
            param_idx += 1
        if filtros.get('id_categoria'):
            base_query += f" AND m.id_categoria = ${param_idx}"
            params.append(filtros['id_categoria'])
            param_idx += 1
        if filtros.get('id_proyecto'):
            base_query += f" AND c.id_proyecto = ${param_idx}"
            params.append(filtros['id_proyecto'])
            param_idx += 1
        if filtros.get('fecha_inicio'):
            base_query += f" AND m.fecha_factura >= ${param_idx}"
            params.append(filtros['fecha_inicio'])
            param_idx += 1
        if filtros.get('fecha_fin'):
            base_query += f" AND m.fecha_factura <= ${param_idx}"
            params.append(filtros['fecha_fin'])
            param_idx += 1
        if filtros.get('origen'):
            base_query += f" AND m.origen = ${param_idx}"
            params.append(filtros['origen'])
            param_idx += 1
        if filtros.get('q'):
            base_query += f" AND (m.descripcion_proveedor ILIKE ${param_idx} OR m.descripcion_interna ILIKE ${param_idx})"
            params.append(f"%{filtros['q']}%")
            param_idx += 1

        row = await conn.fetchrow(base_query, *params)
        return dict(row)

    async def get_catalogos(self, conn) -> dict:
        """Catalogos para dropdowns de materiales."""
        categorias = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_categorias_compra WHERE activo = true ORDER BY orden, nombre"
        )
        proveedores = await conn.fetch(
            "SELECT id_proveedor, rfc, razon_social FROM tb_proveedores WHERE activo = true ORDER BY razon_social"
        )
        proyectos = await conn.fetch(
            "SELECT id_proyecto, proyecto_id_estandar as nombre FROM tb_proyectos_gate WHERE aprobacion_direccion = true ORDER BY proyecto_id_estandar"
        )
        return {
            "categorias": [dict(r) for r in categorias],
            "proveedores": [dict(r) for r in proveedores],
            "proyectos": [dict(r) for r in proyectos],
        }


    async def buscar_similar_materiales(
        self, conn, query: str, threshold: float = 0.3, limit: int = 20
    ) -> List[dict]:
        """Busqueda fuzzy con pg_trgm similarity() en descripcion_proveedor.

        Requiere extension pg_trgm y indice GIN en descripcion_proveedor.
        """
        rows = await conn.fetch("""
            SELECT
                m.id,
                m.descripcion_proveedor,
                m.precio_unitario,
                m.importe,
                m.unidad,
                m.clave_prod_serv,
                m.fecha_factura,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                similarity(m.descripcion_proveedor, $1) as similitud
            FROM tb_materiales_historial m
            LEFT JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
            WHERE similarity(m.descripcion_proveedor, $1) >= $2
            ORDER BY similitud DESC
            LIMIT $3
        """, query, threshold, limit)
        return [dict(r) for r in rows]


def get_materials_db_service():
    return MaterialsDBService()
