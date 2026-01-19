import io
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from fpdf import FPDF
from datetime import datetime
from tempfile import NamedTemporaryFile
from uuid import UUID

# Configuración de Estilo Corporativo
ESTILO = {
    "primary": (18, 52, 86),      # Azul Oscuro #123456
    "accent": (0, 186, 187),      # Cyan/Teal #00BABB
    "white": (255, 255, 255),
    "light_grey": (241, 245, 249),# Slate 100
    "grey_text": (100, 116, 139), # Slate 500
    "success": (34, 197, 94),     # Green 500
    "warning": (249, 115, 22),    # Orange 500
    "danger": (239, 68, 68),      # Red 500
    "highlight": (224, 247, 250)  # Cyan 50
}

class AdvancedPDF(FPDF):
    def header(self):
        # Fondo del Header
        self.set_fill_color(*ESTILO["primary"])
        self.rect(0, 0, 297, 25, 'F') # A4 Landscape width is 297mm
        
        # Título
        self.set_text_color(255, 255, 255)
        self.set_font('Arial', 'B', 20)
        self.set_xy(10, 8)
        self.cell(0, 10, 'Reporte de Operaciones y Métricas de Simulación', 0, 0, 'L')
        
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Página {self.page_no()}/{{nb}} | Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")}', 0, 0, 'C')

