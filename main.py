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

# --- VARIABLES GLOBALES (CRUCIAL: Definidas afuera para que todos las vean) ---
sh = None
ws_jugadoras = None
ws_habilidades = None
ws_asistencia = None
ws_partidos = None
ws_fixture = None
lista_jugadoras_raw = []

# Variables de configuración
categoria_actual = ["Primera"]
club_actual = ["Mi Club"]

# --- HELPERS GENERALES ---
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
#  PANTALLA DE ARRANQUE (TU CÓDIGO QUE SÍ FUNCIONA)
# =========================================================

def main(page: ft.Page):
    # Configuración básica
    page.title = "Hockey Gestión Total"
    page.bgcolor = "#F5F5F5"
    page.padding = 0
    
    # Intentamos configurar assets para PDFs
    try: page.assets_dir = "assets"
    except: pass
    if not os.path.exists("assets"):
        try: os.makedirs("assets")
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
            lista_jugadoras_raw.clear() # Limpiamos por si acaso
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
    
    # --- TRANSICIÓN A TU APP COMPLETA ---
    def ir_al_menu(e):
        page.clean() # Borramos la pantalla de inicio
        iniciar_app_completa(page) # Cargamos toda tu lógica

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
#  TU APLICACIÓN COMPLETA (INYECTADA AQUÍ)
# =========================================================

