import flet as ft
from core.database import db
from core.microsoft import MicrosoftAuth 
from datetime import datetime, timedelta, time as dt_time
import pandas as pd
import os
import time
import uuid

# Configuración de entorno
os.environ["FLET_SECRET_KEY"] = os.getenv("FLET_SECRET_KEY", "Clave_Secreta_Dev_123")

# --- CONSTANTES ---
USUARIO_ACTUAL = "SEBASTIAN_LEOCADIO"
ES_GERENTE = True 
CORREO_DESTINO_SIMULACION = ["sistemas@enertika.mx"] 
COLOR_PRIMARIO = "#123456"
COLOR_TURQUESA = "#00BABB"
LIMITE_MB = 35
LIMITE_BYTES = LIMITE_MB * 1024 * 1024 

def ViewComercial(page: ft.Page):
    print("Inicializando vista Comercial...") 
    
    # --- ESTADO DE LA APLICACIÓN ---
    # Centralizamos todo el estado mutable aquí para evitar variables globales dispersas
    state = {
        # Flujo Principal
        "paso_actual": 1,
        "id_oportunidad_guardada": None, 
        
        # Gestión de Archivos y Excel
        "archivos_seleccionados": [], 
        "df_sitios": None,
        "excel_file_obj": None,
        "upload_dir": os.path.join(os.getcwd(), "assets"),
        "temp_excel_name": None, # Rastreo del archivo temporal subido
        
        # Gestión de Fechas y UI
        "editando_fecha": None,
        "fecha_inicio_personalizada": None,
        "fecha_fin_personalizada": None,
        "update_fechas_ui": None, # Hook para refrescar componentes UI
        
        # Datos Maestros
        "data_completa": [],
        "id_correo_original": None
    }

    ms_auth = MicrosoftAuth()
    
    # Asegurar existencia de directorio de uploads (Assets)
    if not os.path.exists(state["upload_dir"]):
        os.makedirs(state["upload_dir"], exist_ok=True)

    # --- LÓGICA DE CARGA DE EXCEL ---

    def leer_datos_excel_logica(ruta_excel, archivo_obj):
        """
        Fase 3: Procesamiento
        Lee el archivo físico (ya sea local o subido a assets), valida reglas de negocio y limpia.
        """
        try:
            print(f"📖 Procesando Excel: {ruta_excel}")
            
            # Carga agnóstica (Excel o CSV)
            if archivo_obj.name.lower().endswith('.csv'): 
                df = pd.read_csv(ruta_excel)
            else: 
                df = pd.read_excel(ruta_excel)
            
            # 1. Normalización
            df.columns = [str(c).strip().upper() for c in df.columns]
            cols_req = ["NOMBRE", "DIRECCION"]
            
            # 2. Validación de Estructura
            errores = None
            if not all(col in df.columns for col in cols_req):
                 errores = "El archivo no tiene las columnas requeridas (NOMBRE, DIRECCION)."
            
            # 3. Validación de Negocio
            if not errores:
                try:
                    cant_declarada = int(tf_cantidad_sitios.value) if tf_cantidad_sitios.value else 1
                    if len(df) != cant_declarada:
                        errores = f"Declaraste {cant_declarada} sitios, pero el archivo contiene {len(df)} filas."
                except:
                    errores = "La cantidad de sitios declarada no es un número válido."

            # 4. Resultado
            if errores:
                state["df_sitios"] = None
                state["excel_file_obj"] = None
                tabla_preview.rows.clear()
                page.open(ft.SnackBar(ft.Text(f"⛔ {errores}"), bgcolor="red"))
            else:
                state["df_sitios"] = df
                state["excel_file_obj"] = archivo_obj
                
                # Actualizar Preview (Solo primeros 5)
                tabla_preview.rows.clear()
                for _, row in df.head(5).iterrows():
                    tabla_preview.rows.append(ft.DataRow(cells=[
                        ft.DataCell(ft.Text(str(row.get("NOMBRE", ""))[:20])),
                        ft.DataCell(ft.Text(str(row.get("DIRECCION", ""))[:30]))
                    ]))
                page.open(ft.SnackBar(ft.Text(f"✅ Carga exitosa: {len(df)} sitios."), bgcolor="green"))

        except Exception as ex:
            state["df_sitios"] = None
            page.open(ft.SnackBar(ft.Text(f"❌ Error crítico leyendo archivo: {ex}"), bgcolor="red"))
        
        finally:
            # LIMPIEZA AUTOMÁTICA: Siempre borramos el archivo temporal de assets
            if os.path.exists(ruta_excel):
                try:
                    os.remove(ruta_excel)
                    print(f"🗑️ Archivo temporal eliminado: {ruta_excel}")
                except Exception as e:
                    print(f"⚠️ No se pudo borrar temporal: {e}")
            
            # Restaurar UI
            page.update()

    def on_upload_excel_completed(e):
        """
        Fase 2: Confirmación de Subida (Solo Web)
        Implementa lógica de 'Puerta Cerrada' para evitar errores por eventos múltiples.
        """
        # 1. CONSUMO INMEDIATO (Atomicidad)
        # Leemos y borramos la referencia AL INSTANTE.
        # Si llega un segundo evento milisegundos después, encontrará None y rebotará.
        nombre_esperado = state["temp_excel_name"]
        state["temp_excel_name"] = None 

        if not nombre_esperado: 
            # Si llegamos aquí, es un evento duplicado (eco). 
            # No hacemos nada, no imprimimos error, no tocamos la UI.
            return

        try:
            ruta_final = os.path.join(state["upload_dir"], nombre_esperado)
            print(f"☁️ Upload detectado. Procesando único: {ruta_final}")
            
            # Pequeña espera de cortesía (por si el disco es mecánico o de red lenta)
            if not os.path.exists(ruta_final):
                time.sleep(0.5)
            
            if os.path.exists(ruta_final):
                leer_datos_excel_logica(ruta_final, state["excel_file_obj"])
            else:
                print("❌ ERROR REAL: El archivo no apareció en disco.")
                page.open(ft.SnackBar(ft.Text("Error de IO: El archivo no se guardó."), bgcolor="red"))
                page.update()
        
        except Exception as ex:
            print(f"❌ Error en callback upload: {ex}")
            page.open(ft.SnackBar(ft.Text(f"Error procesando: {ex}"), bgcolor="red"))
            page.update()
        
        finally:
            # Solo el hilo "ganador" (el que tenía el nombre) desbloquea el botón
            btn_cargar_excel.disabled = False
            btn_cargar_excel.text = "2. Cargar Excel"
            page.update()

    def procesar_excel_sitios(e):
        """
        Fase 1: Inicio de Carga
        Maneja la selección del archivo y decide si leer local (Desktop) o subir (Web).
        """
        if not e.files: return

        # Evitar re-entradas (Doble click)
        if btn_cargar_excel.disabled: return
        
        btn_cargar_excel.disabled = True
        btn_cargar_excel.text = "Procesando..."
        page.update()
        
        try:
            archivo = e.files[0]
            
            # --- RUTA A: MODO WEB (Upload requerido) ---
            if archivo.path is None:
                # 1. Generar nombre seguro (UUID) para evitar colisiones
                ext = archivo.name.split('.')[-1]
                nombre_servidor = f"{uuid.uuid4().hex}.{ext}"
                
                # 2. Guardar estado para la Fase 2
                state["temp_excel_name"] = nombre_servidor
                state["excel_file_obj"] = archivo 
                
                # 3. Iniciar subida asíncrona
                upload_url = page.get_upload_url(nombre_servidor, 600)
                excel_picker.upload([
                    ft.FilePickerUploadFile(archivo.name, upload_url=upload_url)
                ])
                print(f"⬆️ Iniciando subida web: {nombre_servidor}")
            
            # --- RUTA B: MODO DESKTOP (Lectura directa) ---
            else:
                # Pasar directo a Fase 3
                leer_datos_excel_logica(archivo.path, archivo)
                btn_cargar_excel.disabled = False
                btn_cargar_excel.text = "2. Cargar Excel"
                page.update()

        except Exception as ex:
            print(f"Error inicio carga: {ex}")
            btn_cargar_excel.disabled = False
            btn_cargar_excel.text = "2. Cargar Excel"
            page.update()
    
    # --- DEFINICIÓN DE DIÁLOGOS (PICKERS) ---
    file_picker = ft.FilePicker(
        on_result=lambda e: agregar_archivos(e),
        on_upload=lambda e: print(f"Upload completado: {e.file_name}")
    )
    
    # Definición del Botón (Controlable)
    btn_cargar_excel = ft.ElevatedButton(
        "2. Cargar Excel", 
        icon=ft.Icons.UPLOAD_FILE, 
        bgcolor="green", 
        color="white"
    )

    # Definición del Picker
    excel_picker = ft.FilePicker(
        on_result=procesar_excel_sitios,       # Fase 1
        on_upload=on_upload_excel_completed    # Fase 2
    )
    
    # Asignación del evento
    btn_cargar_excel.on_click = lambda _: excel_picker.pick_files(allowed_extensions=["xlsx", "xls", "csv"])
    
    save_file_picker = ft.FilePicker(on_result=lambda e: guardar_plantilla(e))
    
    # DatePicker configurado para rango de fechas
    def on_date_change(e):
        """Procesa la fecha seleccionada según el tipo (inicio o fin)"""
        if state["editando_fecha"] == "inicio":
            state["fecha_inicio_personalizada"] = e.control.value
            print(f"Fecha inicio seleccionada: {e.control.value}")
        elif state["editando_fecha"] == "fin":
            state["fecha_fin_personalizada"] = e.control.value
            print(f"Fecha fin seleccionada: {e.control.value}")
        state["editando_fecha"] = None  # Reset
        
        # FIX 2 Step C: Disparar hook para actualizar UI
        if state["update_fechas_ui"]:
            state["update_fechas_ui"]()
        page.update()
    
    date_picker = ft.DatePicker(
        first_date=datetime(2023, 1, 1),
        last_date=datetime(2030, 12, 31),
        on_change=on_date_change
    )

    # IMPORTANTE: Registrar todos los diálogos en el overlay
    page.overlay.extend([file_picker, excel_picker, save_file_picker, date_picker])

    # --- LOGICA FECHAS ---
    def calcular_deadline():
        ahora = datetime.now()
        fecha_base = ahora.date()
        hora_actual = ahora.time()
        corte = dt_time(17, 30, 0)
        if hora_actual > corte: fecha_base += timedelta(days=1)
        dia_semana = fecha_base.weekday()
        if dia_semana == 5: fecha_base += timedelta(days=2) 
        elif dia_semana == 6: fecha_base += timedelta(days=1) 
        return fecha_base + timedelta(days=7)

    # --- UI PORTLETS (GRAFICOS Y METRICAS) ---
    def crear_portlets():
        
        # Funciones para seleccionar fechas de rango
        def seleccionar_fecha_inicio(e):
            state["editando_fecha"] = "inicio"
            page.open(date_picker)
            page.update()
        
        def seleccionar_fecha_fin(e):
            state["editando_fecha"] = "fin"
            page.open(date_picker)
            page.update()
        
        # Actualizar texto de botones cuando cambian las fechas
        def actualizar_texto_botones():
            if state["fecha_inicio_personalizada"]:
                btn_fecha_inicio.text = f"Inicio: {state['fecha_inicio_personalizada'].strftime('%d/%m/%Y')}"
            if state["fecha_fin_personalizada"]:
                btn_fecha_fin.text = f"Fin: {state['fecha_fin_personalizada'].strftime('%d/%m/%Y')}"
            
            # FIX 2: Actualizar texto de rango seleccionado con visibilidad
            if state["fecha_inicio_personalizada"] and state["fecha_fin_personalizada"]:
                txt_rango_seleccionado.value = f"Rango: {state['fecha_inicio_personalizada'].strftime('%d/%m/%Y')} al {state['fecha_fin_personalizada'].strftime('%d/%m/%Y')}"
                txt_rango_seleccionado.visible = True
            elif state["fecha_inicio_personalizada"]:
                txt_rango_seleccionado.value = f"Inicio seleccionado: {state['fecha_inicio_personalizada'].strftime('%d/%m/%Y')}"
                txt_rango_seleccionado.visible = True
            elif state["fecha_fin_personalizada"]:
                txt_rango_seleccionado.value = f"Fin seleccionado: {state['fecha_fin_personalizada'].strftime('%d/%m/%Y')}"
                txt_rango_seleccionado.visible = True
            else:
                txt_rango_seleccionado.value = "Ningún rango seleccionado"
                txt_rango_seleccionado.visible = False
            page.update()

        # FIX 3: Control de texto para mostrar rango seleccionado
        txt_rango_seleccionado = ft.Text("Ningún rango seleccionado", size=12, italic=True, color="grey", visible=False)

        btn_fecha_inicio = ft.ElevatedButton(
            "Fecha Inicio", 
            icon=ft.Icons.CALENDAR_TODAY, 
            visible=False,
            on_click=seleccionar_fecha_inicio
        )
        
        btn_fecha_fin = ft.ElevatedButton(
            "Fecha Fin", 
            icon=ft.Icons.EVENT, 
            visible=False,
            on_click=seleccionar_fecha_fin
        )

        def cambio_filtro_tiempo(e):
            val = e.control.value
            if val == "Personalizado":
                btn_fecha_inicio.visible = True
                btn_fecha_fin.visible = True
                txt_rango_seleccionado.visible = True
                # FIX 3: Llamar actualizar si ya hay fechas guardadas
                if state["fecha_inicio_personalizada"] or state["fecha_fin_personalizada"]:
                    actualizar_texto_botones()
            else:
                btn_fecha_inicio.visible = False
                btn_fecha_fin.visible = False
                txt_rango_seleccionado.visible = False
            page.update()

        # Filtros de tiempo visuales
        filtros = ft.Row([
            ft.Text("Métricas:", weight="bold", size=16, color=COLOR_PRIMARIO),
            ft.Container(expand=True), # Espaciador
            txt_rango_seleccionado,  # FIX 1: Único control de rango de fechas
            btn_fecha_inicio,
            btn_fecha_fin,
            ft.Dropdown(
                label="Periodo",
                options=[
                    ft.dropdown.Option("Semanal"),
                    ft.dropdown.Option("Mensual"),
                    ft.dropdown.Option("Trimestral"),
                    ft.dropdown.Option("Semestral"),
                    ft.dropdown.Option("Anual"),
                    ft.dropdown.Option("Personalizado")
                ],
                value="Semanal",
                width=150,
                text_size=12,
                content_padding=10,
                border_color=COLOR_PRIMARIO,
                on_change=cambio_filtro_tiempo
            ),
            ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Actualizar métricas", icon_size=20, icon_color=COLOR_PRIMARIO)
        ], alignment=ft.MainAxisAlignment.END)

        # KPIs Rápidos
        def kpi_card(titulo, valor, icon, color_bg):
            return ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Icon(icon, color="white", size=24),
                        padding=10, bgcolor=ft.Colors.with_opacity(0.2, "white"), border_radius=50
                    ),
                    ft.Column([
                        ft.Text(valor, size=22, weight="bold", color="white"),
                        ft.Text(titulo, size=11, color="white", weight="w500")
                    ], spacing=2, alignment=ft.MainAxisAlignment.CENTER)
                ], alignment=ft.MainAxisAlignment.START),
                bgcolor=color_bg, 
                width=190, height=80, border_radius=10, padding=10,
                shadow=ft.BoxShadow(blur_radius=5, color=ft.Colors.with_opacity(0.2, "black"))
            )

        row_kpis = ft.Row([
            kpi_card("Solicitudes Totales", "24", ft.Icons.FOLDER_OPEN, COLOR_TURQUESA),
            kpi_card("Levantamientos", "3", ft.Icons.ENGINEERING, "#FFA726"),   # Naranja
            kpi_card("Ganadas", "8", ft.Icons.EMOJI_EVENTS, "#66BB6A"),      # Verde
            kpi_card("Perdidas", "2", ft.Icons.CANCEL, "#EF5350"),     # Rojo
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True)

        # Grafico 1: Tendencia (Barras)
        chart_barras = ft.BarChart(
            bar_groups=[
                ft.BarChartGroup(x=0, bar_rods=[ft.BarChartRod(from_y=0, to_y=4, width=20, color="amber", tooltip="Lunes")]),
                ft.BarChartGroup(x=1, bar_rods=[ft.BarChartRod(from_y=0, to_y=8, width=20, color="blue", tooltip="Martes")]),
                ft.BarChartGroup(x=2, bar_rods=[ft.BarChartRod(from_y=0, to_y=2, width=20, color="red", tooltip="Miércoles")]),
                ft.BarChartGroup(x=3, bar_rods=[ft.BarChartRod(from_y=0, to_y=5, width=20, color="green", tooltip="Jueves")]),
                ft.BarChartGroup(x=4, bar_rods=[ft.BarChartRod(from_y=0, to_y=3, width=20, color="purple", tooltip="Viernes")]),
            ],
            border=ft.border.all(1, ft.Colors.GREY_400),
            left_axis=ft.ChartAxis(labels_size=40, title=ft.Text("Cant. Solicitudes")),
            bottom_axis=ft.ChartAxis(labels=[
                ft.ChartAxisLabel(value=0, label=ft.Container(ft.Text("Lun"), padding=5)),
                ft.ChartAxisLabel(value=1, label=ft.Container(ft.Text("Mar"), padding=5)),
                ft.ChartAxisLabel(value=2, label=ft.Container(ft.Text("Mie"), padding=5)),
                ft.ChartAxisLabel(value=3, label=ft.Container(ft.Text("Jue"), padding=5)),
                ft.ChartAxisLabel(value=4, label=ft.Container(ft.Text("Vie"), padding=5)),
            ], labels_size=30),
            horizontal_grid_lines=ft.ChartGridLines(color=ft.Colors.GREY_300, width=1, dash_pattern=[3, 3]),
            tooltip_bgcolor=ft.Colors.with_opacity(0.8, ft.Colors.BLUE_GREY),
            max_y=10,
            expand=True
        )

        # Grafico 2: Tecnologías (PieChart)
        chart_pie = ft.PieChart(
            sections=[
                ft.PieChartSection(40, title="FV", color=ft.Colors.BLUE, radius=50),
                ft.PieChartSection(30, title="BESS", color=ft.Colors.ORANGE, radius=50),
                ft.PieChartSection(15, title="FV+BESS", color=ft.Colors.PURPLE, radius=50),
                ft.PieChartSection(15, title="Hibrido", color=ft.Colors.GREY, radius=50),
            ],
            sections_space=2,
            center_space_radius=40,
            expand=True
        )

        # FIX 2 Step B: Conectar hook para actualizar UI de fechas
        state["update_fechas_ui"] = actualizar_texto_botones

        return ft.Container(
            content=ft.Column([
                filtros,
                ft.Divider(),
                row_kpis,
                ft.Container(height=20),
                
                # Fila de Graficos
                ft.Row([
                    # Columna Izquierda: Tendencia
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Tendencia de Solicitudes", weight="bold", color=COLOR_PRIMARIO),
                            ft.Container(content=chart_barras, height=250)
                        ]),
                        expand=2, border=ft.border.all(1, "#E1E1E1"), border_radius=10, padding=20
                    ),
                    # Columna Derecha: Tecnologias
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Mix Tecnológico", weight="bold", color=COLOR_PRIMARIO),
                            ft.Container(content=chart_pie, height=250)
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        expand=1, border=ft.border.all(1, "#E1E1E1"), border_radius=10, padding=20
                    )
                ], spacing=20)
            ], scroll=ft.ScrollMode.AUTO),
            padding=10
        )

    # --- UI PASO 1 (FORMULARIO) ---
    tf_cliente = ft.TextField(label="Nombre del Cliente", border_color=COLOR_PRIMARIO, text_size=14)
    tf_proyecto_nombre = ft.TextField(label="Nombre del Proyecto", border_color=COLOR_PRIMARIO, text_size=14)
    tf_canal_venta = ft.TextField(label="Canal de Venta", value=USUARIO_ACTUAL, read_only=False, border_color=COLOR_PRIMARIO, text_size=14)

    dd_tecnologia = ft.Dropdown(label="Tecnología", border_color=COLOR_PRIMARIO, text_size=14, options=[ft.dropdown.Option("FV"), ft.dropdown.Option("BESS"), ft.dropdown.Option("FV + BESS")], value="FV")
    
    dd_solicitud = ft.Dropdown(label="Tipo de Solicitud", border_color=COLOR_PRIMARIO, text_size=14, options=[
        ft.dropdown.Option("PRE OFERTA"), 
        ft.dropdown.Option("LICITACION"),
        ft.dropdown.Option("SOLICITUD DE LEVANTAMIENTO"),
        ft.dropdown.Option("ACTUALIZACION DE OFERTA"),
        ft.dropdown.Option("COTIZACION"),
        ft.dropdown.Option("CIERRE")
    ])
    
    def cambio_cantidad_sitios(e):
        try:
            cant = int(tf_cantidad_sitios.value)
            if cant > 1:
                col_carga_masiva.visible = True
            else:
                col_carga_masiva.visible = False
                state["df_sitios"] = None 
                state["excel_file_obj"] = None
                tabla_preview.rows.clear()
            page.update()
        except: pass

    tf_cantidad_sitios = ft.TextField(
        label="Cant. Sitios", 
        value="1", 
        border_color=COLOR_PRIMARIO, 
        text_size=14, 
        width=100,
        keyboard_type=ft.KeyboardType.NUMBER,
        text_align=ft.TextAlign.CENTER,
        helper_text="Si > 1 habilita carga masiva",
        on_change=cambio_cantidad_sitios
    )

    tf_direccion = ft.TextField(label="Dirección (Obligatorio)", multiline=True, height=60, border_color=COLOR_PRIMARIO, text_size=14)
    tf_coordenadas = ft.TextField(label="Coordenadas GPS (Opcional)", border_color=COLOR_PRIMARIO, text_size=14, hint_text="Ej: 19.4326, -99.1332", icon=ft.Icons.PUBLIC)
    tf_maps = ft.TextField(label="Link Google Maps (Obligatorio)", multiline=True, height=60, border_color=COLOR_PRIMARIO, text_size=14, color="blue")
    tf_folder_link = ft.TextField(label="Link Carpeta SharePoint (Opcional)", multiline=False, border_color=COLOR_PRIMARIO, text_size=14, icon=ft.Icons.FOLDER_SHARED, helper_text="Aqui puedes agregar un link o ruta de la carpeta con documentos si aplica")
    dd_prioridad = ft.Dropdown(label="Prioridad", border_color=COLOR_PRIMARIO, text_size=14, options=[ft.dropdown.Option("Low"), ft.dropdown.Option("Normal"), ft.dropdown.Option("High")], value="Normal")

    tabla_preview = ft.DataTable(columns=[ft.DataColumn(ft.Text("NOMBRE")), ft.DataColumn(ft.Text("DIRECCION"))], rows=[])
    
    # FIX 2: Descarga de plantilla para modo web
    def click_descargar_plantilla(e):
        """Genera y descarga la plantilla Excel en modo web"""
        try:
            # FIX 1 & 2: Crear ruta absoluta y asegurar que el directorio existe
            ruta_absoluta = os.path.join(os.getcwd(), "assets", "plantilla_sitios.xlsx")
            print(f"Intentando guardar en: {ruta_absoluta}")
            
            # FIX 2: Crear carpeta si no existe
            os.makedirs(os.path.dirname(ruta_absoluta), exist_ok=True)
            
            cols = ["#", "NOMBRE", "# DE SERVICIO", "TARIFA", "LINK GOOGLE", "DIRECCION", "COMENTARIOS"]
            df = pd.DataFrame(columns=cols)
            df.loc[0] = [1, "SUCURSAL NORTE", "123456789012", "GDMTO", "http://maps...", "Av. Reforma 123", "Revisar recibo"]
            df.to_excel(ruta_absoluta, index=False)
            
            # FIX 2: URL corregida - assets_dir sirve archivos en raíz
            page.launch_url("/plantilla_sitios.xlsx")
            page.open(ft.SnackBar(ft.Text("✅ Plantilla generada y descargando..."), bgcolor="green"))
            page.update()
        except Exception as ex:
            page.open(ft.SnackBar(ft.Text(f"❌ Error generando plantilla: {ex}"), bgcolor="red"))
            page.update()

    # --- CAMBIO 1: Definir botón fuera del layout para controlarlo ---
    btn_cargar_excel = ft.ElevatedButton(
        "2. Cargar Excel", 
        icon=ft.Icons.UPLOAD_FILE, 
        bgcolor="green", 
        color="white"
    )
    # NOTA: El evento on_click se asignará más abajo, después de definir el picker.
    
    # Asignar la acción al botón AQUÍ, porque excel_picker ya existe
    btn_cargar_excel.on_click = lambda _: excel_picker.pick_files(allowed_extensions=["xlsx", "xls", "csv"])
    
    col_carga_masiva = ft.Column([
        ft.Container(height=10),
        ft.Text("Carga Masiva de Sitios", weight="bold", color=COLOR_PRIMARIO),
        ft.Row([
            ft.ElevatedButton("1. Descargar Plantilla", icon=ft.Icons.DOWNLOAD, on_click=click_descargar_plantilla),
            btn_cargar_excel,  # Usamos la variable definida arriba
        ]),
        ft.Text("Previsualización (Primeros 5 registros):", size=11, italic=True),
        ft.Container(
            content=ft.Column([tabla_preview], scroll=ft.ScrollMode.AUTO), 
            border=ft.border.all(1, "grey"), 
            border_radius=5, 
            height=150, 
            padding=5
        )
    ], visible=False) 

    col_paso1_form = ft.Column([
        ft.Text("Paso 1: Datos del Proyecto", weight="bold", size=16, color=COLOR_PRIMARIO),
        tf_cliente, tf_proyecto_nombre, tf_canal_venta, 
        ft.Divider(),
        ft.Text("Especificaciones", weight="bold", color=COLOR_PRIMARIO),
        ft.Row([dd_tecnologia, dd_solicitud, tf_cantidad_sitios], spacing=10),
        col_carga_masiva, 
        dd_prioridad,
        ft.Divider(),
        ft.Text("Ubicación Principal y Referencias", weight="bold", color=COLOR_PRIMARIO),
        tf_direccion, tf_maps, tf_coordenadas, tf_folder_link
    ], scroll=ft.ScrollMode.AUTO, spacing=15, expand=True)

    # --- UI PASO 2 (CORREO) ---
    tf_cuerpo_correo = ft.TextField(
        label="Redacción de Correo",
        multiline=True,
        min_lines=8, max_lines=12,
        border_color=COLOR_PRIMARIO, text_size=14,
        hint_text="Escribe aquí el mensaje..."
    )

    lista_archivos_visual = ft.Column(spacing=5)
    txt_peso_total = ft.Text("Total: 0.00 MB / 35.00 MB", size=11, color="grey", weight="bold")
    
    col_paso2_correo = ft.Column([
        ft.Text("Paso 2: Redactar y Adjuntar", weight="bold", size=16, color=COLOR_PRIMARIO),
        ft.Text("Verifica el mensaje y adjunta los archivos necesarios.", size=12, color="grey"),
        ft.Divider(),
        tf_cuerpo_correo,
        ft.Container(height=10),
        ft.Row([
            ft.ElevatedButton("Adjuntar Archivos", icon=ft.Icons.ATTACH_FILE, bgcolor="#E1E1E1", color="black", on_click=lambda _: file_picker.pick_files(allow_multiple=True)),
            ft.Column([ft.Text("Múltiples archivos permitidos", size=10, italic=True, color="grey"), txt_peso_total], spacing=2)
        ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(height=5),
        ft.Text("Archivos seleccionados:", size=12, weight="bold"),
        ft.Container(content=lista_archivos_visual, padding=10, bgcolor="#F9F9F9", border_radius=5, border=ft.border.all(1, "#E1E1E1"), width=500)
    ], visible=False, scroll=ft.ScrollMode.AUTO, expand=True)

    # --- MODAL ---
    btn_cancelar = ft.TextButton("Cancelar")
    btn_siguiente = ft.ElevatedButton("Guardar y Continuar", bgcolor=COLOR_PRIMARIO, color="white")
    btn_enviar = ft.ElevatedButton("Enviar Solicitud", icon=ft.Icons.SEND, bgcolor="green", color="white", visible=False)

    dlg_modal = ft.AlertDialog(
        modal=True,
        title=ft.Text("Nueva Solicitud", size=20, weight="bold"),
        content=ft.Container(width=550, height=700, content=ft.Column([col_paso1_form, col_paso2_correo], expand=True)),
        actions=[btn_cancelar, btn_siguiente, btn_enviar],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # --- LOGICA EXCEL Y ARCHIVOS ---

    def guardar_plantilla(e):
        if e.path:
            ruta = e.path
            if not ruta.endswith(".xlsx"):
                ruta += ".xlsx"
            cols = ["#", "NOMBRE", "# DE SERVICIO", "TARIFA", "LINK GOOGLE", "DIRECCION", "COMENTARIOS"]
            df = pd.DataFrame(columns=cols)
            df.loc[0] = [1, "SUCURSAL NORTE", "123456789012", "GDMTO", "http://maps...", "Av. Reforma 123", "Revisar recibo"]
            try:
                df.to_excel(ruta, index=False)
                page.open(ft.SnackBar(ft.Text("✅ Plantilla descargada"), bgcolor="green"))
            except Exception as ex:
                page.open(ft.SnackBar(ft.Text(f"❌ Error: {ex}"), bgcolor="red"))
            page.update()

    # FIX CRÍTICO: Función separada para leer y procesar Excel después del upload
    # --- CAMBIO 2: Lógica de lectura limpia ---
    def leer_datos_excel_logica(ruta_excel, archivo_obj):
        """Lee el Excel físico, valida y actualiza la UI"""
        try:
            print(f"📖 Leyendo Excel: {ruta_excel}")
            
            if archivo_obj.name.endswith('.csv'): 
                df = pd.read_csv(ruta_excel)
            else: 
                df = pd.read_excel(ruta_excel)
            
            # Normalizar columnas
            df.columns = [c.strip().upper() for c in df.columns]
            cols_req = ["NOMBRE", "DIRECCION"]
            
            errores = None
            if not all(col in df.columns for col in cols_req):
                 errores = "Formato incorrecto. Por favor usa la plantilla oficial."
            
            if not errores:
                cant_declarada = int(tf_cantidad_sitios.value) if tf_cantidad_sitios.value else 1
                if len(df) != cant_declarada:
                    errores = f"Declaraste {cant_declarada} sitios, pero el Excel tiene {len(df)}."

            if errores:
                page.open(ft.SnackBar(ft.Text(f"⛔ {errores}"), bgcolor="red"))
                state["df_sitios"] = None
                state["excel_file_obj"] = None
                tabla_preview.rows.clear()
            else:
                # ÉXITO
                state["df_sitios"] = df
                state["excel_file_obj"] = archivo_obj
                
                tabla_preview.rows.clear()
                for i, row in df.head(5).iterrows():
                    tabla_preview.rows.append(ft.DataRow(cells=[
                        ft.DataCell(ft.Text(str(row.get("NOMBRE", ""))[:20])),
                        ft.DataCell(ft.Text(str(row.get("DIRECCION", ""))[:30]))
                    ]))
                page.open(ft.SnackBar(ft.Text(f"✅ {len(df)} sitios cargados correctamente."), bgcolor="green"))

        except Exception as ex:
            state["df_sitios"] = None
            page.open(ft.SnackBar(ft.Text(f"❌ Error leyendo Excel: {ex}"), bgcolor="red"))
        finally:
            # LIMPIEZA INMEDIATA: Borrar el archivo físico temporal
            if os.path.exists(ruta_excel):
                try:
                    os.remove(ruta_excel)
                    print("🧹 Archivo temporal eliminado tras lectura.")
                except: pass
            page.update()

    # --- CAMBIO 4: Inicio de carga con bloqueo y UUID ---
    def procesar_excel_sitios(e):
        if not e.files: return

        # BLOQUEO UI: Evitar doble click o reintentos rápidos
        if btn_cargar_excel.disabled: return
        
        btn_cargar_excel.disabled = True
        btn_cargar_excel.text = "Procesando..."
        page.update()
        
        try:
            archivo = e.files[0]
            
            # --- MODO WEB ---
            if archivo.path is None:
                # 1. Generar nombre único seguro (UUID)
                ext = archivo.name.split('.')[-1]
                nombre_servidor = f"{uuid.uuid4().hex}.{ext}"
                
                # 2. Guardar referencia
                state["temp_excel_name"] = nombre_servidor
                state["excel_file_obj"] = archivo 
                
                # 3. Iniciar subida con URL específica
                upload_url = page.get_upload_url(nombre_servidor, 600)
                excel_picker.upload([
                    ft.FilePickerUploadFile(archivo.name, upload_url=upload_url)
                ])
                print(f"⬆️ Subiendo como: {nombre_servidor}")
            
            # --- MODO DESKTOP ---
            else:
                leer_datos_excel_logica(archivo.path, archivo)
                btn_cargar_excel.disabled = False
                btn_cargar_excel.text = "2. Cargar Excel"
                page.update()

        except Exception as ex:
            print(f"Error inicio carga: {ex}")
            btn_cargar_excel.disabled = False
            btn_cargar_excel.text = "2. Cargar Excel"
            page.update()

    def calcular_peso_total():
        total_bytes = sum([f.size for f in state["archivos_seleccionados"]])
        total_mb = total_bytes / (1024 * 1024)
        txt_peso_total.value = f"Total: {total_mb:.2f} MB / {LIMITE_MB}.00 MB"
        
        excede = total_bytes > LIMITE_BYTES
        txt_peso_total.color = "red" if excede else "grey"
        btn_enviar.disabled = excede
        btn_enviar.text = "Excede 35MB" if excede else "Enviar Solicitud"
        page.update()
        return total_bytes

    def actualizar_lista_visual():
        lista_archivos_visual.controls.clear()
        for f in state["archivos_seleccionados"]:
            lista_archivos_visual.controls.append(
                ft.Row([
                    ft.Icon(ft.Icons.ATTACH_FILE, size=14, color=COLOR_PRIMARIO),
                    ft.Text(f.name, size=12, weight="bold", expand=True),
                    ft.Text(f"({round(f.size/1024, 1)} KB)", size=10, color="grey"),
                    ft.IconButton(icon=ft.Icons.DELETE, icon_color="red", icon_size=16, on_click=lambda e, arch=f: eliminar_archivo(arch))
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            )
        calcular_peso_total()

    def agregar_archivos(e):
        if e.files:
            peso_act = sum([f.size for f in state["archivos_seleccionados"]])
            peso_new = sum([f.size for f in e.files])
            if (peso_act + peso_new) > LIMITE_BYTES:
                page.open(ft.SnackBar(ft.Text(f"⚠️ Error: Límite de {LIMITE_MB}MB excedido."), bgcolor="red"))
                page.update()
                return 
            
            # En modo web, subir archivos al servidor
            archivos_a_subir = []
            for archivo in e.files:
                if archivo.path is None:
                    # Modo web: preparar upload
                    archivos_a_subir.append(ft.FilePickerUploadFile(
                        archivo.name,
                        upload_url=page.get_upload_url(archivo.name, 600)
                    ))
            
            # Si hay archivos para subir (modo web), disparar upload
            if archivos_a_subir:
                file_picker.upload(archivos_a_subir)
            
            # Agregar a la lista (en web, estarán en assets después del upload)
            state["archivos_seleccionados"].extend(e.files)
            actualizar_lista_visual()

    def eliminar_archivo(arch):
        state["archivos_seleccionados"] = [f for f in state["archivos_seleccionados"] if f != arch]
        actualizar_lista_visual()

    # --- CONTROL FLUJO ---
    def cerrar_modal(e):
        if state["paso_actual"] == 2 and state["id_oportunidad_guardada"]:
            try:
                # Si cancela en paso 2, borramos el borrador de BD
                if not db.table("tb_oportunidades").select("email_enviado").eq("id", state["id_oportunidad_guardada"]).execute().data[0]['email_enviado']:
                    db.table("tb_oportunidades").delete().eq("id", state["id_oportunidad_guardada"]).execute()
                    e.page.open(ft.SnackBar(ft.Text("Borrador cancelado."), bgcolor="orange")) 
            except: pass

        e.page.close(dlg_modal)
        col_paso1_form.visible = True; col_paso2_correo.visible = False
        btn_siguiente.visible = True; btn_siguiente.disabled = False; btn_enviar.visible = False
        state["archivos_seleccionados"] = []; state["id_oportunidad_guardada"] = None; state["paso_actual"] = 1
        state["df_sitios"] = None; state["excel_file_obj"] = None
        tabla_preview.rows.clear(); col_carga_masiva.visible = False 
        lista_archivos_visual.controls.clear(); tf_cuerpo_correo.value = ""
        recargar_listas() 

    btn_cancelar.on_click = cerrar_modal

    def ir_a_paso_2_guardar_bd(e):
        btn_siguiente.disabled = True
        e.page.update()

        errores = []
        val_cliente = tf_cliente.value.strip() if tf_cliente.value else ""
        val_proyecto = tf_proyecto_nombre.value.strip() if tf_proyecto_nombre.value else ""
        if not val_cliente: errores.append("Cliente")
        if not val_proyecto: errores.append("Proyecto")
        if not dd_solicitud.value: errores.append("Tipo Solicitud")
        if not tf_direccion.value: errores.append("Dirección")
        if not tf_maps.value: errores.append("Maps")
        
        cant_sitios = 1
        try:
            cant_sitios = int(tf_cantidad_sitios.value)
            if cant_sitios < 1: raise ValueError
            if cant_sitios > 1 and state["df_sitios"] is None: errores.append("Cargar/Validar Excel")
        except: errores.append("Cant. Sitios inválida")

        if errores:
            btn_siguiente.disabled = False 
            e.page.open(ft.SnackBar(ft.Text(f"⚠️ Faltan: {', '.join(errores)}"), bgcolor="red"))
            e.page.update()
            return

        try:
            val_canal = tf_canal_venta.value.strip() if tf_canal_venta.value else ""
            cliente_nombre = val_cliente.upper()
            res_cliente = db.table("tb_clientes").select("id").eq("nombre_fiscal", cliente_nombre).execute()
            cliente_id = res_cliente.data[0]['id'] if res_cliente.data else db.table("tb_clientes").insert({"nombre_fiscal": cliente_nombre}).execute().data[0]['id']

            fecha = datetime.now()
            nombre_concat_padre = f"{dd_solicitud.value}_{cliente_nombre}_{val_proyecto}_{dd_tecnologia.value}_{val_canal}".upper()
            
            id_interno = None
            if not state["id_oportunidad_guardada"]:
                timestamp_id = fecha.strftime('%y%m%d%H%M')
                id_interno = f"OP - {timestamp_id}_{val_proyecto}_{cliente_nombre}".upper()

            datos = {
                "titulo_proyecto": nombre_concat_padre, 
                "nombre_proyecto": val_proyecto,
                "cliente_id": cliente_id,
                "canal_venta": val_canal, 
                "solicitado_por": USUARIO_ACTUAL,    
                "tipo_tecnologia": dd_tecnologia.value,
                "tipo_solicitud": dd_solicitud.value,
                "cantidad_sitios": cant_sitios,
                "prioridad": dd_prioridad.value,
                "direccion_obra": tf_direccion.value,
                "coordenadas_gps": tf_coordenadas.value, 
                "google_maps_link": tf_maps.value,
                "sharepoint_folder_url": tf_folder_link.value,
                "status_global": "Pendiente",
                "deadline_calculado": calcular_deadline().isoformat(),
                "codigo_generado": nombre_concat_padre, 
                "id_interno_simulacion": id_interno, 
                "outlook_message_id": state["id_correo_original"]
            }

            if state["id_oportunidad_guardada"]:
                datos.pop("id_interno_simulacion", None)
                db.table("tb_oportunidades").update(datos).eq("id", state["id_oportunidad_guardada"]).execute()
            else:
                datos["fecha_solicitud"] = fecha.isoformat()
                datos["email_enviado"] = False
                res = db.table("tb_oportunidades").insert(datos).execute()
                if res.data: 
                    state["id_oportunidad_guardada"] = res.data[0]['id']

            dlg_modal.title.value = f"Redactando: {nombre_concat_padre}"

            if cant_sitios > 1 and state["df_sitios"] is not None:
                db.table("tb_sitios_oportunidad").delete().eq("oportunidad_id", state["id_oportunidad_guardada"]).execute()
                batch = []
                for _, row in state["df_sitios"].iterrows():
                    nombre_sitio_excel = str(row.get("NOMBRE", "")).strip()
                    nombre_concat_hijo = f"{dd_solicitud.value}_{cliente_nombre}_{nombre_sitio_excel}_{dd_tecnologia.value}_{val_canal}".upper()
                    
                    batch.append({
                        "oportunidad_id": state["id_oportunidad_guardada"],
                        "nombre_sitio": nombre_sitio_excel, 
                        "codigo_generado": nombre_concat_hijo, 
                        "direccion_completa": str(row.get("DIRECCION", "")),
                        "google_maps_link": str(row.get("LINK GOOGLE", "")),
                        "usuario_carga": USUARIO_ACTUAL
                    })
                if batch: db.table("tb_sitios_oportunidad").insert(batch).execute()

            col_paso1_form.visible = False
            col_paso2_correo.visible = True
            btn_siguiente.visible = False
            
            btn_enviar.visible = True
            btn_enviar.disabled = False 
            btn_enviar.text = "Enviar Solicitud"
            
            # Si se cargó un excel, lo añadimos a la lista de envío
            if state["excel_file_obj"]:
                if state["excel_file_obj"] not in state["archivos_seleccionados"]:
                    state["archivos_seleccionados"].append(state["excel_file_obj"])
                    actualizar_lista_visual()

            state["paso_actual"] = 2
            e.page.update()

        except Exception as ex:
            print(f"Error: {ex}")
            btn_siguiente.disabled = False
            e.page.open(ft.SnackBar(ft.Text(f"❌ Error BD: {ex}"), bgcolor="red"))
            e.page.update()

    def accion_finalizar_envio(e):        
        # 1. BLOQUEAR UI
        btn_enviar.disabled = True
        btn_enviar.text = "Enviando con Microsoft..."
        e.page.update()
        
        # 2. PREPARAR DATOS
        cuerpo = tf_cuerpo_correo.value or " "
        extra = f"\n\n--- DETALLES ---\nDir: {tf_direccion.value}\nGPS: {tf_coordenadas.value}\nMaps: {tf_maps.value}\n"
        
        cant = int(tf_cantidad_sitios.value)
        if cant > 1 and state["df_sitios"] is not None:
             extra += f"\n** MULTISITIO: {cant} SITIOS **\n"
             for i, row in state["df_sitios"].head(3).iterrows():
                 nombre_clean = str(row['NOMBRE']).strip()
                 extra += f"- {nombre_clean}: {row['DIRECCION']}\n"
             if cant > 3: extra += f"... y {cant-3} más.\n"

        if tf_folder_link.value: extra += f"SharePoint: {tf_folder_link.value}\n"
        
        asunto = dlg_modal.title.value.replace("Redactando: ", "").replace("Nueva Solicitud", "")  # FIX 3: Limpiar asunto
        
        # Preparar archivos adjuntos con rutas correctas
        # En modo web, los archivos están en assets/
        archivos_para_enviar = []
        for archivo in state["archivos_seleccionados"]:
            # Crear un objeto tipo archivo con la ruta correcta
            if archivo.path is None:
                # Modo web: usar ruta desde assets
                archivo_con_ruta = type('obj', (object,), {
                    'name': archivo.name,
                    'path': os.path.join(state["upload_dir"], archivo.name),
                    'size': archivo.size
                })()
                archivos_para_enviar.append(archivo_con_ruta)
            else:
                # Modo desktop: usar archivo original
                archivos_para_enviar.append(archivo)
        
        # 3. LLAMADA A MICROSOFT GRAPH
        try:
            exito, mensaje = ms_auth.send_email_with_attachments(
                subject=asunto,  # FIX 3: Ya está limpio, no reemplazar más
                body=cuerpo + extra,
                recipients=CORREO_DESTINO_SIMULACION,
                attachments_files=archivos_para_enviar
            )

            if exito:
                # 4. ACTUALIZAR DB SI FUE EXITOSO
                db.table("tb_oportunidades").update({"email_enviado": True}).eq("id", state["id_oportunidad_guardada"]).execute()
                
                # FIX 2: Limpiar archivos de assets después de envío exitoso
                for archivo in state["archivos_seleccionados"]:
                    if archivo.path is None:  # Solo limpiar archivos subidos en modo web
                        try:
                            ruta_temp = os.path.join(state["upload_dir"], archivo.name)
                            if os.path.exists(ruta_temp):
                                os.remove(ruta_temp)
                                print(f"✅ Archivo limpiado de assets: {archivo.name}")
                        except Exception as cleanup_ex:
                            print(f"⚠️ No se pudo limpiar archivo: {cleanup_ex}")
                
                e.page.open(ft.SnackBar(ft.Text(f"🚀 Correo enviado y registrado!"), bgcolor="green"))
                
                # 5. LIMPIEZA
                state["paso_actual"] = 1; state["id_oportunidad_guardada"] = None; state["df_sitios"] = None
                state["excel_file_obj"] = None
                col_carga_masiva.visible = False; cerrar_modal(e); recargar_listas()
            else:
                # ERROR EN ENVIO
                e.page.open(ft.SnackBar(ft.Text(f"❌ Error al enviar: {mensaje}"), bgcolor="red"))
                btn_enviar.disabled = False
                btn_enviar.text = "Reintentar Envío"
                
        except Exception as ex:
            e.page.open(ft.SnackBar(ft.Text(f"❌ Error Crítico: {ex}"), bgcolor="red"))
            btn_enviar.disabled = False
            btn_enviar.text = "Reintentar Envío"
        
        e.page.update()

    btn_siguiente.on_click = ir_a_paso_2_guardar_bd
    btn_enviar.on_click = accion_finalizar_envio

    # --- APERTURA ---
    def abrir_modal_nuevo(e):
        tf_cliente.value = ""; tf_proyecto_nombre.value = ""; tf_direccion.value = ""; tf_maps.value = ""
        tf_coordenadas.value = ""; tf_folder_link.value = ""; tf_canal_venta.value = USUARIO_ACTUAL 
        tf_cantidad_sitios.value = "1"; dd_tecnologia.value = "FV"; dd_prioridad.value = "Normal"
        
        dd_solicitud.options = [ft.dropdown.Option("PRE OFERTA"), ft.dropdown.Option("LICITACION")]
        dd_solicitud.value = None; dd_solicitud.disabled = False
        
        state["id_correo_original"] = None; state["archivos_seleccionados"] = []
        state["id_oportunidad_guardada"] = None; state["paso_actual"] = 1; state["df_sitios"] = None
        state["excel_file_obj"] = None
        
        col_carga_masiva.visible = False; tabla_preview.rows.clear(); lista_archivos_visual.controls.clear()
        tf_cuerpo_correo.value = ""; txt_peso_total.value = f"Total: 0.00 MB / {LIMITE_MB}.00 MB"; txt_peso_total.color = "grey"
        
        col_paso1_form.visible = True; col_paso2_correo.visible = False
        btn_siguiente.visible = True; btn_siguiente.disabled = False; btn_enviar.visible = False
        dlg_modal.title.value = "Nueva Solicitud"
        e.page.open(dlg_modal); e.page.update()

    def abrir_modal_accion(e, item_data, tipo_accion):
        tf_cliente.value = item_data['tb_clientes']['nombre_fiscal']
        tf_proyecto_nombre.value = item_data.get('nombre_proyecto', '')
        tf_direccion.value = item_data.get('direccion_obra', '')
        tf_coordenadas.value = item_data.get('coordenadas_gps', '')
        tf_maps.value = item_data.get('google_maps_link', '')
        tf_folder_link.value = item_data.get('sharepoint_folder_url', '')
        tf_canal_venta.value = item_data.get('canal_venta', USUARIO_ACTUAL)
        
        cant = item_data.get('cantidad_sitios'); tf_cantidad_sitios.value = str(cant) if cant else "1"
        col_carga_masiva.visible = False 

        dd_tecnologia.value = item_data.get('tipo_tecnologia', 'FV')
        dd_solicitud.options = [ft.dropdown.Option(tipo_accion)]
        dd_solicitud.value = tipo_accion; dd_solicitud.disabled = True
        
        msg_id = item_data.get('outlook_message_id'); state["id_correo_original"] = msg_id if msg_id else None
        
        state["id_oportunidad_guardada"] = None; state["paso_actual"] = 1; state["df_sitios"] = None
        col_paso1_form.visible = True; col_paso2_correo.visible = False
        btn_siguiente.visible = True; btn_siguiente.disabled = False; btn_enviar.visible = False
        lista_archivos_visual.controls.clear(); tf_cuerpo_correo.value = ""
        
        if not msg_id: e.page.open(ft.SnackBar(ft.Text("⚠️ Sin historial de correo"), bgcolor="orange")); e.page.update()
        e.page.open(dlg_modal); e.page.update()

    # --- TARJETAS ---
    col_activos = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
    col_levantamientos = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO) 
    col_historial = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
    tf_buscar = ft.TextField(hint_text="Buscar por Cliente, Proyecto o ID...", prefix_icon=ft.Icons.SEARCH, height=40, text_size=12, expand=True, on_change=lambda e: filtrar_listas(e.control.value))

    def determinar_etiqueta_horario(fecha_str):
        if not fecha_str: return None
        try:
            # Limpieza para compatibilidad ISO (Manejo de 'Z' y microsegundos)
            fecha_clean = fecha_str.replace('Z', '+00:00')
            fecha_dt = datetime.fromisoformat(fecha_clean)
            
            # Lógica de negocio (Horario laboral: L-V antes de las 17:30)
            dia_semana = fecha_dt.weekday() # 0=Lun, 6=Dom
            hora = fecha_dt.time()
            corte = dt_time(17, 30)
            
            es_fin_de_semana = dia_semana in [5, 6] # Sabado o Domingo
            es_tarde = hora > corte
            
            if es_fin_de_semana or es_tarde:
                return ft.Container(
                    content=ft.Text("FUERA DE HORARIO", size=9, color="white", weight="bold"),
                    bgcolor=ft.Colors.RED_400,
                    padding=ft.padding.symmetric(horizontal=4, vertical=2),
                    border_radius=4
                )
            return None
        except Exception as e:
            print(f"Error parseando fecha etiqueta: {e}")
            return None


    def crear_tarjeta(item, es_historial):
        raw_id = item.get('id_interno_simulacion', '---')
        # FIX ID VISUAL: SE MUESTRA COMPLETO
        id_visual = raw_id 
        
        titulo = item.get('titulo_proyecto', 'Sin Título')
        solicitado = item.get('solicitado_por', USUARIO_ACTUAL) 
        asignado = item.get('responsable_simulacion') or "Sin Asignar"
        estado = item.get('status_global', 'Pendiente')
        enviado = item.get('email_enviado', False)
        
        cant_sitios = item.get('cantidad_sitios', 1)
        es_multisitio = cant_sitios and cant_sitios > 1
        
        icon_email = ft.Icon(ft.Icons.MARK_EMAIL_READ, color="green", size=16) if enviado else ft.Icon(ft.Icons.WARNING_AMBER, color="orange", size=16)
        color_st = ft.Colors.ORANGE_400 if estado == "Pendiente" else ft.Colors.BLUE_400
        if estado in ["Entregado", "Ganada"]: color_st = ft.Colors.GREEN_600
        if estado in ["Cancelado", "Perdida"]: color_st = ft.Colors.RED_400

        acciones = []
        if es_historial:
            acciones = [
                ft.PopupMenuItem(text="Actualización", icon=ft.Icons.UPDATE, on_click=lambda e: abrir_modal_accion(e, item, "ACTUALIZACION DE OFERTA")),
                ft.PopupMenuItem(text="Levantamiento", icon=ft.Icons.ENGINEERING, on_click=lambda e: abrir_modal_accion(e, item, "SOLICITUD DE LEVANTAMIENTO")),
                ft.PopupMenuItem(text="Cotización", icon=ft.Icons.REQUEST_QUOTE, on_click=lambda e: abrir_modal_accion(e, item, "COTIZACION")),
                ft.PopupMenuItem(text="Cierre (Traspaso)", icon=ft.Icons.CHECK_CIRCLE, on_click=lambda e: abrir_modal_accion(e, item, "CIERRE")),
            ]
            boton_accion = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, items=acciones)
        else: boton_accion = ft.Container()

        fecha_sol = item.get('fecha_solicitud')
        fecha_envio = "---"; etiq = None
        if fecha_sol:
            try: dt = datetime.fromisoformat(fecha_sol); fecha_envio = dt.strftime("%d/%m/%y %H:%M"); etiq = determinar_etiqueta_horario(fecha_sol)
            except: pass
        
        # FIX 3: Formatear fecha de entrega como DD/MM/YYYY
        deadline_str = item.get('deadline_calculado', '')
        fecha_entrega_formateada = ""
        if deadline_str:
            try:
                from datetime import datetime as dt_parse
                fecha_obj = dt_parse.fromisoformat(deadline_str.replace('Z', '+00:00'))
                fecha_entrega_formateada = fecha_obj.strftime('%d/%m/%Y')
            except:
                # Si falla el parsing, usar los primeros 10 caracteres
                fecha_entrega_formateada = deadline_str[:10] if len(deadline_str) >= 10 else deadline_str
        
        col_fechas = ft.Column([
            ft.Row([ft.Text("Enviado:", size=10, color="grey"), ft.Text(fecha_envio, size=10, weight="bold"), etiq if etiq else ft.Container()], spacing=5),
            ft.Row([ft.Text("Entrega:", size=10, color="grey"), ft.Text(fecha_entrega_formateada, size=10, weight="bold", color="blue")], spacing=5)
        ], spacing=2)

        nueva_fecha = item.get('nueva_fecha_compromiso')
        if nueva_fecha: col_fechas.controls.append(ft.Row([ft.Text("Nueva F.:", size=10, color="grey"), ft.Text(nueva_fecha[:10], size=10, weight="bold", color="red")], spacing=5))

        col_sub_sitios = ft.Column(visible=False, spacing=2)
        btn_ver_sitios = ft.Container()

        def toggle_sitios(e):
            if not col_sub_sitios.controls:
                res = db.table("tb_sitios_oportunidad").select("*").eq("oportunidad_id", item['id']).execute()
                if res.data:
                    for s in res.data:
                        nombre_mostrar = s.get('codigo_generado', s['nombre_sitio'])
                        # FIX 4: Agregar indicador de estatus circular
                        indicador_estatus = ft.Container(
                            width=10,
                            height=10,
                            bgcolor="orange",  # Pendiente por defecto (sin módulo simulación)
                            border_radius=5
                        )
                        col_sub_sitios.controls.append(
                            ft.Container(
                                content=ft.Row([
                                    indicador_estatus,
                                    ft.Text("-", size=10, color="grey"),
                                    ft.Text(f"{nombre_mostrar}", size=10, color="#333333", weight="bold"),
                                    ft.Text("-", size=10, color="grey"),
                                    ft.Text(f"{s['direccion_completa'][:30]}...", size=10, color="#666666", selectable=True)
                                ], spacing=5),
                                bgcolor="#f0f0f0", padding=5, border_radius=4
                            )
                        )
                else:
                    col_sub_sitios.controls.append(ft.Text("No se encontraron sitios cargados.", size=10, italic=True))
            
            col_sub_sitios.visible = not col_sub_sitios.visible
            e.control.text = "Ocultar Sitios" if col_sub_sitios.visible else f"Ver {cant_sitios} Sitios"
            page.update()

        if es_multisitio:
            btn_ver_sitios = ft.TextButton(f"Ver {cant_sitios} Sitios", on_click=toggle_sitios, style=ft.ButtonStyle(color=COLOR_PRIMARIO))

        return ft.Card(
            elevation=2, content=ft.Container(padding=15, content=ft.Column([
                ft.Row([
                    ft.Row([ft.Container(content=ft.Text(f"ID: {id_visual}", size=12, weight="bold", color="white", selectable=True), bgcolor=COLOR_PRIMARIO, padding=5, border_radius=4), icon_email], spacing=5),
                    ft.Container(content=ft.Text(estado, size=11, color="white", weight="bold"), bgcolor=color_st, padding=5, border_radius=10)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                
                ft.Row([
                    ft.Text(titulo, size=14, weight="bold", color="#333333", expand=True, selectable=True),
                    btn_ver_sitios
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                
                col_sub_sitios,
                
                ft.Divider(height=1, color="grey"),
                
                ft.Row([
                    ft.Column([
                        ft.Row([ft.Icon(ft.Icons.PERSON, size=12, color="grey"), ft.Text(f"Solicitó: {solicitado}", size=11, weight="bold")]),
                        ft.Row([ft.Icon(ft.Icons.ASSIGNMENT_IND, size=12, color="grey"), ft.Text(f"Asignado: {asignado}", size=11, color=ft.Colors.GREY if asignado=="Sin Asignar" else "black")])
                    ], spacing=5),
                    col_fechas
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START),
                
                ft.Row([ft.Container(), boton_accion], alignment=ft.MainAxisAlignment.END)
            ]))
        )

    def filtrar_listas(texto):
        texto = texto.upper()
        col_activos.controls.clear(); col_historial.controls.clear(); col_levantamientos.controls.clear()
        
        fin = ["Entregado", "Cancelado", "Cancelado Trabajado"]
        
        for item in state["data_completa"]:
            cliente = item['tb_clientes']['nombre_fiscal'].upper()
            proyecto = str(item.get('nombre_proyecto','')).upper()
            codigo = str(item.get('codigo_generado','')).upper()
            tipo = item.get('tipo_solicitud', '')
            
            if (texto in cliente) or (texto in proyecto) or (texto in codigo):
                if item['status_global'] in fin: 
                    col_historial.controls.append(crear_tarjeta(item, True))
                elif "LEVANTAMIENTO" in tipo: 
                    col_levantamientos.controls.append(crear_tarjeta(item, False))
                else: 
                    col_activos.controls.append(crear_tarjeta(item, False))
        page.update()

    def recargar_listas():
        try:
            col_activos.controls.clear(); col_historial.controls.clear(); col_levantamientos.controls.clear()
            
            query = db.table("tb_oportunidades").select("*, tb_clientes(nombre_fiscal)").order("fecha_solicitud", desc=True)
            if not ES_GERENTE: query = query.eq('solicitado_por', USUARIO_ACTUAL)
            res = query.execute()
            state["data_completa"] = res.data 
            
            fin = ["Entregado", "Cancelado", "Cancelado Trabajado"]
            for item in res.data:
                tipo = item.get('tipo_solicitud', '')
                if item['status_global'] in fin: 
                    col_historial.controls.append(crear_tarjeta(item, True))
                elif "LEVANTAMIENTO" in tipo: 
                    col_levantamientos.controls.append(crear_tarjeta(item, False))
                else: 
                    col_activos.controls.append(crear_tarjeta(item, False))
            page.update()
        except Exception as e: print(e)

    recargar_listas()

    # --- BOTON SOLICITUD ESPECIAL ---
    btn_solicitud_especial = ft.ElevatedButton(
        "Solicitud Histórica", 
        icon=ft.Icons.RESTORE, 
        bgcolor="#E1E1E1", 
        color="black",
        on_click=lambda _: print("Boton inactivo: Esperando conexion a Graph API")
    )
    
    # --- BOTON NUEVA SOLICITUD ---
    btn_nueva_solicitud = ft.ElevatedButton(
        "Nueva Solicitud", 
        icon=ft.Icons.ADD, 
        bgcolor=COLOR_PRIMARIO, 
        color="white", 
        on_click=abrir_modal_nuevo
    )

    return ft.Container(
        padding=20,
        content=ft.Column([
            ft.Row([
                ft.Row([
                    ft.Column([ft.Text("Comercial", size=28, weight="bold", color=COLOR_PRIMARIO), ft.Text("Gestión de Prospectos", size=12, color="grey")], spacing=2),
                    ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Actualizar lista", on_click=lambda _: recargar_listas())
                ]),
                ft.Container(
                    content=ft.Text(f"Bienvenido, {USUARIO_ACTUAL}", size=14, weight="bold", color="white"),
                    padding=10, bgcolor=COLOR_TURQUESA, border_radius=20,
                    shadow=ft.BoxShadow(spread_radius=1, blur_radius=5, color=ft.Colors.with_opacity(0.3, "black"))
                ),
                # AGREGADO: Orden de Botones
                ft.Row([
                    btn_nueva_solicitud,
                    btn_solicitud_especial
                ])
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(),
            ft.Row([ft.Text("Buscar:", weight="bold"), tf_buscar], alignment=ft.MainAxisAlignment.START),
            
            ft.Tabs(selected_index=0, animation_duration=300, tabs=[
                ft.Tab(text="Portlets", icon=ft.Icons.BAR_CHART, content=crear_portlets()), 
                ft.Tab(text="Activos", icon=ft.Icons.PENDING_ACTIONS, content=ft.Container(col_activos, padding=10)),
                ft.Tab(text="Levantamientos", icon=ft.Icons.ENGINEERING, content=ft.Container(col_levantamientos, padding=10)), 
                ft.Tab(text="Historial", icon=ft.Icons.HISTORY, content=ft.Container(col_historial, padding=10)),
            ], expand=True)
        ], expand=True), expand=True
    )