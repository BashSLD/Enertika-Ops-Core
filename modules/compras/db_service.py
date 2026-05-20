
# modules/compras/db_service.py
from uuid import UUID, uuid4
from datetime import date
from typing import List, Tuple, Optional
from decimal import Decimal
from fastapi import HTTPException
import logging
import json

from core.timezone import now_mx

logger = logging.getLogger("Compras.DBService")

_PROVEEDOR_FALLBACK_JOIN = """LEFT JOIN tb_proveedores p ON p.id_proveedor = COALESCE(
                c.id_proveedor,
                (SELECT bp.id_proveedor FROM tb_beneficiario_proveedor bp
                 WHERE bp.beneficiario_nombre = c.beneficiario_orig
                 ORDER BY bp.created_at DESC LIMIT 1)
            )"""

_SAT_CANDIDATOS_SUBQUERY = """
    (SELECT COUNT(*) FROM tb_sat_inbox i
     WHERE i.estado = 'pendiente'
       AND i.total IS NOT NULL
       AND c.moneda = COALESCE(i.moneda, 'MXN')
       AND (
           (
               COALESCE(i.tipo_detectado, 'NORMAL') != 'CIERRE_ANTICIPO'
               AND c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')
               AND (
                   ABS(i.total - c.monto) <= 1.00
                   OR (
                       p.rfc IS NOT NULL
                       AND p.rfc = i.rfc_emisor
                       AND i.total <= (c.monto - COALESCE(c.monto_facturado, 0)) + 0.50
                   )
                   OR (
                       c.beneficiario_orig <> ''
                       AND extensions.word_similarity(
                           LOWER(COALESCE(i.nombre_emisor, '')),
                           LOWER(c.beneficiario_orig)
                       ) > 0.30
                   )
               )
           )
           OR (
               i.tipo_detectado = 'CIERRE_ANTICIPO'
               AND c.estatus = 'ANTICIPO'
               AND i.total <= c.monto + 0.50
           )
       )
    ) as sat_candidatos_count
"""