def iniciar_app_completa(page):
    # Variables de estado internas de la interfaz
    txt_estado = ft.Text("🟢 En línea", size=12, color="green")
    columna_contenido = ft.Column(expand=True, scroll="auto")
    contenedor_principal = ft.Container(content=columna_contenido, padding=15, expand=True)

    # --- TUS VISTAS ORIGINALES (ADAPTADAS LIGERAMENTE) ---

    def vista_asistencia():
        txt_fecha_display = ft.Text(f"📅 {datetime.now().strftime('%d/%m/%Y')}", size=16, weight="bold")
        
        def toggle_config(e):
            if row_config_display.visible: 
                row_config_display.visible = False; row_config_edit.visible = True
            else: 
                row_config_display.visible = True; row_config_edit.visible = False
                categoria_actual[0] = txt_cat_input.value
                club_actual[0] = txt_club_input.value
                txt_cat_label.value = f"Categoría: {categoria_actual[0]}"
                txt_club_label.value = f"Club: {club_actual[0]}"
                page.update()

        txt_cat_label = ft.Text(f"Categoría: {categoria_actual[0]}", size=14, weight="bold", color=C_AZUL)
        txt_club_label = ft.Text(f"Club: {club_actual[0]}", size=14, weight="bold", color="#E91E63")
        btn_edit_config = ft.IconButton(ft.Icons.EDIT, on_click=toggle_config)
        row_config_display = ft.Row([txt_cat_label, ft.VerticalDivider(), txt_club_label, btn_edit_config], alignment="center")
        
        txt_cat_input = ft.TextField(value=categoria_actual[0], label="Categoría", expand=True)
        txt_club_input = ft.TextField(value=club_actual[0], label="Nombre Club", expand=True)
        btn_save_config = ft.IconButton(ft.Icons.CHECK, on_click=toggle_config)
        row_config_edit = ft.Row([txt_cat_input, txt_club_input, btn_save_config], visible=False)

        dd_tipo = ft.Dropdown(options=[ft.dropdown.Option("Entrenamiento"), ft.dropdown.Option("Partido"), ft.dropdown.Option("Suspendido")], value="Entrenamiento", bgcolor=C_BLANCO, expand=True)
        txt_obs = ft.TextField(label="Observaciones del día", bgcolor=C_BLANCO, expand=True)
        col_lista = ft.Column(spacing=0)
        
        controles_filas = {} 
        
        def actualizar_visual_fila(dni, estado):
            if dni not in controles_filas: return
            ctrls = controles_filas[dni]
            if estado == "SI":
                ctrls['txt'].color = C_GRIS_TXT; ctrls['txt'].decoration = "line-through"
                ctrls['btn_p'].bgcolor = C_VERDE; ctrls['btn_p'].color = "white"; ctrls['btn_a'].bgcolor = "#EEEEEE"; ctrls['btn_a'].color = "black"
            elif estado == "NO":
                ctrls['txt'].color = C_GRIS_TXT; ctrls['txt'].decoration = "none"
                ctrls['btn_a'].bgcolor = C_ROJO; ctrls['btn_a'].color = "white"; ctrls['btn_p'].bgcolor = "#EEEEEE"; ctrls['btn_p'].color = "black"
            else:
                ctrls['txt'].color = C_TEXTO; ctrls['txt'].decoration = "none"
                ctrls['btn_p'].bgcolor = "#EEEEEE"; ctrls['btn_p'].color = "green"; ctrls['btn_a'].bgcolor = "#EEEEEE"; ctrls['btn_a'].color = "red"
            ctrls['estado'] = estado; page.update()

        def cargar_datos_fecha(e=None):
            f_str = txt_fecha_display.value.replace("📅 ", "")
            for dni in controles_filas: actualizar_visual_fila(dni, None)
            try:
                raw = ws_asistencia.get_all_values()
                for row in raw[1:]:
                    if row[0] == f_str:
                        dni = str(row[1]); actualizar_visual_fila(dni, row[2]) 
                        if row[3]: dd_tipo.value = row[3]
                        if row[4]: txt_obs.value = row[4]
                dd_tipo.update(); txt_obs.update(); page.update()
            except: pass

        def cambiar_fecha(e):
            if date_picker.value: nueva_f = date_picker.value.strftime("%d/%m/%Y"); txt_fecha_display.value = f"📅 {nueva_f}"; txt_fecha_display.update(); cargar_datos_fecha() 
        
        date_picker = ft.DatePicker(on_change=cambiar_fecha, first_date=datetime(2023,1,1), last_date=datetime(2030,12,31))
        try: page.overlay.append(date_picker)
        except: pass 
        
        col_lista.controls.append(ft.Container(content=ft.Row([ft.Text("JUGADORA", weight="bold", color="white", expand=True), ft.Text("ASISTENCIA", weight="bold", color="white", width=100)]), bgcolor="#607D8B", padding=10, border_radius=5))
        for i, jug in enumerate(lista_jugadoras_raw):
            dni = str(jug['dni']); num = jug['camiseta'] or "-"; edad = calcular_edad(jug['nacimiento'])
            txt_n = ft.Text(f"#{num} - {jug['apellido'].upper()} {jug['nombre']} ({edad})", weight="bold", size=14, color=C_TEXTO, expand=True)
            btn_p = ft.ElevatedButton("✅", width=50, on_click=lambda e, d=dni: actualizar_visual_fila(d, "SI"))
            btn_a = ft.ElevatedButton("❌", width=50, on_click=lambda e, d=dni: actualizar_visual_fila(d, "NO"))
            controles_filas[dni] = {'txt': txt_n, 'btn_p': btn_p, 'btn_a': btn_a, 'estado': None}
            col_lista.controls.append(ft.Container(content=ft.Row([txt_n, btn_p, btn_a], alignment="spaceBetween"), padding=10, bgcolor=C_BLANCO if i%2==0 else C_GRIS_CLARO, border=ft.border.only(bottom=ft.border.BorderSide(1, "#DDD"))))
        
        def guardar(e):
            f_str = txt_fecha_display.value.replace("📅 ", ""); susp = "Suspendido" in dd_tipo.value; txt_estado.value = "⏳ Guardando..."; page.update()
            try:
                raw = ws_asistencia.get_all_values(); filas_ok = [row for row in raw if row[0] != f_str]
                if not filas_ok or filas_ok[0][0] != "Fecha": filas_ok.insert(0, ["Fecha", "DNI", "Presente", "Tipo", "Observaciones"])
                filas_nuevas = []
                for dni, ctrl in controles_filas.items():
                    est = ctrl['estado']
                    if not est and not susp: continue
                    val = "-" if susp else est
                    filas_nuevas.append([f_str, dni, val, dd_tipo.value, txt_obs.value])
                ws_asistencia.clear(); ws_asistencia.append_rows(filas_ok + filas_nuevas)
                txt_estado.value = "✅ Guardado"; page.update()
            except Exception as ex: txt_estado.value = f"Error: {ex}"; page.update()
        
        btn_guardar = ft.ElevatedButton("💾 GUARDAR ASISTENCIA", on_click=guardar, bgcolor=C_AZUL, color="white", height=50)
        
        # Carga inicial
        cargar_datos_fecha() 
        return ft.Column([
            ft.Text("Tomar Asistencia", size=22, weight="bold", color=C_AZUL), 
            ft.Container(content=ft.Column([row_config_display, row_config_edit]), padding=10), 
            ft.Row([ft.ElevatedButton("📅 CAMBIAR DÍA", on_click=lambda e: setattr(date_picker, 'open', True) or page.update(), bgcolor=C_AZUL, color="white"), txt_fecha_display]), 
            ft.Row([dd_tipo, txt_obs]), ft.Divider(), 
            col_lista, ft.Divider(), btn_guardar
        ], scroll="auto")

    def vista_plantel():
        def form(jug=None):
            columna_contenido.controls.clear()
            v_nom = jug['nombre'] if jug else ""; v_ape = jug['apellido'] if jug else ""; v_dni = str(jug['dni']) if jug else ""
            v_nac = str(jug.get('nacimiento','') or "") if jug else ""; v_cam = str(jug.get('camiseta','') or "") if jug else ""; v_pos = jug.get('posicion') if jug else None; v_tel = str(jug.get('telefono','') or "") if jug else ""
            dni_orig = v_dni
            t_nom = ft.TextField(label="Nombre", value=v_nom); t_ape = ft.TextField(label="Apellido", value=v_ape)
            t_dni = ft.TextField(label="DNI", value=v_dni); t_nac = ft.TextField(label="Nacimiento (DD/MM/AAAA)", value=v_nac)
            t_cami = ft.TextField(label="N° Camiseta", value=v_cam); t_pos = ft.Dropdown(label="Posición", options=[ft.dropdown.Option(x) for x in ["Arquera","Defensora","Volante","Delantera"]], value=v_pos); t_tel = ft.TextField(label="Teléfono", value=v_tel)
            def save(e):
                if not t_dni.value: txt_estado.value = "⚠️ Falta DNI"; page.update(); return
                nd = ["", t_nom.value, t_ape.value, t_dni.value, t_nac.value, t_pos.value, t_tel.value, "SI", t_cami.value]
                try:
                    if jug:
                        rows = ws_jugadoras.get_all_values()
                        for i, r in enumerate(rows):
                            if len(r) > 3 and str(r[3]) == str(dni_orig):
                                ws_jugadoras.update(f"A{i+1}:I{i+1}", [nd]); jug.update({'nombre':t_nom.value, 'apellido':t_ape.value, 'dni':t_dni.value, 'nacimiento':t_nac.value, 'camiseta':t_cami.value}); break
                    else:
                        ws_jugadoras.append_row(nd)
                        lista_jugadoras_raw.append({'id':"", 'nombre':t_nom.value, 'apellido':t_ape.value, 'dni':t_dni.value, 'nacimiento':t_nac.value, 'posicion':t_pos.value, 'telefono':t_tel.value, 'activo':"SI", 'camiseta':t_cami.value})
                    txt_estado.value="✅ Guardado"; navegar("plantel")
                except Exception as ex: txt_estado.value=str(ex); page.update()
            columna_contenido.controls.append(ft.Column([ft.Text("Editar" if jug else "Alta", size=20, weight="bold", color=C_AZUL), t_nom, t_ape, t_dni, t_nac, t_cami, t_pos, t_tel, ft.Row([ft.ElevatedButton("Cancelar", on_click=lambda e:navegar("plantel"), bgcolor="grey", color="white"), ft.ElevatedButton("GUARDAR", on_click=save, bgcolor=C_VERDE, color="white")])])); page.update()
        items = []
        for j in lista_jugadoras_raw:
            btn = ft.ElevatedButton("✏️", bgcolor=C_BLANCO, color=C_AZUL, width=50, on_click=lambda e, x=j: form(x))
            items.append(ft.Container(content=ft.Row([ft.Text("👤", size=20), ft.Column([ft.Text(f"{j['nombre']} {j['apellido']}", weight="bold"), ft.Text(f"Camiseta: {j.get('camiseta','-')}", size=12, color="grey")], expand=True), btn]), padding=10, border=ft.Border.all(1, "#EEE")))
        return ft.Column([ft.Row([ft.Text("Mi Plantel", size=20, weight="bold"), ft.ElevatedButton("+ ALTA", on_click=lambda e:form(None), bgcolor=C_AZUL, color="white")], alignment="spaceBetween"), ft.Column(items, spacing=5)])

    def vista_gestion_fixture():
        # *** CORRECCIÓN CRÍTICA AQUÍ ***
        # Usamos 'global' porque ws_fixture está definida al principio del archivo
        global ws_fixture 
        
        if ws_fixture is None: return ft.Text("Falta hoja fixture")
        hoy = datetime.now(); mes_v = [hoy.month]; anio_v = [hoy.year]; contenedor_cal = ft.Container()
        def actualizar_cal():
            m, a = mes_v[0], anio_v[0]; pe = {}
            try:
                raw = ws_fixture.get_all_values()
                for r in raw[1:]:
                    try:
                        dt = datetime.strptime(r[0], "%d/%m/%Y")
                        if dt.month == m and dt.year == a: pe[dt.day] = C_AZUL if r[2] == "Local" else "#FF9800"
                    except: pass
            except: pass
            cal = calendar.monthcalendar(a, m)
            fc = [ft.Row([ft.Container(content=ft.Text(d, size=10, weight="bold"), width=35, height=35, alignment=ft.alignment.Alignment(0,0)) for d in LETRAS_DIAS], alignment="center")]
            for sem in cal:
                celdas = []
                for dia in sem:
                    if dia == 0: celdas.append(ft.Container(width=35, height=35))
                    else:
                        bg, tc = (pe[dia], C_BLANCO) if dia in pe else (C_GRIS_CLARO, C_TEXTO)
                        celdas.append(ft.Container(content=ft.Text(str(dia), color=tc, weight="bold"), width=35, height=35, bgcolor=bg, border_radius=5, alignment=ft.alignment.Alignment(0,0)))
                fc.append(ft.Row(celdas, alignment="center"))
            contenedor_cal.content = ft.Container(content=ft.Column([ft.Row([ft.ElevatedButton("<", on_click=mes_ant, width=45), ft.Text(f"{LISTA_MESES[m-1]} {a}", weight="bold", size=16), ft.ElevatedButton(">", on_click=mes_sig, width=45)], alignment="spaceBetween"), ft.Column(fc, spacing=5)], horizontal_alignment="center"), padding=10, bgcolor=C_BLANCO, border_radius=10, border=ft.Border.all(1, C_GRIS)); page.update()
        def mes_ant(e): 
            if mes_v[0] == 1: mes_v[0] = 12; anio_v[0] -= 1
            else: mes_v[0] -= 1
            actualizar_cal()
        def mes_sig(e):
            if mes_v[0] == 12: mes_v[0] = 1; anio_v[0] += 1
            else: mes_v[0] += 1
            actualizar_cal()
        
        edit_idx = [-1]; txt_f = ft.TextField(label="Fecha", width=150); txt_r = ft.TextField(label="Rival", expand=True); dd_c = ft.Dropdown(options=[ft.dropdown.Option("Local"), ft.dropdown.Option("Visitante")], value="Local", width=120); 
        txt_maps = ft.TextField(label="Link Ubicación (Maps)", expand=True)
        col_partidos = ft.Column(scroll="auto", expand=True); btn_accion = ft.ElevatedButton("AGREGAR PARTIDO", bgcolor=C_VERDE, color="white")
        
        def procesar(e):
            row_data = [txt_f.value, txt_r.value, dd_c.value, txt_maps.value]
            try:
                if edit_idx[0] != -1: ws_fixture.delete_rows(edit_idx[0]); ws_fixture.insert_row(row_data, edit_idx[0]); edit_idx[0] = -1; btn_accion.content = ft.Text("AGREGAR PARTIDO")
                else: ws_fixture.append_row(row_data)
                txt_r.value=""; txt_maps.value=""; cargar_fix(); actualizar_cal()
            except Exception as ex: txt_estado.value = str(ex); page.update()
        
        btn_accion.on_click = procesar
        
        def cargar_fix():
            col_partidos.controls.clear()
            try:
                raw = ws_fixture.get_all_values()
                for i, r in enumerate(raw[1:]):
                    real_idx = i + 2
                    botones = []
                    f_date = r[0]; f_rival = r[1]; f_cond = r[2]
                    f_map_link = r[3] if len(r) > 3 else ""

                    if f_map_link:
                        botones.append(ft.TextButton("📍 Ver Ubicación", url=f_map_link))
                    
                    btn_edit = ft.TextButton("✏️", on_click=lambda e, idx=real_idx, d=r: preparar(idx, d))
                    btn_del = ft.TextButton("🗑️", on_click=lambda e, idx=real_idx: borrar(idx))

                    card = ft.Card(
                        content=ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Text(f"📅 {f_date}", weight="bold", size=16),
                                    ft.Text(f"({f_cond})", color="blue" if f_cond == "Local" else "orange", weight="bold")
                                ], alignment="spaceBetween"),
                                ft.Text(f"VS {f_rival}", size=18, weight="bold", color=C_AZUL),
                                ft.Row(botones + [ft.Container(expand=True), btn_edit, btn_del])
                            ]),
                            padding=15
                        )
                    )
                    col_partidos.controls.append(card)
                page.update()
            except: pass

        def preparar(idx, d): 
            txt_f.value=d[0]; txt_r.value=d[1]; dd_c.value=d[2]; 
            if len(d) > 3: txt_maps.value = d[3]
            else: txt_maps.value = ""
            edit_idx[0]=idx; btn_accion.content = ft.Text("GUARDAR"); page.update()
        
        def borrar(idx): ws_fixture.delete_rows(idx); cargar_fix(); actualizar_cal()
        
        cargar_fix(); actualizar_cal()
        
        btn_volver = ft.ElevatedButton("VOLVER", on_click=lambda e: navegar("part"), bgcolor="grey", color="white")
        btn_actualizar = ft.ElevatedButton("🔄 ACTUALIZAR", on_click=lambda e: cargar_fix(), bgcolor=C_AZUL, color="white", expand=True)
        
        return ft.Column([
            ft.Row([ft.Text("Fixture", size=20, weight="bold"), btn_volver], alignment="spaceBetween"),
            contenedor_cal, ft.Divider(), 
            ft.Row([txt_f, dd_c]), 
            txt_r, 
            txt_maps,
            btn_accion, 
            ft.Divider(),
            ft.Row([btn_actualizar]),
            ft.Divider(), 
            ft.Container(content=col_partidos, expand=True)
        ], expand=True)

    def vista_partidos():
        c_jug = len(ws_partidos.get_all_values()); c_tot = len(ws_fixture.get_all_values())-1 if ws_fixture else 0
        top = ft.Container(content=ft.Text(f"Jugados: {c_jug}/{c_tot}", color="white"), bgcolor="#607D8B", padding=5)
        rivales_set = set()
        if ws_fixture:
            try: rivales_set = set(r[1].strip() for r in ws_fixture.get_all_values()[1:] if len(r)>1)
            except: pass
        dd_rival = ft.Dropdown(label="Rival", options=[ft.dropdown.Option(x) for x in sorted(list(rivales_set))], expand=True)
        dc = ft.Dropdown(options=[ft.dropdown.Option("Local"), ft.dropdown.Option("Visitante")], value="Local", width=120)
        gf = ft.TextField(label="GF", width=80); gc = ft.TextField(label="GC", width=80)
        cf = ft.TextField(label="Corn F", width=80); cc = ft.TextField(label="Corn C", width=80)
        hist = ft.Column()
        goleadoras_dict = {}; lista_goles = ft.Column()
        opciones_jug = [ft.dropdown.Option(f"{j['nombre']} {j['apellido']}") for j in lista_jugadoras_raw]
        dd_autora = ft.Dropdown(label="Jugadora", options=opciones_jug, expand=True)
        def act_goles():
            lista_goles.controls.clear()
            for n, c in goleadoras_dict.items():
                lista_goles.controls.append(ft.Row([ft.Text(n, expand=True), ft.ElevatedButton("-", on_click=lambda e,x=n: mod_gol(x,-1), width=40), ft.Text(str(c)), ft.ElevatedButton("+", on_click=lambda e,x=n: mod_gol(x,1), width=40)]))
            page.update()
        def mod_gol(n, d):
            goleadoras_dict[n] += d
            if goleadoras_dict[n] <= 0: del goleadoras_dict[n]
            act_goles()
        def add_gol(e):
            if dd_autora.value:
                goleadoras_dict[dd_autora.value] = goleadoras_dict.get(dd_autora.value, 0) + 1
                dd_autora.value = None; dd_autora.update(); act_goles()
        def load_hist():
            hist.controls.clear()
            try:
                raw = ws_partidos.get_all_values()
                if raw:
                    for i, r in enumerate(reversed(list(enumerate(raw)))):
                        idx_real = r[0] + 1; data = r[1]
                        if len(data) < 5: continue
                        
                        titulo_partido = f"{club_actual[0]} vs {data[1]}" if data[2] == "Local" else f"{data[1]} vs {club_actual[0]}"
                        texto_res = f"Res: {data[3]} - {data[4]} (R) | Corn: {data[5]}(f) - {data[6]}(c)"
                        
                        card = ft.Container(content=ft.Column([
                            ft.Row([ft.Text(f"{data[0]}", weight="bold"), ft.Container(expand=True), ft.TextButton("🗑️", on_click=lambda e, ix=idx_real: borrar(idx_real))]),
                            ft.Text(titulo_partido),
                            ft.Text(texto_res),
                            ft.Text(f"Goles: {data[7]}" if len(data)>7 else "")
                        ]), padding=10, border=ft.Border.all(1, "grey"), border_radius=5)
                        hist.controls.append(card)
            except: pass
            page.update()
        def borrar(ix): ws_partidos.delete_rows(ix); load_hist()
        def sv(e):
            txt_gol = ", ".join([f"{n} ({c})" for n,c in goleadoras_dict.items()])
            ws_partidos.append_row([datetime.now().strftime("%d/%m/%Y"), dd_rival.value, dc.value, gf.value, gc.value, cf.value, cc.value, txt_gol])
            goleadoras_dict.clear(); act_goles(); load_hist()
        load_hist()
        return ft.Column([ft.Text("Resultados", size=20, weight="bold"), top, 
                          ft.Row([ft.ElevatedButton("📅 FIXTURE", on_click=lambda e: navegar("fixture_full")), ft.ElevatedButton("📊 RESUMEN", on_click=lambda e: navegar("resumen_partidos"))]),
                          ft.Divider(),
                          ft.Row([dd_rival, dc]), ft.Row([gf, gc]), ft.Row([cf, cc]),
                          ft.Text("Goleadoras:"), ft.Row([dd_autora, ft.ElevatedButton("+", on_click=add_gol)]), lista_goles,
                          ft.ElevatedButton("GUARDAR", on_click=sv), ft.Divider(), hist], scroll="auto")

    def vista_resumen_partidos():
        stats_col = ft.Column(scroll="auto", expand=True); txt_estado.value="Calculando..."; page.update()
        try:
            raw = ws_partidos.get_all_values()
            filas_planilla = []; ranking = {}
            if len(raw) > 0:
                for r in raw:
                    try:
                        g_f = r[3]; g_c = r[4]
                        filas_planilla.append(ft.DataRow(cells=[
                            ft.DataCell(ft.Text(r[0])), 
                            ft.DataCell(ft.Text(r[1])), 
                            ft.DataCell(ft.Text(f"{g_f}(f) - {g_c}(c)", weight="bold")), 
                            ft.DataCell(ft.Text(r[2])) 
                        ]))
                        txt_goles = r[7]
                        if txt_goles and txt_goles.strip() != "Sin datos":
                            partes = txt_goles.split(",")
                            for p in partes:
                                match = re.search(r"(.+)\((\d+)\)", p)
                                if match:
                                    nombre = match.group(1).strip(); goles = int(match.group(2))
                                    if nombre in ranking: ranking[nombre] += goles
                                    else: ranking[nombre] = goles
                    except: pass
            tabla_planilla = ft.DataTable(columns=[ft.DataColumn(ft.Text("FECHA")), ft.DataColumn(ft.Text("RIVAL")), ft.DataColumn(ft.Text("RES")), ft.DataColumn(ft.Text("COND"))], rows=filas_planilla, border=ft.Border.all(1, C_GRIS))
            filas_gol = []
            for nombre, cant in sorted(ranking.items(), key=lambda item: item[1], reverse=True):
                filas_gol.append(ft.DataRow(cells=[ft.DataCell(ft.Text(nombre, weight="bold")), ft.DataCell(ft.Text(str(cant)))]))
            tabla_goleadoras = ft.DataTable(columns=[ft.DataColumn(ft.Text("JUGADORA")), ft.DataColumn(ft.Text("GOLES"))], rows=filas_gol, border=ft.Border.all(1, C_GRIS))
            stats_col.controls.append(ft.Column([ft.Text("Resultados", weight="bold"), ft.Row([tabla_planilla], scroll="always"), ft.Divider(), ft.Text("Goleadoras", weight="bold"), ft.Row([tabla_goleadoras], scroll="always")]))
            txt_estado.value="Listo"
        except: pass
        
        return ft.Column([
            ft.Text(f"Resumen Técnico - {club_actual[0]}", size=20, weight="bold", color=C_AZUL), 
            ft.Divider(), stats_col, ft.Divider(), 
            ft.ElevatedButton("VOLVER", on_click=lambda e: navegar("part"))
        ])

    def vista_formacion_pdf_wrapper():
        # Tu función original de formación, simplificada en envoltura para ahorrar espacio
        # pero la lógica completa está arriba en generar_pdf_formacion
        return vista_formacion() # Reusamos vista_formacion

    def vista_evaluacion():
        area_contenido = ft.Column()
        txt_progreso = ft.Text("", size=16, weight="bold", color=C_AZUL)
        estado_edicion = {"dni_jugadora": None, "fila": None}; sliders_refs = []
        botones_meses_refs = [] 
        def get_color_nota(v):
            if v < 5: return C_ROJO
            elif v < 8: return C_AMARILLO
            return C_VERDE
        def mostrar_formulario_evaluacion(dni_jugadora, nombre_jugadora, mes_num):
            area_contenido.controls.clear()
            raw = ws_habilidades.get_all_values()
            vals = [1]*len(TITULOS_SKILLS); fila_enc = None
            for idx, row in enumerate(raw):
                if idx==0: continue
                try:
                    f = datetime.strptime(row[0], "%d/%m/%Y")
                    if str(row[1]) == str(dni_jugadora) and f.month == mes_num and f.year == datetime.now().year:
                        fila_enc = idx + 1; vals = []
                        for i in range(len(TITULOS_SKILLS)): 
                            try: vals.append(safe_int(row[i+2]))
                            except: vals.append(1)
                except: pass
            estado_edicion["dni_jugadora"] = dni_jugadora; estado_edicion["fila"] = fila_enc
            sliders_refs.clear(); col_sliders = ft.Column()
            for i, tit in enumerate(TITULOS_SKILLS):
                val_ini = int(vals[i])
                lbl = ft.Text(str(val_ini), weight="bold", size=16)
                color_ini = get_color_nota(val_ini)
                bar = ft.Container(width=val_ini*30, height=15, bgcolor=color_ini, border_radius=5, animate=300)
                bg = ft.Container(content=bar, width=300, height=15, bgcolor=C_GRIS, border_radius=5, alignment=ft.Alignment(-1.0, 0.0))
                def crear_mover(label_ref, bar_ref):
                    def mover(e):
                        v = int(e.control.value)
                        label_ref.value = str(v)
                        bar_ref.width = v * 30
                        bar_ref.bgcolor = get_color_nota(v)
                        label_ref.update(); bar_ref.update()
                    return mover
                s = ft.Slider(min=1, max=10, divisions=9, value=val_ini, on_change=crear_mover(lbl, bar))
                sliders_refs.append(s)
                col_sliders.controls.append(ft.Column([ft.Row([ft.Text(tit, weight="bold"), lbl], alignment="spaceBetween"), bg, s], spacing=5))
            def guardar_y_volver(e):
                notas = [int(s.value) for s in sliders_refs]
                anio = datetime.now().year
                fecha_guardado = datetime(anio, mes_num, 1).strftime("%d/%m/%Y")
                try:
                    if estado_edicion["fila"]: 
                        letra_fin = chr(ord('C') + len(TITULOS_SKILLS) - 1)
                        ws_habilidades.update(f"C{estado_edicion['fila']}:{letra_fin}{estado_edicion['fila']}", [notas])
                    else: ws_habilidades.append_row([fecha_guardado, dni_jugadora] + notas + ["Obs"])
                    txt_estado.value = "✅ Guardado"; mostrar_lista_jugadoras(mes_num)
                except Exception as ex: txt_estado.value = f"Error: {ex}"; page.update()
            area_contenido.controls.append(ft.Column([ft.Text(f"Evaluando a: {nombre_jugadora}", size=20, weight="bold", color=C_VIOLETA), ft.Divider(), col_sliders, ft.Divider(), ft.Row([ft.ElevatedButton("Cancelar", on_click=lambda e: mostrar_lista_jugadoras(mes_num), bgcolor="grey", color="white"), ft.ElevatedButton("GUARDAR", on_click=guardar_y_volver, bgcolor=C_VERDE, color="white", expand=True)])]))
            page.update()
        def mostrar_lista_jugadoras(mes_num):
            area_contenido.controls.clear(); txt_estado.value = "⏳ Calculando..."; page.update()
            for i, btn in enumerate(botones_meses_refs):
                if (i + 1) == mes_num: btn.bgcolor = C_VERDE; btn.color = "white"
                else: btn.bgcolor = C_BLANCO; btn.color = "black"
            page.update() 
            raw = ws_habilidades.get_all_values(); anio = datetime.now().year
            dnis_activos = [str(j['dni']) for j in lista_jugadoras_raw]; notas_validas = {} 
            acumulado_skills = [0]*len(TITULOS_SKILLS); cantidad_evaluadas = 0
            for row in raw[1:]:
                try:
                    f = datetime.strptime(row[0], "%d/%m/%Y")
                    if f.year == anio and f.month == mes_num:
                        dni_fila = str(row[1])
                        if dni_fila in dnis_activos:
                            notas = []
                            for i in range(len(TITULOS_SKILLS)): 
                                try: val = safe_int(row[i+2])
                                except: val = 1
                                notas.append(val)
                                acumulado_skills[i] += val
                            notas_validas[dni_fila] = notas
                            cantidad_evaluadas += 1
                except: pass
            txt_progreso.value = f"Estado {LISTA_MESES[mes_num-1]}: {len(notas_validas)}/{len(lista_jugadoras_raw)} Evaluadas"
            items_lista = []
            for j in lista_jugadoras_raw:
                dni = str(j['dni']); ya_esta = dni in notas_validas
                icono = "✅" if ya_esta else "⚠️"
                texto_estado = "Completado" if ya_esta else "Pendiente"
                color_bg = "#E8F5E9" if ya_esta else "#FFF3E0" 
                card = ft.Container(
                    content=ft.Row([
                        ft.Text(icono, size=20),
                        ft.Column([
                            ft.Text(f"{j['nombre']} {j['apellido']}", weight="bold"),
                            ft.Text(texto_estado, size=12, color="grey")
                        ], expand=True),
                        ft.ElevatedButton("EDITAR" if ya_esta else "CARGAR", color="blue", bgcolor=C_BLANCO, on_click=lambda e, d=dni, n=f"{j['nombre']} {j['apellido']}": mostrar_formulario_evaluacion(d, n, mes_num))
                    ]),
                    padding=10, bgcolor=color_bg, border_radius=8
                )
                items_lista.append(card)
            area_contenido.controls.append(ft.Column(items_lista, spacing=5))
            if cantidad_evaluadas > 0:
                area_contenido.controls.append(ft.Divider())
                nombre_mes = LISTA_MESES[mes_num-1]
                area_contenido.controls.append(ft.Text(f"📊 Rendimiento Equipo - {nombre_mes}", weight="bold", color=C_AZUL))
                promedios = [int(tot / cantidad_evaluadas) for tot in acumulado_skills] 
                for i, prom in enumerate(promedios):
                    c = get_color_nota(prom)
                    area_contenido.controls.append(ft.Column([
                        ft.Row([ft.Text(TITULOS_SKILLS[i], size=10, width=80), ft.Text(str(prom), weight="bold")], alignment="spaceBetween"),
                        ft.Stack([ft.Container(width=300, height=8, bgcolor=C_GRIS, border_radius=4, alignment=ft.Alignment(-1.0, 0.0)), ft.Container(width=prom*30, height=8, bgcolor=c, border_radius=4)])
                    ], spacing=2))
            else:
                area_contenido.controls.append(ft.Container(content=ft.Text("Ninguna evaluación cargada este mes.", color="orange"), padding=20))
            txt_estado.value = "✅ Lista actualizada"; page.update()
        botones_meses_refs.clear()
        fila_botones = ft.Row(scroll="always")
        for i, nombre_mes in enumerate(LISTA_MESES):
            btn = ft.ElevatedButton(nombre_mes, on_click=lambda e, m=i+1: mostrar_lista_jugadoras(m))
            botones_meses_refs.append(btn)
            fila_botones.controls.append(btn)
        mostrar_lista_jugadoras(datetime.now().month)
        return ft.Column([
            ft.Text("Evaluación Técnica Mensual", size=20, weight="bold", color=C_VERDE),
            fila_botones,
            txt_progreso,
            ft.Divider(),
            area_contenido
        ], scroll="auto")

    def vista_formacion():
        partidos_disp = []
        if ws_fixture:
            try:
                for r in ws_fixture.get_all_values()[1:]: 
                    if len(r) > 2: partidos_disp.append(f"{r[0]} vs {r[1]} ({r[2]})")
            except: pass

        dd_partido = ft.Dropdown(label="Partido", options=[ft.dropdown.Option(p) for p in partidos_disp], expand=True)
        dd_esquema = ft.Dropdown(label="Esquema", options=[ft.dropdown.Option("Doble 5"), ft.dropdown.Option("3-3-1-3"), ft.dropdown.Option("4-3-3")], value="Doble 5", width=120)
        
        LINEAS = {
            "ARCO": ["Arquera (1)"], "DEFENSA": ["Libero (2)", "Stopper (6)", "Half Der. (4)", "Half Izq. (3)"],
            "MEDIO": ["Volante Central (5)", "Volante Der. (8)", "Volante Izq. (10)"], "ATAQUE": ["Delantera Centro (9)", "Wing Der. (7)", "Wing Izq. (11)"]
        }
        dropdowns_refs = {}
        lista_ausentes_data = []

        def obtener_libres():
            seleccionadas = {dd.value for dd in dropdowns_refs.values() if dd.value}
            ausentes = {a['nombre'] for a in lista_ausentes_data}
            return sorted([f"{j['nombre']} {j['apellido']}" for j in lista_jugadoras_raw 
                    if f"{j['nombre']} {j['apellido']}" not in seleccionadas and f"{j['nombre']} {j['apellido']}" not in ausentes])

        def refrescar_manual(e=None):
            for pos, dd in dropdowns_refs.items():
                if dd.page:
                    v = dd.value; libres = obtener_libres()
                    dd.options = [ft.dropdown.Option("")] + [ft.dropdown.Option(n) for n in sorted(list(set(([v] if v else []) + libres)))]
                    dd.value = v; dd.update()
            dispo = obtener_libres()
            if dd_nueva_ausente.page: 
                dd_nueva_ausente.options = [ft.dropdown.Option(n) for n in dispo]
                dd_nueva_ausente.update()
            if txt_suplentes.page:
                txt_suplentes.value = f"SUPLENTES: {', '.join(dispo)}"
                txt_suplentes.update()

        col_lineas = ft.Column(spacing=15)
        jugadoras_iniciales = sorted([f"{j['nombre']} {j['apellido']}" for j in lista_jugadoras_raw])
        
        for lin, puestos in LINEAS.items():
            rows_p = ft.Column(spacing=5)
            for p in puestos:
                dd = ft.Dropdown(label=p, dense=True, text_size=12, expand=True)
                dd.options = [ft.dropdown.Option("")] + [ft.dropdown.Option(n) for n in jugadoras_iniciales]
                dd.on_change = refrescar_manual 
                dropdowns_refs[p] = dd
                rows_p.controls.append(dd)
            col_lineas.controls.append(ft.Container(content=ft.Column([ft.Text(lin, size=11, weight="bold", color=C_GRIS_TXT), rows_p]), padding=10, bgcolor=C_BLANCO, border_radius=8))

        dd_nueva_ausente = ft.Dropdown(label="Jugadora Ausente", expand=True)
        dd_nueva_ausente.options = [ft.dropdown.Option(n) for n in jugadoras_iniciales]
        txt_motivo = ft.TextField(label="Motivo", expand=True)
        col_ausentes = ft.Column()
        txt_suplentes = ft.Text("SUPLENTES: -", color=C_GRIS_TXT, size=11)
        txt_suplentes.value = f"SUPLENTES: {', '.join(jugadoras_iniciales)}"

        def add_aus(e):
            if dd_nueva_ausente.value:
                lista_ausentes_data.append({"nombre": dd_nueva_ausente.value, "motivo": txt_motivo.value})
                dd_nueva_ausente.value = None; txt_motivo.value = ""; render_aus(); refrescar_manual()

        def render_aus():
            col_ausentes.controls.clear()
            for i, a in enumerate(lista_ausentes_data):
                col_ausentes.controls.append(ft.Row([ft.Text(f"• {a['nombre']}", color=C_ROJO, size=12, expand=True), ft.IconButton(ft.Icons.DELETE, on_click=lambda e, idx=i: (lista_ausentes_data.pop(idx), render_aus(), refrescar_manual()))]))
            if col_ausentes.page: col_ausentes.update()

        btn_ojo = ft.IconButton(icon=ft.Icons.VISIBILITY, disabled=True, icon_color=C_GRIS_TXT, tooltip="Abrir PDF")

        def btn_pdf_click(e):
            if not dd_partido.value: txt_estado.value = "⚠️ Falta partido"; page.update(); return
            txt_estado.value = "Generando PDF..."
            page.update()
            tits = {p: dd.value for p, dd in dropdowns_refs.items() if dd.value}
            ok, res, url_pdf = generar_pdf_formacion(dd_partido.value, dd_esquema.value, tits, lista_ausentes_data, obtener_libres(), categoria_actual[0])
            
            if ok:
                txt_estado.value = "✅ Link Listo. Click en el ojo."
                btn_ojo.disabled = False
                btn_ojo.icon_color = C_AZUL
                btn_ojo.url = url_pdf # ASIGNACIÓN DIRECTA
                btn_ojo.update()
            else:
                txt_estado.value = f"❌ Error Gen: {res}"
            page.update()

        return ft.Column([
            ft.Text("Armado de Equipo", size=20, weight="bold", color=C_AZUL),
            ft.Row([dd_partido, dd_esquema]),
            ft.ElevatedButton("🔄 ACTUALIZAR LISTAS", on_click=refrescar_manual, bgcolor=C_AZUL, color="white"),
            ft.Divider(), col_lineas, ft.Divider(),
            ft.Text("AUSENTES", size=14, weight="bold", color=C_ROJO),
            ft.Row([dd_nueva_ausente, txt_motivo, ft.ElevatedButton("➕", on_click=add_aus, bgcolor=C_AZUL, color="white")]),
            col_ausentes, ft.Divider(),
            ft.Container(content=txt_suplentes, bgcolor="#E0F7FA", padding=10, border_radius=5),
            ft.Divider(),
            ft.Row([ft.ElevatedButton("📄 GENERAR PDF", on_click=btn_pdf_click, bgcolor=C_VERDE, color="white", height=50, expand=True), btn_ojo], alignment="spaceBetween"),
        ], scroll="auto")

    # =========================================================
    # NAVEGACIÓN PRINCIPAL
    # =========================================================
    def navegar(e):
        destino = e
        if not isinstance(e, str) and hasattr(e, "control") and hasattr(e.control, "data"):
            destino = e.control.data
        elif not isinstance(e, str):
            destino = "asis"

        # FEEDBACK VISUAL
        columna_contenido.controls.clear()
        columna_contenido.controls.append(
            ft.Column(
                [
                    ft.ProgressBar(width=200, color=C_AZUL, bgcolor="#EEEEEE"),
                    ft.Text("Cargando...", color="grey", size=12)
                ], 
                alignment=ft.MainAxisAlignment.CENTER, 
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True
            )
        )
        page.update()
        
        # Pequeña pausa técnica
        time.sleep(0.01)
        columna_contenido.controls.clear()
        
        # CARGA DE VISTA
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
    # MENÚ INFERIOR
    # =========================================================
    btn_s = ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=0), color=C_BLANCO)
    menu = ft.Container(content=ft.Row([
        ft.ElevatedButton("📝", data="asis", on_click=navegar, bgcolor=C_AZUL, style=btn_s, expand=True),
        ft.ElevatedButton("📊", data="eval", on_click=navegar, bgcolor=C_VERDE, style=btn_s, expand=True),
        ft.ElevatedButton("🏆", data="part", on_click=navegar, bgcolor="#FF9800", style=btn_s, expand=True),
        ft.ElevatedButton("👥", data="formacion", on_click=navegar, bgcolor="#E91E63", style=btn_s, expand=True),
        ft.ElevatedButton("👤", data="plantel", on_click=navegar, bgcolor="#607D8B", style=btn_s, expand=True),
        ft.ElevatedButton("📄", data="ficha", on_click=navegar, bgcolor=C_VIOLETA, style=btn_s, expand=True),
    ], spacing=0), padding=0)

    # LIMPIAMOS LA PANTALLA DE CARGA Y MOSTRAMOS LA APP REAL
    page.clean()
    page.add(menu, contenedor_principal, ft.Container(content=txt_estado, padding=5, bgcolor="#EEE"))
    
    # INICIAMOS EN ASISTENCIA
    navegar("asis")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    ft.app(
        target=main, 
        view=ft.AppView.WEB_BROWSER, 
        port=port, 
        host="0.0.0.0", 
        assets_dir="assets"
    )
