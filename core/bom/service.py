"""
Service Layer para BOM (Lista de Materiales).
Logica de negocio, workflow de aprobaciones, versionado y exportacion Excel.
"""

import logging
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone

from core.bom.db_service import BomDBService
from core.bom.schemas import EstatusBOM, AccionHistorial, TipoAprobacion

logger = logging.getLogger("BOM.Service")

# Campos que puede editar cada area
CAMPOS_INGENIERIA = {'id_categoria', 'descripcion', 'cantidad', 'unidad_medida', 'precio_unitario', 'origen_precio'}
CAMPOS_CONSTRUCCION = {'fecha_requerida', 'entregado', 'comentarios'}
CAMPOS_COMPRAS = {
    'id_proveedor', 'tipo_entrega', 'fecha_estimada_entrega',
    'fecha_llegada_real', 'comentarios'
}

# Estatus que permiten edicion de items por ingenieria
ESTATUS_EDITABLE_ING = {EstatusBOM.BORRADOR}

# Estatus que permiten edicion por construccion/compras (campos especificos)
ESTATUS_EDITABLE_CONST_COMPRAS = {
    EstatusBOM.APROBADO_ING, EstatusBOM.EN_REVISION_CONST, EstatusBOM.APROBADO
}

# Labels para historial
CAMPO_LABELS = {
    'id_categoria': 'Categoria',
    'descripcion': 'Descripcion',
    'cantidad': 'Cantidad',
    'unidad_medida': 'Unidad de medida',
    'fecha_requerida': 'Fecha requerida',
    'fecha_llegada_real': 'Fecha llegada real',
    'id_proveedor': 'Proveedor',
    'tipo_entrega': 'Tipo entrega',
    'fecha_estimada_entrega': 'Fecha estimada entrega',
    'comentarios': 'Comentarios',
    'entregado': 'Entregado',
    'precio_unitario': 'Precio unitario',
    'origen_precio': 'Origen precio',
}


