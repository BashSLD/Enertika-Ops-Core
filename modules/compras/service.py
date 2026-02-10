# Archivo: modules/compras/service.py
"""
Service Layer del Módulo Compras.
Maneja la lógica de negocio para comprobantes de pago y facturas XML.
"""

from uuid import UUID, uuid4
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Any
from fastapi import HTTPException
from decimal import Decimal
import logging
import time
import json

from .pdf_extractor import process_uploaded_pdf, process_pdf_bytes, ComprobantePDFData
from .xml_extractor import parse_cfdi_xml, validate_xml_content, process_uploaded_xml
from .schemas import (
    CfdiData, TipoFactura, XmlMatchResult, XmlUploadResult, XmlUploadError,
)

logger = logging.getLogger("ComprasService")

# Tolerancia de matching por monto (pesos/dolares)
MATCH_TOLERANCIA = Decimal("0.50")


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


    # ========================================
    # CARGA Y PROCESAMIENTO DE XMLs
    # ========================================

    async def procesar_xmls(
        self,
        conn,
        files: list,
        user_id: UUID
    ) -> XmlUploadResult:
        """
        Procesa multiples XMLs CFDI: parsea, busca match, prepara resultados.
        NO confirma match automaticamente — retorna candidatos para UI.

        Args:
            conn: Conexion a base de datos
            files: Lista de UploadFile
            user_id: UUID del usuario

        Returns:
            XmlUploadResult con procesados, duplicados y errores
        """
        from .db_service import get_db_service
        db_svc = get_db_service()

        result = XmlUploadResult()

        for file in files:
            filename = file.filename or "sin_nombre.xml"

            # 1. Leer contenido
            try:
                content = await file.read()
                await file.seek(0)
            except Exception as e:
                logger.error("Error leyendo XML %s: %s", filename, e)
                result.errores.append(XmlUploadError(
                    archivo=filename, error=f"Error al leer archivo: {e}"
                ))
                continue

            # 2. Validacion rapida
            error_msg = validate_xml_content(content, filename)
            if error_msg:
                result.errores.append(XmlUploadError(
                    archivo=filename, error=error_msg
                ))
                continue

            # 3. Parsear XML
            try:
                cfdi = parse_cfdi_xml(content, filename)
            except ValueError as e:
                result.errores.append(XmlUploadError(
                    archivo=filename, error=str(e)
                ))
                continue

            # 4. Verificar UUID duplicado
            if await db_svc.uuid_factura_exists(conn, cfdi.uuid):
                result.duplicados.append(XmlUploadError(
                    archivo=filename,
                    error=f"UUID {cfdi.uuid[:8]}... ya existe en el sistema"
                ))
                continue

            # 5. Buscar/crear proveedor
            proveedor = await db_svc.get_proveedor_by_rfc(conn, cfdi.emisor_rfc)
            if not proveedor:
                proveedor = await db_svc.create_proveedor(
                    conn, cfdi.emisor_rfc, cfdi.emisor_nombre
                )
                logger.info(
                    "Proveedor creado: RFC=%s, Nombre=%s",
                    cfdi.emisor_rfc, cfdi.emisor_nombre
                )

            # 6. Buscar matching con comprobantes
            match_result = await self._buscar_match(
                conn, db_svc, cfdi, proveedor
            )

            result.procesados.append(match_result)

        logger.info(
            "XMLs procesados: %d OK, %d duplicados, %d errores",
            len(result.procesados), len(result.duplicados), len(result.errores)
        )
        return result

    async def _buscar_match(
        self, conn, db_svc, cfdi: CfdiData, proveedor: dict
    ) -> XmlMatchResult:
        """
        Busca match para un CFDI parseado en 3 niveles:
        1. Relacion conocida (beneficiario↔proveedor)
        2. Solo por monto + moneda
        3. Sin match
        """
        id_proveedor = proveedor['id_proveedor']
        monto = cfdi.total
        moneda = cfdi.moneda or "MXN"

        # Nivel 1: buscar por relacion conocida
        relaciones = await db_svc.get_relaciones_beneficiario(conn, id_proveedor)
        for rel in relaciones:
            beneficiario = rel['beneficiario_nombre']
            candidatos = await db_svc.buscar_comprobantes_match(
                conn, beneficiario, monto, moneda, MATCH_TOLERANCIA
            )
            if len(candidatos) == 1:
                return XmlMatchResult(
                    cfdi=cfdi,
                    match_type="AUTO_MATCH",
                    candidatos=self._format_candidatos(candidatos),
                    comprobante_id=candidatos[0]['id_comprobante'],
                )
            if candidatos:
                return XmlMatchResult(
                    cfdi=cfdi,
                    match_type="MULTIPLE_MATCH",
                    candidatos=self._format_candidatos(candidatos),
                )

        # Nivel 2: buscar solo por monto
        candidatos = await db_svc.buscar_comprobantes_por_monto(
            conn, monto, moneda, MATCH_TOLERANCIA
        )
        if len(candidatos) == 1:
            return XmlMatchResult(
                cfdi=cfdi,
                match_type="MONTO_MATCH",
                candidatos=self._format_candidatos(candidatos),
                comprobante_id=candidatos[0]['id_comprobante'],
            )
        if candidatos:
            return XmlMatchResult(
                cfdi=cfdi,
                match_type="MULTIPLE_MATCH",
                candidatos=self._format_candidatos(candidatos),
            )

        # Nivel 3: sin match
        return XmlMatchResult(
            cfdi=cfdi,
            match_type="NO_MATCH",
            candidatos=[],
        )

    def _format_candidatos(self, rows: List[dict]) -> List[dict]:
        """Formatea candidatos para la respuesta, convirtiendo Decimal a float."""
        formatted = []
        for r in rows:
            item = dict(r)
            if 'monto' in item and isinstance(item['monto'], Decimal):
                item['monto'] = float(item['monto'])
            if 'fecha_pago' in item and hasattr(item['fecha_pago'], 'strftime'):
                item['fecha_pago_str'] = item['fecha_pago'].strftime("%d/%m/%Y")
            formatted.append(item)
        return formatted

    async def confirmar_match_xml(
        self,
        conn,
        cfdi_data: dict,
        id_comprobante: UUID,
        user_id: UUID,
        guardar_relacion: bool = True
    ) -> dict:
        """
        Confirma el match entre un XML y un comprobante de pago.
        Actualiza el comprobante, guarda relacion, conceptos y CFDI relacionados.

        Args:
            conn: Conexion a BD
            cfdi_data: Datos del CFDI (dict del CfdiData)
            id_comprobante: UUID del comprobante seleccionado
            user_id: UUID del usuario
            guardar_relacion: Si guardar la relacion beneficiario↔proveedor

        Returns:
            dict con resultado
        """
        from .db_service import get_db_service
        db_svc = get_db_service()

        uuid_factura = cfdi_data['uuid']
        emisor_rfc = cfdi_data['emisor_rfc']
        tipo_factura = cfdi_data.get('tipo_factura', 'NORMAL')

        # Verificar UUID duplicado (doble check)
        if await db_svc.uuid_factura_exists(conn, uuid_factura):
            raise ValueError(f"UUID {uuid_factura[:8]}... ya existe en el sistema")

        # Obtener/crear proveedor
        proveedor = await db_svc.get_proveedor_by_rfc(conn, emisor_rfc)
        if not proveedor:
            proveedor = await db_svc.create_proveedor(
                conn, emisor_rfc, cfdi_data['emisor_nombre']
            )
        id_proveedor = proveedor['id_proveedor']

        # Obtener comprobante para saber el beneficiario
        comprobante = await db_svc.get_comprobante_by_id(conn, id_comprobante)
        if not comprobante:
            raise ValueError("Comprobante no encontrado")
        if comprobante['estatus'] != 'PENDIENTE':
            raise ValueError("El comprobante ya no esta pendiente")

        # 1. Actualizar comprobante con datos de la factura
        await db_svc.confirmar_match(
            conn, id_comprobante, uuid_factura, id_proveedor, tipo_factura
        )

        # 2. Guardar relacion beneficiario↔proveedor
        if guardar_relacion:
            beneficiario = comprobante['beneficiario_orig']
            await db_svc.guardar_relacion_beneficiario(
                conn, beneficiario, id_proveedor, user_id
            )

        # 3. Guardar conceptos en historial de materiales
        conceptos = cfdi_data.get('conceptos', [])
        if conceptos:
            fecha_str = cfdi_data.get('fecha', '')
            try:
                fecha_factura = datetime.fromisoformat(fecha_str).date()
            except (ValueError, TypeError):
                fecha_factura = date.today()

            conceptos_dicts = [
                {
                    'descripcion': c.get('descripcion', c) if isinstance(c, dict) else c.descripcion,
                    'cantidad': c.get('cantidad', 0) if isinstance(c, dict) else c.cantidad,
                    'valor_unitario': c.get('valor_unitario', 0) if isinstance(c, dict) else c.valor_unitario,
                    'importe': c.get('importe', 0) if isinstance(c, dict) else c.importe,
                    'unidad': c.get('unidad') if isinstance(c, dict) else c.unidad,
                    'clave_prod_serv': c.get('clave_prod_serv') if isinstance(c, dict) else c.clave_prod_serv,
                    'clave_unidad': c.get('clave_unidad') if isinstance(c, dict) else c.clave_unidad,
                }
                for c in conceptos
            ]

            await db_svc.guardar_conceptos_historial(
                conn, uuid_factura, id_comprobante, id_proveedor,
                conceptos_dicts, fecha_factura, user_id
            )

        # 4. Guardar CFDI relacionados
        relacionados = cfdi_data.get('relacionados', [])
        if relacionados:
            rel_dicts = [
                {
                    'uuid': r.get('uuid', r) if isinstance(r, dict) else r.uuid,
                    'tipo_relacion': r.get('tipo_relacion', '') if isinstance(r, dict) else r.tipo_relacion,
                    'tipo_relacion_desc': r.get('tipo_relacion_desc') if isinstance(r, dict) else r.tipo_relacion_desc,
                }
                for r in relacionados
            ]
            await db_svc.guardar_cfdi_relacionados(conn, uuid_factura, rel_dicts)

        # 5. Si es CIERRE_ANTICIPO, vincular con anticipo original
        if tipo_factura == "CIERRE_ANTICIPO" and relacionados:
            for rel in relacionados:
                tipo_rel = rel.get('tipo_relacion', '') if isinstance(rel, dict) else rel.tipo_relacion
                uuid_rel = rel.get('uuid', '') if isinstance(rel, dict) else rel.uuid
                if tipo_rel == "07":
                    await db_svc.vincular_cierre_anticipo(
                        conn, id_comprobante, uuid_rel
                    )

        logger.info(
            "Match confirmado: UUID=%s, Comprobante=%s, Proveedor=%s, Tipo=%s",
            uuid_factura[:8], id_comprobante, emisor_rfc, tipo_factura
        )

        return {
            "uuid_factura": uuid_factura,
            "id_comprobante": str(id_comprobante),
            "id_proveedor": str(id_proveedor),
            "tipo_factura": tipo_factura,
            "conceptos_guardados": len(conceptos),
            "relacionados_guardados": len(relacionados),
        }

    async def buscar_comprobantes_pendientes(
        self, conn, q: Optional[str] = None, limit: int = 20
    ) -> List[dict]:
        """Busqueda libre de comprobantes pendientes para match manual."""
        from .db_service import get_db_service
        db_svc = get_db_service()
        rows = await db_svc.buscar_comprobantes_pendientes(conn, q, limit)
        return self._format_candidatos(rows)

    # ========================================
    # SHAREPOINT - ARCHIVOS
    # ========================================

    async def upload_archivo_sharepoint(
        self, conn, file, subcarpeta: str,
        id_comprobante: Optional[UUID],
        origen_slug: str, user_id: UUID,
        metadata_extra: Optional[dict] = None
    ) -> Optional[dict]:
        """
        Sube un archivo a SharePoint y registra en tb_documentos_attachments.
        Reutiliza patron de levantamientos.

        Args:
            conn: Conexion a BD
            file: UploadFile de FastAPI
            subcarpeta: Ruta relativa (ej: 'compras/facturas_xml/2026-02')
            id_comprobante: UUID del comprobante asociado (puede ser None)
            origen_slug: 'comprobante_pago' o 'factura_xml'
            user_id: UUID del usuario
            metadata_extra: Datos adicionales para JSONB

        Returns:
            dict con url_sharepoint y datos del upload, o None si falla
        """
        from .db_service import get_db_service
        db_svc = get_db_service()

        try:
            from core.microsoft import MicrosoftAuth
            from core.integrations.sharepoint import SharePointService

            ms_auth = MicrosoftAuth()
            app_token = await ms_auth.get_application_token()
            if not app_token:
                logger.error("No se pudo obtener token de SharePoint")
                return None

            sharepoint = SharePointService(access_token=app_token)

            # Construir ruta
            base_folder = await sharepoint._get_base_folder(conn)
            folder_path = f"{base_folder}/{subcarpeta}" if base_folder else subcarpeta

            # Nombre unico
            original_name = file.filename or "archivo"
            timestamp = int(time.time())
            file.filename = f"{timestamp}_{original_name}"

            # Validar tamano
            max_size_row = await conn.fetchval(
                "SELECT valor FROM tb_configuracion_global WHERE clave = 'MAX_UPLOAD_SIZE_MB'"
            )
            max_size_mb = float(max_size_row) if max_size_row else 50.0

            file.file.seek(0, 2)
            f_size = file.file.tell()
            file.file.seek(0)

            if f_size / (1024 * 1024) > max_size_mb:
                logger.warning("Archivo %s excede limite: %d bytes", original_name, f_size)
                return None

            # Upload
            upload_result = await sharepoint.upload_file(conn, file, folder_path)

            # Metadata
            meta = {
                "nombre_original": original_name,
                "content_type": getattr(file, 'content_type', 'application/octet-stream'),
            }
            if id_comprobante:
                meta["id_comprobante"] = str(id_comprobante)
            if metadata_extra:
                meta.update(metadata_extra)

            # Registrar en BD
            doc_id = await db_svc.registrar_archivo_sharepoint(
                conn, id_comprobante, origen_slug,
                upload_result, user_id, meta
            )

            logger.info(
                "Archivo subido a SharePoint: %s -> %s",
                original_name, upload_result.get('webUrl', '')
            )

            return {
                "doc_id": str(doc_id),
                "url_sharepoint": upload_result.get('webUrl', ''),
                "nombre": upload_result.get('name', ''),
            }

        except Exception as e:
            logger.error("Error subiendo archivo a SharePoint: %s", e, exc_info=True)
            return None

    async def get_archivos_comprobante(
        self, conn, id_comprobante: UUID
    ) -> List[dict]:
        """Obtiene archivos asociados a un comprobante."""
        from .db_service import get_db_service
        db_svc = get_db_service()
        return await db_svc.get_archivos_comprobante(conn, id_comprobante)


def get_compras_service():
    """Dependency injection para FastAPI."""
    return ComprasService()
