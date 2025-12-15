import flet as ft
from core.database import probar_conexion
# IMPORTANTE: Importamos con el nuevo nombre
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
    page.title = "Enertika Operations Core"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window_width = 1280
    page.window_height = 720
    page.padding = 0
    page.bgcolor = ESTILO["light_grey"] 

    # --- ELEMENTOS DE LOGIN ---
    txt_password = ft.TextField(
        label="Contraseña de Acceso", 
        password=True, 
        can_reveal_password=True,
        width=300,
        border_color=ESTILO["primary"],
        color=ESTILO["dark_grey"]
    )
    
    lbl_status = ft.Text("", color=ESTILO["error"])

    # --- NAVEGACIÓN (ROUTING) ---
    def cambiar_ruta(e):
        index = e.control.selected_index
        rutas = [
            "/ventas", 
            "/simulacion", 
            "/ingenieria", 
            "/compras", 
            "/construccion", 
            "/oym"
        ]
        if 0 <= index < len(rutas):
            page.go(rutas[index])

    # --- PANTALLA 1: LOGIN ---
    def login_click(e):
        if txt_password.value == "admin123": 
            lbl_status.value = "Conectando con Supabase..."
            lbl_status.color = ESTILO["success"]
            page.update()
            
            if probar_conexion():
                page.go("/ventas") 
            else:
                lbl_status.value = "Error: No se pudo conectar a la BD"
                lbl_status.color = ESTILO["error"]
                page.update()
        else:
            lbl_status.value = "Contraseña incorrecta"
            page.update()

    container_login = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.BOLT, size=100, color=ESTILO["accent"]), 
                ft.Text("Enertika Core", size=30, weight=ft.FontWeight.BOLD, color=ESTILO["primary"]),
                ft.Text("Plataforma de Operaciones Unificada", size=16, color=ESTILO["dark_grey"]),
                ft.Divider(height=20, color="transparent"),
                txt_password,
                ft.ElevatedButton(
                    "Ingresar al Sistema", 
                    on_click=login_click,
                    style=ft.ButtonStyle(
                        bgcolor=ESTILO["primary"],
                        color=ESTILO["white"],
                        padding=20,
                        shape=ft.RoundedRectangleBorder(radius=8)
                    )
                ),
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
                            label="Comercial" # Nombre actualizado
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

    # --- GESTOR DE RUTAS ---
    def route_change(route):
        page.views.clear()
        
        if page.route == "/login":
            page.views.append(
                ft.View("/login", [container_login], padding=0)
            )
        
        elif page.route == "/ventas":
            # CORRECCIÓN AQUÍ: Llamamos a ViewComercial
            contenido_comercial = ViewComercial(page)
            page.views.append(
                ft.View(
                    "/ventas", 
                    [crear_layout_principal(contenido_comercial)], 
                    padding=0,
                    bgcolor=ESTILO["light_grey"]
                )
            )

        elif page.route == "/ingenieria":
            contenido = ft.Text("Módulo de Ingeniería en construcción", size=20, color=ESTILO["dark_grey"])
            page.views.append(
                ft.View("/ingenieria", [crear_layout_principal(contenido)], padding=0)
            )
            
        page.update()

    page.on_route_change = route_change
    page.go("/login")

ft.app(target=main)