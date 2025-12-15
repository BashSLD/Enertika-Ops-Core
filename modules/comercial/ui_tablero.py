import flet as ft
from core.database import db
from datetime import datetime, timedelta, time
import pandas as pd
import os

# --- CONSTANTES Y CONFIGURACION ---
USUARIO_ACTUAL = "SEBASTIAN_LEOCADIO"
ES_GERENTE = True 

COLOR_PRIMARIO = "#123456"
LIMITE_MB = 35
LIMITE_BYTES = LIMITE_MB * 1024 * 1024 

def ViewComercial(page: ft.Page):
    print("Inicializando vista Comercial (Final v1.0 - ID Completo)...") 
    
    # --- ESTADOS MUTABLES ---
    state = {
        "id_correo_original": None,
        "archivos_seleccionados": [], 
        "id_oportunidad_guardada": None, 
        "paso_actual": 1,
        "df_sitios": None,
        "data_completa": [],
        "excel_file_obj": None
    }

    file_picker = ft.FilePicker(on_result=lambda e: agregar_archivos(e))
    excel_picker = ft.FilePicker(on_result=lambda e: procesar_excel_sitios(e))
    save_file_picker = ft.FilePicker(on_result=lambda e: guardar_plantilla(e))

    page.overlay.extend([file_picker, excel_picker, save_file_picker])

    # --- LOGICA FECHAS ---
    def calcular_deadline():
        ahora = datetime.now()
        fecha_base = ahora.date()
        hora_actual = ahora.time()
        corte = time(17, 30, 0)
        if hora_actual > corte: fecha_base += timedelta(days=1)
        dia_semana = fecha_base.weekday()
        if dia_semana == 5: fecha_base += timedelta(days=2) 
        elif dia_semana == 6: fecha_base += timedelta(days=1) 
        return fecha_base + timedelta(days=7)

    # --- UI PASO 1 ---
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
    
    col_carga_masiva = ft.Column([
        ft.Container(height=10),
        ft.Text("Carga Masiva de Sitios", weight="bold", color=COLOR_PRIMARIO),
        ft.Row([
            ft.ElevatedButton("1. Descargar Plantilla", icon=ft.Icons.DOWNLOAD, on_click=lambda _: save_file_picker.save_file(file_name="plantilla_sitios.xlsx", allowed_extensions=["xlsx"])),
            ft.ElevatedButton("2. Cargar Excel", icon=ft.Icons.UPLOAD_FILE, bgcolor="green", color="white", on_click=lambda _: excel_picker.pick_files(allowed_extensions=["xlsx", "xls", "csv"])),
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

    # --- UI PASO 2 ---
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
            # FIX: Forzar extension .xlsx
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

    def procesar_excel_sitios(e):
        if e.files:
            try:
                archivo = e.files[0]
                if archivo.name.endswith('.csv'): df = pd.read_csv(archivo.path)
                else: df = pd.read_excel(archivo.path)
                
                cols_req = ["NOMBRE", "DIRECCION"] 
                df.columns = [c.strip().upper() for c in df.columns]
                
                if not all(col in df.columns for col in cols_req):
                     page.open(ft.SnackBar(ft.Text("❌ Formato incorrecto. Usa la plantilla."), bgcolor="red"))
                     state["df_sitios"] = None
                     return

                cant_declarada = int(tf_cantidad_sitios.value)
                cant_real = len(df)
                
                if cant_real != cant_declarada:
                    page.open(ft.SnackBar(ft.Text(f"⛔ Error: Declaraste {cant_declarada} sitios, Excel tiene {cant_real}. Corrige."), bgcolor="red"))
                    state["df_sitios"] = None 
                    state["excel_file_obj"] = None
                    tabla_preview.rows.clear()
                    page.update()
                    return 

                state["df_sitios"] = df
                state["excel_file_obj"] = archivo 
                
                tabla_preview.rows.clear()
                for i, row in df.head(5).iterrows():
                    tabla_preview.rows.append(ft.DataRow(cells=[
                        ft.DataCell(ft.Text(str(row["NOMBRE"])[:20])),
                        ft.DataCell(ft.Text(str(row["DIRECCION"])[:30]))
                    ]))
                page.open(ft.SnackBar(ft.Text(f"✅ {cant_real} sitios cargados."), bgcolor="green"))
                page.update()
            except Exception as ex:
                page.open(ft.SnackBar(ft.Text(f"❌ Error Archivo: {ex}"), bgcolor="red"))
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
            state["archivos_seleccionados"].extend(e.files)
            actualizar_lista_visual()

    def eliminar_archivo(arch):
        state["archivos_seleccionados"] = [f for f in state["archivos_seleccionados"] if f != arch]
        actualizar_lista_visual()

    # --- CONTROL FLUJO ---
    def cerrar_modal(e):
        if state["paso_actual"] == 2 and state["id_oportunidad_guardada"]:
            try:
                db.table("tb_oportunidades").delete().eq("id", state["id_oportunidad_guardada"]).execute()
                e.page.open(ft.SnackBar(ft.Text("Solicitud cancelada."), bgcolor="orange")) 
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
        btn_enviar.disabled = True; btn_enviar.text = "Enviando..."; e.page.update()
        
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
        
        print(f"--- ENVIANDO CORREO (Asunto: {dlg_modal.title.value}) ---")
        print(f"{cuerpo + extra}\n-------------")
        
        db.table("tb_oportunidades").update({"email_enviado": True}).eq("id", state["id_oportunidad_guardada"]).execute()
        e.page.open(ft.SnackBar(ft.Text(f"🚀 Correo enviado"), bgcolor="green"))
        
        state["paso_actual"] = 1; state["id_oportunidad_guardada"] = None; state["df_sitios"] = None
        state["excel_file_obj"] = None
        col_carga_masiva.visible = False; cerrar_modal(e); recargar_listas()
        btn_enviar.disabled = False; btn_enviar.text = "Enviar Solicitud"; e.page.update()

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
            fecha_dt = datetime.fromisoformat(fecha_str)
            dia_semana = fecha_dt.weekday(); hora = fecha_dt.time(); corte = time(17, 30)
            if (dia_semana in [5, 6]) or (hora > corte):
                return ft.Container(content=ft.Text("FUERA DE HORARIO", size=9, color="white", weight="bold"), bgcolor=ft.Colors.RED_400, padding=2, border_radius=4)
            return None
        except: return None

    def crear_tarjeta(item, es_historial):
        raw_id = item.get('id_interno_simulacion', '---')
        # FIX ID VISUAL: Mostramos el texto completo, no solo el timestamp
        id_visual = raw_id # SE MUESTRA COMPLETO
        
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
        
        col_fechas = ft.Column([
            ft.Row([ft.Text("Enviado:", size=10, color="grey"), ft.Text(fecha_envio, size=10, weight="bold"), etiq if etiq else ft.Container()], spacing=5),
            ft.Row([ft.Text("Entrega:", size=10, color="grey"), ft.Text(item.get('deadline_calculado', '')[:10], size=10, weight="bold", color="blue")], spacing=5)
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
                        col_sub_sitios.controls.append(
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.PLACE, size=12, color="grey"),
                                    ft.Text(f"{nombre_mostrar} - {s['direccion_completa'][:30]}...", size=10, color="#333333", selectable=True)
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

    # --- BOTON SOLICITUD ESPECIAL (INACTIVO POR AHORA) ---
    btn_solicitud_especial = ft.ElevatedButton(
        "Solicitud Histórica", 
        icon=ft.Icons.RESTORE, 
        bgcolor="#E1E1E1", 
        color="black",
        on_click=lambda _: print("Boton inactivo: Esperando conexion a Graph API")
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
                    padding=10, bgcolor="#00BABB", border_radius=20,
                    shadow=ft.BoxShadow(spread_radius=1, blur_radius=5, color=ft.Colors.with_opacity(0.3, "black"))
                ),
                # AGREGADO: Boton Especial
                ft.Row([
                    btn_solicitud_especial,
                    ft.ElevatedButton("Nueva Solicitud", icon=ft.Icons.ADD, bgcolor=COLOR_PRIMARIO, color="white", on_click=abrir_modal_nuevo)
                ])
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(),
            ft.Row([ft.Text("Buscar:", weight="bold"), tf_buscar], alignment=ft.MainAxisAlignment.START),
            
            ft.Tabs(selected_index=0, animation_duration=300, tabs=[
                ft.Tab(text="Activos", icon=ft.Icons.PENDING_ACTIONS, content=ft.Container(col_activos, padding=10)),
                ft.Tab(text="Levantamientos", icon=ft.Icons.ENGINEERING, content=ft.Container(col_levantamientos, padding=10)), 
                ft.Tab(text="Historial", icon=ft.Icons.HISTORY, content=ft.Container(col_historial, padding=10)),
            ], expand=True)
        ], expand=True), expand=True
    )