# Archivo: modules/compras/service.py
"""
Service Layer del Módulo Compras.
Maneja la lógica de negocio para comprobantes de pago.
"""

from uuid import UUID, uuid4
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Any
from fastapi import HTTPException
from decimal import Decimal
import logging

from .pdf_extractor import process_uploaded_pdf, process_pdf_bytes, ComprobantePDFData

logger = logging.getLogger("ComprasService")


class ComprasService:
    """Lógica de negocio del módulo Compras - Comprobantes de Pago."""
    
    # ========================================
    # CARGA DE COMPROBANTES (PDFs)
    # ========================================
    
    async def process_and_save_pdfs(
        self, 
        conn, 
        files: list, 
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Procesa múltiples PDFs y guarda los comprobantes válidos.
        
        Args:
            conn: Conexión a base de datos
            files: Lista de UploadFile de FastAPI
            user_id: UUID del usuario que realiza la carga
            
        Returns:
            {
                "insertados": int,
                "duplicados": List[dict],
                "errores": List[dict]
            }
        """
        insertados = 0
        duplicados = []
        errores = []
        
        for file in files:
            filename = file.filename
            
            # 1. Leer contenido del archivo
            try:
                content = await file.read()
                await file.seek(0)
            except Exception as e:
                logger.error(f"Error leyendo archivo {filename}: {e}")
                errores.append({
                    "archivo": filename,
                    "error": f"Error al leer archivo: {str(e)}"
                })
                continue
            
            # 2. Extraer datos del PDF
            data = process_pdf_bytes(content, filename)
            
            if data.error or not data.is_valid():
                errores.append({
                    "archivo": filename,
                    "error": data.error or "Datos incompletos"
                })
                continue
            
            # 3. Verificar duplicado
            fecha_pago_date = data.fecha_pago.date() if isinstance(data.fecha_pago, datetime) else data.fecha_pago
            
            exists = await conn.fetchval("""
                SELECT 1 FROM tb_comprobantes_pago 
                WHERE fecha_pago = $1 
                AND beneficiario_orig = $2 
                AND monto = $3
            """, fecha_pago_date, data.beneficiario, Decimal(str(data.monto)))
            
            if exists:
                duplicados.append({
                    "archivo": filename,
                    "fecha": data.fecha_pago.strftime("%d/%m/%Y"),
                    "beneficiario": data.beneficiario,
                    "monto": data.monto,
                    "moneda": data.moneda
                })
                logger.info(f"Duplicado detectado: {filename}")
                continue
            
            # 4. Insertar en base de datos
            try:
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
                    uuid4(), 
                    fecha_pago_date, 
                    data.beneficiario,
                    Decimal(str(data.monto)), 
                    data.moneda, 
                    user_id
                )
                
                insertados += 1
                logger.info(f"Comprobante insertado: {filename} - {data.beneficiario} - ${data.monto}")
                
            except Exception as e:
                logger.error(f"Error insertando comprobante {filename}: {e}")
                errores.append({
                    "archivo": filename,
                    "error": f"Error de base de datos: {str(e)}"
                })
        
        logger.info(f"Proceso completado: {insertados} insertados, {len(duplicados)} duplicados, {len(errores)} errores")
        
        return {
            "insertados": insertados,
            "duplicados": duplicados,
            "errores": errores
        }
    
    # ========================================
    # CONSULTAS DE COMPROBANTES
    # ========================================
    
    async def get_comprobantes(
        self,
        conn,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        estatus: Optional[str] = None,
        id_zona: Optional[int] = None,
        id_proyecto: Optional[UUID] = None,
        id_categoria: Optional[int] = None,
        page: int = 1,
        per_page: int = 50
    ) -> Tuple[List[dict], int]:
        """
        Obtiene comprobantes con filtros y paginación.
        
        Returns:
            (lista_comprobantes, total_count)
        """
        # Query base con JOINs
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
        
        params = []
        param_idx = 1
        
        # Aplicar filtros dinámicamente
        if fecha_inicio:
            base_query += f" AND c.fecha_pago >= ${param_idx}"
            params.append(fecha_inicio)
            param_idx += 1
        
        if fecha_fin:
            base_query += f" AND c.fecha_pago <= ${param_idx}"
            params.append(fecha_fin)
            param_idx += 1
        
        if estatus:
            base_query += f" AND c.estatus = ${param_idx}"
            params.append(estatus)
            param_idx += 1
        
        if id_zona:
            base_query += f" AND c.id_zona = ${param_idx}"
            params.append(id_zona)
            param_idx += 1
        
        if id_proyecto:
            base_query += f" AND c.id_proyecto = ${param_idx}"
            params.append(id_proyecto)
            param_idx += 1
        
        if id_categoria:
            base_query += f" AND c.id_categoria = ${param_idx}"
            params.append(id_categoria)
            param_idx += 1
        
        # Contar total (sin paginación)
        count_query = f"SELECT COUNT(*) FROM ({base_query}) sub"
        total = await conn.fetchval(count_query, *params)
        
        # Agregar ordenamiento y paginación
        base_query += " ORDER BY c.fecha_pago DESC, c.created_at DESC"
        base_query += f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([per_page, (page - 1) * per_page])
        
        # Ejecutar query
        rows = await conn.fetch(base_query, *params)
        
        # Convertir a diccionarios
        comprobantes = []
        for row in rows:
            comp = dict(row)
            # Convertir Decimal a float para serialización
            if comp.get('monto'):
                comp['monto'] = float(comp['monto'])
            comprobantes.append(comp)
        
        return comprobantes, total
    
    async def get_comprobantes_default_view(self, conn) -> Tuple[List[dict], int]:
        """
        Vista default: TODOS los pendientes (sin filtro de fecha) + Mes Actual.
        """
        return await self.get_comprobantes(
            conn,
            fecha_inicio=None,
            fecha_fin=None,
            estatus="PENDIENTE"
        )
    
    async def get_comprobante_by_id(self, conn, id_comprobante: UUID) -> Optional[dict]:
        """
        Obtiene un comprobante específico por ID.
        """
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
        
        if row:
            comp = dict(row)
            if comp.get('monto'):
                comp['monto'] = float(comp['monto'])
            return comp
        return None
    
    # ========================================
    # EDICIÓN DE COMPROBANTES
    # ========================================
    
    async def update_comprobante(
        self,
        conn,
        id_comprobante: UUID,
        updates: dict
    ) -> dict:
        """
        Actualiza campos editables de un comprobante.
        
        Args:
            updates: {id_zona, id_proyecto, id_categoria, estatus, id_proveedor}
            
            Returns:
            Comprobante actualizado
        """
        allowed_fields = ['id_zona', 'id_proyecto', 'id_categoria', 'estatus', 'id_proveedor']
        
        set_clauses = []
        params = []
        param_idx = 1
        
        for field in allowed_fields:
            if field in updates:
                value = updates[field]
                # Permitir NULL explícito
                if value is None or value == "" or value == "null":
                    set_clauses.append(f"{field} = NULL")
                else:
                    set_clauses.append(f"{field} = ${param_idx}")
                    params.append(value)
                    param_idx += 1
        
        if not set_clauses:
            raise HTTPException(status_code=400, detail="No hay campos para actualizar")
        
        # Agregar updated_at
        set_clauses.append(f"updated_at = ${param_idx}")
        params.append(datetime.now())
        param_idx += 1
        
        # ID del comprobante
        params.append(id_comprobante)
        
        query = f"""
            UPDATE tb_comprobantes_pago 
            SET {', '.join(set_clauses)}
            WHERE id_comprobante = ${param_idx}
            RETURNING *
        """
        
        row = await conn.fetchrow(query, *params)
        if not row:
            raise HTTPException(status_code=404, detail="Comprobante no encontrado")
        
        # Obtener datos completos con JOINs
        return await self.get_comprobante_by_id(conn, id_comprobante)
    
    async def bulk_update_comprobantes(
        self,
        conn,
        ids: List[UUID],
        updates: dict
    ) -> int:
        """
        Actualización masiva de múltiples comprobantes.
        
        Args:
            ids: Lista de UUIDs a actualizar
            updates: Campos a actualizar
            
        Returns:
            Número de registros actualizados
        """
        if not ids:
            return 0
            
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
        
        # Agregar updated_at
        set_clauses.append(f"updated_at = ${param_idx}")
        params.append(datetime.now())
        param_idx += 1
        
        # Array de UUIDs
        params.append(ids)
        
        query = f"""
            UPDATE tb_comprobantes_pago 
            SET {', '.join(set_clauses)}
            WHERE id_comprobante = ANY(${param_idx}::uuid[])
        """
        
        result = await conn.execute(query, *params)
        
        # Extraer número de filas afectadas (formato: "UPDATE X")
        try:
            count = int(result.split()[-1])
        except (IndexError, ValueError):
            count = len(ids)
        
        logger.info(f"Bulk update: {count} comprobantes actualizados")
        return count
    
    # ========================================
    # EXPORTACIÓN A EXCEL
    # ========================================
    
    async def export_to_excel(
        self,
        conn,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        estatus: Optional[str] = None,
        id_zona: Optional[int] = None,
        id_proyecto: Optional[UUID] = None,
        id_categoria: Optional[int] = None
    ) -> bytes:
        """
        Genera archivo Excel con los comprobantes filtrados.
        
        Returns:
            Bytes del archivo Excel
        """
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        from io import BytesIO
        
        # Obtener datos (sin límite de paginación)
        comprobantes, _ = await self.get_comprobantes(
            conn,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            estatus=estatus,
            id_zona=id_zona,
            id_proyecto=id_proyecto,
            id_categoria=id_categoria,
            per_page=100000  # Sin límite práctico
        )
        
        # Crear workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Comprobantes de Pago"
        
        # Estilos
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Headers
        headers = [
            "Comprador",
            "Proveedor",
            "Proyecto",
            "Zona",
            "Fecha de Pago",
            "Estatus",
            "Monto",
            "Moneda",
            "Categoría",
            "UUID Factura"
        ]
        
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # Datos
        for row_num, comp in enumerate(comprobantes, 2):
            # Determinar nombre de proveedor
            proveedor = comp.get('proveedor_nombre') or comp.get('beneficiario_orig', '')
            
            row_data = [
                comp.get('comprador_nombre', ''),
                proveedor,
                comp.get('proyecto_nombre', ''),
                comp.get('zona_nombre', ''),
                comp['fecha_pago'].strftime("%d/%m/%Y") if comp.get('fecha_pago') else '',
                comp.get('estatus', ''),
                comp.get('monto', 0),
                comp.get('moneda', 'MXN'),
                comp.get('categoria_nombre', ''),
                str(comp.get('uuid_factura', '')) if comp.get('uuid_factura') else ''
            ]
            
            for col_num, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_num, column=col_num, value=value)
                cell.border = thin_border
                
                # Formato especial para monto
                if col_num == 7:  # Columna Monto
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right")
        
        # Ajustar anchos de columna
        column_widths = [20, 35, 30, 15, 15, 15, 15, 10, 20, 40]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width
        
        # Congelar primera fila
        ws.freeze_panes = "A2"
        
        # Exportar a bytes
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        return buffer.getvalue()
    
    # ========================================
    # CATÁLOGOS
    # ========================================
    
    async def get_catalogos(self, conn) -> dict:
        """
        Obtiene todos los catálogos necesarios para dropdowns.
        """
        zonas = await conn.fetch("""
            SELECT id, nombre 
            FROM tb_cat_zonas_compra 
            WHERE activo = true 
            ORDER BY orden, nombre
        """)
        
        categorias = await conn.fetch("""
            SELECT id, nombre 
            FROM tb_cat_categorias_compra 
            WHERE activo = true 
            ORDER BY orden, nombre
        """)
        
        proyectos = await conn.fetch("""
            SELECT id_proyecto, proyecto_id_estandar as nombre
            FROM tb_proyectos_gate 
            WHERE aprobacion_direccion = true
            ORDER BY proyecto_id_estandar
        """)
        
        # Compradores (usuarios del departamento Compras)
        compradores = await conn.fetch("""
            SELECT id_usuario, nombre
            FROM tb_usuarios
            WHERE is_active = true
            AND LOWER(department) = 'compras'
            ORDER BY nombre
        """)
        
        return {
            "zonas": [dict(z) for z in zonas],
            "categorias": [dict(c) for c in categorias],
            "proyectos": [dict(p) for p in proyectos],
            "compradores": [dict(c) for c in compradores]
        }
    
    async def get_proveedores_search(
        self, 
        conn, 
        search_term: str, 
        limit: int = 10
    ) -> List[dict]:
        """
        Búsqueda de proveedores por nombre o RFC.
        """
        search_pattern = f"%{search_term}%"
        
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
        """, search_pattern, limit)
        
        return [dict(r) for r in rows]
    
    # ========================================
    # ESTADÍSTICAS (para dashboard futuro)
    # ========================================
    
    async def get_estadisticas_generales(
        self, 
        conn,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None,
        estatus: Optional[str] = None,
        id_zona: Optional[int] = None,
        id_proyecto: Optional[UUID] = None,
        id_categoria: Optional[int] = None
    ) -> dict:
        """
        Obtiene estadísticas generales con filtros dinámicos.
        """
        # Query base
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
        
        # Aplicar filtros
        if fecha_inicio:
            base_query += f" AND fecha_pago >= ${param_idx}"
            params.append(fecha_inicio)
            param_idx += 1
        
        if fecha_fin:
            base_query += f" AND fecha_pago <= ${param_idx}"
            params.append(fecha_fin)
            param_idx += 1
            
        if estatus:
            base_query += f" AND estatus = ${param_idx}"
            params.append(estatus)
            param_idx += 1
            
        if id_zona:
            base_query += f" AND id_zona = ${param_idx}"
            params.append(id_zona)
            param_idx += 1
            
        if id_proyecto:
            base_query += f" AND id_proyecto = ${param_idx}"
            params.append(id_proyecto)
            param_idx += 1
            
        if id_categoria:
            base_query += f" AND id_categoria = ${param_idx}"
            params.append(id_categoria)
            param_idx += 1
            
        stats = await conn.fetchrow(base_query, *params)
        
        return {
            "total": stats['total'],
            "pendientes": stats['pendientes'],
            "facturados": stats['facturados'],
            "total_mxn": float(stats['total_mxn']),
            "total_usd": float(stats['total_usd'])
        }


def get_compras_service():
    """Dependency injection para FastAPI."""
    return ComprasService()
