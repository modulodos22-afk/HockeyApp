"""
HockeyApp - Gestión Total
Versión mejorada: estructura limpia, manejo de errores robusto,
caché de datos, reconexión automática a Google Sheets.
"""

import flet as ft
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import calendar
import re
import time
import logging
import threading
import json
import requests

# --- LOGGING (reemplaza tracemalloc en producción) ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("HockeyApp")

# --- LIBRERÍA PDF ---
try:
    from fpdf import FPDF
    TIENE_PDF = True
except ImportError:
    TIENE_PDF = False
    log.warning("fpdf no instalado. Generación de PDF deshabilitada.")

# ==============================================================
# CONSTANTES
# ==============================================================
NOMBRE_SPREADSHEET = "HockeyApp_DB"
ARCHIVO_CONFIG     = "categoria_guardada.txt"
ARCHIVO_CLUB       = "club_guardado.txt"

TITULOS_SKILLS = ["Push", "Dribbling", "Flick", "Pegada", "Barrida", "Físico", "Quites"]
MAPA_MESES     = {
    "Enero":1,"Febrero":2,"Marzo":3,"Abril":4,"Mayo":5,"Junio":6,
    "Julio":7,"Agosto":8,"Septiembre":9,"Octubre":10,"Noviembre":11,"Diciembre":12
}
LISTA_MESES  = list(MAPA_MESES.keys())
DIAS_ESP     = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
LETRAS_DIAS  = ["L","M","M","J","V","S","D"]

# Colores — Paleta moderna 2025
C_AZUL       = "#1565C0"   # azul profundo
C_VERDE      = "#2E7D32"   # verde bosque
C_ROJO       = "#C62828"   # rojo profundo
C_FONDO      = "#EEF2FF"   # fondo azul-blanco suave
C_BLANCO     = "#FFFFFF"
C_GRIS       = "#D0D9F0"   # gris azulado claro
C_GRIS_CLARO = "#F5F7FF"   # blanco azulado
C_VIOLETA    = "#4527A0"   # violeta profundo
C_AMARILLO   = "#E65100"   # naranja ambar
C_TEXTO      = "#0D1B4B"   # texto azul oscuro
C_GRIS_TXT   = "#546E7A"   # gris azulado medio
C_ACCENT     = "#00ACC1"   # teal acento

