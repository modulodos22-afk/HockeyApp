import flet as ft
import os
import time
from datetime import datetime
import base64
import platform

# --- PROTECCIÓN DE IMPORTS ---
# Intentamos cargar las librerías peligrosas con seguridad.
# Si fallan, la app NO se cierra, sino que guarda el error para mostrarlo.
ERROR_IMPORT = None
try:
    import gspread
    from google.oauth2 import service_account
    TIENE_GOOGLE = True
except Exception as e:
    TIENE_GOOGLE = False
    ERROR_IMPORT = str(e)

try:
    from fpdf import FPDF
    TIENE_PDF = True
except ImportError:
    TIENE_PDF = False

# --- COLORES ---
C_AZUL = "#2196F3"
C_VERDE = "#4CAF50"
C_ROJO = "#F44336"
C_FONDO = "#F5F5F5"
C_BLANCO = "#FFFFFF"
C_GRIS = "#E0E0E0"
C_GRIS_CLARO = "#F9F9F9"
C_VIOLETA = "#9C27B0"
C_AMARILLO = "#FFC107"
C_TEXTO = "#212121"
C_GRIS_TXT = "#757575"
C_ROSITA = "#FFC0CB"

def main(page: ft.Page):
    page.title = "Hockey App"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = C_FONDO
    
    # Intentamos configurar assets con seguridad
    try:
        page.assets_dir = "assets"
    except: pass

    # --- PANTALLA DE ERROR DE ARRANQUE ---
    # Si hubo un error cargando librerías (pantalla negra), lo mostramos acá.
    if ERROR_IMPORT:
        page.add(ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.BUG_REPORT, color="red", size=60),
                ft.Text("Error de Librerías", size=25, weight="bold", color="red"),
                ft.Text("La app no pudo cargar una herramienta:", size=16),
                ft.Container(
                    content=ft.Text(str(ERROR_IMPORT), color="white", font_family="monospace"),
                    bgcolor="black", padding=10, border_radius=5
                ),
                ft.Text("Por favor, revisá requirements.txt", color="grey")
            ], alignment="center", horizontal_alignment="center"),
            alignment=ft.alignment.center, expand=True, bgcolor="#FFEBEE"
        ))
        page.update()
        return # DETENEMOS TODO PARA QUE NO EXPLOTE

    # --- PANTALLA DE CARGA ---
    lbl_estado = ft.Text("Iniciando...", color="blue")
    page.add(ft.Container(
        content=ft.Column([
            ft.ProgressRing(),
            ft.Divider(height=10, color="transparent"),
            lbl_estado
        ], alignment="center", horizontal_alignment="center"),
        alignment=ft.alignment.center, expand=True
    ))
    page.update()

    # --- VARIABLES GLOBALES ---
    sh = None
    ws_jugadoras = None
    ws_habilidades = None
    ws_asistencia = None
    ws_partidos = None
    ws_fixture = None
    lista_jugadoras_raw = []
    
    cat_inicial = "Primera"
    club_inicial = "Mi Club"
    categoria_actual = [cat_inicial]
    club_actual = [club_inicial]

    # --- FUNCIÓN CONEXIÓN SEGURA ---
    def conectar_seguro():
        try:
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
                     "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
            
            # Buscamos credentials donde sea
            archivo = "credentials.json"
            if not os.path.exists(archivo):
                if os.path.exists("assets/credentials.json"):
                    archivo = "assets/credentials.json"
                else:
                    return None, "No encuentro credentials.json"

            creds = service_account.Credentials.from_service_account_file(archivo, scopes=scope)
            client = gspread.authorize(creds)
            return client.open("HockeyApp_DB"), "OK"
        except Exception as ex:
            return None, str(ex)

    # --- PROCESO DE CARGA ---
    try:
        lbl_estado.value = "Conectando a Google..."
        page.update()
        
        sh, msg = conectar_seguro()
        
        if not sh:
            raise Exception(f"Fallo conexión: {msg}")

        lbl_estado.value = "Leyendo datos..."
        page.update()

        ws_jugadoras = sh.worksheet("jugadoras")
        ws_habilidades = sh.worksheet("habilidades")
        ws_asistencia = sh.worksheet("asistencia")
        ws_partidos = sh.worksheet("partidos")
        try: ws_fixture = sh.worksheet("fixture")
        except: ws_fixture = None

        raw = ws_jugadoras.get_all_values()
        if len(raw) > 1:
            for row in raw[1:]:
                row += [""] * (9 - len(row))
                jug = {"id": row[0], "nombre": row[1], "apellido": row[2], "dni": row[3], "nacimiento": row[4], "posicion": row[5], "telefono": row[6], "activo": row[7], "camiseta": row[8]}
                if jug["dni"]: lista_jugadoras_raw.append(jug)

    except Exception as e:
        page.clean()
        page.add(ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.WIFI_OFF, color="orange", size=50),
                ft.Text("Error de Conexión", size=20, weight="bold"),
                ft.Text(str(e), size=14, text_align="center"),
                ft.ElevatedButton("Reintentar", on_click=lambda _: page.window_reload())
            ], alignment="center", horizontal_alignment="center"),
            alignment=ft.alignment.center, expand=True
        ))
        page.update()
        return

    # =================================================================
    #  SI LLEGAMOS ACÁ, LA APP FUNCIONA. AHORA DEFINIMOS LA INTERFAZ
    # =================================================================

    columna_contenido = ft.Column(expand=True, scroll="auto")
    txt_info = ft.Text("🟢 Online", color="green", size=12)
    
    # --- HELPERS ---
    MAPA_MESES = {"Enero":1,"Febrero":2,"Marzo":3,"Abril":4,"Mayo":5,"Junio":6,"Julio":7,"Agosto":8,"Septiembre":9,"Octubre":10,"Noviembre":11,"Diciembre":12}
    LISTA_MESES = list(MAPA_MESES.keys())
    TITULOS_SKILLS = ["Push", "Dribbling", "Flick", "Pegada", "Barrida", "Físico", "Quites"]
    LETRAS_DIAS = ["L", "M", "M", "J", "V", "S", "D"]

    def safe_int(val):
        try: return int(float(str(val))) if val else 0
        except: return 0

    def calcular_edad(fecha_nac):
        try:
            fmt = "%d/%m/%Y" if "/" in str(fecha_nac) else "%d-%m-%Y"
            nac = datetime.strptime(str(fecha_nac), fmt)
            hoy = datetime.now()
            return str(hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day)))
        except: return "?"

    def clean_latin(t):
        if not t: return ""
        try: return str(t).encode('latin-1', 'replace').decode('latin-1')
        except: return str(t)

    # --- DEFINICIÓN VISTA ASISTENCIA ---
    def vista_asistencia():
        txt_fecha = ft.Text(f"📅 {datetime.now().strftime('%d/%m/%Y')}", size=16, weight="bold")
        
        col_lista = ft.Column()
        for i, jug in enumerate(lista_jugadoras_raw):
            dni = str(jug['dni']); nombre = f"{jug['apellido']} {jug['nombre']}"
            
            # Botones simples que cambian de color (Lógica visual directa)
            def cambiar_estado(e, d=dni):
                # Aquí iría la lógica de guardar en memoria temporal
                e.control.bgcolor = "green" if e.control.text == "P" else "red"
                e.control.color = "white"
                e.control.update()

            btn_p = ft.ElevatedButton("P", width=40, on_click=cambiar_estado)
            btn_a = ft.ElevatedButton("A", width=40, on_click=cambiar_estado)
            
            fila = ft.Container(
                content=ft.Row([
                    ft.Text(nombre, weight="bold", expand=True),
                    btn_p, btn_a
                ]),
                padding=10, bgcolor="white" if i%2==0 else "#F0F0F0"
            )
            col_lista.controls.append(fila)
            
        return ft.Column([
            ft.Text("Tomar Asistencia", size=20, weight="bold", color=C_AZUL),
            txt_fecha,
            ft.Divider(),
            col_lista,
            ft.ElevatedButton("Simular Guardado (Demo)", bgcolor=C_AZUL, color="white")
        ], scroll="auto")

    # --- DEFINICIÓN VISTA PLANTEL ---
    def vista_plantel():
        items = []
        for j in lista_jugadoras_raw:
            card = ft.Container(
                content=ft.Row([
                    ft.Text("👤", size=20),
                    ft.Column([
                        ft.Text(f"{j['apellido']} {j['nombre']}", weight="bold"),
                        ft.Text(f"DNI: {j['dni']}", size=12)
                    ])
                ]),
                padding=10, border=ft.Border.all(1, "#EEE"), border_radius=5
            )
            items.append(card)
        return ft.Column([ft.Text("Mi Plantel", size=20, weight="bold"), ft.Column(items)])

    # --- NAVEGACIÓN ---
    def navegar(e):
        destino = e.control.data if hasattr(e, "control") else "asis"
        columna_contenido.controls.clear()
        
        if destino == "asis": columna_contenido.controls.append(vista_asistencia())
        elif destino == "plantel": columna_contenido.controls.append(vista_plantel())
        else: columna_contenido.controls.append(ft.Text(f"Sección {destino} en construcción"))
        
        page.update()

    # --- MENU ---
    btn_s = ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=0), color=C_BLANCO)
    menu = ft.Container(content=ft.Row([
        ft.ElevatedButton("📝", data="asis", on_click=navegar, bgcolor=C_AZUL, style=btn_s, expand=True),
        ft.ElevatedButton("👤", data="plantel", on_click=navegar, bgcolor="#607D8B", style=btn_s, expand=True),
    ], spacing=0), padding=0)

    page.clean()
    page.add(
        menu,
        ft.Container(content=columna_contenido, padding=10, expand=True),
        ft.Container(content=txt_info, padding=5, bgcolor="#EEE")
    )
    navegar(ft.Control(data="asis")) # Iniciar

if __name__ == "__main__":
    ft.app(target=main)
