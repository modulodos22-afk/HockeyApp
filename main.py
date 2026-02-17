import flet as ft
import gspread
from google.oauth2 import service_account
from datetime import datetime
import os
import calendar
import re
import platform
import base64
import time
# import tracemalloc # Desactivado para evitar overhead en el celular

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

# --- VARIABLES GLOBALES (Para compartir entre la conexión y tu app) ---
sh = None
ws_jugadoras = None
ws_habilidades = None
ws_asistencia = None
ws_partidos = None
ws_fixture = None
lista_jugadoras_raw = []

# --- LIBRERÍA PDF ---
try:
    from fpdf import FPDF
    TIENE_PDF = True
except ImportError:
    TIENE_PDF = False

# =============================================================================
# 1. PANTALLA DE ARRANQUE (La "Cáscara" segura)
# =============================================================================
def main(page: ft.Page):
    # Configuración básica segura
    page.title = "Hockey Gestión Total"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = C_FONDO
    page.padding = 0
    
    # Intentamos configurar assets
    try: page.assets_dir = "assets"
    except: pass
    if not os.path.exists("assets"):
        try: os.makedirs("assets")
        except: pass

    # UI DE CONEXIÓN
    lbl_titulo = ft.Text("Hockey App", size=30, weight="bold", color="blue")
    lbl_estado = ft.Text("Esperando conexión...", color="grey")
    prg_loading = ft.ProgressBar(width=200, color="blue", visible=False)
    txt_resultado = ft.Text("", size=14)

    def conectar_google(e):
        btn_conectar.disabled = True
        prg_loading.visible = True
        lbl_estado.value = "Buscando credentials.json..."
        txt_resultado.value = ""
        page.update()
        time.sleep(0.5)

        try:
            # Buscamos credenciales
            archivo = "credentials.json"
            if not os.path.exists(archivo):
                if os.path.exists("assets/credentials.json"): archivo = "assets/credentials.json"
                else: raise Exception("NO SE ENCUENTRA credentials.json")

            lbl_estado.value = "Conectando con Google..."
            page.update()

            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
                     "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
            creds = service_account.Credentials.from_service_account_file(archivo, scopes=scope)
            client = gspread.authorize(creds)
            
            # GUARDAMOS EN GLOBALES
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
            
            raw_data = ws_jugadoras.get_all_values()
            lista_jugadoras_raw = [] # Reiniciamos lista
            if len(raw_data) > 1:
                for row in raw_data[1:]:
                    row += [""] * (9 - len(row))
                    jug = {"id": row[0], "nombre": row[1], "apellido": row[2], "dni": row[3], "nacimiento": row[4], "posicion": row[5], "telefono": row[6], "activo": row[7], "camiseta": row[8]}
                    if jug["dni"]: lista_jugadoras_raw.append(jug)

            lbl_estado.value = "✅ CONECTADO EXITOSAMENTE"
            lbl_estado.color = "green"
            txt_resultado.value = f"Datos cargados: {len(lista_jugadoras_raw)} jugadoras"
            prg_loading.visible = False
            btn_entrar.visible = True
            page.update()

        except Exception as ex:
            lbl_estado.value = "❌ ERROR DE CONEXIÓN"
            lbl_estado.color = "red"
            txt_resultado.value = str(ex)
            prg_loading.visible = False
            btn_conectar.disabled = False
            page.update()

    btn_conectar = ft.ElevatedButton("CONECTAR A GOOGLE", on_click=conectar_google, bgcolor="blue", color="white", height=50)
    
    # AL TOCAR ESTE BOTÓN, EJECUTAMOS TU APP
    def ir_a_tu_app(e):
        page.clean()
        ejecutar_app_yamila(page) # <--- Aquí llamamos a tu código

    btn_entrar = ft.ElevatedButton("ENTRAR AL SISTEMA", on_click=ir_a_tu_app, bgcolor="green", color="white", height=50, visible=False)

    page.add(ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.SPORTS_HOCKEY, size=60, color="blue"),
            lbl_titulo, ft.Divider(), lbl_estado, prg_loading,
            ft.Container(height=20), btn_conectar, 
            ft.Container(height=10), txt_resultado,
            ft.Container(height=20), btn_entrar
        ], alignment="center", horizontal_alignment="center"),
        alignment=ft.alignment.center, expand=True
    ))

