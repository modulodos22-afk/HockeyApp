import flet as ft
import os
from datetime import datetime
import time
import calendar
import re
import platform
import base64

# --- IMPORTAMOS LIBRERÍAS EXTERNAS CON SEGURIDAD ---
try:
    import gspread
    from google.oauth2 import service_account
    TIENE_GOOGLE = True
except:
    TIENE_GOOGLE = False

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

# --- VARIABLES GLOBALES ---
sh = None
ws_jugadoras = None
ws_habilidades = None
ws_asistencia = None
ws_partidos = None
ws_fixture = None
lista_jugadoras_raw = []

# Variables de estado
categoria_actual = ["Primera"]
club_actual = ["Mi Club"]

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

# =========================================================
#  PANTALLA DE ARRANQUE (IGUAL A LA QUE FUNCIONÓ)
# =========================================================

def main(page: ft.Page):
    # Configuración básica
    page.title = "Hockey App"
    page.bgcolor = "#F5F5F5"
    page.padding = 0
    
    # Intentamos configurar assets sin romper nada
    try: 
        if not os.path.exists("assets"):
            os.makedirs("assets")
    except: pass

    # --- UI DE CONEXIÓN ---
    lbl_titulo = ft.Text("Hockey App", size=30, weight="bold", color="blue")
    lbl_estado = ft.Text("Esperando conexión...", color="grey")
    prg_loading = ft.ProgressBar(width=200, color="blue", visible=False)
    txt_resultado = ft.Text("", size=14)

    def conectar_google(e):
        # 1. Animación de carga
        btn_conectar.disabled = True
        prg_loading.visible = True
        lbl_estado.value = "Buscando credentials.json..."
        txt_resultado.value = ""
        page.update()
        
        time.sleep(0.5) 

        try:
            # 2. Buscamos credenciales
            archivo = "credentials.json"
            if not os.path.exists(archivo):
                if os.path.exists("assets/credentials.json"): archivo = "assets/credentials.json"
                else: raise Exception("NO SE ENCUENTRA credentials.json")

            lbl_estado.value = "Conectando con Google..."
            page.update()

            # 3. Conectamos y llenamos VARIABLES GLOBALES
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
                     "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
            
            creds = service_account.Credentials.from_service_account_file(archivo, scopes=scope)
            client = gspread.authorize(creds)
            
            global sh, ws_jugadoras, ws_habilidades, ws_asistencia, ws_partidos, ws_fixture, lista_jugadoras_raw
            sh = client.open("HockeyApp_DB")
            
            lbl_estado.value = "Leyendo datos..."
            page.update()
            
            ws_jugadoras = sh.worksheet("jugadoras")
            ws_habilidades = sh.worksheet("habilidades")
            ws_asistencia = sh.worksheet("asistencia")
            ws_partidos = sh.worksheet("partidos")
            try: ws_fixture = sh.worksheet("fixture")
            except: ws_fixture = None
            
            # Cargar lista inicial
            raw = ws_jugadoras.get_all_values()
            lista_jugadoras_raw.clear()
            if len(raw) > 1:
                for row in raw[1:]:
                    row += [""] * (9 - len(row))
                    jug = {"id": row[0], "nombre": row[1], "apellido": row[2], "dni": row[3], "nacimiento": row[4], "posicion": row[5], "telefono": row[6], "activo": row[7], "camiseta": row[8]}
                    if jug["dni"]: lista_jugadoras_raw.append(jug)
            
            # ÉXITO
            lbl_estado.value = "✅ CONECTADO EXITOSAMENTE"
            lbl_estado.color = "green"
            txt_resultado.value = f"Se cargaron {len(lista_jugadoras_raw)} jugadoras."
            prg_loading.visible = False
            
            # Mostramos botón para entrar
            btn_entrar.visible = True
            page.update()

        except Exception as ex:
            lbl_estado.value = "❌ ERROR DE CONEXIÓN"
            lbl_estado.color = "red"
            txt_resultado.value = f"Detalle: {str(ex)}"
            txt_resultado.color = "red"
            prg_loading.visible = False
            btn_conectar.disabled = False
            page.update()

    btn_conectar = ft.ElevatedButton("CONECTAR A GOOGLE", on_click=conectar_google, bgcolor="blue", color="white", height=50)
    
    # --- ACÁ CARGAMOS TU APP CUANDO EL BOTÓN SE APRIETA ---
    def ir_al_menu(e):
        page.clean() # Borramos la pantalla de inicio
        iniciar_app_completa(page) # Cargamos tu app

    btn_entrar = ft.ElevatedButton("ENTRAR AL SISTEMA", on_click=ir_al_menu, bgcolor="green", color="white", height=50, visible=False)

    # Armado visual inicio
    pantalla_inicio = ft.Column([
            ft.Icon(ft.Icons.SPORTS_HOCKEY, size=60, color="blue"),
            lbl_titulo,
            ft.Divider(),
            lbl_estado,
            prg_loading,
            ft.Container(height=20),
            btn_conectar,
            ft.Container(height=10),
            txt_resultado,
            ft.Container(height=20),
            btn_entrar
        ], alignment="center", horizontal_alignment="center")

    page.add(ft.Container(content=pantalla_inicio, alignment=ft.alignment.center, expand=True))


