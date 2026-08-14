# Archivo: core/materials/db_service.py
"""
Capa de Acceso a Datos para Materiales compartido.
Queries puras con asyncpg, recibe conn.
"""

from uuid import UUID
from typing import List, Optional
import logging

from core.materials.normalizer import normalizar_descripcion
from core.timezone import now_mx

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
                    pr.proyecto_id_estandar as proyecto_nombre,
                    (SELECT COUNT(*) FROM tb_materiales_interno_xml v
                     WHERE v.id_material_xml = m.id) AS vinculos_interno,
                    ci.descripcion_canonica AS descripcion_interno_vinculado
                FROM tb_materiales_historial m
                LEFT JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
                LEFT JOIN tb_cat_categorias_compra cat ON m.id_categoria = cat.id
                LEFT JOIN tb_comprobantes_pago c ON m.id_comprobante = c.id_comprobante
                LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
                LEFT JOIN tb_materiales_interno_xml vlink ON vlink.id_material_xml = m.id
                LEFT JOIN tb_cat_materiales ci ON ci.id = vlink.id_material_interno
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

    async def get_material_descripcion(self, conn, material_id: UUID) -> Optional[str]:
        """Lookup liviano de solo la descripcion (sin JOINs), para armar sugerencias
        difusas sin pagar el costo de get_material_by_id cuando no se va a mostrar."""
        return await conn.fetchval(
            "SELECT descripcion_proveedor FROM tb_materiales_historial WHERE id = $1", material_id
        )

    async def get_material_by_id(self, conn, material_id: UUID) -> Optional[dict]:
        """Obtiene un material por ID con JOINs."""
        row = await conn.fetchrow("""
            SELECT
                m.*,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                cat.nombre as categoria_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                (SELECT COUNT(*) FROM tb_materiales_interno_xml v
                 WHERE v.id_material_xml = m.id) AS vinculos_interno
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


    async def get_cat_unidades(self, conn) -> list:
        rows = await conn.fetch(
            "SELECT id, codigo, nombre, tipo FROM tb_cat_unidades_medida WHERE activo ORDER BY orden, codigo"
        )
        return [dict(r) for r in rows]

    async def get_estadisticas_internos(self, conn) -> dict:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE activo)                                   AS total_activos,
                COUNT(*) FILTER (WHERE NOT activo)                               AS total_inactivos,
                COUNT(*) FILTER (WHERE activo AND id_categoria IS NOT NULL)      AS con_categoria,
                COUNT(*) FILTER (WHERE activo AND precio_referencia IS NOT NULL) AS con_precio
            FROM tb_cat_materiales
        """)
        return dict(row)

    async def get_internos_filtered(
        self, conn, filtros: dict, page: int = 1, per_page: int = 50, count_only: bool = False
    ):
        if count_only:
            base = "SELECT COUNT(*) FROM tb_cat_materiales c WHERE c.activo = TRUE"
        else:
            base = """
                SELECT
                    c.id, c.descripcion_canonica, c.id_unidad_medida, c.id_categoria,
                    c.clave_prod_serv, c.precio_referencia, c.notas, c.activo,
                    c.material, c.tipo, c.acabado, c.marca, c.adicional, c.medida, c.moneda,
                    c.created_at, c.updated_at, c.creado_por,
                    u.codigo AS unidad_codigo, u.nombre AS unidad_nombre,
                    cat.nombre AS categoria_nombre,
                    cr.nombre AS creado_por_nombre,
                    (SELECT COUNT(*) FROM tb_materiales_interno_xml v
                     WHERE v.id_material_interno = c.id) AS vinculos_xml
                FROM tb_cat_materiales c
                LEFT JOIN tb_cat_unidades_medida u    ON u.id  = c.id_unidad_medida
                LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
                LEFT JOIN tb_usuarios cr               ON cr.id_usuario = c.creado_por
                WHERE c.activo = TRUE
            """
        params = []
        idx = 1

        if filtros.get('q'):
            q_norm = normalizar_descripcion(filtros['q'])
            base += f" AND (c.descripcion_norm ILIKE ${idx} OR c.descripcion_canonica ILIKE ${idx})"
            params.append(f"%{q_norm}%")
            idx += 1
        if filtros.get('id_unidad_medida'):
            base += f" AND c.id_unidad_medida = ${idx}"
            params.append(filtros['id_unidad_medida'])
            idx += 1
        if filtros.get('id_categoria'):
            base += f" AND c.id_categoria = ${idx}"
            params.append(filtros['id_categoria'])
            idx += 1

        if count_only:
            return await conn.fetchval(base, *params)

        base += f" ORDER BY c.created_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
        params.extend([per_page, (page - 1) * per_page])
        return await conn.fetch(base, *params)

    async def get_interno_descripcion(self, conn, id: UUID) -> Optional[str]:
        """Lookup liviano de solo la descripcion (sin JOINs), para armar sugerencias
        difusas sin pagar el costo de get_interno_by_id cuando no se va a mostrar."""
        return await conn.fetchval(
            "SELECT descripcion_canonica FROM tb_cat_materiales WHERE id = $1", id
        )

    async def get_interno_by_id(self, conn, id: UUID) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT
                c.id, c.descripcion_canonica, c.id_unidad_medida, c.id_categoria,
                c.clave_prod_serv, c.precio_referencia, c.notas, c.activo,
                c.material, c.tipo, c.acabado, c.marca, c.adicional, c.medida, c.moneda,
                c.created_at, c.updated_at, c.creado_por,
                u.codigo AS unidad_codigo, u.nombre AS unidad_nombre,
                cat.nombre AS categoria_nombre,
                cr.nombre AS creado_por_nombre
            FROM tb_cat_materiales c
            LEFT JOIN tb_cat_unidades_medida u    ON u.id  = c.id_unidad_medida
            LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
            LEFT JOIN tb_usuarios cr               ON cr.id_usuario = c.creado_por
            WHERE c.id = $1
        """, id)
        return dict(row) if row else None

    # Orden de columnas para INSERT en tb_cat_materiales (compartido por alta y bulk).
    _INTERNO_INSERT_SQL = """
            INSERT INTO tb_cat_materiales
                (descripcion_canonica, descripcion_norm, id_unidad_medida, id_categoria,
                 clave_prod_serv, precio_referencia, notas,
                 material, tipo, acabado, marca, adicional, medida, moneda,
                 creado_por, actualizado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
    """

    @staticmethod
    def _interno_values(data: dict) -> tuple:
        """Tupla de valores en el orden de _INTERNO_INSERT_SQL. Usa descripcion_norm
        precalculado si viene; si no, lo deriva de la descripcion canonica."""
        norm = data.get('descripcion_norm') or normalizar_descripcion(data['descripcion_canonica'])
        return (
            data['descripcion_canonica'], norm,
            data.get('id_unidad_medida'), data.get('id_categoria'),
            data.get('clave_prod_serv') or None, data.get('precio_referencia'),
            data.get('notas') or None,
            data.get('material') or None, data.get('tipo') or None,
            data.get('acabado') or None, data.get('marca') or None,
            data.get('adicional') or None, data.get('medida') or None,
            data.get('moneda') or 'MXN',
            data.get('creado_por'), data.get('actualizado_por'),
        )

    async def crear_interno(self, conn, data: dict) -> dict:
        row = await conn.fetchrow(
            self._INTERNO_INSERT_SQL + " RETURNING id", *self._interno_values(data)
        )
        return await self.get_interno_by_id(conn, row['id'])

    async def crear_internos_bulk(self, conn, registros: List[dict]) -> int:
        """Insercion por lotes para carga masiva. Cada registro ya viene validado y
        con 'descripcion_norm' precalculado por el service. Inserta en una sola pasada."""
        if not registros:
            return 0
        await conn.executemany(
            self._INTERNO_INSERT_SQL, [self._interno_values(r) for r in registros]
        )
        return len(registros)

    async def get_unidad_alias_map(self, conn) -> dict:
        """Mapa {clave_normalizada_upper: id_unidad} desde codigos + aliases activos.
        Permite resolver 'Pieza'->pza, 'Metros'->m, etc."""
        rows = await conn.fetch("""
            SELECT UPPER(codigo) AS k, id FROM tb_cat_unidades_medida WHERE activo
            UNION
            SELECT UPPER(a.alias) AS k, a.unidad_id AS id
            FROM tb_cat_unidad_aliases a WHERE a.activo
        """)
        return {r['k']: r['id'] for r in rows}

    async def get_norms_existentes(self, conn) -> set:
        """Conjunto de descripcion_norm ya registradas (para deteccion de duplicados)."""
        rows = await conn.fetch(
            "SELECT descripcion_norm FROM tb_cat_materiales WHERE descripcion_norm IS NOT NULL"
        )
        return {r['descripcion_norm'] for r in rows}

    async def get_precios_actuales(self, conn) -> dict:
        """Mapa de precios y moneda actuales para internos activos."""
        rows = await conn.fetch(
            "SELECT id, precio_referencia, moneda FROM tb_cat_materiales WHERE activo = TRUE"
        )
        return {
            r['id']: {
                'precio': (
                    float(r['precio_referencia'])
                    if r['precio_referencia'] is not None
                    else None
                ),
                'moneda': r['moneda'] or 'MXN',
            }
            for r in rows
        }

    async def actualizar_precios_bulk(self, conn, registros: List[dict]) -> int:
        """Actualiza precio_referencia y moneda; devuelve filas realmente actualizadas."""
        if not registros:
            return 0

        import json

        payload = [
            {
                "id": str(r["id"]),
                "precio_referencia": r["precio_referencia"],
                "moneda": r["moneda"],
                "actualizado_por": (
                    str(r["actualizado_por"]) if r.get("actualizado_por") else None
                ),
            }
            for r in registros
        ]
        rows = await conn.fetch(
            """
            WITH payload AS (
                SELECT *
                FROM jsonb_to_recordset($1::jsonb) AS x(
                    id uuid,
                    precio_referencia numeric,
                    moneda varchar,
                    actualizado_por uuid
                )
            )
            UPDATE tb_cat_materiales m
            SET precio_referencia = p.precio_referencia,
                moneda = p.moneda,
                actualizado_por = p.actualizado_por,
                updated_at = $2
            FROM payload p
            WHERE m.id = p.id
              AND m.activo = TRUE
            RETURNING m.id
            """,
            json.dumps(payload),
            now_mx(),
        )
        return len(rows)

    async def actualizar_interno(self, conn, id: UUID, data: dict) -> bool:
        allowed = ['descripcion_canonica', 'id_unidad_medida', 'id_categoria',
                   'clave_prod_serv', 'precio_referencia', 'notas',
                   'material', 'tipo', 'acabado', 'marca', 'adicional', 'medida', 'moneda',
                   'actualizado_por']
        sets, params, idx = [], [], 1
        for field in allowed:
            if field not in data:
                continue
            val = data[field]
            if field == 'descripcion_canonica' and val:
                sets += [f"descripcion_canonica = ${idx}", f"descripcion_norm = ${idx + 1}"]
                params += [val, normalizar_descripcion(val)]
                idx += 2
            elif val is None or val == "":
                sets.append(f"{field} = NULL")
            else:
                sets.append(f"{field} = ${idx}")
                params.append(val)
                idx += 1
        if not sets:
            return False
        sets.append(f"updated_at = ${idx}")
        params.extend([now_mx(), id])
        result = await conn.execute(
            f"UPDATE tb_cat_materiales SET {', '.join(sets)} WHERE id = ${idx + 1}", *params
        )
        return result == "UPDATE 1"

    async def desactivar_interno(self, conn, id: UUID) -> bool:
        result = await conn.execute(
            "UPDATE tb_cat_materiales SET activo = FALSE, updated_at = $1 WHERE id = $2",
            now_mx(), id
        )
        return result == "UPDATE 1"

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


    async def get_vinculos_xml(self, conn, id_interno: UUID) -> list:
        rows = await conn.fetch("""
            SELECT
                m.id AS id_xml,
                m.descripcion_proveedor,
                COALESCE(m.unidad_homologada, m.unidad) AS unidad,
                m.precio_unitario,
                m.clave_prod_serv,
                p.razon_social AS proveedor_nombre,
                m.fecha_factura,
                v.created_at AS vinculado_en
            FROM tb_materiales_interno_xml v
            JOIN tb_materiales_historial m ON m.id = v.id_material_xml
            LEFT JOIN tb_proveedores p ON p.id_proveedor = m.id_proveedor
            WHERE v.id_material_interno = $1
            ORDER BY v.created_at DESC
        """, id_interno)
        return [dict(r) for r in rows]

    # SELECT base compartido por busqueda textual y sugerencia difusa del catalogo
    # interno (vincular-interno): solo cambia el filtro y el ORDER BY.
    _INTERNO_VINCULAR_SELECT = """
        SELECT
            c.id,
            c.descripcion_canonica,
            u.codigo AS unidad,
            c.precio_referencia,
            cat.nombre AS categoria_nombre,
            EXISTS(
                SELECT 1 FROM tb_materiales_interno_xml v
                WHERE v.id_material_xml = $1 AND v.id_material_interno = c.id
            ) AS ya_vinculado
        FROM tb_cat_materiales c
        LEFT JOIN tb_cat_unidades_medida u ON u.id = c.id_unidad_medida
        LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
        WHERE c.activo = TRUE
    """

    async def buscar_xml_para_vincular(self, conn, id_interno: UUID, q: str, limite: int = 20) -> list:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (m.descripcion_proveedor)
                m.id,
                m.descripcion_proveedor,
                COALESCE(m.unidad_homologada, m.unidad) AS unidad,
                m.precio_unitario,
                p.razon_social AS proveedor_nombre,
                m.fecha_factura,
                EXISTS(
                    SELECT 1 FROM tb_materiales_interno_xml v
                    WHERE v.id_material_interno = $1 AND v.id_material_xml = m.id
                ) AS ya_vinculado
            FROM tb_materiales_historial m
            LEFT JOIN tb_proveedores p ON p.id_proveedor = m.id_proveedor
            WHERE m.descripcion_proveedor ILIKE '%' || $2 || '%'
            ORDER BY m.descripcion_proveedor, m.fecha_factura DESC
            LIMIT $3
        """, id_interno, q, limite)
        return [dict(r) for r in rows]

    async def sugerir_internos_por_similitud(
        self, conn, id_xml: UUID, descripcion: str, limite: int = 5, umbral: float = 0.2
    ) -> list:
        """Sugiere items del catalogo interno por similitud difusa (word_similarity)
        contra la descripcion de un registro XML, para prellenar el modal antes de
        que el usuario escriba una busqueda manual."""
        norm = normalizar_descripcion(descripcion)
        query = self._INTERNO_VINCULAR_SELECT + """
              AND word_similarity(c.descripcion_norm, $2) >= $4
            ORDER BY word_similarity(c.descripcion_norm, $2) DESC
            LIMIT $3
        """
        rows = await conn.fetch(query, id_xml, norm, limite, umbral)
        return [dict(r) for r in rows]

    async def sugerir_xml_por_similitud(
        self, conn, id_interno: UUID, descripcion: str, limite: int = 5, umbral: float = 0.2
    ) -> list:
        """Sugiere registros XML del historial por similitud difusa (word_similarity)
        contra la descripcion canonica de un item del catalogo interno. Deduplica por
        descripcion_proveedor (mismo criterio que buscar_xml_para_vincular) y limpia
        ruido comercial/saltos de linea antes de comparar -- tb_materiales_historial no
        tiene una columna de descripcion normalizada precalculada como tb_cat_materiales,
        por lo que la limpieza se hace inline (no incluye remocion de acentos: la
        extension unaccent no esta instalada)."""
        rows = await conn.fetch("""
            WITH candidatos AS (
                SELECT
                    m.id,
                    m.descripcion_proveedor,
                    COALESCE(m.unidad_homologada, m.unidad) AS unidad,
                    m.precio_unitario,
                    p.razon_social AS proveedor_nombre,
                    m.fecha_factura,
                    EXISTS(
                        SELECT 1 FROM tb_materiales_interno_xml v
                        WHERE v.id_material_interno = $1 AND v.id_material_xml = m.id
                    ) AS ya_vinculado,
                    word_similarity(
                        upper($2),
                        upper(regexp_replace(
                            regexp_replace(m.descripcion_proveedor, '\\*{2,}.*', '', 's'),
                            '[\\r\\n\\t]+', ' ', 'g'
                        ))
                    ) AS score
                FROM tb_materiales_historial m
                LEFT JOIN tb_proveedores p ON p.id_proveedor = m.id_proveedor
            ),
            deduplicados AS (
                SELECT DISTINCT ON (descripcion_proveedor) *
                FROM candidatos
                WHERE score >= $3
                ORDER BY descripcion_proveedor, score DESC
            )
            SELECT * FROM deduplicados
            ORDER BY score DESC
            LIMIT $4
        """, id_interno, descripcion, umbral, limite)
        return [dict(r) for r in rows]

    async def crear_vinculo_xml(self, conn, id_interno: UUID, id_xml: UUID) -> None:
        await conn.execute("""
            INSERT INTO tb_materiales_interno_xml (id_material_interno, id_material_xml)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, id_interno, id_xml)

    async def eliminar_vinculo_xml(self, conn, id_interno: UUID, id_xml: UUID) -> None:
        await conn.execute("""
            DELETE FROM tb_materiales_interno_xml
            WHERE id_material_interno = $1 AND id_material_xml = $2
        """, id_interno, id_xml)

    async def get_vinculos_interno_por_xml(self, conn, id_xml: UUID) -> list:
        rows = await conn.fetch("""
            SELECT
                c.id AS id_interno,
                c.descripcion_canonica,
                u.codigo AS unidad,
                c.precio_referencia,
                cat.nombre AS categoria_nombre,
                v.created_at AS vinculado_en
            FROM tb_materiales_interno_xml v
            JOIN tb_cat_materiales c ON c.id = v.id_material_interno
            LEFT JOIN tb_cat_unidades_medida u ON u.id = c.id_unidad_medida
            LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
            WHERE v.id_material_xml = $1
            ORDER BY v.created_at DESC
        """, id_xml)
        return [dict(r) for r in rows]

    async def buscar_internos_para_vincular(self, conn, id_xml: UUID, q: str, limite: int = 20) -> list:
        q_norm = normalizar_descripcion(q)
        query = self._INTERNO_VINCULAR_SELECT + """
              AND (c.descripcion_norm ILIKE '%' || $2 || '%' OR c.descripcion_canonica ILIKE '%' || $2 || '%')
            ORDER BY c.descripcion_canonica
            LIMIT $3
        """
        rows = await conn.fetch(query, id_xml, q_norm, limite)
        return [dict(r) for r in rows]

    async def vincular_interno_a_xml(self, conn, id_xml: UUID, id_interno: UUID) -> None:
        """Vincula (o revincula) un registro XML a un item del catalogo interno.

        Relacion 1:N forzada por uq_interno_xml_xml (mig 119): cada factura XML
        pertenece a un solo item interno, por lo que un nuevo vinculo reemplaza
        al anterior en vez de fallar por conflicto."""
        await conn.execute("""
            INSERT INTO tb_materiales_interno_xml (id_material_interno, id_material_xml)
            VALUES ($1, $2)
            ON CONFLICT (id_material_xml) DO UPDATE
            SET id_material_interno = EXCLUDED.id_material_interno, created_at = now()
        """, id_interno, id_xml)


def get_materials_db_service():
    return MaterialsDBService()
