import flet as ft
import os
from datetime import datetime
import time

# --- IMPORTAMOS CON CUIDADO ---
try:
    import gspread
    from google.oauth2 import service_account
    TIENE_GOOGLE = True
except:
    TIENE_GOOGLE = False

# --- VARIABLES GLOBALES ---
sh = None
ws_jugadoras = None
ws_habilidades = None
ws_asistencia = None
ws_partidos = None
ws_fixture = None
lista_jugadoras_raw = []

def main(page: ft.Page):
    # Configuración básica para que NO falle
    page.title = "Hockey App"
    page.bgcolor = "#F5F5F5"
    page.padding = 20
    
    # --- UI: ELEMENTOS VISUALES ---
    lbl_titulo = ft.Text("Hockey App", size=30, weight="bold", color="blue")
    lbl_estado = ft.Text("Esperando conexión...", color="grey")
    prg_loading = ft.ProgressBar(width=200, color="blue", visible=False)
    
    # Contenedor para mensajes de error o éxito
    txt_resultado = ft.Text("", size=14)

    # --- FUNCIÓN DE CONEXIÓN ---
    def conectar_google(e):
        # 1. Activamos la animación de carga
        btn_conectar.disabled = True
        prg_loading.visible = True
        lbl_estado.value = "Buscando credentials.json..."
        txt_resultado.value = ""
        page.update()
        
        time.sleep(0.5) # Pequeña pausa para que se vea la animación

        try:
            # 2. Buscamos el archivo
            archivo = "credentials.json"
            if not os.path.exists(archivo):
                # Intentamos ruta assets
                if os.path.exists("assets/credentials.json"):
                    archivo = "assets/credentials.json"
                else:
                    raise Exception("NO SE ENCUENTRA credentials.json")

            lbl_estado.value = "Conectando con Google..."
            page.update()

            # 3. Conectamos
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
                     "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
            
            creds = service_account.Credentials.from_service_account_file(archivo, scopes=scope)
            client = gspread.authorize(creds)
            
            global sh, ws_jugadoras, ws_asistencia
            sh = client.open("HockeyApp_DB")
            
            lbl_estado.value = "Leyendo datos..."
            page.update()
            
            # Intentamos leer una hoja para confirmar
            ws_jugadoras = sh.worksheet("jugadoras")
            datos = ws_jugadoras.get_all_values() # Prueba de lectura
            
            # SI LLEGAMOS ACÁ, ÉXITO TOTAL
            lbl_estado.value = "✅ CONECTADO EXITOSAMENTE"
            lbl_estado.color = "green"
            txt_resultado.value = f"Se cargaron {len(datos)} filas de jugadoras."
            prg_loading.visible = False
            
            # Mostramos botón para entrar
            btn_entrar.visible = True
            page.update()

        except Exception as ex:
            # SI FALLA, MOSTRAMOS EL ERROR EN PANTALLA
            lbl_estado.value = "❌ ERROR DE CONEXIÓN"
            lbl_estado.color = "red"
            txt_resultado.value = f"Detalle: {str(ex)}"
            txt_resultado.color = "red"
            prg_loading.visible = False
            btn_conectar.disabled = False # Habilitamos para probar de nuevo
            page.update()

    # --- BOTONES ---
    btn_conectar = ft.ElevatedButton("CONECTAR A GOOGLE", on_click=conectar_google, bgcolor="blue", color="white", height=50)
    
    # Este botón solo aparece si funcionó
    def ir_al_menu(e):
        page.clean()
        page.add(ft.Text("¡Bienvenida al Sistema!", size=25))
    
    btn_entrar = ft.ElevatedButton("ENTRAR AL SISTEMA", on_click=ir_al_menu, bgcolor="green", color="white", height=50, visible=False)

    # --- ARMADO DE PANTALLA INICIAL ---
    page.add(
        ft.Column([
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
    )

if __name__ == "__main__":
    ft.app(target=main)