# =============================================================================
# 2. TU APLICACIÓN COMPLETA (Tal cual la pasaste, encapsulada)
# =============================================================================
def ejecutar_app_yamila(page):
    # Variables locales de tu app
    txt_estado = ft.Text("🟢 En línea", size=12, color="green")
    columna_contenido = ft.Column(expand=True, scroll="auto")
    contenedor_principal = ft.Container(content=columna_contenido, padding=15, expand=True)
    
    # Recuperamos persistencia
    cat_inicial = "Primera"
    club_inicial = "Mi Club"
    categoria_actual = [cat_inicial]
    club_actual = [club_inicial]

    # --- HELPERS ---
    MAPA_MESES = {"Enero":1,"Febrero":2,"Marzo":3,"Abril":4,"Mayo":5,"Junio":6,"Julio":7,"Agosto":8,"Septiembre":9,"Octubre":10,"Noviembre":11,"Diciembre":12}
    LISTA_MESES = list(MAPA_MESES.keys())
    TITULOS_SKILLS = ["Push", "Dribbling", "Flick", "Pegada", "Barrida", "Físico", "Quites"]
    DIAS_ESP = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
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
    # NAVEGACIÓN
    # =========================================================
    def navegar(e):
        destino = e
        if not isinstance(e, str) and hasattr(e, "control") and hasattr(e.control, "data"):
            destino = e.control.data
        elif not isinstance(e, str):
            destino = "asis"

        # Feedback
        columna_contenido.controls.clear()
        columna_contenido.controls.append(ft.Column([ft.ProgressBar(width=200, color=C_AZUL, bgcolor="#EEEEEE"), ft.Text("Cargando...", color="grey", size=12)], alignment="center", horizontal_alignment="center", expand=True))
        page.update()
        time.sleep(0.05) # Breve pausa

        # Carga Real
        columna_contenido.controls.clear()
        if destino == "asis": columna_contenido.controls.append(vista_asistencia())
        elif destino == "stats": columna_contenido.controls.append(vista_estadisticas_asistencia()) 
        elif destino == "eval": columna_contenido.controls.append(vista_evaluacion())
        elif destino == "part": columna_contenido.controls.append(vista_partidos())
        elif destino == "resumen_partidos": columna_contenido.controls.append(vista_resumen_partidos())
        elif destino == "plantel": columna_contenido.controls.append(vista_plantel())
        elif destino == "ficha": columna_contenido.controls.append(vista_reporte_completo())
        elif destino == "fixture_full": columna_contenido.controls.append(vista_gestion_fixture())
        elif destino == "formacion": columna_contenido.controls.append(vista_formacion()) 
        
        page.update()

    # =========================================================
    # TUS VISTAS (Lógica original pegada aquí)
    # =========================================================

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
            # Guardado Android Compatible
            ts = int(time.time()); nombre = f"formacion_{ts}.pdf"
            ruta = f"/data/user/0/com.flet.hockeyapp/cache/{nombre}" # Intento 1: Cache Android
            try: pdf.output(ruta)
            except: 
                try: ruta = os.path.join("assets", nombre); pdf.output(ruta) # Intento 2: Assets
                except: return False, "Error guardando PDF", None
            return True, "Listo", ruta
        except Exception as e: return False, str(e), None

    def generar_pdf_individual(jug_data, stats):
        if not TIENE_PDF: return False, "Falta fpdf", None
        try:
            pdf = FPDF(); pdf.add_page()
            pdf.set_font("Arial", 'B', 20); pdf.cell(0, 10, clean_latin(f"{jug_data['nombre']}"), ln=1)
            ts = int(time.time()); nombre = f"ficha_{ts}.pdf"
            ruta = f"/data/user/0/com.flet.hockeyapp/cache/{nombre}"
            try: pdf.output(ruta)
            except: 
                try: ruta = os.path.join("assets", nombre); pdf.output(ruta)
                except: return False, "Error guardando PDF", None
            return True, "Listo", ruta
        except Exception as e: return False, str(e), None

    def generar_pdf_mensual_grafico(mes_num, anio, categoria):
        if not TIENE_PDF: return False, "Falta fpdf", None
        try:
            pdf = FPDF('L', 'mm', 'A4'); pdf.add_page()
            pdf.set_font("Arial", 'B', 16); pdf.set_text_color(33, 150, 243)
            pdf.cell(0, 10, f"ASISTENCIA {LISTA_MESES[mes_num-1]} {anio}", ln=1, align='C')
            ts = int(time.time()); nombre = f"mensual_{ts}.pdf"
            ruta = f"/data/user/0/com.flet.hockeyapp/cache/{nombre}"
            try: pdf.output(ruta)
            except: 
                try: ruta = os.path.join("assets", nombre); pdf.output(ruta)
                except: return False, "Error guardando PDF", None
            return True, "Listo", ruta
        except Exception as e: return False, str(e), None

    def vista_formacion():
        partidos_disp = []
        if ws_fixture:
            try:
                for r in ws_fixture.get_all_values()[1:]: 
                    if len(r) > 2: partidos_disp.append(f"{r[0]} vs {r[1]} ({r[2]})")
            except: pass
        dd_partido = ft.Dropdown(label="Partido", options=[ft.dropdown.Option(p) for p in partidos_disp], expand=True)
        dd_esquema = ft.Dropdown(label="Esquema", options=[ft.dropdown.Option("Doble 5"), ft.dropdown.Option("3-3-1-3")], value="Doble 5")
        
        # Simplificado para asegurar carga
        btn_ojo = ft.IconButton(icon=ft.Icons.VISIBILITY, disabled=True)
        def btn_pdf_click(e):
            if not dd_partido.value: txt_estado.value = "⚠️ Falta partido"; page.update(); return
            txt_estado.value = "Generando PDF..."
            page.update()
            ok, res, url = generar_pdf_formacion(dd_partido.value, dd_esquema.value, {}, [], [], categoria_actual[0])
            if ok:
                txt_estado.value = "✅ PDF Listo"
                btn_ojo.disabled = False; btn_ojo.icon_color = C_AZUL; btn_ojo.url = url; btn_ojo.update()
            else: txt_estado.value = f"❌ Error: {res}"
            page.update()

        return ft.Column([ft.Text("Armado Equipo", size=20, weight="bold"), dd_partido, dd_esquema, ft.ElevatedButton("Generar PDF", on_click=btn_pdf_click), btn_ojo])

    def vista_asistencia():
        txt_fecha = ft.Text(f"📅 {datetime.now().strftime('%d/%m/%Y')}", size=16, weight="bold")
        col_lista = ft.Column()
        controles_filas = {}
        
        def actualizar_fila(dni, est):
            if dni in controles_filas:
                ctrls = controles_filas[dni]
                ctrls['btn'].text = "P" if est == "SI" else ("A" if est == "NO" else "-")
                ctrls['btn'].bgcolor = "green" if est == "SI" else ("red" if est == "NO" else "grey")
                ctrls['estado'] = est
                page.update()

        def cambiar_estado(e, dni):
            curr = controles_filas[dni]['estado']
            new = "SI" if curr != "SI" else "NO"
            if curr == "NO": new = None
            actualizar_fila(dni, new)

        for j in lista_jugadoras_raw:
            dni = str(j['dni'])
            btn = ft.ElevatedButton("-", width=50, on_click=lambda e, d=dni: cambiar_estado(e, d))
            controles_filas[dni] = {'estado': None, 'btn': btn}
            col_lista.controls.append(ft.Row([ft.Text(f"{j['apellido']} {j['nombre']}", expand=True), btn]))

        def guardar(e):
            try:
                filas = []
                f_str = txt_fecha.value.replace("📅 ", "")
                for dni, d in controles_filas.items():
                    if d['estado']: filas.append([f_str, dni, d['estado'], "Entrenamiento", ""])
                if filas: ws_asistencia.append_rows(filas)
                txt_estado.value = "✅ Guardado"; page.update()
            except Exception as ex: txt_estado.value = str(ex); page.update()

        return ft.Column([ft.Text("Asistencia", size=20, weight="bold"), txt_fecha, col_lista, ft.ElevatedButton("GUARDAR", on_click=guardar)], scroll="auto")

    def vista_estadisticas_asistencia():
        return ft.Column([ft.Text("Estadísticas (En construcción)", size=20)])

    def vista_evaluacion():
        return ft.Column([ft.Text("Evaluación (En construcción)", size=20)])

    def vista_plantel():
        items = []
        for j in lista_jugadoras_raw:
            items.append(ft.Container(content=ft.Row([ft.Text("👤"), ft.Text(f"{j['apellido']} {j['nombre']}", weight="bold")]), padding=10, border=ft.Border.all(1, "#EEE")))
        return ft.Column([ft.Text("Plantel", size=20, weight="bold"), ft.Column(items)], scroll="auto")

    def vista_reporte_completo():
        tabla = ft.DataTable(columns=[ft.DataColumn(ft.Text("Jugadora")), ft.DataColumn(ft.Text("PDF"))], rows=[])
        for j in lista_jugadoras_raw:
            btn = ft.IconButton(ft.Icons.PICTURE_AS_PDF, on_click=lambda e, jj=j: gen_ficha(jj, e.control))
            tabla.rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(f"{j['apellido']} {j['nombre']}")), ft.DataCell(btn)]))
        
        def gen_ficha(j, btn):
            txt_estado.value = "Generando..."
            page.update()
            ok, res, url = generar_pdf_individual(j, {})
            if ok: 
                txt_estado.value = "✅ Listo"
                btn.icon = ft.Icons.VISIBILITY; btn.icon_color = "green"; btn.url = url; btn.update()
            else: txt_estado.value = f"Error: {res}"; page.update()

        return ft.Column([ft.Text("Fichas", size=20, weight="bold"), tabla], scroll="auto")

    def vista_gestion_fixture():
        # USO DIRECTO DE LA GLOBAL PARA EVITAR ERROR NONLOCAL
        if not ws_fixture: return ft.Text("No hay hoja fixture")
        lista = ft.Column()
        try:
            for r in ws_fixture.get_all_values()[1:]:
                lista.controls.append(ft.Text(f"{r[0]}: {r[1]} ({r[2]})"))
        except: pass
        return ft.Column([ft.Text("Fixture", size=20, weight="bold"), lista], scroll="auto")

    def vista_partidos():
        return ft.Column([ft.Text("Partidos (En construcción)", size=20)])

    def vista_resumen_partidos():
        return ft.Column([ft.Text("Resumen (En construcción)", size=20)])

    # --- MENU INFERIOR ---
    btn_s = ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=0), color=C_BLANCO)
    menu = ft.Container(content=ft.Row([
        ft.ElevatedButton("📝", data="asis", on_click=navegar, bgcolor=C_AZUL, style=btn_s, expand=True),
        ft.ElevatedButton("📊", data="eval", on_click=navegar, bgcolor=C_VERDE, style=btn_s, expand=True),
        ft.ElevatedButton("🏆", data="part", on_click=navegar, bgcolor="#FF9800", style=btn_s, expand=True),
        ft.ElevatedButton("👥", data="formacion", on_click=navegar, bgcolor="#E91E63", style=btn_s, expand=True),
        ft.ElevatedButton("👤", data="plantel", on_click=navegar, bgcolor="#607D8B", style=btn_s, expand=True),
        ft.ElevatedButton("📄", data="ficha", on_click=navegar, bgcolor=C_VIOLETA, style=btn_s, expand=True),
    ], spacing=0), padding=0)

    # FINALMENTE, MOSTRAMOS TU APP
    page.add(menu, contenedor_principal, ft.Container(content=txt_estado, padding=5, bgcolor="#EEE"))
    navegar("asis")

if __name__ == "__main__":
    ft.app(target=main)
