"""
DB Service para BOM (Lista de Materiales).
Queries SQL puras con asyncpg. Recibe conn como parametro.
"""

import logging
import json
from decimal import Decimal
from uuid import UUID
from typing import Optional, List

from core.bom.db_compras import BomComprasDBMixin
from core.bom.schemas import EstatusBOM

logger = logging.getLogger("BOM.DBService")


class BomDBService(BomComprasDBMixin):
    """Capa de acceso a datos para BOM."""

    @staticmethod
    def _merge_item_ejecucion(row) -> dict:
        """Combina campos base del item con el overlay de ejecucion real."""
        item = dict(row)
        item["tipo_origen_item"] = item.get("tipo_origen_item") or "BASE"
        item["id_proveedor_base"] = item.get("id_proveedor")
        item["precio_base"] = item.get("precio_unitario")
        item["importe"] = item.get("importe_base")

        if item.get("id_proveedor_real") is not None:
            item["id_proveedor"] = item["id_proveedor_real"]
        item["proveedor_nombre"] = (
            item.get("proveedor_real_nombre") or item.get("proveedor_base_nombre")
        )

        for real_key, public_key in (
            ("fecha_estimada_entrega_real", "fecha_estimada_entrega"),
            ("fecha_llegada_real_ejecucion", "fecha_llegada_real"),
            ("tipo_entrega_real", "tipo_entrega"),
            ("cantidad_recibida_real", "cantidad_recibida"),
        ):
            if item.get(real_key) is not None:
                item[public_key] = item[real_key]

        cantidad_recibida = item.get("cantidad_recibida") or 0
        cantidad = item.get("cantidad") or 0
        if cantidad and cantidad_recibida >= cantidad:
            item["entregado"] = True

        return item

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
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
        """, id_proyecto, version, EstatusBOM.BORRADOR.value, elaborado_por,
            responsable_ing, jefe_construccion, coordinador_obra, notas)
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
                   p.id_oportunidad,
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
            WHERE b.id_proyecto = $1 AND b.estatus != 'CANCELADO'
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
                   p.id_oportunidad,
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
            WHERE id_proyecto = $1 AND estatus = $2
            ORDER BY version DESC
            LIMIT 1
        """, id_proyecto, EstatusBOM.BORRADOR.value)
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
            'fecha_envio_obra': 'fecha_envio_obra',
            'fecha_aprobacion_obra': 'fecha_aprobacion_obra',
            'fecha_envio_const': 'fecha_envio_const',
            'fecha_aprobacion_const': 'fecha_aprobacion_const',
            'fecha_envio_final': 'fecha_envio_final',
            'fecha_aprobacion_final': 'fecha_aprobacion_final',
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
            SELECT b.id_bom, b.version, b.estatus,
                   b.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
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
        id_material_ref: Optional[UUID] = None,
        id_material_interno: Optional[UUID] = None,
        tipo_partida: Optional[str] = 'MATERIAL',
        moneda: Optional[str] = 'MXN',
        tipo_origen_item: str = 'BASE',
        id_item_reemplazado: Optional[UUID] = None,
        motivo_adenda: Optional[str] = None,
        creado_en_adenda: Optional[UUID] = None,
    ) -> dict:
        """Agrega un item al BOM."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_items (id_bom, id_categoria, descripcion,
                                      cantidad, unidad_medida, comentarios, orden,
                                      precio_unitario, origen_precio, id_material_ref,
                                      id_material_interno, tipo_partida, moneda,
                                      tipo_origen_item, id_item_reemplazado,
                                      motivo_adenda, creado_en_adenda)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17)
            RETURNING *
        """, id_bom, id_categoria, descripcion, cantidad,
            unidad_medida, comentarios, orden,
            precio_unitario, origen_precio, id_material_ref,
            id_material_interno, tipo_partida, moneda,
            tipo_origen_item, id_item_reemplazado, motivo_adenda, creado_en_adenda)
        return dict(row)

    async def get_item_ids_by_bom(self, conn, id_bom: UUID) -> List[UUID]:
        """Ids de items activos de un BOM en el orden de despliegue, para navegacion prev/next."""
        rows = await conn.fetch("""
            SELECT id_item
            FROM tb_bom_items
            WHERE id_bom = $1 AND activo = TRUE
            ORDER BY orden ASC, created_at ASC
        """, id_bom)
        return [r['id_item'] for r in rows]

    async def get_items_by_bom(self, conn, id_bom: UUID, solo_activos: bool = True) -> List[dict]:
        """Lista items de un BOM con datos de categoria y proveedor."""
        filtro_activo = "AND i.activo = TRUE" if solo_activos else ""
        rows = await conn.fetch(f"""
            SELECT i.*,
                   c.nombre AS categoria_nombre,
                   p.nombre_comercial AS proveedor_base_nombre,
                   er.id_proveedor_real,
                   pr.nombre_comercial AS proveedor_real_nombre,
                   er.precio_real,
                   er.moneda_real,
                   er.cantidad_recibida AS cantidad_recibida_real,
                   er.fecha_estimada_entrega AS fecha_estimada_entrega_real,
                   er.fecha_llegada_real AS fecha_llegada_real_ejecucion,
                   er.tipo_entrega AS tipo_entrega_real,
                   er.estatus_ejecucion,
                   er.comentarios_operativos,
                   (i.cantidad * COALESCE(i.precio_unitario, 0)) AS importe_base,
                   (i.cantidad * COALESCE(er.precio_real, 0)) AS importe_real
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_proveedores p ON p.id_proveedor = i.id_proveedor
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            LEFT JOIN tb_proveedores pr ON pr.id_proveedor = er.id_proveedor_real
            WHERE i.id_bom = $1 {filtro_activo}
            ORDER BY i.orden ASC, i.created_at ASC
        """, id_bom)
        return [self._merge_item_ejecucion(r) for r in rows]

    async def get_items_sin_costo_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista items activos sin costo asignado (NULL o menor/igual a cero)."""
        rows = await conn.fetch("""
            SELECT i.id_item,
                   i.descripcion,
                   i.cantidad,
                   i.unidad_medida,
                   i.precio_unitario,
                   i.moneda,
                   i.tipo_partida,
                   i.orden,
                   c.nombre AS categoria_nombre,
                   COALESCE(
                       string_agg(DISTINCT g.codigo, ', ' ORDER BY g.codigo),
                       ''
                   ) AS grupos
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_bom_item_grupos ig ON ig.id_item = i.id_item
            LEFT JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo AND g.activo = TRUE
            WHERE i.id_bom = $1
              AND i.activo = TRUE
              AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
              AND (i.precio_unitario IS NULL OR i.precio_unitario <= 0)
            GROUP BY i.id_item, c.nombre
            ORDER BY i.orden, i.created_at
        """, id_bom)
        return [dict(r) for r in rows]

    async def sincronizar_costos_catalogo(self, conn, id_bom: UUID) -> List[dict]:
        """Sincroniza precio_unitario de items BASE sin costo desde el catalogo interno.

        Precio resuelto por material: precio de la factura XML vinculada mas reciente
        (tb_materiales_interno_xml + tb_materiales_historial) si existe, si no
        precio_referencia del catalogo (tb_cat_materiales). Solo toca items con
        id_material_interno asignado."""
        rows = await conn.fetch("""
            WITH resueltos AS (
                SELECT c.id AS id_material_interno,
                       COALESCE(
                           (SELECT m.precio_unitario
                            FROM tb_materiales_interno_xml v
                            JOIN tb_materiales_historial m ON m.id = v.id_material_xml
                            WHERE v.id_material_interno = c.id
                            ORDER BY m.fecha_factura DESC NULLS LAST
                            LIMIT 1),
                           c.precio_referencia
                       ) AS precio_resuelto
                FROM tb_cat_materiales c
                WHERE c.activo = TRUE
            ),
            candidatos AS (
                SELECT i.id_item, i.descripcion, i.precio_unitario AS precio_anterior,
                       i.origen_precio AS origen_precio_anterior,
                       r.precio_resuelto
                FROM tb_bom_items i
                JOIN resueltos r ON r.id_material_interno = i.id_material_interno
                WHERE i.id_bom = $1
                  AND i.activo = TRUE
                  AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
                  AND (i.precio_unitario IS NULL OR i.precio_unitario <= 0)
                  AND r.precio_resuelto IS NOT NULL
                  AND r.precio_resuelto > 0
            )
            UPDATE tb_bom_items i
            SET precio_unitario = c.precio_resuelto,
                origen_precio = 'CATALOGO',
                updated_at = now()
            FROM candidatos c
            WHERE i.id_item = c.id_item
            RETURNING i.id_item, c.descripcion, c.precio_anterior, c.origen_precio_anterior, c.precio_resuelto
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_item_by_id(self, conn, id_item: UUID) -> Optional[dict]:
        """Obtiene un item por ID con datos de BOM."""
        row = await conn.fetchrow("""
            SELECT i.*,
                   c.nombre AS categoria_nombre,
                   p.nombre_comercial AS proveedor_base_nombre,
                   er.id_proveedor_real,
                   pr.nombre_comercial AS proveedor_real_nombre,
                   er.precio_real,
                   er.moneda_real,
                   er.cantidad_recibida AS cantidad_recibida_real,
                   er.fecha_estimada_entrega AS fecha_estimada_entrega_real,
                   er.fecha_llegada_real AS fecha_llegada_real_ejecucion,
                   er.tipo_entrega AS tipo_entrega_real,
                   er.estatus_ejecucion,
                   er.comentarios_operativos,
                   b.estatus AS bom_estatus,
                   b.id_proyecto,
                   b.version AS bom_version,
                   (i.cantidad * COALESCE(i.precio_unitario, 0)) AS importe_base,
                   (i.cantidad * COALESCE(er.precio_real, 0)) AS importe_real
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_proveedores p ON p.id_proveedor = i.id_proveedor
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            LEFT JOIN tb_proveedores pr ON pr.id_proveedor = er.id_proveedor_real
            JOIN tb_bom b ON b.id_bom = i.id_bom
            WHERE i.id_item = $1
        """, id_item)
        return self._merge_item_ejecucion(row) if row else None

    async def get_items_by_ids(self, conn, item_ids: List[UUID]) -> List[dict]:
        """Obtiene varios items por lista de IDs. Solo items activos."""
        rows = await conn.fetch("""
            SELECT i.id_item, i.descripcion, i.cantidad, i.moneda,
                   i.estatus_compra, i.activo, i.precio_unitario, i.origen_precio,
                   COALESCE(i.tipo_origen_item, 'BASE') AS tipo_origen_item,
                   i.id_item_reemplazado, i.creado_en_adenda,
                   a.estatus AS adenda_estatus,
                   er.estatus_ejecucion
            FROM tb_bom_items i
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            LEFT JOIN tb_bom_adendas a ON a.id_adenda = i.creado_en_adenda
            WHERE i.id_item = ANY($1::uuid[]) AND i.activo = TRUE
        """, item_ids)
        return [dict(r) for r in rows]

    async def get_items_context_by_ids(self, conn, item_ids: List[UUID]) -> List[dict]:
        """Obtiene items con contexto del BOM para validaciones de lote."""
        rows = await conn.fetch("""
            SELECT i.*,
                   er.estatus_ejecucion,
                   b.estatus AS bom_estatus,
                   b.id_proyecto,
                   b.version AS bom_version
            FROM tb_bom_items i
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            JOIN tb_bom b ON b.id_bom = i.id_bom
            WHERE i.id_item = ANY($1::uuid[])
        """, item_ids)
        return [dict(r) for r in rows]

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
            'precio_unitario', 'origen_precio', 'id_material_ref',
            'cantidad_recibida', 'tipo_partida', 'moneda'
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

    async def upsert_item_ejecucion(
        self, conn, id_item: UUID, updated_by: Optional[UUID] = None, **campos
    ) -> Optional[dict]:
        """Inserta o actualiza los datos reales de ejecucion/compra de un item."""
        allowed = {
            "id_proveedor_real",
            "precio_real",
            "moneda_real",
            "cantidad_recibida",
            "fecha_estimada_entrega",
            "fecha_llegada_real",
            "tipo_entrega",
            "estatus_ejecucion",
            "comentarios_operativos",
        }
        data = {key: val for key, val in campos.items() if key in allowed}
        if not data:
            return await self.get_item_by_id(conn, id_item)

        columns = ["id_item", *data.keys(), "updated_by"]
        params = [id_item, *data.values(), updated_by]
        placeholders = ", ".join(f"${idx}" for idx in range(1, len(params) + 1))
        updates = ", ".join(
            f"{key} = EXCLUDED.{key}" for key in data
        )
        query = f"""
            INSERT INTO tb_bom_item_ejecucion ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (id_item) DO UPDATE
            SET {updates},
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
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
        """Copia items activos de un BOM a otro con trazabilidad de origen.
        Items FACTURADOS/PAGADOS se copian como bloqueados.
        Retorna cantidad copiada."""
        result = await conn.execute("""
            INSERT INTO tb_bom_items (id_bom, id_categoria, descripcion,
                                      cantidad, unidad_medida, fecha_requerida,
                                      id_proveedor, tipo_entrega,
                                      fecha_estimada_entrega, comentarios, orden,
                                      precio_unitario, origen_precio, id_material_ref,
                                      id_material_interno, tipo_partida, moneda,
                                      estatus_compra, id_item_origen, bloqueado,
                                      tipo_origen_item, id_item_reemplazado,
                                      motivo_adenda, creado_en_adenda)
            SELECT $2, id_categoria, descripcion,
                   cantidad, unidad_medida, fecha_requerida,
                   id_proveedor, tipo_entrega,
                   fecha_estimada_entrega, comentarios, orden,
                   precio_unitario, origen_precio, id_material_ref,
                   id_material_interno, tipo_partida, moneda,
                   estatus_compra, id_item,
                   (estatus_compra IN ('PAGADO', 'FACTURADO')),
                   COALESCE(tipo_origen_item, 'BASE'), id_item_reemplazado,
                   motivo_adenda, creado_en_adenda
            FROM tb_bom_items
            WHERE id_bom = $1 AND activo = TRUE
            ORDER BY orden ASC
        """, id_bom_origen, id_bom_destino)
        count = int(result.split()[-1]) if result else 0
        return count

    async def crear_adenda(
        self, conn, id_bom_base: UUID, tipo_adenda: str,
        motivo: str, creado_por: UUID,
        estatus: str = "PENDIENTE_CONSTRUCCION",
    ) -> dict:
        """Crea el encabezado de una adenda operativa del BOM."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_adendas (
                id_bom_base, tipo_adenda, motivo, estatus,
                creado_por, enviado_construccion_por, fecha_envio_construccion
            )
            VALUES ($1, $2, $3, $4, $5, $5, NOW())
            RETURNING *
        """, id_bom_base, tipo_adenda, motivo, estatus, creado_por)
        return dict(row)

    async def registrar_adenda_item(
        self, conn, id_adenda: UUID, tipo_linea: str, motivo: str,
        id_item_origen: Optional[UUID] = None,
        id_item_bom: Optional[UUID] = None,
        datos_item: Optional[dict] = None,
        grupo_ids: Optional[List[int]] = None,
    ) -> dict:
        """Registra la relacion entre adenda, item origen e item generado."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_adenda_items
                (id_adenda, id_item_origen, id_item_bom, tipo_linea, motivo,
                 datos_item, grupo_ids)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::integer[])
            RETURNING *
        """, id_adenda, id_item_origen, id_item_bom, tipo_linea, motivo,
             json.dumps(datos_item or {}), grupo_ids or [])
        return dict(row)

    async def get_adenda_by_id(self, conn, id_adenda: UUID) -> Optional[dict]:
        """Obtiene una adenda con contexto de BOM para validaciones."""
        row = await conn.fetchrow("""
            SELECT a.*,
                   b.id_bom AS id_bom,
                   b.id_proyecto,
                   b.version AS bom_version,
                   b.estatus AS bom_estatus,
                   b.elaborado_por,
                   b.responsable_ing,
                   b.coordinador_obra,
                   b.jefe_construccion
            FROM tb_bom_adendas a
            JOIN tb_bom b ON b.id_bom = a.id_bom_base
            WHERE a.id_adenda = $1
        """, id_adenda)
        return dict(row) if row else None

    async def get_adenda_items(self, conn, id_adenda: UUID) -> List[dict]:
        """Lista lineas propuestas o aplicadas de una adenda."""
        rows = await conn.fetch("""
            SELECT ai.*,
                   origen.descripcion AS origen_descripcion,
                   item.descripcion AS item_bom_descripcion
            FROM tb_bom_adenda_items ai
            LEFT JOIN tb_bom_items origen ON origen.id_item = ai.id_item_origen
            LEFT JOIN tb_bom_items item ON item.id_item = ai.id_item_bom
            WHERE ai.id_adenda = $1
            ORDER BY ai.created_at, ai.id_adenda_item
        """, id_adenda)
        return [dict(r) for r in rows]

    async def marcar_adenda_construccion(
        self, conn, id_adenda: UUID, user_id: UUID, requiere_ingenieria: bool
    ) -> dict:
        """Registra aprobacion de Construccion y deja la adenda en el siguiente paso."""
        siguiente = "PENDIENTE_INGENIERIA" if requiere_ingenieria else "APROBADA"
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = $3,
                requiere_aprobacion_ingenieria = $4,
                aprobado_construccion_por = $2,
                fecha_aprobacion_construccion = NOW(),
                updated_at = NOW()
            WHERE id_adenda = $1
            RETURNING *
        """, id_adenda, user_id, siguiente, requiere_ingenieria)
        return dict(row) if row else None

    async def aprobar_adenda_ingenieria(
        self, conn, id_adenda: UUID, user_id: UUID
    ) -> dict:
        """Registra aprobacion tecnica de Ingenieria y marca la adenda aprobada."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = 'APROBADA',
                aprobado_ingenieria_por = $2,
                fecha_aprobacion_ingenieria = NOW(),
                updated_at = NOW()
            WHERE id_adenda = $1
            RETURNING *
        """, id_adenda, user_id)
        return dict(row) if row else None

    async def rechazar_adenda(
        self, conn, id_adenda: UUID, user_id: UUID, motivo_rechazo: str
    ) -> dict:
        """Rechaza una adenda pendiente sin aplicar cambios al BOM."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = 'RECHAZADA',
                rechazado_por = $2,
                fecha_rechazo = NOW(),
                motivo_rechazo = $3,
                updated_at = NOW()
            WHERE id_adenda = $1
            RETURNING *
        """, id_adenda, user_id, motivo_rechazo)
        return dict(row) if row else None

    async def cancelar_adenda(
        self, conn, id_adenda: UUID, user_id: UUID
    ) -> dict:
        """Cancela una adenda pendiente de construccion sin mutar items."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = 'CANCELADA',
                cancelado_por = $2,
                fecha_cancelacion = NOW(),
                updated_at = NOW()
            WHERE id_adenda = $1
            RETURNING *
        """, id_adenda, user_id)
        return dict(row) if row else None

    async def vincular_adenda_item_bom(
        self, conn, id_adenda_item: UUID, id_item_bom: UUID
    ) -> dict:
        """Vincula una linea de adenda con el item creado al aprobar."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adenda_items
            SET id_item_bom = $2,
                updated_at = NOW()
            WHERE id_adenda_item = $1
            RETURNING *
        """, id_adenda_item, id_item_bom)
        return dict(row) if row else None

    async def registrar_adenda_comentario(
        self, conn, id_adenda: UUID, comentario: str, creado_por: UUID
    ) -> dict:
        """Agrega un comentario a una adenda."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_adenda_comentarios (id_adenda, comentario, creado_por)
            VALUES ($1, $2, $3)
            RETURNING *
        """, id_adenda, comentario, creado_por)
        return dict(row)

    async def get_adenda_comentarios(self, conn, id_adenda: UUID) -> List[dict]:
        """Lista comentarios de una adenda."""
        rows = await conn.fetch("""
            SELECT c.*,
                   u.nombre AS creado_por_nombre
            FROM tb_bom_adenda_comentarios c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE c.id_adenda = $1
            ORDER BY c.created_at ASC
        """, id_adenda)
        return [dict(r) for r in rows]

    async def get_adenda_comentarios_by_bom(self, conn, id_bom: UUID) -> dict:
        """Lista comentarios de todas las adendas de un BOM agrupados por adenda."""
        rows = await conn.fetch("""
            SELECT c.*,
                   u.nombre AS creado_por_nombre
            FROM tb_bom_adenda_comentarios c
            JOIN tb_bom_adendas a ON a.id_adenda = c.id_adenda
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE a.id_bom_base = $1
            ORDER BY c.created_at ASC
        """, id_bom)
        result: dict = {}
        for row in rows:
            data = dict(row)
            result.setdefault(str(data["id_adenda"]), []).append(data)
        return result

    async def get_item_compra_bloqueante(self, conn, id_item: UUID) -> dict:
        """Indica si un item ya tiene cotizacion seleccionada o autorizacion activa."""
        row = await conn.fetchrow("""
            SELECT
                EXISTS (
                    SELECT 1
                    FROM tb_bom_cotizacion_items ci
                    JOIN tb_bom_cotizaciones c ON c.id = ci.cotizacion_id
                    WHERE ci.bom_item_id = $1
                      AND c.estatus = 'SELECCIONADA'
                ) AS tiene_cotizacion_seleccionada,
                EXISTS (
                    SELECT 1
                    FROM tb_bom_cotizacion_items ci
                    JOIN tb_bom_autorizaciones a ON a.cotizacion_id = ci.cotizacion_id
                    WHERE ci.bom_item_id = $1
                      AND a.estatus IN (
                          'PENDIENTE',
                          'AUTORIZADO_OBRA',
                          'AUTORIZADO_DIRECCION',
                          'AUTORIZADO_FINANZAS'
                      )
                ) AS tiene_autorizacion_activa
        """, id_item)
        return dict(row) if row else {
            "tiene_cotizacion_seleccionada": False,
            "tiene_autorizacion_activa": False,
        }

    async def crear_propuesta_cambio(
        self, conn, id_bom: UUID, tipo_solicitante: str,
        motivo: str, lineas: list, creado_por: UUID
    ) -> dict:
        """Crea una propuesta de cambio pre-final pendiente de Ingenieria."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_propuestas_cambio
                (id_bom, tipo_solicitante, motivo, lineas, creado_por)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            RETURNING *
        """, id_bom, tipo_solicitante, motivo, json.dumps(lineas or []), creado_por)
        return dict(row)

    async def get_propuesta_cambio_by_id(
        self, conn, id_propuesta: UUID
    ) -> Optional[dict]:
        """Obtiene una propuesta con contexto del BOM."""
        row = await conn.fetchrow("""
            SELECT p.*,
                   b.id_proyecto,
                   b.version AS bom_version,
                   b.estatus AS bom_estatus,
                   b.elaborado_por,
                   b.responsable_ing,
                   b.coordinador_obra,
                   b.jefe_construccion
            FROM tb_bom_propuestas_cambio p
            JOIN tb_bom b ON b.id_bom = p.id_bom
            WHERE p.id_propuesta = $1
        """, id_propuesta)
        if not row:
            return None
        data = dict(row)
        if isinstance(data.get("lineas"), str):
            data["lineas"] = json.loads(data["lineas"] or "[]")
        return data

    async def get_propuestas_cambio_by_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista propuestas de cambio pre-final de un BOM."""
        rows = await conn.fetch("""
            SELECT p.*,
                   u.nombre AS creado_por_nombre,
                   r.nombre AS revisado_por_nombre
            FROM tb_bom_propuestas_cambio p
            LEFT JOIN tb_usuarios u ON u.id_usuario = p.creado_por
            LEFT JOIN tb_usuarios r ON r.id_usuario = p.revisado_por
            WHERE p.id_bom = $1
            ORDER BY p.created_at DESC
        """, id_bom)
        result = []
        for row in rows:
            data = dict(row)
            if isinstance(data.get("lineas"), str):
                data["lineas"] = json.loads(data["lineas"] or "[]")
            result.append(data)
        return result

    async def actualizar_propuesta_cambio_revision(
        self, conn, id_propuesta: UUID, estatus: str, revisado_por: UUID,
        comentario_revision: Optional[str] = None
    ) -> dict:
        """Marca una propuesta como revisada."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_propuestas_cambio
            SET estatus = $2,
                revisado_por = $3,
                fecha_revision = NOW(),
                comentario_revision = $4,
                updated_at = NOW()
            WHERE id_propuesta = $1
            RETURNING *
        """, id_propuesta, estatus, revisado_por, comentario_revision)
        return dict(row) if row else None

    async def get_adendas_by_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista adendas del BOM con resumen de lineas afectadas."""
        rows = await conn.fetch("""
            SELECT a.*,
                   u.nombre AS creado_por_nombre,
                   uc.nombre AS aprobado_construccion_por_nombre,
                   ui.nombre AS aprobado_ingenieria_por_nombre,
                   ur.nombre AS rechazado_por_nombre,
                   COUNT(ai.id_adenda_item) AS total_lineas,
                   COALESCE(
                       string_agg(
                           DISTINCT COALESCE(
                               item.descripcion,
                               origen.descripcion,
                               ai.datos_item->>'descripcion'
                           ),
                           ', '
                       ) FILTER (
                           WHERE COALESCE(
                               item.descripcion,
                               origen.descripcion,
                               ai.datos_item->>'descripcion'
                           ) IS NOT NULL
                       ),
                       ''
                   ) AS items_resumen
            FROM tb_bom_adendas a
            LEFT JOIN tb_usuarios u ON u.id_usuario = a.creado_por
            LEFT JOIN tb_usuarios uc ON uc.id_usuario = a.aprobado_construccion_por
            LEFT JOIN tb_usuarios ui ON ui.id_usuario = a.aprobado_ingenieria_por
            LEFT JOIN tb_usuarios ur ON ur.id_usuario = a.rechazado_por
            LEFT JOIN tb_bom_adenda_items ai ON ai.id_adenda = a.id_adenda
            LEFT JOIN tb_bom_items origen ON origen.id_item = ai.id_item_origen
            LEFT JOIN tb_bom_items item ON item.id_item = ai.id_item_bom
            WHERE a.id_bom_base = $1
            GROUP BY a.id_adenda, u.nombre, uc.nombre, ui.nombre, ur.nombre
            ORDER BY a.created_at DESC
        """, id_bom)
        return [dict(r) for r in rows]

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
            SELECT h.id, h.id_bom, h.id_item, h.accion, h.campo_modificado,
                   h.valor_anterior, h.valor_nuevo, h.version_bom, h.realizado_por,
                   h.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
                   u.nombre AS realizado_por_nombre
            FROM tb_bom_historial h
            LEFT JOIN tb_usuarios u ON u.id_usuario = h.realizado_por
            WHERE h.id_bom = $1
            ORDER BY h.created_at DESC
        """, id_bom)
        return [dict(r) for r in rows]

    # ─── APROBACIONES ───────────────────────────────────────

    async def registrar_aprobacion(
        self, conn, id_bom: UUID, tipo: str, version_bom: int,
        usuario_id: UUID, comentarios: Optional[str] = None,
        destino_rechazo: Optional[str] = None,
    ) -> dict:
        """Registra una accion de aprobacion/rechazo."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_aprobaciones (id_bom, tipo, version_bom,
                                             usuario_id, comentarios,
                                             destino_rechazo)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """, id_bom, tipo, version_bom, usuario_id, comentarios, destino_rechazo)
        return dict(row)

    async def get_aprobaciones_by_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista aprobaciones/rechazos de un BOM."""
        rows = await conn.fetch("""
            SELECT a.id, a.id_bom, a.tipo, a.version_bom, a.usuario_id,
                   a.comentarios, a.destino_rechazo,
                   a.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
                   u.nombre AS usuario_nombre
            FROM tb_bom_aprobaciones a
            LEFT JOIN tb_usuarios u ON u.id_usuario = a.usuario_id
            WHERE a.id_bom = $1
            ORDER BY a.created_at ASC
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_ultimo_rechazo(self, conn, id_bom: UUID) -> Optional[dict]:
        """Obtiene el ultimo rechazo/devolucion del BOM."""
        row = await conn.fetchrow("""
            SELECT a.tipo, a.comentarios, a.destino_rechazo,
                   a.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
                   u.nombre AS rechazado_por
            FROM tb_bom_aprobaciones a
            JOIN tb_usuarios u ON a.usuario_id = u.id_usuario
            WHERE a.id_bom = $1
              AND a.tipo IN (
                  'RECHAZO_ING', 'RECHAZO_OBRA', 'RECHAZO_CONST',
                  'RECHAZO_FINAL', 'DEVOLUCION_BORRADOR'
              )
            ORDER BY a.created_at DESC LIMIT 1
        """, id_bom)
        return dict(row) if row else None

    # ─── ESTADISTICAS ───────────────────────────────────────

    async def get_estadisticas_bom(self, conn, id_bom: UUID) -> dict:
        """Estadisticas de items del BOM: totales, entregados, pendientes, costos, recepcion."""
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE i.activo) AS total_items,
                COUNT(*) FILTER (
                    WHERE i.activo
                      AND (
                          i.entregado
                          OR (i.cantidad > 0 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad)
                      )
                ) AS entregados,
                COUNT(*) FILTER (
                    WHERE i.activo
                      AND NOT (
                          i.entregado
                          OR (i.cantidad > 0 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad)
                      )
                ) AS pendientes,
                COUNT(*) FILTER (WHERE i.activo AND COALESCE(er.id_proveedor_real, i.id_proveedor) IS NOT NULL) AS con_proveedor,
                COUNT(*) FILTER (WHERE i.activo AND i.fecha_requerida IS NOT NULL) AS con_fecha_requerida,
                COUNT(*) FILTER (WHERE i.activo AND i.fecha_requerida IS NOT NULL
                                 AND i.fecha_requerida < CURRENT_DATE
                                 AND NOT (
                                     i.entregado
                                     OR (i.cantidad > 0 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad)
                                 )) AS atrasados,
                COALESCE(SUM(i.cantidad * COALESCE(i.precio_unitario, 0))
                    FILTER (WHERE i.activo AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'), 0) AS costo_total_estimado,
                COUNT(*) FILTER (
                    WHERE i.activo
                      AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
                      AND i.precio_unitario > 0
                ) AS items_con_precio,
                COUNT(*) FILTER (
                    WHERE i.activo
                      AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
                      AND (i.precio_unitario IS NULL OR i.precio_unitario <= 0)
                ) AS items_sin_costo,
                COUNT(*) FILTER (
                    WHERE i.activo AND COALESCE(i.tipo_origen_item, 'BASE') = 'REEMPLAZO'
                ) AS items_reemplazo,
                COUNT(*) FILTER (
                    WHERE i.activo AND COALESCE(i.tipo_origen_item, 'BASE') = 'FUERA_SCOPE'
                ) AS items_fuera_scope,
                COUNT(*) FILTER (
                    WHERE i.activo AND er.estatus_ejecucion IN ('NO_ADQUIRIDO', 'REEMPLAZADO', 'CERRADO')
                ) AS items_no_adquiridos,
                COUNT(*) FILTER (WHERE i.activo AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) > 0
                                 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) < i.cantidad) AS items_parcialmente_recibidos,
                COUNT(*) FILTER (WHERE i.activo AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad
                                 AND i.cantidad > 0) AS items_completamente_recibidos
            FROM tb_bom_items i
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            WHERE i.id_bom = $1
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
        """Lista usuarios activos por modulo; jefes salen de rol_organizacional."""
        if solo_jefes:
            rol_org_por_modulo = {
                "ingenieria": "jefe_ingenieria",
                "construccion": "jefe_construccion",
            }
            rol_org = rol_org_por_modulo.get(module_slug)
            if not rol_org:
                return []
            rows = await conn.fetch("""
                SELECT id_usuario, nombre, email, rol_organizacional
                FROM tb_usuarios
                WHERE rol_organizacional = $1
                  AND is_active = TRUE
                ORDER BY nombre ASC
            """, rol_org)
            return [dict(r) for r in rows]

        rows = await conn.fetch("""
            SELECT u.id_usuario, u.nombre, u.email, pm.rol_modulo
            FROM tb_usuarios u
            JOIN tb_permisos_modulos pm ON pm.usuario_id = u.id_usuario
            WHERE pm.modulo_slug = $1
              AND pm.rol_modulo IN ('editor', 'admin')
              AND u.is_active = TRUE
            ORDER BY u.nombre ASC
        """, module_slug)
        return [dict(r) for r in rows]

    async def buscar_materiales_para_bom(
        self, conn, query: str, query_norm: str = "",
        umbral: float = 0.15, limite: int = 20, offset: int = 0
    ) -> dict:
        """Busca materiales en historial XML y catalogo interno.
        query_norm debe ser normalizar_descripcion(query) para el matching contra descripcion_norm."""
        rows = await conn.fetch("""
            WITH xml_dedup AS (
                SELECT DISTINCT ON (m.descripcion_proveedor)
                    m.id::text                                        AS id,
                    m.descripcion_proveedor                           AS descripcion,
                    COALESCE(m.unidad_homologada, m.unidad)           AS unidad,
                    m.precio_unitario,
                    p.razon_social                                     AS proveedor_nombre,
                    NULL::text                                         AS categoria_nombre,
                    m.clave_prod_serv,
                    m.fecha_factura,
                    'XML'::text                                        AS fuente,
                    GREATEST(
                        similarity(m.descripcion_proveedor, $1),
                        word_similarity($1, m.descripcion_proveedor)
                    )                                                  AS similitud,
                    vlink.id_material_interno
                FROM tb_materiales_historial m
                LEFT JOIN tb_proveedores p ON p.id_proveedor = m.id_proveedor
                LEFT JOIN tb_materiales_interno_xml vlink ON vlink.id_material_xml = m.id
                WHERE m.descripcion_proveedor ILIKE '%' || $1 || '%'
                   OR word_similarity($1, m.descripcion_proveedor) >= $2
                ORDER BY m.descripcion_proveedor,
                         (vlink.id_material_interno IS NOT NULL) DESC,
                         m.fecha_factura DESC
            )
            SELECT
                xd.id, xd.descripcion, xd.unidad, xd.precio_unitario,
                xd.proveedor_nombre, xd.categoria_nombre, xd.clave_prod_serv,
                xd.fecha_factura, xd.fuente, xd.similitud,
                ci.descripcion_canonica                                AS descripcion_interna,
                xd.id_material_interno::text                           AS id_material_interno
            FROM xml_dedup xd
            LEFT JOIN tb_cat_materiales ci ON ci.id = xd.id_material_interno
            UNION ALL
            SELECT
                c.id::text,
                c.descripcion_canonica,
                u.codigo,
                c.precio_referencia,
                NULL,
                cat.nombre,
                c.clave_prod_serv,
                NULL::date,
                'INTERNO'::text,
                GREATEST(
                    similarity(c.descripcion_norm, $3),
                    word_similarity($3, c.descripcion_norm)
                ),
                NULL::text,
                NULL::text
            FROM tb_cat_materiales c
            LEFT JOIN tb_cat_unidades_medida u   ON u.id  = c.id_unidad_medida
            LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
            WHERE c.activo = TRUE
              AND (c.descripcion_norm ILIKE '%' || $3 || '%'
                   OR word_similarity($3, c.descripcion_norm) >= $2)
              AND NOT EXISTS (
                  SELECT 1 FROM tb_materiales_interno_xml v
                  WHERE v.id_material_interno = c.id
              )
        """, query, umbral, query_norm or query)
        rows_list = [dict(r) for r in rows]
        xml_items = sorted(
            [r for r in rows_list if r['fuente'] == 'XML'],
            key=lambda x: -(float(x['similitud'] or 0)),
        )
        int_items = sorted(
            [r for r in rows_list if r['fuente'] == 'INTERNO'],
            key=lambda x: -(float(x['similitud'] or 0)),
        )
        result = xml_items + int_items
        return {
            "items": result[offset:offset + limite],
            "total": len(result),
            "limit": limite,
            "offset": offset,
        }

    async def get_materiales_recientes(self, conn, limite: int = 10, offset: int = 0) -> dict:
        """Lista materiales recientes (XML) y todos los internos activos para el dropdown inicial."""
        rows = await conn.fetch("""
            WITH xml_dedup AS (
                SELECT DISTINCT ON (m.descripcion_proveedor)
                    m.id::text                              AS id,
                    m.descripcion_proveedor                 AS descripcion,
                    COALESCE(m.unidad_homologada, m.unidad) AS unidad,
                    m.precio_unitario,
                    p.razon_social                          AS proveedor_nombre,
                    NULL::text                              AS categoria_nombre,
                    m.clave_prod_serv,
                    m.fecha_factura,
                    'XML'::text                             AS fuente,
                    1.0::real                               AS similitud,
                    vlink.id_material_interno
                FROM tb_materiales_historial m
                LEFT JOIN tb_proveedores p ON p.id_proveedor = m.id_proveedor
                LEFT JOIN tb_materiales_interno_xml vlink ON vlink.id_material_xml = m.id
                ORDER BY m.descripcion_proveedor,
                         (vlink.id_material_interno IS NOT NULL) DESC,
                         m.fecha_factura DESC
            )
            SELECT
                xd.id, xd.descripcion, xd.unidad, xd.precio_unitario,
                xd.proveedor_nombre, xd.categoria_nombre, xd.clave_prod_serv,
                xd.fecha_factura, xd.fuente, xd.similitud,
                ci.descripcion_canonica                 AS descripcion_interna,
                xd.id_material_interno::text            AS id_material_interno
            FROM xml_dedup xd
            LEFT JOIN tb_cat_materiales ci ON ci.id = xd.id_material_interno
            UNION ALL
            SELECT
                c.id::text,
                c.descripcion_canonica,
                u.codigo,
                c.precio_referencia,
                NULL,
                cat.nombre,
                c.clave_prod_serv,
                (c.created_at AT TIME ZONE 'America/Mexico_City')::date,
                'INTERNO'::text,
                1.0::real,
                NULL::text,
                NULL::text
            FROM tb_cat_materiales c
            LEFT JOIN tb_cat_unidades_medida u   ON u.id  = c.id_unidad_medida
            LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
            WHERE c.activo = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM tb_materiales_interno_xml v
                  WHERE v.id_material_interno = c.id
              )
        """)
        rows_list = [dict(r) for r in rows]
        xml_items = sorted(
            [r for r in rows_list if r['fuente'] == 'XML'],
            key=lambda x: x['fecha_factura'].isoformat() if x.get('fecha_factura') else '',
            reverse=True,
        )
        int_items = sorted(
            [r for r in rows_list if r['fuente'] == 'INTERNO'],
            key=lambda x: (x.get('descripcion') or '').lower(),
        )
        result = xml_items + int_items
        return {
            "items": result[offset:offset + limite],
            "total": len(result),
            "limit": limite,
            "offset": offset,
        }

    async def get_proyecto_info(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Obtiene info basica del proyecto."""
        row = await conn.fetchrow("""
            SELECT p.id_proyecto, p.proyecto_id_estandar, o.nombre_proyecto, p.area_actual
            FROM tb_proyectos_gate p
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            WHERE p.id_proyecto = $1
        """, id_proyecto)
        return dict(row) if row else None

    async def get_usuario_activo_por_rol_org(
        self, conn, rol_organizacional: str
    ) -> Optional[dict]:
        """Obtiene el usuario activo con un rol organizacional."""
        rows = await conn.fetch("""
            SELECT id_usuario, nombre, email, rol_organizacional
            FROM tb_usuarios
            WHERE rol_organizacional = $1
              AND is_active = TRUE
            ORDER BY nombre ASC
        """, rol_organizacional)
        if len(rows) > 1:
            logger.warning(
                "Multiples usuarios activos con rol_organizacional='%s': %s — usando primero",
                rol_organizacional, [r['nombre'] for r in rows]
            )
        return dict(rows[0]) if rows else None

    async def get_responsable_proyecto_o_global(
        self, conn, id_proyecto, rol_organizacional: str
    ) -> Optional[dict]:
        """
        Resuelve el jefe del area para un proyecto: primero el RC/RI persistido en
        tb_proyecto_usuarios; si el proyecto aun no lo tiene, cae al primer jefe
        organizacional activo (comportamiento previo).
        """
        rol_resp = {
            "jefe_construccion": "responsable_construccion",
            "jefe_ingenieria": "responsable_ingenieria",
        }.get(rol_organizacional)
        if rol_resp:
            row = await conn.fetchrow(
                """
                SELECT u.id_usuario, u.nombre, u.email
                FROM tb_proyecto_usuarios pu
                JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
                WHERE pu.id_proyecto = $1 AND pu.rol_proyecto = $2 AND pu.activo = TRUE
                  AND u.is_active = TRUE
                LIMIT 1
                """,
                id_proyecto, rol_resp,
            )
            if row:
                return dict(row)
        return await self.get_usuario_activo_por_rol_org(conn, rol_organizacional)

    async def get_asignacion_proyecto(
        self, conn, id_proyecto: UUID, rol_proyecto: str, area: str
    ) -> Optional[dict]:
        """Obtiene una asignacion activa del equipo del proyecto."""
        row = await conn.fetchrow("""
            SELECT pu.id_usuario, pu.rol_proyecto, pu.area, u.nombre, u.email
            FROM tb_proyecto_usuarios pu
            JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
            WHERE pu.id_proyecto = $1
              AND pu.rol_proyecto = $2
              AND pu.area = $3
              AND pu.activo = TRUE
              AND u.is_active = TRUE
            LIMIT 1
        """, id_proyecto, rol_proyecto, area)
        return dict(row) if row else None

    async def get_asignaciones_proyecto(
        self, conn, id_proyecto: UUID, roles: List[str], area: str
    ) -> dict:
        """Obtiene varias asignaciones activas del proyecto en una sola consulta.

        Retorna dict {rol_proyecto: row}, solo con los roles que tienen asignacion activa.
        """
        rows = await conn.fetch("""
            SELECT pu.id_usuario, pu.rol_proyecto, pu.area, u.nombre, u.email
            FROM tb_proyecto_usuarios pu
            JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
            WHERE pu.id_proyecto = $1
              AND pu.rol_proyecto = ANY($2::text[])
              AND pu.area = $3
              AND pu.activo = TRUE
              AND u.is_active = TRUE
        """, id_proyecto, roles, area)
        return {row['rol_proyecto']: dict(row) for row in rows}

    async def usuario_tiene_rol_org(
        self, conn, user_id: UUID, rol_organizacional: str
    ) -> bool:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM tb_usuarios
                WHERE id_usuario = $1
                  AND rol_organizacional = $2
                  AND is_active = TRUE
            )
        """, user_id, rol_organizacional)
        return bool(exists)

    async def usuario_tiene_asignacion_proyecto(
        self,
        conn,
        id_proyecto: UUID,
        user_id: UUID,
        rol_proyecto: str,
        area: str,
    ) -> bool:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM tb_proyecto_usuarios pu
                JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
                WHERE pu.id_proyecto = $1
                  AND pu.id_usuario = $2
                  AND pu.rol_proyecto = $3
                  AND pu.area = $4
                  AND pu.activo = TRUE
                  AND u.is_active = TRUE
            )
        """, id_proyecto, user_id, rol_proyecto, area)
        return bool(exists)

    # ─── GRUPOS BOM ─────────────────────────────────────────

    async def get_grupos_bom(self, conn) -> List[dict]:
        """Lista grupos BOM activos (AC/DC/CM/OC/TE)."""
        rows = await conn.fetch("""
            SELECT id, codigo, nombre, orden
            FROM tb_cat_grupos_bom
            WHERE activo = TRUE
            ORDER BY orden ASC
        """)
        return [dict(r) for r in rows]

    async def get_grupos_por_item(self, conn, id_item: UUID) -> List[str]:
        """Retorna lista de codigos de grupos para un item."""
        rows = await conn.fetch("""
            SELECT g.codigo
            FROM tb_bom_item_grupos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            WHERE ig.id_item = $1
            ORDER BY g.orden ASC
        """, id_item)
        return [r['codigo'] for r in rows]

    async def get_grupos_operativos_por_item(self, conn, id_item: UUID) -> List[str]:
        """Retorna lista de codigos de grupos operativos para un item."""
        rows = await conn.fetch("""
            SELECT g.codigo
            FROM tb_bom_item_grupos_operativos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            WHERE ig.id_item = $1
              AND g.activo = TRUE
            ORDER BY g.orden ASC
        """, id_item)
        return [r['codigo'] for r in rows]

    async def get_grupos_por_bom(self, conn, id_bom: UUID) -> dict:
        """Retorna mapa {id_item: [codigo, ...]} para todos los items del BOM. Previene N+1."""
        rows = await conn.fetch("""
            SELECT ig.id_item, g.codigo
            FROM tb_bom_item_grupos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            JOIN tb_bom_items i ON i.id_item = ig.id_item
            WHERE i.id_bom = $1 AND i.activo = TRUE
            ORDER BY g.orden ASC
        """, id_bom)
        result: dict = {}
        for r in rows:
            key = str(r['id_item'])
            result.setdefault(key, [])
            result[key].append(r['codigo'])
        return result

    async def get_grupos_operativos_por_bom(self, conn, id_bom: UUID) -> dict:
        """Retorna mapa {id_item: [codigo, ...]} de grupos operativos."""
        rows = await conn.fetch("""
            SELECT ig.id_item, g.codigo
            FROM tb_bom_item_grupos_operativos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            JOIN tb_bom_items i ON i.id_item = ig.id_item
            WHERE i.id_bom = $1
              AND i.activo = TRUE
              AND g.activo = TRUE
            ORDER BY g.orden ASC
        """, id_bom)
        result: dict = {}
        for r in rows:
            key = str(r['id_item'])
            result.setdefault(key, [])
            result[key].append(r['codigo'])
        return result

    async def set_item_grupos(self, conn, id_item: UUID, grupo_ids: List[int]) -> None:
        """Reemplaza todos los grupos de un item (delete + insert)."""
        await conn.execute(
            "DELETE FROM tb_bom_item_grupos WHERE id_item = $1", id_item
        )
        if grupo_ids:
            for gid in grupo_ids:
                await conn.execute(
                    "INSERT INTO tb_bom_item_grupos (id_item, id_grupo) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    id_item, gid
                )

    async def set_item_grupos_operativos(
        self, conn, id_item: UUID, grupo_ids: List[int], user_id: Optional[UUID] = None
    ) -> None:
        """Reemplaza todos los grupos operativos de un item."""
        await conn.execute(
            "DELETE FROM tb_bom_item_grupos_operativos WHERE id_item = $1", id_item
        )
        if grupo_ids:
            await conn.executemany("""
                    INSERT INTO tb_bom_item_grupos_operativos
                        (id_item, id_grupo, created_by)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (id_item, id_grupo) DO UPDATE
                    SET created_by = EXCLUDED.created_by
                """,
                [(id_item, gid, user_id) for gid in grupo_ids],
            )

    # ─── SUPLENCIAS ─────────────────────────────────────────

    async def get_suplencia_activa_del_titular(self, conn, titular_id: UUID) -> Optional[dict]:
        """Obtiene suplencia activa vigente de un usuario (como titular)."""
        row = await conn.fetchrow("""
            SELECT s.id, s.titular_id, s.suplente_id, s.fecha_fin, s.activo, s.created_at,
                   u.nombre AS suplente_nombre
            FROM tb_bom_suplencias s
            JOIN tb_usuarios u ON u.id_usuario = s.suplente_id
            WHERE s.titular_id = $1
              AND s.activo = TRUE
              AND s.fecha_fin >= CURRENT_DATE
            ORDER BY s.fecha_fin DESC
            LIMIT 1
        """, titular_id)
        return dict(row) if row else None

    async def get_titulares_que_representa(self, conn, suplente_id: UUID) -> List[UUID]:
        """Retorna los titular_ids que este usuario puede representar hoy."""
        rows = await conn.fetch("""
            SELECT titular_id
            FROM tb_bom_suplencias
            WHERE suplente_id = $1
              AND activo = TRUE
              AND fecha_fin >= CURRENT_DATE
        """, suplente_id)
        return [r['titular_id'] for r in rows]

    async def crear_suplencia(
        self, conn, titular_id: UUID, suplente_id: UUID, fecha_fin
    ) -> dict:
        """Desactiva suplencias previas del titular e inserta la nueva."""
        await conn.execute("""
            UPDATE tb_bom_suplencias SET activo = FALSE
            WHERE titular_id = $1 AND activo = TRUE
        """, titular_id)
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_suplencias (titular_id, suplente_id, fecha_fin)
            VALUES ($1, $2, $3)
            RETURNING *
        """, titular_id, suplente_id, fecha_fin)
        return dict(row)

    async def desactivar_suplencia(self, conn, titular_id: UUID) -> None:
        """Desactiva todas las suplencias activas del usuario como titular."""
        await conn.execute("""
            UPDATE tb_bom_suplencias SET activo = FALSE
            WHERE titular_id = $1 AND activo = TRUE
        """, titular_id)

    # ─── APROBADOR FINAL ────────────────────────────────────

    async def get_aprobador_final_id(self, conn) -> Optional[UUID]:
        """Lee el UUID del aprobador final desde tb_configuracion_global."""
        val = await conn.fetchval("""
            SELECT valor FROM tb_configuracion_global
            WHERE clave = 'bom_aprobador_final_id'
        """)
        if val:
            try:
                from uuid import UUID as _UUID
                return _UUID(val)
            except (ValueError, AttributeError):
                return None
        return None

    async def get_usuario_email(self, conn, user_id: UUID) -> Optional[str]:
        """Retorna el email de un usuario activo, o None si no existe."""
        return await conn.fetchval(
            "SELECT email FROM tb_usuarios WHERE id_usuario = $1 AND is_active = TRUE",
            user_id
        )

    async def get_usuario_activo_basico(self, conn, user_id: UUID) -> Optional[dict]:
        """Retorna id y nombre de un usuario activo."""
        row = await conn.fetchrow(
            "SELECT id_usuario, nombre FROM tb_usuarios WHERE id_usuario = $1 AND is_active = TRUE",
            user_id,
        )
        return dict(row) if row else None

    async def get_usuario_nombre(self, conn, user_id: UUID) -> Optional[str]:
        """Retorna el nombre de un usuario, o None si no existe."""
        return await conn.fetchval(
            "SELECT nombre FROM tb_usuarios WHERE id_usuario = $1",
            user_id,
        )

    async def get_sender_email(self, conn, departamento: str = 'DEFAULT') -> Optional[str]:
        """Retorna email_remitente del buzon de notificaciones configurado."""
        email = await conn.fetchval("""
            SELECT email_remitente FROM tb_correos_notificaciones
            WHERE departamento = $1 AND activo = TRUE LIMIT 1
        """, departamento.upper())
        if not email:
            email = await conn.fetchval("""
                SELECT email_remitente FROM tb_correos_notificaciones
                WHERE departamento = 'DEFAULT' AND activo = TRUE LIMIT 1
            """)
        return email

    async def set_aprobador_final_id(self, conn, user_id: Optional[UUID]) -> None:
        """Actualiza el UUID del aprobador final en tb_configuracion_global."""
        await conn.execute("""
            UPDATE tb_configuracion_global
            SET valor = $1
            WHERE clave = 'bom_aprobador_final_id'
        """, str(user_id) if user_id else "")

    # ─── TIPO DE CAMBIO PARA ITEMS USD ─────────────────────

    async def get_tc_from_linked_materials(
        self, conn, item_ids: List[UUID]
    ) -> dict:
        """Retorna {id_item: tipo_cambio_xml} para items vinculados a materiales con TC del XML."""
        rows = await conn.fetch("""
            SELECT mh.id_bom_item, mh.tipo_cambio_xml
            FROM tb_materiales_historial mh
            WHERE mh.id_bom_item = ANY($1::uuid[])
              AND mh.tipo_cambio_xml IS NOT NULL
            ORDER BY mh.created_at DESC
        """, item_ids)
        result = {}
        for r in rows:
            key = str(r['id_bom_item'])
            if key not in result:
                result[key] = r['tipo_cambio_xml']
        return result

    async def get_tasa_promedio(self, conn, days: int = 7) -> Optional[Decimal]:
        """Promedio de los ultimos N dias de tasa Banxico. Fallback si no hay TC reciente."""
        val = await conn.fetchval("""
            SELECT AVG(tasa_mxn)
            FROM (
                SELECT tasa_mxn FROM tb_tipo_cambio
                ORDER BY fecha DESC
                LIMIT $1
            ) sub
        """, days)
        return val if val else None

    async def get_gasto_real_por_item(self, conn, item_ids: List[UUID]) -> dict:
        """Retorna {id_item: total_gastado} sumando importes del item actual y su item_origen.

        Agrupa por current_id (el ID del item actual) para que el gasto histórico de
        versiones anteriores se sume al item vigente, no se devuelva como clave separada.
        Solo incluye items con al menos una factura vinculada (COUNT > 0): un item sin
        compras registradas no debe distinguirse de uno con $0 de gasto real confirmado.
        """
        rows = await conn.fetch("""
            WITH expanded AS (
                SELECT bi.id_item AS current_id, bi.id_item AS target_id
                FROM tb_bom_items bi WHERE bi.id_item = ANY($1::uuid[])
                UNION ALL
                SELECT bi.id_item AS current_id, bi.id_item_origen AS target_id
                FROM tb_bom_items bi
                WHERE bi.id_item = ANY($1::uuid[]) AND bi.id_item_origen IS NOT NULL
            )
            SELECT e.current_id, SUM(m.importe) AS total_gastado
            FROM expanded e
            JOIN tb_materiales_historial m ON m.id_bom_item = e.target_id
            GROUP BY e.current_id
        """, item_ids)
        return {str(r['current_id']): r['total_gastado'] for r in rows}
