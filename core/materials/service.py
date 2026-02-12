# Archivo: core/materials/service.py
"""
Service Layer para Materiales compartido.
Logica de negocio, conversion de tipos y exportacion Excel.
"""

from uuid import UUID
from typing import List, Dict, Optional, Tuple
from decimal import Decimal
import logging

from .db_service import MaterialsDBService, get_materials_db_service

logger = logging.getLogger("MaterialsService")


class MaterialsService:
    """Logica de negocio del modulo Materiales."""

    def __init__(self):
        self.db = get_materials_db_service()

    async def get_materiales(
        self, conn, filtros: dict, page: int = 1, per_page: int = 50
    ) -> Tuple[List[dict], int]:
        """Obtiene materiales con filtros y paginacion."""
        total = await self.db.get_materiales_filtered(
            conn, filtros, page, per_page, count_only=True
        )
        rows = await self.db.get_materiales_filtered(
            conn, filtros, page, per_page, count_only=False
        )

        materiales = []
        for row in rows:
            m = dict(row)
            for key in ('cantidad', 'precio_unitario', 'importe'):
                if m.get(key) and isinstance(m[key], Decimal):
                    m[key] = float(m[key])
            materiales.append(m)

        return materiales, total

    async def get_material_precios(
        self, conn, material_id: UUID
    ) -> Tuple[Optional[dict], List[dict], List[dict]]:
        """Obtiene material + analisis de precios por proveedor + productos con misma clave SAT."""
        material = await self.db.get_material_by_id(conn, material_id)
        if not material:
            return None, [], []

        precios = await self.db.get_material_precios(
            conn, material['descripcion_proveedor']
        )
        # Convertir Decimal a float
        for p in precios:
            for key in ('min_precio', 'max_precio', 'avg_precio'):
                if p.get(key) and isinstance(p[key], Decimal):
                    p[key] = float(p[key])

        # Productos similares por clave SAT (excluye misma descripcion)
        precios_sat = []
        if material.get('clave_prod_serv'):
            precios_sat = await self.db.get_precios_por_clave_sat(
                conn, material['clave_prod_serv'],
                exclude_descripcion=material['descripcion_proveedor']
            )
            for p in precios_sat:
                for key in ('min_precio', 'max_precio', 'avg_precio'):
                    if p.get(key) and isinstance(p[key], Decimal):
                        p[key] = float(p[key])

        return material, precios, precios_sat

    async def update_material(
        self, conn, material_id: UUID, updates: dict
    ) -> Optional[dict]:
        """Actualiza clasificacion interna de un material."""
        success = await self.db.update_material(conn, material_id, updates)
        if not success:
            return None
        material = await self.db.get_material_by_id(conn, material_id)
        if material:
            for key in ('cantidad', 'precio_unitario', 'importe'):
                if material.get(key) and isinstance(material[key], Decimal):
                    material[key] = float(material[key])
        return material

    async def get_estadisticas(self, conn, filtros: dict) -> dict:
        """Obtiene estadisticas de materiales."""
        return await self.db.get_estadisticas(conn, filtros)

    async def get_catalogos(self, conn) -> dict:
        """Obtiene catalogos para dropdowns."""
        return await self.db.get_catalogos(conn)

    async def buscar_materiales_similares(
        self, conn, query: str, threshold: float = 0.3, limit: int = 20
    ) -> List[dict]:
        """Busqueda fuzzy de materiales por descripcion."""
        rows = await self.db.buscar_similar_materiales(
            conn, query, threshold, limit
        )
        for r in rows:
            for key in ('precio_unitario', 'importe', 'similitud'):
                if r.get(key) and isinstance(r[key], Decimal):
                    r[key] = float(r[key])
        return rows

    async def export_to_excel(self, conn, filtros: dict) -> bytes:
        """Genera archivo Excel con materiales filtrados."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        from io import BytesIO

        materiales, _ = await self.get_materiales(
            conn, filtros=filtros, per_page=100000
        )

        wb = Workbook()
        ws = wb.active
        ws.title = "Materiales"

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

        headers = [
            "Proveedor",
            "RFC",
            "Descripcion Proveedor",
            "Descripcion Interna",
            "Categoria",
            "Cantidad",
            "P. Unitario",
            "Importe",
            "Unidad",
            "Clave SAT",
            "Fecha Factura",
            "Origen",
            "Proyecto",
        ]

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border

        for row_num, m in enumerate(materiales, 2):
            row_data = [
                m.get('proveedor_nombre', ''),
                m.get('proveedor_rfc', ''),
                m.get('descripcion_proveedor', ''),
                m.get('descripcion_interna', ''),
                m.get('categoria_nombre', ''),
                m.get('cantidad', 0),
                m.get('precio_unitario', 0),
                m.get('importe', 0),
                m.get('unidad', ''),
                m.get('clave_prod_serv', ''),
                m['fecha_factura'].strftime("%d/%m/%Y") if m.get('fecha_factura') else '',
                m.get('origen', ''),
                m.get('proyecto_nombre', ''),
            ]

            for col_num, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_num, column=col_num, value=value)
                cell.border = thin_border

                # Formato numerico para cantidad, precio e importe
                if col_num in (6, 7, 8):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right")

        # Anchos de columna
        column_widths = [30, 15, 40, 35, 20, 12, 14, 14, 10, 12, 14, 10, 25]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        ws.freeze_panes = "A2"

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()


def get_materials_service():
    """Dependency injection para FastAPI."""
    return MaterialsService()