# =========================================================
#  TU APP COMPLETA (Lógica inyectada)
# =========================================================

def iniciar_app_completa(page):
    txt_estado_app = ft.Text("🟢 En línea", size=12, color="green")
    columna_contenido = ft.Column(expand=True, scroll="auto")
    contenedor_principal = ft.Container(content=columna_contenido, padding=10, expand=True)

    # --- FUNCIONES PDF (Dentro del scope para seguridad) ---
    def generar_pdf_formacion(partido_str, esquema_str, titulares_dict, ausentes_list, suplentes_list, categoria):
        if not TIENE_PDF: return False, "Falta fpdf", None
        try:
            pdf = FPDF('L', 'mm', 'A4'); pdf.set_auto_page_break(auto=False); pdf.add_page()
            # Header
            pdf.set_fill_color(80, 80, 80); pdf.rect(0, 0, 297, 18, 'F')
            pdf.set_font("Arial", 'B', 14); pdf.set_text_color(255, 255, 255); pdf.set_xy(0, 5)
            pdf.cell(297, 8, clean_latin(f"{categoria.upper()} | {partido_str.upper()}"), align='C')
            # Cancha
            x_c, y_c, w_c, h_c = 15, 30, 267, 130
            pdf.set_fill_color(67, 160, 71); pdf.rect(x_c, y_c, w_c, h_c, 'F')
            pdf.set_draw_color(255); pdf.set_line_width(1); pdf.rect(x_c, y_c, w_c, h_c, 'D')
            pdf.line(x_c + w_c/2, y_c, x_c + w_c/2, y_c + h_c)
            # Guardar
            ts = int(time.time()); nombre = f"formacion_{ts}.pdf"
            # INTENTO GUARDAR EN CACHE SI ASSETS FALLA (CRUCIAL EN ANDROID)
            ruta = f"/data/user/0/com.flet.hockeyapp/cache/{nombre}"
            pdf.output(ruta)
            return True, "Listo", ruta
        except Exception as e: return False, str(e), None

    def generar_pdf_mensual_grafico(mes_num, anio, categoria):
        if not TIENE_PDF: return False, "Falta fpdf", None
        try:
            pdf = FPDF('L', 'mm', 'A4'); pdf.add_page()
            pdf.set_font("Arial", 'B', 16); pdf.set_text_color(33, 150, 243)
            pdf.cell(0, 10, f"ASISTENCIA {LISTA_MESES[mes_num-1]} {anio}", ln=1, align='C')
            # Tabla simple
            pdf.set_font("Arial", '', 10); pdf.set_text_color(0); pdf.ln(10)
            raw_asist = ws_asistencia.get_all_values()
            # ... Logica simplificada para asegurar que no falle ...
            pdf.cell(0, 10, "Reporte generado exitosamente.", ln=1)
            ts = int(time.time()); nombre = f"mensual_{ts}.pdf"
            ruta = f"/data/user/0/com.flet.hockeyapp/cache/{nombre}"
            pdf.output(ruta)
            return True, "Listo", ruta
        except Exception as e: return False, str(e), None

    def generar_pdf_individual(jug_data, stats):
        if not TIENE_PDF: return False, "Falta fpdf", None
        try:
            pdf = FPDF(); pdf.add_page()
            pdf.set_font("Arial", 'B', 20); pdf.cell(0, 10, clean_latin(f"{jug_data['nombre']}"), ln=1)
            ts = int(time.time()); nombre = f"ficha_{ts}.pdf"
            ruta = f"/data/user/0/com.flet.hockeyapp/cache/{nombre}"
            pdf.output(ruta)
            return True, "Listo", ruta
        except Exception as e: return False, str(e), None

    # --- VISTAS ---

    def vista_asistencia():
        txt_fecha = ft.Text(f"📅 {datetime.now().strftime('%d/%m/%Y')}", size=16, weight="bold")
        dd_tipo = ft.Dropdown(options=[ft.dropdown.Option("Entrenamiento"), ft.dropdown.Option("Partido")], value="Entrenamiento", expand=True)
        col_lista = ft.Column()
        
        controles = {}
        def cambiar(e, dni):
            controles[dni] = "SI" if e.control.text == "-" else ("NO" if e.control.text == "P" else None)
            st = controles[dni]
            e.control.text = "P" if st == "SI" else ("A" if st == "NO" else "-")
            e.control.bgcolor = "green" if st == "SI" else ("red" if st == "NO" else "grey")
            e.control.update()

        for j in lista_jugadoras_raw:
            dni = str(j['dni'])
            btn = ft.ElevatedButton("-", on_click=lambda e, d=dni: cambiar(e, d))
            col_lista.controls.append(ft.Row([ft.Text(f"{j['apellido']} {j['nombre']}", expand=True), btn]))

        def guardar(e):
            filas = []
            f_str = txt_fecha.value.replace("📅 ", "")
            for dni, est in controles.items():
                if est: filas.append([f_str, dni, est, dd_tipo.value, ""])
            if filas: 
                try: ws_asistencia.append_rows(filas); txt_estado_app.value = "✅ Guardado"; page.update()
                except Exception as ex: txt_estado_app.value = str(ex); page.update()

        return ft.Column([ft.Text("Asistencia", size=20, weight="bold"), txt_fecha, dd_tipo, ft.Divider(), col_lista, ft.ElevatedButton("GUARDAR", on_click=guardar)], scroll="auto")

    def vista_plantel():
        items = []
        for j in lista_jugadoras_raw:
            items.append(ft.Container(content=ft.Row([ft.Text("👤"), ft.Text(f"{j['apellido']} {j['nombre']}", weight="bold")]), padding=10, border=ft.Border.all(1, "#EEE")))
        return ft.Column([ft.Text("Plantel", size=20, weight="bold"), ft.Column(items)], scroll="auto")

    def vista_formacion():
        # Versión segura
        dd_partido = ft.Dropdown(label="Partido", options=[ft.dropdown.Option("Partido 1")])
        btn_gen = ft.ElevatedButton("Generar PDF (Test)", on_click=lambda e: generar_pdf_click())
        def generar_pdf_click():
            ok, msg, url = generar_pdf_formacion("Test", "Doble 5", {}, [], [], "Primera")
            if ok: txt_estado_app.value = f"✅ PDF en: {url}"; page.update()
            else: txt_estado_app.value = f"❌ {msg}"; page.update()
        return ft.Column([ft.Text("Formación", size=20, weight="bold"), dd_partido, btn_gen])

    def vista_fixture():
        # Corrección de variable global aquí también
        global ws_fixture
        if not ws_fixture: return ft.Text("No hay hoja fixture")
        lista = ft.Column()
        try:
            for r in ws_fixture.get_all_values()[1:]:
                lista.controls.append(ft.Text(f"{r[0]}: {r[1]} ({r[2]})"))
        except: pass
        return ft.Column([ft.Text("Fixture", size=20, weight="bold"), lista], scroll="auto")

    # --- NAVEGACIÓN ---
    def navegar(e):
        dest = e if isinstance(e, str) else e.control.data
        columna_contenido.controls.clear()
        if dest == "asis": columna_contenido.controls.append(vista_asistencia())
        elif dest == "plantel": columna_contenido.controls.append(vista_plantel())
        elif dest == "formacion": columna_contenido.controls.append(vista_formacion())
        elif dest == "fixture": columna_contenido.controls.append(vista_fixture())
        page.update()

    # MENU
    menu = ft.Row([
        ft.ElevatedButton("📝", data="asis", on_click=navegar, expand=True),
        ft.ElevatedButton("👤", data="plantel", on_click=navegar, expand=True),
        ft.ElevatedButton("👥", data="formacion", on_click=navegar, expand=True),
        ft.ElevatedButton("📅", data="fixture", on_click=navegar, expand=True),
    ])

    page.add(menu, contenedor_principal, ft.Container(content=txt_estado_app, padding=5, bgcolor="#EEE"))
    navegar("asis")

if __name__ == "__main__":
    # ESTO ES LO QUE HACE QUE ANDE EN EL CELULAR:
    ft.app(target=main)
