"""
DB Service para BOM (Lista de Materiales).
Queries SQL puras con asyncpg. Recibe conn como parametro.
"""

import logging
from uuid import UUID
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger("BOM.DBService")


class BomDBService:
    """Capa de acceso a datos para BOM."""

    # ─── BOM CABECERA ───────────────────────────────────────

    async def crear_bom(
        self, conn, id_proyecto: UUID, elaborado_por: UUID,
        responsable_ing: Optional[UUID] = None,
        jefe_construccion: Optional[UUID] = None,
        coordinador_obra: Optional[UUID] = None,
        notas: Optional[str] = None,
        version: int = 1
    ) -> dict:
        """Crea un nuevo BOM para un proyecto."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom (id_proyecto, version, estatus, elaborado_por,
                                responsable_ing, jefe_construccion,
                                coordinador_obra, notas)
            VALUES ($1, $2, 'BORRADOR', $3, $4, $5, $6, $7)
            RETURNING *
        """, id_proyecto, version, elaborado_por, responsable_ing,
            jefe_construccion, coordinador_obra, notas)
        return dict(row)

    async def get_bom_by_proyecto(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Obtiene el BOM mas reciente (mayor version) de un proyecto."""
        row = await conn.fetchrow("""
            SELECT b.*,
                   u1.nombre AS elaborado_por_nombre,
                   u2.nombre AS responsable_ing_nombre,
                   u3.nombre AS jefe_construccion_nombre,
                   u4.nombre AS coordinador_obra_nombre,
                   o.nombre_proyecto AS proyecto_nombre,
                   p.proyecto_id_estandar,
                   COALESCE(items.total, 0) AS total_items,
                   COALESCE(items.entregados, 0) AS items_entregados
            FROM tb_bom b
            LEFT JOIN tb_usuarios u1 ON u1.id_usuario = b.elaborado_por
            LEFT JOIN tb_usuarios u2 ON u2.id_usuario = b.responsable_ing
            LEFT JOIN tb_usuarios u3 ON u3.id_usuario = b.jefe_construccion
            LEFT JOIN tb_usuarios u4 ON u4.id_usuario = b.coordinador_obra
            LEFT JOIN tb_proyectos_gate p ON p.id_proyecto = b.id_proyecto
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE activo) AS total,
                       COUNT(*) FILTER (WHERE activo AND entregado) AS entregados
                FROM tb_bom_items WHERE id_bom = b.id_bom
            ) items ON TRUE
            WHERE b.id_proyecto = $1
            ORDER BY b.version DESC
            LIMIT 1
        """, id_proyecto)
        return dict(row) if row else None

    async def get_bom_by_id(self, conn, id_bom: UUID) -> Optional[dict]:
        """Obtiene un BOM por su ID con datos de usuarios y proyecto."""
        row = await conn.fetchrow("""
            SELECT b.*,
                   u1.nombre AS elaborado_por_nombre,
                   u2.nombre AS responsable_ing_nombre,
                   u3.nombre AS jefe_construccion_nombre,
                   u4.nombre AS coordinador_obra_nombre,
                   o.nombre_proyecto AS proyecto_nombre,
                   p.proyecto_id_estandar,
                   COALESCE(items.total, 0) AS total_items,
                   COALESCE(items.entregados, 0) AS items_entregados
            FROM tb_bom b
            LEFT JOIN tb_usuarios u1 ON u1.id_usuario = b.elaborado_por
            LEFT JOIN tb_usuarios u2 ON u2.id_usuario = b.responsable_ing
            LEFT JOIN tb_usuarios u3 ON u3.id_usuario = b.jefe_construccion
            LEFT JOIN tb_usuarios u4 ON u4.id_usuario = b.coordinador_obra
            LEFT JOIN tb_proyectos_gate p ON p.id_proyecto = b.id_proyecto
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE activo) AS total,
                       COUNT(*) FILTER (WHERE activo AND entregado) AS entregados
                FROM tb_bom_items WHERE id_bom = b.id_bom
            ) items ON TRUE
            WHERE b.id_bom = $1
        """, id_bom)
        return dict(row) if row else None

    async def get_bom_borrador_by_proyecto(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Verifica si existe un BOM en BORRADOR para el proyecto."""
        row = await conn.fetchrow("""
            SELECT id_bom, version, estatus
            FROM tb_bom
            WHERE id_proyecto = $1 AND estatus = 'BORRADOR'
            ORDER BY version DESC
            LIMIT 1
        """, id_proyecto)
        return dict(row) if row else None

    async def update_bom_estatus(
        self, conn, id_bom: UUID, estatus: str,
        **kwargs
    ) -> dict:
        """Actualiza estatus y campos opcionales del BOM."""
        sets = ["estatus = $2", "updated_at = NOW()"]
        params = [id_bom, estatus]
        idx = 3

        campo_map = {
            'fecha_envio_ing': 'fecha_envio_ing',
            'fecha_aprobacion_ing': 'fecha_aprobacion_ing',
            'fecha_envio_const': 'fecha_envio_const',
            'fecha_aprobacion_const': 'fecha_aprobacion_const',
            'responsable_ing': 'responsable_ing',
            'jefe_construccion': 'jefe_construccion',
            'coordinador_obra': 'coordinador_obra',
            'notas': 'notas',
        }

        for key, col in campo_map.items():
            if key in kwargs:
                sets.append(f"{col} = ${idx}")
                params.append(kwargs[key])
                idx += 1

        query = f"""
            UPDATE tb_bom SET {', '.join(sets)}
            WHERE id_bom = $1
            RETURNING *
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def get_max_version(self, conn, id_proyecto: UUID) -> int:
        """Obtiene la version maxima de BOM para un proyecto."""
        val = await conn.fetchval("""
            SELECT COALESCE(MAX(version), 0) FROM tb_bom WHERE id_proyecto = $1
        """, id_proyecto)
        return val

    async def get_all_bom_versions(self, conn, id_proyecto: UUID) -> List[dict]:
        """Lista todas las versiones de BOM de un proyecto."""
        rows = await conn.fetch("""
            SELECT b.id_bom, b.version, b.estatus, b.created_at,
                   u.nombre AS elaborado_por_nombre
            FROM tb_bom b
            LEFT JOIN tb_usuarios u ON u.id_usuario = b.elaborado_por
            WHERE b.id_proyecto = $1
            ORDER BY b.version DESC
        """, id_proyecto)
        return [dict(r) for r in rows]

    # ─── BOM ITEMS ──────────────────────────────────────────

    async def agregar_item(
        self, conn, id_bom: UUID, descripcion: str, cantidad,
        id_categoria: Optional[int] = None,
        unidad_medida: Optional[str] = None,
        comentarios: Optional[str] = None,
        orden: int = 0,
        precio_unitario=None,
        origen_precio: Optional[str] = 'MANUAL',
        id_material_ref: Optional[UUID] = None
    ) -> dict:
        """Agrega un item al BOM."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_items (id_bom, id_categoria, descripcion,
                                      cantidad, unidad_medida, comentarios, orden,
                                      precio_unitario, origen_precio, id_material_ref)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
        """, id_bom, id_categoria, descripcion, cantidad,
            unidad_medida, comentarios, orden,
            precio_unitario, origen_precio, id_material_ref)
        return dict(row)

    async def get_items_by_bom(self, conn, id_bom: UUID, solo_activos: bool = True) -> List[dict]:
        """Lista items de un BOM con datos de categoria y proveedor."""
        filtro_activo = "AND i.activo = TRUE" if solo_activos else ""
        rows = await conn.fetch(f"""
            SELECT i.*,
                   c.nombre AS categoria_nombre,
                   p.nombre_comercial AS proveedor_nombre,
                   (i.cantidad * COALESCE(i.precio_unitario, 0)) AS importe
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_proveedores p ON p.id_proveedor = i.id_proveedor
            WHERE i.id_bom = $1 {filtro_activo}
            ORDER BY i.orden ASC, i.created_at ASC
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_item_by_id(self, conn, id_item: UUID) -> Optional[dict]:
        """Obtiene un item por ID con datos de BOM."""
        row = await conn.fetchrow("""
            SELECT i.*,
                   c.nombre AS categoria_nombre,
                   p.nombre_comercial AS proveedor_nombre,
                   b.estatus AS bom_estatus,
                   b.id_proyecto,
                   b.version AS bom_version,
                   (i.cantidad * COALESCE(i.precio_unitario, 0)) AS importe
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_proveedores p ON p.id_proveedor = i.id_proveedor
            JOIN tb_bom b ON b.id_bom = i.id_bom
            WHERE i.id_item = $1
        """, id_item)
        return dict(row) if row else None

    async def update_item(self, conn, id_item: UUID, **campos) -> dict:
        """Actualiza campos de un item. Solo actualiza los campos proporcionados."""
        sets = ["updated_at = NOW()"]
        params = [id_item]
        idx = 2

        allowed = {
            'id_categoria', 'descripcion', 'cantidad', 'unidad_medida',
            'fecha_requerida', 'fecha_llegada_real', 'id_proveedor',
            'tipo_entrega', 'fecha_estimada_entrega', 'comentarios',
            'entregado', 'fecha_entrega_check', 'orden',
            'precio_unitario', 'origen_precio', 'id_material_ref'
        }

        for key, val in campos.items():
            if key in allowed:
                sets.append(f"{key} = ${idx}")
                params.append(val)
                idx += 1

        query = f"""
            UPDATE tb_bom_items SET {', '.join(sets)}
            WHERE id_item = $1
            RETURNING *
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def soft_delete_item(self, conn, id_item: UUID) -> dict:
        """Marca un item como inactivo (soft delete)."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_items SET activo = FALSE, updated_at = NOW()
            WHERE id_item = $1
            RETURNING *
        """, id_item)
        return dict(row) if row else None

    async def restaurar_item(self, conn, id_item: UUID) -> dict:
        """Restaura un item eliminado."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_items SET activo = TRUE, updated_at = NOW()
            WHERE id_item = $1
            RETURNING *
        """, id_item)
        return dict(row) if row else None

    async def get_next_orden(self, conn, id_bom: UUID) -> int:
        """Obtiene el siguiente numero de orden para items."""
        val = await conn.fetchval("""
            SELECT COALESCE(MAX(orden), 0) + 1
            FROM tb_bom_items WHERE id_bom = $1 AND activo = TRUE
        """, id_bom)
        return val

    async def copiar_items_a_nueva_version(
        self, conn, id_bom_origen: UUID, id_bom_destino: UUID
    ) -> int:
        """Copia items activos de un BOM a otro. Retorna cantidad copiada."""
        result = await conn.execute("""
            INSERT INTO tb_bom_items (id_bom, id_categoria, descripcion,
                                      cantidad, unidad_medida, fecha_requerida,
                                      id_proveedor, tipo_entrega,
                                      fecha_estimada_entrega, comentarios, orden,
                                      precio_unitario, origen_precio, id_material_ref)
            SELECT $2, id_categoria, descripcion,
                   cantidad, unidad_medida, fecha_requerida,
                   id_proveedor, tipo_entrega,
                   fecha_estimada_entrega, comentarios, orden,
                   precio_unitario, origen_precio, id_material_ref
            FROM tb_bom_items
            WHERE id_bom = $1 AND activo = TRUE
            ORDER BY orden ASC
        """, id_bom_origen, id_bom_destino)
        # result es algo como 'INSERT 0 5'
        count = int(result.split()[-1]) if result else 0
        return count

    # ─── HISTORIAL ──────────────────────────────────────────

    async def registrar_historial(
        self, conn, id_bom: UUID, accion: str, version_bom: int,
        realizado_por: UUID, id_item: Optional[UUID] = None,
        campo_modificado: Optional[str] = None,
        valor_anterior: Optional[str] = None,
        valor_nuevo: Optional[str] = None
    ) -> dict:
        """Registra un cambio en el historial de auditoria."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_historial (id_bom, id_item, accion, campo_modificado,
                                          valor_anterior, valor_nuevo, version_bom,
                                          realizado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
        """, id_bom, id_item, accion, campo_modificado,
            valor_anterior, valor_nuevo, version_bom, realizado_por)
        return dict(row)

    async def get_historial_by_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista historial de cambios de un BOM."""
        rows = await conn.fetch("""
            SELECT h.*, u.nombre AS realizado_por_nombre
            FROM tb_bom_historial h
            LEFT JOIN tb_usuarios u ON u.id_usuario = h.realizado_por
            WHERE h.id_bom = $1
            ORDER BY h.created_at DESC
        """, id_bom)
        return [dict(r) for r in rows]

    # ─── APROBACIONES ───────────────────────────────────────

    async def registrar_aprobacion(
        self, conn, id_bom: UUID, tipo: str, version_bom: int,
        usuario_id: UUID, comentarios: Optional[str] = None
    ) -> dict:
        """Registra una accion de aprobacion/rechazo."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_aprobaciones (id_bom, tipo, version_bom,
                                             usuario_id, comentarios)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
        """, id_bom, tipo, version_bom, usuario_id, comentarios)
        return dict(row)

    async def get_aprobaciones_by_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista aprobaciones/rechazos de un BOM."""
        rows = await conn.fetch("""
            SELECT a.*, u.nombre AS usuario_nombre
            FROM tb_bom_aprobaciones a
            LEFT JOIN tb_usuarios u ON u.id_usuario = a.usuario_id
            WHERE a.id_bom = $1
            ORDER BY a.created_at ASC
        """, id_bom)
        return [dict(r) for r in rows]

    # ─── ESTADISTICAS ───────────────────────────────────────

    async def get_estadisticas_bom(self, conn, id_bom: UUID) -> dict:
        """Estadisticas de items del BOM: totales, entregados, pendientes, costos."""
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE activo) AS total_items,
                COUNT(*) FILTER (WHERE activo AND entregado) AS entregados,
                COUNT(*) FILTER (WHERE activo AND NOT entregado) AS pendientes,
                COUNT(*) FILTER (WHERE activo AND id_proveedor IS NOT NULL) AS con_proveedor,
                COUNT(*) FILTER (WHERE activo AND fecha_requerida IS NOT NULL) AS con_fecha_requerida,
                COUNT(*) FILTER (WHERE activo AND fecha_requerida IS NOT NULL
                                 AND fecha_requerida < CURRENT_DATE AND NOT entregado) AS atrasados,
                COALESCE(SUM(cantidad * COALESCE(precio_unitario, 0))
                    FILTER (WHERE activo), 0) AS costo_total_estimado,
                COUNT(*) FILTER (WHERE activo AND precio_unitario IS NOT NULL) AS items_con_precio
            FROM tb_bom_items
            WHERE id_bom = $1
        """, id_bom)
        return dict(row) if row else {}

    # ─── CATALOGOS ──────────────────────────────────────────

    async def get_tipos_entrega(self, conn) -> List[dict]:
        """Lista tipos de entrega activos."""
        rows = await conn.fetch("""
            SELECT id, nombre FROM tb_cat_tipos_entrega
            WHERE activo = TRUE ORDER BY orden ASC
        """)
        return [dict(r) for r in rows]

    async def get_categorias_compra(self, conn) -> List[dict]:
        """Lista categorias de compra activas."""
        rows = await conn.fetch("""
            SELECT id, nombre FROM tb_cat_categorias_compra
            WHERE activo = TRUE ORDER BY orden ASC
        """)
        return [dict(r) for r in rows]

    async def get_proveedores(self, conn) -> List[dict]:
        """Lista proveedores activos."""
        rows = await conn.fetch("""
            SELECT id_proveedor, nombre_comercial, razon_social, rfc
            FROM tb_proveedores
            WHERE activo = TRUE
            ORDER BY nombre_comercial ASC
        """)
        return [dict(r) for r in rows]

    async def get_usuarios_por_area(self, conn, module_slug: str, solo_jefes: bool = False) -> List[dict]:
        """Lista usuarios con acceso a un modulo (editor+)."""
        filtro_jefes = "AND u.puede_ser_jefe_area = TRUE" if solo_jefes else ""
        rows = await conn.fetch(f"""
            SELECT u.id_usuario, u.nombre, u.email, pm.rol_modulo
            FROM tb_usuarios u
            JOIN tb_permisos_modulos pm ON pm.usuario_id = u.id_usuario
            WHERE pm.modulo_slug = $1
              AND pm.rol_modulo IN ('editor', 'admin')
              AND u.is_active = TRUE
              {filtro_jefes}
            ORDER BY u.nombre ASC
        """, module_slug)
        return [dict(r) for r in rows]

    async def buscar_materiales_para_bom(
        self, conn, query: str, umbral: float = 0.15, limite: int = 15
    ) -> List[dict]:
        """Busca materiales en historial. Usa ILIKE + word_similarity (pg_trgm)
        para encontrar palabras dentro de descripciones largas."""
        rows = await conn.fetch("""
            SELECT DISTINCT ON (m.descripcion_proveedor)
                m.id,
                m.descripcion_proveedor,
                m.precio_unitario,
                m.unidad,
                m.clave_prod_serv,
                m.fecha_factura,
                p.razon_social AS proveedor_nombre,
                GREATEST(
                    similarity(m.descripcion_proveedor, $1),
                    word_similarity($1, m.descripcion_proveedor)
                ) AS similitud
            FROM tb_materiales_historial m
            LEFT JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
            WHERE m.descripcion_proveedor ILIKE '%' || $1 || '%'
               OR word_similarity($1, m.descripcion_proveedor) >= $2
            ORDER BY m.descripcion_proveedor, m.fecha_factura DESC
        """, query, umbral)
        # Ordenar por similitud descendente y limitar
        result = sorted([dict(r) for r in rows], key=lambda x: x['similitud'], reverse=True)
        return result[:limite]

    async def get_materiales_recientes(self, conn, limite: int = 10) -> List[dict]:
        """Lista materiales mas recientes del historial (para dropdown inicial sin busqueda)."""
        rows = await conn.fetch("""
            SELECT DISTINCT ON (m.descripcion_proveedor)
                m.id,
                m.descripcion_proveedor,
                m.precio_unitario,
                m.unidad,
                m.clave_prod_serv,
                m.fecha_factura,
                p.razon_social AS proveedor_nombre,
                1.0::real AS similitud
            FROM tb_materiales_historial m
            LEFT JOIN tb_proveedores p ON m.id_proveedor = p.id_proveedor
            ORDER BY m.descripcion_proveedor, m.fecha_factura DESC
        """)
        # Los mas recientes primero, limitados
        result = sorted([dict(r) for r in rows], key=lambda x: x['fecha_factura'] or '', reverse=True)
        return result[:limite]

    async def get_proyecto_info(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Obtiene info basica del proyecto."""
        row = await conn.fetchrow("""
            SELECT p.id_proyecto, p.proyecto_id_estandar, o.nombre_proyecto, p.area_actual
            FROM tb_proyectos_gate p
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            WHERE p.id_proyecto = $1
        """, id_proyecto)
        return dict(row) if row else None