class ComprasDBService:
    """Capa de Acceso a Datos para el Módulo Compras"""

    async def check_duplicate_comprobante(self, conn, fecha_pago: date, beneficiario: str, monto: Decimal) -> bool:
        """Verifica si existe un comprobante con los mismos datos clave."""
        exists = await conn.fetchval("""
            SELECT 1 FROM tb_comprobantes_pago 
            WHERE fecha_pago = $1 
            AND beneficiario_orig = $2 
            AND monto = $3
        """, fecha_pago, beneficiario, monto)
        return bool(exists)

    async def insert_comprobante(self, conn, comprobante_data: dict) -> UUID:
        """Inserta un nuevo comprobante."""
        new_id = uuid4()
        id_proveedor = comprobante_data.get('id_proveedor')
        await conn.execute("""
            INSERT INTO tb_comprobantes_pago (
                id_comprobante, 
                fecha_pago, 
                beneficiario_orig,
                monto, 
                moneda, 
                estatus, 
                capturado_por_id,
                id_proveedor,
                created_at,
                updated_at
            ) VALUES ($1, $2, $3, $4, $5, 'PENDIENTE', $6, $7, NOW(), NOW())
        """, 
            new_id, 
            comprobante_data['fecha_pago'], 
            comprobante_data['beneficiario'],
            comprobante_data['monto'], 
            comprobante_data['moneda'], 
            comprobante_data['user_id'],
            id_proveedor
        )
        return new_id

    async def get_comprobantes_filtered(
        self,
        conn,
        filtros: dict,
        page: int = 1,
        per_page: int = 50,
        count_only: bool = False
    ):
        """Builds dynamic query for filtering comprobantes."""
        base_query = f"""
            SELECT
                c.id_comprobante,
                c.fecha_pago,
                c.beneficiario_orig,
                c.monto,
                c.moneda,
                c.estatus,
                c.uuid_factura,
                c.monto_facturado,
                c.monto_remanente,
                c.motivo_cierre,
                c.created_at,
                c.id_proveedor,
                c.id_zona,
                c.id_proyecto,
                c.id_categoria,
                c.tipo_factura,
                c.es_anticipo,
                u.nombre as comprador_nombre,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                z.nombre as zona_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                cat.nombre as categoria_nombre,
                (SELECT COUNT(*)
                 FROM tb_documentos_attachments da
                 WHERE da.activo = true
                 AND da.metadata->>'id_comprobante' = c.id_comprobante::text
                 AND da.origen_slug = 'comprobante_pago'
                ) as count_pdf,
                (SELECT COUNT(*)
                 FROM tb_comprobante_facturas cf
                 WHERE cf.id_comprobante = c.id_comprobante
                ) as count_xml,
                {_SAT_CANDIDATOS_SUBQUERY}
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            {_PROVEEDOR_FALLBACK_JOIN}
            LEFT JOIN tb_cat_zonas_compra z ON c.id_zona = z.id
            LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
            LEFT JOIN tb_cat_categorias_compra cat ON c.id_categoria = cat.id
            WHERE 1=1
        """
        
        if count_only:
            base_query = "SELECT COUNT(*) FROM tb_comprobantes_pago c WHERE 1=1"

        params = []
        param_idx = 1
        
        # Apply filters
        if filtros.get('fecha_inicio'):
            base_query += f" AND c.fecha_pago >= ${param_idx}"
            params.append(filtros['fecha_inicio'])
            param_idx += 1
        
        if filtros.get('fecha_fin'):
            base_query += f" AND c.fecha_pago <= ${param_idx}"
            params.append(filtros['fecha_fin'])
            param_idx += 1
        
        if filtros.get('estatus'):
            if filtros['estatus'] == 'SIN_COMPLETAR':
                base_query += " AND (c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO') OR (c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50))"
            elif filtros['estatus'] == 'ANTICIPO':
                base_query += " AND c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50"
            else:
                base_query += f" AND c.estatus = ${param_idx}"
                params.append(filtros['estatus'])
                param_idx += 1

        if filtros.get('id_zona'):
            base_query += f" AND c.id_zona = ${param_idx}"
            params.append(filtros['id_zona'])
            param_idx += 1
        
        if filtros.get('id_proyecto'):
            base_query += f" AND c.id_proyecto = ${param_idx}"
            params.append(filtros['id_proyecto'])
            param_idx += 1
        
        if filtros.get('id_categoria'):
            base_query += f" AND c.id_categoria = ${param_idx}"
            params.append(filtros['id_categoria'])
            param_idx += 1

        if filtros.get('id_usuario'):
            base_query += f" AND c.capturado_por_id = ${param_idx}"
            params.append(filtros['id_usuario'])
            param_idx += 1

        if count_only:
            return await conn.fetchval(base_query, *params)
            
        # Add sorting and pagination
        base_query += " ORDER BY c.fecha_pago DESC, c.created_at DESC"
        
        # Handle "all" for export
        if per_page > 0:
            base_query += f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
            params.extend([per_page, (page - 1) * per_page])
        
        return await conn.fetch(base_query, *params)

    async def get_comprobante_by_id(self, conn, id_comprobante: UUID) -> Optional[dict]:
        row = await conn.fetchrow(f"""
            SELECT
                c.*,
                u.nombre as comprador_nombre,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                z.nombre as zona_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                cat.nombre as categoria_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            {_PROVEEDOR_FALLBACK_JOIN}
            LEFT JOIN tb_cat_zonas_compra z ON c.id_zona = z.id
            LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
            LEFT JOIN tb_cat_categorias_compra cat ON c.id_categoria = cat.id
            WHERE c.id_comprobante = $1
        """, id_comprobante)
        return dict(row) if row else None

    async def get_comprobante_fila(self, conn, id_comprobante: UUID) -> Optional[dict]:
        row = await conn.fetchrow(f"""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig, c.monto, c.moneda,
                c.estatus, c.uuid_factura, c.monto_facturado, c.monto_remanente,
                c.tipo_factura, c.es_anticipo, c.id_proveedor, c.id_zona,
                c.id_proyecto, c.id_categoria,
                u.nombre as comprador_nombre,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                z.nombre as zona_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                cat.nombre as categoria_nombre,
                (SELECT COUNT(*) FROM tb_documentos_attachments da
                 WHERE da.activo = true
                   AND da.metadata->>'id_comprobante' = c.id_comprobante::text
                   AND da.origen_slug = 'comprobante_pago') as count_pdf,
                (SELECT COUNT(*) FROM tb_comprobante_facturas cf
                 WHERE cf.id_comprobante = c.id_comprobante) as count_xml,
                {_SAT_CANDIDATOS_SUBQUERY}
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            {_PROVEEDOR_FALLBACK_JOIN}
            LEFT JOIN tb_cat_zonas_compra z ON c.id_zona = z.id
            LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
            LEFT JOIN tb_cat_categorias_compra cat ON c.id_categoria = cat.id
            WHERE c.id_comprobante = $1
        """, id_comprobante)
        return dict(row) if row else None

    async def update_comprobante(self, conn, id_comprobante: UUID, updates: dict) -> bool:
        allowed_fields = ['id_zona', 'id_proyecto', 'id_categoria', 'id_proveedor']
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
            
        set_clauses.append(f"updated_at = ${param_idx}")
        params.append(now_mx())
        param_idx += 1
        
        params.append(id_comprobante)
        
        query = f"""
            UPDATE tb_comprobantes_pago 
            SET {', '.join(set_clauses)}
            WHERE id_comprobante = ${param_idx}
        """
        result = await conn.execute(query, *params)
        return result == "UPDATE 1"

    async def bulk_update(self, conn, ids: List[UUID], updates: dict) -> int:
        allowed_fields = ['id_zona', 'id_proyecto', 'id_categoria', 'estatus']
        set_clauses = []
        params = []
        param_idx = 1
        
        for field in allowed_fields:
            if field in updates and updates[field] is not None:
                set_clauses.append(f"{field} = ${param_idx}")
                params.append(updates[field])
                param_idx += 1
                
        if not set_clauses:
            return 0
            
        set_clauses.append(f"updated_at = ${param_idx}")
        params.append(now_mx())
        param_idx += 1
        
        params.append(ids)
        
        query = f"""
            UPDATE tb_comprobantes_pago 
            SET {', '.join(set_clauses)}
            WHERE id_comprobante = ANY(${param_idx}::uuid[])
        """
        result = await conn.execute(query, *params)
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    async def get_catalogos_data(self, conn) -> dict:
        zonas = await conn.fetch("SELECT id, nombre FROM tb_cat_zonas_compra WHERE activo = true ORDER BY orden, nombre")
        categorias = await conn.fetch("SELECT id, nombre FROM tb_cat_categorias_compra WHERE activo = true ORDER BY orden, nombre")
        proyectos = await conn.fetch("SELECT id_proyecto, proyecto_id_estandar as nombre FROM tb_proyectos_gate WHERE aprobacion_direccion = true ORDER BY proyecto_id_estandar")
        compradores = await conn.fetch("SELECT id_usuario, nombre FROM tb_usuarios WHERE is_active = true ORDER BY nombre")
        
        return {
            "zonas": [dict(r) for r in zonas],
            "categorias": [dict(r) for r in categorias],
            "proyectos": [dict(r) for r in proyectos],
            "compradores": [dict(r) for r in compradores]
        }

    async def get_estadisticas(self, conn, filtros: dict) -> dict:
        base_query = """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE estatus = 'PENDIENTE') as pendientes,
                COUNT(*) FILTER (WHERE estatus = 'FACTURADO') as facturados,
                COUNT(*) FILTER (WHERE estatus = 'ANTICIPO') as anticipos,
                COUNT(*) FILTER (WHERE estatus = 'PARCIALMENTE_FACTURADO') as parciales,
                COUNT(*) FILTER (WHERE estatus = 'CERRADO') as cerrados,
                COALESCE(SUM(monto) FILTER (WHERE moneda = 'MXN'), 0) as total_mxn,
                COALESCE(SUM(monto) FILTER (WHERE moneda = 'USD'), 0) as total_usd
            FROM tb_comprobantes_pago
            WHERE 1=1
        """
        params = []
        param_idx = 1
        
        # Reusar logica de filtros simplificada
        if filtros.get('fecha_inicio'):
            base_query += f" AND fecha_pago >= ${param_idx}"
            params.append(filtros['fecha_inicio'])
            param_idx += 1
        if filtros.get('fecha_fin'):
            base_query += f" AND fecha_pago <= ${param_idx}"
            params.append(filtros['fecha_fin'])
            param_idx += 1
        if filtros.get('estatus'):
            if filtros['estatus'] == 'SIN_COMPLETAR':
                base_query += " AND (estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO') OR (estatus = 'ANTICIPO' AND COALESCE(monto_facturado, 0) < monto - 0.50))"
            elif filtros['estatus'] == 'ANTICIPO':
                base_query += " AND estatus = 'ANTICIPO' AND COALESCE(monto_facturado, 0) < monto - 0.50"
            else:
                base_query += f" AND estatus = ${param_idx}"
                params.append(filtros['estatus'])
                param_idx += 1
        if filtros.get('id_zona'):
            base_query += f" AND id_zona = ${param_idx}"
            params.append(filtros['id_zona'])
            param_idx += 1
        if filtros.get('id_proyecto'):
            base_query += f" AND id_proyecto = ${param_idx}"
            params.append(filtros['id_proyecto'])
            param_idx += 1
        if filtros.get('id_categoria'):
            base_query += f" AND id_categoria = ${param_idx}"
            params.append(filtros['id_categoria'])
            param_idx += 1

        if filtros.get('id_usuario'):
            base_query += f" AND capturado_por_id = ${param_idx}"
            params.append(filtros['id_usuario'])
            param_idx += 1

        row = await conn.fetchrow(base_query, *params)
        return dict(row)

    async def search_proveedores(self, conn, term: str, limit: int = 10) -> List[dict]:
        rows = await conn.fetch("""
             SELECT id_proveedor, rfc, razon_social, nombre_comercial
            FROM tb_proveedores
            WHERE activo = true
            AND (
                razon_social ILIKE $1
                OR nombre_comercial ILIKE $1
                OR rfc ILIKE $1
            )
            ORDER BY razon_social
            LIMIT $2
        """, f"%{term}%", limit)
        return [dict(r) for r in rows]

    # ========================================
    # XML / PROVEEDORES / MATCHING
    # ========================================

    async def get_proveedor_by_rfc(self, conn, rfc: str) -> Optional[dict]:
        """Busca un proveedor por RFC."""
        row = await conn.fetchrow(
            "SELECT * FROM tb_proveedores WHERE rfc = $1 AND activo = true",
            rfc
        )
        return dict(row) if row else None

    async def create_proveedor(self, conn, rfc: str, razon_social: str) -> dict:
        """Crea un proveedor nuevo. Retorna el registro creado."""
        new_id = uuid4()
        await conn.execute("""
            INSERT INTO tb_proveedores (id_proveedor, rfc, razon_social, activo, created_at)
            VALUES ($1, $2, $3, true, NOW())
        """, new_id, rfc, razon_social)
        row = await conn.fetchrow(
            "SELECT * FROM tb_proveedores WHERE id_proveedor = $1", new_id
        )
        return dict(row)

    async def get_relaciones_beneficiario(self, conn, id_proveedor: UUID) -> List[dict]:
        """Obtiene los nombres de beneficiario asociados a un proveedor."""
        rows = await conn.fetch("""
            SELECT beneficiario_nombre
            FROM tb_beneficiario_proveedor
            WHERE id_proveedor = $1
        """, id_proveedor)
        return [dict(r) for r in rows]

    async def get_proveedor_by_beneficiario(self, conn, beneficiario: str) -> Optional[dict]:
        """Busca proveedor por nombre exacto de beneficiario (relacion conocida)."""
        row = await conn.fetchrow("""
            SELECT p.id_proveedor, p.rfc, p.razon_social, p.nombre_comercial
            FROM tb_beneficiario_proveedor bp
            JOIN tb_proveedores p ON bp.id_proveedor = p.id_proveedor
            WHERE bp.beneficiario_nombre = $1
            AND p.activo = true
        """, beneficiario)
        return dict(row) if row else None

    async def buscar_comprobantes_match(
        self, conn, beneficiario: str, monto: Decimal,
        moneda: str, tolerancia: Decimal = Decimal("0.50")
    ) -> List[dict]:
        """Busca comprobantes pendientes/anticipo/parcial por beneficiario + monto con tolerancia."""
        rows = await conn.fetch("""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.monto_facturado, c.created_at,
                u.nombre as comprador_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            WHERE (c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO') OR (c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50))
            AND c.beneficiario_orig = $1
            AND c.moneda = $2
            AND ABS(c.monto - $3) <= $4
            ORDER BY c.fecha_pago DESC
        """, beneficiario, moneda, monto, tolerancia)
        return [dict(r) for r in rows]

    async def buscar_comprobantes_por_nombres_proveedor(
        self, conn, nombres: List[str], monto: Decimal,
        moneda: str, tolerancia: Decimal = Decimal("0.50")
    ) -> List[dict]:
        """Busca comprobantes pendientes/anticipo/parcial donde beneficiario coincide con
        razon_social o nombre_comercial del proveedor + monto."""
        if not nombres:
            return []
        rows = await conn.fetch("""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.monto_facturado, c.created_at,
                u.nombre as comprador_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            WHERE (c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO') OR (c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50))
            AND c.beneficiario_orig = ANY($1)
            AND c.moneda = $2
            AND ABS(c.monto - $3) <= $4
            ORDER BY c.fecha_pago DESC
        """, nombres, moneda, monto, tolerancia)
        return [dict(r) for r in rows]

    async def buscar_comprobantes_por_monto(
        self, conn, monto: Decimal, moneda: str,
        tolerancia: Decimal = Decimal("0.50")
    ) -> List[dict]:
        """Busca comprobantes pendientes/anticipo/parcial solo por monto + moneda."""
        rows = await conn.fetch("""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.monto_facturado, c.created_at,
                u.nombre as comprador_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            WHERE (c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO') OR (c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50))
            AND c.moneda = $1
            AND ABS(c.monto - $2) <= $3
            ORDER BY c.fecha_pago DESC
        """, moneda, monto, tolerancia)
        return [dict(r) for r in rows]

    async def buscar_comprobantes_parciales_por_proveedor(
        self, conn, id_proveedor: UUID, moneda: str,
        monto_xml: Decimal, tolerancia: Decimal = Decimal("0.50")
    ) -> List[dict]:
        """Busca comprobantes PENDIENTE o PARCIALMENTE_FACTURADO del mismo proveedor
        donde el saldo restante (monto - monto_facturado) puede absorber el XML.

        Ordena por cercanía entre saldo y monto del XML.
        """
        rows = await conn.fetch("""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.monto_facturado,
                (c.monto - c.monto_facturado) AS saldo_pendiente,
                u.nombre AS comprador_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            WHERE c.id_proveedor = $1
            AND c.moneda = $2
            AND c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')
            AND (c.monto - c.monto_facturado) >= $3::NUMERIC - $4::NUMERIC
            ORDER BY ABS((c.monto - c.monto_facturado) - $3::NUMERIC) ASC
            LIMIT 5
        """, id_proveedor, moneda, monto_xml, tolerancia)
        return [dict(r) for r in rows]

    async def buscar_comprobantes_pendientes(
        self, conn, q: Optional[str] = None, limit: int = 20
    ) -> List[dict]:
        """Busqueda libre de comprobantes pendientes/anticipo/parcial (para match manual)."""
        query = """
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.monto_facturado, c.created_at
            FROM tb_comprobantes_pago c
            WHERE (c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO') OR (c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50))
        """
        params = []
        if q:
            query += """ AND (
                c.beneficiario_orig ILIKE $1
                OR CAST(c.monto AS TEXT) LIKE $1
            )"""
            params.append(f"%{q}%")
        query += " ORDER BY c.fecha_pago DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def uuid_factura_exists(self, conn, uuid_factura: str) -> bool:
        """Verifica si un UUID de factura ya esta registrado."""
        exists = await conn.fetchval(
            "SELECT 1 FROM tb_comprobantes_pago WHERE uuid_factura = $1",
            uuid_factura
        )
        return bool(exists)

    async def uuid_factura_exists_for_comprobante(
        self, conn, id_comprobante: UUID, uuid_factura: str
    ) -> bool:
        """Verifica si el UUID ya esta vinculado al comprobante indicado."""
        exists = await conn.fetchval("""
            SELECT 1
            FROM tb_comprobante_facturas
            WHERE id_comprobante = $1 AND uuid_factura = $2
        """, id_comprobante, uuid_factura)
        if exists:
            return True

        exists_legacy = await conn.fetchval("""
            SELECT 1
            FROM tb_comprobantes_pago
            WHERE id_comprobante = $1 AND uuid_factura = $2::uuid
        """, id_comprobante, uuid_factura)
        return bool(exists_legacy)

    async def get_factura_aplicacion_resumen(self, conn, uuid_factura: str) -> dict:
        """Monto total y aplicado de una factura en todos los comprobantes."""
        row = await conn.fetchrow("""
            SELECT
                COALESCE(MAX(monto), 0) AS monto_factura,
                COALESCE(SUM(COALESCE(monto_aplicado, monto, 0)), 0) AS monto_aplicado
            FROM tb_comprobante_facturas
            WHERE uuid_factura = $1
        """, uuid_factura)
        return dict(row) if row else {"monto_factura": Decimal("0"), "monto_aplicado": Decimal("0")}

    async def confirmar_match(
        self, conn, id_comprobante: UUID, uuid_factura: str,
        id_proveedor: UUID, tipo_factura: str = "NORMAL",
        current_estatus: Optional[str] = None,
        monto_factura: Decimal = Decimal("0"),
        id_comprobante_anticipo: Optional[UUID] = None,
        monto_comprobante: Optional[Decimal] = None,
        monto_acumulado: Optional[Decimal] = None,
        monto_aplicado: Optional[Decimal] = None,
    ):
        """Actualiza comprobante con datos de la factura XML.

        Logica de estatus con soporte de parciales:
        - NOTA_CREDITO: no cambia estatus del comprobante
        - ANTICIPO: estatus → ANTICIPO
        - NORMAL/CIERRE_ANTICIPO:
            monto_facturado_nuevo >= monto_pago - $0.50 → FACTURADO
            monto_facturado_nuevo < monto_pago - $0.50  → PARCIALMENTE_FACTURADO

        El campo uuid_factura se setea solo si era NULL (primera factura vinculada).
        El campo id_proveedor se setea solo si era NULL.
        """
        tolerancia = Decimal("0.50")
        es_anticipo = tipo_factura == "ANTICIPO"
        monto_movimiento = Decimal(str(monto_aplicado if monto_aplicado is not None else monto_factura))

        if tipo_factura == "NOTA_CREDITO":
            nuevo_estatus = current_estatus or "FACTURADO"
            await conn.execute("""
                UPDATE tb_comprobantes_pago
                SET uuid_factura = COALESCE(uuid_factura, $1),
                    id_proveedor = COALESCE(id_proveedor, $2),
                    estatus = $3,
                    es_anticipo = $4,
                    tipo_factura = $5,
                    updated_at = NOW()
                WHERE id_comprobante = $6
            """, uuid_factura, id_proveedor, nuevo_estatus, es_anticipo,
                tipo_factura, id_comprobante)
            return

        if tipo_factura == "ANTICIPO":
            await conn.execute("""
                UPDATE tb_comprobantes_pago
                SET uuid_factura = COALESCE(uuid_factura, $1),
                    id_proveedor = COALESCE(id_proveedor, $2),
                    estatus = 'ANTICIPO',
                    es_anticipo = TRUE,
                    tipo_factura = $3,
                    monto_facturado = monto_facturado + $4,
                    updated_at = NOW()
                WHERE id_comprobante = $5
            """, uuid_factura, id_proveedor, tipo_factura, monto_movimiento, id_comprobante)
            return

        if tipo_factura == "CIERRE_ANTICIPO":
            if monto_comprobante is not None and monto_acumulado is not None:
                monto_total = monto_comprobante
                monto_nuevo = monto_acumulado + monto_movimiento
            else:
                row = await conn.fetchrow("""
                    SELECT monto, COALESCE(monto_facturado, 0) AS monto_facturado
                    FROM tb_comprobantes_pago
                    WHERE id_comprobante = $1
                """, id_comprobante)
                row_data = dict(row) if row else {}
                monto_total = row_data.get('monto', Decimal("0"))
                monto_nuevo = Decimal(str(row_data.get('monto_facturado') or 0))
                monto_nuevo += monto_movimiento
            nuevo_estatus = (
                "FACTURADO"
                if monto_nuevo >= monto_total - tolerancia
                else "PARCIALMENTE_FACTURADO"
            )

            await conn.execute("""
                UPDATE tb_comprobantes_pago
                SET uuid_factura = COALESCE(uuid_factura, $1),
                    id_proveedor = COALESCE(id_proveedor, $2),
                    estatus = $5,
                    es_anticipo = FALSE,
                    tipo_factura = $3,
                    monto_facturado = $6,
                    id_comprobante_anticipo = COALESCE($4, id_comprobante_anticipo),
                    updated_at = NOW()
                WHERE id_comprobante = $7
            """, uuid_factura, id_proveedor, tipo_factura, id_comprobante_anticipo,
                nuevo_estatus, monto_nuevo, id_comprobante)
            return

        # NORMAL: calcular si cubre el pago completo
        row = await conn.fetchrow("""
            SELECT monto, monto_facturado
            FROM tb_comprobantes_pago
            WHERE id_comprobante = $1
        """, id_comprobante)
        monto_actual = Decimal(str(row['monto_facturado'] or 0))
        nuevo_monto_facturado = monto_actual + monto_movimiento
        if nuevo_monto_facturado >= row['monto'] - tolerancia:
            nuevo_estatus = "FACTURADO"
        else:
            nuevo_estatus = "PARCIALMENTE_FACTURADO"

        await conn.execute("""
            UPDATE tb_comprobantes_pago
            SET uuid_factura = COALESCE(uuid_factura, $1),
                id_proveedor = COALESCE(id_proveedor, $2),
                estatus = $3,
                es_anticipo = $4,
                tipo_factura = $5,
                monto_facturado = $6,
                updated_at = NOW()
            WHERE id_comprobante = $7
        """, uuid_factura, id_proveedor, nuevo_estatus, es_anticipo,
            tipo_factura, nuevo_monto_facturado, id_comprobante)

    async def vincular_cierre_anticipo(
        self, conn, id_comprobante: UUID, uuid_anticipo_relacionado: str
    ):
        """Para CIERRE_ANTICIPO: busca el comprobante del anticipo original y vincula."""
        anticipo_row = await conn.fetchrow("""
            SELECT id_comprobante FROM tb_comprobantes_pago
            WHERE uuid_factura = $1 AND es_anticipo = true
        """, uuid_anticipo_relacionado)

        if anticipo_row:
            await conn.execute("""
                UPDATE tb_comprobantes_pago
                SET id_comprobante_anticipo = $1
                WHERE id_comprobante = $2
            """, anticipo_row['id_comprobante'], id_comprobante)

    async def get_comprobante_anticipo_by_uuid(
        self, conn, uuid_anticipo: str
    ) -> Optional[dict]:
        """Busca el comprobante de anticipo original por UUID de factura."""
        uuid_anticipo_uuid = UUID(str(uuid_anticipo))
        uuid_anticipo_text = str(uuid_anticipo).upper()

        row = await conn.fetchrow("""
            SELECT c.id_comprobante, c.id_proveedor
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_comprobante_facturas cf
                ON cf.id_comprobante = c.id_comprobante
            WHERE c.es_anticipo = true
              AND (
                  c.uuid_factura = $1::uuid
                  OR UPPER(cf.uuid_factura) = $2::text
              )
            ORDER BY CASE WHEN c.uuid_factura = $1::uuid THEN 0 ELSE 1 END
            LIMIT 1
        """, uuid_anticipo_uuid, uuid_anticipo_text)
        return dict(row) if row else None

    async def guardar_relacion_beneficiario(
        self, conn, beneficiario: str, id_proveedor: UUID, user_id: UUID
    ):
        """Guarda o actualiza la relacion beneficiario - proveedor.

        Primera vez: confianza='MANUAL'.
        Si ya existe (match repetido): escala a 'AUTO_CONFIRMADO'.
        """
        await conn.execute("""
            INSERT INTO tb_beneficiario_proveedor
                (beneficiario_nombre, id_proveedor, confianza, created_by_id)
            VALUES ($1, $2, 'MANUAL', $3)
            ON CONFLICT (beneficiario_nombre, id_proveedor) DO UPDATE SET
                confianza = 'AUTO_CONFIRMADO'
        """, beneficiario, id_proveedor, user_id)

    async def get_categorias_by_claves_sat(self, conn, claves: List[str]) -> dict:
        """Batch lookup de categorias para multiples claves SAT.

        Busca items previamente categorizados con las mismas claves.
        Retorna dict {clave_prod_serv: id_categoria}.
        """
        if not claves:
            return {}
        rows = await conn.fetch("""
            SELECT DISTINCT ON (clave_prod_serv)
                clave_prod_serv, id_categoria
            FROM tb_materiales_historial
            WHERE clave_prod_serv = ANY($1)
            AND id_categoria IS NOT NULL
        """, claves)
        return {r['clave_prod_serv']: r['id_categoria'] for r in rows}

    async def guardar_conceptos_historial(
        self, conn, uuid_factura: str, id_comprobante: Optional[UUID],
        id_proveedor: UUID, conceptos: List[dict],
        fecha_factura: date, user_id: UUID,
        tipo_cambio_xml: Optional[Decimal] = None,
        bom_item_map: dict = None
    ):
        """Guarda los conceptos/items del XML en tb_materiales_historial.

        Auto-categoriza por clave SAT: si existen items previamente
        categorizados con la misma clave_prod_serv, asigna la misma categoria.
        tipo_cambio_xml: TC SAT-certificado de la factura (None si moneda=MXN).
        bom_item_map: dict opcional {indice_concepto: UUID(id_bom_item)} para trazabilidad.
        """
        bom_item_map = bom_item_map or {}

        # Batch: obtener categorias conocidas por clave SAT
        claves_sat = list(set(
            c.get('clave_prod_serv') for c in conceptos if c.get('clave_prod_serv')
        ))
        cat_map = await self.get_categorias_by_claves_sat(conn, claves_sat) if claves_sat else {}

        auto_cat_count = 0
        rows = []
        for idx, c in enumerate(conceptos):
            clave_sat = c.get('clave_prod_serv')
            id_categoria = cat_map.get(clave_sat) if clave_sat else None
            if id_categoria:
                auto_cat_count += 1
            id_bom_item = bom_item_map.get(idx)
            rows.append((
                uuid_factura, id_comprobante, id_proveedor,
                c['descripcion'], c['cantidad'], c['valor_unitario'],
                c['importe'], c.get('unidad'), clave_sat,
                c.get('clave_unidad'), id_categoria, 'XML', fecha_factura,
                tipo_cambio_xml, user_id, id_bom_item
            ))

        if rows:
            await conn.executemany("""
                INSERT INTO tb_materiales_historial (
                    uuid_factura, id_comprobante, id_proveedor,
                    descripcion_proveedor, cantidad, precio_unitario,
                    importe, unidad, clave_prod_serv, clave_unidad,
                    id_categoria, origen, fecha_factura,
                    tipo_cambio_xml, created_by_id, id_bom_item
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                ON CONFLICT (uuid_factura, descripcion_proveedor, cantidad, precio_unitario)
                DO NOTHING
            """, rows)

        if auto_cat_count:
            logger.info(
                "Auto-categorizado %d/%d conceptos por clave SAT (UUID=%s)",
                auto_cat_count, len(conceptos), uuid_factura[:8]
            )

    async def guardar_cfdi_relacionados(
        self, conn, uuid_factura: str, relacionados: List[dict]
    ):
        """Guarda los CFDI relacionados del XML."""
        if not relacionados:
            return
        rows = [
            (uuid_factura, rel['uuid'], rel['tipo_relacion'], rel.get('tipo_relacion_desc'))
            for rel in relacionados
        ]
        await conn.executemany("""
            INSERT INTO tb_cfdi_relacionados
                (uuid_factura, uuid_relacionado, tipo_relacion, tipo_relacion_desc)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (uuid_factura, uuid_relacionado, tipo_relacion)
            DO NOTHING
        """, rows)

    async def registrar_archivo_sharepoint(
        self, conn, id_comprobante: Optional[UUID], origen_slug: str,
        upload_result: dict, user_id: UUID, metadata_extra: dict
    ):
        """Registra un archivo subido a SharePoint en tb_documentos_attachments."""
        import json
        doc_id = uuid4()
        parent_ref = upload_result.get('parentReference', {})

        await conn.execute("""
            INSERT INTO tb_documentos_attachments (
                id_documento, nombre_archivo, url_sharepoint,
                drive_item_id, parent_drive_id,
                tipo_contenido, tamano_bytes,
                subido_por_id, origen_slug, activo, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, TRUE, $10::jsonb)
        """,
            doc_id,
            upload_result.get('name', ''),
            upload_result.get('webUrl', ''),
            upload_result.get('id', ''),
            parent_ref.get('driveId'),
            metadata_extra.get('content_type', 'application/xml'),
            upload_result.get('size', 0),
            user_id,
            origen_slug,
            json.dumps(metadata_extra)
        )
        return doc_id

    async def get_config_valor(self, conn, clave: str) -> str:
        """
        Obtiene un valor de configuración de tb_configuracion_global.
        Retorna el valor limpio o cadena vacía si no existe.
        """
        row = await conn.fetchrow("""
            SELECT valor FROM tb_configuracion_global
            WHERE clave = $1
        """, clave)
        return row['valor'].strip().strip("/") if row and row['valor'] else ""

    async def check_ownership_bulk(self, conn, ids: List[UUID], user_id: UUID) -> int:
        """
        Cuenta cuántos comprobantes de la lista NO pertenecen al usuario.
        Usado para validación de permisos en bulk updates.
        """
        count = await conn.fetchval("""
            SELECT COUNT(*) 
            FROM tb_comprobantes_pago
            WHERE id_comprobante = ANY($1)
            AND capturado_por_id != $2
        """, ids, user_id)
        return count or 0

    async def get_email_sender_config(self, conn, departamento: str = 'LEVANTAMIENTOS') -> str:
        """
        Obtiene la configuración de email para notificaciones.
        Primero intenta con el departamento específico, luego con DEFAULT.
        Retorna el email del remitente o un default.
        """
        sender_config = await conn.fetchrow("""
            SELECT email_remitente FROM tb_correos_notificaciones
            WHERE departamento = $1 AND activo = true
            LIMIT 1
        """, departamento)
        
        if not sender_config:
            sender_config = await conn.fetchrow("""
                SELECT email_remitente FROM tb_correos_notificaciones
                WHERE departamento = 'DEFAULT' AND activo = true
                LIMIT 1
            """)
        
        return sender_config['email_remitente'] if sender_config else 'app-notifications@enertika.mx'

    async def insert_documento_attachment(
        self, conn, doc_data: dict
    ) -> UUID:
        """
        Inserta un registro en tb_documentos_attachments.
        
        Args:
            doc_data: dict con campos:
                - nombre_archivo
                - url_sharepoint
                - drive_item_id
                - parent_drive_id
                - tipo_contenido
                - tamano_bytes
                - id_oportunidad (optional)
                - subido_por_id
                - origen_slug
                - metadata (dict)
        
        Returns:
            UUID del documento creado
        """
        import json
        doc_id = uuid4()
        
        await conn.execute("""
            INSERT INTO tb_documentos_attachments (
                id_documento, nombre_archivo, url_sharepoint, drive_item_id, parent_drive_id,
                tipo_contenido, tamano_bytes, id_oportunidad, subido_por_id,
                origen_slug, activo, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, TRUE, $11::jsonb)
        """,
            doc_id,
            doc_data.get('nombre_archivo', ''),
            doc_data.get('url_sharepoint', ''),
            doc_data.get('drive_item_id', ''),
            doc_data.get('parent_drive_id'),
            doc_data.get('tipo_contenido', 'application/octet-stream'),
            doc_data.get('tamano_bytes', 0),
            doc_data.get('id_oportunidad'),
            doc_data['subido_por_id'],
            doc_data.get('origen_slug', 'comprobante_pago'),
            json.dumps(doc_data.get('metadata', {}))
        )
        return doc_id

    async def get_archivos_comprobante(self, conn, id_comprobante: UUID) -> List[dict]:
        """Obtiene archivos asociados a un comprobante (PDF y/o XML)."""
        rows = await conn.fetch("""
            SELECT
                id_documento, nombre_archivo, url_sharepoint,
                origen_slug, tamano_bytes, fecha_subida, metadata
            FROM tb_documentos_attachments
            WHERE activo = true
            AND (
                metadata->>'id_comprobante' = $1
            )
            ORDER BY fecha_subida DESC
        """, str(id_comprobante))
        
        # Parsear metadata JSON si es string (fix asyncpg default)
        results = []
        for r in rows:
            d = dict(r)
            if d.get('metadata') and isinstance(d['metadata'], str):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except (json.JSONDecodeError, TypeError):
                    d['metadata'] = {}
            results.append(d)
        
        return results


    # ========================================
    # JUNCTION TABLE: COMPROBANTE ↔ FACTURAS
    # ========================================

    async def insertar_comprobante_factura(
        self, conn, id_comprobante: UUID, uuid_factura: str,
        tipo: str, monto: Optional[Decimal] = None,
        monto_aplicado: Optional[Decimal] = None,
        moneda: str = "MXN", fecha: Optional[date] = None,
        id_proveedor: Optional[UUID] = None,
        rfc_emisor: Optional[str] = None,
        nombre_emisor: Optional[str] = None
    ):
        """Inserta registro en junction table. ON CONFLICT DO NOTHING."""
        await conn.execute("""
            INSERT INTO tb_comprobante_facturas
                (id_comprobante, uuid_factura, tipo, monto, monto_aplicado, moneda,
                 fecha, id_proveedor, rfc_emisor, nombre_emisor)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (id_comprobante, uuid_factura) DO NOTHING
        """, id_comprobante, uuid_factura, tipo, monto, monto_aplicado, moneda,
            fecha, id_proveedor, rfc_emisor, nombre_emisor)

    async def get_facturas_comprobante(
        self, conn, id_comprobante: UUID
    ) -> List[dict]:
        """Todas las facturas asociadas a un comprobante."""
        rows = await conn.fetch("""
            WITH facturas AS (
                SELECT
                    id_comprobante, uuid_factura, tipo, monto,
                    COALESCE(monto_aplicado, monto, 0) AS monto_aplicado,
                    GREATEST(
                        COALESCE(MAX(monto) OVER (PARTITION BY uuid_factura), 0)
                        - COALESCE(SUM(COALESCE(monto_aplicado, monto, 0)) OVER (PARTITION BY uuid_factura), 0),
                        0
                    ) AS saldo_factura,
                    moneda, fecha, rfc_emisor, nombre_emisor, created_at
                FROM tb_comprobante_facturas
            )
            SELECT
                uuid_factura, tipo, monto,
                monto_aplicado, saldo_factura,
                moneda, fecha, rfc_emisor, nombre_emisor, created_at
            FROM facturas
            WHERE id_comprobante = $1
            ORDER BY created_at
        """, id_comprobante)
        return [dict(r) for r in rows]

    async def get_facturas_for_comprobantes(
        self, conn, ids: List[UUID]
    ) -> dict:
        """Batch fetch de facturas para N comprobantes. Evita N+1 en Excel.

        Returns:
            dict {id_comprobante: [lista de facturas]}
        """
        if not ids:
            return {}
        rows = await conn.fetch("""
            WITH facturas AS (
                SELECT
                    id_comprobante, uuid_factura, tipo, monto,
                    COALESCE(monto_aplicado, monto, 0) AS monto_aplicado,
                    GREATEST(
                        COALESCE(MAX(monto) OVER (PARTITION BY uuid_factura), 0)
                        - COALESCE(SUM(COALESCE(monto_aplicado, monto, 0)) OVER (PARTITION BY uuid_factura), 0),
                        0
                    ) AS saldo_factura,
                    moneda, fecha, rfc_emisor, nombre_emisor, created_at
                FROM tb_comprobante_facturas
            )
            SELECT
                id_comprobante, uuid_factura, tipo, monto,
                monto_aplicado, saldo_factura,
                moneda, fecha, rfc_emisor, nombre_emisor
            FROM facturas
            WHERE id_comprobante = ANY($1)
            ORDER BY id_comprobante, created_at
        """, ids)
        result = {}
        for r in rows:
            comp_id = r['id_comprobante']
            if comp_id not in result:
                result[comp_id] = []
            result[comp_id].append(dict(r))
        return result

    async def uuid_factura_exists_in_junction(
        self, conn, uuid_factura: str
    ) -> bool:
        """Verifica si un UUID de factura ya esta en la junction table."""
        exists = await conn.fetchval(
            "SELECT 1 FROM tb_comprobante_facturas WHERE uuid_factura = $1",
            uuid_factura
        )
        return bool(exists)

    async def get_cfdi_relacionados_by_comprobante(
        self, conn, id_comprobante: UUID
    ) -> List[dict]:
        """CFDI relacionados de todas las facturas de un comprobante."""
        rows = await conn.fetch("""
            SELECT cr.uuid_factura, cr.uuid_relacionado,
                   cr.tipo_relacion, cr.tipo_relacion_desc
            FROM tb_comprobante_facturas cf
            JOIN tb_cfdi_relacionados cr ON cf.uuid_factura = cr.uuid_factura
            WHERE cf.id_comprobante = $1
            ORDER BY cr.uuid_factura
        """, id_comprobante)
        return [dict(r) for r in rows]

    # ========================================
    # RELACIONES BENEFICIARIO-PROVEEDOR (VISTA)
    # ========================================

    async def get_relaciones_all(
        self, conn, q: Optional[str] = None, limit: int = 100
    ) -> List[dict]:
        """Lista todas las relaciones beneficiario-proveedor con datos del proveedor."""
        query = """
            SELECT
                bp.id, bp.beneficiario_nombre, bp.confianza, bp.created_at,
                p.id_proveedor, p.razon_social, p.rfc, p.nombre_comercial
            FROM tb_beneficiario_proveedor bp
            JOIN tb_proveedores p ON bp.id_proveedor = p.id_proveedor
            WHERE 1=1
        """
        params = []
        param_idx = 1

        if q:
            query += f""" AND (
                bp.beneficiario_nombre ILIKE ${param_idx}
                OR p.razon_social ILIKE ${param_idx}
                OR p.rfc ILIKE ${param_idx}
            )"""
            params.append(f"%{q}%")
            param_idx += 1

        query += f" ORDER BY bp.created_at DESC LIMIT ${param_idx}"
        params.append(limit)

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def delete_relacion(self, conn, relacion_id: int) -> bool:
        """Elimina una relacion beneficiario-proveedor."""
        result = await conn.execute(
            "DELETE FROM tb_beneficiario_proveedor WHERE id = $1", relacion_id
        )
        return result == "DELETE 1"

    # ========================================
    # FACTURAS PARCIALES Y REMANENTES
    # ========================================

    async def desvincular_factura(
        self, conn, id_comprobante: UUID, uuid_factura: str
    ) -> dict:
        """Elimina una factura de la junction table y recalcula el estado del comprobante.

        Retorna dict con nuevo estatus y monto_facturado.
        """
        comprobante_row = await conn.fetchrow(
            "SELECT estatus FROM tb_comprobantes_pago WHERE id_comprobante = $1",
            id_comprobante
        )
        if not comprobante_row:
            raise ValueError("Comprobante no encontrado")
        if comprobante_row['estatus'] == 'CERRADO':
            raise ValueError(
                "No se puede desvincular una factura de un comprobante cerrado. "
                "Reabre el comprobante primero."
            )

        tolerancia = Decimal("0.50")

        # Eliminar de junction
        await conn.execute("""
            DELETE FROM tb_comprobante_facturas
            WHERE id_comprobante = $1 AND uuid_factura = $2
        """, id_comprobante, uuid_factura)

        # Eliminar materiales del historial asociados a esa factura en este comprobante
        await conn.execute("""
            DELETE FROM tb_materiales_historial
            WHERE uuid_factura = $1 AND id_comprobante = $2
        """, uuid_factura, id_comprobante)

        # Eliminar attachment XML de SharePoint registry
        await conn.execute("""
            DELETE FROM tb_documentos_attachments
            WHERE origen_slug = 'factura_xml'
            AND metadata->>'uuid_factura' = $1
            AND metadata->>'id_comprobante' = $2
        """, uuid_factura, str(id_comprobante))

        # Recalcular monto_facturado desde junction
        nuevo_total = await conn.fetchval("""
            SELECT COALESCE(SUM(COALESCE(monto_aplicado, monto, 0)), 0)
            FROM tb_comprobante_facturas
            WHERE id_comprobante = $1
        """, id_comprobante)
        nuevo_total = nuevo_total or Decimal("0")

        row = await conn.fetchrow(
            "SELECT monto, uuid_factura as uuid_principal FROM tb_comprobantes_pago WHERE id_comprobante = $1",
            id_comprobante
        )
        monto_pago = row['monto']
        uuid_principal = row['uuid_principal']

        # Determinar nuevo estatus
        if nuevo_total <= Decimal("0"):
            nuevo_estatus = "PENDIENTE"
        elif nuevo_total >= monto_pago - tolerancia:
            nuevo_estatus = "FACTURADO"
        else:
            nuevo_estatus = "PARCIALMENTE_FACTURADO"

        # Si se desvinculó la factura principal, encontrar la siguiente o limpiar
        nueva_uuid_principal = uuid_principal
        if str(uuid_principal).upper() == uuid_factura.upper():
            siguiente = await conn.fetchval("""
                SELECT uuid_factura FROM tb_comprobante_facturas
                WHERE id_comprobante = $1
                ORDER BY created_at ASC LIMIT 1
            """, id_comprobante)
            nueva_uuid_principal = siguiente  # None si no hay más

        await conn.execute("""
            UPDATE tb_comprobantes_pago
            SET monto_facturado = $1,
                estatus = $2,
                uuid_factura = $3,
                updated_at = NOW()
            WHERE id_comprobante = $4
        """, nuevo_total, nuevo_estatus, nueva_uuid_principal, id_comprobante)

        return {"nuevo_estatus": nuevo_estatus, "monto_facturado": float(nuevo_total)}

    async def cerrar_remanente(
        self, conn, id_comprobante: UUID, motivo: str, user_id: UUID
    ) -> bool:
        """Marca el comprobante como CERRADO con el saldo restante como remanente.

        Solo aplica a PENDIENTE o PARCIALMENTE_FACTURADO.
        """
        row = await conn.fetchrow("""
            SELECT monto, monto_facturado, estatus
            FROM tb_comprobantes_pago
            WHERE id_comprobante = $1
        """, id_comprobante)

        if not row:
            return False
        if row['estatus'] not in ('PENDIENTE', 'PARCIALMENTE_FACTURADO'):
            return False

        monto_remanente = row['monto'] - row['monto_facturado']

        await conn.execute("""
            UPDATE tb_comprobantes_pago
            SET estatus = 'CERRADO',
                monto_remanente = $1,
                motivo_cierre = $2,
                cerrado_por_id = $3,
                cerrado_at = NOW(),
                updated_at = NOW()
            WHERE id_comprobante = $4
        """, monto_remanente, motivo, user_id, id_comprobante)
        return True

    async def cerrar_remanente_automatico(
        self, conn, id_comprobante: UUID, motivo: str, user_id: UUID
    ) -> Optional[dict]:
        """Cierra un comprobante parcial por tolerancia o excepcion de match grupal."""
        row = await conn.fetchrow("""
            SELECT monto, COALESCE(monto_facturado, 0) AS monto_facturado, estatus
            FROM tb_comprobantes_pago
            WHERE id_comprobante = $1
        """, id_comprobante)

        if not row:
            return None

        monto_remanente = row['monto'] - row['monto_facturado']
        puede_cerrar = (
            row['estatus'] in ('PARCIALMENTE_FACTURADO', 'FACTURADO')
            and abs(monto_remanente) > Decimal("0.005")
        )
        if not puede_cerrar:
            return {
                "id_comprobante": id_comprobante,
                "estatus": row['estatus'],
                "monto_remanente": monto_remanente,
                "cerrado": False,
            }

        await conn.execute("""
            UPDATE tb_comprobantes_pago
            SET estatus = 'CERRADO',
                monto_remanente = $1,
                motivo_cierre = $2,
                cerrado_por_id = $3,
                cerrado_at = NOW(),
                updated_at = NOW()
            WHERE id_comprobante = $4
        """, monto_remanente, motivo, user_id, id_comprobante)

        return {
            "id_comprobante": id_comprobante,
            "estatus": "CERRADO",
            "monto_remanente": monto_remanente,
            "cerrado": True,
        }

    async def reabrir_comprobante(
        self, conn, id_comprobante: UUID
    ) -> bool:
        """Revierte un comprobante CERRADO a su estado anterior (PENDIENTE o PARCIALMENTE_FACTURADO).

        Solo aplica a CERRADO.
        """
        tolerancia = Decimal("0.50")

        row = await conn.fetchrow("""
            SELECT monto, monto_facturado, estatus
            FROM tb_comprobantes_pago
            WHERE id_comprobante = $1
        """, id_comprobante)

        if not row or row['estatus'] != 'CERRADO':
            return False

        monto_facturado = row['monto_facturado'] or Decimal("0")
        if monto_facturado <= Decimal("0"):
            estatus_anterior = "PENDIENTE"
        elif monto_facturado >= row['monto'] - tolerancia:
            estatus_anterior = "FACTURADO"
        else:
            estatus_anterior = "PARCIALMENTE_FACTURADO"

        await conn.execute("""
            UPDATE tb_comprobantes_pago
            SET estatus = $1,
                monto_remanente = NULL,
                motivo_cierre = NULL,
                cerrado_por_id = NULL,
                cerrado_at = NULL,
                updated_at = NOW()
            WHERE id_comprobante = $2
        """, estatus_anterior, id_comprobante)
        return True

    # ========================================
    # XML STAGING
    # ========================================

    async def get_xml_attachments_for_backfill(self, conn) -> List[dict]:
        """Retorna XMLs en SharePoint cuyos ítems en historial no tienen tipo_cambio_xml."""
        rows = await conn.fetch("""
            SELECT DISTINCT d.drive_item_id, d.nombre_archivo,
                   d.metadata->>'uuid_factura' AS uuid_factura
            FROM tb_documentos_attachments d
            WHERE d.origen_slug = 'factura_xml'
              AND d.activo = true
              AND d.drive_item_id IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM tb_materiales_historial m
                WHERE m.uuid_factura = (d.metadata->>'uuid_factura')::uuid
                  AND m.tipo_cambio_xml IS NULL
              )
        """)
        return [dict(r) for r in rows]

    async def update_tc_materiales(
        self, conn, uuid_factura: str, tipo_cambio: Decimal
    ) -> int:
        result = await conn.execute("""
            UPDATE tb_materiales_historial
            SET tipo_cambio_xml = $1
            WHERE uuid_factura = $2::uuid AND tipo_cambio_xml IS NULL
        """, tipo_cambio, uuid_factura)
        return int(result.split()[-1])

    async def upsert_xml_staging(
        self, conn, uuid_factura: str, emisor_rfc: str, emisor_nombre: str,
        monto, moneda: str, tipo_factura: str, match_type: str, user_id,
        xml_content_b64: str | None = None
    ):
        await conn.execute("""
            INSERT INTO tb_xml_staging
                (uuid_factura, emisor_rfc, emisor_nombre, monto, moneda,
                 tipo_factura, match_type, estado, uploaded_by_id, updated_at,
                 xml_content_b64)
            VALUES ($1,$2,$3,$4,$5,$6,$7,'PENDIENTE',$8,NOW(),$9)
            ON CONFLICT (uuid_factura) DO UPDATE SET
                estado = 'PENDIENTE',
                match_type = EXCLUDED.match_type,
                updated_at = NOW(),
                xml_content_b64 = COALESCE(EXCLUDED.xml_content_b64, tb_xml_staging.xml_content_b64)
        """, uuid_factura, emisor_rfc, emisor_nombre, monto, moneda,
            tipo_factura, match_type, user_id, xml_content_b64)

    async def confirm_xml_staging(self, conn, uuid_factura: str):
        await conn.execute("""
            UPDATE tb_xml_staging SET estado = 'CONFIRMADO', updated_at = NOW()
            WHERE uuid_factura = $1
        """, uuid_factura)

    async def get_xml_pendientes_count(self, conn) -> int:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM tb_xml_staging WHERE estado = 'PENDIENTE'"
        )
        return int(val or 0)

    async def get_xml_staging_pendientes(self, conn) -> list[dict]:
        rows = await conn.fetch("""
            SELECT
                uuid_factura, emisor_rfc, emisor_nombre,
                monto, moneda, tipo_factura, match_type,
                updated_at,
                xml_content_b64 IS NOT NULL AS tiene_contenido,
                xml_content_b64
            FROM tb_xml_staging
            WHERE estado = 'PENDIENTE'
            ORDER BY updated_at DESC
        """)
        return [dict(r) for r in rows]

    async def delete_xml_staging(self, conn, uuid_factura: str) -> bool:
        result = await conn.execute("""
            DELETE FROM tb_xml_staging
            WHERE uuid_factura = $1 AND estado = 'PENDIENTE'
        """, uuid_factura)
        return result.split()[-1] != '0'

    # ─── PROYECTOS CON BOM (Gap 6) ──────────────────────────

    async def get_proyectos_con_bom(self, conn) -> list:
        """Proyectos con BOM en estatus visible para Compras."""
        rows = await conn.fetch("""
            SELECT DISTINCT ON (p.id_proyecto)
                p.id_proyecto,
                p.proyecto_id_estandar,
                o.nombre_proyecto,
                b.id_bom,
                b.estatus AS bom_estatus,
                b.version AS bom_version,
                COALESCE(items.total, 0) AS total_items,
                COALESCE(items.costo_estimado, 0) AS costo_estimado
            FROM tb_bom b
            JOIN tb_proyectos_gate p ON p.id_proyecto = b.id_proyecto
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(cantidad * COALESCE(precio_unitario, 0)) FILTER (WHERE activo), 0) AS costo_estimado
                FROM tb_bom_items
                WHERE id_bom = b.id_bom
            ) items ON TRUE
            WHERE b.estatus IN ('APROBADO_CONST', 'EN_REVISION_FINAL', 'APROBADO_FINAL')
            ORDER BY p.id_proyecto, b.version DESC
        """)
        return [dict(r) for r in rows]

    # ─── MINI ALMACÉN (Gap 9) ─────────────────────────────

    async def get_proveedores_activos(self, conn) -> list:
        rows = await conn.fetch(
            "SELECT id_proveedor, razon_social FROM tb_proveedores WHERE activo = true ORDER BY razon_social"
        )
        return [dict(r) for r in rows]

    async def get_inventario(self, conn) -> list:
        rows = await conn.fetch("""
            SELECT i.*, p.nombre_comercial AS proveedor_nombre
            FROM tb_inventario i
            LEFT JOIN tb_proveedores p ON p.id_proveedor = i.id_proveedor
            WHERE i.activo = TRUE
            ORDER BY i.descripcion ASC
        """)
        return [dict(r) for r in rows]

    async def insert_inventario(
        self, conn, descripcion: str, cantidad: float,
        unidad_medida: str = None, ubicacion: str = None,
        id_proveedor: UUID = None, id_bom_item_ref: UUID = None,
        notas: str = None
    ) -> dict:
        row = await conn.fetchrow("""
            INSERT INTO tb_inventario
                (descripcion, cantidad_disponible, unidad_medida, ubicacion,
                 id_proveedor, id_bom_item_ref, notas)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
        """, descripcion, cantidad, unidad_medida, ubicacion,
            id_proveedor, id_bom_item_ref, notas)
        return dict(row)

    async def update_inventario(
        self, conn, inventario_id: UUID, **campos
    ) -> dict:
        sets = []
        params = [inventario_id]
        idx = 2
        for key in ('cantidad_disponible', 'ubicacion', 'notas', 'activo'):
            if key in campos and campos[key] is not None:
                sets.append(f"{key} = ${idx}")
                params.append(campos[key])
                idx += 1
        sets.append(f"updated_at = ${idx}")
        params.append(now_mx())
        query = f"UPDATE tb_inventario SET {', '.join(sets)} WHERE id = $1 RETURNING *"
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def get_stock_por_descripcion(self, conn, descripcion: str) -> float:
        """Busca stock disponible por similitud de descripción."""
        val = await conn.fetchval("""
            SELECT COALESCE(SUM(cantidad_disponible), 0)
            FROM tb_inventario
            WHERE activo = TRUE AND descripcion ILIKE $1
        """, f"%{descripcion}%")
        return float(val) if val else 0

    async def get_comprobantes_by_ids(self, conn, ids: List[UUID]) -> List[dict]:
        """Obtiene comprobantes disponibles para match por lista de IDs."""
        rows = await conn.fetch("""
            SELECT id_comprobante, fecha_pago, beneficiario_orig, monto, moneda, estatus, monto_facturado
            FROM tb_comprobantes_pago
            WHERE id_comprobante = ANY($1)
              AND (estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')
                   OR (estatus = 'ANTICIPO' AND COALESCE(monto_facturado, 0) < monto - 0.50))
        """, ids)
        return [dict(r) for r in rows]

    async def buscar_comprobantes_pendientes_para_grupo(
        self, conn, q: Optional[str], moneda: str = 'MXN', limit: int = 30
    ) -> List[dict]:
        """Comprobantes pendientes filtrados por moneda y texto para el panel grupo."""
        params: list = [moneda]
        query = """
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.monto_facturado,
                (c.monto - COALESCE(c.monto_facturado, 0)) AS saldo_pendiente
            FROM tb_comprobantes_pago c
            WHERE (c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')
                   OR (c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50))
              AND c.moneda = $1
        """
        if q:
            params.append(f"%{q}%")
            query += f" AND c.beneficiario_orig ILIKE ${len(params)}"
        query += f" ORDER BY c.fecha_pago DESC LIMIT ${len(params) + 1}"
        params.append(limit)
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


def get_db_service():
    return ComprasDBService()