class SimulacionReportService:
    def __init__(self):
        pass

    async def get_report_bytes(self, conn, start_date, end_date):
        # 1. Extracción de Datos Profunda
        query = """
            SELECT 
                o.*,
                eg.nombre as estatus_nombre, 
                eg.cuenta_para_kpi,
                eg.modulo_aplicable,
                t.nombre as tecnologia_nombre,
                ts.nombre as tipo_solicitud_nombre,
                ts.es_seguimiento,
                u.nombre as responsable_nombre,
                u.email as responsable_email,
                mc.motivo as motivo_cierre_nombre,
                sol.nombre as solicitante_extra_nombre
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global eg ON o.id_estatus_global = eg.id
            LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            LEFT JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            LEFT JOIN tb_usuarios u ON o.responsable_simulacion_id = u.id_usuario
            LEFT JOIN tb_cat_motivos_cierre mc ON o.id_motivo_cierre = mc.id
            LEFT JOIN tb_usuarios sol ON o.solicitado_por_id = sol.id_usuario
            WHERE o.fecha_solicitud::date BETWEEN $1 AND $2
        """
        rows = await conn.fetch(query, start_date, end_date)
        
        if not rows:
            return None # O manejar con PDF vacio

        # 2. Preprocesamiento con Pandas
        df = pd.DataFrame([dict(r) for r in rows])
        
        # Conversión de Tipos y Columnas Derivadas
        df['fecha_rs'] = pd.to_datetime(df['fecha_solicitud'])
        df['fecha_entrega_rs'] = pd.to_datetime(df['fecha_entrega_simulacion'], errors='coerce')
        df['mes'] = df['fecha_rs'].dt.month
        df['mes_nombre'] = df['fecha_rs'].dt.strftime('%b')
        
        # Lógica Multisitio (Peso)
        df['peso'] = pd.to_numeric(df['cantidad_sitios'], errors='coerce').fillna(1)
        
        # Lógica de Plazos (KPI Flag: cuenta_para_kpi)
        # kpi_status_compromiso: 'Entrega a tiempo', 'Entrega tarde' (Strings exactos de BD)
        df['es_a_tiempo'] = df['kpi_status_compromiso'].astype(str).str.lower().str.contains('tiempo').fillna(False)
        df['es_tarde'] = df['kpi_status_compromiso'].astype(str).str.lower().str.contains('tarde').fillna(False)
        
        # Clasificaciones Booleanas
        df['es_licitacion'] = df['es_licitacion'].fillna(False)
        df['es_retrabajo'] = df['parent_id'].notna()
        df['es_extraordinario'] = df['clasificacion_solicitud'] == 'EXTRAORDINARIO'
        df['es_cancelada'] = df['id_motivo_cierre'].notna()  # Asumiendo que motivo cierre implica perdida/cancelacion
        df['es_entregada'] = df['cuenta_para_kpi'].fillna(False)
        
        # 3. Generación de PDF
        pdf = AdvancedPDF(orientation='L', unit='mm', format='A4')
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # --- PAGINA 1: DASHBOARD EJECUTIVO ---
        pdf.add_page()
        self._render_dashboard(pdf, df, start_date, end_date)
        
        # --- PAGINA 2: DESGLOSE POR TECNOLOGIA ---
        pdf.add_page()
        self._render_technology_section(pdf, df)
        
        # --- PAGINA 3: DESGLOSE POR TIPO DE SOLICITUD ---
        pdf.add_page()
        self._render_request_type_section(pdf, df)
        
        # --- PAGINA 4: DESEMPEÑO POR RESPONSABLE ---
        pdf.add_page()
        self._render_user_performance(pdf, df)
        
        # --- PAGINA 5: SABANA ANUAL (Resumen Mensual) ---
        pdf.add_page()
        self._render_yearly_summary(pdf, df)

        return pdf.output()

    # ================= RENDERING METHODS =================

    def _render_dashboard(self, pdf, df, start, end):
        self._title(pdf, f"Dashboard Ejecutivo ({start} - {end})")
        
        # KPI CALCULATIONS
        total_recibidas = df['peso'].sum()
        total_entregadas = df[df['es_entregada']]['peso'].sum()
        
        # KPI: % Cumplimiento (Sobre Entregadas)
        if total_entregadas > 0:
            total_a_tiempo = df[df['es_entregada'] & df['es_a_tiempo']]['peso'].sum()
            pct_cumplimiento = (total_a_tiempo / total_entregadas) * 100
        else:
            pct_cumplimiento = 0.0
            
        avg_time = df[df['es_entregada']]['tiempo_elaboracion_horas'].mean()
        avg_time = avg_time if not pd.isna(avg_time) else 0.0

        sol_espera = df[(~df['es_entregada']) & (~df['es_cancelada'])]['peso'].sum()
        sol_canceladas = df[df['es_cancelada']]['peso'].sum()
        sol_extra = df[df['es_extraordinario']]['peso'].sum()
        sol_retrabajo = df[df['es_retrabajo']]['peso'].sum()
        
        # CARD ROW
        y_cards = 35  # Subí un poco para dar espacio
        card_w = 45
        spacing = 10
        self._draw_kpi_card(pdf, 10, y_cards, card_w, "Recibidas", int(total_recibidas), icon="IN")
        self._draw_kpi_card(pdf, 10 + card_w + spacing, y_cards, card_w, "Ofertas Generadas", int(total_entregadas), icon="OUT")
        self._draw_kpi_card(pdf, 10 + (card_w + spacing)*2, y_cards, card_w, "% Cumplimiento", f"{pct_cumplimiento:.1f}%", 
                            color_logic=pct_cumplimiento)
        self._draw_kpi_card(pdf, 10 + (card_w + spacing)*3, y_cards, card_w, "Tiempo Prom. (Hrs)", f"{avg_time:.1f}")
        self._draw_kpi_card(pdf, 10 + (card_w + spacing)*4, y_cards, card_w, "Extraordinarias", int(sol_extra), is_alert=True if sol_extra > 0 else False)

        # CHART ROW (Matplotlib) - Ajuste de posición para evitar overlap
        y_charts = 75 
        chart_h = 65 # Altura fija controlada
        
        # 1. Pie Chart: Estatus Global
        status_counts = df.groupby('estatus_nombre')['peso'].sum()
        # Filtrar estatus con 0 para limpiar gráfica
        status_counts = status_counts[status_counts > 0]
        
        img1 = self._create_pie_chart(status_counts, "Distribución por Estatus")
        pdf.image(img1, x=10, y=y_charts, w=85, h=chart_h)
        os.unlink(img1)
        
        # 2. Bar Chart: Monthly Volume
        monthly_counts = df.groupby('mes')['peso'].sum()
        img2 = self._create_bar_chart(monthly_counts, "Volumen Mensual de Solicitudes", df['mes_nombre'].unique()) 
        # Nota: mes_nombre unique podría no estar ordenado correcto si no lo tratamos, pero simplifiquemos.
        # Mejor pasar el index (num mes) y mapear labels si es necesario, o dejar que bar chart lo maneje.
        
        pdf.image(img2, x=105, y=y_charts, w=90, h=chart_h)
        os.unlink(img2)
        
        # 3. Donut Chart: Delivery Performance
        on_time_count = df[df['es_entregada'] & df['es_a_tiempo']]['peso'].sum()
        late_count = df[df['es_entregada'] & df['es_tarde']]['peso'].sum()
        
        if on_time_count + late_count > 0:
            img3 = self._create_donut_chart([on_time_count, late_count], ["A Tiempo", "Tarde"], ["#00BABB", "#EF4444"], "Eficiencia Entrega")
            pdf.image(img3, x=205, y=y_charts, w=80, h=chart_h)
            os.unlink(img3)

        # SUMMARY TEXT - Movido más abajo para evitar overlap
        y_text = y_charts + chart_h + 10 # 75 + 65 + 10 = 150
        pdf.set_y(y_text)
        pdf.set_font('Arial', '', 10)
        pdf.set_text_color(0,0,0)
        
        # Metrics list logic
        metrics_text = [
            f"Solicitudes en espera: {int(sol_espera)}",
            f"Solicitudes canceladas/no viables: {int(sol_canceladas)}",
            f"Solicitudes retrabajadas (Versiones): {int(sol_retrabajo)}",
            f"Potencia FV Total (Cierre): {df['potencia_cierre_fv_kwp'].sum():,.2f} kWp",
            f"Capacidad BESS Total (Cierre): {df['capacidad_cierre_bess_kwh'].sum():,.2f} kWh"
        ]
        
        pdf.set_x(10)
        pdf.set_font('Arial','B',12)
        pdf.cell(0, 10, "Métricas Adicionales", 0, 1)
        pdf.set_font('Arial','',10)
        for m in metrics_text:
            pdf.cell(10)
            pdf.cell(0, 6, chr(149) + " " + m, 0, 1)

    # ... (Rest of layouts unchanged unless specific overlap reported) ...
    # Re-inserting other render methods to ensure file consistency if replace block is large.
    # Actually, to be safe and efficient, I will keep the other render methods as is if they weren't the problem.
    # But user said "desafses", implying general layout check.
    # I'll include user_performance and technology just to be sure table headers don't conflict.

    def _render_technology_section(self, pdf, df):
        self._title(pdf, "Desglose por Tecnología")
        tech_groups = df.groupby('tecnologia_nombre')
        data = []
        for name, group in tech_groups:
            total = group['peso'].sum()
            ofertas = group[group['es_entregada']]['peso'].sum()
            tiempo_prom = group[group['es_entregada']]['tiempo_elaboracion_horas'].mean()
            entregadas_group = group[group['es_entregada']]
            if len(entregadas_group) > 0:
                pct_ok = (len(entregadas_group[entregadas_group['es_a_tiempo']]) / len(entregadas_group)) * 100
                pct_late = (len(entregadas_group[entregadas_group['es_tarde']]) / len(entregadas_group)) * 100
            else:
                pct_ok = 0; pct_late = 0
            extra = group[group['es_extraordinario']]['peso'].sum()
            retrabajo = group[group['es_retrabajo']]['peso'].sum()
            data.append([name, int(total), int(ofertas), f"{tiempo_prom:.1f} h" if not pd.isna(tiempo_prom) else "-", f"{pct_ok:.1f}%", f"{pct_late:.1f}%", int(extra), int(retrabajo)])
            
        columns = ["Tecnología", "Solicitudes", "Ofertas", "T. Promedio", "% A Tiempo", "% Tarde", "Extra", "Retrabajos"]
        self._draw_table(pdf, columns, data, col_widths=[50, 25, 25, 30, 30, 30, 25, 30])
        
        # Loss Analysis
        pdf.ln(10)
        # Check page break
        if pdf.get_y() > 170: pdf.add_page(); self._title(pdf, "Análisis de Motivos de Cierre (Cont.)")
        
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, "Análisis de Motivos de Cierre / Pérdida", 0, 1)
        loss_groups = df[df['id_motivo_cierre'].notna()].groupby('motivo_cierre_nombre')['peso'].sum().sort_values(ascending=False)
        if not loss_groups.empty:
            loss_data = [[m, int(c)] for m, c in loss_groups.items()]
            self._draw_table(pdf, ["Motivo", "Cantidad"], loss_data, col_widths=[150, 30])

    def _render_request_type_section(self, pdf, df):
        self._title(pdf, "Contabilización por Tipo de Solicitud (Semaforización)")
        types = df['tipo_solicitud_nombre'].dropna().unique().tolist()
        types.sort()
        data = []
        for t in types:
            g = df[df['tipo_solicitud_nombre'] == t]
            data.append(self._calc_semaphore_row(t, g))
        licitaciones = df[df['es_licitacion']]
        if not licitaciones.empty:
            data.append(self._calc_semaphore_row("LICITACIONES (Transversal)", licitaciones))
        columns = ["Tipo Solicitud", "Total", "A Tiempo", "Tarde", "Sin Fecha", "Cumplimiento"]
        self._draw_table(pdf, columns, data, col_widths=[80, 25, 25, 25, 25, 40], color_column_idx=5)

    def _calc_semaphore_row(self, label, group):
        total = group['peso'].sum()
        entregadas = group[group['es_entregada']]
        a_tiempo = entregadas[entregadas['es_a_tiempo']]['peso'].sum()
        tarde = entregadas[entregadas['es_tarde']]['peso'].sum()
        sin_fecha = group[~group['es_entregada']]['peso'].sum()
        total_ent_count = entregadas['peso'].sum()
        pct = (a_tiempo / total_ent_count * 100) if total_ent_count > 0 else 0.0
        return [label, int(total), int(a_tiempo), int(tarde), int(sin_fecha), pct]

    def _render_user_performance(self, pdf, df):
        self._title(pdf, "Desempeño Individual por Responsable")
        users = df[df['responsable_nombre'].notna()]['responsable_nombre'].unique()
        users.sort()
        data = []
        for u in users:
            g = df[df['responsable_nombre'] == u]
            total = g['peso'].sum()
            ofertas = g[g['es_entregada']]['peso'].sum()
            entregadas = g[g['es_entregada']]
            if not entregadas.empty:
                t_prom = entregadas['tiempo_elaboracion_horas'].mean()
                pct_ok = (entregadas[entregadas['es_a_tiempo']]['peso'].sum() / entregadas['peso'].sum()) * 100
                pct_late = (entregadas[entregadas['es_tarde']]['peso'].sum() / entregadas['peso'].sum()) * 100
            else:
                t_prom = 0; pct_ok = 0; pct_late = 0
            espera = g[(~g['es_entregada']) & (~g['es_cancelada'])]['peso'].sum()
            extra = g[g['es_extraordinario']]['peso'].sum()
            data.append([u, int(total), int(ofertas), f"{t_prom:.1f} h", f"{pct_ok:.1f}%", f"{pct_late:.1f}%", int(espera), int(extra)])
        cols = ["Responsable", "Recibidas", "Ofertas", "T. Prom", "% OK", "% Tarde", "Espera", "Extra"]
        self._draw_table(pdf, cols, data, col_widths=[60, 20, 20, 25, 20, 20, 20, 20])
        
        pdf.ln(10)
        self._subtitle(pdf, "Auditoría de Solicitudes Extraordinarias")
        extras_df = df[df['es_extraordinario']]
        if not extras_df.empty:
            extra_data = []
            for _, row in extras_df.iterrows():
                try:
                    p_name = row['nombre_proyecto'][:30] if row['nombre_proyecto'] else "S/N"
                    sol_by = row['solicitante_extra_nombre'] if pd.notna(row.get('solicitante_extra_nombre')) else "N/A"
                    # Si no existe la columna en el DF (por error de join), fallback
                    # Pero en query pusimos 'sol.nombre as solicitante_extra_nombre'
                except:
                    p_name = "Err"; sol_by = "Err"
                    
                extra_data.append([
                    str(row['op_id_estandar']),
                    str(p_name),
                    str(sol_by),
                    str(row['responsable_nombre'] or "N/A")
                ])
            self._draw_table(pdf, ["ID Ref", "Proyecto", "Solicitado Por", "Asignado A"], extra_data, col_widths=[40, 80, 60, 60])

    def _render_yearly_summary(self, pdf, df):
        self._title(pdf, "Resumen Anual (Sábana Operativa)")
        months = range(1, 13)
        month_labels = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
        row_defs = [
            ("Solicitudes Recibidas", lambda d: d['peso'].sum(), False),
            ("Ofertas Generadas", lambda d: d[d['es_entregada']]['peso'].sum(), False),
            ("% Entregas en plazo", lambda d: self._safe_pct(d[d['es_entregada'] & d['es_a_tiempo']]['peso'].sum(), d[d['es_entregada']]['peso'].sum()), True),
            ("% Entregas fuera plazo", lambda d: self._safe_pct(d[d['es_entregada'] & d['es_tarde']]['peso'].sum(), d[d['es_entregada']]['peso'].sum(), is_late=True), False),
            ("Solicitudes Extraordinarias", lambda d: d[d['es_extraordinario']]['peso'].sum(), False)
        ]
        col_w_label = 55; col_w_month = 18
        pdf.set_font('Arial','B',8)
        pdf.set_fill_color(*ESTILO["primary"])
        pdf.set_text_color(255,255,255)
        pdf.cell(col_w_label, 8, "Métrica General", 1, 0, 'L', True)
        for m in month_labels: pdf.cell(col_w_month, 8, m, 1, 0, 'C', True)
        pdf.ln()
        pdf.set_text_color(0,0,0)
        pdf.set_font('Arial','',8)
        for label, func, is_pct in row_defs:
            pdf.cell(col_w_label, 6, label, 1)
            for m in months:
                m_df = df[df['mes'] == m]
                val = func(m_df)
                if is_pct:
                    txt = f"{val:.0f}%"
                    fill = False
                    if label == "% Entregas en plazo":
                        if val >= 90: pdf.set_fill_color(*ESTILO["success"])
                        elif val >= 85: pdf.set_fill_color(*ESTILO["warning"])
                        else: pdf.set_fill_color(*ESTILO["danger"])
                        if not(m_df.empty or m_df[m_df['es_entregada']].empty): fill = True
                    pdf.cell(col_w_month, 6, txt, 1, 0, 'C', fill)
                    pdf.set_fill_color(255,255,255)
                else:
                    pdf.cell(col_w_month, 6, str(int(val)), 1, 0, 'C')
            pdf.ln()

    # ================= HELPER METHODS =================

    def _title(self, pdf, text):
        pdf.set_font('Arial', 'B', 16)
        pdf.set_text_color(*ESTILO["primary"])
        pdf.cell(0, 10, text, 0, 1, 'L')
        pdf.set_draw_color(*ESTILO["accent"])
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

    def _subtitle(self, pdf, text):
        pdf.set_font('Arial', 'B', 12)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 8, text, 0, 1, 'L')

    def _draw_kpi_card(self, pdf, x, y, w, label, value, icon=None, color_logic=None, is_alert=False):
        # Shadow/Border
        pdf.set_xy(x, y)
        pdf.set_fill_color(255, 255, 255)
        if is_alert:
            pdf.set_draw_color(*ESTILO["danger"])
            pdf.set_line_width(0.5)
        else:
            pdf.set_draw_color(200, 200, 200)
            pdf.set_line_width(0.2)
            
        pdf.rect(x, y, w, 25, 'DF')
        
        # Label
        pdf.set_xy(x, y+2)
        pdf.set_font('Arial', '', 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(w, 5, label, 0, 1, 'C')
        
        # Value
        pdf.set_xy(x, y+10)
        pdf.set_font('Arial', 'B', 16)
        
        # Color Logic for Value
        if color_logic is not None:
             # Assuming Semaphore
             if isinstance(color_logic, (int, float)):
                 if color_logic >= 90: pdf.set_text_color(*ESTILO["success"])
                 elif color_logic >= 85: pdf.set_text_color(*ESTILO["warning"])
                 else: pdf.set_text_color(*ESTILO["danger"])
        else:
            pdf.set_text_color(*ESTILO["primary"])
            
        pdf.cell(w, 8, str(value), 0, 1, 'C')

    def _draw_table(self, pdf, columns, data, col_widths=None, color_column_idx=None):
        if not col_widths:
            col_widths = [190 / len(columns)] * len(columns)
            
        # Header
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(*ESTILO["primary"])
        pdf.set_text_color(255, 255, 255)
        
        for i, col in enumerate(columns):
            pdf.cell(col_widths[i], 8, col, 1, 0, 'C', True)
        pdf.ln()
        
        # Rows
        pdf.set_font('Arial', '', 9)
        pdf.set_text_color(0, 0, 0)
        
        for row in data:
            for i, val in enumerate(row):
                # Special Color Handling (Semaphore)
                fill = False
                reset_text = False
                
                if color_column_idx is not None and i == color_column_idx:
                    # Expecting numeric value for semaphore or tuple
                    if isinstance(val, (int, float)):
                        numeric_val = val
                        txt_val = f"{val:.1f}%"
                        fill = True
                        if numeric_val >= 90: pdf.set_fill_color(*ESTILO["success"])
                        elif numeric_val >= 85: pdf.set_fill_color(*ESTILO["warning"])
                        else: pdf.set_fill_color(*ESTILO["danger"])
                        pdf.set_text_color(255,255,255)
                        reset_text = True
                        val = txt_val # Show formatted percentage
                
                pdf.cell(col_widths[i], 8, str(val), 1, 0, 'C', fill)
                
                if reset_text:
                    pdf.set_text_color(0,0,0)
                    pdf.set_fill_color(255,255,255)

            pdf.ln()

    def _safe_pct(self, num, den, is_late=False):
        if den == 0: return 0.0
        return (num / den) * 100

    # ================= CHART GENERATION (UPDATED FOR HIGH FIDELITY) =================
    # Colores Chart.js (Dashboard Web) like:
    # Turquoise (#00BABB), DarkBlue (#123456), Green (#22c55e), Orange (#f97316), Purple (#a855f7)
    
    def _create_pie_chart(self, series, title):
        plt.style.use('seaborn-v0_8-white')
        plt.figure(figsize=(5, 4))
        
        colors = ['#00BABB', '#123456', '#22c55e', '#f97316', '#a855f7'] # Corporate List
        
        if series.empty:
            plt.text(0.5, 0.5, "Sin Datos", ha='center', va='center', color='#9ca3af')
            plt.axis('off')
        else:
            # Sort for consistency
            series = series.sort_values(ascending=False)
            
            wedges, texts, autotexts = plt.pie(
                series, 
                labels=series.index, 
                autopct='%1.1f%%', 
                startangle=90, 
                colors=colors[:len(series)],
                textprops={'fontsize': 9, 'color': '#374151'},
                wedgeprops={'linewidth': 1, 'edgecolor': 'white'}
            )
            plt.setp(autotexts, size=8, weight="bold", color="white")
        
        plt.title(title, fontsize=11, fontweight='bold', color='#374151', pad=15)
        
        tmp = NamedTemporaryFile(delete=False, suffix=".png")
        plt.savefig(tmp.name, bbox_inches='tight', dpi=150) # Higher DPI
        plt.close()
        return tmp.name

    def _create_bar_chart(self, series, title, x_labels=None):
        plt.style.use('seaborn-v0_8-white')
        fig, ax = plt.subplots(figsize=(6, 4))
        
        if series.empty:
            ax.text(0.5, 0.5, "Sin Datos", ha='center', va='center', color='#9ca3af')
            ax.axis('off')
        else:
            # Bar Styling
            # Ensure full 12 months present or just show what we have? User said "monthly volume"
            # It's better to show existing data on clean bars
            
            bars = ax.bar(series.index, series.values, color='#00BABB', width=0.6, edgecolor='none')
            
            # Remove spines
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_visible(False)
            ax.spines['bottom'].set_color('#e5e7eb')
            
            # Horizontal Grid only
            ax.grid(axis='y', linestyle='-', alpha=0.5, color='#f3f4f6')
            ax.set_axisbelow(True)
            
            # Labels and Ticks
            ax.tick_params(axis='y', colors='#6b7280', labelsize=8)
            ax.tick_params(axis='x', colors='#6b7280', labelsize=8)
            
            # Bar Labels
            ax.bar_label(bars, padding=3, color='#123456', fontweight='bold', fontsize=9)
            
        plt.title(title, fontsize=11, fontweight='bold', color='#374151', pad=15)
        
        tmp = NamedTemporaryFile(delete=False, suffix=".png")
        plt.savefig(tmp.name, bbox_inches='tight', dpi=150)
        plt.close()
        return tmp.name

    def _create_donut_chart(self, values, labels, colors, title):
        plt.style.use('seaborn-v0_8-white')
        fig, ax = plt.subplots(figsize=(5, 4))
        
        total = sum(values)
        if total == 0:
            ax.text(0.5, 0.5, "Sin Datos", ha='center', va='center')
            ax.axis('off')
        else:
            wedges, texts, autotexts = ax.pie(
                values, 
                labels=labels, 
                colors=colors, 
                autopct='%1.1f%%', 
                pctdistance=0.75, 
                startangle=90,
                wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2),
                textprops={'fontsize': 9, 'color': '#374151'}
            )
            plt.setp(autotexts, size=8, weight="bold", color="white")
            
            # Center Text (Total)
            ax.text(0, 0, f"{int(total)}", ha='center', va='center', fontsize=20, fontweight='bold', color='#123456')
            
            # Legend
            ax.legend(wedges, labels, title="", loc="lower center", bbox_to_anchor=(0.5, -0.1), ncol=2, frameon=False)
            
        plt.title(title, fontsize=11, fontweight='bold', color='#374151', pad=15)
        
        tmp = NamedTemporaryFile(delete=False, suffix=".png")
        plt.savefig(tmp.name, bbox_inches='tight', dpi=150)
        plt.close()
        return tmp.name


def get_report_service():
    return SimulacionReportService()
