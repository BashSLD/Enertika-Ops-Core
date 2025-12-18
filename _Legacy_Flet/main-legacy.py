import flet as ft
from core.database import probar_conexion
from core.microsoft import MicrosoftAuth 
# Importamos la vista comercial
from modules.comercial.ui_tablero import ViewComercial 

# --- CONFIGURACIÓN DE ESTILO CORPORATIVO (ENERTIKA) ---
ESTILO = {
    "primary": "#123456",      # Azul Oscuro Corporativo
    "accent": "#00BABB",       # Turquesa
    "dark_grey": "#262626",    # Texto principal
    "light_grey": "#dfddd9",   # Fondos suaves
    "white": "#FFFFFF",
    "success": ft.Colors.GREEN_600,
    "error": ft.Colors.RED_600
}

def main(page: ft.Page):
    # 1. Configuración General
    page.title = "Enertika Operations Core V1.0"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window_width = 1280
    page.window_height = 720
    page.padding = 0
    page.bgcolor = ESTILO["light_grey"] 

    # Instancia de Autenticación
    ms_auth = MicrosoftAuth()

    # --- ELEMENTOS DE LOGIN ---
    # AGREGADO: selectable=True para que puedas copiar los errores
    lbl_status = ft.Text("", color=ESTILO["error"], text_align=ft.TextAlign.CENTER, selectable=True)

    def login_microsoft_click(e):
        lbl_status.value = "Redirigiendo a Microsoft..."
        lbl_status.color = ESTILO["primary"]
        page.update()
        try:
            # Iniciamos el flujo real de OAuth
            auth_url = ms_auth.get_auth_url()
            page.launch_url(auth_url, web_window_name="_self")
        except Exception as ex:
            lbl_status.value = f"Error al lanzar URL: {ex}"
            page.update()

    # --- NAVEGACIÓN (ROUTING) ---
    def cambiar_ruta(e):
        index = e.control.selected_index
        rutas = [
            "/comercial", 
            "/simulacion", 
            "/ingenieria", 
            "/compras", 
            "/construccion", 
            "/oym"
        ]
        if 0 <= index < len(rutas):
            page.go(rutas[index])

    # --- PANTALLA 1: LOGIN ---
    container_login = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.BOLT, size=100, color=ESTILO["accent"]), 
                ft.Text("Enertika Core", size=30, weight=ft.FontWeight.BOLD, color=ESTILO["primary"]),
                ft.Text("Plataforma de Operaciones Unificada", size=16, color=ESTILO["dark_grey"]),
                ft.Divider(height=20, color="transparent"),
                
                # Botón de Microsoft
                ft.ElevatedButton(
                    content=ft.Row([
                        # CORRECCION: Usamos ícono WINDOW que es valido
                        ft.Icon(ft.Icons.WINDOW, color=ESTILO["white"]),
                        ft.Text("Iniciar Sesión con Microsoft 365", weight="bold")
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
                    width=320,
                    on_click=login_microsoft_click,
                    style=ft.ButtonStyle(
                        bgcolor="#0078D4", # Azul Microsoft oficial
                        color=ESTILO["white"],
                        padding=20,
                        shape=ft.RoundedRectangleBorder(radius=8)
                    )
                ),
                ft.Container(height=10),
                lbl_status
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        alignment=ft.alignment.center,
        expand=True,
        bgcolor=ESTILO["white"]
    )

    # --- PANTALLA 2: LAYOUT PRINCIPAL ---
    def crear_layout_principal(contenido_central):
        return ft.Row(
            [
                # Barra Lateral
                ft.NavigationRail(
                    selected_index=0,
                    label_type=ft.NavigationRailLabelType.ALL,
                    min_width=100,
                    min_extended_width=200,
                    bgcolor=ESTILO["white"],
                    indicator_color=ESTILO["accent"],
                    destinations=[
                        ft.NavigationRailDestination(
                            icon=ft.Icons.GROUPS_OUTLINED, 
                            selected_icon=ft.Icons.GROUPS, 
                            label="Comercial" 
                        ),
                        ft.NavigationRailDestination(
                            icon=ft.Icons.SCIENCE_OUTLINED, 
                            selected_icon=ft.Icons.SCIENCE, 
                            label="Simulación"
                        ),
                        ft.NavigationRailDestination(
                            icon=ft.Icons.ENGINEERING_OUTLINED, 
                            selected_icon=ft.Icons.ENGINEERING, 
                            label="Ingeniería"
                        ),
                        ft.NavigationRailDestination(
                            icon=ft.Icons.SHOPPING_CART_OUTLINED, 
                            selected_icon=ft.Icons.SHOPPING_CART, 
                            label="Compras"
                        ),
                        ft.NavigationRailDestination(
                            icon=ft.Icons.CONSTRUCTION_OUTLINED, 
                            selected_icon=ft.Icons.CONSTRUCTION, 
                            label="Construcción"
                        ),
                        ft.NavigationRailDestination(
                            icon=ft.Icons.HANDYMAN_OUTLINED, 
                            selected_icon=ft.Icons.HANDYMAN, 
                            label="O&M"
                        ),
                    ],
                    on_change=cambiar_ruta,
                ),
                ft.VerticalDivider(width=1, color=ESTILO["light_grey"]),
                # Área de Contenido
                ft.Container(
                    content=contenido_central,
                    expand=True,
                    padding=20,
                    bgcolor=ESTILO["light_grey"]
                )
            ],
            expand=True,
        )

    # --- GESTOR DE RUTAS Y OAUTH ---
    def route_change(route):
        # 1. Interceptar el retorno de Microsoft (?code=...)
        if "code" in page.route:
            try:
                from urllib.parse import urlparse, parse_qs
                parsed_url = urlparse(page.route)
                code = parse_qs(parsed_url.query).get('code')
                
                if code:
                    lbl_status.value = "Autenticando..."
                    page.update()
                    # Canjeamos el código por el token real
                    ms_auth.get_token_from_code(code[0])
                    
                    # Si todo sale bien, vamos al dashboard
                    page.go("/comercial")
                    return
            except Exception as ex:
                lbl_status.value = f"Error de Login: {ex}"
                lbl_status.color = ESTILO["error"]
                # Forzamos update para ver el error
                page.update()
                # Esperamos un poco antes de regresar al login para que el usuario lea el error
                import time
                time.sleep(2)
                page.go("/login")
                return

        # 2. Manejo normal de vistas
        page.views.clear()
        
        if page.route == "/login" or page.route == "/":
            page.views.append(
                ft.View("/login", [container_login], padding=0)
            )
        
        elif page.route == "/comercial":
            # Validamos conexion a DB antes de cargar
            if probar_conexion():
                contenido_comercial = ViewComercial(page)
                page.views.append(
                    ft.View(
                        "/comercial", 
                        [crear_layout_principal(contenido_comercial)], 
                        padding=0,
                        bgcolor=ESTILO["light_grey"]
                    )
                )
            else:
                 page.snack_bar = ft.SnackBar(ft.Text("Error conectando a Supabase"), bgcolor="red")
                 page.snack_bar.open = True
                 page.go("/login")

        elif page.route == "/ingenieria":
            contenido = ft.Text("Módulo de Ingeniería en construcción", size=20, color=ESTILO["dark_grey"])
            page.views.append(
                ft.View("/ingenieria", [crear_layout_principal(contenido)], padding=0)
            )
            
        page.update()

    page.on_route_change = route_change
    
    # Comprobamos si la app se abrió con un codigo (redirect directo)
    if "code" in page.route:
        route_change(None)
    else:
        page.go("/login")

# IMPORTANTE: Puerto fijo 8550 para que coincida con Azure
ft.app(target=main, port=8550, view=ft.WEB_BROWSER, upload_dir="assets", assets_dir="assets", host="0.0.0.0")