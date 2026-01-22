from fpdf import FPDF
from datetime import datetime
import io
import base64
import logging
from typing import Dict, Any

logger = logging.getLogger("PDFGenerator")

# =============================================================================
# CONSTANTES DE ESTILO
# =============================================================================

COLORS = {
    'primary': (0, 186, 187),      # #00BABB - Teal corporativo
    'header_bg': (18, 52, 86),     # #123456 - Azul oscuro
    'green': (16, 185, 129),       # #10B981
    'amber': (245, 158, 11),       # #F59E0B
    'red': (239, 68, 68),          # #EF4444
    'gray': (107, 114, 128),       # #6B7280
    'text': (17, 24, 39),          # #111827
    'light_gray': (243, 244, 246)  # #F3F4F6 - Fondo alterno filas
}


class PDFConFooter(FPDF):
    """Subclase de FPDF con footer automático"""
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        fecha_gen = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.cell(0, 10, f'Generado el: {fecha_gen} | Página {self.page_no()}', 0, 0, 'C')


class ReportePDFGenerator:
    def __init__(self, filtros: Any, datos: Dict[str, Any], chart_images: Dict[str, str]):
        self.pdf = PDFConFooter(orientation='L', unit='mm', format='Letter')
        self.filtros = filtros
        self.datos = datos
        self.chart_images = chart_images
        
        self.pdf.set_margins(10, 10, 10)
        self.pdf.set_auto_page_break(auto=True, margin=15)
        
        # Metadata
        self.pdf.set_title(f"Reporte Simulación {filtros.fecha_inicio} - {filtros.fecha_fin}")
        self.pdf.set_author("Enertika Core Ops")
        
        # Temp images registry to cleanup later (if using temp files)
        # Using bytes directly with FPDF 1.7.2 might require a trick or temp file 
        # But we will use the clean approach of writing temp files if needed, 
        # or passing buffer if supported (FPDF 1.7.2 supports image from file mostly)
        self.temp_files = []

    def _add_header(self):
        # Header azul
        self.pdf.set_fill_color(*COLORS['header_bg'])
        self.pdf.rect(0, 0, 279.4, 25, 'F')
        
        # Texto Header
        self.pdf.set_y(8)
        self.pdf.set_font('Arial', 'B', 16)
        self.pdf.set_text_color(255, 255, 255)
        self.pdf.cell(0, 10, 'Reporte de Simulación - KPI Dashboard', 0, 1, 'C')
        
        # Periodo
        self.pdf.set_font('Arial', '', 10)
        self.pdf.cell(0, 5, f"Periodo: {self.filtros.fecha_inicio} al {self.filtros.fecha_fin}", 0, 1, 'C')
        self.pdf.ln(10)

    # Footer ahora es automático via PDFConFooter.footer()

    def insert_chart_image(self, chart_key: str, x: int, y: int, w: int, h: int = 0) -> bool:
        """Decodifica base64 y dibuja la imagen. Retorna False si no hay imagen."""
        if chart_key not in self.chart_images or not self.chart_images[chart_key]:
            return False

        b64_str = self.chart_images[chart_key]
        if ',' in b64_str:
            b64_str = b64_str.split(',')[1]
            
        try:
            img_data = base64.b64decode(b64_str)
            
            # FPDF 1.7.2 trick: use a temporary file
            import tempfile
            import os
            
            # Create a named temporary file that FPDF can read
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                tmp.write(img_data)
                tmp_path = tmp.name
                
            self.pdf.image(tmp_path, x=x, y=y, w=w, h=h)
            
            # Clean up
            try:
                os.unlink(tmp_path)
            except:
                pass
                
        except Exception as e:
            print(f"Error insertando imagen {chart_key}: {e}")
            self.pdf.set_xy(x, y)
            self.pdf.set_font('Arial', '', 8)
            self.pdf.cell(w, 10, f"[Error gráfico: {chart_key}]", border=1, align='C')

    def _draw_kpi_card(self, x, y, title, value, subtitle=None, color_key='primary'):
        # Card background
        self.pdf.set_fill_color(255, 255, 255)
        self.pdf.set_draw_color(220, 220, 220)
        self.pdf.rect(x, y, 60, 25, 'FD')
        
        # Border left color
        r, g, b = COLORS.get(color_key, COLORS['primary'])
        self.pdf.set_fill_color(r, g, b)
        self.pdf.rect(x, y, 2, 25, 'F')
        
        # Title
        self.pdf.set_xy(x + 5, y + 4)
        self.pdf.set_font('Arial', '', 9)
        self.pdf.set_text_color(*COLORS['gray'])
        self.pdf.cell(50, 5, title, 0, 1)
        
        # Value
        self.pdf.set_xy(x + 5, y + 10)
        self.pdf.set_font('Arial', 'B', 14)
        self.pdf.set_text_color(*COLORS['text'])
        self.pdf.cell(50, 8, str(value), 0, 1)
        
        # Subtitle
        if subtitle:
            self.pdf.set_xy(x + 5, y + 18)
            self.pdf.set_font('Arial', '', 7)
            self.pdf.set_text_color(*COLORS['gray'])
            self.pdf.cell(50, 4, subtitle, 0, 1)

    def _add_kpis_page(self):
        self.pdf.add_page()
        self._add_header()
        m = self.datos['metricas']
        
        # --- CARDS ROW ---
        y_cards = 35
        # Fila 1
        self._draw_kpi_card(10, y_cards, "Solicitudes", m.total_solicitudes)
        self._draw_kpi_card(75, y_cards, "Ofertas Generadas", m.total_ofertas, "Entregadas + Perdidas")
        self._draw_kpi_card(140, y_cards, "Entregas a Tiempo", f"{m.porcentaje_a_tiempo}%", f"{m.entregas_a_tiempo} de {m.entregas_a_tiempo + m.entregas_tarde}", 'green')
        self._draw_kpi_card(205, y_cards, "Tiempo Promedio", f"{m.tiempo_promedio_dias} días", "Elaboración", 'primary')
        
        # --- CHARTS ROW ---
        y_charts = 75
        
        # Estatus Pie
        self.pdf.set_xy(10, y_charts - 5)
        self.pdf.set_font('Arial', 'B', 11)
        self.pdf.set_text_color(*COLORS['text'])
        self.pdf.cell(80, 5, "Distribución por Estatus", 0, 1)
        self.insert_chart_image('estatus', 10, y_charts, 80)
        
        # Mensual Bar
        self.pdf.set_xy(100, y_charts - 5)
        self.pdf.cell(100, 5, "Solicitudes por Mes", 0, 1)
        self.insert_chart_image('mensual', 100, y_charts, 160, 60)
        
        # KPI Bar (abajo)
        y_charts_2 = 145
        self.pdf.set_xy(100, y_charts_2 - 5)
        self.pdf.cell(100, 5, "KPI Cumplimiento", 0, 1)
        self.insert_chart_image('kpi', 100, y_charts_2, 160, 50)
        # Footer automático via PDFConFooter

    def _add_tecnologia_page(self):
        if not self.datos.get('tecnologias'):
            return  # No agregar página si no hay datos
        self.pdf.add_page()
        self._add_header()
        
        # Título sección
        self.pdf.set_font('Arial', 'B', 14)
        self.pdf.set_text_color(*COLORS['primary'])
        self.pdf.cell(0, 10, "Detalle por Tecnología", 0, 1)
        
        # Tabla
        headers = ["Tecnología", "Solicitudes", "Ofertas", "A Tiempo", "Tarde", "% Cumpl.", "Potencia (kWp)", "Capacidad (kWh)"]
        widths = [45, 25, 25, 25, 25, 25, 35, 35]
        
        self._draw_table_header(headers, widths)
        
        total_sol = 0
        total_ofe = 0
        
        for tech in self.datos['tecnologias']:
            row_data = [
                tech.nombre,
                str(tech.total_solicitudes),
                str(tech.total_ofertas),
                str(tech.entregas_a_tiempo),
                str(tech.entregas_tarde),
                f"{tech.porcentaje_a_tiempo}%",
                f"{tech.potencia_total_kwp:,.0f}",
                f"{tech.capacidad_total_kwh:,.0f}"
            ]
            self._draw_table_row(row_data, widths)
            total_sol += tech.total_solicitudes
            total_ofe += tech.total_ofertas
            
        # Chart tecnología
        self.pdf.set_y(self.pdf.get_y() + 10)
        self.pdf.set_font('Arial', 'B', 11)
        self.pdf.set_text_color(*COLORS['text'])
        self.pdf.cell(0, 10, "Distribución Visual", 0, 1)
        self.insert_chart_image('tecnologia', 10, self.pdf.get_y(), 100)
        # Footer automático via PDFConFooter

    def _add_contabilizacion_page(self):
        if not self.datos.get('contabilizacion'):
            return  # No agregar página si no hay datos
        self.pdf.add_page()
        self._add_header()
        
        self.pdf.set_font('Arial', 'B', 14)
        self.pdf.set_text_color(*COLORS['primary'])
        self.pdf.cell(0, 10, "Contabilización y Semáforos", 0, 1)
        
        # headers = ["Tipo Solicitud", "Código", "Total", "En Plazo", "Fuera Plazo", "% Cumplimiento", "Semáforo"]
        headers = ["Tipo Solicitud", "Total", "En Plazo", "Fuera Plazo", "Sin Fecha", "% Cumpl.", "Estado"]
        widths = [70, 25, 25, 25, 25, 25, 20]
        
        self._draw_table_header(headers, widths)
        
        for row in self.datos['contabilizacion']:
            self.pdf.set_font('Arial', '', 9)
            self.pdf.set_fill_color(*COLORS['light_gray'] if self.pdf.get_y() % 2 == 0 else (255, 255, 255))
            
            x_start = self.pdf.get_x()
            y_start = self.pdf.get_y()
            
            # Celdas texto
            data = [
                row.nombre,
                str(row.total),
                str(row.en_plazo),
                str(row.fuera_plazo),
                str(row.sin_fecha),
                f"{row.porcentaje_en_plazo}%" if not row.es_levantamiento else "N/A"
            ]
            
            for i, txt in enumerate(data):
                self.pdf.cell(widths[i], 8, txt, 1, 0, 'C' if i > 0 else 'L')
                
            # Celda semáforo
            x_sem = self.pdf.get_x()
            self.pdf.cell(widths[-1], 8, "", 1, 1)
            
            # Dibujar círculo
            if not row.es_levantamiento and row.total > 0:
                color = COLORS.get(row.semaforo, COLORS['gray'])
                self.pdf.set_fill_color(*color)
                # Centrar círculo
                cx = x_sem + (widths[-1] / 2)
                cy = y_start + 4
                r = 2.5
                self.pdf.ellipse(cx - r, cy - r, r * 2, r * 2, 'F')
                
                # Reset fill color
                self.pdf.set_fill_color(255, 255, 255)
        # Footer automático via PDFConFooter

    def _add_usuarios_pages(self):
        """Genera páginas con detalle por usuario.
        Espera List[DetalleUsuario] con: usuario_id, nombre, metricas_generales, metricas_por_tecnologia
        """
        if not self.datos.get('usuarios'):
            return  # No agregar página si no hay datos
        
        self.pdf.add_page()
        self._add_header()
        
        self.pdf.set_font('Arial', 'B', 14)
        self.pdf.set_text_color(*COLORS['primary'])
        self.pdf.cell(0, 10, "Desempeño por Usuario", 0, 1)
        
        headers = ["Usuario", "Solicitudes", "A Tiempo", "Tarde", "Sin Fecha", "% Cumpl.", "Potencia"]
        widths = [65, 30, 30, 30, 30, 30, 45]
        
        self._draw_table_header(headers, widths)
        
        total_sol = 0
        
        for user in self.datos.get('usuarios', []):
            # Verificar si necesitamos nueva página
            if self.pdf.get_y() > 180:
                self.pdf.add_page()
                self._draw_table_header(headers, widths)
                
            self.pdf.set_font('Arial', '', 9)
            
            # row data extraction - acceso via user.metricas_generales
            nombre = user.nombre
            m = user.metricas_generales
            total = m.total_solicitudes
            a_tiempo = m.entregas_a_tiempo
            tarde = m.entregas_tarde
            sin_fecha = m.sin_fecha_entrega
            pct = f"{m.porcentaje_a_tiempo}%"
            # Potencia viene de sumar tecnologías del usuario
            potencia_total = sum(t.potencia_total_kwp for t in user.metricas_por_tecnologia)
            potencia = f"{potencia_total:,.0f} kWp"
            
            row_data = [nombre, str(total), str(a_tiempo), str(tarde), str(sin_fecha), pct, potencia]
            
            self._draw_table_row(row_data, widths)
            total_sol += total
            
        # Footer automático via PDFConFooter

    def _add_mensual_page(self):
        if not self.datos.get('mensual'):
            return  # No agregar página si no hay datos
        self.pdf.add_page()
        self._add_header()
        
        self.pdf.set_font('Arial', 'B', 14)
        self.pdf.set_text_color(*COLORS['primary'])
        self.pdf.cell(0, 10, "Resumen Mensual", 0, 1)
        
        # El endpoint devuelve un dict {nombre_metrica: FilaMensual}
        # FilaMensual tiene .valores = {mes_int: valor}
        resumen_dict = self.datos.get('mensual', {})
        
        headers = ["Mes", "Solicitudes", "Ofertas", "A Tiempo", "Tarde", "En Espera", "Tiempo Promedio"]
        widths = [40, 35, 35, 35, 35, 35, 45]
        
        self._draw_table_header(headers, widths)
        
        # Determinar rango de meses basado en filtros
        start_date = self.filtros.fecha_inicio
        end_date = self.filtros.fecha_fin
        
        # Generar lista de meses (tuples year, month para orden)
        meses_a_procesar = []
        current = start_date.replace(day=1)
        while current <= end_date:
            meses_a_procesar.append(current.month)
            # Avanzar mes
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        # Eliminar duplicados y ordenar (si el rango es corto y mismo año)
        # Si cruza año, la lógica simple de meses 1-12 funciona si no distinguimos año en tabla
        # Asumiremos la lógica del frontend que muestra meses simples
        meses_sorted = sorted(list(set(meses_a_procesar)))
        
        meses_nombres = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 
                         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        
        # Helpers para extraer valor seguro
        def get_val(metrica, mes):
            fila = resumen_dict.get(metrica)
            if not fila: return 0
            # Si es objeto (desde service) o dict (desde json)
            valores = getattr(fila, 'valores', {})
            if isinstance(valores, dict):
                return valores.get(mes, 0)
            elif isinstance(valores, list): # Por si acaso
                return 0
            return valores.get(str(mes), 0) if isinstance(valores, dict) else 0

        for mes_num in meses_sorted:
            nombre_mes = meses_nombres[mes_num] if 1 <= mes_num <= 12 else str(mes_num)
            
            # Extraer métricas transponiendo
            solicitudes = get_val('solicitudes_recibidas', mes_num)
            ofertas = get_val('ofertas_generadas', mes_num)
            # Calcular a tiempo / tarde usando porcentajes y totales es impreciso si no tenemos los absolutos
            # Pero el service devuelve 'entregas_a_tiempo'?? No, devuelve porcentajes en 'porcentaje_en_plazo'
            # Revisando service: devuelve 'porcentaje_en_plazo' y 'porcentaje_fuera_plazo'.
            # NO devuelve absolutos de entregas por mes en el resumen, solo porcentajes y totales base.
            # Espera, get_resumen_mensual calcula porcentajes y los guarda.
            # Filas disponibles: solicitudes_recibidas, ofertas_generadas, porcentaje_en_plazo, porcentaje_fuera_plazo...
            
            # Vamos a mostrar lo que tenemos. Si faltan absolutos de entregas, usamos porcentajes.
            pct_tiempo = get_val('porcentaje_en_plazo', mes_num)
            pct_tarde = get_val('porcentaje_fuera_plazo', mes_num)
            en_espera = get_val('en_espera', mes_num)
            tiempo = get_val('tiempo_promedio', mes_num)
            
            row_data = [
                nombre_mes,
                str(solicitudes),
                str(ofertas),
                f"{pct_tiempo}%",
                f"{pct_tarde}%",
                str(en_espera),
                f"{tiempo} días"
            ]
            
            self._draw_table_row(row_data, widths)
            
        # Insertar gráfico mensual
        self.pdf.ln(10)
        self.pdf.set_font('Arial', 'B', 11)
        self.pdf.cell(0, 10, "Tendencia Mensual", 0, 1)
        self.insert_chart_image('mensual', 10, self.pdf.get_y(), 180, 70)
        # Footer automático via PDFConFooter

    def _add_motivos_page(self):
        if not self.chart_images.get('motivos'):
            return  # No agregar página si no hay gráfico de motivos
        self.pdf.add_page()
        self._add_header()
        
        self.pdf.set_font('Arial', 'B', 14)
        self.pdf.set_text_color(*COLORS['primary'])
        self.pdf.cell(0, 10, "Análisis de Motivos de Cierre", 0, 1)
        
        # Gráfico grande
        y_chart = self.pdf.get_y() + 5
        self.insert_chart_image('motivos', 40, y_chart, 200, 100)
        
        # Tabla explicativa o leyenda si fuera necesario
        # Por ahora solo la imagen capturada que ya incluye leyenda
        # Footer automático via PDFConFooter

    def _draw_table_header(self, headers, widths):
        self.pdf.set_fill_color(*COLORS['primary'])
        self.pdf.set_text_color(255, 255, 255)
        self.pdf.set_font('Arial', 'B', 9)
        for i, h in enumerate(headers):
            self.pdf.cell(widths[i], 8, h, 1, 0, 'C', True)
        self.pdf.ln()
        self.pdf.set_text_color(*COLORS['text'])

    def _draw_table_row(self, data, widths):
        self.pdf.set_font('Arial', '', 9)
        # zebra striping logic could go here
        for i, d in enumerate(data):
            self.pdf.cell(widths[i], 8, str(d), 1, 0, 'C' if i > 0 else 'L')
        self.pdf.ln()

    def generate(self) -> bytes:
        """Orquesta la generación de todas las páginas"""
        try:
            logger.info("Generando página KPIs...")
            self._add_kpis_page()
            
            logger.info("Generando página Tecnología...")
            self._add_tecnologia_page()
            
            logger.info("Generando página Contabilización...")
            self._add_contabilizacion_page()
            
            logger.info("Generando páginas Usuarios...")
            self._add_usuarios_pages()
            
            logger.info("Generando página Mensual...")
            self._add_mensual_page()
            
            logger.info("Generando página Motivos...")
            self._add_motivos_page()
            
            logger.info("PDF generado exitosamente")
        except Exception as e:
            logger.error(f"Error generando PDF: {e}", exc_info=True)
            raise
        
        # Output to buffer (FPDF 1.7.2 supports returning string, needs encoding to bytes)
        # Or output(dest='S') returns string.
        # En Python 3, FPDF 1.7.2 output('S') returns a latin-1 string representing bytes (si es pyfpdf antiguo)
        # o bytearray si es fpdf2 o version modificada.
        # El error indica que es un bytearray, por lo que devolvemos directo.
        
        try:
            return self.pdf.output(dest='S')
        except Exception as e:
            # Fallback seguro
            out = self.pdf.output(dest='S')
            if isinstance(out, str):
                return out.encode('latin-1')
            return out
