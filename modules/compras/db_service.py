
# modules/compras/db_service.py
from uuid import UUID, uuid4
from datetime import date, datetime
from typing import List, Tuple, Optional
from decimal import Decimal
from fastapi import HTTPException
import logging

logger = logging.getLogger("Compras.DBService")

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
        await conn.execute("""
            INSERT INTO tb_comprobantes_pago (
                id_comprobante, 
                fecha_pago, 
                beneficiario_orig,
                monto, 
                moneda, 
                estatus, 
                capturado_por_id,
                created_at,
                updated_at
            ) VALUES ($1, $2, $3, $4, $5, 'PENDIENTE', $6, NOW(), NOW())
        """, 
            new_id, 
            comprobante_data['fecha_pago'], 
            comprobante_data['beneficiario'],
            comprobante_data['monto'], 
            comprobante_data['moneda'], 
            comprobante_data['user_id']
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
        base_query = """
            SELECT 
                c.id_comprobante,
                c.fecha_pago,
                c.beneficiario_orig,
                c.monto,
                c.moneda,
                c.estatus,
                c.uuid_factura,
                c.created_at,
                c.id_proveedor,
                c.id_zona,
                c.id_proyecto,
                c.id_categoria,
                u.nombre as comprador_nombre,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                z.nombre as zona_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                cat.nombre as categoria_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            LEFT JOIN tb_proveedores p ON c.id_proveedor = p.id_proveedor
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
        row = await conn.fetchrow("""
            SELECT 
                c.*,
                u.nombre as comprador_nombre,
                p.razon_social as proveedor_nombre,
                z.nombre as zona_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                cat.nombre as categoria_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            LEFT JOIN tb_proveedores p ON c.id_proveedor = p.id_proveedor
            LEFT JOIN tb_cat_zonas_compra z ON c.id_zona = z.id
            LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
            LEFT JOIN tb_cat_categorias_compra cat ON c.id_categoria = cat.id
            WHERE c.id_comprobante = $1
        """, id_comprobante)
        return dict(row) if row else None

    async def update_comprobante(self, conn, id_comprobante: UUID, updates: dict) -> bool:
        allowed_fields = ['id_zona', 'id_proyecto', 'id_categoria', 'estatus', 'id_proveedor']
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
        params.append(datetime.now())
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
        params.append(datetime.now())
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
        except:
            return 0

    async def get_catalogos_data(self, conn) -> dict:
        zonas = await conn.fetch("SELECT id, nombre FROM tb_cat_zonas_compra WHERE activo = true ORDER BY orden, nombre")
        categorias = await conn.fetch("SELECT id, nombre FROM tb_cat_categorias_compra WHERE activo = true ORDER BY orden, nombre")
        proyectos = await conn.fetch("SELECT id_proyecto, proyecto_id_estandar as nombre FROM tb_proyectos_gate WHERE aprobacion_direccion = true ORDER BY proyecto_id_estandar")
        compradores = await conn.fetch("SELECT id_usuario, nombre FROM tb_usuarios WHERE is_active = true AND LOWER(department) = 'compras' ORDER BY nombre")
        
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
        """Busca comprobantes pendientes por beneficiario + monto con tolerancia."""
        rows = await conn.fetch("""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.created_at,
                u.nombre as comprador_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            WHERE c.estatus = 'PENDIENTE'
            AND c.beneficiario_orig = $1
            AND c.moneda = $2
            AND ABS(c.monto - $3) <= $4
            ORDER BY c.fecha_pago DESC
        """, beneficiario, moneda, monto, tolerancia)
        return [dict(r) for r in rows]

    async def buscar_comprobantes_por_monto(
        self, conn, monto: Decimal, moneda: str,
        tolerancia: Decimal = Decimal("0.50")
    ) -> List[dict]:
        """Busca comprobantes pendientes solo por monto + moneda."""
        rows = await conn.fetch("""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.created_at,
                u.nombre as comprador_nombre
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            WHERE c.estatus = 'PENDIENTE'
            AND c.moneda = $1
            AND ABS(c.monto - $2) <= $3
            ORDER BY c.fecha_pago DESC
        """, moneda, monto, tolerancia)
        return [dict(r) for r in rows]

    async def buscar_comprobantes_pendientes(
        self, conn, q: Optional[str] = None, limit: int = 20
    ) -> List[dict]:
        """Busqueda libre de comprobantes pendientes (para match manual)."""
        query = """
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig,
                c.monto, c.moneda, c.estatus, c.created_at
            FROM tb_comprobantes_pago c
            WHERE c.estatus = 'PENDIENTE'
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

    async def confirmar_match(
        self, conn, id_comprobante: UUID, uuid_factura: str,
        id_proveedor: UUID, tipo_factura: str = "NORMAL"
    ):
        """Actualiza comprobante con datos de la factura XML."""
        estatus = "ANTICIPO" if tipo_factura == "ANTICIPO" else "FACTURADO"
        es_anticipo = tipo_factura == "ANTICIPO"

        await conn.execute("""
            UPDATE tb_comprobantes_pago
            SET uuid_factura = $1,
                id_proveedor = $2,
                estatus = $3,
                es_anticipo = $4,
                tipo_factura = $5,
                updated_at = NOW()
            WHERE id_comprobante = $6
        """, uuid_factura, id_proveedor, estatus, es_anticipo,
            tipo_factura, id_comprobante)

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

    async def guardar_relacion_beneficiario(
        self, conn, beneficiario: str, id_proveedor: UUID, user_id: UUID
    ):
        """Guarda o actualiza la relacion beneficiario - proveedor."""
        await conn.execute("""
            INSERT INTO tb_beneficiario_proveedor
                (beneficiario_nombre, id_proveedor, confianza, created_by_id)
            VALUES ($1, $2, 'MANUAL', $3)
            ON CONFLICT (beneficiario_nombre, id_proveedor) DO NOTHING
        """, beneficiario, id_proveedor, user_id)

    async def guardar_conceptos_historial(
        self, conn, uuid_factura: str, id_comprobante: Optional[UUID],
        id_proveedor: UUID, conceptos: List[dict],
        fecha_factura: date, user_id: UUID
    ):
        """Guarda los conceptos/items del XML en tb_materiales_historial."""
        for c in conceptos:
            await conn.execute("""
                INSERT INTO tb_materiales_historial (
                    uuid_factura, id_comprobante, id_proveedor,
                    descripcion_proveedor, cantidad, precio_unitario,
                    importe, unidad, clave_prod_serv, clave_unidad,
                    origen, fecha_factura, created_by_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'XML', $11, $12)
                ON CONFLICT (uuid_factura, descripcion_proveedor, cantidad, precio_unitario)
                DO NOTHING
            """,
                uuid_factura, id_comprobante, id_proveedor,
                c['descripcion'], c['cantidad'], c['valor_unitario'],
                c['importe'], c.get('unidad'), c.get('clave_prod_serv'),
                c.get('clave_unidad'), fecha_factura, user_id
            )

    async def guardar_cfdi_relacionados(
        self, conn, uuid_factura: str, relacionados: List[dict]
    ):
        """Guarda los CFDI relacionados del XML."""
        for rel in relacionados:
            await conn.execute("""
                INSERT INTO tb_cfdi_relacionados
                    (uuid_factura, uuid_relacionado, tipo_relacion, tipo_relacion_desc)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (uuid_factura, uuid_relacionado, tipo_relacion)
                DO NOTHING
            """,
                uuid_factura, rel['uuid'],
                rel['tipo_relacion'], rel.get('tipo_relacion_desc')
            )

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
        return [dict(r) for r in rows]


def get_db_service():
    return ComprasDBService()
