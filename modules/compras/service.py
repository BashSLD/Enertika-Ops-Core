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
        filtros: dict,
        page: int = 1,
        per_page: int = 50
    ) -> Tuple[List[dict], int]:
        """
        Obtiene comprobantes con filtros y paginación.
        """
        from .db_service import get_db_service
        db_svc = get_db_service()

        # Obtener total
        total = await db_svc.get_comprobantes_filtered(
            conn, filtros, page, per_page, count_only=True
        )

        # Obtener datos
        rows = await db_svc.get_comprobantes_filtered(
            conn, filtros, page, per_page, count_only=False
        )
        
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
        Vista default: TODOS los pendientes (sin filtro de fecha).
        """
        return await self.get_comprobantes(
            conn,
            filtros={"estatus": "PENDIENTE"}
        )
    
    async def get_comprobante_by_id(self, conn, id_comprobante: UUID) -> Optional[dict]:
        """
        Obtiene un comprobante específico por ID.
        """
        from .db_service import get_db_service
        db_svc = get_db_service()
        
        comp = await db_svc.get_comprobante_by_id(conn, id_comprobante)
        if comp:
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
        updates: dict,
        user_context: dict
    ) -> dict:
        """
        Actualiza campos editables de un comprobante.
        """
        from .db_service import get_db_service
        db_svc = get_db_service()
        
        # PERMISOS: Admin/Manager, Editor Module, o DUEÑO DEL REGISTRO
        user_id = user_context.get("user_db_id")
        user_role = user_context.get("role")
        mod_role = user_context.get("module_roles", {}).get("compras")
        
        is_admin_or_editor = (user_role in ["ADMIN", "MANAGER"] or mod_role in ["admin", "editor"])
        
        if not is_admin_or_editor:
            # Verificar ownership
            current = await db_svc.get_comprobante_by_id(conn, id_comprobante)
            if not current:
                raise HTTPException(status_code=404, detail="Comprobante no encontrado")
                
            if current['capturado_por_id'] != user_id:
                raise HTTPException(
                    status_code=403, 
                    detail="Solo puedes editar los comprobantes que tú capturaste."
                )
        
        success = await db_svc.update_comprobante(conn, id_comprobante, updates)
        if not success:
             raise HTTPException(status_code=404, detail="Comprobante no encontrado o sin cambios")
        
        return await self.get_comprobante_by_id(conn, id_comprobante)
    
    async def bulk_update_comprobantes(
        self,
        conn,
        ids: List[UUID],
        updates: dict,
        user_context: dict
    ) -> int:
        """
        Actualización masiva de múltiples comprobantes.
        """
        if not ids:
            return 0
            
        from .db_service import get_db_service
        db_svc = get_db_service()
        
        # PERMISOS
        user_id = user_context.get("user_db_id")
        user_role = user_context.get("role")
        mod_role = user_context.get("module_roles", {}).get("compras")
        
        is_admin_or_editor = (user_role in ["ADMIN", "MANAGER"] or mod_role in ["admin", "editor"])
        
        if not is_admin_or_editor:
            # Verificar que TODOS los comprobantes sean del usuario
            # Optimizacion: Consultar solo los que NO son del usuario
            query = """
                SELECT COUNT(*) 
                FROM tb_comprobantes_pago
                WHERE id_comprobante = ANY($1)
                AND capturado_por_id != $2
            """
            not_owned_count = await conn.fetchval(query, ids, user_id)
            
            if not_owned_count > 0:
                raise HTTPException(
                    status_code=403,
                    detail=f"Seleccionaste {not_owned_count} comprobante(s) que no te pertenecen. Solo puedes editar tus propios registros."
                )
        
        count = await db_svc.bulk_update(conn, ids, updates)
        logger.info(f"Bulk update: {count} comprobantes actualizados")
        return count
    
    # ========================================
    # EXPORTACIÓN A EXCEL
    # ========================================
    
    async def export_to_excel(
        self,
        conn,
        filtros: dict
    ) -> bytes:
        """
        Genera archivo Excel con los comprobantes filtrados.
        """
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        from io import BytesIO
        
        # Obtener datos (sin límite de paginación logic handled inside get_comprobantes via per_page=0 trick or similar in db_service if implemented, 
        # but here we reuse get_comprobantes which expects per_page.
        # Let's adjust get_comprobantes call to request all.
        
        comprobantes, _ = await self.get_comprobantes(
            conn,
            filtros=filtros,
            per_page=100000 
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
        from .db_service import get_db_service
        db_svc = get_db_service()
        return await db_svc.get_catalogos_data(conn)
    
    async def get_proveedores_search(
        self, 
        conn, 
        search_term: str, 
        limit: int = 10
    ) -> List[dict]:
        """
        Búsqueda de proveedores por nombre o RFC.
        """
        from .db_service import get_db_service
        db_svc = get_db_service()
        return await db_svc.search_proveedores(conn, search_term, limit)
    
    # ========================================
    # ESTADÍSTICAS (para dashboard futuro)
    # ========================================
    
    async def get_estadisticas_generales(
        self, 
        conn,
        filtros: Optional[dict] = None,
        # Legacy params support for ease of refactor, convert them to dict
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
        from .db_service import get_db_service
        db_svc = get_db_service()
        
        # Build filter dict if not provided
        if filtros is None:
            filtros = {
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "estatus": estatus,
                "id_zona": id_zona,
                "id_proyecto": id_proyecto,
                "id_categoria": id_categoria
            }
            
        stats = await db_svc.get_estadisticas(conn, filtros)
        
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
