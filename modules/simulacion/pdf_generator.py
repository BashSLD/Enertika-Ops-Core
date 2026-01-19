from fpdf import FPDF
from datetime import datetime
import io
import base64
from typing import Dict, Any

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

class ReportePDFGenerator:
    def __init__(self, filtros: Any, datos: Dict[str, Any], chart_images: Dict[str, str]):
        self.pdf = FPDF(orientation='L', unit='mm', format='Letter')
        self.filtros = filtros
        self.datos = datos
        self.chart_images = chart_images
        
        self.pdf.set_margins(10, 10, 10)
        self.pdf.set_auto_page_break(auto=True, margin=15)
        
        # Metadata
        self.pdf.set_title(f"Reporte Simulación {filtros.fecha_inicio} - {filtros.fecha_fin}")
        self.pdf.set_author("Enertika Ops Core")
        
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

    def _add_footer(self):
        self.pdf.set_y(-15)
        self.pdf.set_font('Arial', 'I', 8)
        self.pdf.set_text_color(128, 128, 128)
        fecha_gen = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.pdf.cell(0, 10, f'Generado el: {fecha_gen} | Página {self.pdf.page_no()}', 0, 0, 'C')

    def insert_chart_image(self, chart_key: str, x: int, y: int, w: int, h: int = 0):
        """Decodifica base64 y dibuja la imagen"""
        if chart_key not in self.chart_images:
            return

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

        self._add_footer()

    def _add_tecnologia_page(self):
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
        
        self._add_footer()

    def _add_contabilizacion_page(self):
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
                self.pdf.circle(cx, cy, r, 'F')
                
                # Reset fill color
                self.pdf.set_fill_color(255, 255, 255)
        
        self._add_footer()

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
        self._add_kpis_page()
        self._add_tecnologia_page()
        self._add_contabilizacion_page()
        
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