class BomService:
    """Logica de negocio para BOM."""

    def __init__(self):
        self.db = BomDBService()

    # ─── CREAR BOM ──────────────────────────────────────────

    async def crear_bom(
        self, conn, id_proyecto: UUID, elaborado_por: UUID,
        responsable_ing: Optional[UUID] = None,
        jefe_construccion: Optional[UUID] = None,
        coordinador_obra: Optional[UUID] = None,
        notas: Optional[str] = None
    ) -> dict:
        """Crea un nuevo BOM. Valida que no exista otro en BORRADOR."""
        # Verificar proyecto existe
        proyecto = await self.db.get_proyecto_info(conn, id_proyecto)
        if not proyecto:
            raise ValueError("Proyecto no encontrado")

        # Verificar no hay BOM en BORRADOR
        borrador = await self.db.get_bom_borrador_by_proyecto(conn, id_proyecto)
        if borrador:
            raise ValueError(
                f"Ya existe un BOM en borrador (v{borrador['version']}). "
                "Edita el existente o eliminalo antes de crear uno nuevo."
            )

        # Obtener siguiente version
        max_version = await self.db.get_max_version(conn, id_proyecto)
        nueva_version = max_version + 1

        bom = await self.db.crear_bom(
            conn, id_proyecto, elaborado_por,
            responsable_ing=responsable_ing,
            jefe_construccion=jefe_construccion,
            coordinador_obra=coordinador_obra,
            notas=notas,
            version=nueva_version
        )

        # Registrar en historial
        await self.db.registrar_historial(
            conn, bom['id_bom'], AccionHistorial.CREADO,
            nueva_version, elaborado_por
        )

        logger.info(
            "BOM creado: proyecto=%s, version=%d, por=%s",
            id_proyecto, nueva_version, elaborado_por
        )

        return await self.db.get_bom_by_id(conn, bom['id_bom'])

    # ─── OBTENER BOM ────────────────────────────────────────

    async def get_bom_proyecto(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Obtiene el BOM mas reciente del proyecto."""
        return await self.db.get_bom_by_proyecto(conn, id_proyecto)

    async def get_bom(self, conn, id_bom: UUID) -> dict:
        """Obtiene un BOM por ID. Lanza error si no existe."""
        bom = await self.db.get_bom_by_id(conn, id_bom)
        if not bom:
            raise ValueError("BOM no encontrado")
        return bom

    # ─── ITEMS CRUD ─────────────────────────────────────────


    async def agregar_item(
        self, conn, id_bom: UUID, user_id: UUID,
        descripcion: str, cantidad, id_categoria: Optional[int] = None,
        unidad_medida: Optional[str] = None,
        comentarios: Optional[str] = None,
        precio_unitario=None,
        origen_precio: Optional[str] = 'MANUAL',
        id_material_ref: Optional[UUID] = None,
        area_editor: str = 'ingenieria'
    ) -> dict:
        """Agrega un item al BOM. Permite edicion segun area y estado."""
        bom = await self._validar_edicion_items(conn, id_bom, area_editor)

        orden = await self.db.get_next_orden(conn, id_bom)

        item = await self.db.agregar_item(
            conn, id_bom, descripcion, cantidad,
            id_categoria=id_categoria,
            unidad_medida=unidad_medida,
            comentarios=comentarios,
            orden=orden,
            precio_unitario=precio_unitario,
            origen_precio=origen_precio,
            id_material_ref=id_material_ref
        )

        await self.db.registrar_historial(
            conn, id_bom, AccionHistorial.AGREGADO,
            bom['version'], user_id,
            id_item=item['id_item'],
            campo_modificado='item',
            valor_nuevo=descripcion
        )

        return item

    async def editar_item(
        self, conn, id_item: UUID, user_id: UUID,
        area_editor: str, **campos
    ) -> dict:
        """
        Edita un item del BOM. Valida permisos segun area del editor.
        area_editor: 'ingenieria', 'construccion', 'compras'
        """
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        if not item.get('activo', True):
            raise ValueError("No se puede editar un item eliminado")

        bom_estatus = EstatusBOM(item['bom_estatus'])
        es_catalogo = item.get('origen_precio') == 'CATALOGO'

        # Campos protegidos: items de catalogo no permiten cambiar descripcion,
        # precio, unidad ni origen para preservar integridad del analisis de costos
        campos_protegidos_catalogo = {
            'descripcion', 'precio_unitario', 'origen_precio',
            'id_material_ref', 'unidad_medida'
        }

        # Validar que campos correspondan al area del editor
        campos_filtrados = {}
        if area_editor == 'ingenieria':
            if bom_estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError("El BOM no esta en estado editable para ingenieria")
            campos_filtrados = {k: v for k, v in campos.items() if k in CAMPOS_INGENIERIA}
            # Items de catalogo: remover campos protegidos
            if es_catalogo:
                campos_filtrados = {
                    k: v for k, v in campos_filtrados.items()
                    if k not in campos_protegidos_catalogo
                }
        elif area_editor == 'construccion':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para construccion")
            campos_filtrados = {k: v for k, v in campos.items() if k in CAMPOS_CONSTRUCCION}
            # Marcar entregado: registrar timestamp
            if 'entregado' in campos_filtrados and campos_filtrados['entregado']:
                campos_filtrados['fecha_entrega_check'] = datetime.now(timezone.utc)
            elif 'entregado' in campos_filtrados and not campos_filtrados['entregado']:
                campos_filtrados['fecha_entrega_check'] = None
        elif area_editor == 'compras':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para compras")
            campos_filtrados = {k: v for k, v in campos.items() if k in CAMPOS_COMPRAS}

        if not campos_filtrados:
            raise ValueError("No hay campos validos para actualizar")

        # Registrar cambios en historial
        for campo, valor_nuevo in campos_filtrados.items():
            valor_anterior = item.get(campo)
            if str(valor_anterior) != str(valor_nuevo):
                await self.db.registrar_historial(
                    conn, item['id_bom'], AccionHistorial.EDITADO,
                    item['bom_version'], user_id,
                    id_item=id_item,
                    campo_modificado=CAMPO_LABELS.get(campo, campo),
                    valor_anterior=str(valor_anterior) if valor_anterior is not None else None,
                    valor_nuevo=str(valor_nuevo) if valor_nuevo is not None else None
                )

        updated = await self.db.update_item(conn, id_item, **campos_filtrados)
        return updated

    async def eliminar_item(self, conn, id_item: UUID, user_id: UUID, area_editor: str = 'ingenieria') -> dict:
        """Soft delete de un item. Valida permisos segun area."""
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")

        await self._validar_edicion_items(conn, item['id_bom'], area_editor)

        deleted = await self.db.soft_delete_item(conn, id_item)

        await self.db.registrar_historial(
            conn, item['id_bom'], AccionHistorial.ELIMINADO,
            item['bom_version'], user_id,
            id_item=id_item,
            campo_modificado='item',
            valor_anterior=item.get('descripcion')
        )

        return deleted

    async def get_items(self, conn, id_bom: UUID) -> list:
        """Lista items activos del BOM."""
        return await self.db.get_items_by_bom(conn, id_bom)

    async def get_item(self, conn, id_item: UUID) -> dict:
        """Obtiene un item por ID."""
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        return item

    # ─── WORKFLOW DE APROBACION ──────────────────────────────

    async def enviar_revision_ing(
        self, conn, id_bom: UUID, user_id: UUID,
        responsable_ing: Optional[UUID] = None
    ) -> dict:
        """Envia BOM a revision de responsable de ingenieria."""
        bom = await self.get_bom(conn, id_bom)

        if EstatusBOM(bom['estatus']) != EstatusBOM.BORRADOR:
            raise ValueError("Solo se puede enviar a revision desde BORRADOR")

        # Verificar que tenga items
        items = await self.db.get_items_by_bom(conn, id_bom)
        if not items:
            raise ValueError("El BOM debe tener al menos un item")

        update_kwargs = {
            'fecha_envio_ing': datetime.now(timezone.utc)
        }
        if responsable_ing:
            update_kwargs['responsable_ing'] = responsable_ing

        updated = await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_ING, **update_kwargs
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.ENVIO_REVISION_ING,
            bom['version'], user_id
        )

        logger.info("BOM %s enviado a revision ing por %s", id_bom, user_id)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def aprobar_ing(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Aprueba BOM por responsable de ingenieria."""
        bom = await self.get_bom(conn, id_bom)

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_ING:
            raise ValueError("El BOM debe estar EN_REVISION_ING para aprobar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO_ING,
            fecha_aprobacion_ing=datetime.now(timezone.utc)
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.APROBACION_ING,
            bom['version'], user_id, comentarios=comentarios
        )

        logger.info("BOM %s aprobado por ing %s", id_bom, user_id)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def rechazar_ing(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Rechaza BOM por responsable de ingenieria. Vuelve a BORRADOR."""
        bom = await self.get_bom(conn, id_bom)

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_ING:
            raise ValueError("El BOM debe estar EN_REVISION_ING para rechazar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.BORRADOR
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.RECHAZO_ING,
            bom['version'], user_id, comentarios=comentarios
        )

        logger.info("BOM %s rechazado por ing %s: %s", id_bom, user_id, comentarios)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def enviar_revision_const(
        self, conn, id_bom: UUID, user_id: UUID,
        coordinador_obra: Optional[UUID] = None
    ) -> dict:
        """Envia BOM aprobado por ing a revision de construccion."""
        bom = await self.get_bom(conn, id_bom)

        if EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_ING:
            raise ValueError("El BOM debe estar APROBADO_ING para enviar a construccion")

        update_kwargs = {
            'fecha_envio_const': datetime.now(timezone.utc)
        }
        if coordinador_obra:
            update_kwargs['coordinador_obra'] = coordinador_obra

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_CONST, **update_kwargs
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.ENVIO_REVISION_CONST,
            bom['version'], user_id
        )

        logger.info("BOM %s enviado a revision const por %s", id_bom, user_id)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def aprobar_const(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Aprueba BOM por coordinador de construccion. Estado final."""
        bom = await self.get_bom(conn, id_bom)

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_CONST:
            raise ValueError("El BOM debe estar EN_REVISION_CONST para aprobar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO,
            fecha_aprobacion_const=datetime.now(timezone.utc)
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.APROBACION_CONST,
            bom['version'], user_id, comentarios=comentarios
        )

        logger.info("BOM %s aprobado por const %s", id_bom, user_id)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def rechazar_const(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Rechaza BOM por construccion. Vuelve a APROBADO_ING."""
        bom = await self.get_bom(conn, id_bom)

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_CONST:
            raise ValueError("El BOM debe estar EN_REVISION_CONST para rechazar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO_ING
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.RECHAZO_CONST,
            bom['version'], user_id, comentarios=comentarios
        )

        logger.info("BOM %s rechazado por const %s: %s", id_bom, user_id, comentarios)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def solicitar_modificacion(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """
        Solicita modificacion post-aprobacion.
        Crea nueva version copiando items y pone en BORRADOR.
        """
        bom = await self.get_bom(conn, id_bom)

        if EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO:
            raise ValueError("Solo se puede solicitar modificacion de un BOM APROBADO")

        # Registrar solicitud en version actual
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.SOLICITUD_MODIFICACION,
            bom['version'], user_id, comentarios=comentarios
        )

        # Crear nueva version
        nueva_version = bom['version'] + 1
        nuevo_bom = await self.db.crear_bom(
            conn, bom['id_proyecto'], user_id,
            responsable_ing=bom.get('responsable_ing'),
            coordinador_obra=bom.get('coordinador_obra'),
            notas=f"Modificacion solicitada sobre v{bom['version']}. {comentarios or ''}".strip(),
            version=nueva_version
        )

        # Copiar items activos
        items_copiados = await self.db.copiar_items_a_nueva_version(
            conn, id_bom, nuevo_bom['id_bom']
        )

        await self.db.registrar_historial(
            conn, nuevo_bom['id_bom'], AccionHistorial.CREADO,
            nueva_version, user_id,
            campo_modificado='version',
            valor_anterior=str(bom['version']),
            valor_nuevo=str(nueva_version)
        )

        logger.info(
            "Nueva version BOM creada: proyecto=%s, v%d->v%d, %d items copiados",
            bom['id_proyecto'], bom['version'], nueva_version, items_copiados
        )

        return await self.db.get_bom_by_id(conn, nuevo_bom['id_bom'])

    # ─── HISTORIAL Y APROBACIONES ────────────────────────────

    async def get_historial(self, conn, id_bom: UUID) -> list:
        """Lista historial de cambios."""
        return await self.db.get_historial_by_bom(conn, id_bom)

    async def get_aprobaciones(self, conn, id_bom: UUID) -> list:
        """Lista aprobaciones/rechazos."""
        return await self.db.get_aprobaciones_by_bom(conn, id_bom)

    async def get_estadisticas(self, conn, id_bom: UUID) -> dict:
        """Estadisticas del BOM."""
        return await self.db.get_estadisticas_bom(conn, id_bom)

    # ─── CATALOGOS ──────────────────────────────────────────

    async def get_catalogos(self, conn) -> dict:
        """Obtiene todos los catalogos necesarios para formularios."""
        tipos_entrega = await self.db.get_tipos_entrega(conn)
        categorias = await self.db.get_categorias_compra(conn)
        proveedores = await self.db.get_proveedores(conn)
        usuarios_ing_jefes = await self.db.get_usuarios_por_area(conn, 'ingenieria', solo_jefes=True)
        usuarios_ing = await self.db.get_usuarios_por_area(conn, 'ingenieria', solo_jefes=False)
        
        usuarios_const_jefes = await self.db.get_usuarios_por_area(conn, 'construccion', solo_jefes=True)
        usuarios_const = await self.db.get_usuarios_por_area(conn, 'construccion', solo_jefes=False)

        return {
            'tipos_entrega': tipos_entrega,
            'categorias': categorias,
            'proveedores': proveedores,
            'usuarios_ing': usuarios_ing,           # Lista completa (por si se requiere)
            'usuarios_ing_jefes': usuarios_ing_jefes, # Solo jefes (para Responsable de Ing)
            'usuarios_const': usuarios_const,       # Lista completa (para Coordinador de Obra)
            'usuarios_const_jefes': usuarios_const_jefes, # Solo jefes (para Jefe de Construcción)
        }

    # ─── EXPORT EXCEL ────────────────────────────────────────

    async def export_to_excel(self, conn, id_bom: UUID) -> bytes:
        """Genera archivo Excel con los items del BOM."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        from io import BytesIO

        bom = await self.get_bom(conn, id_bom)
        items = await self.db.get_items_by_bom(conn, id_bom)

        wb = Workbook()
        ws = wb.active
        ws.title = "Lista de Materiales"

        # Estilos
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )

        # Info cabecera BOM (filas 1-5)
        info_font = Font(bold=True, size=10)
        ws.cell(row=1, column=1, value="Proyecto:").font = info_font
        ws.cell(row=1, column=2, value=f"{bom.get('proyecto_id_estandar', '')} - {bom.get('proyecto_nombre', '')}")
        ws.cell(row=2, column=1, value="Version:").font = info_font
        ws.cell(row=2, column=2, value=bom.get('version', 1))
        ws.cell(row=3, column=1, value="Estatus:").font = info_font
        ws.cell(row=3, column=2, value=bom.get('estatus', ''))
        ws.cell(row=4, column=1, value="Elaborado por:").font = info_font
        ws.cell(row=4, column=2, value=bom.get('elaborado_por_nombre', ''))
        ws.cell(row=5, column=1, value="Responsable Ing:").font = info_font
        ws.cell(row=5, column=2, value=bom.get('responsable_ing_nombre', ''))

        # Headers de tabla (fila 7)
        headers_row = 7
        headers = [
            "#", "Categoria", "Descripcion", "Cantidad", "Unidad",
            "Precio Unitario", "Importe",
            "Fecha Requerida", "Fecha Llegada Real", "Proveedor",
            "Tipo Entrega", "Fecha Estimada Entrega", "Comentarios", "Entregado"
        ]

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=headers_row, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border

        # Datos
        total_importe = 0
        for row_num, item in enumerate(items, headers_row + 1):
            precio = item.get('precio_unitario') or 0
            cantidad = item.get('cantidad') or 0
            importe = float(cantidad) * float(precio)
            total_importe += importe

            row_data = [
                row_num - headers_row,
                item.get('categoria_nombre', ''),
                item.get('descripcion', ''),
                item.get('cantidad', 0),
                item.get('unidad_medida', ''),
                float(precio) if precio else None,
                importe if precio else None,
                item['fecha_requerida'].strftime("%d/%m/%Y") if item.get('fecha_requerida') else '',
                item['fecha_llegada_real'].strftime("%d/%m/%Y") if item.get('fecha_llegada_real') else '',
                item.get('proveedor_nombre', ''),
                item.get('tipo_entrega', ''),
                item['fecha_estimada_entrega'].strftime("%d/%m/%Y") if item.get('fecha_estimada_entrega') else '',
                item.get('comentarios', ''),
                'Si' if item.get('entregado') else 'No',
            ]

            for col_num, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_num, column=col_num, value=value)
                cell.border = thin_border
                if col_num == 4:
                    cell.number_format = '#,##0.0000'
                    cell.alignment = Alignment(horizontal="right")
                elif col_num in (6, 7):
                    cell.number_format = '$#,##0.00'
                    cell.alignment = Alignment(horizontal="right")

        # Fila de total
        if items:
            total_row = headers_row + len(items) + 1
            total_font = Font(bold=True, size=11)
            ws.cell(row=total_row, column=3, value="TOTAL").font = total_font
            ws.cell(row=total_row, column=3).border = thin_border
            cell_total = ws.cell(row=total_row, column=7, value=total_importe)
            cell_total.font = total_font
            cell_total.number_format = '$#,##0.00'
            cell_total.alignment = Alignment(horizontal="right")
            cell_total.border = thin_border

        # Anchos de columna
        column_widths = [5, 20, 40, 12, 10, 16, 16, 16, 16, 25, 16, 18, 30, 10]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        ws.freeze_panes = f"A{headers_row + 1}"

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    # ─── HELPERS INTERNOS ────────────────────────────────────

    async def _validar_edicion_items(self, conn, id_bom: UUID, area_editor: str) -> dict:
        """Valida que el BOM estÃ© en estado editable para agregar/eliminar items segun el area."""
        bom = await self.get_bom(conn, id_bom)
        estatus = EstatusBOM(bom['estatus'])

        if area_editor == 'ingenieria':
            if estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError(
                    f"El BOM estÃ¡ en estado {estatus} y no permite ediciÃ³n estructural por IngenierÃa."
                )
        elif area_editor == 'construccion':
            if estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                 raise ValueError(
                    f"El BOM estÃ¡ en estado {estatus} y no permite ediciÃ³n estructural por ConstrucciÃ³n."
                )
        # Compras no suele agregar/eliminar items, pero si fuera necesario se agrega aqui.
        else:
            # Fallback seguro
             if estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError("Area de edicion no reconocida o estado invalido.")
        
        return bom


def get_bom_service():
    """Dependency injection para FastAPI."""
    return BomService()
