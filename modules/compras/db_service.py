
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

def get_db_service():
    return ComprasDBService()