# ==============================================================
# CAPA DE DATOS — SheetsService
# ==============================================================
class SheetsService:
    """
    Encapsula toda la comunicación con Google Sheets.
    Incluye reconexión automática y caché simple por TTL.
    """
    _SCOPE = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    _CACHE_TTL = 60  # segundos

    def __init__(self):
        self._client    = None
        self._sh        = None
        self._worksheets: dict = {}
        self._cache: dict      = {}      # {key: (timestamp, data)}
        self._conectar()

    # ----------------------------------------------------------
    # Conexión / reconexión
    # ----------------------------------------------------------
    def _conectar(self):
        try:
            creds        = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", self._SCOPE)
            self._client = gspread.authorize(creds)
            self._sh     = self._client.open(NOMBRE_SPREADSHEET)
            self._worksheets = {}   # limpia caché de hojas
            log.info("Conectado a Google Sheets OK")
        except Exception as e:
            log.error(f"Error conectando a Sheets: {e}")
            raise

    def _get_ws(self, nombre: str):
        if nombre not in self._worksheets:
            try:
                self._worksheets[nombre] = self._sh.worksheet(nombre)
            except gspread.exceptions.WorksheetNotFound:
                log.warning(f"Hoja '{nombre}' no encontrada.")
                return None
        return self._worksheets[nombre]

    def _with_retry(self, fn, *args, **kwargs):
        """Ejecuta fn; si falla por token expirado reconecta y reintenta una vez."""
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            log.warning(f"APIError, reconectando... ({e})")
            self._conectar()
            return fn(*args, **kwargs)

    # ----------------------------------------------------------
    # Caché
    # ----------------------------------------------------------
    def _cache_get(self, key):
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._CACHE_TTL:
                return data
        return None

    def _cache_set(self, key, data):
        self._cache[key] = (time.time(), data)

    def invalidar_cache(self, key=None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    # ----------------------------------------------------------
    # API pública
    # ----------------------------------------------------------
    def get_all(self, hoja: str) -> list:
        cached = self._cache_get(hoja)
        if cached is not None:
            return cached
        ws = self._get_ws(hoja)
        if ws is None:
            return []
        data = self._with_retry(ws.get_all_values)
        self._cache_set(hoja, data)
        return data

    def append(self, hoja: str, fila: list):
        ws = self._get_ws(hoja)
        if ws is None:
            raise ValueError(f"Hoja '{hoja}' no existe")
        self._with_retry(ws.append_row, fila)
        self.invalidar_cache(hoja)

    def update_range(self, hoja: str, rango: str, valores: list):
        ws = self._get_ws(hoja)
        if ws is None:
            raise ValueError(f"Hoja '{hoja}' no existe")
        self._with_retry(ws.update, rango, valores)
        self.invalidar_cache(hoja)

    def clear_and_write(self, hoja: str, filas: list):
        ws = self._get_ws(hoja)
        if ws is None:
            raise ValueError(f"Hoja '{hoja}' no existe")
        self._with_retry(ws.clear)
        if filas:
            self._with_retry(ws.append_rows, filas)
        self.invalidar_cache(hoja)

    def delete_row(self, hoja: str, idx: int):
        ws = self._get_ws(hoja)
        if ws is None:
            raise ValueError(f"Hoja '{hoja}' no existe")
        self._with_retry(ws.delete_rows, idx)
        self.invalidar_cache(hoja)

    def insert_row(self, hoja: str, fila: list, idx: int):
        ws = self._get_ws(hoja)
        if ws is None:
            raise ValueError(f"Hoja '{hoja}' no existe")
        self._with_retry(ws.insert_row, fila, idx)
        self.invalidar_cache(hoja)

    def tiene_hoja(self, nombre: str) -> bool:
        return self._get_ws(nombre) is not None


# ==============================================================
# UTILIDADES
# ==============================================================
def safe_int(val) -> int:
    try:
        return int(float(str(val))) if val else 0
    except Exception:
        return 0


def calcular_edad(fecha_nac: str) -> str:
    try:
        fmt = "%d/%m/%Y" if "/" in str(fecha_nac) else "%d-%m-%Y"
        nac = datetime.strptime(str(fecha_nac), fmt)
        hoy = datetime.now()
        edad = hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
        return str(edad)
    except Exception:
        return "?"


def clean_latin(t: str) -> str:
    if not t:
        return ""
    try:
        return str(t).encode("latin-1", "replace").decode("latin-1")
    except Exception:
        return str(t)


def leer_archivo(path: str, default: str = "") -> str:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip() or default
        except Exception as e:
            log.warning(f"No se pudo leer {path}: {e}")
    return default


def escribir_archivo(path: str, contenido: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(contenido)
    except Exception as e:
        log.warning(f"No se pudo escribir {path}: {e}")


# ==============================================================
# GENERADORES PDF
# ==============================================================
class PDFGenerator:
    """Centraliza toda la lógica de generación de PDFs."""

    def __init__(self, assets_dir: str, categoria_fn, club_fn):
        self._assets     = assets_dir
        self._categoria  = categoria_fn   # callable → str
        self._club       = club_fn        # callable → str
        os.makedirs(self._assets, exist_ok=True)

    def _guardar(self, pdf: "FPDF", prefijo: str):
        nombre = f"{prefijo}_{int(time.time())}.pdf"
        ruta   = os.path.join(self._assets, nombre)
        pdf.output(ruta)
        return f"/{nombre}"

    # ----------------------------------------------------------
    def resumen_partidos(self, partidos_raw: list):
        if not TIENE_PDF:
            return False, "fpdf no instalado", None
        try:
            pdf = FPDF("P", "mm", "A4")
            pdf.add_page()
            club     = self._club()
            categoria = self._categoria()

            # Header
            pdf.set_fill_color(33, 150, 243)
            pdf.rect(0, 0, 210, 20, "F")
            pdf.set_y(6)
            pdf.set_font("Arial", "B", 14)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(0, 8, clean_latin(f"RESUMEN TECNICO - {club.upper()} ({categoria.upper()})"), align="C", ln=1)
            pdf.set_font("Arial", "I", 9)
            pdf.cell(0, 5, f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", align="C", ln=1)
            pdf.ln(8)

            if not partidos_raw:
                pdf.set_text_color(0)
                pdf.cell(0, 10, "No hay partidos registrados.", align="C")
                return True, "Listo", self._guardar(pdf, "resumen_tecnico")

            tot_gf = tot_gc = tot_cf = tot_cc = 0
            goleadoras: dict = {}
            for r in partidos_raw:
                if len(r) >= 5:
                    tot_gf += safe_int(r[3])
                    tot_gc += safe_int(r[4])
                if len(r) >= 7:
                    tot_cf += safe_int(r[5])
                    tot_cc += safe_int(r[6])
                if len(r) >= 8 and r[7]:
                    for p in r[7].split(","):
                        m = re.search(r"(.+)\((\d+)\)", p)
                        if m:
                            n = m.group(1).strip()
                            goleadoras[n] = goleadoras.get(n, 0) + int(m.group(2))

            def draw_box(x, y, w, h, title, val, bg_c):
                pdf.set_fill_color(*bg_c)
                pdf.rect(x, y, w, h, "F")
                pdf.set_xy(x, y + 2)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font("Arial", "B", 8)
                pdf.cell(w, 4, clean_latin(title), align="C", ln=1)
                pdf.set_xy(x, y + 7)
                pdf.set_font("Arial", "B", 14)
                pdf.cell(w, 8, str(val), align="C")

            w_box, gap = 34, 4
            x_s = (210 - (w_box * 5 + gap * 4)) / 2
            draw_box(x_s,                    30, w_box, 16, "Partidos",   len(partidos_raw), (96, 125, 139))
            draw_box(x_s + (w_box+gap),      30, w_box, 16, "Goles Fav", tot_gf,            (76, 175, 80))
            draw_box(x_s + (w_box+gap)*2,    30, w_box, 16, "Goles Con", tot_gc,            (244, 67, 54))
            draw_box(x_s + (w_box+gap)*3,    30, w_box, 16, "Corn Fav",  tot_cf,            (33, 150, 243))
            draw_box(x_s + (w_box+gap)*4,    30, w_box, 16, "Corn Con",  tot_cc,            (255, 152, 0))
            pdf.ln(22)

            # Goleadoras
            pdf.set_text_color(0); pdf.set_font("Arial", "B", 10)
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(0, 7, "  TOP GOLEADORAS", 1, 1, "L", True)
            pdf.set_font("Arial", "B", 8)
            pdf.cell(15, 6, "PUESTO", 1, 0, "C")
            pdf.cell(145, 6, "JUGADORA", 1, 0, "L")
            pdf.cell(30, 6, "GOLES", 1, 1, "C")
            pdf.set_font("Arial", "", 8)
            for rank, (n, g) in enumerate(sorted(goleadoras.items(), key=lambda x: x[1], reverse=True), 1):
                pdf.cell(15, 6, str(rank), 1, 0, "C")
                pdf.cell(145, 6, clean_latin(n), 1, 0, "L")
                pdf.cell(30, 6, str(g), 1, 1, "C")
                if rank >= 15:
                    break
            pdf.ln(5)

            # Detalle partidos
            pdf.set_font("Arial", "B", 10)
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(0, 7, "  DETALLE DE PARTIDOS", 1, 1, "L", True)
            pdf.set_font("Arial", "B", 7)
            for lbl, w in [("FECHA",18),("RIVAL",42),("COND.",15),("RES (F-C)",18),("CORN (F-C)",18),("GOLEADORAS",79)]:
                pdf.cell(w, 6, lbl, 1, 0, "C")
            pdf.ln()
            pdf.set_font("Arial", "", 7)
            for r in partidos_raw:
                if len(r) < 5:
                    continue
                f_gol = clean_latin(r[7]) if len(r) > 7 else ""
                if len(f_gol) > 65:
                    f_gol = f_gol[:62] + "..."
                pdf.cell(18, 6, clean_latin(r[0][:10]),               1, 0, "C")
                pdf.cell(42, 6, clean_latin(r[1][:25]),               1, 0, "L")
                pdf.cell(15, 6, clean_latin(r[2][:3].upper()),        1, 0, "C")
                pdf.cell(18, 6, f"{safe_int(r[3])} - {safe_int(r[4])}", 1, 0, "C")
                pdf.cell(18, 6, f"{safe_int(r[5])} - {safe_int(r[6])}" if len(r)>6 else "0-0", 1, 0, "C")
                pdf.cell(79, 6, f_gol or "-",                         1, 1, "L")

            return True, "Listo", self._guardar(pdf, "resumen_tecnico")
        except Exception as e:
            log.error(f"PDF resumen error: {e}")
            return False, str(e), None

    # ----------------------------------------------------------
    def formacion(self, partido_str, esquema_str, titulares_dict, ausentes_list, suplentes_dict, notas=""):
        # suplentes_dict: {"Defensoras": [...], "Volantes": [...], "Delanteras": [...]}
        # backwards-compat: si llega como lista plana la metemos en Defensoras
        if isinstance(suplentes_dict, list):
            suplentes_dict = {"Defensoras": suplentes_dict, "Volantes": [], "Delanteras": []}
        if not TIENE_PDF:
            return False, "fpdf no instalado", None
        try:
            import math
            categoria = self._categoria()
            club      = self._club()
            pdf = FPDF("L", "mm", "A4")
            pdf.set_auto_page_break(auto=False)
            pdf.add_page()
            W, H = 297, 210

            # ── PALETA ───────────────────────────────────────────────
            FONDO       = (205, 242, 231)   # verde agua pastel
            FIELD_A     = (68,  114, 196)   # azul cancha (par)
            FIELD_B     = (55,   98, 178)   # azul cancha (impar)
            HEADER_BG   = (34,   94, 110)   # teal header
            PANEL_BG    = (255, 255, 255)   # panel blanco
            PANEL_BD    = (170, 210, 195)   # borde panel
            FOOTER_BG   = (34,   94, 110)
            C_BLANCO_PDF = (255, 255, 255)
            C_NEGRO     = (30,   30,  30)

            # Colores secciones panel
            SEC = {
                "Defensoras": ((220, 234, 255), (35,  75, 160), "DEF"),
                "Volantes":   ((220, 248, 225), (30, 120,  55), "VOL"),
                "Delanteras": ((255, 243, 218), (170, 90,  15), "DEL"),
            }
            AUS_BG    = (255, 228, 228)
            AUS_TITLE = (170,  35,  35)

            # ── FONDO ────────────────────────────────────────────────
            pdf.set_fill_color(*FONDO)
            pdf.rect(0, 0, W, H, "F")

            # ── LAYOUT ───────────────────────────────────────────────
            panel_w  = 86
            header_h = 24
            footer_h = 10
            margin   = 5
            gap_cp   = 9

            avail_h = H - header_h - footer_h - margin * 2
            ch = int(avail_h * 0.90)
            cw = int(ch * 1.38)

            cy = header_h + margin + (avail_h - ch) // 2
            total_used = cw + gap_cp + panel_w
            cx = max(4, (W - total_used) // 2)
            px_p = cx + cw + gap_cp
            pw   = panel_w

            # ── CANCHA AZUL ───────────────────────────────────────────
            n_f = 11
            fw  = cw / n_f
            for i in range(n_f):
                col = FIELD_A if i % 2 == 0 else FIELD_B
                pdf.set_fill_color(*col)
                pdf.rect(cx + i*fw, cy, fw + 0.3, ch, "F")

            # Líneas blancas
            pdf.set_draw_color(*C_BLANCO_PDF); pdf.set_line_width(0.7)
            pdf.rect(cx, cy, cw, ch)
            pdf.set_line_width(0.5)
            pdf.line(cx+cw/2, cy, cx+cw/2, cy+ch)
            pdf.set_line_width(0.3)
            pdf.line(cx+cw*0.25, cy, cx+cw*0.25, cy+ch)
            pdf.line(cx+cw*0.75, cy, cx+cw*0.75, cy+ch)

            # Círculo central
            pdf.set_line_width(0.5)
            r_circ = 13
            pdf.ellipse(cx+cw/2-r_circ, cy+ch/2-r_circ, r_circ*2, r_circ*2)
            pdf.set_fill_color(*C_BLANCO_PDF)
            pdf.ellipse(cx+cw/2-1, cy+ch/2-1, 2, 2, "F")

            # Semicírculos y penales (arcos)
            r_sol = 25; r_dot = 36
            pdf.set_draw_color(*C_BLANCO_PDF); pdf.set_line_width(0.6)
            pdf.ellipse(cx - r_sol, cy+ch/2-r_sol, r_sol*2, r_sol*2)
            pdf.set_line_width(0.25)
            for ang in range(-85, 86, 12):
                a1, a2 = math.radians(ang), math.radians(ang+7)
                pdf.line(cx+r_dot*math.cos(a1), (cy+ch/2)+r_dot*math.sin(a1),
                         cx+r_dot*math.cos(a2), (cy+ch/2)+r_dot*math.sin(a2))
            pdf.set_line_width(0.6)
            pdf.ellipse(cx+cw-r_sol, cy+ch/2-r_sol, r_sol*2, r_sol*2)
            pdf.set_line_width(0.25)
            for ang in range(95, 266, 12):
                a1, a2 = math.radians(ang), math.radians(ang+7)
                pdf.line((cx+cw)+r_dot*math.cos(a1), (cy+ch/2)+r_dot*math.sin(a1),
                         (cx+cw)+r_dot*math.cos(a2), (cy+ch/2)+r_dot*math.sin(a2))

            # Tapar lo que se sale de la cancha con el fondo
            pdf.set_fill_color(*FONDO); pdf.set_draw_color(*FONDO)
            pdf.rect(0,     cy, cx,        ch+1, "F")
            pdf.rect(cx+cw, cy, W-cx-cw+2, ch+1, "F")
            # Reborder exterior
            pdf.set_draw_color(*C_BLANCO_PDF); pdf.set_line_width(0.7)
            pdf.rect(cx, cy, cw, ch)
            # Arcos de portería — gris claro con sombra
            pdf.set_fill_color(140, 140, 140)
            pdf.rect(cx-2.5,    cy+ch/2-6.5, 3, 14, "F")
            pdf.rect(cx+cw+0.5, cy+ch/2-6.5, 3, 14, "F")
            pdf.set_fill_color(215, 215, 215)
            pdf.rect(cx-3,   cy+ch/2-7, 3, 14, "F")
            pdf.rect(cx+cw,  cy+ch/2-7, 3, 14, "F")

            # ── CAMISETAS ────────────────────────────────────────────
            coords = {
                "Arquera (1)":          (0.04, 0.50),
                "Libero (2)":           (0.17, 0.50),
                "Stopper (6)":          (0.44, 0.50),
                "Half Der. (4)":        (0.22, 0.18),
                "Half Izq. (3)":        (0.22, 0.82),
                "Volante Central (5)":  (0.44, 0.68),
                "Volante Der. (8)":     (0.46, 0.22),
                "Volante Izq. (10)":    (0.46, 0.78),
                "Wing Der. (7)":        (0.65, 0.27),
                "Delantera Centro (9)": (0.75, 0.50),
                "Wing Izq. (11)":       (0.65, 0.73),
            }
            if esquema_str == "Doble 5":
                coords["Stopper (6)"]         = (0.44, 0.38)
                coords["Volante Central (5)"] = (0.44, 0.62)

            def dibujar_camiseta(ax, ay, num, es_arq=False):
                """Camiseta con diseño diagonal azul/verde (o rosa/azul para arquera).
                Contorno blanco SOLO por fuera de la silueta completa, sin líneas internas."""
                c_a = (214, 48, 144) if es_arq else (61, 184, 88)   # izq / arriba
                c_b = (16, 64, 160)                                   # der / abajo
                wb = 7.5; hb = 9.5
                wm = 2.6; hm = 2.6
                mx = ax - wb/2; my = ay - hb/2

                # Sombra de la camiseta
                pdf.set_fill_color(80, 80, 80)
                pdf.rect(mx+0.9, my+0.9, wb+wm*0.3, hb, "F")

                # Diagonal: triángulo superior-izquierdo = c_a, inferior-derecho = c_b
                # Dibujamos fondo c_b primero, luego triángulo c_a encima
                # Cuerpo fondo (color b)
                pdf.set_fill_color(*c_b); pdf.set_draw_color(*c_b); pdf.set_line_width(0)
                pdf.rect(mx, my, wb, hb, "F")

                # Triángulo superior-izquierdo (color a) — simulado con franjas
                # Diagonal de (mx, my) a (mx+wb, my+hb)
                # Para cada columna x, la diagonal está en y = my + (x-mx)*(hb/wb)
                strip_w = 0.5
                nx = int(wb / strip_w) + 1
                for i in range(nx):
                    x_col = mx + i * strip_w
                    y_diag = my + i * strip_w * (hb / wb)
                    h_strip = y_diag - my
                    if h_strip > 0:
                        pdf.set_fill_color(*c_a)
                        pdf.rect(x_col, my, min(strip_w, mx+wb-x_col), min(h_strip, hb), "F")

                # Mangas sin contorno
                pdf.set_fill_color(*c_a); pdf.set_draw_color(*c_a)
                pdf.rect(mx-wm, my, wm, hm, "F")
                pdf.set_fill_color(*c_b); pdf.set_draw_color(*c_b)
                pdf.rect(mx+wb, my, wm, hm, "F")

                # Contorno externo COMPLETO de la silueta (cuerpo + mangas como forma)
                # Dibujamos el perímetro exterior como polígono de líneas
                pdf.set_draw_color(255, 255, 255); pdf.set_line_width(0.5)
                # Silueta: top de manga izq → top manga izq → top cuerpo → top manga der → ...
                # Simplificado: contorno del cuerpo + contorno de cada manga por fuera
                # Cuerpo exterior
                pdf.line(mx,    my,    mx+wb, my)        # top
                pdf.line(mx+wb, my,    mx+wb, my+hb)     # right
                pdf.line(mx+wb, my+hb, mx,    my+hb)     # bottom
                pdf.line(mx,    my+hb, mx,    my)        # left
                # Manga izq — solo lados exteriores (top, left, bottom)
                pdf.line(mx-wm, my,    mx,    my)        # top manga izq
                pdf.line(mx-wm, my,    mx-wm, my+hm)    # left manga izq
                pdf.line(mx-wm, my+hm, mx,    my+hm)    # bottom manga izq
                # Manga der — solo lados exteriores
                pdf.line(mx+wb, my,    mx+wb+wm, my)     # top manga der
                pdf.line(mx+wb+wm, my, mx+wb+wm, my+hm) # right manga der
                pdf.line(mx+wb+wm, my+hm, mx+wb, my+hm) # bottom manga der

                # Número blanco grande centrado en el cuerpo de la camiseta
                pdf.set_font("Arial", "B", 13)
                num_str = str(num)
                nw = pdf.get_string_width(num_str)
                center_y = my + hb * 0.68
                for dx, dy in [(-0.4,0),(0.4,0),(0,-0.4),(0,0.4)]:
                    pdf.set_text_color(0,0,0)
                    pdf.text(ax-nw/2+dx, center_y+dy, num_str)
                pdf.set_text_color(255,255,255)
                pdf.text(ax-nw/2, center_y, num_str)
                return my + hb + 0.5

            def dibujar_nombre(ax, y_base, nombre):
                nom = clean_latin(nombre)
                nom = re.sub(r'\(.*?\)', '', nom).strip()
                partes = [p for p in nom.split() if p]
                if len(partes) >= 2:
                    inicial = partes[0][0].upper() + "."
                    apellido = " ".join(partes[1:])
                    nom = f"{inicial} {apellido}"[:16]
                elif partes:
                    nom = partes[0][:16]
                else:
                    nom = "?"
                pdf.set_font("Arial", "B", 9)
                wn = pdf.get_string_width(nom) + 5
                # Sombra del badge
                pdf.set_fill_color(20, 30, 60)
                pdf.rect(ax - wn/2 + 0.6, y_base + 0.6, wn, 5.8, "F")
                # Badge azul oscuro
                pdf.set_fill_color(18, 52, 120)
                pdf.set_draw_color(18, 52, 120)
                pdf.rect(ax - wn/2, y_base, wn, 5.8, "F")
                pdf.set_text_color(255, 255, 255)
                pdf.text(ax - wn/2 + 2.5, y_base + 4.5, nom)

            for pos, jug in titulares_dict.items():
                if not jug: continue
                px, py = coords.get(pos, (0.5, 0.5))
                ax = cx + cw * px
                ay = cy + ch * py
                n_p = re.search(r"\((\d+)\)", pos)
                num = n_p.group(1) if n_p else "?"
                y_nom = dibujar_camiseta(ax, ay, num, "Arquera" in pos)
                dibujar_nombre(ax, y_nom, jug)

            # ── REFERENCIAS DEBAJO CANCHA ─────────────────────────────
            ref_y = cy + ch + 2
            pdf.set_font("Arial", "", 6.5); pdf.set_text_color(60, 80, 70)
            pdf.text(cx + 2, ref_y + 3.5, clean_latin("Arq.  = Rosa/Azul     Jugadora = Verde/Azul"))

            # ── PANEL DERECHO BLANCO ──────────────────────────────────
            # Sombra sutil
            pdf.set_fill_color(180, 210, 198)
            pdf.rect(px_p+1.5, cy+1.5, pw, ch, "F")
            # Fondo blanco
            pdf.set_fill_color(*PANEL_BG)
            pdf.rect(px_p, cy, pw, ch, "F")
            pdf.set_draw_color(*PANEL_BD); pdf.set_line_width(0.5)
            pdf.rect(px_p, cy, pw, ch)

            y_cur = cy + 4

            # Total citadas — dos líneas, sin abreviar
            total_tit = len([v for v in titulares_dict.values() if v])
            total_sup = sum(len(v) for v in suplentes_dict.values())
            total_cit = total_tit + total_sup
            pdf.set_font("Arial", "B", 9); pdf.set_text_color(*C_NEGRO)
            pdf.text(px_p + 4, y_cur + 5,
                     clean_latin(f"Total citadas: {total_cit}"))
            pdf.set_font("Arial", "", 7.5); pdf.set_text_color(60, 80, 70)
            pdf.text(px_p + 4, y_cur + 11,
                     clean_latin(f"{total_tit} titulares + {total_sup} suplentes"))
            y_cur += 18
            pdf.set_draw_color(*PANEL_BD); pdf.set_line_width(0.3)
            pdf.line(px_p + 3, y_cur, px_p + pw - 3, y_cur)
            y_cur += 4

            # SUPLENTES por categoría
            ORDEN_CATS = ["Defensoras", "Volantes", "Delanteras"]
            for cat in ORDEN_CATS:
                lista_cat = suplentes_dict.get(cat, [])
                if not lista_cat:
                    continue
                bg_c, tx_c, tag = SEC[cat]
                # Cabecera: fondo de color, texto en negro
                pdf.set_fill_color(*bg_c)
                pdf.rect(px_p+2, y_cur, pw-4, 6.5, "F")
                pdf.set_font("Arial", "B", 8); pdf.set_text_color(30, 30, 30)
                pdf.text(px_p + 4, y_cur + 5,
                         clean_latin(f"{cat.upper()}  ({len(lista_cat)})"))
                y_cur += 10
                # Jugadoras enumeradas
                pdf.set_font("Arial", "", 9)
                for i, nom in enumerate(lista_cat[:5], 1):
                    pdf.set_text_color(*C_NEGRO)
                    pdf.text(px_p + 4, y_cur, clean_latin(f"{i}. {nom}"))
                    y_cur += 6.5
                y_cur += 3

            # AUSENTES
            if ausentes_list:
                aus_rows = sum(1 + (1 if a.get("motivo") else 0) for a in ausentes_list[:5])
                aus_block = aus_rows * 5.5 + 14 + (10 + 4*6 if notas else 0)
                y_cur = max(y_cur, cy + ch - aus_block)
                pdf.set_fill_color(*AUS_BG)
                pdf.rect(px_p+2, y_cur, pw-4, 6.5, "F")
                pdf.set_font("Arial", "B", 8); pdf.set_text_color(*AUS_TITLE)
                pdf.text(px_p + 4, y_cur + 5, "AUSENTES")
                y_cur += 10
                for a in ausentes_list[:5]:
                    n = clean_latin(a["nombre"])
                    # Nombre: truncar por ancho real
                    pdf.set_font("Arial", "B", 8.5)
                    nom_line = f"- {n}"
                    while pdf.get_string_width(nom_line) > pw - 9 and len(nom_line) > 3:
                        nom_line = nom_line[:-1]
                    pdf.set_text_color(*AUS_TITLE)
                    pdf.text(px_p + 4, y_cur, nom_line)
                    y_cur += 5.5
                    # Motivo en línea separada
                    if a.get("motivo"):
                        mot = clean_latin(a["motivo"])
                        pdf.set_font("Arial", "I", 7.5)
                        mot_line = mot
                        while pdf.get_string_width(f"  {mot_line}") > pw - 9 and len(mot_line) > 3:
                            mot_line = mot_line[:-1]
                        pdf.set_text_color(150, 50, 50)
                        pdf.text(px_p + 7, y_cur, clean_latin(f"  {mot_line}"))
                        y_cur += 5

            # NOTAS al pie del panel
            if notas and notas.strip():
                notas_y = cy + ch - 2  # anclar al fondo del panel
                notas_lines = []
                words = clean_latin(notas.strip()).split()
                line_buf = ""
                for w in words:
                    test = (line_buf + " " + w).strip()
                    pdf.set_font("Arial", "", 7.5)
                    if pdf.get_string_width(test) <= pw - 10:
                        line_buf = test
                    else:
                        notas_lines.append(line_buf)
                        line_buf = w
                if line_buf:
                    notas_lines.append(line_buf)
                notas_lines = notas_lines[:4]
                box_h = len(notas_lines) * 5 + 9
                notas_y = cy + ch - box_h - 2
                pdf.set_fill_color(232, 232, 232)
                pdf.rect(px_p+2, notas_y, pw-4, box_h, "F")
                pdf.set_draw_color(190, 190, 190); pdf.set_line_width(0.3)
                pdf.rect(px_p+2, notas_y, pw-4, box_h)
                pdf.set_font("Arial", "BI", 7.5); pdf.set_text_color(60, 60, 60)
                pdf.text(px_p + 4, notas_y + 5.5, "Notas:")
                pdf.set_font("Arial", "", 7.5); pdf.set_text_color(40, 40, 40)
                for i, ln in enumerate(notas_lines):
                    pdf.text(px_p + 4, notas_y + 5.5 + (i+1)*5, clean_latin(ln))

            # ── HEADER teal ───────────────────────────────────────────
            pdf.set_fill_color(*HEADER_BG)
            pdf.rect(0, 0, W, header_h, "F")
            # Franja inferior más clara
            pdf.set_fill_color(45, 115, 130)
            pdf.rect(0, header_h - 8, W, 8, "F")
            # Título
            pdf.set_font("Arial", "B", 16)
            pdf.set_text_color(*C_BLANCO_PDF)
            pdf.set_xy(0, 2)
            pdf.cell(W, 8, clean_latin(f"{club.upper()}  |  {categoria.upper()}"), align="C")
            pdf.set_font("Arial", "", 8)
            pdf.set_text_color(200, 240, 230)
            pdf.set_xy(0, 11)
            pdf.cell(W, 5, clean_latin(
                f"Formacion: {partido_str}  |  Esquema: {esquema_str}  |  {datetime.now().strftime('%d/%m/%Y')}"
            ), align="C")

            # ── PALO DE HOCKEY (decoración) ───────────────────────────
            sc = 0.17; ox_s, oy_s = 1.5, 0.5
            def stp(x, y): return ox_s + x*sc, oy_s + y*sc
            pdf.set_draw_color(200, 235, 220); pdf.set_line_width(1.6)
            pdf.line(*stp(56,4), *stp(60,62))
            puntos_j = [(60,62),(60,80),(59,88),(55,94),(48,97),(40,97),
                        (33,93),(30,86),(33,79),(39,76),(48,75),(55,77)]
            for i in range(len(puntos_j)-1):
                pdf.line(*stp(*puntos_j[i]), *stp(*puntos_j[i+1]))
            bx2, by2 = stp(80,88); br2 = 7*sc
            pdf.set_fill_color(200,235,220)
            pdf.ellipse(bx2-br2, by2-br2, br2*2, br2*2, "F")

            # ── FOOTER teal ───────────────────────────────────────────
            pdf.set_fill_color(*FOOTER_BG)
            pdf.rect(0, H-footer_h, W, footer_h, "F")
            pdf.set_font("Arial", "", 7); pdf.set_text_color(200, 240, 230)
            pdf.set_xy(0, H-footer_h+2)
            pdf.cell(W, 4, clean_latin(f"HockeyApp  |  {club}  |  {datetime.now().year}"), align="C")

            return True, "Listo", self._guardar(pdf, "formacion")
        except Exception as e:
            log.error(f"PDF formacion error: {e}")
            return False, str(e), None

    def informe_plantel(self, jugadoras, ws_service):
        """PDF comparativo de estadisticas de todo el plantel."""
        if not TIENE_PDF:
            return False, "fpdf no instalado", None
        try:
            import math as _math
            categoria = self._categoria()
            club      = self._club()

            SKILLS = ["Push", "Dribbling", "Flick", "Pegada", "Barrida", "Fisico", "Quites"]

            def norm_dni(d):
                return re.sub(r'[.\-\s]', '', str(d).strip())

            # ── CARGAR DATOS ─────────────────────────────────────
            hab_data = {}
            hab_fechas = []
            try:
                for row in ws_service.get_all("habilidades"):
                    if not row or row[0] == "Fecha": continue
                    row += [""] * max(0, 9 - len(row))
                    dni = norm_dni(row[1])
                    if not dni: continue
                    fecha_h = str(row[0]).strip()
                    if fecha_h:
                        hab_fechas.append(fecha_h)
                    if dni not in hab_data:
                        hab_data[dni] = {s: [] for s in SKILLS}
                    for i, sk in enumerate(SKILLS):
                        try:
                            v = float(str(row[i+2]).replace(",", "."))
                            if 0 < v <= 10:
                                hab_data[dni][sk].append(v)
                        except Exception:
                            pass
            except Exception:
                pass

            # Rango de fechas de evaluaciones
            MESES_ES = ["enero","febrero","marzo","abril","mayo","junio",
                        "julio","agosto","septiembre","octubre","noviembre","diciembre"]
            rango_eval = ""
            if hab_fechas:
                _parsed = []
                for _f in hab_fechas:
                    for _fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                        try:
                            _parsed.append(datetime.strptime(_f, _fmt)); break
                        except Exception:
                            pass
                if _parsed:
                    _mn = min(_parsed); _mx = max(_parsed)
                    if _mn.month == _mx.month and _mn.year == _mx.year:
                        rango_eval = f"Evaluacion: {MESES_ES[_mn.month-1]} {_mn.year}"
                    elif _mn.year == _mx.year:
                        rango_eval = f"Evaluacion: {MESES_ES[_mn.month-1]} a {MESES_ES[_mx.month-1]} de {_mn.year}"
                    else:
                        rango_eval = f"Evaluacion: {MESES_ES[_mn.month-1]} {_mn.year} a {MESES_ES[_mx.month-1]} {_mx.year}"

            asis_data = {}
            asis_part_detail = {}   # {dni: {fecha: True/False}}
            try:
                for row in ws_service.get_all("asistencia"):
                    if not row or row[0] == "Fecha": continue
                    row += [""] * max(0, 4 - len(row))
                    dni = norm_dni(row[1])
                    if not dni: continue
                    if dni not in asis_data:
                        asis_data[dni] = {"ent_si": 0, "ent_tot": 0, "part_si": 0, "part_tot": 0}
                    es_partido = "Partido" in str(row[3])
                    es_si = str(row[2]).strip().upper() == "SI"
                    fecha_a = str(row[0]).strip()
                    if es_partido:
                        asis_data[dni]["part_tot"] += 1
                        if es_si: asis_data[dni]["part_si"] += 1
                        if dni not in asis_part_detail: asis_part_detail[dni] = {}
                        asis_part_detail[dni][fecha_a] = es_si
                    else:
                        asis_data[dni]["ent_tot"] += 1
                        if es_si: asis_data[dni]["ent_si"] += 1
            except Exception:
                pass

            ganados = empates = perdidos = 0
            gf_total = gc_total = 0
            goles_por_nombre = {}
            partidos_lista = []   # [(fecha, rival, condicion)]
            fechas_amistoso = set()
            try:
                for row in ws_service.get_all("partidos"):
                    if not row or row[0] == "Fecha": continue
                    row += [""] * max(0, 8 - len(row))
                    try:
                        fecha_p  = str(row[0]).strip()
                        rival_p  = str(row[1]).strip()
                        cond_p   = str(row[2]).strip()
                        es_amistoso = "mist" in cond_p.lower()
                        partidos_lista.append((fecha_p, rival_p, cond_p))
                        if es_amistoso:
                            fechas_amistoso.add(fecha_p)
                            continue   # no cuenta para W/D/L ni goles
                        gf = int(str(row[3]).strip() or "0")
                        gc = int(str(row[4]).strip() or "0")
                        gf_total += gf; gc_total += gc
                        if   gf > gc: ganados  += 1
                        elif gf == gc: empates  += 1
                        else:          perdidos += 1
                        for m in re.findall(r"(.+?)\((\d+)\)", str(row[7])):
                            nombre, cant = m[0].strip(), int(m[1])
                            goles_por_nombre[nombre] = goles_por_nombre.get(nombre, 0) + cant
                    except Exception:
                        pass
            except Exception:
                pass
            partido_por_fecha = {p[0]: p[1] for p in partidos_lista}

            jugados = ganados + empates + perdidos

            goles_por_dni = {}
            for j in jugadoras:
                nombre_comp = f"{j['nombre']} {j['apellido']}".strip().lower()
                for k, v in goles_por_nombre.items():
                    if nombre_comp in k.lower() or k.lower() in nombre_comp:
                        dni_j = norm_dni(j["dni"])
                        goles_por_dni[dni_j] = goles_por_dni.get(dni_j, 0) + v

            # ── PALETA ────────────────────────────────────────────
            FONDO      = (205, 242, 231)
            HDR_BG     = (34,  94, 110)
            HDR_BG2    = (45, 115, 130)
            C_BL       = (255, 255, 255)
            C_NK       = (30,  30,  30)
            PANEL_BD   = (170, 210, 195)
            C_G        = (76,  175,  80)
            C_Y        = (255, 193,   7)
            C_R        = (229,  57,  53)
            C_TEAL     = (34,  94, 110)

            def sk_bg(v):
                if not v or v <= 0: return (220, 220, 220)
                if v >= 8: return (140, 210, 140)
                if v >= 6: return (200, 235, 180)
                if v >= 4: return (255, 240, 160)
                if v >= 2: return (255, 200, 150)
                return (255, 170, 170)

            def sk_tx(v):
                if not v or v <= 0: return (150, 150, 150)
                if v >= 6: return (20,  90,  20)
                if v >= 4: return (100, 80,   0)
                return (150, 40,  40)

            pdf = FPDF("L", "mm", "A4")
            pdf.set_auto_page_break(auto=False)
            W, H = 297, 210

            def hdr(sub=""):
                pdf.set_fill_color(*HDR_BG)
                pdf.rect(0, 0, W, 22, "F")
                pdf.set_fill_color(*HDR_BG2)
                pdf.rect(0, 14, W, 8, "F")
                pdf.set_font("Arial", "B", 14); pdf.set_text_color(*C_BL)
                pdf.set_xy(0, 2)
                pdf.cell(W, 8, clean_latin(f"{club.upper()}  |  {categoria.upper()}  |  INFORME GENERAL DEL PLANTEL"), align="C")
                pdf.set_font("Arial", "", 7.5); pdf.set_text_color(200, 240, 230)
                pdf.set_xy(0, 11)
                pdf.cell(W, 5, clean_latin(sub or f"Temporada {datetime.now().year}  |  {datetime.now().strftime('%d/%m/%Y')}"), align="C")

            def ftr(msg=""):
                pdf.set_fill_color(*HDR_BG)
                pdf.rect(0, H-10, W, 10, "F")
                pdf.set_font("Arial", "", 7); pdf.set_text_color(200, 240, 230)
                pdf.set_xy(0, H-8)
                pdf.cell(W, 4, clean_latin(msg or f"HockeyApp  |  {club}  |  {datetime.now().strftime('%d/%m/%Y')}"), align="C")

            def panel_box(x, y, w, h, title, tbg, ttx):
                pdf.set_fill_color(160, 195, 180)
                pdf.rect(x+1.5, y+1.5, w, h, "F")
                pdf.set_fill_color(*C_BL)
                pdf.rect(x, y, w, h, "F")
                pdf.set_draw_color(*PANEL_BD); pdf.set_line_width(0.4)
                pdf.rect(x, y, w, h)
                pdf.set_fill_color(*tbg)
                pdf.rect(x, y, w, 8, "F")
                pdf.set_font("Arial", "B", 8.5); pdf.set_text_color(*ttx)
                pdf.text(x+4, y+5.8, clean_latin(title.upper()))
                return y + 11

            # ════════════════════════════════════════════════════════
            # PAG 1 — Resumen del equipo
            # ════════════════════════════════════════════════════════
            pdf.add_page()
            pdf.set_fill_color(*FONDO); pdf.rect(0, 0, W, H, "F")
            hdr()

            MG = 5; TOP = 25; BOT = H - 13
            AH  = BOT - TOP
            PW1 = 88; PW2 = 90; PW3 = W - PW1 - PW2 - MG*4
            X1  = MG; X2 = X1 + PW1 + MG; X3 = X2 + PW2 + MG

            # ── Panel 1: Resultados ───────────────────────────────
            y1 = panel_box(X1, TOP, PW1, AH, "Resultados del equipo", HDR_BG, C_BL)
            pdf.set_font("Arial", "B", 10); pdf.set_text_color(*C_NK)
            pdf.text(X1+4, y1+4, clean_latin(f"Partidos oficiales: {jugados}"))
            y1 += 10

            BX = X1+4; BW = PW1-8; BH = 11
            pG = ganados/jugados if jugados else 0
            pE = empates/jugados if jugados else 0
            pP = perdidos/jugados if jugados else 0
            wG = BW*pG; wE = BW*pE; wP = BW*pP
            pdf.set_fill_color(*C_G);  (wG > 0) and pdf.rect(BX, y1, wG, BH, "F")
            pdf.set_fill_color(*C_Y);  (wE > 0) and pdf.rect(BX+wG, y1, wE, BH, "F")
            pdf.set_fill_color(*C_R);  (wP > 0) and pdf.rect(BX+wG+wE, y1, wP, BH, "F")
            pdf.set_draw_color(180,180,180); pdf.set_line_width(0.3)
            pdf.rect(BX, y1, BW, BH)
            # Porcentajes dentro de la barra
            for col, pct, ox in [(C_BL, pG, wG/2), (C_NK, pE, wG+wE/2), (C_BL, pP, wG+wE+wP/2)]:
                if pct > 0.08:
                    pdf.set_font("Arial", "B", 7); pdf.set_text_color(*col)
                    s = f"{pct*100:.0f}%"
                    pdf.text(BX + ox - pdf.get_string_width(s)/2, y1+7.5, s)
            y1 += 20

            for color, lbl, cnt in [(C_G,"Ganados",ganados),(C_Y,"Empates",empates),(C_R,"Perdidos",perdidos)]:
                pdf.set_fill_color(*color)
                pdf.rect(X1+4, y1-3.5, 4, 4.5, "F")
                pdf.set_font("Arial", "", 7.5); pdf.set_text_color(*C_NK)
                pdf.text(X1+10, y1, clean_latin(f"{lbl}: {cnt}"))
                y1 += 6.5
            # Nota amistoso si aplica
            if partidos_lista and "mist" in partidos_lista[0][2].lower():
                pdf.set_font("Arial", "I", 6.5); pdf.set_text_color(120,120,120)
                pdf.text(X1+4, y1, clean_latin(f"* 1er partido amistoso vs {partidos_lista[0][1][:14]}"))
                y1 += 5
            y1 += 3

            pdf.set_draw_color(*PANEL_BD); pdf.set_line_width(0.3)
            pdf.line(X1+4, y1, X1+PW1-4, y1); y1 += 5
            pdf.set_font("Arial", "B", 8); pdf.set_text_color(*C_TEAL)
            pdf.text(X1+4, y1, "GOLES"); y1 += 6
            dif = gf_total - gc_total
            for lbl, val, tc in [("A favor:", gf_total, C_G), ("En contra:", gc_total, C_R), ("Diferencia:", f"+{dif}" if dif>=0 else str(dif), C_TEAL if dif>=0 else C_R)]:
                pdf.set_font("Arial", "", 8); pdf.set_text_color(*C_NK)
                pdf.text(X1+4, y1, clean_latin(lbl))
                pdf.set_font("Arial", "B", 9); pdf.set_text_color(*tc)
                pdf.text(X1+40, y1, str(val))
                y1 += 6.5
            y1 += 3

            pdf.set_draw_color(*PANEL_BD); pdf.set_line_width(0.3)
            pdf.line(X1+4, y1, X1+PW1-4, y1); y1 += 5
            pdf.set_font("Arial", "B", 8); pdf.set_text_color(*C_TEAL)
            pdf.text(X1+4, y1, "TOP GOLEADORAS"); y1 += 6
            top_g = sorted(goles_por_nombre.items(), key=lambda x: -x[1])[:5]
            PODIO_COLORES = [
                (218, 165,  32),  # 1° oro
                (180, 180, 180),  # 2° plata
                (180, 110,  50),  # 3° bronce
                (150, 190, 210),  # 4°
                (180, 210, 190),  # 5°
            ]
            PODIO_SIZES = [9, 8, 7.5, 7, 7]
            for rank_i, (nom, g) in enumerate(top_g):
                col_pod = PODIO_COLORES[rank_i]
                sz = PODIO_SIZES[rank_i]
                # Badge con número de puesto
                pdf.set_fill_color(*col_pod)
                pdf.rect(X1+4, y1-4, 5.5, 5.5, "F")
                pdf.set_font("Arial", "B", 6.5); pdf.set_text_color(255, 255, 255)
                pdf.text(X1+4.9, y1, str(rank_i+1))
                # Nombre
                pdf.set_font("Arial", "B" if rank_i == 0 else "", sz)
                pdf.set_text_color(*C_NK)
                pdf.text(X1+11, y1, clean_latin(nom[:16]))
                # Goles alineados a la derecha
                gol_lbl = f"{g} goles"
                pdf.set_font("Arial", "B", sz); pdf.set_text_color(*col_pod)
                pdf.text(X1+PW1 - 4 - pdf.get_string_width(gol_lbl), y1, gol_lbl)
                y1 += 7 if rank_i == 0 else 6

            # ── Panel 2: Asistencia ───────────────────────────────
            y2 = panel_box(X2, TOP, PW2, AH, "Asistencia del plantel", HDR_BG2, C_BL)
            total_ent  = max((d["ent_tot"]  for d in asis_data.values()), default=0)
            total_part = max((d["part_tot"] for d in asis_data.values()), default=0)
            # Totales con números en negrita
            xp = X2 + 4
            for txt_n, val_n in [("Entrenamientos: ", total_ent), ("   |   Partidos: ", total_part)]:
                pdf.set_font("Arial", "", 7.5); pdf.set_text_color(*C_NK)
                pdf.text(xp, y2, clean_latin(txt_n))
                xp += pdf.get_string_width(txt_n)
                pdf.set_font("Arial", "B", 7.5)
                pdf.text(xp, y2, str(val_n))
                xp += pdf.get_string_width(str(val_n))
            # Nota amistoso
            if partidos_lista:
                y2 += 5
                pdf.set_font("Arial", "I", 6.5); pdf.set_text_color(120, 120, 120)
                primer = partidos_lista[0]
                nota_am = f"* 1er partido vs {primer[1][:12]} (amistoso)" if "mist" in primer[2].lower() else f"* 1er partido vs {primer[1][:18]}"
                pdf.text(X2+4, y2, clean_latin(nota_am))
            y2 += 8

            pdf.set_fill_color(225, 242, 238)
            pdf.rect(X2+2, y2-3.5, PW2-4, 6, "F")
            pdf.set_font("Arial", "B", 7); pdf.set_text_color(*C_TEAL)
            pdf.text(X2+3,  y2, "JUGADORA")
            pdf.text(X2+44, y2, "ENT%")
            pdf.text(X2+62, y2, "PART%")
            pdf.text(X2+78, y2, "PJ")
            y2 += 5.5

            asis_jug = []
            for j in jugadoras:
                dni = norm_dni(j["dni"])
                d = asis_data.get(dni, {"ent_si":0,"ent_tot":0,"part_si":0,"part_tot":0})
                nom2 = clean_latin(j["apellido"].upper()[:14])
                pct_e2 = d["ent_si"]/d["ent_tot"]*100 if d["ent_tot"] > 0 else 0
                pct_p2 = d["part_si"]/d["part_tot"]*100 if d["part_tot"] > 0 else 0
                asis_jug.append((nom2, pct_e2, pct_p2, d["part_si"]))
            asis_jug.sort(key=lambda x: -x[1])

            # Rebuild asis_jug with dni for lookup
            asis_jug_ext = []
            for j in jugadoras:
                dni = norm_dni(j["dni"])
                d = asis_data.get(dni, {"ent_si":0,"ent_tot":0,"part_si":0,"part_tot":0})
                nom2 = clean_latin(j["apellido"].upper()[:14])
                pct_e2 = d["ent_si"]/d["ent_tot"]*100 if d["ent_tot"] > 0 else 0
                pct_p2 = d["part_si"]/d["part_tot"]*100 if d["part_tot"] > 0 else 0
                asis_jug_ext.append((nom2, pct_e2, pct_p2, d["part_si"], dni))
            asis_jug_ext.sort(key=lambda x: -x[1])
            asis_jug = [(a,b,c,dd) for a,b,c,dd,_ in asis_jug_ext]

            for idx2, (nom2, pct_e2, pct_p2, pj) in enumerate(asis_jug[:14]):
                rbg = (248,252,250) if idx2 % 2 == 0 else C_BL
                pdf.set_fill_color(*rbg)
                pdf.rect(X2+2, y2-3.5, PW2-4, 5.5, "F")
                col_e = C_G if pct_e2 >= 75 else C_Y if pct_e2 >= 50 else C_R
                pdf.set_fill_color(*col_e)
                bwe = (pct_e2/100)*22
                if bwe > 0: pdf.rect(X2+42, y2-2.5, bwe, 3.5, "F")
                pdf.set_font("Arial", "", 7); pdf.set_text_color(*C_NK)
                pdf.text(X2+3, y2, nom2)
                pdf.set_font("Arial", "B", 7); pdf.set_text_color(*col_e)
                pdf.text(X2+44, y2, f"{pct_e2:.0f}%")
                pdf.set_text_color(*C_NK)
                pdf.text(X2+64, y2, f"{pct_p2:.0f}%")
                pdf.text(X2+80, y2, str(pj))
                y2 += 5.5

            # Faltas en partidos
            y2 += 3
            pdf.set_draw_color(*PANEL_BD); pdf.set_line_width(0.3)
            pdf.line(X2+3, y2, X2+PW2-3, y2); y2 += 4
            pdf.set_font("Arial", "B", 7); pdf.set_text_color(*C_TEAL)
            pdf.text(X2+3, y2, "FALTAS EN PARTIDOS:"); y2 += 5
            faltas_mostradas = False
            for nom2, pct_e2, pct_p2, pj, dni in asis_jug_ext:
                det = asis_part_detail.get(dni, {})
                rivales_faltados = []
                for fecha_p, rival_p in partido_por_fecha.items():
                    if fecha_p in det and not det[fecha_p]:
                        suf = " (amist.)" if fecha_p in fechas_amistoso else ""
                        rivales_faltados.append(rival_p[:12] + suf)
                if rivales_faltados and y2 < BOT - 4:
                    pdf.set_font("Arial", "B", 6.5); pdf.set_text_color(180, 50, 50)
                    pdf.text(X2+3, y2, f"{nom2}:")
                    pdf.set_font("Arial", "", 6.5); pdf.set_text_color(*C_NK)
                    pdf.text(X2+3+pdf.get_string_width(f"{nom2}:")+1, y2,
                             clean_latin(", ".join(rivales_faltados)))
                    y2 += 5
                    faltas_mostradas = True
            if not faltas_mostradas:
                pdf.set_font("Arial", "I", 6.5); pdf.set_text_color(120,120,120)
                pdf.text(X2+3, y2, "Sin faltas registradas")

            # ── Panel 3: Promedios del equipo ─────────────────────
            y3 = panel_box(X3, TOP, PW3, AH, "Habilidades del equipo", HDR_BG, C_BL)
            sk_team = {}
            for sk in SKILLS:
                vals = []
                for d in hab_data.values():
                    vals.extend(d.get(sk, []))
                sk_team[sk] = sum(vals)/len(vals) if vals else 0

            pdf.set_font("Arial", "B", 7.5); pdf.set_text_color(*C_TEAL)
            pdf.text(X3+3, y3, "Promedio general"); y3 += 7
            BMAX = PW3 - 22
            sk_team_display = {sk: sk_team[sk] for sk in ([s for s in SKILLS if s != "Fisico"] + ["Fisico"])}
            for sk, avg in sk_team_display.items():
                pdf.set_fill_color(215, 225, 220)
                pdf.rect(X3+3, y3-4, BMAX, 6, "F")
                if avg > 0:
                    pdf.set_fill_color(*sk_bg(avg))
                    pdf.rect(X3+3, y3-4, (avg/10)*BMAX, 6, "F")
                pdf.set_font("Arial", "", 7); pdf.set_text_color(*C_NK)
                pdf.text(X3+3, y3, clean_latin(sk[:8]))
                if avg > 0:
                    pdf.set_font("Arial", "B", 7); pdf.set_text_color(*sk_tx(avg))
                    pdf.text(X3+3+BMAX+1, y3, f"{avg:.1f}")
                y3 += 8

            y3 += 4
            # Frase motivadora
            pdf.set_font("Arial", "BI", 8); pdf.set_text_color(*C_TEAL)
            if jugados > 0 and ganados/jugados >= 0.6:
                msg = "Excelente temporada! Sigan adelante!"
            elif jugados > 0 and ganados/jugados >= 0.4:
                msg = "Buen rendimiento. A seguir creciendo!"
            else:
                msg = "Cada entrenamiento suma. Vamos juntas!"
            pdf.text(X3+3, y3, clean_latin(msg))
            y3 += 7
            # Resumen de mejora grupal — habilidad(es) más bajas
            sk_con_datos = {k: v for k, v in sk_team.items() if v > 0}
            if sk_con_datos:
                sk_ord = sorted(sk_con_datos.items(), key=lambda x: x[1])
                debiles = [clean_latin(s[:8]) for s, _ in sk_ord[:2]]
                mejora_txt = f"A trabajar: {' y '.join(debiles)}"
                pdf.set_font("Arial", "I", 7); pdf.set_text_color(120, 80, 30)
                pdf.text(X3+3, y3, clean_latin(mejora_txt))

            ftr()

            # ════════════════════════════════════════════════════════
            # PAG 2 — Comparativa de habilidades por jugadora
            # ════════════════════════════════════════════════════════
            pdf.add_page()
            pdf.set_fill_color(*C_BL); pdf.rect(0, 0, W, H, "F")
            _subtit2 = f"Comparativa de Habilidades  |  Temporada {datetime.now().year}"
            if rango_eval:
                _subtit2 += f"  |  {rango_eval}"
            hdr(_subtit2)

            TOP2  = 36
            RH    = 7.5
            C_NOM = 40; C_AS = 15; C_SK = 16; C_PR = 14; SEP_FIS = 5
            # Físico al final del display
            SKILLS_DISPLAY = [s for s in SKILLS if s != "Fisico"] + ["Fisico"]
            FISICO_DISPLAY_IDX = len(SKILLS_DISPLAY) - 1
            TAB_W = C_NOM + C_AS + C_SK * len(SKILLS_DISPLAY) + C_PR + SEP_FIS
            TX    = (W - TAB_W) / 2

            def draw_table_header(yt):
                # Período de evaluación en negrita grande encima de la tabla
                if rango_eval:
                    pdf.set_font("Arial", "B", 9.5); pdf.set_text_color(*HDR_BG)
                    rango_up = clean_latin(rango_eval.upper())
                    rw = pdf.get_string_width(rango_up)
                    pdf.text(TX + (TAB_W - rw) / 2, yt - 4, rango_up)
                pdf.set_fill_color(*HDR_BG)
                pdf.rect(TX, yt, TAB_W, RH, "F")
                pdf.set_font("Arial", "B", 7); pdf.set_text_color(*C_BL)
                cx = TX
                pdf.text(cx+2, yt+5, "JUGADORA");      cx += C_NOM
                pdf.text(cx+2, yt+5, "ASIS%");          cx += C_AS
                for i, sk in enumerate(SKILLS_DISPLAY):
                    if i == FISICO_DISPLAY_IDX:
                        cx += SEP_FIS  # gap separador antes de Fisico
                        pdf.set_fill_color(50, 110, 180)
                        pdf.rect(cx, yt, C_SK, RH, "F")
                        pdf.set_text_color(*C_BL)
                    else:
                        pdf.set_text_color(*C_BL)
                    pdf.text(cx+2, yt+5, clean_latin(sk[:5])); cx += C_SK
                pdf.text(cx+2, yt+5, "PROM")
                return yt + RH

            yt = draw_table_header(TOP2)

            for idx, j in enumerate(sorted(jugadoras, key=lambda x: x.get("apellido",""))):
                if yt > H - 20:
                    ftr(clean_latin(f"HockeyApp  |  {club}  |  continua..."))
                    pdf.add_page()
                    pdf.set_fill_color(*C_BL); pdf.rect(0, 0, W, H, "F")
                    _subtit2c = f"Comparativa de Habilidades (cont.)  |  Temporada {datetime.now().year}"
                    if rango_eval:
                        _subtit2c += f"  |  {rango_eval}"
                    hdr(_subtit2c)
                    yt = draw_table_header(TOP2)

                dni = norm_dni(j["dni"])
                sk_avgs = []
                for sk in SKILLS_DISPLAY:
                    vals = hab_data.get(dni, {}).get(sk, [])
                    sk_avgs.append(sum(vals)/len(vals) if vals else 0)
                validos = [v for v in sk_avgs if v > 0]
                prom = sum(validos)/len(validos) if validos else 0

                d = asis_data.get(dni, {"ent_si":0,"ent_tot":0})
                pct_e3 = d["ent_si"]/d["ent_tot"]*100 if d.get("ent_tot",0) > 0 else 0

                rbg2 = (245, 250, 248) if idx % 2 == 0 else C_BL
                pdf.set_fill_color(*rbg2)
                pdf.rect(TX, yt, TAB_W, RH, "F")
                pdf.set_draw_color(215, 228, 222); pdf.set_line_width(0.15)
                pdf.line(TX, yt+RH, TX+TAB_W, yt+RH)

                cx = TX
                nom_pdf = clean_latin(f"{j['apellido']}, {j['nombre'][:1]}.")[:22]
                pdf.set_font("Arial", "", 7.5); pdf.set_text_color(*C_NK)
                pdf.text(cx+2, yt+5.2, nom_pdf);  cx += C_NOM

                col_a = C_G if pct_e3 >= 75 else C_Y if pct_e3 >= 50 else C_R
                pdf.set_font("Arial", "B", 7.5); pdf.set_text_color(*col_a)
                pdf.text(cx+2, yt+5.2, f"{pct_e3:.0f}%"); cx += C_AS

                for sk_i, sk_v in enumerate(sk_avgs):
                    if sk_i == FISICO_DISPLAY_IDX:
                        cx += SEP_FIS  # gap visual antes de Fisico (último)
                    pdf.set_fill_color(*sk_bg(sk_v))
                    pdf.rect(cx+0.8, yt+0.8, C_SK-1.6, RH-1.6, "F")
                    if sk_v > 0:
                        pdf.set_font("Arial", "B", 7.5); pdf.set_text_color(*sk_tx(sk_v))
                        sw = pdf.get_string_width(f"{sk_v:.1f}")
                        pdf.text(cx + (C_SK-sw)/2, yt+5.2, f"{sk_v:.1f}")
                    else:
                        pdf.set_font("Arial", "", 6); pdf.set_text_color(170,170,170)
                        pdf.text(cx + C_SK/2 - 1, yt+5.2, "-")
                    cx += C_SK

                pdf.set_fill_color(*sk_bg(prom))
                pdf.rect(cx+0.8, yt+0.8, C_PR-1.6, RH-1.6, "F")
                if prom > 0:
                    pdf.set_font("Arial", "B", 8); pdf.set_text_color(*sk_tx(prom))
                    pdf.text(cx+3, yt+5.2, f"{prom:.1f}")

                yt += RH

            # Leyenda
            yt += 12
            if yt < H - 20:
                pdf.set_font("Arial", "B", 7); pdf.set_text_color(*C_NK)
                pdf.text(TX, yt, "Escala de colores:")
                lx2 = TX + 32
                for sc2, lbl2 in [((140,210,140),"8-10 Excelente"),((200,235,180),"6-7 Muy bueno"),
                                   ((255,240,160),"4-5 Bueno"),((255,200,150),"2-3 En desarrollo"),
                                   ((220,220,220),"Sin datos")]:
                    pdf.set_fill_color(*sc2)
                    pdf.rect(lx2, yt-3.5, 5, 5, "F")
                    pdf.set_font("Arial", "", 6.5); pdf.set_text_color(*C_NK)
                    pdf.text(lx2+6, yt, lbl2)
                    lx2 += 44

            ftr(clean_latin(f"HockeyApp  |  {club}  |  Informe confidencial  |  {datetime.now().strftime('%d/%m/%Y')}"))

            return True, "Listo", self._guardar(pdf, "informe_plantel")
        except Exception as e:
            log.error(f"PDF informe_plantel: {e}")
            return False, str(e), None

    # ----------------------------------------------------------
    def plantel_completo(self, jugadoras: list):
        if not TIENE_PDF:
            return False, "fpdf no instalado", None
        try:
            categoria = self._categoria()
            pdf = FPDF("L", "mm", "A4")
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()
            pdf.set_font("Arial", "B", 16); pdf.set_text_color(33, 150, 243)
            pdf.cell(0, 10, clean_latin(f"PLANTEL COMPLETO - {categoria.upper()}"), ln=1, align="C")
            pdf.ln(5)
            pdf.set_font("Arial", "B", 10); pdf.set_fill_color(220, 220, 220); pdf.set_text_color(0)
            w_cols = [15, 40, 40, 30, 30, 35, 40, 20]
            headers = ["N", "Nombre", "Apellido", "DNI", "Nacimiento", "Posición", "Teléfono", "Activo"]
            for i, h in enumerate(headers):
                pdf.cell(w_cols[i], 8, clean_latin(h), 1, 0, "C", True)
            pdf.ln()
            pdf.set_font("Arial", "", 9)
            for i, j in enumerate(jugadoras):
                bg = 245 if i % 2 == 0 else 255
                pdf.set_fill_color(bg, bg, bg)
                vals = [
                    str(j.get("camiseta", "-")), j.get("nombre", "-"), j.get("apellido", "-"),
                    str(j.get("dni", "-")), str(j.get("nacimiento", "-")), j.get("posicion", "-"),
                    str(j.get("telefono", "-")), str(j.get("activo", "-")),
                ]
                for k, v in enumerate(vals):
                    aln = "L" if k in (1, 2) else "C"
                    pdf.cell(w_cols[k], 8, clean_latin(v), 1, 0, aln, True)
                pdf.ln()
            return True, "Listo", self._guardar(pdf, "plantel_completo")
        except Exception as e:
            log.error(f"PDF plantel error: {e}")
            return False, str(e), None

    # ----------------------------------------------------------
    def individual(self, jug_data: dict, ws_service: "SheetsService"):
        if not TIENE_PDF:
            return False, "fpdf no instalado", None
        try:
            categoria = self._categoria()
            pdf = FPDF(); pdf.add_page()
            dni_jug  = str(jug_data["dni"])
            anio_act = datetime.now().year

            pdf.set_font("Arial", "B", 10); pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 5, f"TEMPORADA {anio_act}  -  CATEGORIA: {categoria.upper()}", ln=1, align="R")
            pdf.ln(5)
            pdf.set_font("Arial", "B", 24); pdf.set_text_color(33, 150, 243)
            pdf.cell(0, 15, clean_latin(f"{jug_data['nombre']} {jug_data['apellido']}".upper()), ln=1, align="C")
            pdf.set_text_color(0); pdf.ln(5)

            def seccion(titulo):
                pdf.set_font("Arial", "B", 12); pdf.set_fill_color(240, 240, 240)
                pdf.cell(0, 10, f"  {titulo}", 1, 1, "L", True); pdf.ln(2)

            def dato(lbl, val):
                pdf.set_font("Arial", "B", 11); pdf.cell(50, 8, f"  {lbl}", 0, 0)
                pdf.set_font("Arial", "", 11); pdf.cell(0, 8, clean_latin(str(val)), 0, 1)

            seccion("DATOS PERSONALES")
            dato("Nacimiento:", f"{jug_data['nacimiento']} ({calcular_edad(jug_data['nacimiento'])} años)")
            dato("DNI:", dni_jug)
            dato("N Camiseta:", jug_data.get("camiseta", "-"))
            dato("Posición:", jug_data.get("posicion", "-"))
            dato("Teléfono:", jug_data.get("telefono", "-"))
            pdf.ln(8)

            # Habilidades
            seccion("EVOLUCIÓN TÉCNICA (MES A MES)")
            raw_hab = ws_service.get_all("habilidades")
            w_mes, w_col = 25, 20
            pdf.set_font("Arial", "B", 9); pdf.set_fill_color(255, 255, 255)
            pdf.cell(w_mes, 8, "MES", 1, 0, "C")
            for t in TITULOS_SKILLS:
                pdf.cell(w_col, 8, clean_latin(t[:9]), 1, 0, "C")
            pdf.ln()
            pdf.set_font("Arial", "", 9)
            hay_datos_hab = False
            acum = [0] * len(TITULOS_SKILLS); count_eval = 0
            datos_hab = []
            for row in raw_hab[1:]:
                if str(row[1]) == dni_jug:
                    try:
                        f = datetime.strptime(row[0], "%d/%m/%Y")
                        if f.year == anio_act:
                            datos_hab.append((f, row))
                    except Exception:
                        pass
            datos_hab.sort(key=lambda x: x[0])
            for f_obj, row in datos_hab:
                hay_datos_hab = True; count_eval += 1
                pdf.cell(w_mes, 8, LISTA_MESES[f_obj.month - 1], 1, 0, "L")
                for i in range(len(TITULOS_SKILLS)):
                    val = safe_int(row[i + 2]) if len(row) > i + 2 else 0
                    acum[i] += val
                    pdf.cell(w_col, 8, str(val), 1, 0, "C")
                pdf.ln()
            if hay_datos_hab:
                pdf.set_font("Arial", "B", 9); pdf.set_fill_color(230, 240, 255)
                pdf.cell(w_mes, 8, "GLOBAL", 1, 0, "L", True)
                for tot in acum:
                    pdf.cell(w_col, 8, str(round(tot / count_eval, 1)), 1, 0, "C", True)
                pdf.ln()
            else:
                pdf.cell(0, 8, "Sin evaluaciones registradas este año.", 1, 1, "C")
            pdf.ln(8)

            # Asistencia
            seccion("RESUMEN DE ASISTENCIA (ENTRENAMIENTOS)")
            raw_asist = ws_service.get_all("asistencia")
            asist_mes = {m: {"P": 0, "A": 0} for m in range(1, 13)}
            for row in raw_asist[1:]:
                if str(row[1]) == dni_jug:
                    try:
                        f = datetime.strptime(row[0], "%d/%m/%Y")
                        if f.year == anio_act and "Entrenamiento" in row[3]:
                            if row[2] == "SI":
                                asist_mes[f.month]["P"] += 1
                            elif row[2] == "NO":
                                asist_mes[f.month]["A"] += 1
                    except Exception:
                        pass
            pdf.set_font("Arial", "B", 10)
            for lbl, w in [("MES",40),("ASISTIO",40),("FALTO",40),("% EFECTIVIDAD",40)]:
                pdf.cell(w, 8, lbl, 1, 0, "C")
            pdf.ln(); pdf.ln()
            pdf.set_font("Arial", "", 10)
            tot_p = tot_a = 0
            for m in range(1, 13):
                p = asist_mes[m]["P"]; a = asist_mes[m]["A"]
                if p + a > 0:
                    tot_p += p; tot_a += a
                    pdf.cell(40, 8, LISTA_MESES[m-1], 1, 0, "L")
                    pdf.cell(40, 8, str(p), 1, 0, "C")
                    pdf.cell(40, 8, str(a), 1, 0, "C")
                    pdf.cell(40, 8, f"{int(p/(p+a)*100)}%", 1, 1, "C")
            pdf.set_fill_color(250, 250, 250); pdf.set_font("Arial", "B", 10)
            pdf.cell(40, 8, "TOTAL ANUAL", 1, 0, "L", True)
            pdf.cell(40, 8, str(tot_p), 1, 0, "C", True)
            pdf.cell(40, 8, str(tot_a), 1, 0, "C", True)
            pct = int(tot_p / (tot_p + tot_a) * 100) if (tot_p + tot_a) > 0 else 0
            pdf.cell(40, 8, f"{pct}%", 1, 1, "C", True)
            pdf.ln(8)

            # Goles
            seccion("ESTADÍSTICA DE GOLES")
            raw_part = ws_service.get_all("partidos")
            goles_totales = 0
            for r in raw_part:
                if r and r[0] == "Fecha":
                    continue
                txt_gol = r[7] if len(r) > 7 else ""
                if txt_gol:
                    for p in txt_gol.split(","):
                        if jug_data["apellido"].lower() in p.lower():
                            match = re.search(r"\((\d+)\)", p)
                            if match:
                                goles_totales += int(match.group(1))
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 10, f"Goles convertidos en la temporada: {goles_totales}", 0, 1, "L")

            pdf.set_auto_page_break(False)
            pdf.set_y(-15)
            pdf.set_font("Arial", "I", 8); pdf.set_text_color(128)
            pdf.cell(0, 10, f"Página {pdf.page_no()}", 0, 0, "L")

            return True, "Listo", self._guardar(pdf, f"ficha_{dni_jug}")
        except Exception as e:
            log.error(f"PDF individual error: {e}")
            return False, str(e), None

    # ----------------------------------------------------------
    def mensual(self, mes_num: int, anio: int, ws_service: "SheetsService"):
        if not TIENE_PDF:
            return False, "fpdf no instalado", None
        try:
            categoria = self._categoria()
            raw_asist = ws_service.get_all("asistencia")
            jugadoras = ws_service.get_all("jugadoras")

            lista_jug = []
            if len(jugadoras) > 1:
                for row in jugadoras[1:]:
                    row += [""] * (9 - len(row))
                    if row[3]:
                        lista_jug.append({"dni": row[3], "nombre": f"{row[2]} {row[1]}"})

            datos = {j["dni"]: {"nombre": j["nombre"], "dias": {}} for j in lista_jug}
            obs_mes: dict = {}; dias_susp: set = set()

            for row in raw_asist[1:]:
                if row and row[0] == "Fecha":
                    continue
                try:
                    f = datetime.strptime(row[0], "%d/%m/%Y")
                    if f.month != mes_num or f.year != anio:
                        continue
                    dni = str(row[1]); estado = row[2]; tipo = row[3]
                    obs  = row[4] if len(row) > 4 else ""
                    if "Suspendido" in tipo:
                        letra = "S"; dias_susp.add(f.day)
                    elif estado == "SI":
                        letra = "P"
                    elif estado == "NO":
                        letra = "A"
                    else:
                        letra = ""
                    if dni in datos:
                        datos[dni]["dias"][f.day] = {"l": letra, "tipo": tipo}
                    if obs and obs.strip():
                        obs_mes[f.day] = obs
                except Exception:
                    pass

            pdf = FPDF("L", "mm", "A4"); pdf.add_page()
            nombre_mes = LISTA_MESES[mes_num - 1]
            pdf.set_font("Arial", "B", 18); pdf.set_text_color(33, 150, 243)
            pdf.cell(0, 12, f"ASISTENCIA - {nombre_mes.upper()} {anio} - {categoria.upper()}", ln=1, align="L")
            pdf.ln(2)

            an, ad, af = 55, 6.5, 6
            pdf.set_font("Arial", "B", 7); pdf.set_fill_color(220, 220, 220); pdf.set_text_color(0)
            x0, y0 = pdf.get_x(), pdf.get_y()
            pdf.cell(an, af*2, "JUGADORA", 1, 0, "C", True)
            pdf.set_xy(x0 + an, y0)
            for d in range(1, 32):
                pdf.set_fill_color(255, 200, 200) if d in dias_susp else pdf.set_fill_color(220, 220, 220)
                pdf.cell(ad, af, str(d), 1, 0, "C", True)
            pdf.set_fill_color(187, 222, 251); pdf.cell(12, af*2, "ENTR.", 1, 0, "C", True)
            pdf.set_fill_color(255, 224, 178); pdf.cell(12, af*2, "PART.", 1, 0, "C", True)
            pdf.set_xy(x0 + an, y0 + af)
            pdf.set_font("Arial", "B", 6)
            for d in range(1, 32):
                try:
                    ld = LETRAS_DIAS[datetime(anio, mes_num, d).weekday()]
                except Exception:
                    ld = "-"
                pdf.set_fill_color(255, 200, 200) if d in dias_susp else pdf.set_fill_color(220, 220, 220)
                pdf.cell(ad, af, ld, 1, 0, "C", True)
            pdf.set_xy(x0, y0 + af*2)

            pdf.set_font("Arial", size=8)
            for cnt, (dni, info) in enumerate(datos.items(), 1):
                bg = 245 if cnt % 2 == 0 else 255
                pdf.set_fill_color(bg, bg, bg)
                n_s = info["nombre"]
                try:
                    n_s = n_s.encode("latin-1", "replace").decode("latin-1")
                except Exception:
                    pass
                pdf.cell(an, af, n_s, 1, 0, "L", True)
                c_ent = c_par = 0
                for d in range(1, 32):
                    dd = info["dias"].get(d, {}); l = dd.get("l", ""); tp = dd.get("tipo", "")
                    if l == "P":
                        if "Entrenamiento" in tp: c_ent += 1
                        elif "Partido" in tp:     c_par += 1
                    if d in dias_susp: pdf.set_fill_color(255, 235, 238)
                    else:              pdf.set_fill_color(bg, bg, bg)
                    if   l == "P": pdf.set_text_color(0, 128, 0);  pdf.set_font("Arial", "B", 8)
                    elif l == "A": pdf.set_text_color(200, 0, 0);  pdf.set_font("Arial", "B", 8)
                    else:          pdf.set_text_color(0);           pdf.set_font("Arial", "", 8)
                    pdf.cell(ad, af, l, 1, 0, "C", True)
                pdf.set_text_color(0); pdf.set_font("Arial", "B", 8)
                pdf.set_fill_color(227, 242, 253) if cnt % 2 == 0 else pdf.set_fill_color(187, 222, 251)
                pdf.cell(12, af, str(c_ent), 1, 0, "C", True)
                pdf.set_fill_color(255, 243, 224) if cnt % 2 == 0 else pdf.set_fill_color(255, 224, 178)
                pdf.cell(12, af, str(c_par), 1, 0, "C", True)
                pdf.set_text_color(0); pdf.set_font("Arial", "", 8); pdf.ln()

            pdf.ln(5); pdf.set_font("Arial", "B", 10); pdf.cell(0, 6, "REFERENCIAS:", ln=1)
            pdf.set_font("Arial", size=9)
            pdf.set_text_color(0, 128, 0);  pdf.cell(25, 6, "P = Presente", 0, 0)
            pdf.set_text_color(200, 0, 0);  pdf.cell(25, 6, "A = Ausente", 0, 0)
            pdf.set_text_color(0);          pdf.cell(30, 6, "S = Suspendido", 0, 0)
            pdf.set_fill_color(187, 222, 251); pdf.cell(5, 5, "", 1, 0, "C", True); pdf.cell(35, 6, " Tot. Entrenamientos", 0, 0)
            pdf.set_fill_color(255, 224, 178); pdf.cell(5, 5, "", 1, 0, "C", True); pdf.cell(35, 6, " Tot. Partidos", 0, 1)
            pdf.ln(3)
            if obs_mes:
                pdf.set_font("Arial", "B", 10); pdf.cell(0, 6, "OBSERVACIONES:", ln=1)
                pdf.set_font("Arial", size=9)
                for d, obs in sorted(obs_mes.items()):
                    try:
                        obs = obs.encode("latin-1", "replace").decode("latin-1")
                    except Exception:
                        pass
                    pdf.cell(0, 5, f"- Día {d}: {obs}", ln=1)

            return True, "Listo", self._guardar(pdf, f"mensual_{mes_num}")
        except Exception as e:
            log.error(f"PDF mensual error: {e}")
            return False, str(e), None

    def estadisticas_asistencia(self, stats: dict, meses_con_datos: list):
        if not TIENE_PDF:
            return False, "fpdf no instalado", None
        try:
            MESES_CORTOS = ["ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SEP","OCT","NOV","DIC"]
            club     = self._club()
            categoria = self._categoria()
            pdf = FPDF("P", "mm", "A4")
            pdf.add_page()

            # ── FONDO DEGRADADO SUPERIOR ──────────────────────────
            colores_header = [(33,150,243),(76,175,80),(33,150,243),(76,175,80)]
            ancho_banda = 210 / len(colores_header)
            for i, c in enumerate(colores_header):
                pdf.set_fill_color(*c); pdf.rect(i*ancho_banda, 0, ancho_banda+1, 28, "F")

            # Título
            pdf.set_y(4); pdf.set_font("Arial","B",18); pdf.set_text_color(255,255,255)
            pdf.cell(0, 8, clean_latin("RANKING DE ASISTENCIA"), align="C", ln=1)
            pdf.set_font("Arial","B",11)
            pdf.cell(0, 6, clean_latin(f"{club.upper()} - {categoria.upper()}"), align="C", ln=1)
            pdf.set_font("Arial","I",8)
            pdf.cell(0, 5, clean_latin(f"Año {datetime.now().year}  -  Categoria 7ma  |  Entrenamientos"), align="C", ln=1)
            pdf.ln(6)

            # ── FRASE MOTIVADORA ──────────────────────────────────
            pdf.set_fill_color(255,243,224); pdf.set_draw_color(255,152,0); pdf.set_line_width(0.5)
            pdf.rect(10, pdf.get_y(), 190, 10, "FD")
            pdf.set_font("Arial","BI",10); pdf.set_text_color(230,81,0)
            pdf.set_y(pdf.get_y()+2)
            pdf.cell(0, 6, clean_latin("El exito se construye entrenamiento a entrenamiento. Cada presencia cuenta!"), align="C", ln=1)
            pdf.ln(5)

            # ── CALCULAR RANKING ─────────────────────────────────
            lista = []
            for dni, d in stats.items():
                if not isinstance(d, dict): continue
                tot = sum(d[m] for m in range(1,13))
                lista.append((d.get("nombre",""), tot, d))
            lista.sort(key=lambda x: x[1], reverse=True)

            # ── PODIO TOP 3 ───────────────────────────────────────
            # Colores pastel verde/azul para el podio
            podio_bg     = [(197,225,165),(187,222,251),(255,224,178)]
            podio_borde  = [(76,175,80),(33,150,243),(255,152,0)]
            podio_labels = ["1er PUESTO","2do PUESTO","3er PUESTO"]
            podio_medallas = ["(1)", "(2)", "(3)"]
            if len(lista) >= 3:
                pdf.set_font("Arial","B",10); pdf.set_text_color(33,150,243)
                pdf.cell(0, 7, clean_latin("~ PODIO DE ASISTENCIA ~"), align="C", ln=1)
                pdf.ln(2)
                bw = 55; gap = 7
                x_start = (210 - (bw*3 + gap*2)) / 2
                for i in range(3):
                    x = x_start + i*(bw+gap)
                    y = pdf.get_y()
                    # Fondo pastel
                    pdf.set_fill_color(*podio_bg[i])
                    pdf.set_draw_color(*podio_borde[i])
                    pdf.set_line_width(0.8)
                    pdf.rect(x, y, bw, 26, "FD")
                    # Medalla
                    pdf.set_xy(x, y+1)
                    pdf.set_font("Arial","B",11); pdf.set_text_color(*podio_borde[i])
                    pdf.cell(bw, 6, clean_latin(podio_medallas[i]), align="C", ln=1)
                    # Puesto
                    pdf.set_xy(x, y+7)
                    pdf.set_font("Arial","B",7); pdf.set_text_color(60,60,60)
                    pdf.cell(bw, 4, clean_latin(podio_labels[i]), align="C", ln=1)
                    # Nombre
                    pdf.set_xy(x, y+12)
                    pdf.set_font("Arial","B",8); pdf.set_text_color(30,30,30)
                    nom = lista[i][0].split(" ")[0] if lista[i][0] else "-"
                    pdf.cell(bw, 5, clean_latin(nom[:14]), align="C", ln=1)
                    # Total
                    pdf.set_xy(x, y+18)
                    pdf.set_font("Arial","B",14); pdf.set_text_color(*podio_borde[i])
                    pdf.cell(bw, 6, str(lista[i][1]), align="C", ln=1)
            pdf.ln(14)

            # ── TABLA COMPLETA ───────────────────────────────────
            pdf.set_fill_color(156,39,176); pdf.set_text_color(255,255,255)
            pdf.set_font("Arial","B",8)
            pdf.cell(8,  7, "#",        1, 0, "C", True)
            pdf.cell(58, 7, "JUGADORA", 1, 0, "L", True)
            for m in meses_con_datos:
                pdf.cell(12, 7, MESES_CORTOS[m-1], 1, 0, "C", True)
            pdf.cell(15, 7, "TOTAL", 1, 1, "C", True)

            for pos, (nombre, tot, d) in enumerate(lista):
                bg = pos % 2 == 0
                if pos == 0:   pdf.set_fill_color(255,249,196)
                elif pos == 1: pdf.set_fill_color(245,245,245)
                elif pos == 2: pdf.set_fill_color(255,243,224)
                elif bg:       pdf.set_fill_color(243,229,245)
                else:          pdf.set_fill_color(255,255,255)
                pdf.set_text_color(40,40,40)
                pdf.set_font("Arial","B" if pos < 3 else "",8)
                medal = ["* ","** ","*** "]
                prefix = medal[pos] if pos < 3 else ""
                pdf.cell(8,  6, str(pos+1),                          1, 0, "C", True)
                pdf.cell(58, 6, clean_latin((prefix+nombre)[:22]),   1, 0, "L", True)
                for m in meses_con_datos:
                    val = d[m]
                    pdf.set_text_color(0,150,0) if val >= 4 else pdf.set_text_color(40,40,40)
                    pdf.cell(12, 6, str(val), 1, 0, "C", True)
                pdf.set_font("Arial","B",9)
                pdf.set_text_color(156,39,176)
                pdf.cell(15, 6, str(tot), 1, 1, "C", True)

            # ── PIE ──────────────────────────────────────────────
            pdf.ln(6)
            pdf.set_fill_color(240,240,255); pdf.set_draw_color(180,180,255)
            pdf.rect(10, pdf.get_y(), 190, 10, "FD")
            pdf.set_font("Arial","I",8); pdf.set_text_color(100,100,150)
            pdf.set_y(pdf.get_y()+3)
            pdf.cell(0, 5, clean_latin(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  Verde = 4 o mas entrenamientos ese mes"), align="C", ln=1)

            return True, "Listo", self._guardar(pdf, "ranking_asistencia")
        except Exception as e:
            log.error(f"PDF estadisticas error: {e}")
            return False, str(e), None
# ==============================================================
# APLICACIÓN PRINCIPAL
# ==============================================================
def main(page: ft.Page):
    # --- Assets ---
    ASSETS_DIR = "assets"
    os.makedirs(ASSETS_DIR, exist_ok=True)
    page.assets_dir = ASSETS_DIR

    page.title       = "HockeyApp"
    page.theme_mode  = ft.ThemeMode.LIGHT
    page.padding     = 0
    page.bgcolor     = C_FONDO
    page.theme = ft.Theme(color_scheme_seed="#1565C0")

    try:
        page.locale_configuration = ft.LocaleConfiguration(
            supported_locales=[ft.Locale("es", "AR")],
            current_locale=ft.Locale("es", "AR"),
        )
    except Exception:
        pass

    # --- Estado global ---
    categoria_actual = ["SÉPTIMA"]
    club_actual      = ["VARELA"]

    # --- Conexión Sheets ---
    try:
        db = SheetsService()
    except Exception as e:
        page.add(ft.Text(f"❌ No se pudo conectar a Google Sheets: {e}", color="red"))
        page.update()
        return

    # --- Cargar config desde Sheets ---
    def cargar_config():
        try:
            if db.tiene_hoja("config"):
                raw = db.get_all("config")
                for row in raw:
                    if len(row) >= 2 and row[0] == "categoria":
                        categoria_actual[0] = row[1]
                    if len(row) >= 2 and row[0] == "club":
                        club_actual[0] = row[1]
        except Exception as ex:
            log.warning(f"No se pudo cargar config: {ex}")

    def guardar_config():
        try:
            if not db.tiene_hoja("config"):
                ws = db._sh.add_worksheet(title="config", rows=10, cols=2)
                db._worksheets["config"] = ws
            filas = [["categoria", categoria_actual[0]], ["club", club_actual[0]]]
            db.clear_and_write("config", filas)
            log.info("Config guardada en Sheets")
        except Exception as ex:
            log.warning(f"No se pudo guardar config: {ex}")

    cargar_config()

    # --- PDF Generator ---
    pdf_gen = PDFGenerator(
        ASSETS_DIR,
        lambda: categoria_actual[0],
        lambda: club_actual[0],
    )

    # --- Telegram config ---
    TELEGRAM_TOKEN   = "8629326578:AAHr74A1cCGv45z1qOxR8vv5qK42U7S4T6A"
    TELEGRAM_CHAT_ID = "5309873646"

    # --- Banner PDF ---
    banner_pdf = ft.Container(visible=False)

    def enviar_pdf_telegram(ruta_local: str, nombre: str) -> str:
        """Envía el PDF por Telegram y retorna el link directo al archivo."""
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
            with open(ruta_local, "rb") as f:
                resp = requests.post(url, data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": f"📄 {nombre} — HockeyApp VARELA",
                }, files={"document": (nombre, f, "application/pdf")})
            if resp.status_code == 200:
                data     = resp.json()
                file_id  = data["result"]["document"]["file_id"]
                # Obtener link de descarga directa
                r2       = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}")
                file_path = r2.json()["result"]["file_path"]
                link = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                log.info(f"PDF enviado por Telegram: {nombre}")
                return link
            else:
                log.error(f"Telegram error: {resp.text}")
                return ""
        except Exception as ex:
            log.error(f"Error enviando a Telegram: {ex}")
            return ""

    def mostrar_pdf_inline(url_pdf: str):
        ruta_local = os.path.join("assets", url_pdf.lstrip("/"))
        nombre     = os.path.basename(ruta_local)
        txt_estado.value = "📤 Enviando PDF a Telegram..."
        page.update()
        link = enviar_pdf_telegram(ruta_local, nombre)
        if link:
            banner_pdf.content = ft.Column([
                ft.Row([
                    ft.Text("✅ PDF listo", weight="bold", color=C_VERDE, expand=True),
                    ft.TextButton("✖", on_click=lambda e: cerrar_banner()),
                ]),
                ft.ElevatedButton(
                    "🔗 Ver PDF online",
                    url=f"https://docs.google.com/viewer?url={requests.utils.quote(link, safe='')}",
                    url_target="_blank",
                    bgcolor=C_AZUL, color="white", height=45,
                ),
            ], spacing=8)
            banner_pdf.visible       = True
            banner_pdf.bgcolor       = "#E8F5E9"
            banner_pdf.padding       = 10
            banner_pdf.border_radius = 8
            txt_estado.value = "✅ PDF listo — también en Telegram."
        else:
            banner_pdf.content = ft.Text("❌ No se pudo enviar el PDF.", color=C_ROJO)
            banner_pdf.visible = True
            txt_estado.value   = "❌ Error enviando a Telegram."
        page.update()
    def cerrar_banner():
        banner_pdf.visible = False
        page.update()

    # --- Carga inicial de jugadoras ---
    def cargar_jugadoras() -> list:
        raw = db.get_all("jugadoras")
        result = []
        if len(raw) > 1:
            for row in raw[1:]:
                row += [""] * (9 - len(row))
                jug = {
                    "id": row[0], "nombre": row[1], "apellido": row[2],
                    "dni": row[3], "nacimiento": row[4], "posicion": row[5],
                    "telefono": row[6], "activo": row[7], "camiseta": row[8],
                }
                if jug["dni"]:
                    result.append(jug)
        return result

    lista_jugadoras_raw = cargar_jugadoras()

    # --- UI base ---
    txt_estado         = ft.Text("🟢 Sistema Listo", size=12, color="grey")
    columna_contenido  = ft.Column(expand=True, scroll="auto")
    contenedor_principal = ft.Container(content=columna_contenido, padding=15, expand=True)

    # ==========================================================
    # NAVEGACIÓN
    # ==========================================================
    RUTAS = {
        "asis":             lambda: vista_asistencia(),
        "stats":            lambda: vista_estadisticas_asistencia(),
        "eval":             lambda: vista_evaluacion(),
        "part":             lambda: vista_partidos(),
        "resumen_partidos": lambda: vista_resumen_partidos(),
        "plantel":          lambda: vista_plantel(),
        "ficha":            lambda: vista_reporte_completo(),
        "fixture_full":     lambda: vista_gestion_fixture(),
        "formacion":        lambda: vista_formacion(),
    }

    _nav_bar_ref    = [None]   # se llena después de crear nav_bar
    _header_ref     = [None]   # se llena después de crear header
    _NAV_DESTINOS_R = ["asis", "eval", "part", "formacion", "plantel", "ficha"]

    def navegar(destino):
        if not isinstance(destino, str):
            destino = getattr(getattr(destino, "control", None), "data", "asis")
        if destino not in RUTAS:
            log.warning(f"Ruta desconocida: {destino}")
            return
        columna_contenido.controls.clear()
        try:
            columna_contenido.controls.append(RUTAS[destino]())
        except Exception as e:
            log.error(f"Error renderizando {destino}: {e}")
            columna_contenido.controls.append(ft.Text(f"❌ Error cargando vista: {e}", color="red"))
        # Sync nav bar
        if _nav_bar_ref[0] and callable(_nav_bar_ref[0]):
            _nav_bar_ref[0](destino)
        # Sync header club/cat
        try:
            if _header_ref[0]:
                _header_ref[0].value = f"{club_actual[0]}  ·  {categoria_actual[0]}"
        except Exception:
            pass
        page.update()

    # ==========================================================
    # VISTAS
    # ==========================================================

    # ----------------------------------------------------------
    def vista_asistencia():
        fecha_obj = datetime.now()
        txt_fecha_display = ft.Text(f"📅 {fecha_obj.strftime('%d/%m/%Y')}", size=16, weight="bold")

        # Config editable
        txt_cat_label  = ft.Text(f"Categoría: {categoria_actual[0]}", size=14, weight="bold", color=C_AZUL)
        txt_club_label = ft.Text(f"Club: {club_actual[0]}", size=14, weight="bold", color="#E91E63")
        txt_cat_input  = ft.TextField(value=categoria_actual[0], label="Categoría", expand=True)
        txt_club_input = ft.TextField(value=club_actual[0], label="Nombre Club", expand=True)
        row_display    = ft.Row([txt_cat_label, ft.VerticalDivider(), txt_club_label], alignment="center")
        row_edit       = ft.Row([txt_cat_input, txt_club_input], visible=False)

        def toggle_config(e):
            if row_display.visible:
                row_display.visible = False
                row_edit.visible    = True
            else:
                categoria_actual[0] = txt_cat_input.value
                club_actual[0]      = txt_club_input.value
                guardar_config()
                txt_cat_label.value  = f"Categoría: {categoria_actual[0]}"
                txt_club_label.value = f"Club: {club_actual[0]}"
                row_display.visible = True
                row_edit.visible    = False
            page.update()

        btn_edit = ft.IconButton(ft.icons.EDIT, on_click=toggle_config)
        btn_save = ft.IconButton(ft.icons.CHECK, on_click=toggle_config)

        dd_tipo  = ft.Dropdown(
            options=[ft.dropdown.Option(x) for x in ["Entrenamiento","Partido","Suspendido"]],
            value="Entrenamiento", bgcolor=C_BLANCO, expand=True,
        )
        txt_obs = ft.TextField(label="Observaciones del día", bgcolor=C_BLANCO, expand=True)
        col_lista = ft.Column(spacing=0)
        controles_filas: dict = {}

        info_completado = ft.Column(visible=False, controls=[
            ft.Container(
                content=ft.Column([
                    ft.Text("✅ ASISTENCIA COMPLETADA", size=20, weight="bold", color="green"),
                    ft.Divider(),
                    ft.Row([
                        ft.ElevatedButton("✏️ EDITAR",     bgcolor=C_AZUL, color="white", expand=True, on_click=lambda e: mostrar_modo_edicion()),
                        ft.ElevatedButton("🗑️ ELIMINAR DÍA", bgcolor=C_ROJO, color="white", expand=True, on_click=lambda e: eliminar_datos_dia()),
                    ])
                ], alignment=ft.alignment.Alignment(0, 0), horizontal_alignment="center"),
                bgcolor="#E8F5E9", padding=20, border_radius=10, border=ft.border.all(1, "green"),
            )
        ])

        def mostrar_modo_edicion():
            info_completado.visible = False
            col_lista.visible       = True
            btn_guardar.visible     = True
            page.update()

        def actualizar_visual_fila(dni, estado):
            if dni not in controles_filas:
                return
            c = controles_filas[dni]
            if estado == "SI":
                c["txt"].color = C_GRIS_TXT; c["txt"].decoration = "line-through"
                c["btn_p"].bgcolor = C_VERDE;   c["btn_p"].color = "white"
                c["btn_a"].bgcolor = "#EEEEEE"; c["btn_a"].color = "black"
            elif estado == "NO":
                c["txt"].color = C_GRIS_TXT; c["txt"].decoration = "none"
                c["btn_a"].bgcolor = C_ROJO;    c["btn_a"].color = "white"
                c["btn_p"].bgcolor = "#EEEEEE"; c["btn_p"].color = "black"
            else:
                c["txt"].color = C_TEXTO; c["txt"].decoration = "none"
                c["btn_p"].bgcolor = "#EEEEEE"; c["btn_p"].color = "green"
                c["btn_a"].bgcolor = "#EEEEEE"; c["btn_a"].color = "red"
            c["estado"] = estado
            page.update()

        def cargar_datos_fecha(e=None):
            f_str = txt_fecha_display.value.replace("📅 ", "")
            txt_estado.value = f"⏳ Verificando {f_str}..."
            for dni in controles_filas:
                actualizar_visual_fila(dni, None)
            txt_obs.value = ""
            info_completado.visible = False
            col_lista.visible = True
            btn_guardar.visible = True
            page.update()
            try:
                db.invalidar_cache("asistencia")
                raw = db.get_all("asistencia")
                encontrados = 0
                for row in raw[1:]:
                    if row[0] == f_str:
                        encontrados += 1
                        actualizar_visual_fila(str(row[1]), row[2])
                        if len(row) > 3 and row[3]: dd_tipo.value   = row[3]
                        if len(row) > 4 and row[4]: txt_obs.value   = row[4]
                if encontrados > 0:
                    col_lista.visible       = False
                    btn_guardar.visible     = False
                    info_completado.visible = True
                    txt_estado.value        = "✅ Ya registrado"
                else:
                    txt_estado.value = "🆕 Nuevo"
                page.update()
            except Exception as ex:
                log.error(f"cargar_datos_fecha: {ex}")
                txt_estado.value = f"❌ Error: {ex}"; page.update()

        def eliminar_datos_dia():
            f_str = txt_fecha_display.value.replace("📅 ", "")
            try:
                raw      = db.get_all("asistencia")
                filas_ok = [row for row in raw if row[0] != f_str]
                if not filas_ok:
                    filas_ok = [["Fecha","DNI","Presente","Tipo","Observaciones"]]
                db.clear_and_write("asistencia", filas_ok)
                txt_estado.value = "🗑️ Eliminado"
                cargar_datos_fecha()
            except Exception as ex:
                log.error(f"eliminar_datos_dia: {ex}")
                txt_estado.value = f"❌ Error: {ex}"; page.update()

        # ── Calendario custom en español ────────────────────────
        _fecha_cal  = [fecha_obj]
        lbl_mes_cal = ft.Text("", size=15, weight="bold", text_align="center", expand=True)
        cal_grid    = ft.Column(spacing=2)

        def _build_grid():
            mes  = _fecha_cal[0].month
            anio = _fecha_cal[0].year
            sel  = _fecha_cal[0].day
            lbl_mes_cal.value = f"{LISTA_MESES[mes - 1]}  {anio}"
            if lbl_mes_cal.page: lbl_mes_cal.update()
            cal_grid.controls.clear()
            cal_grid.controls.append(ft.Row([
                ft.Container(
                    content=ft.Text(d, size=11, weight="bold", color=C_GRIS_TXT,
                                    text_align="center"),
                    width=38, height=28, alignment=ft.alignment.Alignment(0, 0))
                for d in ["L", "M", "M", "J", "V", "S", "D"]
            ], spacing=2))
            primer = calendar.weekday(anio, mes, 1)
            total  = calendar.monthrange(anio, mes)[1]
            hoy_d  = datetime.now().date()
            celdas = [None] * primer + list(range(1, total + 1))
            while len(celdas) % 7:
                celdas.append(None)
            for s in range(len(celdas) // 7):
                fila = []
                for col in range(7):
                    d = celdas[s * 7 + col]
                    if d is None:
                        fila.append(ft.Container(width=38, height=38))
                    else:
                        es_sel = (d == sel)
                        es_hoy = (datetime(anio, mes, d).date() == hoy_d)
                        fila.append(ft.Container(
                            content=ft.Text(str(d), size=13, text_align="center",
                                            color="white" if es_sel
                                            else (C_AZUL if es_hoy else C_TEXTO)),
                            width=38, height=38,
                            bgcolor=C_AZUL if es_sel else None,
                            border_radius=19,
                            border=ft.border.all(1.5, C_AZUL) if (es_hoy and not es_sel) else None,
                            alignment=ft.alignment.Alignment(0, 0),
                            on_click=lambda e, dd=d: _sel_dia(dd),
                        ))
                cal_grid.controls.append(ft.Row(fila, spacing=2))
            if cal_grid.page: cal_grid.update()

        def _sel_dia(d):
            dt = _fecha_cal[0]
            _fecha_cal[0] = datetime(dt.year, dt.month, d)
            _build_grid()

        def _nav_mes(delta):
            dt = _fecha_cal[0]
            m, a = dt.month + delta, dt.year
            if m > 12: m, a = 1,  a + 1
            if m < 1:  m, a = 12, a - 1
            _fecha_cal[0] = datetime(a, m, 1)
            _build_grid()

        def _cerrar_cal():
            dlg_cal.open = False; page.update()

        def _confirmar_cal():
            dt = _fecha_cal[0]
            txt_fecha_display.value = f"📅 {dt.strftime('%d/%m/%Y')}"
            txt_fecha_display.update()
            dlg_cal.open = False
            page.update()
            cargar_datos_fecha()

        dlg_cal = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.IconButton(icon=ft.icons.CHEVRON_LEFT,  on_click=lambda e: _nav_mes(-1)),
                lbl_mes_cal,
                ft.IconButton(icon=ft.icons.CHEVRON_RIGHT, on_click=lambda e: _nav_mes(1)),
            ], alignment="center"),
            content=ft.Container(content=cal_grid, width=300),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: _cerrar_cal()),
                ft.ElevatedButton("Aceptar", bgcolor=C_AZUL, color="white",
                                  on_click=lambda e: _confirmar_cal()),
            ],
            actions_alignment="end",
        )
        try:
            page.overlay.append(dlg_cal)
        except Exception:
            pass

        def abrir_calendario(e):
            try:
                dt_str = txt_fecha_display.value.replace("📅 ", "")
                _fecha_cal[0] = datetime.strptime(dt_str, "%d/%m/%Y")
            except Exception:
                _fecha_cal[0] = datetime.now()
            _build_grid()
            dlg_cal.open = True
            page.update()

        # Construir lista de jugadoras
        col_lista.controls.append(ft.Container(
            content=ft.Row([
                ft.Text("JUGADORA", weight="bold", color="white", expand=True),
                ft.Text("ASISTENCIA", weight="bold", color="white", width=100),
            ]),
            bgcolor="#607D8B", padding=10, border_radius=5,
        ))
        for i, jug in enumerate(lista_jugadoras_raw):
            dni   = str(jug["dni"])
            num   = jug["camiseta"] or "-"
            edad  = calcular_edad(jug["nacimiento"])
            txt_n = ft.Text(
                f"#{num} - {jug['apellido'].upper()} {jug['nombre']} ({edad})",
                weight="bold", size=14, color=C_TEXTO, expand=True,
            )
            btn_p = ft.ElevatedButton("✅", width=50, on_click=lambda e, d=dni: actualizar_visual_fila(d, "SI"))
            btn_a = ft.ElevatedButton("❌", width=50, on_click=lambda e, d=dni: actualizar_visual_fila(d, "NO"))
            controles_filas[dni] = {"txt": txt_n, "btn_p": btn_p, "btn_a": btn_a, "estado": None}
            col_lista.controls.append(ft.Container(
                content=ft.Row([txt_n, btn_p, btn_a], alignment="spaceBetween"),
                padding=10,
                bgcolor=C_BLANCO if i % 2 == 0 else C_GRIS_CLARO,
                border=ft.border.only(bottom=ft.border.BorderSide(1, "#DDD")),
            ))

        def guardar(e):
            f_str = txt_fecha_display.value.replace("📅 ", "")
            susp  = "Suspendido" in (dd_tipo.value or "")
            txt_estado.value = "⏳ Guardando..."; page.update()
            try:
                raw      = db.get_all("asistencia")
                filas_ok = [row for row in raw if row[0] != f_str]
                if not filas_ok or filas_ok[0][0] != "Fecha":
                    filas_ok.insert(0, ["Fecha","DNI","Presente","Tipo","Observaciones"])
                nuevas = []
                for dni, ctrl in controles_filas.items():
                    est = ctrl["estado"]
                    if not est and not susp:
                        continue
                    val = "-" if susp else est
                    nuevas.append([f_str, dni, val, dd_tipo.value, txt_obs.value])
                db.clear_and_write("asistencia", filas_ok + nuevas)
                txt_estado.value = "✅ Guardado"
                col_lista.visible       = False
                btn_guardar.visible     = False
                info_completado.visible = True
                page.update()
            except Exception as ex:
                log.error(f"guardar asistencia: {ex}")
                txt_estado.value = f"❌ Error: {ex}"; page.update()

        btn_guardar = ft.ElevatedButton("💾 GUARDAR ASISTENCIA", on_click=guardar, bgcolor=C_AZUL, color="white", height=50)
        btn_ojo_mensual = ft.IconButton(icon=ft.icons.VISIBILITY, disabled=True, icon_color=C_GRIS_TXT, tooltip="Abrir PDF")

        def pdf_click(e):
            try:
                txt_estado.value = "Creando PDF..."; page.update()
                dt = datetime.strptime(txt_fecha_display.value.replace("📅 ", ""), "%d/%m/%Y")
                ok, res, url = pdf_gen.mensual(dt.month, dt.year, db)
                if ok:
                    txt_estado.value = "✅ PDF listo."
                    mostrar_pdf_inline(url)
                else:
                    txt_estado.value = f"❌ Error: {res}"
                page.update()
            except Exception as ex:
                log.error(f"pdf_click asistencia: {ex}")
                txt_estado.value = f"❌ Error: {ex}"; page.update()

        # No llamamos cargar_datos_fecha() aquí porque los controles
        # aún no están en la página. Se carga al cambiar fecha.
        txt_estado.value = "🆕 Nuevo"

        return ft.Column([
            ft.Text("Tomar Asistencia", size=22, weight="bold", color=C_AZUL),
            ft.Container(content=ft.Column([
                ft.Row([row_display, btn_edit]),
                ft.Row([row_edit, btn_save]),
            ]), padding=10),
            ft.Row([ft.ElevatedButton("📅 CAMBIAR DÍA", on_click=abrir_calendario, bgcolor=C_AZUL, color="white"), txt_fecha_display]),
            ft.Row([dd_tipo, txt_obs]),
            ft.Divider(),
            ft.Row([
                ft.ElevatedButton("📊 ESTADÍSTICAS", on_click=lambda e: navegar("stats"), bgcolor="#607D8B", color="white", expand=True),
                ft.ElevatedButton("📄 GENERAR MES",  on_click=pdf_click, bgcolor=C_VIOLETA, color="white"),
                btn_ojo_mensual,
            ]),
            ft.Divider(),
            info_completado, col_lista, ft.Divider(), btn_guardar,
        ], scroll="auto")

    # ----------------------------------------------------------
    def vista_estadisticas_asistencia():
        txt_estado.value = "⏳ Calculando..."; page.update()
        col_stats = ft.Column(spacing=0, scroll="auto")
        try:
            raw = db.get_all("asistencia")
            anio_act = datetime.now().year
            MESES_CORTOS = ["ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SEP","OCT","NOV","DIC"]
            stats: dict = {}
            for j in lista_jugadoras_raw:
                dni = str(j["dni"])
                stats[dni] = {m: 0 for m in range(1, 13)}
                stats[dni]["nombre"] = f"{j['apellido']} {j['nombre']}"
            for row in raw:
                if row and row[0] == "Fecha":
                    continue
                try:
                    f = datetime.strptime(row[0], "%d/%m/%Y")
                    dni = str(row[1])
                    if f.year == anio_act and dni in stats and row[2] == "SI":
                        if len(row) > 3 and "Entrenamiento" in row[3]:
                            stats[dni][f.month] += 1
                except Exception:
                    pass

            # Solo mostrar meses que tienen al menos un dato
            meses_con_datos = [m for m in range(1, 13) if any(d[m] > 0 for d in stats.values() if isinstance(d, dict) and m in d)]

            # Encabezado
            col_stats.controls.append(ft.Container(
                content=ft.Row([
                    ft.Text("JUGADORA", width=140, weight="bold", size=12),
                ] + [ft.Text(MESES_CORTOS[m-1], width=35, size=10, weight="bold", color=C_AZUL) for m in meses_con_datos] + [
                    ft.Text("TOT", width=40, weight="bold", color=C_VERDE),
                ], scroll="always"),
                bgcolor=C_GRIS, padding=8,
            ))

            # Ordenar por total descendente
            lista_stats = [(dni, d) for dni, d in stats.items()]
            lista_stats.sort(key=lambda x: sum(x[1][m] for m in range(1,13)), reverse=True)

            for pos, (dni, d) in enumerate(lista_stats):
                tot = sum(d[m] for m in range(1, 13))
                # Medalla para el podio
                if pos == 0:   medalla = "🥇 "
                elif pos == 1: medalla = "🥈 "
                elif pos == 2: medalla = "🥉 "
                else:          medalla = ""
                bg = "#FFF9C4" if pos == 0 else "#F5F5F5" if pos % 2 == 0 else C_BLANCO
                col_stats.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Text(f"{medalla}{d['nombre']}", width=140, size=12, no_wrap=True, weight="bold" if pos < 3 else "normal"),
                    ] + [ft.Text(str(d[m]), width=35, size=12, color=C_VERDE if d[m] >= 4 else C_TEXTO) for m in meses_con_datos] + [
                        ft.Text(str(tot), width=40, weight="bold", color=C_AZUL),
                    ], scroll="always"),
                    padding=6,
                    bgcolor=bg,
                    border=ft.border.only(bottom=ft.border.BorderSide(1, "#EEE")),
                ))
            txt_estado.value = "✅ Listado"
        except Exception as e:
            log.error(f"vista_estadisticas: {e}")
            col_stats.controls.append(ft.Text(f"❌ Error: {e}", color="red"))

        stats_final = stats if 'stats' in locals() else {}
        meses_final = meses_con_datos if 'meses_con_datos' in locals() else []
        btn_ojo = ft.IconButton(icon=ft.icons.VISIBILITY, disabled=True, icon_color=C_GRIS_TXT, tooltip="Abrir PDF")

        def on_pdf(e):
            txt_estado.value = "Generando PDF..."; page.update()
            ok, res, url = pdf_gen.estadisticas_asistencia(stats_final, meses_final)
            if ok:
                txt_estado.value = "✅ PDF listo."
                btn_ojo.disabled = False
                btn_ojo.icon_color = C_VERDE
                btn_ojo.update()
                mostrar_pdf_inline(url)
            else:
                txt_estado.value = f"❌ Error PDF: {res}"; page.update(); return
            page.update()

        return ft.Column([
            ft.Text("🏑 Ranking de Asistencia", size=20, weight="bold", color=C_AZUL),
            ft.Row([
                ft.ElevatedButton("← Volver", on_click=lambda e: navegar("asis"), bgcolor="grey", color="white"),
                ft.ElevatedButton("📄 GENERAR PDF", on_click=on_pdf, bgcolor=C_VIOLETA, color="white"),
                btn_ojo,
            ]),
            ft.Divider(),
            ft.Container(content=col_stats, border=ft.border.all(1, C_GRIS), border_radius=8),
        ], scroll="auto")

    # ----------------------------------------------------------
    def vista_evaluacion():
        area_contenido      = ft.Column()
        txt_progreso        = ft.Text("", size=16, weight="bold", color=C_AZUL)
        estado_edicion      = {"dni": None, "fila": None}
        sliders_refs        = []
        botones_meses_refs  = []

        def color_nota(v):
            if v < 5:  return C_ROJO
            if v < 8:  return C_AMARILLO
            return C_VERDE

        def mostrar_formulario(dni_jug, nombre_jug, mes_num):
            area_contenido.controls.clear()
            raw  = db.get_all("habilidades")
            vals = [1] * len(TITULOS_SKILLS)
            fila_enc = None
            for idx, row in enumerate(raw):
                if row and row[0] == "Fecha":
                    continue
                try:
                    f = datetime.strptime(row[0], "%d/%m/%Y")
                    if str(row[1]) == str(dni_jug) and f.month == mes_num and f.year == datetime.now().year:
                        fila_enc = idx + 1
                        vals = [safe_int(row[i+2]) if len(row) > i+2 else 1 for i in range(len(TITULOS_SKILLS))]
                except Exception:
                    pass

            estado_edicion["dni"]  = dni_jug
            estado_edicion["fila"] = fila_enc
            sliders_refs.clear()
            col_sliders = ft.Column()

            for i, tit in enumerate(TITULOS_SKILLS):
                v0  = int(vals[i])
                lbl = ft.Text(str(v0), weight="bold", size=16)
                bar = ft.Container(width=v0*30, height=15, bgcolor=color_nota(v0), border_radius=5, animate=300)
                bg  = ft.Container(content=bar, width=300, height=15, bgcolor=C_GRIS, border_radius=5, alignment=ft.alignment.Alignment(-1, 0))

                def hacer_mover(lbl_r, bar_r):
                    def mover(e):
                        v = int(e.control.value)
                        lbl_r.value  = str(v)
                        bar_r.width  = v * 30
                        bar_r.bgcolor = color_nota(v)
                        lbl_r.update(); bar_r.update()
                    return mover

                s = ft.Slider(min=1, max=10, divisions=9, value=v0, on_change=hacer_mover(lbl, bar))
                sliders_refs.append(s)
                col_sliders.controls.append(ft.Column([
                    ft.Row([ft.Text(tit, weight="bold"), lbl], alignment="spaceBetween"),
                    bg, s,
                ], spacing=5))

            def guardar_eval(e):
                notas  = [int(s.value) for s in sliders_refs]
                anio   = datetime.now().year
                fecha_g = datetime(anio, mes_num, 1).strftime("%d/%m/%Y")
                try:
                    if estado_edicion["fila"]:
                        fin = chr(ord("C") + len(TITULOS_SKILLS) - 1)
                        db.update_range("habilidades", f"C{estado_edicion['fila']}:{fin}{estado_edicion['fila']}", [notas])
                    else:
                        db.append("habilidades", [fecha_g, dni_jug] + notas + ["Obs"])
                    txt_estado.value = "✅ Guardado"
                    mostrar_lista(mes_num)
                except Exception as ex:
                    log.error(f"guardar_eval: {ex}")
                    txt_estado.value = f"❌ Error: {ex}"; page.update()

            area_contenido.controls.append(ft.Column([
                ft.Text(f"Evaluando: {nombre_jug}", size=20, weight="bold", color=C_VIOLETA),
                ft.Divider(), col_sliders, ft.Divider(),
                ft.Row([
                    ft.ElevatedButton("Cancelar", on_click=lambda e: mostrar_lista(mes_num), bgcolor="grey", color="white"),
                    ft.ElevatedButton("GUARDAR",  on_click=guardar_eval, bgcolor=C_VERDE, color="white", expand=True),
                ]),
            ]))
            page.update()

        def mostrar_lista(mes_num):
            area_contenido.controls.clear()
            txt_estado.value = "⏳ Calculando..."; page.update()

            for i, btn in enumerate(botones_meses_refs):
                btn.bgcolor = C_VERDE if (i + 1) == mes_num else C_BLANCO
                btn.color   = "white"  if (i + 1) == mes_num else "black"
            page.update()

            raw  = db.get_all("habilidades")
            anio = datetime.now().year
            dnis = [str(j["dni"]) for j in lista_jugadoras_raw]
            notas_validas: dict = {}
            acum = [0] * len(TITULOS_SKILLS); cant_eval = 0

            for row in raw:
                if row and row[0] == "Fecha":
                    continue
                try:
                    f = datetime.strptime(row[0], "%d/%m/%Y")
                    if f.year == anio and f.month == mes_num and str(row[1]) in dnis:
                        notas = [safe_int(row[i+2]) if len(row) > i+2 else 1 for i in range(len(TITULOS_SKILLS))]
                        notas_validas[str(row[1])] = notas
                        for i, n in enumerate(notas):
                            acum[i] += n
                        cant_eval += 1
                except Exception:
                    pass

            txt_progreso.value = f"Estado {LISTA_MESES[mes_num-1]}: {len(notas_validas)}/{len(lista_jugadoras_raw)} evaluadas"
            items = []
            for j in lista_jugadoras_raw:
                dni    = str(j["dni"])
                ya_fue = dni in notas_validas
                items.append(ft.Container(
                    content=ft.Row([
                        ft.Text("✅" if ya_fue else "⚠️", size=20),
                        ft.Column([
                            ft.Text(f"{j['nombre']} {j['apellido']}", weight="bold"),
                            ft.Text("Completado" if ya_fue else "Pendiente", size=12, color="grey"),
                        ], expand=True),
                        ft.ElevatedButton(
                            "EDITAR" if ya_fue else "CARGAR",
                            color="blue", bgcolor=C_BLANCO,
                            on_click=lambda e, d=dni, n=f"{j['nombre']} {j['apellido']}": mostrar_formulario(d, n, mes_num),
                        ),
                    ]),
                    padding=10,
                    bgcolor="#E8F5E9" if ya_fue else "#FFF3E0",
                    border_radius=8,
                ))
            area_contenido.controls.append(ft.Column(items, spacing=5))

            if cant_eval > 0:
                area_contenido.controls.append(ft.Divider())
                area_contenido.controls.append(ft.Text(f"📊 Rendimiento Equipo — {LISTA_MESES[mes_num-1]}", weight="bold", color=C_AZUL))
                for i, prom in enumerate(int(t / cant_eval) for t in acum):
                    c = color_nota(prom)
                    area_contenido.controls.append(ft.Column([
                        ft.Row([ft.Text(TITULOS_SKILLS[i], size=10, width=80), ft.Text(str(prom), weight="bold")], alignment="spaceBetween"),
                        ft.Stack([
                            ft.Container(width=300, height=8, bgcolor=C_GRIS, border_radius=4, alignment=ft.alignment.Alignment(-1, 0)),
                            ft.Container(width=prom*30, height=8, bgcolor=c, border_radius=4),
                        ]),
                    ], spacing=2))

            txt_estado.value = "✅ Lista actualizada"; page.update()

        botones_meses_refs.clear()
        fila_botones = ft.Row(scroll="always")
        for i, nm in enumerate(LISTA_MESES):
            btn = ft.ElevatedButton(nm, on_click=lambda e, m=i+1: mostrar_lista(m))
            botones_meses_refs.append(btn)
            fila_botones.controls.append(btn)

        mostrar_lista(datetime.now().month)
        return ft.Column([
            ft.Text("Evaluación Técnica Mensual", size=20, weight="bold", color=C_VERDE),
            fila_botones, txt_progreso, ft.Divider(), area_contenido,
        ], scroll="auto")

    # ----------------------------------------------------------
    def vista_plantel():
        def form(jug=None):
            columna_contenido.controls.clear()
            v_nom = jug["nombre"]   if jug else ""
            v_ape = jug["apellido"] if jug else ""
            v_dni = str(jug["dni"]) if jug else ""
            v_nac = str(jug.get("nacimiento","") or "") if jug else ""
            v_cam = str(jug.get("camiseta","")   or "") if jug else ""
            v_pos = jug.get("posicion")           if jug else None
            v_tel = str(jug.get("telefono","")   or "") if jug else ""
            dni_orig = v_dni

            t_nom = ft.TextField(label="Nombre",  value=v_nom)
            t_ape = ft.TextField(label="Apellido", value=v_ape)
            t_dni = ft.TextField(label="DNI",      value=v_dni)
            t_nac = ft.TextField(label="Nacimiento (DD/MM/AAAA)", value=v_nac)
            t_cam = ft.TextField(label="N° Camiseta", value=v_cam)
            t_pos = ft.Dropdown(
                label="Posición",
                options=[ft.dropdown.Option(x) for x in ["Arquera","Defensora","Volante","Delantera"]],
                value=v_pos,
            )
            t_tel = ft.TextField(label="Teléfono", value=v_tel)

            def save(e):
                if not t_dni.value:
                    txt_estado.value = "⚠️ Falta DNI"; page.update(); return
                nd = ["", t_nom.value, t_ape.value, t_dni.value, t_nac.value, t_pos.value, t_tel.value, "SI", t_cam.value]
                try:
                    if jug:
                        rows = db.get_all("jugadoras")
                        for i, r in enumerate(rows):
                            if len(r) > 3 and str(r[3]) == str(dni_orig):
                                db.update_range("jugadoras", f"A{i+1}:I{i+1}", [nd])
                                jug.update({"nombre": t_nom.value, "apellido": t_ape.value, "dni": t_dni.value, "nacimiento": t_nac.value, "camiseta": t_cam.value})
                                break
                    else:
                        db.append("jugadoras", nd)
                        lista_jugadoras_raw.append({
                            "id":"", "nombre": t_nom.value, "apellido": t_ape.value,
                            "dni": t_dni.value, "nacimiento": t_nac.value,
                            "posicion": t_pos.value, "telefono": t_tel.value,
                            "activo": "SI", "camiseta": t_cam.value,
                        })
                    txt_estado.value = "✅ Guardado"; navegar("plantel")
                except Exception as ex:
                    log.error(f"save plantel: {ex}")
                    txt_estado.value = str(ex); page.update()

            def delete(e):
                if not jug: return
                try:
                    rows = db.get_all("jugadoras")
                    for i, r in enumerate(rows):
                        if len(r) > 3 and str(r[3]) == str(dni_orig):
                            ws = db._get_ws("jugadoras")
                            db._with_retry(ws.delete_rows, i + 1)
                            db.invalidar_cache("jugadoras")
                            break
                    for k in range(len(lista_jugadoras_raw)):
                        if str(lista_jugadoras_raw[k]["dni"]) == str(dni_orig):
                            del lista_jugadoras_raw[k]; break
                    txt_estado.value = "✅ Jugadora eliminada"; navegar("plantel")
                except Exception as ex:
                    log.error(f"delete plantel: {ex}")
                    txt_estado.value = f"❌ Error: {ex}"; page.update()

            btns = [ft.ElevatedButton("Cancelar", on_click=lambda e: navegar("plantel"), bgcolor="grey", color="white")]
            if jug:
                btns.append(ft.ElevatedButton("ELIMINAR", on_click=delete, bgcolor=C_ROJO, color="white"))
            btns.append(ft.ElevatedButton("GUARDAR", on_click=save, bgcolor=C_VERDE, color="white"))

            columna_contenido.controls.append(ft.Column([
                ft.Text("Editar Jugadora" if jug else "Alta Jugadora", size=20, weight="bold", color=C_AZUL),
                t_nom, t_ape, t_dni, t_nac, t_cam, t_pos, t_tel,
                ft.Row(btns),
            ]))
            page.update()

        items = []
        for j in lista_jugadoras_raw:
            btn = ft.ElevatedButton("✏️", bgcolor=C_BLANCO, color=C_AZUL, width=50, on_click=lambda e, x=j: form(x))
            items.append(ft.Container(
                content=ft.Row([
                    ft.Text("👤", size=20),
                    ft.Column([
                        ft.Text(f"{j['nombre']} {j['apellido']}", weight="bold"),
                        ft.Text(f"Camiseta: {j.get('camiseta','-')}", size=12, color="grey"),
                    ], expand=True),
                    btn,
                ]),
                padding=10,
                border=ft.border.only(bottom=ft.border.BorderSide(1, "#EEE")),
            ))

        return ft.Column([
            ft.Row([
                ft.Text("Mi Plantel", size=20, weight="bold"),
                ft.ElevatedButton("+ ALTA", on_click=lambda e: form(None), bgcolor=C_AZUL, color="white"),
            ], alignment="spaceBetween"),
            ft.Column(items, spacing=5),
        ])

    # ----------------------------------------------------------
    def vista_reporte_completo():
        txt_estado.value = "📊 Generando reporte..."; page.update()

        tabla_datos = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(h)) for h in ["Nombre","Apellido","DNI","Nacimiento","Posición","Teléfono","Activo"]],
            rows=[],
        )
        for j in lista_jugadoras_raw:
            tabla_datos.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(j.get("nombre","-"))),
                ft.DataCell(ft.Text(j.get("apellido","-"))),
                ft.DataCell(ft.Text(str(j.get("dni","-")))),
                ft.DataCell(ft.Text(j.get("nacimiento","-"))),
                ft.DataCell(ft.Text(j.get("posicion","-"))),
                ft.DataCell(ft.Text(str(j.get("telefono","-")))),
                ft.DataCell(ft.Text(j.get("activo","-"))),
            ]))

        btn_pdf_plantel = ft.ElevatedButton("📄 GENERAR PDF PLANTEL", bgcolor=C_VERDE, color="white")
        btn_ojo_plantel = ft.IconButton(icon=ft.icons.VISIBILITY, disabled=True, icon_color=C_GRIS_TXT)

        def on_pdf_plantel(e):
            txt_estado.value = "Generando PDF..."; page.update()
            ok, res, url = pdf_gen.plantel_completo(lista_jugadoras_raw)
            if ok:
                txt_estado.value = "✅ PDF listo."
                mostrar_pdf_inline(url)
            else:
                txt_estado.value = f"❌ Error: {res}"
            page.update()

        btn_pdf_plantel.on_click = on_pdf_plantel

        tabla = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(h)) for h in ["Jugadora","Ent.","Part.","Hab.","Fís.","PDF","Ver"]],
            rows=[],
        )
        try:
            raw_asist = db.get_all("asistencia")
            raw_hab   = db.get_all("habilidades")
            stats: dict = {str(j["dni"]): {"ent":0,"part":0,"hab_s":0,"hab_c":0,"fis_s":0,"fis_c":0} for j in lista_jugadoras_raw}
            for r in raw_asist:
                if r and r[0] == "Fecha": continue
                if len(r) > 3 and str(r[1]) in stats and r[2] == "SI":
                    if "Entrenamiento" in r[3]: stats[str(r[1])]["ent"]  += 1
                    elif "Partido"     in r[3]: stats[str(r[1])]["part"] += 1
            for r in raw_hab:
                if r and r[0] == "Fecha": continue
                dni = str(r[1])
                if dni in stats:
                    vals = [safe_int(r[i+2]) if len(r) > i+2 else 0 for i in range(len(TITULOS_SKILLS))]
                    stats[dni]["hab_s"] += sum(vals[:5]) / 5
                    stats[dni]["hab_c"] += 1
                    stats[dni]["fis_s"] += vals[5]
                    stats[dni]["fis_c"] += 1
            for j in lista_jugadoras_raw:
                d = stats[str(j["dni"])]
                ph = int(d["hab_s"] / d["hab_c"]) if d["hab_c"] > 0 else 0
                pf = int(d["fis_s"] / d["fis_c"]) if d["fis_c"] > 0 else 0
                btn_ojo_ind = ft.IconButton(icon=ft.icons.VISIBILITY, disabled=True, icon_color=C_GRIS_TXT)

                def hacer_pdf_ind(jug_f, btn_v_f):
                    def on_click(e):
                        txt_estado.value = "Generando PDF..."; page.update()
                        ok, res, url = pdf_gen.individual(jug_f, db)
                        if ok:
                            txt_estado.value = "✅ PDF listo."
                            mostrar_pdf_inline(url)
                        else:
                            txt_estado.value = f"❌ Error: {res}"; page.update()
                    return on_click

                btn_gen = ft.IconButton(icon=ft.icons.PICTURE_AS_PDF, icon_color=C_ROJO, on_click=hacer_pdf_ind(j, btn_ojo_ind))
                tabla.rows.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(f"{j['apellido']} {j['nombre']}")),
                    ft.DataCell(ft.Text(str(d["ent"]))),
                    ft.DataCell(ft.Text(str(d["part"]))),
                    ft.DataCell(ft.Text(str(ph))),
                    ft.DataCell(ft.Text(str(pf))),
                    ft.DataCell(btn_gen),
                    ft.DataCell(btn_ojo_ind),
                ]))
            txt_estado.value = "✅ Reporte generado"
        except Exception as ex:
            log.error(f"vista_reporte: {ex}")
            tabla = ft.Text(f"❌ Error: {ex}", color="red")

        def _gen_informe(e):
            txt_estado.value = "Generando informe..."; page.update()
            ok, res, url = pdf_gen.informe_plantel(lista_jugadoras_raw, db)
            if ok:
                txt_estado.value = "✅ Informe listo."
                mostrar_pdf_inline(url)
            else:
                txt_estado.value = f"❌ Error: {res}"
            page.update()

        return ft.Column([
            ft.Text("Datos Personales de Jugadoras", size=20, weight="bold", color=C_AZUL),
            ft.Row([btn_pdf_plantel, btn_ojo_plantel]),
            ft.Container(content=ft.Row([tabla_datos], scroll="always"), border=ft.border.all(1,"#EEE"), border_radius=10, padding=10),
            ft.Divider(),
            ft.Text("Estadísticas Generales y PDF", size=20, weight="bold", color=C_AZUL),
            ft.ElevatedButton(
                "📊 GENERAR INFORME GENERAL DEL PLANTEL",
                on_click=_gen_informe,
                bgcolor="#607D8B", color="white",
            ),
            ft.Container(content=ft.Row([tabla], scroll="always"), border=ft.border.all(1,"#EEE"), border_radius=10, padding=10),
        ], scroll="auto")

    # ----------------------------------------------------------
    def vista_gestion_fixture():
        if not db.tiene_hoja("fixture"):
            return ft.Text("Falta hoja 'fixture' en el spreadsheet.")

        hoy = datetime.now()
        edit_idx   = [-1]
        txt_f      = ft.TextField(label="Fecha (DD/MM/AAAA)", width=150, border_radius=10)
        txt_r      = ft.TextField(label="Rival", expand=True, border_radius=10)
        dd_c       = ft.Dropdown(options=[ft.dropdown.Option("Local"), ft.dropdown.Option("Visitante")], value="Local", width=120)
        txt_maps   = ft.TextField(label="Link Ubicación", expand=True, border_radius=10)
        btn_accion = ft.ElevatedButton("+ AGREGAR", bgcolor=C_VERDE, color="white", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))

        # Secciones del layout
        col_proximo    = ft.Column(spacing=0)
        col_pendientes = ft.Column(spacing=8)
        col_jugados    = ft.Column(spacing=8)
        col_stats      = ft.Column(spacing=8)

        # Colores resultado
        BG_DERROTA  = "#FFEBEE"; BD_DERROTA  = "#EF9A9A"; TX_DERROTA  = "#C62828"
        BG_VICTORIA = "#E8F5E9"; BD_VICTORIA = "#A5D6A7"; TX_VICTORIA = "#2E7D32"
        BG_EMPATE   = "#FFF8E1"; BD_EMPATE   = "#FFE082"; TX_EMPATE   = "#E65100"
        BG_PROXIMO  = "#1565C0"

        def _resultado(gf_s, gc_s):
            try:
                gf = int(float(str(gf_s))); gc = int(float(str(gc_s)))
            except Exception:
                return "?", 0, 0
            if gf > gc: return "W", gf, gc
            if gf < gc: return "L", gf, gc
            return "D", gf, gc

        def cargar_fix():
            col_proximo.controls.clear()
            col_pendientes.controls.clear()
            col_jugados.controls.clear()
            col_stats.controls.clear()
            try:
                raw_fix  = db.get_all("fixture")
                raw_part = db.get_all("partidos") if db.tiene_hoja("partidos") else []

                # Doble índice: por fecha y por rival
                jugados_por_fecha  = {}   # fecha  -> [(rival_lower, gf, gc)]
                jugados_por_rival  = {}   # rival  -> [(fecha, gf, gc)]
                for p in raw_part:
                    if not p or p[0] == "Fecha" or len(p) < 5: continue
                    f  = p[0].strip()
                    rv = p[1].strip().lower()
                    jugados_por_fecha.setdefault(f,  []).append((rv, p[3], p[4]))
                    jugados_por_rival.setdefault(rv, []).append((f, p[3], p[4]))

                # Tracking de resultados ya usados para no repetir matches
                consumed = set()

                def _buscar_resultado(fecha_fix, rival_fix):
                    rv = rival_fix.strip().lower()
                    # 1. Fecha exacta + rival exacto
                    for e in jugados_por_fecha.get(fecha_fix, []):
                        k = (fecha_fix, e[0])
                        if e[0] == rv and k not in consumed:
                            consumed.add(k); return e[1], e[2]
                    # 2. Fecha exacta + único resultado ese día
                    libres = [(fecha_fix, e[0]) for e in jugados_por_fecha.get(fecha_fix, [])
                              if (fecha_fix, e[0]) not in consumed]
                    if len(libres) == 1:
                        k = libres[0]
                        consumed.add(k)
                        e = jugados_por_fecha[fecha_fix][[i for i,x in enumerate(jugados_por_fecha[fecha_fix]) if (fecha_fix, x[0]) == k][0]]
                        return e[1], e[2]
                    # 3. Rival exacto (fecha distinta — el partido se jugó otro día)
                    for f2, gf, gc in jugados_por_rival.get(rv, []):
                        k = (f2, rv)
                        if k not in consumed:
                            consumed.add(k); return gf, gc
                    # 4. Rival parcial
                    for rv2, entries in jugados_por_rival.items():
                        if rv2 != rv and (rv in rv2 or rv2 in rv):
                            for f2, gf, gc in entries:
                                k = (f2, rv2)
                                if k not in consumed:
                                    consumed.add(k); return gf, gc
                    return None

                # Parsear y ordenar fixture
                items = []
                for i, r in enumerate(raw_fix):
                    if not r or r[0] == "Fecha" or len(r) < 3: continue
                    try:
                        dt = datetime.strptime(r[0].strip(), "%d/%m/%Y")
                    except Exception:
                        dt = None
                    items.append((dt, i + 1, r))
                items.sort(key=lambda x: x[0] if x[0] else datetime.min)

                pendientes = []
                jugados    = []
                proximo_ok = False

                for dt, real_idx, r in items:
                    match_res = _buscar_resultado(r[0].strip(), r[1])
                    es_pasado = dt and dt.date() < hoy.date()
                    if match_res:
                        gf_s, gc_s = match_res
                        res, gf, gc = _resultado(gf_s, gc_s)
                        jugados.append((dt, real_idx, r, res, gf, gc))
                    elif es_pasado:
                        # Partido pasado sin resultado registrado
                        jugados.append((dt, real_idx, r, "?", 0, 0))
                    else:
                        es_prox = bool(dt and dt.date() >= hoy.date() and not proximo_ok)
                        if es_prox: proximo_ok = True
                        pendientes.append((dt, real_idx, r, es_prox))

                # ── PRÓXIMO PARTIDO ──────────────────────────────────
                prox = next((x for x in pendientes if x[3]), None)
                if prox:
                    dt, real_idx, r, _ = prox
                    dias = (dt.date() - hoy.date()).days if dt else 0
                    dias_txt = "Hoy" if dias == 0 else ("Mañana" if dias == 1 else f"En {dias} días")
                    cond     = r[2] if len(r) > 2 else "Local"
                    f_map    = r[3] if len(r) > 3 else ""

                    accs = []
                    if f_map:
                        accs.append(ft.TextButton("📍 Ubicación", url=f_map,
                            style=ft.ButtonStyle(color="white")))
                    accs += [
                        ft.IconButton(icon=ft.icons.EDIT_OUTLINED, icon_color="white", icon_size=18,
                            on_click=lambda e, ix=real_idx, d=r: preparar(ix, d)),
                        ft.IconButton(icon=ft.icons.DELETE_OUTLINE, icon_color="white", icon_size=18,
                            on_click=lambda e, ix=real_idx: borrar(ix)),
                    ]

                    col_proximo.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("PRÓXIMO PARTIDO", size=10, weight="bold",
                                        color="white", opacity=0.75),
                                ft.Container(expand=True),
                                ft.Container(
                                    content=ft.Text(dias_txt, size=11, weight="bold", color=BG_PROXIMO),
                                    bgcolor="white", border_radius=20,
                                    padding=ft.padding.symmetric(horizontal=12, vertical=4)),
                            ]),
                            ft.Text(f"vs {r[1].upper()}", size=26, weight="bold", color="white"),
                            ft.Row([
                                ft.Text(r[0], size=13, color="white", opacity=0.85),
                                ft.Text("·", color="white", opacity=0.4),
                                ft.Text(cond, size=13, color="white", opacity=0.85),
                            ], spacing=6),
                            ft.Row(accs, spacing=0),
                        ], spacing=8),
                        bgcolor=BG_PROXIMO, border_radius=16, padding=20,
                        margin=ft.margin.only(bottom=4),
                    ))
                else:
                    col_proximo.controls.append(ft.Container(
                        content=ft.Text("Sin partidos pendientes", color=C_GRIS_TXT, italic=True, size=13),
                        padding=ft.padding.symmetric(vertical=8)))

                def _cond_badge(cond_val):
                    if cond_val == "Local":
                        return C_AZUL, "#E3F2FD"        # texto, fondo
                    return "#E65100", "#FFF3E0"          # naranja oscuro, fondo naranja claro

                # ── PENDIENTES (sin el próximo) ───────────────────────
                otros = [x for x in pendientes if not x[3]]
                if not otros:
                    col_pendientes.controls.append(
                        ft.Text("No hay más partidos agendados", color=C_GRIS_TXT, italic=True, size=12))
                for dt, real_idx, r, _ in otros:
                    cond           = r[2] if len(r) > 2 else "Local"
                    ct, cb         = _cond_badge(cond)
                    f_map          = r[3] if len(r) > 3 else ""
                    row_btns       = [
                        ft.IconButton(icon=ft.icons.EDIT_OUTLINED, icon_size=16, icon_color=C_GRIS_TXT,
                            on_click=lambda e, ix=real_idx, d=r: preparar(ix, d)),
                        ft.IconButton(icon=ft.icons.DELETE_OUTLINE, icon_size=16, icon_color=C_GRIS_TXT,
                            on_click=lambda e, ix=real_idx: borrar(ix)),
                    ]
                    if f_map:
                        row_btns.insert(0, ft.TextButton("📍", url=f_map))
                    col_pendientes.controls.append(ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(r[0], size=11, color=C_GRIS_TXT),
                                ft.Text(f"vs {r[1]}", size=15, weight="bold", color=C_TEXTO),
                            ], expand=True, spacing=2),
                            ft.Container(
                                content=ft.Text(cond, size=10, weight="bold", color=ct),
                                bgcolor=cb, border_radius=20,
                                padding=ft.padding.symmetric(horizontal=10, vertical=4)),
                            ft.Row(row_btns, spacing=0),
                        ], vertical_alignment="center"),
                        bgcolor=C_BLANCO, border_radius=12,
                        padding=ft.padding.symmetric(horizontal=16, vertical=10),
                        border=ft.border.all(1, C_GRIS),
                    ))

                # ── JUGADOS ─────────────────────────────────────────
                if not jugados:
                    col_jugados.controls.append(
                        ft.Text("Sin partidos jugados aún", color=C_GRIS_TXT, italic=True, size=12))
                for dt, real_idx, r, res, gf, gc in reversed(jugados):
                    cond          = r[2] if len(r) > 2 else "Local"
                    ct, cb        = _cond_badge(cond)
                    if res == "W":
                        bg, bd, tc, label = BG_VICTORIA, BD_VICTORIA, TX_VICTORIA, "VICTORIA"
                    elif res == "L":
                        bg, bd, tc, label = BG_DERROTA,  BD_DERROTA,  TX_DERROTA,  "DERROTA"
                    elif res == "?":
                        bg, bd, tc, label = "#F5F5F5", "#BDBDBD", C_GRIS_TXT, "SIN DATO"
                    else:
                        bg, bd, tc, label = BG_EMPATE,   BD_EMPATE,   TX_EMPATE,   "EMPATE"
                    resultado_txt = "— —" if res == "?" else f"{gf} — {gc}"
                    col_jugados.controls.append(ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(r[0], size=11, color=C_GRIS_TXT),
                                ft.Text(f"vs {r[1]}", size=15, weight="bold", color=C_TEXTO),
                                ft.Container(
                                    content=ft.Text(cond, size=9, weight="bold", color=ct),
                                    bgcolor=cb, border_radius=20,
                                    padding=ft.padding.symmetric(horizontal=8, vertical=2)),
                            ], expand=True, spacing=3),
                            ft.Column([
                                ft.Text(resultado_txt, size=20, weight="bold", color=tc),
                                ft.Container(
                                    content=ft.Text(label, size=9, weight="bold", color=tc),
                                    bgcolor=bd, border_radius=20,
                                    padding=ft.padding.symmetric(horizontal=8, vertical=3)),
                            ], horizontal_alignment="end", spacing=4),
                        ], vertical_alignment="center"),
                        bgcolor=bg, border_radius=12,
                        padding=ft.padding.symmetric(horizontal=16, vertical=12),
                        border=ft.border.all(1, bd),
                    ))

                # ── ESTADÍSTICAS ─────────────────────────────────────
                con_res = [(dt, r, gf, gc) for (dt, _, _, r, gf, gc) in jugados if r != "?"]
                total   = len(con_res)
                if total > 0:
                    w = sum(1 for _, r, _, _ in con_res if r == "W")
                    l = sum(1 for _, r, _, _ in con_res if r == "L")
                    d = sum(1 for _, r, _, _ in con_res if r == "D")
                    gf_tot = sum(gf for _, _, gf, _ in con_res)
                    gc_tot = sum(gc for _, _, _, gc in con_res)
                    pct_w  = round(w / total * 100)
                    pct_l  = round(l / total * 100)
                    pct_d  = 100 - pct_w - pct_l

                    # Barra proporcional
                    bar_segs = []
                    radii = {"top_left": 6, "bottom_left": 6,
                             "top_right": 0, "bottom_right": 0}
                    first = True
                    segs_data = [(w, TX_VICTORIA, f"{pct_w}%  V"),
                                 (d, TX_EMPATE,   f"{pct_d}%  E"),
                                 (l, TX_DERROTA,  f"{pct_l}%  D")]
                    non_zero = [(n, c, lbl) for n, c, lbl in segs_data if n > 0]
                    for idx_s, (n, color, lbl) in enumerate(non_zero):
                        is_last = (idx_s == len(non_zero) - 1)
                        br = ft.border_radius.only(
                            top_left=6 if idx_s == 0 else 0,
                            bottom_left=6 if idx_s == 0 else 0,
                            top_right=6 if is_last else 0,
                            bottom_right=6 if is_last else 0,
                        )
                        bar_segs.append(ft.Container(
                            expand=n, height=14, bgcolor=color, border_radius=br))

                    # Forma (últimos 5) — G=Ganado, P=Perdido, E=Empate
                    ultimos5 = sorted(con_res, key=lambda x: x[0] or datetime.min)[-5:]
                    chips = []
                    for _, res_u, _, _ in ultimos5:
                        c_chip   = TX_VICTORIA if res_u == "W" else (TX_DERROTA if res_u == "L" else TX_EMPATE)
                        lbl_chip = "G" if res_u == "W" else ("P" if res_u == "L" else "E")
                        chips.append(ft.Container(
                            content=ft.Text(lbl_chip, size=11, weight="bold", color="white",
                                            text_align="center"),
                            width=28, height=28, bgcolor=c_chip, border_radius=14,
                            alignment=ft.alignment.Alignment(0, 0),
                        ))

                    dif = gf_tot - gc_tot
                    dif_color = TX_VICTORIA if dif > 0 else (TX_DERROTA if dif < 0 else TX_EMPATE)
                    dif_txt   = f"+{dif}" if dif > 0 else str(dif)

                    col_stats.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Text("RENDIMIENTO", size=11, weight="bold", color=C_GRIS_TXT),
                            # Contadores
                            ft.Row([
                                ft.Column([ft.Text(str(total), size=22, weight="bold", color=C_TEXTO),
                                           ft.Text("jugados", size=10, color=C_GRIS_TXT)],
                                          horizontal_alignment="center"),
                                ft.Container(width=1, height=40, bgcolor=C_GRIS),
                                ft.Column([ft.Text(str(w), size=22, weight="bold", color=TX_VICTORIA),
                                           ft.Text("ganados", size=10, color=C_GRIS_TXT)],
                                          horizontal_alignment="center"),
                                ft.Container(width=1, height=40, bgcolor=C_GRIS),
                                ft.Column([ft.Text(str(l), size=22, weight="bold", color=TX_DERROTA),
                                           ft.Text("perdidos", size=10, color=C_GRIS_TXT)],
                                          horizontal_alignment="center"),
                                ft.Container(width=1, height=40, bgcolor=C_GRIS),
                                ft.Column([ft.Text(str(d), size=22, weight="bold", color=TX_EMPATE),
                                           ft.Text("empates", size=10, color=C_GRIS_TXT)],
                                          horizontal_alignment="center"),
                            ], alignment="spaceAround"),
                            # Barra
                            ft.Row(bar_segs, spacing=2),
                            ft.Row([
                                ft.Text(f"{pct_w}% G", size=10, color=TX_VICTORIA, expand=True),
                                ft.Text(f"{pct_d}% E", size=10, color=TX_EMPATE, text_align="center", expand=True),
                                ft.Text(f"{pct_l}% P", size=10, color=TX_DERROTA, text_align="right", expand=True),
                            ]),
                            ft.Divider(height=1, color=C_GRIS),
                            # Goles — fondos explícitos (sin interpolación ARGB)
                            ft.Row([
                                ft.Column([
                                    ft.Row([
                                        ft.Container(
                                            content=ft.Column([
                                                ft.Text(str(gf_tot), size=26, weight="bold",
                                                        color=TX_VICTORIA, text_align="center"),
                                                ft.Text("a favor", size=10, color=TX_VICTORIA,
                                                        text_align="center"),
                                            ], horizontal_alignment="center", spacing=0),
                                            bgcolor=BG_VICTORIA, border_radius=10,
                                            padding=ft.padding.symmetric(horizontal=16, vertical=8),
                                        ),
                                        ft.Text("vs", size=14, color=C_GRIS_TXT),
                                        ft.Container(
                                            content=ft.Column([
                                                ft.Text(str(gc_tot), size=26, weight="bold",
                                                        color=TX_DERROTA, text_align="center"),
                                                ft.Text("en contra", size=10, color=TX_DERROTA,
                                                        text_align="center"),
                                            ], horizontal_alignment="center", spacing=0),
                                            bgcolor=BG_DERROTA, border_radius=10,
                                            padding=ft.padding.symmetric(horizontal=16, vertical=8),
                                        ),
                                    ], spacing=10, vertical_alignment="center"),
                                ], expand=True),
                                ft.Container(
                                    content=ft.Column([
                                        ft.Text(dif_txt, size=20, weight="bold", color=dif_color,
                                                text_align="center"),
                                        ft.Text("diferencia", size=9, color=dif_color,
                                                text_align="center"),
                                    ], horizontal_alignment="center", spacing=0),
                                    bgcolor=(BG_VICTORIA if dif > 0 else
                                             (BG_DERROTA if dif < 0 else BG_EMPATE)),
                                    border_radius=12,
                                    padding=ft.padding.symmetric(horizontal=14, vertical=8),
                                ),
                            ], vertical_alignment="center"),
                            # Últimos 5
                            ft.Row([
                                ft.Text("Últimos resultados:", size=11, color=C_GRIS_TXT),
                                *chips,
                            ], spacing=6, vertical_alignment="center"),
                        ], spacing=10),
                        bgcolor=C_BLANCO, border_radius=14,
                        padding=ft.padding.symmetric(horizontal=16, vertical=14),
                        border=ft.border.all(1, C_GRIS),
                    ))

                    # ── CARD TEMPORADA ────────────────────────────────
                    total_season = len(jugados) + len(pendientes)
                    remaining    = len(pendientes)
                    if total_season > 0:
                        win_pct = w / total if total > 0 else 0
                        if win_pct >= 0.6:
                            st_msg, st_col, st_bg = "Buen rendimiento", TX_VICTORIA, BG_VICTORIA
                        elif win_pct >= 0.4:
                            st_msg, st_col, st_bg = "Rendimiento regular", TX_EMPATE, BG_EMPATE
                        else:
                            st_msg, st_col, st_bg = "Hay que levantar", TX_DERROTA, BG_DERROTA

                        played_n = len(jugados)
                        prog_segs = []
                        if played_n > 0:
                            prog_segs.append(ft.Container(
                                expand=played_n, height=12, bgcolor=C_AZUL,
                                border_radius=ft.border_radius.only(
                                    top_left=6, bottom_left=6,
                                    top_right=6 if remaining == 0 else 0,
                                    bottom_right=6 if remaining == 0 else 0,
                                )))
                        if remaining > 0:
                            prog_segs.append(ft.Container(
                                expand=remaining, height=12, bgcolor=C_GRIS,
                                border_radius=ft.border_radius.only(
                                    top_left=6 if played_n == 0 else 0,
                                    bottom_left=6 if played_n == 0 else 0,
                                    top_right=6, bottom_right=6,
                                )))

                        col_stats.controls.append(ft.Container(
                            content=ft.Column([
                                ft.Text("TEMPORADA", size=11, weight="bold", color=C_GRIS_TXT),
                                ft.Row([
                                    ft.Text(f"{played_n} de {total_season} partidos jugados",
                                            size=14, weight="bold", color=C_TEXTO, expand=True),
                                    ft.Text(f"{remaining} restantes", size=12, color=C_AZUL),
                                ], vertical_alignment="center"),
                                ft.Row(prog_segs, spacing=2) if prog_segs else ft.Container(),
                                ft.Row([
                                    ft.Text(f"{round(played_n / total_season * 100)}% completada",
                                            size=10, color=C_GRIS_TXT, expand=True),
                                    ft.Text(f"{pct_w}% victorias", size=10, color=TX_VICTORIA),
                                ]),
                                ft.Container(
                                    content=ft.Text(st_msg, size=13, weight="bold", color=st_col),
                                    bgcolor=st_bg, border_radius=8,
                                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                                ),
                            ], spacing=8),
                            bgcolor=C_BLANCO, border_radius=14,
                            padding=ft.padding.symmetric(horizontal=16, vertical=14),
                            border=ft.border.all(1, C_GRIS),
                        ))

            except Exception as ex:
                log.error(f"cargar_fix: {ex}")
            page.update()

        def preparar(idx, d):
            txt_f.value    = d[0]; txt_r.value = d[1]; dd_c.value = d[2]
            txt_maps.value = d[3] if len(d) > 3 else ""
            edit_idx[0]    = idx
            btn_accion.text  = "GUARDAR"
            btn_accion.bgcolor = C_AZUL
            page.update()

        def borrar(idx):
            db.delete_row("fixture", idx); cargar_fix()

        def procesar(e):
            if not txt_f.value or not txt_r.value:
                txt_estado.value = "⚠️ Completá fecha y rival"; page.update(); return
            row_data = [txt_f.value, txt_r.value, dd_c.value, txt_maps.value]
            try:
                if edit_idx[0] != -1:
                    db.delete_row("fixture", edit_idx[0])
                    db.insert_row("fixture", row_data, edit_idx[0])
                    edit_idx[0] = -1
                    btn_accion.text   = "+ AGREGAR"
                    btn_accion.bgcolor = C_VERDE
                else:
                    db.append("fixture", row_data)
                txt_r.value = ""; txt_maps.value = ""; txt_f.value = ""
                cargar_fix()
            except Exception as ex:
                log.error(f"procesar fixture: {ex}")
                txt_estado.value = str(ex)
            page.update()

        btn_accion.on_click = procesar

        def cargar_fix_delayed():
            import time; time.sleep(0.3); cargar_fix()

        threading.Thread(target=cargar_fix_delayed, daemon=True).start()

        def _section_label(txt):
            return ft.Text(txt, size=11, weight="bold", color=C_GRIS_TXT)

        # columna_contenido ya tiene scroll="auto", no anidamos scroll
        return ft.Column([
            ft.Row([
                ft.Text("Fixture", size=22, weight="bold", color=C_TEXTO),
                ft.Container(expand=True),
                ft.IconButton(icon=ft.icons.REFRESH, icon_color=C_AZUL,
                              tooltip="Actualizar", on_click=lambda e: cargar_fix()),
                ft.TextButton("Volver", on_click=lambda e: navegar("part"),
                              style=ft.ButtonStyle(color=C_GRIS_TXT)),
            ]),
            ft.Divider(height=1, color=C_GRIS, thickness=1),
            col_proximo,
            ft.Container(content=_section_label("PRÓXIMOS PARTIDOS"),
                         margin=ft.margin.only(top=8, bottom=4)),
            col_pendientes,
            ft.Divider(height=1, color=C_GRIS, thickness=1),
            ft.Container(content=_section_label("PARTIDOS JUGADOS"),
                         margin=ft.margin.only(top=4, bottom=4)),
            col_jugados,
            ft.Divider(height=1, color=C_GRIS, thickness=1),
            ft.Container(content=_section_label("ESTADÍSTICAS"),
                         margin=ft.margin.only(top=4, bottom=4)),
            col_stats,
            ft.Divider(height=1, color=C_GRIS, thickness=1),
            ft.Container(content=_section_label("AGREGAR / EDITAR PARTIDO"),
                         margin=ft.margin.only(top=4, bottom=4)),
            ft.Row([txt_f, dd_c]),
            txt_r,
            txt_maps,
            btn_accion,
            ft.Container(height=24),
        ], spacing=8)

    # ----------------------------------------------------------
    def vista_resumen_partidos():
        stats_col = ft.Column(scroll="auto", expand=True)
        txt_estado.value = "Calculando..."; page.update()

        btn_pdf  = ft.ElevatedButton("📄 GENERAR PDF", bgcolor=C_VERDE, color="white")
        btn_ojo  = ft.IconButton(icon=ft.icons.VISIBILITY, disabled=True, icon_color=C_GRIS_TXT)

        try:
            raw      = db.get_all("partidos")
            raw_data = [r for r in raw if len(r) > 0 and r[0] != "Fecha"]
            filas    = []; ranking: dict = {}

            for r in raw_data:
                gf = r[3] if len(r) > 3 else "0"
                gc = r[4] if len(r) > 4 else "0"
                filas.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(r[0] if r else "")),
                    ft.DataCell(ft.Text(r[1] if len(r)>1 else "")),
                    ft.DataCell(ft.Text(f"{gf}(f) - {gc}(c)", weight="bold")),
                    ft.DataCell(ft.Text(r[2] if len(r)>2 else "")),
                ]))
                txt_goles = r[7] if len(r) > 7 else ""
                if txt_goles and txt_goles.strip() != "Sin datos":
                    for p in txt_goles.split(","):
                        m = re.search(r"(.+)\((\d+)\)", p)
                        if m:
                            n = m.group(1).strip()
                            ranking[n] = ranking.get(n, 0) + int(m.group(2))

            def on_pdf(e):
                txt_estado.value = "Generando PDF..."; page.update()
                ok, res, url = pdf_gen.resumen_partidos(raw_data)
                if ok:
                    txt_estado.value = "✅ PDF listo."
                    mostrar_pdf_inline(url)
                else:
                    txt_estado.value = f"❌ Error: {res}"
                page.update()

            btn_pdf.on_click = on_pdf

            tabla_p = ft.DataTable(
                columns=[ft.DataColumn(ft.Text(h)) for h in ["FECHA","RIVAL","RES","COND"]],
                rows=filas, border=ft.border.all(1, C_GRIS),
            )
            filas_g = [
                ft.DataRow(cells=[ft.DataCell(ft.Text(n, weight="bold")), ft.DataCell(ft.Text(str(c)))])
                for n, c in sorted(ranking.items(), key=lambda x: x[1], reverse=True)
            ]
            tabla_g = ft.DataTable(
                columns=[ft.DataColumn(ft.Text(h)) for h in ["JUGADORA","GOLES"]],
                rows=filas_g, border=ft.border.all(1, C_GRIS),
            )
            stats_col.controls.append(ft.Column([
                ft.Text("Resultados", weight="bold"),
                ft.Row([tabla_p], scroll="always"),
                ft.Divider(),
                ft.Text("Goleadoras", weight="bold"),
                ft.Row([tabla_g], scroll="always"),
            ]))
            txt_estado.value = "✅ Listo"
        except Exception as ex:
            log.error(f"vista_resumen_partidos: {ex}")
            stats_col.controls.append(ft.Text(f"❌ Error: {ex}", color="red"))

        def _gen_informe_plantel():
            txt_estado.value = "Generando informe..."; page.update()
            ok, res, url = pdf_gen.informe_plantel(lista_jugadoras_raw, db)
            if ok:
                txt_estado.value = "✅ Informe listo."
                mostrar_pdf_inline(url)
            else:
                txt_estado.value = f"❌ Error: {res}"
            page.update()

        return ft.Column([
            ft.Text(f"Resumen Técnico — {club_actual[0]}", size=20, weight="bold", color=C_AZUL),
            ft.ElevatedButton(
                "📊 INFORME GENERAL DEL PLANTEL",
                on_click=lambda e: _gen_informe_plantel(),
                bgcolor="#607D8B", color="white",
            ),
            ft.Row([btn_pdf, btn_ojo]),
            ft.Divider(), stats_col, ft.Divider(),
            ft.ElevatedButton("VOLVER", on_click=lambda e: navegar("part")),
        ])

    # ----------------------------------------------------------
    def vista_partidos():
        raw_count = db.get_all("partidos")
        c_jug = len([r for r in raw_count if r and r[0] != "Fecha"])
        c_tot = 0
        if db.tiene_hoja("fixture"):
            raw_fix = db.get_all("fixture")
            c_tot = len([r for r in raw_fix if r and r[0] != "Fecha"])

        rivales_set: set = set()
        if db.tiene_hoja("fixture"):
            try:
                for r in db.get_all("fixture"):
                    if r and r[0] != "Fecha" and len(r) > 1:
                        rivales_set.add(r[1].strip())
            except Exception:
                pass

        top = ft.Container(content=ft.Text(f"Jugados: {c_jug}/{c_tot}", color="white"), bgcolor="#607D8B", padding=5)
        txt_fecha_p = ft.TextField(label="Fecha", value=datetime.now().strftime("%d/%m/%Y"), width=110)
        dd_rival    = ft.Dropdown(label="Rival", options=[ft.dropdown.Option(x) for x in sorted(rivales_set)], expand=True)
        dc          = ft.Dropdown(options=[ft.dropdown.Option("Local"), ft.dropdown.Option("Visitante")], value="Local", width=110)
        gf = ft.TextField(label="GF", width=80); gc = ft.TextField(label="GC", width=80)
        cf = ft.TextField(label="Corn F", width=80); cc = ft.TextField(label="Corn C", width=80)
        hist             = ft.Column()
        goleadoras_dict: dict = {}
        lista_goles      = ft.Column()
        dd_autora        = ft.Dropdown(label="Jugadora", options=[ft.dropdown.Option(f"{j['nombre']} {j['apellido']}") for j in lista_jugadoras_raw], expand=True)
        txt_ext          = ft.TextField(label="Externa", width=120)

        def act_goles():
            lista_goles.controls.clear()
            for n, c_g in goleadoras_dict.items():
                lista_goles.controls.append(ft.Row([
                    ft.Text(n, expand=True),
                    ft.ElevatedButton("-", on_click=lambda e, x=n: mod_gol(x, -1), width=40),
                    ft.Text(str(c_g)),
                    ft.ElevatedButton("+", on_click=lambda e, x=n: mod_gol(x, +1), width=40),
                ]))
            page.update()

        def mod_gol(n, d):
            goleadoras_dict[n] = goleadoras_dict.get(n, 0) + d
            if goleadoras_dict[n] <= 0:
                del goleadoras_dict[n]
            act_goles()

        def add_gol(e):
            n = dd_autora.value or txt_ext.value
            if n:
                goleadoras_dict[n] = goleadoras_dict.get(n, 0) + 1
                dd_autora.value = None; txt_ext.value = ""
                if dd_autora.page: dd_autora.update()
                if txt_ext.page:   txt_ext.update()
                act_goles()

        def load_hist():
            hist.controls.clear()
            try:
                raw = db.get_all("partidos")
                for i, data in enumerate(reversed(raw)):
                    if data and data[0] == "Fecha": continue
                    if len(data) < 5: continue
                    idx_real = len(raw) - i
                    titulo   = f"{club_actual[0]} vs {data[1]}" if data[2] == "Local" else f"{data[1]} vs {club_actual[0]}"
                    res_txt  = f"Res: {data[3]} - {data[4]} | Corn: {data[5] if len(data)>5 else 0}(f) - {data[6] if len(data)>6 else 0}(c)"
                    hist.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Row([ft.Text(data[0], weight="bold"), ft.Container(expand=True), ft.TextButton("🗑️", on_click=lambda e, ix=idx_real: borrar(ix))]),
                            ft.Text(titulo),
                            ft.Text(res_txt),
                            ft.Text(f"Goles: {data[7]}" if len(data) > 7 else ""),
                        ]),
                        padding=10, border=ft.border.all(1, "grey"), border_radius=5,
                    ))
            except Exception as ex:
                log.error(f"load_hist: {ex}")
            page.update()

        def borrar(ix):
            db.delete_row("partidos", ix); load_hist()

        def sv(e):
            txt_gol   = ", ".join(f"{n} ({c_g})" for n, c_g in goleadoras_dict.items())
            val_rival = dd_rival.value or "Desconocido"
            try:
                db.append("partidos", [
                    txt_fecha_p.value, val_rival, dc.value or "Local",
                    gf.value or "0", gc.value or "0",
                    cf.value or "0", cc.value or "0",
                    txt_gol,
                ])
                goleadoras_dict.clear(); act_goles(); load_hist()
                txt_estado.value = "✅ Partido guardado"
            except Exception as ex:
                log.error(f"sv partido: {ex}")
                txt_estado.value = f"❌ Error: {ex}"
            page.update()

        load_hist()
        return ft.Column([
            ft.Text("Resultados", size=20, weight="bold"),
            top,
            ft.Row([
                ft.ElevatedButton("📅 FIXTURE",  on_click=lambda e: navegar("fixture_full"), bgcolor=C_AZUL,  color="white"),
                ft.ElevatedButton("📊 RESUMEN",  on_click=lambda e: navegar("resumen_partidos"), bgcolor="#607D8B", color="white"),
            ]),
            ft.Divider(),
            ft.Row([txt_fecha_p, dd_rival, dc]),
            ft.Row([gf, gc]), ft.Row([cf, cc]),
            ft.Text("Goleadoras:"),
            ft.Row([dd_autora, txt_ext, ft.ElevatedButton("+", on_click=add_gol)]),
            lista_goles,
            ft.ElevatedButton("GUARDAR", on_click=sv, bgcolor=C_VERDE, color="white"),
            ft.Divider(), hist,
        ], scroll="auto")

    # ----------------------------------------------------------
    def vista_formacion():
        jugadoras_externas:       list = []
        lista_ausentes:           list = []
        lista_suplentes_manual:   list = []   # [{"nombre": str, "categoria": str}]
        seleccion:                dict = {}

        POSICIONES = [
            ("ARCO",    "🟥", "Arquera (1)"),
            ("DEFENSA", "🟦", "Libero (2)"),
            ("DEFENSA", "🟦", "Stopper (6)"),
            ("DEFENSA", "🟦", "Half Der. (4)"),
            ("DEFENSA", "🟦", "Half Izq. (3)"),
            ("MEDIO",   "🟩", "Volante Central (5)"),
            ("MEDIO",   "🟩", "Volante Der. (8)"),
            ("MEDIO",   "🟩", "Volante Izq. (10)"),
            ("ATAQUE",  "🟨", "Wing Der. (7)"),
            ("ATAQUE",  "🟨", "Delantera Centro (9)"),
            ("ATAQUE",  "🟨", "Wing Izq. (11)"),
        ]

        # Cargar partidos
        partidos_disp = []
        if db.tiene_hoja("fixture"):
            try:
                for r in db.get_all("fixture"):
                    if r and r[0] == "Fecha": continue
                    if len(r) > 2:
                        partidos_disp.append(f"{r[0]} vs {r[1]} ({r[2]})")
            except Exception:
                pass

        def get_todas():
            base = [f"{j['nombre']} {j['apellido']}" for j in lista_jugadoras_raw]
            return sorted(base + jugadoras_externas)

        dd_partido = ft.Dropdown(
            label="Partido",
            options=[ft.dropdown.Option(p) for p in partidos_disp],
            expand=True,
        )
        dd_esquema = ft.Dropdown(
            label="Esquema",
            options=[ft.dropdown.Option(x) for x in ["Doble 5","3-3-1-3","4-3-3"]],
            value="Doble 5", width=120,
        )

        # Construir filas de posición con filtrado dinámico
        filas_posiciones = []
        dropdowns_pos: dict = {}
        todas_ini = get_todas()

        def actualizar_opciones():
            sel_actuales = {v for v in seleccion.values() if v}
            aus_set = {a["nombre"] for a in lista_ausentes}
            sup_set = {s["nombre"] for s in lista_suplentes_manual}
            for pos, dd in dropdowns_pos.items():
                val_actual = seleccion.get(pos, "")
                otras = sel_actuales - ({val_actual} if val_actual else set())
                libres = [n for n in get_todas() if n not in otras and n not in aus_set and n not in sup_set]
                dd.options = [ft.dropdown.Option("")] + [ft.dropdown.Option(n) for n in libres]
                dd.value = val_actual or None
            ocupadas = sel_actuales | aus_set | sup_set
            dd_nueva_ausente.options  = [ft.dropdown.Option(n) for n in get_todas() if n not in ocupadas]
            dd_nueva_suplente.options = [ft.dropdown.Option(n) for n in get_todas() if n not in ocupadas]
            page.update()

        def on_cambio_posicion(e, pos):
            seleccion[pos] = e.control.value or ""
            actualizar_opciones()

        seccion_actual = ""
        for lin, icono, p in POSICIONES:
            if lin != seccion_actual:
                seccion_actual = lin
                filas_posiciones.append(
                    ft.Container(
                        content=ft.Text(f"{icono} {lin}", size=13, weight="bold", color=C_BLANCO),
                        bgcolor={"ARCO": C_ROJO, "DEFENSA": C_AZUL, "MEDIO": C_VERDE, "ATAQUE": C_AMARILLO}.get(lin, C_GRIS_TXT),
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=6,
                        margin=ft.margin.only(top=8),
                    )
                )

            dd = ft.Dropdown(
                options=[ft.dropdown.Option("")] + [ft.dropdown.Option(n) for n in todas_ini],
                hint_text="Seleccionar...",
                expand=True,
                dense=True,
                text_size=13,
                on_change=lambda e, pos=p: on_cambio_posicion(e, pos),
            )
            dropdowns_pos[p] = dd

            filas_posiciones.append(
                ft.Container(
                    content=ft.Row([
                        ft.Container(
                            content=ft.Text(p.split("(")[0].strip(), size=12, color=C_TEXTO, weight="bold"),
                            width=160,
                        ),
                        dd,
                    ], alignment="spaceBetween"),
                    bgcolor=C_BLANCO,
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    border=ft.border.only(bottom=ft.border.BorderSide(1, C_GRIS)),
                )
            )

        # Ausentes
        col_ausentes     = ft.Column(spacing=4)
        dd_nueva_ausente = ft.Dropdown(
            label="Jugadora Ausente", expand=True,
            options=[ft.dropdown.Option(n) for n in todas_ini],
        )
        txt_motivo = ft.TextField(label="Motivo (opcional)", expand=True)

        def render_aus():
            col_ausentes.controls.clear()
            for i, a in enumerate(lista_ausentes):
                def hacer_del(idx):
                    def fn(e):
                        lista_ausentes.pop(idx)
                        render_aus()
                        actualizar_opciones()
                    return fn
                col_ausentes.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Text(f"• {a['nombre']}" + (f" — {a['motivo']}" if a['motivo'] else ""),
                                color=C_ROJO, size=12, expand=True),
                        ft.IconButton(ft.icons.DELETE, icon_color=C_ROJO, on_click=hacer_del(i)),
                    ]),
                    bgcolor="#FFEBEE", border_radius=6, padding=6,
                ))
            page.update()

        def add_aus(e):
            if dd_nueva_ausente.value:
                lista_ausentes.append({"nombre": dd_nueva_ausente.value, "motivo": txt_motivo.value})
                dd_nueva_ausente.value = None
                txt_motivo.value = ""
                render_aus()
                actualizar_opciones()

        # Suplentes manuales
        col_suplentes_manual = ft.Column(spacing=4)
        dd_nueva_suplente = ft.Dropdown(
            label="Suplente", expand=True,
            options=[ft.dropdown.Option(n) for n in todas_ini],
        )
        dd_cat_suplente = ft.Dropdown(
            label="Posición",
            options=[ft.dropdown.Option(x) for x in ["Defensoras", "Volantes", "Delanteras"]],
            value="Defensoras", width=140,
        )
        CAT_COLOR = {"Defensoras": C_AZUL, "Volantes": C_VERDE, "Delanteras": "#FF9800"}

        def render_sup():
            col_suplentes_manual.controls.clear()
            for i, s in enumerate(lista_suplentes_manual):
                cc = CAT_COLOR.get(s["categoria"], C_GRIS_TXT)
                def hacer_del_sup(idx):
                    def fn(e):
                        lista_suplentes_manual.pop(idx)
                        render_sup(); actualizar_opciones()
                    return fn
                col_suplentes_manual.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Container(
                            content=ft.Text(s["categoria"][:3].upper(), size=9, weight="bold", color="white"),
                            bgcolor=cc, border_radius=4,
                            padding=ft.padding.symmetric(horizontal=6, vertical=3)),
                        ft.Text(s["nombre"], size=12, expand=True),
                        ft.IconButton(ft.icons.DELETE, icon_color=C_GRIS_TXT, icon_size=16,
                                      on_click=hacer_del_sup(i)),
                    ], vertical_alignment="center"),
                    bgcolor=C_BLANCO, border_radius=6, padding=4,
                    border=ft.border.all(1, C_GRIS),
                ))
            page.update()

        def add_sup(e):
            if dd_nueva_suplente.value:
                lista_suplentes_manual.append({
                    "nombre": dd_nueva_suplente.value,
                    "categoria": dd_cat_suplente.value or "Defensoras",
                })
                dd_nueva_suplente.value = None
                render_sup(); actualizar_opciones()

        # Notas
        txt_notas = ft.TextField(
            label="Notas del partido (aparecerá en el PDF)",
            multiline=True, min_lines=2, max_lines=3,
        )

        # Jugadora externa
        txt_externa = ft.TextField(label="Nombre y Apellido", expand=True)

        def add_externa(e):
            val = txt_externa.value.strip()
            if val and val not in jugadoras_externas:
                jugadoras_externas.append(val)
                txt_externa.value = ""
                actualizar_opciones()

        # Título manual del partido (cuando no está en el fixture)
        txt_partido_manual = ft.TextField(
            label="O escribir título del partido manualmente",
            hint_text="ej: Club Atlético vs Rivadavia",
        )

        # PDF
        def btn_pdf_click(e):
            partido_str = dd_partido.value or (txt_partido_manual.value or "").strip()
            if not partido_str:
                txt_estado.value = "⚠️ Seleccioná o escribí el partido"
                page.update(); return
            txt_estado.value = "Generando PDF..."; page.update()
            tits = {p: dd.value for p, dd in dropdowns_pos.items() if dd.value}

            # Usar lista manual de suplentes
            suplentes_dict = {"Defensoras": [], "Volantes": [], "Delanteras": []}
            for s in lista_suplentes_manual:
                cat = s.get("categoria", "Defensoras")
                suplentes_dict.setdefault(cat, []).append(s["nombre"])

            ok, res, url = pdf_gen.formacion(
                partido_str, dd_esquema.value,
                tits, lista_ausentes, suplentes_dict,
                notas=txt_notas.value or "",
            )
            if ok:
                txt_estado.value = "✅ PDF listo."
                mostrar_pdf_inline(url)
            else:
                txt_estado.value = f"❌ Error: {res}"
            page.update()

        return ft.Column([
            ft.Text("Armado de Equipo", size=20, weight="bold", color=C_AZUL),

            # Partido y esquema
            ft.Container(
                content=ft.Column([
                    ft.Row([dd_partido, dd_esquema]),
                    ft.Text("O escribí el título manualmente:", size=11, color=C_GRIS_TXT),
                    txt_partido_manual,
                ], spacing=6),
                bgcolor=C_BLANCO, padding=10, border_radius=8,
                border=ft.border.all(1, C_GRIS),
            ),

            # Jugadora externa
            ft.Container(
                content=ft.Column([
                    ft.Text("➕ Jugadora externa (invitada)", size=12, color=C_GRIS_TXT, weight="bold"),
                    ft.Row([txt_externa, ft.ElevatedButton("Agregar", on_click=add_externa, bgcolor=C_VERDE, color="white")]),
                ]),
                bgcolor=C_BLANCO, padding=10, border_radius=8,
                border=ft.border.all(1, C_GRIS),
            ),

            # Posiciones
            ft.Container(
                content=ft.Column(filas_posiciones, spacing=0),
                bgcolor=C_GRIS_CLARO, padding=10, border_radius=8,
                border=ft.border.all(1, C_GRIS),
            ),

            # Ausentes
            ft.Container(
                content=ft.Column([
                    ft.Text("🚫 Ausentes", size=13, weight="bold", color=C_ROJO),
                    ft.Row([dd_nueva_ausente, txt_motivo, ft.ElevatedButton("➕", on_click=add_aus, bgcolor=C_ROJO, color="white")]),
                    col_ausentes,
                ]),
                bgcolor=C_BLANCO, padding=10, border_radius=8,
                border=ft.border.all(1, C_GRIS),
            ),

            # Suplentes manuales
            ft.Container(
                content=ft.Column([
                    ft.Text("🔄 Suplentes", size=13, weight="bold", color=C_AZUL),
                    ft.Row([
                        dd_nueva_suplente,
                        dd_cat_suplente,
                        ft.ElevatedButton("➕", on_click=add_sup, bgcolor=C_AZUL, color="white"),
                    ]),
                    col_suplentes_manual,
                ]),
                bgcolor=C_BLANCO, padding=10, border_radius=8,
                border=ft.border.all(1, C_GRIS),
            ),

            # Notas
            ft.Container(
                content=ft.Column([
                    ft.Text("📝 Notas del partido", size=13, weight="bold", color=C_GRIS_TXT),
                    txt_notas,
                ]),
                bgcolor=C_BLANCO, padding=10, border_radius=8,
                border=ft.border.all(1, C_GRIS),
            ),

            ft.ElevatedButton(
                "📄 GENERAR PDF DE FORMACIÓN",
                on_click=btn_pdf_click,
                bgcolor=C_VERDE, color="white", height=50,
            ),
        ], spacing=8, scroll="auto")


    # ==========================================================
    # MENÚ PRINCIPAL
    # ==========================================================
    # NAVEGACIÓN MODERNA — barra custom compatible con Flet 0.21
    # ==========================================================
    _NAV_ITEMS = [
        ("asis",      ft.Icons.LIST_ALT,    "Asistencia"),
        ("eval",      ft.Icons.SHOW_CHART,  "Estadísticas"),
        ("part",      ft.Icons.SPORTS,      "Partidos"),
        ("formacion", ft.Icons.GRID_ON,     "Formación"),
        ("plantel",   ft.Icons.GROUP,       "Plantel"),
        ("ficha",     ft.Icons.NOTES,       "Informes"),
    ]
    _nav_buttons = []   # referencias a los containers de cada ítem

    def _build_nav_item(destino, icono, label, seleccionado):
        return ft.Container(
            content=ft.Column([
                ft.Icon(icono, color="#1565C0" if seleccionado else "#546E7A", size=22),
                ft.Text(label, size=10,
                        color="#1565C0" if seleccionado else "#546E7A",
                        weight="bold" if seleccionado else "normal"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
            padding=ft.padding.symmetric(horizontal=4, vertical=6),
            border_radius=12,
            bgcolor="#DBEAFE" if seleccionado else "transparent",
            expand=True,
            on_click=lambda e, d=destino: navegar(d),
        )

    def _refresh_nav(destino_activo):
        for i, (d, ic, lbl) in enumerate(_NAV_ITEMS):
            sel = (d == destino_activo)
            c = _nav_buttons[i]
            c.bgcolor = "#DBEAFE" if sel else "transparent"
            try:
                col = c.content
                col.controls[0].color = "#1565C0" if sel else "#546E7A"
                col.controls[1].color = "#1565C0" if sel else "#546E7A"
                col.controls[1].weight = "bold" if sel else "normal"
            except Exception:
                pass
        if page.controls:
            page.update()

    _nav_bar_ref[0] = _refresh_nav   # guardamos la función de refresco

    nav_bar = ft.Container(
        content=ft.Row([], spacing=0),
        bgcolor=C_BLANCO,
        padding=ft.padding.symmetric(horizontal=4, vertical=2),
        shadow=ft.BoxShadow(blur_radius=8, color="#22000000", offset=ft.Offset(0, -2)),
    )
    for d, ic, lbl in _NAV_ITEMS:
        btn = _build_nav_item(d, ic, lbl, d == "asis")
        _nav_buttons.append(btn)
        nav_bar.content.controls.append(btn)

    # HEADER superior con gradiente
    _header_club_txt = ft.Text(
        f"{club_actual[0]}  ·  {categoria_actual[0]}",
        color="#B3D4FF", size=12,
    )
    header = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.SPORTS, color="white", size=26),
            ft.Text("HockeyApp", color="white", weight="bold", size=18, expand=True),
            _header_club_txt,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        gradient=ft.LinearGradient(
            begin=ft.alignment.Alignment(-1, 0),
            end=ft.alignment.Alignment(1, 0),
            colors=["#0D47A1", "#1565C0", "#0097A7"],
        ),
    )
    _header_ref[0] = _header_club_txt   # guardamos referencia al Text para actualizar

    # STATUS BAR inferior muy sutil
    status_bar = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.CIRCLE, size=8, color="#43A047"),
            txt_estado,
        ], spacing=6),
        padding=ft.padding.symmetric(horizontal=12, vertical=4),
        bgcolor="#EEF2FF",
    )

    contenedor_principal.bgcolor = C_FONDO

    columna_contenido.controls.append(vista_asistencia())
    page.add(header, banner_pdf, contenedor_principal, status_bar, nav_bar)


# ==============================================================
# ENTRY POINT
# ==============================================================
port = int(os.environ.get("PORT", 8502))
ft.app(
    target=main,
    view=ft.AppView.WEB_BROWSER,
    port=port,
    assets_dir="assets",
)
