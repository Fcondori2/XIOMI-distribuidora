import flet as ft
import os
import sqlite3
import traceback
import time
import urllib.parse
from contextlib import contextmanager
from datetime import date, datetime, timedelta

# ==========================================
# 0. RUTAS ABSOLUTAS Y HERRAMIENTAS
# ==========================================
directorio_actual = os.path.dirname(os.path.abspath(__file__))
carpeta_assets = os.path.join(directorio_actual, "assets")
ruta_db = os.path.join(directorio_actual, "sistema_ventas.db")

if not os.path.exists(carpeta_assets):
    os.makedirs(carpeta_assets)

def abrir_archivo_local(ruta_absoluta):
    try:
        if os.name == 'nt':
            os.startfile(ruta_absoluta)
        else:
            import subprocess
            subprocess.call(['xdg-open', ruta_absoluta])
    except Exception as e:
        print("Error al abrir nativo:", e)
        try:
            url_pdf = f"file:///{urllib.parse.quote(ruta_absoluta.replace(chr(92), '/'), safe=':/')}"
            import webbrowser
            webbrowser.open(url_pdf)
        except Exception as e2:
            print("Error al abrir navegador:", e2)

# ==========================================
# 1. BASE DE DATOS LOCAL
# ==========================================
@contextmanager
def conexion_segura():
    conexion = sqlite3.connect(ruta_db, timeout=15)
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conexion
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()

def db(query, parametros=(), fetch=False, fetchall=False):
    with conexion_segura() as conexion:
        cursor = conexion.cursor()
        cursor.execute(query, parametros)
        if fetch:
            return cursor.fetchall() if fetchall else cursor.fetchone()
        return None

def ejecutar_transaccion(operaciones):
    with conexion_segura() as conexion:
        cursor = conexion.cursor()
        for query, parametros in operaciones:
            cursor.execute(query, parametros)

def inicializar_base_datos():
    db('''CREATE TABLE IF NOT EXISTS Clientes (numero_cliente INTEGER PRIMARY KEY AUTOINCREMENT, nombre_apellido TEXT NOT NULL, direccion_entrega TEXT)''')
    db('''CREATE TABLE IF NOT EXISTS Productos (codigo_articulo TEXT PRIMARY KEY, nombre_articulo TEXT NOT NULL, precio_unitario REAL NOT NULL)''')
    db('''CREATE TABLE IF NOT EXISTS Facturas (numero_factura INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, numero_cliente INTEGER, total_a_pagar REAL NOT NULL, preventista TEXT)''')
    db('''CREATE TABLE IF NOT EXISTS Detalle_Factura (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_factura INTEGER, codigo_articulo TEXT, nombre_personalizado TEXT, precio_unitario REAL, unidades REAL, total_linea REAL)''')
    db('''CREATE TABLE IF NOT EXISTS Preventistas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, pin TEXT NOT NULL)''')
    
    try: db("ALTER TABLE Facturas ADD COLUMN preventista TEXT DEFAULT 'ADMIN'")
    except: pass

    try: db("ALTER TABLE Detalle_Factura ADD COLUMN nombre_personalizado TEXT")
    except: pass

    if db("SELECT COUNT(*) FROM Clientes", fetch=True)[0] == 0:
        db("INSERT INTO Clientes (nombre_apellido, direccion_entrega) VALUES ('CONSUMIDOR FINAL', 'PERICO')")
    
    usuarios_permitidos = [("ABR042026", "4444"), ("ABR012026", "1111"), ("ABR022026", "2222"), ("ABR032026", "3333")]
    for nombre, pin in usuarios_permitidos:
        if db("SELECT COUNT(*) FROM Preventistas WHERE nombre=?", (nombre,), fetch=True)[0] == 0:
            db("INSERT INTO Preventistas (nombre, pin) VALUES (?, ?)", (nombre, pin))

    if db("SELECT COUNT(*) FROM Productos", fetch=True)[0] == 0:
        lista_productos_junio = [
            ("ART-001", "SODA MARINARO 1,5 LT X 6", 5500.0), ("ART-002", "SODA SIFON 2LT X 4", 6700.0),
            ("ART-003", "AGUA MARINARO 500 ML X 12", 7000.0), ("ART-004", "SODA MARINARO 500 ML X 12", 7000.0),
            ("ART-005", "ICE LIMONADA 500 ML X 12", 8000.0), ("ART-006", "ICE GRANADINA 500 ML X 12", 8000.0),
            ("ART-007", "ICE COLA 500ML X 12", 8000.0), ("ART-008", "ICE MANZANA 500 ML X12", 8000.0),
            ("ART-009", "REAKTOR 500 ML X 8", 14700.0), ("ART-010", "AGUA MARINARO 1,5 X 6", 6000.0)
        ]
        for cod, nom, pre in lista_productos_junio:
            db("INSERT INTO Productos (codigo_articulo, nombre_articulo, precio_unitario) VALUES (?, ?, ?)", (cod, nom, pre))

def formato_ars(numero): 
    return f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def formatear_fecha_archivo(fecha_str):
    try:
        dt = datetime.strptime(fecha_str, "%Y-%m-%d")
        return dt.strftime("%d-%m-%y")
    except:
        return datetime.now().strftime("%d-%m-%y")

# ==========================================
# 2. MOTORES DE REPORTES PDF
# ==========================================
def limpiar_texto(texto):
    return str(texto).encode('latin-1', 'replace').decode('latin-1')

def generar_pdf_facturas(ruta_destino, num_factura=None, fecha_consulta=None):
    from fpdf import FPDF 
    if num_factura: facturas = db("SELECT numero_factura FROM Facturas WHERE numero_factura = ?", (num_factura,), fetch=True, fetchall=True)
    elif fecha_consulta: facturas = db("SELECT numero_factura FROM Facturas WHERE fecha = ?", (fecha_consulta,), fetch=True, fetchall=True)
    else: return False
    
    if not facturas: return False
    
    pdf = FPDF(); pdf.alias_nb_pages() 
    for (f_id,) in facturas:
        factura = db('''SELECT f.numero_factura, f.fecha, c.nombre_apellido, c.direccion_entrega, f.total_a_pagar, f.preventista, c.numero_cliente FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente WHERE f.numero_factura = ?''', (f_id,), fetch=True)
        lineas = db('''SELECT COALESCE(d.nombre_personalizado, p.nombre_articulo), d.unidades, d.precio_unitario, d.total_linea FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo WHERE d.numero_factura = ?''', (f_id,), fetch=True, fetchall=True)
        
        pdf.add_page(); pdf.set_font("Arial", 'B', 18); pdf.cell(0, 10, limpiar_texto("Factura"), ln=1, align='C'); pdf.ln(10)
        pdf.set_font("Arial", '', 10); pdf.cell(0, 5, "xiaomideposito@gmail.com", ln=1, align='L'); pdf.ln(10)
        
        pdf.set_font("Arial", '', 10)
        pdf.set_x(30); pdf.cell(0, 5, limpiar_texto(factura[2]), ln=1)
        pdf.set_x(30)
        direccion_texto = limpiar_texto(factura[3] if factura[3] else "")
        pdf.multi_cell(150, 5, direccion_texto, align='L')
        pdf.ln(10)

        try:
            fecha_obj = datetime.strptime(factura[1], "%Y-%m-%d"); venc_fmt = (fecha_obj + timedelta(days=30)).strftime("%d/%m/%Y"); fecha_fmt = fecha_obj.strftime("%d/%m/%Y")
        except: fecha_fmt = factura[1]; venc_fmt = factura[1]

        pdf.set_fill_color(210, 210, 210); pdf.set_font("Arial", 'B', 9)
        pdf.cell(35, 8, limpiar_texto("Número de cliente"), border=1, align='C', fill=True); pdf.cell(35, 8, limpiar_texto("Número de factura"), border=1, align='C', fill=True); pdf.cell(25, 8, limpiar_texto("Página"), border=1, align='C', fill=True); pdf.cell(45, 8, limpiar_texto("Fecha de factura"), border=1, align='C', fill=True); pdf.cell(50, 8, limpiar_texto("Vencimiento"), border=1, ln=True, align='C', fill=True)
        pdf.set_font("Arial", '', 9)
        pdf.cell(35, 8, limpiar_texto(str(factura[6])), border=1, align='C'); pdf.cell(35, 8, limpiar_texto(str(factura[0])), border=1, align='C'); pdf.cell(25, 8, limpiar_texto(f"{pdf.page_no()} / {{nb}}"), border=1, align='C'); pdf.cell(45, 8, limpiar_texto(fecha_fmt), border=1, align='C'); pdf.cell(50, 8, limpiar_texto(venc_fmt), border=1, ln=True, align='C'); pdf.ln(15)
        
        pdf.set_fill_color(210, 210, 210); pdf.set_font("Arial", 'B', 9)
        pdf.cell(105, 8, limpiar_texto("Artículo"), border=1, align='L', fill=True); pdf.cell(25, 8, limpiar_texto("Cantidad"), border=1, align='R', fill=True); pdf.cell(30, 8, limpiar_texto("Precio"), border=1, align='R', fill=True); pdf.cell(30, 8, limpiar_texto("Importe total"), border=1, ln=True, align='R', fill=True)
        pdf.set_font("Arial", '', 9)
        for art, cant, pre, tot in lineas:
            cant_fmt = str(int(cant)) if cant == int(cant) else str(cant).replace('.', ',')
            pdf.cell(105, 8, limpiar_texto(str(art)[:60]), border='LR', align='L')
            pdf.cell(25, 8, limpiar_texto(cant_fmt), border='LR', align='R')
            pdf.cell(30, 8, limpiar_texto(formato_ars(pre)), border='LR', align='R')
            pdf.cell(30, 8, limpiar_texto(formato_ars(tot)), border='LR', ln=True, align='R')
            
        for _ in range(max(0, 18 - len(lineas))):
            pdf.cell(105, 8, "", border='LR', align='L'); pdf.cell(25, 8, "", border='LR', align='L'); pdf.cell(30, 8, "", border='LR', align='L'); pdf.cell(30, 8, "", border='LR', ln=True, align='L')
        
        pdf.cell(190, 0, "", border='T', ln=True); pdf.ln(2)
        pdf.set_x(140); pdf.set_font("Arial", 'B', 10); pdf.cell(25, 8, limpiar_texto("Importe total"), align='L'); pdf.cell(35, 8, limpiar_texto(f"$ {formato_ars(factura[4])}"), align='R', ln=True)
        pdf.set_y(-30); pdf.set_font("Arial", '', 10)
        pdf.cell(0, 5, limpiar_texto(f"Vendedor asignado: {factura[5] if len(factura)>5 else 'ADMIN'}"), ln=True, align='L')
    
    pdf.output(ruta_destino)
    return True

def generar_reporte_generico(ruta_destino, query, parametros, titulo, subtitulo):
    from fpdf import FPDF
    productos = db(query, parametros, fetch=True, fetchall=True)
    if not productos: return False
    pdf = FPDF(); pdf.add_page(); pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", 'B', 18); pdf.cell(190, 10, txt=limpiar_texto(titulo), ln=True, align='C')
    pdf.set_font("Arial", size=11); pdf.cell(190, 8, txt=limpiar_texto(subtitulo), ln=True, align='C'); pdf.ln(10)
    pdf.set_fill_color(210, 210, 210); pdf.set_font("Arial", 'B', 10)
    for col, w in [("Codigo", 25), ("Descripcion", 65), ("Precio Unit.", 30), ("Total Unid.", 30)]: pdf.cell(w, 10, limpiar_texto(col), border=1, align='C', fill=True)
    pdf.cell(40, 10, limpiar_texto("Total"), border=1, ln=True, align='C', fill=True)
    pdf.set_font("Arial", size=10); unidades_t, dinero_t = 0, 0
    for cod, nom, pre, uni, tot in productos:
        uni_fmt = str(int(uni)) if uni == int(uni) else str(uni).replace('.', ',')
        pdf.cell(25, 9, limpiar_texto(str(cod)), border='LR', align='C'); pdf.cell(65, 9, limpiar_texto(str(nom)), border='LR', align='C'); pdf.cell(30, 9, limpiar_texto(f"$ {formato_ars(pre)}"), border='LR', align='C'); pdf.cell(30, 9, limpiar_texto(uni_fmt), border='LR', align='C')
        pdf.cell(40, 9, limpiar_texto(f"$ {formato_ars(tot)}"), border='LR', ln=True, align='C')
        unidades_t += uni; dinero_t += tot
    pdf.cell(190, 0, "", border='T', ln=True); pdf.ln(5)
    
    uni_t_fmt = str(int(unidades_t)) if unidades_t == int(unidades_t) else str(unidades_t).replace('.', ',')
    pdf.set_font("Arial", 'B', 11); pdf.cell(120, 10, limpiar_texto("TOTAL GENERAL:"), border=1, align='R'); pdf.cell(30, 10, limpiar_texto(uni_t_fmt), border=1, align='C'); pdf.cell(40, 10, limpiar_texto(f"$ {formato_ars(dinero_t)}"), border=1, ln=True, align='C')
    pdf.output(ruta_destino); return True

def generar_reporte_preventistas(ruta_destino, f_inicio, f_fin):
    from fpdf import FPDF
    if f_inicio == f_fin:
        datos = db("SELECT preventista, COUNT(numero_factura), SUM(total_a_pagar) FROM Facturas WHERE fecha = ? GROUP BY preventista", (f_inicio,), fetch=True, fetchall=True)
        periodo = f"Fecha consultada: {f_inicio}"
    else:
        datos = db("SELECT preventista, COUNT(numero_factura), SUM(total_a_pagar) FROM Facturas WHERE fecha BETWEEN ? AND ? GROUP BY preventista", (f_inicio, f_fin), fetch=True, fetchall=True)
        periodo = f"Periodo: {f_inicio} al {f_fin}"

    if not datos: return False

    pdf = FPDF(); pdf.add_page(); pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 18); pdf.cell(190, 10, txt=limpiar_texto("RENDICION DE CAJA POR PREVENTISTA"), ln=True, align='C')
    pdf.set_font("Arial", size=11); pdf.cell(190, 8, txt=limpiar_texto(periodo), ln=True, align='C'); pdf.ln(10)

    pdf.set_fill_color(210, 210, 210); pdf.set_font("Arial", 'B', 12)
    pdf.cell(70, 10, limpiar_texto("Usuario / Vendedor"), border=1, align='C', fill=True)
    pdf.cell(50, 10, limpiar_texto("Tickets Emitidos"), border=1, align='C', fill=True)
    pdf.cell(70, 10, limpiar_texto("Total Recaudado"), border=1, ln=True, align='C', fill=True)

    pdf.set_font("Arial", size=11)
    total_tickets, total_dinero = 0, 0

    for prev, cant, tot in datos:
        nombre = str(prev) if prev else "ADMIN"
        pdf.cell(70, 10, limpiar_texto(nombre), border='LR', align='C')
        pdf.cell(50, 10, limpiar_texto(str(cant)), border='LR', align='C')
        pdf.cell(70, 10, limpiar_texto(f"$ {formato_ars(tot)}"), border='LR', ln=True, align='C')
        total_tickets += cant
        total_dinero += tot

    pdf.cell(190, 0, "", border='T', ln=True); pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(70, 10, limpiar_texto("TOTAL DE VENTAS:"), border=1, align='R')
    pdf.cell(50, 10, limpiar_texto(str(total_tickets)), border=1, align='C')
    pdf.cell(70, 10, limpiar_texto(f"$ {formato_ars(total_dinero)}"), border=1, ln=True, align='C')
    
    pdf.output(ruta_destino); return True

def generar_reporte_total_preventistas_fecha(ruta_destino, fecha_sel):
    """Genera el consolidado de TODOS los preventistas para una sola fecha.
    No utiliza page.session ni filtra por el usuario logueado.
    """
    return generar_reporte_preventistas(ruta_destino, fecha_sel, fecha_sel)


def generar_reporte_articulos_por_usuario_dia(ruta_destino, fecha_sel, usuario_sel):
    from fpdf import FPDF
    query = "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, SUM(d.unidades), SUM(d.total_linea) FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo JOIN Facturas f ON d.numero_factura = f.numero_factura WHERE f.fecha = ? AND f.preventista = ? GROUP BY d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario"
    params = (fecha_sel, usuario_sel)
    periodo = f"Usuario: {usuario_sel} | Fecha: {fecha_sel}"

    productos = db(query, params, fetch=True, fetchall=True)
    if not productos: return False

    pdf = FPDF(); pdf.add_page(); pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 18); pdf.cell(190, 10, txt=limpiar_texto("REPORTE DIARIO POR USUARIO"), ln=True, align='C')
    pdf.set_font("Arial", size=11); pdf.cell(190, 8, txt=limpiar_texto(periodo), ln=True, align='C'); pdf.ln(10)

    pdf.set_fill_color(210, 210, 210); pdf.set_font("Arial", 'B', 10)
    for col, w in [("Codigo", 25), ("Descripcion", 65), ("Precio Unit.", 30), ("Total Unid.", 30)]: pdf.cell(w, 10, limpiar_texto(col), border=1, align='C', fill=True)
    pdf.cell(40, 10, limpiar_texto("Total"), border=1, ln=True, align='C', fill=True)

    pdf.set_font("Arial", size=10); unidades_t, dinero_t = 0, 0
    for cod, nom, pre, uni, tot in productos:
        uni_fmt = str(int(uni)) if uni == int(uni) else str(uni).replace('.', ',')
        pdf.cell(25, 9, limpiar_texto(str(cod)), border='LR', align='C'); pdf.cell(65, 9, limpiar_texto(str(nom)), border='LR', align='C'); pdf.cell(30, 9, limpiar_texto(f"$ {formato_ars(pre)}"), border='LR', align='C'); pdf.cell(30, 9, limpiar_texto(uni_fmt), border='LR', align='C')
        pdf.cell(40, 9, limpiar_texto(f"$ {formato_ars(tot)}"), border='LR', ln=True, align='C')
        unidades_t += uni; dinero_t += tot

    pdf.cell(190, 0, "", border='T', ln=True); pdf.ln(5)
    uni_t_fmt = str(int(unidades_t)) if unidades_t == int(unidades_t) else str(unidades_t).replace('.', ',')
    pdf.set_font("Arial", 'B', 11); pdf.cell(120, 10, limpiar_texto("TOTAL GENERAL:"), border=1, align='R'); pdf.cell(30, 10, limpiar_texto(uni_t_fmt), border=1, align='C'); pdf.cell(40, 10, limpiar_texto(f"$ {formato_ars(dinero_t)}"), border=1, ln=True, align='C')
    pdf.output(ruta_destino); return True

def generar_reporte_articulos_por_usuario_rango(ruta_destino, f_inicio, f_fin, usuario_sel):
    from fpdf import FPDF
    query = "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, SUM(d.unidades), SUM(d.total_linea) FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo JOIN Facturas f ON d.numero_factura = f.numero_factura WHERE f.fecha BETWEEN ? AND ? AND f.preventista = ? GROUP BY d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario"
    params = (f_inicio, f_fin, usuario_sel)
    periodo = f"Usuario: {usuario_sel} | Periodo: {f_inicio} al {f_fin}"

    productos = db(query, params, fetch=True, fetchall=True)
    if not productos: return False

    pdf = FPDF(); pdf.add_page(); pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 18); pdf.cell(190, 10, txt=limpiar_texto("BALANCE CONSOLIDADO POR USUARIO"), ln=True, align='C')
    pdf.set_font("Arial", size=11); pdf.cell(190, 8, txt=limpiar_texto(periodo), ln=True, align='C'); pdf.ln(10)

    pdf.set_fill_color(210, 210, 210); pdf.set_font("Arial", 'B', 10)
    for col, w in [("Codigo", 25), ("Descripcion", 65), ("Precio Unit.", 30), ("Total Unid.", 30)]: pdf.cell(w, 10, limpiar_texto(col), border=1, align='C', fill=True)
    pdf.cell(40, 10, limpiar_texto("Total"), border=1, ln=True, align='C', fill=True)

    pdf.set_font("Arial", size=10); unidades_t, dinero_t = 0, 0
    for cod, nom, pre, uni, tot in productos:
        uni_fmt = str(int(uni)) if uni == int(uni) else str(uni).replace('.', ',')
        pdf.cell(25, 9, limpiar_texto(str(cod)), border='LR', align='C'); pdf.cell(65, 9, limpiar_texto(str(nom)), border='LR', align='C'); pdf.cell(30, 9, limpiar_texto(f"$ {formato_ars(pre)}"), border='LR', align='C'); pdf.cell(30, 9, limpiar_texto(uni_fmt), border='LR', align='C')
        pdf.cell(40, 9, limpiar_texto(f"$ {formato_ars(tot)}"), border='LR', ln=True, align='C')
        unidades_t += uni; dinero_t += tot

    pdf.cell(190, 0, "", border='T', ln=True); pdf.ln(5)
    uni_t_fmt = str(int(unidades_t)) if unidades_t == int(unidades_t) else str(unidades_t).replace('.', ',')
    pdf.set_font("Arial", 'B', 11); pdf.cell(120, 10, limpiar_texto("TOTAL GENERAL:"), border=1, align='R'); pdf.cell(30, 10, limpiar_texto(uni_t_fmt), border=1, align='C'); pdf.cell(40, 10, limpiar_texto(f"$ {formato_ars(dinero_t)}"), border=1, ln=True, align='C')
    pdf.output(ruta_destino); return True

def generar_reporte_clientes_dia(ruta_destino, f_consulta):
    from fpdf import FPDF
    datos = db("SELECT c.nombre_apellido, c.direccion_entrega, SUM(f.total_a_pagar) FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente WHERE f.fecha = ? GROUP BY c.numero_cliente", (f_consulta,), fetch=True, fetchall=True)
    
    if not datos: return False

    pdf = FPDF(); pdf.add_page(); pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 18); pdf.cell(190, 10, txt=limpiar_texto("LISTADO DE COBRANZA DIARIA"), ln=True, align='C')
    pdf.set_font("Arial", size=11); pdf.cell(190, 8, txt=limpiar_texto(f"Fecha: {f_consulta}"), ln=True, align='C'); pdf.ln(10)

    pdf.set_fill_color(210, 210, 210); pdf.set_font("Arial", 'B', 11)
    pdf.cell(150, 10, limpiar_texto(" Cliente y Dirección"), border=1, align='L', fill=True)
    pdf.cell(40, 10, limpiar_texto("Total a Cobrar"), border=1, ln=True, align='C', fill=True)

    total_dinero = 0

    for cli, direc, tot in datos:
        dir_str = direc if direc else "Sin dirección"
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(150, 7, limpiar_texto(f" {str(cli)[:75]}"), border='L', align='L')
        pdf.cell(40, 7, limpiar_texto(f"$ {formato_ars(tot)}"), border='R', ln=True, align='C')
        pdf.set_font("Arial", '', 9)
        pdf.cell(150, 7, limpiar_texto(f" Dir: {str(dir_str)[:90]}"), border='LB', align='L')
        pdf.cell(40, 7, "", border='RB', ln=True) 
        total_dinero += tot

    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(150, 10, limpiar_texto("TOTAL A COBRAR EN LA CALLE:"), border=1, align='R')
    pdf.cell(40, 10, limpiar_texto(f"$ {formato_ars(total_dinero)}"), border=1, ln=True, align='C')
    pdf.output(ruta_destino); return True

# ==========================================
# 3. SISTEMA VISUAL Y COMPONENTES UI
# ==========================================
COLORES = {
    "primary": "#263238",
    "secondary": "#00838F",
    "accent": "#FF8F00",
    "info": "#1976D2",
    "warning": "#EF6C00",
    "danger": "#C62828",
    "success": "#2E7D32",
    "background": "#F4F6F8",
    "surface": "#FFFFFF",
    "border": "#E0E0E0",
    "muted": "#607D8B",
    "text": "#263238",
}

def ui_card(content, padding=18):
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=COLORES["surface"],
        border_radius=12,
        border=ft.border.all(1, COLORES["border"]),
    )

def ui_boton(texto, icono, accion, color=None):
    return ft.ElevatedButton(
        texto,
        icon=icono,
        on_click=accion,
        style=ft.ButtonStyle(
            bgcolor=color or COLORES["primary"],
            color="white",
            padding=16,
        ),
    )

# ==========================================
# 4. INTERFAZ GRÁFICA UNIVERSAL
# ==========================================
def main(page: ft.Page):
    try:
        page.title = "XIOMI Distribuidora | Gestión Comercial B3"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = COLORES["background"]
        page.padding = 0
        page.scroll = ft.ScrollMode.AUTO
        page.fonts = {"Inter": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"}
        page.theme = ft.Theme(font_family="Inter")
        try:
            page.window_min_width = 900
            page.window_min_height = 650
        except Exception:
            pass
        inicializar_base_datos()
        
        carrito = {}
        estado_carrito = {"editando": False, "id_factura": None, "cargado": False}

        def cambiar_pantalla(e):
            try:
                page.views.clear()
                usuario_actual = page.session.get("usuario")
                
                if not usuario_actual and page.route != "/login":
                    page.views.append(ft.View("/cargando", [ft.Text("Redirigiendo...", size=20)]))
                    page.go("/login")
                    return

                if page.route == "/login":
                    inp_user = ft.TextField(label="Usuario (Ej: ABR012026)", width=300)
                    inp_pin = ft.TextField(label="PIN (Ej: 1111)", password=True, can_reveal_password=True, width=300)
                    
                    def ingresar(e):
                        vendedor = db("SELECT nombre FROM Preventistas WHERE nombre=? AND pin=?", (inp_user.value.strip().upper(), inp_pin.value.strip()), fetch=True)
                        if vendedor:
                            page.session.set("usuario", vendedor[0])
                            page.go("/")
                        else:
                            page.snack_bar = ft.SnackBar(ft.Text("Usuario o PIN incorrectos", color="white"), bgcolor="red")
                            page.snack_bar.open = True; page.update()

                    page.views.append(ft.View("/login", [
                        ft.Container(height=50),
                        ft.Icon("storefront", size=80, color="#212121"),
                        ft.Text("XIOMI Distribuidora", size=30, weight="bold", color="#212121"),
                        ft.Text("Acceso al Sistema", size=16),
                        ft.Container(height=20),
                        inp_user, inp_pin,
                        ft.ElevatedButton("INGRESAR", icon="login", on_click=ingresar, style=ft.ButtonStyle(bgcolor="#424242", color="white", padding=20), width=300)
                    ], horizontal_alignment="center"))

                elif page.route == "/":
                    # ==========================================================
                    # DASHBOARD B3 — CENTRO DE CONTROL COMERCIAL
                    # ==========================================================
                    def salir(e):
                        page.session.clear()
                        page.go("/login")

                    hoy = date.today().strftime("%Y-%m-%d")
                    mes_actual = date.today().strftime("%Y-%m")

                    # Indicadores globales: no dependen del usuario logueado.
                    ventas_hoy = db(
                        "SELECT COALESCE(SUM(total_a_pagar),0) FROM Facturas WHERE fecha=?",
                        (hoy,), fetch=True
                    )[0] or 0
                    tickets_hoy = db(
                        "SELECT COUNT(*) FROM Facturas WHERE fecha=?",
                        (hoy,), fetch=True
                    )[0] or 0
                    ventas_mes = db(
                        "SELECT COALESCE(SUM(total_a_pagar),0) FROM Facturas WHERE substr(fecha,1,7)=?",
                        (mes_actual,), fetch=True
                    )[0] or 0
                    clientes_total = db("SELECT COUNT(*) FROM Clientes", fetch=True)[0] or 0
                    productos_total = db("SELECT COUNT(*) FROM Productos", fetch=True)[0] or 0

                    def moneda(v):
                        return f"$ {formato_ars(v or 0)}"

                    def kpi(icono, titulo, valor, detalle, color):
                        return ft.Container(
                            col={"xs": 12, "sm": 6, "md": 3},
                            content=ft.Container(
                                padding=18,
                                bgcolor="white",
                                border_radius=16,
                                border=ft.border.all(1, COLORES["border"]),
                                shadow=ft.BoxShadow(
                                    spread_radius=0,
                                    blur_radius=12,
                                    color="#18000000",
                                    offset=ft.Offset(0, 3),
                                ),
                                content=ft.Row([
                                    ft.Container(
                                        width=46, height=46,
                                        bgcolor=color,
                                        border_radius=12,
                                        alignment=ft.alignment.center,
                                        content=ft.Icon(icono, color="white", size=23),
                                    ),
                                    ft.Column([
                                        ft.Text(titulo.upper(), size=10, color=COLORES["muted"],
                                                weight=ft.FontWeight.W_600),
                                        ft.Text(valor, size=21, weight=ft.FontWeight.BOLD,
                                                color=COLORES["text"]),
                                        ft.Text(detalle, size=10, color=COLORES["muted"]),
                                    ], spacing=2, expand=True),
                                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            ),
                        )

                    def modulo(icono, titulo, descripcion, ruta, color):
                        return ft.Container(
                            col={"xs": 12, "sm": 6, "lg": 4},
                            content=ft.Container(
                                padding=18,
                                bgcolor="white",
                                border_radius=16,
                                border=ft.border.all(1, COLORES["border"]),
                                ink=True,
                                on_click=lambda e, r=ruta: page.go(r),
                                shadow=ft.BoxShadow(
                                    spread_radius=0,
                                    blur_radius=8,
                                    color="#12000000",
                                    offset=ft.Offset(0, 2),
                                ),
                                content=ft.Row([
                                    ft.Container(
                                        width=50, height=50,
                                        bgcolor=color,
                                        border_radius=14,
                                        alignment=ft.alignment.center,
                                        content=ft.Icon(icono, color="white", size=25),
                                    ),
                                    ft.Column([
                                        ft.Text(titulo, size=14, weight=ft.FontWeight.BOLD,
                                                color=COLORES["text"]),
                                        ft.Text(descripcion, size=10, color=COLORES["muted"]),
                                    ], spacing=3, expand=True),
                                    ft.Icon("chevron_right", color=COLORES["muted"], size=20),
                                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            ),
                        )

                    # Rendimiento del día por preventista.
                    ranking = db(
                        """SELECT COALESCE(preventista,'SIN ASIGNAR'),
                                  COUNT(*), COALESCE(SUM(total_a_pagar),0)
                           FROM Facturas
                           WHERE fecha=?
                           GROUP BY preventista
                           ORDER BY SUM(total_a_pagar) DESC""",
                        (hoy,), fetch=True, fetchall=True
                    )

                    filas_ranking = []
                    for prev, tickets, total in ranking[:8]:
                        filas_ranking.append(
                            ft.DataRow(cells=[
                                ft.DataCell(ft.Text(str(prev))),
                                ft.DataCell(ft.Text(str(tickets), text_align=ft.TextAlign.CENTER)),
                                ft.DataCell(ft.Text(moneda(total), weight=ft.FontWeight.W_600)),
                            ])
                        )

                    tabla_ranking = ft.DataTable(
                        column_spacing=28,
                        heading_row_height=38,
                        data_row_min_height=38,
                        data_row_max_height=44,
                        columns=[
                            ft.DataColumn(ft.Text("PREVENTISTA", size=10, weight=ft.FontWeight.BOLD)),
                            ft.DataColumn(ft.Text("TICKETS", size=10, weight=ft.FontWeight.BOLD)),
                            ft.DataColumn(ft.Text("VENTAS", size=10, weight=ft.FontWeight.BOLD)),
                        ],
                        rows=filas_ranking,
                    )

                    recientes = db(
                        """SELECT f.numero_factura, f.fecha,
                                  COALESCE(c.nombre_apellido,'CONSUMIDOR FINAL'),
                                  COALESCE(f.preventista,'SIN ASIGNAR'),
                                  f.total_a_pagar
                           FROM Facturas f
                           LEFT JOIN Clientes c ON c.numero_cliente=f.numero_cliente
                           ORDER BY f.numero_factura DESC LIMIT 6""",
                        fetch=True, fetchall=True
                    )

                    def tarjeta_venta(num, fecha_v, cliente, prev, total):
                        return ft.Container(
                            padding=10,
                            border=ft.border.only(bottom=ft.BorderSide(1, COLORES["border"])),
                            content=ft.Row([
                                ft.Container(
                                    width=38, height=38,
                                    bgcolor="#ECEFF1",
                                    border_radius=10,
                                    alignment=ft.alignment.center,
                                    content=ft.Text(str(num), size=10, weight=ft.FontWeight.BOLD),
                                ),
                                ft.Column([
                                    ft.Text(str(cliente), size=12, weight=ft.FontWeight.W_600),
                                    ft.Text(f"{fecha_v}  •  {prev}", size=9, color=COLORES["muted"]),
                                ], spacing=2, expand=True),
                                ft.Text(moneda(total), size=12, weight=ft.FontWeight.BOLD),
                            ])
                        )

                    lista_recientes = ft.Column(
                        [tarjeta_venta(*r) for r in recientes] or
                        [ft.Container(
                            padding=20,
                            content=ft.Text("Todavía no hay ventas registradas.", color=COLORES["muted"])
                        )],
                        spacing=0,
                    )

                    encabezado = ft.Container(
                        padding=ft.padding.symmetric(horizontal=24, vertical=18),
                        bgcolor=COLORES["primary"],
                        content=ft.Row([
                            ft.Container(
                                width=44, height=44,
                                bgcolor=COLORES["secondary"],
                                border_radius=12,
                                alignment=ft.alignment.center,
                                content=ft.Icon("storefront", color="white", size=24),
                            ),
                            ft.Column([
                                ft.Text("XIOMI DISTRIBUIDORA", size=19,
                                        weight=ft.FontWeight.BOLD, color="white"),
                                ft.Text("Sistema de Gestión Comercial • B3",
                                        size=10, color="#CFD8DC"),
                            ], spacing=2, expand=True),
                            ft.Column([
                                ft.Text(f"USUARIO  {usuario_actual}", size=9,
                                        color="#B0BEC5", text_align=ft.TextAlign.RIGHT),
                                ft.Text(datetime.now().strftime("%d/%m/%Y"),
                                        size=11, weight=ft.FontWeight.W_600, color="white",
                                        text_align=ft.TextAlign.RIGHT),
                            ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END),
                            ft.IconButton(
                                "logout",
                                icon_color="white",
                                tooltip="Cerrar sesión",
                                on_click=salir,
                            ),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    )

                    contenido = ft.Container(
                        padding=24,
                        content=ft.Column([
                            ft.Row([
                                ft.Column([
                                    ft.Text("Centro de Control", size=24,
                                            weight=ft.FontWeight.BOLD, color=COLORES["text"]),
                                    ft.Text(
                                        f"Resumen operativo del {datetime.now().strftime('%d/%m/%Y')}",
                                        size=11, color=COLORES["muted"]
                                    ),
                                ], spacing=3, expand=True),
                                ft.ElevatedButton(
                                    "NUEVA VENTA",
                                    icon="add_shopping_cart",
                                    on_click=lambda e: page.go("/carrito"),
                                    style=ft.ButtonStyle(
                                        bgcolor=COLORES["accent"],
                                        color="white",
                                        padding=ft.padding.symmetric(horizontal=18, vertical=13),
                                        shape=ft.RoundedRectangleBorder(radius=10),
                                    ),
                                ),
                            ]),
                            ft.Container(height=4),
                            ft.ResponsiveRow([
                                kpi("payments", "Ventas de hoy", moneda(ventas_hoy),
                                    f"{tickets_hoy} tickets", COLORES["success"]),
                                kpi("receipt_long", "Tickets", str(tickets_hoy),
                                    "operaciones del día", COLORES["info"]),
                                kpi("trending_up", "Ventas del mes", moneda(ventas_mes),
                                    "acumulado mensual", COLORES["accent"]),
                                kpi("people", "Clientes", str(clientes_total),
                                    f"{productos_total} productos", COLORES["secondary"]),
                            ], spacing=12, run_spacing=12),
                            ft.Container(height=6),
                            ft.Text("Operaciones", size=17, weight=ft.FontWeight.BOLD),
                            ft.ResponsiveRow([
                                modulo("point_of_sale", "Ventas", "Pedidos, edición e impresión.",
                                       "/pedidos_dia", COLORES["primary"]),
                                modulo("people", "Clientes", "Directorio y gestión comercial.",
                                       "/agregar_cliente", COLORES["secondary"]),
                                modulo("inventory_2", "Productos", "Catálogo, precios y artículos.",
                                       "/agregar_producto", COLORES["accent"]),
                                modulo("swap_horiz", "Reasignar tickets", "Control de preventistas.",
                                       "/reasignar_tickets", COLORES["info"]),
                                modulo("bar_chart", "Reportes", "Balances, PDF y rendiciones.",
                                       "/reportes", COLORES["warning"]),
                                modulo("cloud_upload", "Carga inteligente", "Importación y procesamiento.",
                                       "/carga_inteligente", COLORES["success"]),
                            ], spacing=12, run_spacing=12),
                            ft.Container(height=6),
                            ft.ResponsiveRow([
                                ft.Container(
                                    col={"xs": 12, "lg": 6},
                                    content=ui_card(
                                        ft.Column([
                                            ft.Row([
                                                ft.Column([
                                                    ft.Text("Rendimiento por preventista",
                                                            size=14, weight=ft.FontWeight.BOLD),
                                                    ft.Text("Ventas acumuladas de hoy",
                                                            size=10, color=COLORES["muted"]),
                                                ], spacing=2, expand=True),
                                                ft.Icon("leaderboard", color=COLORES["secondary"]),
                                            ]),
                                            ft.Container(
                                                content=ft.Row([tabla_ranking], scroll=ft.ScrollMode.AUTO),
                                                margin=ft.margin.only(top=8),
                                            ),
                                        ], spacing=8),
                                        padding=16,
                                    )
                                ),
                                ft.Container(
                                    col={"xs": 12, "lg": 6},
                                    content=ui_card(
                                        ft.Column([
                                            ft.Row([
                                                ft.Column([
                                                    ft.Text("Últimas operaciones",
                                                            size=14, weight=ft.FontWeight.BOLD),
                                                    ft.Text("Actividad comercial reciente",
                                                            size=10, color=COLORES["muted"]),
                                                ], spacing=2, expand=True),
                                                ft.Icon("history", color=COLORES["secondary"]),
                                            ]),
                                            lista_recientes,
                                        ], spacing=8),
                                        padding=16,
                                    )
                                ),
                            ], spacing=12, run_spacing=12),
                            ft.Container(height=8),
                            ft.Text(
                                "XIOMI • Gestión comercial B3",
                                size=9, color=COLORES["muted"],
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ], spacing=12),
                    )

                    page.views.append(ft.View(
                        "/",
                        [encabezado, ft.Container(content=contenido, expand=True)],
                        padding=0,
                        scroll=ft.ScrollMode.AUTO,
                    ))

                elif page.route == "/reasignar_tickets":
                    tabla_reasignar = ft.DataTable(columns=[
                        ft.DataColumn(ft.Text("Nro", weight="bold")),
                        ft.DataColumn(ft.Text("Fecha", weight="bold")),
                        ft.DataColumn(ft.Text("Cliente", weight="bold")),
                        ft.DataColumn(ft.Text("Preventista Actual", weight="bold")),
                        ft.DataColumn(ft.Text("Cambiar a:", weight="bold")),
                        ft.DataColumn(ft.Text("Acción", weight="bold")),
                    ], rows=[])

                    lista_preventistas_bd = [r[0] for r in db("SELECT DISTINCT nombre FROM Preventistas", fetch=True, fetchall=True)]
                    if not lista_preventistas_bd: lista_preventistas_bd = ["ADMIN"]

                    def cargar_tickets_reasignar():
                        try:
                            tabla_reasignar.rows.clear()
                            filas = db("SELECT f.numero_factura, f.fecha, c.nombre_apellido, f.preventista FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente ORDER BY f.numero_factura DESC LIMIT 50", fetch=True, fetchall=True)
                            if filas:
                                for num_fac, fec, nom_cli, prev_actual in filas:
                                    dd_nuevo_prev = ft.Dropdown(
                                        options=[ft.dropdown.Option(text=u) for u in lista_preventistas_bd],
                                        value=prev_actual if prev_actual in lista_preventistas_bd else lista_preventistas_bd[0],
                                        width=150
                                    )
                                    
                                    def hacer_cambio(n_f=num_fac, d_p=dd_nuevo_prev):
                                        def guardar_click(e):
                                            nuevo_vendedor = d_p.value
                                            db("UPDATE Facturas SET preventista = ? WHERE numero_factura = ?", (nuevo_vendedor, n_f))
                                            page.snack_bar = ft.SnackBar(ft.Text(f"✅ Factura #{n_f} reasignada a {nuevo_vendedor}", color="white"), bgcolor="green")
                                            page.snack_bar.open = True
                                            cargar_tickets_reasignar()
                                        return guardar_click

                                    btn_guardar_cambio = ft.ElevatedButton("Guardar", icon="save", bgcolor="green", color="white", on_click=hacer_cambio(num_fac, dd_nuevo_prev))

                                    tabla_reasignar.rows.append(ft.DataRow(cells=[
                                        ft.DataCell(ft.Text(str(num_fac))),
                                        ft.DataCell(ft.Text(str(fec))),
                                        ft.DataCell(ft.Text(str(nom_cli))),
                                        ft.DataCell(ft.Text(str(prev_actual if prev_actual else "ADMIN"))),
                                        ft.DataCell(dd_nuevo_prev),
                                        ft.DataCell(btn_guardar_cambio),
                                    ]))
                            tabla_reasignar.update()
                        except Exception as ex:
                            print("Error al cargar tickets:", ex)

                    page.views.append(ft.View("/reasignar_tickets", [
                        ft.AppBar(title=ft.Text("Reasignar Tickets a Preventistas"), bgcolor="#00838F", color="white", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/"))),
                        ft.Text("Modificá el preventista de las últimas 50 facturas emitidas:", weight="bold", size=16),
                        ft.Divider(),
                        ft.Column([tabla_reasignar], scroll="auto", expand=True)
                    ], padding=20))
                    cargar_tickets_reasignar()

                elif page.route == "/pedidos_dia":
                    hoy = date.today().strftime("%Y-%m-%d")
                    
                    vista_modelo_factura = ft.Column([
                        ft.Icon("receipt_long", size=50, color="grey"),
                        ft.Text("Seleccioná una factura de la izquierda\npara ver su detalle y controlarla.", italic=True, color="grey", text_align="center")
                    ], alignment="center", horizontal_alignment="center", expand=True)

                    card_modelo_derecho = ft.Card(
                        color="#fafafa",
                        content=ft.Container(
                            padding=20,
                            content=ft.Column([
                                ft.Row([ft.Icon("visibility"), ft.Text("Modelo de Factura / Control", weight="bold", size=18)]),
                                ft.Divider(),
                                vista_modelo_factura
                            ], expand=True)
                        ),
                        expand=4
                    )

                    tabla_pedidos = ft.DataTable(columns=[ft.DataColumn(ft.Text(c, weight="bold")) for c in ["Nro", "Fecha", "Cliente", "Total", "Acciones"]], rows=[])

                    def mostrar_modelo_factura(id_fac):
                        try:
                            factura = db('''SELECT f.numero_factura, f.fecha, c.nombre_apellido, c.direccion_entrega, f.total_a_pagar, f.preventista, c.numero_cliente 
                                          FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente 
                                          WHERE f.numero_factura = ?''', (id_fac,), fetch=True)
                            lineas = db('''SELECT COALESCE(d.nombre_personalizado, p.nombre_articulo), d.unidades, d.precio_unitario, d.total_linea 
                                           FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo 
                                           WHERE d.numero_factura = ?''', (id_fac,), fetch=True, fetchall=True)
                            
                            if not factura: return

                            try:
                                fecha_obj = datetime.strptime(factura[1], "%Y-%m-%d")
                                venc_fmt = (fecha_obj + timedelta(days=30)).strftime("%d/%m/%Y")
                                fecha_fmt = fecha_obj.strftime("%d/%m/%Y")
                            except: 
                                fecha_fmt = factura[1]; venc_fmt = factura[1]

                            filas_items = []
                            for art, cant, pre, tot in lineas:
                                cant_fmt = str(int(cant)) if cant == int(cant) else str(cant).replace('.', ',')
                                filas_items.append(ft.DataRow(cells=[
                                    ft.DataCell(ft.Text(str(art)[:35], size=11)),
                                    ft.DataCell(ft.Text(cant_fmt, size=11)),
                                    ft.DataCell(ft.Text(f"${formato_ars(pre)}", size=11)),
                                    ft.DataCell(ft.Text(f"${formato_ars(tot)}", size=11)),
                                ]))

                            tabla_items_preview = ft.DataTable(
                                columns=[
                                    ft.DataColumn(ft.Text("Art.", size=11, weight="bold")),
                                    ft.DataColumn(ft.Text("Cant.", size=11, weight="bold")),
                                    ft.DataColumn(ft.Text("Precio", size=11, weight="bold")),
                                    ft.DataColumn(ft.Text("Total", size=11, weight="bold")),
                                ],
                                rows=filas_items,
                                heading_row_height=30,
                                data_row_min_height=30,
                                data_row_max_height=35
                            )

                            def imprimir_este(_):
                                fecha_fac = factura[1]
                                fecha_fmt_archivo = formatear_fecha_archivo(fecha_fac)
                                nombre_archivo = f"Reporte_factura_{fecha_fmt_archivo}.pdf"
                                ruta_completa = os.path.join(carpeta_assets, nombre_archivo)
                                if generar_pdf_facturas(ruta_completa, num_factura=id_fac):
                                    abrir_archivo_local(ruta_completa)

                            vista_modelo_factura.controls.clear()
                            vista_modelo_factura.controls.extend([
                                ft.Row([
                                    ft.Text(f"FACTURA #{factura[0]}", weight="bold", size=16, color="#00838F"),
                                    ft.ElevatedButton("Ver PDF", icon="picture_as_pdf", bgcolor="#FF8F00", color="white", on_click=imprimir_este, height=30)
                                ], alignment="space_between"),
                                ft.Divider(),
                                ft.Text(f"Cliente: {factura[2]} (ID: {factura[6]})", size=13, weight="bold"),
                                ft.Text(f"Dirección: {factura[3] if factura[3] else 'Sin dirección'}", size=12),
                                ft.Text(f"Fecha: {fecha_fmt} | Venc.: {venc_fmt}", size=12),
                                ft.Text(f"Vendedor: {factura[5] if factura[5] else 'ADMIN'}", size=12, italic=True),
                                ft.Divider(),
                                ft.Text("Detalle de Artículos:", weight="bold", size=12),
                                ft.Container(
                                    content=ft.Column([tabla_items_preview], scroll="auto"),
                                    height=180,
                                    border=ft.border.all(1, "grey400"),
                                    border_radius=5,
                                    padding=5
                                ),
                                ft.Container(height=10),
                                ft.Row([
                                    ft.Text("TOTAL A PAGAR:", weight="bold", size=14),
                                    ft.Text(f"$ {formato_ars(factura[4])}", weight="bold", size=16, color="green")
                                ], alignment="space_between")
                            ])
                            page.update()
                        except Exception as ex:
                            print("Error cargando modelo de factura:", ex)

                    def ref_pedidos():
                        try:
                            tabla_pedidos.rows.clear()
                            filas = db("""
                                SELECT f.numero_factura, f.fecha, c.nombre_apellido, f.total_a_pagar 
                                FROM Facturas f 
                                JOIN Clientes c ON f.numero_cliente = c.numero_cliente 
                                WHERE f.fecha = ?
                                ORDER BY f.numero_factura DESC
                            """, (hoy,), fetch=True, fetchall=True)
                            
                            if filas:
                                for id_f, fec, cli, tot in filas:
                                    def crear_borrar_p(num_b=id_f):
                                        def eliminar(_):
                                            def ejecutar():
                                                ejecutar_transaccion([
                                                    ("DELETE FROM Detalle_Factura WHERE numero_factura=?", (num_b,)),
                                                    ("DELETE FROM Facturas WHERE numero_factura=?", (num_b,)),
                                                ])
                                                ref_pedidos()
                                            dialogo = ft.AlertDialog(
                                                modal=True,
                                                title=ft.Text("Eliminar factura", weight="bold"),
                                                content=ft.Text(f"Se eliminará la factura #{num_b} y sus detalles. Esta acción no se puede deshacer."),
                                                actions=[
                                                    ft.TextButton("Cancelar", on_click=lambda _: (setattr(page.dialog, "open", False), page.update())),
                                                    ft.ElevatedButton("Eliminar", bgcolor=COLORES["danger"], color="white", on_click=lambda _: (setattr(page.dialog, "open", False), ejecutar(), page.update())),
                                                ],
                                            )
                                            page.dialog = dialogo; dialogo.open = True; page.update()
                                        return eliminar
                                    def crear_editar_p(num_e=id_f): return lambda _: (estado_carrito.update({"editando": True, "id_factura": num_e, "cargado": False}), carrito.clear(), page.go("/carrito"))
                                    def crear_seleccionar_p(num_s=id_f): return lambda _: mostrar_modelo_factura(num_s)

                                    tabla_pedidos.rows.append(ft.DataRow(
                                        on_select_changed=crear_seleccionar_p(id_f),
                                        cells=[
                                            ft.DataCell(ft.Text(str(id_f))), 
                                            ft.DataCell(ft.Text(fec)), 
                                            ft.DataCell(ft.Text(cli)), 
                                            ft.DataCell(ft.Text(f"${formato_ars(tot)}")), 
                                            ft.DataCell(ft.Row([
                                                ft.IconButton("visibility", icon_color="green", tooltip="Ver Modelo", on_click=crear_seleccionar_p(id_f)),
                                                ft.IconButton("edit", icon_color="blue", tooltip="Editar", on_click=crear_editar_p(id_f)), 
                                                ft.IconButton("delete", icon_color="red", tooltip="Eliminar", on_click=crear_borrar_p(id_f))
                                            ]))
                                        ]
                                    ))
                                tabla_pedidos.update()
                            else:
                                tabla_pedidos.rows.clear()
                                tabla_pedidos.update()
                        except: pass
                    
                    btn_armar_manual = ft.ElevatedButton("+ ARMAR NUEVO PEDIDO", icon="add_shopping_cart", on_click=lambda _: (estado_carrito.update({"editando": False, "id_factura": None, "cargado": False}), carrito.clear(), page.go("/carrito")), style=ft.ButtonStyle(bgcolor="#424242", color="white", padding=20), expand=True)
                    btn_armar_ia = ft.ElevatedButton("CARGA INTELIGENTE (IA) ⚡", icon="auto_fix_high", on_click=lambda _: page.go("/carga_inteligente"), style=ft.ButtonStyle(bgcolor="#00838F", color="white", padding=20), expand=True)

                    panel_tabla_izq = ft.Card(
                        content=ft.Container(
                            padding=10,
                            content=ft.Column([
                                ft.Text(f"Facturas emitidas hoy ({hoy}):", weight="bold"),
                                ft.Column([tabla_pedidos], scroll="auto", expand=True)
                            ], expand=True)
                        ),
                        expand=7
                    )

                    page.views.append(ft.View("/pedidos_dia", [
                        ft.AppBar(title=ft.Text("Registro de Ventas y Control"), bgcolor=COLORES["primary"], color="white", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/"))), 
                        ft.Row([btn_armar_manual, btn_armar_ia]), 
                        ft.Divider(), 
                        ft.Row([panel_tabla_izq, card_modelo_derecho], expand=True, vertical_alignment=ft.CrossAxisAlignment.START)
                    ], padding=20)); ref_pedidos()

                elif page.route == "/carrito":
                    texto_total = ft.Text("TOTAL: $ 0.00", size=24, weight="bold", color="white")
                    lista_carrito_ui = ft.Column(scroll="auto", expand=True)
                    
                    clientes_db = db("SELECT nombre_apellido, direccion_entrega FROM Clientes", fetch=True, fetchall=True)
                    todos_los_clientes = [f"{c[0]} ({c[1] if c[1] else 'Sin dirección'})" for c in clientes_db]
                    
                    def recargar_catalogo():
                        nonlocal cat
                        cat = {cod: {"nombre": nom, "precio": pre} for cod, nom, pre in db("SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos", fetch=True, fetchall=True)}
                        dd_productos.options = [ft.dropdown.Option(key=cod, text=f"{v['nombre']} | ${formato_ars(v['precio'])}") for cod, v in cat.items()]
                        page.update()

                    cat = {cod: {"nombre": nom, "precio": pre} for cod, nom, pre in db("SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos", fetch=True, fetchall=True)}
                    
                    inp_dir_factura = ft.TextField(label="Dirección de Entrega (Editable)", expand=2)
                    
                    def actualizar_direccion(e=None):
                        if dd_clientes.value:
                            nombre_limpio = dd_clientes.value.split(" (")[0]
                            dir_actual = db("SELECT direccion_entrega FROM Clientes WHERE nombre_apellido = ?", (nombre_limpio,), fetch=True)
                            if dir_actual and dir_actual[0]:
                                inp_dir_factura.value = dir_actual[0]
                            else:
                                inp_dir_factura.value = ""
                        else:
                            inp_dir_factura.value = ""
                        page.update()

                    def filtrar_clientes(e):
                        busqueda = buscador_cli.value.upper()
                        coincidencias = [c for c in todos_los_clientes if busqueda in c.upper()]
                        dd_clientes.options = [ft.dropdown.Option(text=c) for c in coincidencias]
                        if busqueda and len(coincidencias) > 0:
                            dd_clientes.value = coincidencias[0]
                        else:
                            dd_clientes.value = None
                        actualizar_direccion()

                    def filtrar_productos(e):
                        busqueda = buscador_prod.value.upper()
                        coincidencias = [(cod, v) for cod, v in cat.items() if busqueda in v['nombre'].upper() or busqueda in cod.upper()]
                        dd_productos.options = [ft.dropdown.Option(key=c_cod, text=f"{c_v['nombre']} | ${formato_ars(c_v['precio'])}") for c_cod, c_v in coincidencias]
                        if busqueda and len(coincidencias) > 0:
                            dd_productos.value = coincidencias[0][0]
                            cod_encontrado = coincidencias[0][0]
                            inp_precio.value = str(cat[cod_encontrado]['precio'])
                            inp_desc_item.value = str(cat[cod_encontrado]['nombre'])
                        else:
                            dd_productos.value = None
                            inp_precio.value = ""
                            inp_desc_item.value = ""
                        page.update()

                    def al_cambiar_producto(e):
                        if dd_productos.value and dd_productos.value in cat:
                            inp_precio.value = str(cat[dd_productos.value]['precio'])
                            inp_desc_item.value = str(cat[dd_productos.value]['nombre'])
                            page.update()

                    buscador_cli = ft.TextField(label="🔍 Buscar Cliente o Dirección...", on_change=filtrar_clientes, expand=1)
                    dd_clientes = ft.Dropdown(label="Seleccionar Cliente", options=[ft.dropdown.Option(text=c) for c in todos_los_clientes], expand=2, on_change=actualizar_direccion)
                    
                    buscador_prod = ft.TextField(label="🔍 Buscar Producto...", on_change=filtrar_productos, expand=1)
                    dd_productos = ft.Dropdown(label="Seleccionar Artículo", options=[ft.dropdown.Option(key=cod, text=f"{v['nombre']} | ${formato_ars(v['precio'])}") for cod, v in cat.items()], expand=2, on_change=al_cambiar_producto)
                    
                    inp_fecha_factura = ft.TextField(label="Fecha (YYYY-MM-DD)", value=date.today().strftime("%Y-%m-%d"), expand=1)
                    inp_cant = ft.TextField(label="Cant.", keyboard_type="text", width=90)
                    inp_precio = ft.TextField(label="Precio Unit. ($)", keyboard_type="number", width=120)
                    inp_desc_item = ft.TextField(label="Descripción / Sabor en Ticket", expand=2)

                    # Función para autocalcular el siguiente código correlativo (Ej: ART-011, ART-012, etc.)
                    def generar_siguiente_codigo():
                        try:
                            # Buscamos todos los códigos que sigan el formato ART-XXX o códigos numéricos/alfanuméricos
                            cods = db("SELECT codigo_articulo FROM Productos", fetch=True, fetchall=True)
                            max_num = 0
                            for (c,) in cods:
                                if c.startswith("ART-"):
                                    try:
                                        num = int(c.split("-")[1])
                                        if num > max_num: max_num = num
                                    except: pass
                            return f"ART-{str(max_num + 1).zfill(3)}"
                        except:
                            return "ART-011"

                    c_prod_modal = ft.TextField(label="Código Automático", value=generar_siguiente_codigo(), width=300, read_only=True)
                    n_prod_modal = ft.TextField(label="Descripción del Producto", width=300)
                    p_prod_modal = ft.TextField(label="Precio Unitario ($)", keyboard_type="number", width=300)

                    def abrir_modal_producto(e):
                        c_prod_modal.value = generar_siguiente_codigo()
                        n_prod_modal.value = ""
                        p_prod_modal.value = ""
                        setattr(page, 'dialog', modal_prod)
                        setattr(modal_prod, 'open', True)
                        page.update()

                    def guardar_producto_rapido(ev):
                        if n_prod_modal.value and p_prod_modal.value:
                            try:
                                nuevo_codigo = c_prod_modal.value
                                p_val = float(p_prod_modal.value.replace(',', '.'))
                                db("INSERT INTO Productos VALUES (?, ?, ?)", (nuevo_codigo, n_prod_modal.value.upper(), p_val))
                                recargar_catalogo()
                                dd_productos.value = nuevo_codigo
                                inp_precio.value = str(p_val)
                                inp_desc_item.value = n_prod_modal.value.upper()
                                page.dialog.open = False
                                page.snack_bar = ft.SnackBar(ft.Text(f"✅ Producto {nuevo_codigo} creado con éxito", color="white"), bgcolor="green")
                                page.snack_bar.open = True; page.update()
                            except Exception as ex:
                                page.snack_bar = ft.SnackBar(ft.Text(f"❌ Error al crear producto: {ex}", color="white"), bgcolor="red")
                                page.snack_bar.open = True; page.update()

                    modal_prod = ft.AlertDialog(
                        title=ft.Text("Nuevo Producto Rápido"),
                        content=ft.Column([c_prod_modal, n_prod_modal, p_prod_modal], tight=True),
                        actions=[ft.TextButton("Guardar", on_click=guardar_producto_rapido), ft.TextButton("Cancelar", on_click=lambda _: (setattr(page.dialog, 'open', False), page.update()))]
                    )

                    campo_nom_cli = ft.TextField(label="Nombre", width=300); campo_dir_cli = ft.TextField(label="Dirección", width=300)
                    def guardar_cliente_rapido(e):
                        if not campo_nom_cli.value: return
                        nom_nuevo = campo_nom_cli.value.upper()
                        dir_nueva = campo_dir_cli.value.upper()
                        db("INSERT INTO Clientes (nombre_apellido, direccion_entrega) VALUES (?, ?)", (nom_nuevo, dir_nueva))
                        
                        clientes_db = db("SELECT nombre_apellido, direccion_entrega FROM Clientes", fetch=True, fetchall=True)
                        nonlocal todos_los_clientes
                        todos_los_clientes = [f"{c[0]} ({c[1] if c[1] else 'Sin dirección'})" for c in clientes_db]
                        
                        dd_clientes.options = [ft.dropdown.Option(text=c) for c in todos_los_clientes]
                        cliente_recien_creado = f"{nom_nuevo} ({dir_nueva if dir_nueva else 'Sin dirección'})"
                        dd_clientes.value = cliente_recien_creado
                        campo_nom_cli.value = ""; campo_dir_cli.value = ""; page.dialog.open = False
                        actualizar_direccion()
                        
                    modal_cliente = ft.AlertDialog(title=ft.Text("Agregar Cliente"), content=ft.Column([campo_nom_cli, campo_dir_cli], tight=True), actions=[ft.TextButton("Guardar", on_click=guardar_cliente_rapido)])

                    if estado_carrito["editando"]:
                        id_fac = estado_carrito["id_factura"]
                        cliente_actual = db("SELECT c.nombre_apellido, c.direccion_entrega, f.fecha FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente WHERE f.numero_factura = ?", (id_fac,), fetch=True)
                        if cliente_actual: 
                            nombre_encontrado = cliente_actual[0]
                            dir_encontrada = cliente_actual[1] if cliente_actual[1] else 'Sin dirección'
                            dd_clientes.value = f"{nombre_encontrado} ({dir_encontrada})"
                            inp_fecha_factura.value = cliente_actual[2]
                            actualizar_direccion()
                        if not estado_carrito["cargado"]:
                            detalles = db("SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, d.unidades FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo WHERE d.numero_factura = ?", (id_fac,), fetch=True, fetchall=True)
                            carrito.clear()
                            for cod, nom_pers, pre, uni in detalles: 
                                carrito[cod] = {"nombre": nom_pers, "precio": pre, "cantidad": uni}
                            estado_carrito["cargado"] = True

                    def act_carrito():
                        lista_carrito_ui.controls.clear()
                        suma = sum(item["cantidad"] * item["precio"] for item in carrito.values())
                        for cod, item in carrito.items():
                            def crear_borrar_item(c_item=cod): return lambda _: (carrito.pop(c_item), act_carrito())
                            cant_fmt = str(int(item['cantidad'])) if item['cantidad'] == int(item['cantidad']) else str(item['cantidad']).replace('.', ',')
                            lista_carrito_ui.controls.append(ft.ListTile(leading=ft.Icon("check_circle", color="green"), title=ft.Text(f"{cant_fmt}x {item['nombre']}", weight="bold"), subtitle=ft.Text(f"Precio Unit: ${formato_ars(item['precio'])} | Subtotal: ${formato_ars(item['cantidad'] * item['precio'])}"), trailing=ft.IconButton("delete", icon_color="red", on_click=crear_borrar_item(cod))))
                        texto_total.value = f"TOTAL: $ {formato_ars(suma)}"; page.update()

                    def agregar(e):
                        if not dd_productos.value or not inp_cant.value: return
                        try:
                            cant_float = float(inp_cant.value.replace(',', '.'))
                            precio_float = float(inp_precio.value.replace(',', '.')) if inp_precio.value else cat[dd_productos.value]["precio"]
                            nombre_personalizado = (inp_desc_item.value or cat[dd_productos.value]["nombre"]).strip().upper()
                            if cant_float <= 0 or precio_float < 0: return
                        except ValueError:
                            page.snack_bar = ft.SnackBar(ft.Text("Cantidad o precio inválido", color="white"), bgcolor="red")
                            page.snack_bar.open = True; page.update()
                            return
                            
                        cod = dd_productos.value
                        cant = int(cant_float) if cant_float.is_integer() else cant_float
                        
                        carrito[cod] = {
                            "nombre": nombre_personalizado, 
                            "precio": precio_float, 
                            "cantidad": carrito.get(cod, {}).get("cantidad", 0) + cant
                        }
                        dd_productos.value = None; inp_cant.value = ""; inp_precio.value = ""; inp_desc_item.value = ""; buscador_prod.value = ""
                        act_carrito()

                    def confirmar(e):
                        if not dd_clientes.value or not carrito: return
                        nombre_limpio = dd_clientes.value.split(" (")[0]
                        num_cli = db("SELECT numero_cliente FROM Clientes WHERE nombre_apellido = ?", (nombre_limpio,), fetch=True)[0]
                        fecha_elegida = inp_fecha_factura.value.strip()
                        if not fecha_elegida: fecha_elegida = date.today().strftime("%Y-%m-%d")

                        if estado_carrito["editando"]:
                            ya_facturado = db("SELECT COUNT(*) FROM Facturas WHERE numero_cliente = ? AND fecha = ? AND numero_factura != ?", (num_cli, fecha_elegida, estado_carrito["id_factura"]), fetch=True)[0]
                        else:
                            ya_facturado = db("SELECT COUNT(*) FROM Facturas WHERE numero_cliente = ? AND fecha = ?", (num_cli, fecha_elegida), fetch=True)[0]

                        if ya_facturado > 0:
                            page.snack_bar = ft.SnackBar(ft.Text("❌ ¡CUIDADO! Este cliente ya tiene una factura en esta fecha. Usá el lápiz azul para editarla.", color="white"), bgcolor="red", duration=6000)
                            page.snack_bar.open = True
                            page.update()
                            return
                            
                        nueva_direccion = (inp_dir_factura.value or "").strip().upper()
                        db("UPDATE Clientes SET direccion_entrega = ? WHERE nombre_apellido = ?", (nueva_direccion, nombre_limpio))

                        tot = sum(item["cantidad"] * item["precio"] for item in carrito.values())
                        vendedor_factura = page.session.get("usuario")
                        
                        try: db("ALTER TABLE Detalle_Factura ADD COLUMN nombre_personalizado TEXT")
                        except: pass

                        if estado_carrito["editando"]:
                            id_fac = estado_carrito["id_factura"]
                            db("UPDATE Facturas SET numero_cliente = ?, total_a_pagar = ?, preventista = ?, fecha = ? WHERE numero_factura = ?", (num_cli, tot, vendedor_factura, fecha_elegida, id_fac))
                            db("DELETE FROM Detalle_Factura WHERE numero_factura = ?", (id_fac,))
                            for cod, item in carrito.items(): 
                                db("INSERT INTO Detalle_Factura (numero_factura, codigo_articulo, nombre_personalizado, precio_unitario, unidades, total_linea) VALUES (?, ?, ?, ?, ?, ?)", (id_fac, cod, item["nombre"], item["precio"], item["cantidad"], item["cantidad"] * item["precio"]))
                        else:
                            db("INSERT INTO Facturas (fecha, numero_cliente, total_a_pagar, preventista) VALUES (?, ?, ?, ?)", (fecha_elegida, num_cli, tot, vendedor_factura))
                            nuevo_num = db("SELECT MAX(numero_factura) FROM Facturas", fetch=True)[0]
                            for cod, item in carrito.items(): 
                                db("INSERT INTO Detalle_Factura (numero_factura, codigo_articulo, nombre_personalizado, precio_unitario, unidades, total_linea) VALUES (?, ?, ?, ?, ?, ?)", (nuevo_num, cod, item["nombre"], item["precio"], item["cantidad"], item["cantidad"] * item["precio"]))
                        
                        carrito.clear(); estado_carrito["editando"] = False; page.go("/pedidos_dia")

                    tit_pantalla = f"CORRIGIENDO NRO {estado_carrito['id_factura']}" if estado_carrito["editando"] else "Armar Pedido"
                    color_fondo = "#424242"

                    panel_izquierdo = ft.Card(
                        content=ft.Container(
                            padding=20,
                            content=ft.Column([
                                ft.Text("1. Datos Generales", weight="bold", size=16), 
                                ft.Row([buscador_cli, dd_clientes, ft.IconButton(icon="person_add", icon_color="blue", tooltip="Nuevo Cliente", on_click=lambda _: (setattr(page, 'dialog', modal_cliente), setattr(modal_cliente, 'open', True), page.update()))]), 
                                ft.Row([inp_dir_factura, inp_fecha_factura]), 
                                ft.Divider(),
                                ft.Text("2. Buscar y Agregar Artículos", weight="bold", size=16), 
                                ft.Row([buscador_prod, dd_productos, ft.IconButton(icon="add_box", icon_color="blue", tooltip="Nuevo Producto Rápido", on_click=abrir_modal_producto)]), 
                                ft.Row([inp_cant, inp_precio]),
                                inp_desc_item,
                                ft.ElevatedButton("AGREGAR AL TICKET", icon="add", on_click=agregar, width=float("inf"), style=ft.ButtonStyle(padding=20, bgcolor="#e0e0e0", color="black"))
                            ], scroll="auto")
                        ),
                        expand=6
                    )

                    panel_derecho = ft.Card(
                        color="#f5f5f5",
                        content=ft.Container(
                            padding=20,
                            content=ft.Column([
                                ft.Row([ft.Icon("shopping_cart"), ft.Text("Resumen del Ticket", weight="bold", size=18)]),
                                ft.Divider(),
                                lista_carrito_ui,
                                ft.Divider(),
                                ft.Container(
                                    bgcolor=color_fondo, 
                                    padding=15, 
                                    border_radius=10, 
                                    content=ft.Column([
                                        ft.Row([texto_total], alignment="center"), 
                                        ft.ElevatedButton("GUARDAR VENTA", icon="save", on_click=confirmar, bgcolor="green", color="white", width=float("inf"), height=55)
                                    ])
                                )
                            ], expand=True)
                        ),
                        expand=4
                    )

                    page.views.append(ft.View("/carrito", [
                        ft.AppBar(title=ft.Text(tit_pantalla), bgcolor=color_fondo, color="white", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/pedidos_dia"))), 
                        ft.Row([panel_izquierdo, panel_derecho], expand=True, vertical_alignment=ft.CrossAxisAlignment.START)
                    ], padding=20)); act_carrito()

                elif page.route == "/agregar_producto":
                    inp_cod = ft.TextField(label="Código (ART-01)", width=float("inf"))
                    inp_nom = ft.TextField(label="Descripción", width=float("inf"))
                    inp_pre = ft.TextField(label="Precio ($)", keyboard_type="number", width=float("inf"))
                    
                    boton_guardar_prod = ft.ElevatedButton("GUARDAR", icon="save", style=ft.ButtonStyle(bgcolor=COLORES["secondary"], color="white", padding=20), width=float("inf"))
                    tabla_prod = ft.DataTable(columns=[ft.DataColumn(ft.Text(c, weight="bold")) for c in ["Cod.", "Desc", "Prec", "Acciones"]], rows=[])
                    estado_edicion_prod = {"editando": False, "codigo_viejo": None}

                    def ref_prod():
                        try:
                            tabla_prod.rows.clear()
                            filas = db("SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos", fetch=True, fetchall=True)
                            if filas:
                                for c, n, p in filas:
                                    def crear_borrar_p(cod_p=c):
                                        def eliminar(_):
                                            usado = db("SELECT COUNT(*) FROM Detalle_Factura WHERE codigo_articulo=?", (cod_p,), fetch=True)[0]
                                            if usado:
                                                page.snack_bar = ft.SnackBar(ft.Text("No se puede eliminar: el producto tiene historial de ventas.", color="white"), bgcolor=COLORES["warning"], duration=5000)
                                                page.snack_bar.open = True; page.update(); return
                                            db("DELETE FROM Productos WHERE codigo_articulo=?", (cod_p,))
                                            ref_prod()
                                        return eliminar
                                    def crear_editar_p(cod_p=c, nom_p=n, pre_p=p):
                                        def cargar(_):
                                            estado_edicion_prod["editando"] = True
                                            estado_edicion_prod["codigo_viejo"] = cod_p
                                            inp_cod.value = str(cod_p); inp_cod.disabled = True
                                            inp_nom.value = str(nom_p); inp_pre.value = str(p)
                                            boton_guardar_prod.text = "ACTUALIZAR"
                                            boton_guardar_prod.style = ft.ButtonStyle(bgcolor="orange", color="white", padding=20)
                                            page.update()
                                        return cargar
                                    tabla_prod.rows.append(ft.DataRow(cells=[
                                        ft.DataCell(ft.Text(str(c))), ft.DataCell(ft.Text(str(n))), ft.DataCell(ft.Text(f"${formato_ars(p)}")), 
                                        ft.DataCell(ft.Row([ft.IconButton("edit", icon_color="blue", on_click=crear_editar_p(c, n, p)), ft.IconButton("delete", icon_color="red", on_click=crear_borrar_p(c))]))
                                    ]))
                            tabla_prod.update()
                        except: pass
                    
                    def guardar_p(e):
                        if inp_cod.value and inp_nom.value and inp_pre.value:
                            cod = (inp_cod.value or "").strip().upper()
                            nom = (inp_nom.value or "").strip().upper()
                            try: pre = float(inp_pre.value.replace(',','.'))
                            except ValueError:
                                page.snack_bar = ft.SnackBar(ft.Text("Precio inválido", color="white"), bgcolor="red")
                                page.snack_bar.open = True; page.update()
                                return

                            if estado_edicion_prod["editando"]:
                                db("UPDATE Productos SET nombre_articulo=?, precio_unitario=? WHERE codigo_articulo=?", (nom, pre, estado_edicion_prod["codigo_viejo"]))
                                estado_edicion_prod["editando"] = False; estado_edicion_prod["codigo_viejo"] = None
                                inp_cod.disabled = False; boton_guardar_prod.text = "GUARDAR"
                                boton_guardar_prod.style = ft.ButtonStyle(bgcolor=COLORES["secondary"], color="white", padding=20)
                            else:
                                try: db("INSERT INTO Productos VALUES (?, ?, ?)", (cod, nom, pre))
                                except sqlite3.IntegrityError:
                                    page.snack_bar = ft.SnackBar(ft.Text("Ese código ya existe.", color="white"), bgcolor="red")
                                    page.snack_bar.open = True; page.update()
                                    return
                            inp_cod.value = ""; inp_nom.value = ""; inp_pre.value = ""
                            ref_prod(); page.update()

                    boton_guardar_prod.on_click = guardar_p
                    page.views.append(ft.View("/agregar_producto", [ft.AppBar(title=ft.Text("Catálogo"), bgcolor=COLORES["secondary"], color="white", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/"))), inp_cod, inp_nom, inp_pre, boton_guardar_prod, ft.Divider(), ft.Column([tabla_prod], scroll="auto", expand=True)], padding=20)); ref_prod()

                elif page.route == "/agregar_cliente":
                    # ======================================================
                    # GESTIÓN DE CLIENTES - versión liviana
                    # ======================================================
                    inp_nom_c = ft.TextField(label="Nombre / Razón social", expand=True)
                    inp_dir_c = ft.TextField(label="Dirección de entrega", expand=True)
                    buscador_cli_gestion = ft.TextField(
                        label="🔎 Buscar cliente por nombre o dirección",
                        prefix_icon="search",
                        expand=True,
                        on_change=None
                    )

                    boton_guardar_cli = ft.ElevatedButton(
                        "GUARDAR CLIENTE",
                        icon="person_add",
                        style=ft.ButtonStyle(
                            bgcolor=COLORES["secondary"],
                            color="white",
                            padding=15
                        )
                    )

                    tabla_cli = ft.DataTable(
                        columns=[
                            ft.DataColumn(ft.Text("ID", weight="bold")),
                            ft.DataColumn(ft.Text("CLIENTE", weight="bold")),
                            ft.DataColumn(ft.Text("DIRECCIÓN", weight="bold")),
                            ft.DataColumn(ft.Text("ACCIONES", weight="bold")),
                        ],
                        rows=[],
                        column_spacing=28,
                        horizontal_margin=12,
                    )

                    estado_edicion_cli = {"editando": False, "id_viejo": None}
                    pagina_clientes = {"valor": 0}
                    clientes_por_pagina = 40
                    total_clientes_txt = ft.Text("", size=12, color=COLORES["muted"])
                    pagina_txt = ft.Text("", size=12, color=COLORES["muted"])

                    def limpiar_formulario_cliente(_=None):
                        estado_edicion_cli["editando"] = False
                        estado_edicion_cli["id_viejo"] = None
                        inp_nom_c.value = ""
                        inp_dir_c.value = ""
                        boton_guardar_cli.text = "GUARDAR CLIENTE"
                        boton_guardar_cli.icon = "person_add"
                        boton_guardar_cli.style = ft.ButtonStyle(
                            bgcolor=COLORES["secondary"],
                            color="white",
                            padding=15
                        )
                        page.update()

                    def ref_cli(e=None):
                        try:
                            filtro = (buscador_cli_gestion.value or "").strip().upper()
                            pagina = pagina_clientes["valor"]

                            # Búsqueda directamente en SQLite:
                            # nunca cargamos toda la tabla en memoria.
                            if filtro:
                                like = f"%{filtro}%"
                                total = db(
                                    """SELECT COUNT(*) FROM Clientes
                                       WHERE UPPER(nombre_apellido) LIKE ?
                                       OR UPPER(COALESCE(direccion_entrega,'')) LIKE ?""",
                                    (like, like),
                                    fetch=True
                                )[0]

                                filas = db(
                                    """SELECT numero_cliente, nombre_apellido, direccion_entrega
                                       FROM Clientes
                                       WHERE UPPER(nombre_apellido) LIKE ?
                                       OR UPPER(COALESCE(direccion_entrega,'')) LIKE ?
                                       ORDER BY nombre_apellido COLLATE NOCASE
                                       LIMIT ? OFFSET ?""",
                                    (like, like, clientes_por_pagina,
                                     pagina * clientes_por_pagina),
                                    fetch=True,
                                    fetchall=True
                                )
                            else:
                                total = db(
                                    "SELECT COUNT(*) FROM Clientes",
                                    fetch=True
                                )[0]

                                filas = db(
                                    """SELECT numero_cliente, nombre_apellido, direccion_entrega
                                       FROM Clientes
                                       ORDER BY nombre_apellido COLLATE NOCASE
                                       LIMIT ? OFFSET ?""",
                                    (clientes_por_pagina,
                                     pagina * clientes_por_pagina),
                                    fetch=True,
                                    fetchall=True
                                )

                            tabla_cli.rows.clear()

                            for id_c, n, d in filas:

                                def crear_borrar_c(num_c=id_c, nom_c=n):
                                    def eliminar(_):
                                        usado = db(
                                            "SELECT COUNT(*) FROM Facturas WHERE numero_cliente=?",
                                            (num_c,),
                                            fetch=True
                                        )[0]

                                        if usado:
                                            page.snack_bar = ft.SnackBar(
                                                ft.Text(
                                                    "No se puede eliminar: el cliente tiene historial de ventas.",
                                                    color="white"
                                                ),
                                                bgcolor=COLORES["warning"],
                                                duration=5000
                                            )
                                            page.snack_bar.open = True
                                            page.update()
                                            return

                                        db(
                                            "DELETE FROM Clientes WHERE numero_cliente=?",
                                            (num_c,)
                                        )
                                        ref_cli()

                                    return eliminar

                                def crear_editar_c(num_c=id_c, nom_c=n, dir_c=d):
                                    def cargar(_):
                                        estado_edicion_cli["editando"] = True
                                        estado_edicion_cli["id_viejo"] = num_c
                                        inp_nom_c.value = str(nom_c or "")
                                        inp_dir_c.value = str(dir_c or "")
                                        boton_guardar_cli.text = "ACTUALIZAR CLIENTE"
                                        boton_guardar_cli.icon = "save"
                                        boton_guardar_cli.style = ft.ButtonStyle(
                                            bgcolor=COLORES["warning"],
                                            color="white",
                                            padding=15
                                        )
                                        page.update()

                                    return cargar

                                tabla_cli.rows.append(
                                    ft.DataRow(
                                        cells=[
                                            ft.DataCell(ft.Text(str(id_c))),
                                            ft.DataCell(
                                                ft.Text(
                                                    str(n or ""),
                                                    weight="bold"
                                                )
                                            ),
                                            ft.DataCell(
                                                ft.Text(
                                                    str(d or "Sin dirección"),
                                                    color=COLORES["muted"]
                                                )
                                            ),
                                            ft.DataCell(
                                                ft.Row(
                                                    [
                                                        ft.IconButton(
                                                            "edit",
                                                            tooltip="Editar cliente",
                                                            icon_color=COLORES["info"],
                                                            on_click=crear_editar_c()
                                                        ),
                                                        ft.IconButton(
                                                            "delete_outline",
                                                            tooltip="Eliminar cliente",
                                                            icon_color=COLORES["danger"],
                                                            on_click=crear_borrar_c()
                                                        ),
                                                    ],
                                                    spacing=0
                                                )
                                            ),
                                        ]
                                    )
                                )

                            total_clientes_txt.value = (
                                f"{total:,} clientes registrados".replace(",", ".")
                            )

                            total_paginas = max(
                                1,
                                (total + clientes_por_pagina - 1) //
                                clientes_por_pagina
                            )
                            pagina_txt.value = (
                                f"Página {pagina + 1} de {total_paginas}"
                            )

                            btn_anterior.disabled = pagina <= 0
                            btn_siguiente.disabled = pagina >= total_paginas - 1

                            tabla_cli.update()
                            total_clientes_txt.update()
                            pagina_txt.update()
                            btn_anterior.update()
                            btn_siguiente.update()

                        except Exception as ex:
                            print("Error en directorio de clientes:", ex)

                    def buscar_clientes(e=None):
                        pagina_clientes["valor"] = 0
                        ref_cli()

                    buscador_cli_gestion.on_change = buscar_clientes

                    def pagina_anterior(_):
                        if pagina_clientes["valor"] > 0:
                            pagina_clientes["valor"] -= 1
                            ref_cli()

                    def pagina_siguiente(_):
                        pagina_clientes["valor"] += 1
                        ref_cli()

                    btn_anterior = ft.IconButton(
                        icon="chevron_left",
                        tooltip="Clientes anteriores",
                        on_click=pagina_anterior
                    )
                    btn_siguiente = ft.IconButton(
                        icon="chevron_right",
                        tooltip="Clientes siguientes",
                        on_click=pagina_siguiente
                    )

                    def guardar_c(e):
                        nom_nuevo = (inp_nom_c.value or "").strip().upper()
                        dir_nueva = (inp_dir_c.value or "").strip().upper()

                        if not nom_nuevo:
                            page.snack_bar = ft.SnackBar(
                                ft.Text(
                                    "Ingrese el nombre del cliente.",
                                    color="white"
                                ),
                                bgcolor=COLORES["warning"]
                            )
                            page.snack_bar.open = True
                            page.update()
                            return

                        if estado_edicion_cli["editando"]:
                            db(
                                """UPDATE Clientes
                                   SET nombre_apellido=?, direccion_entrega=?
                                   WHERE numero_cliente=?""",
                                (
                                    nom_nuevo,
                                    dir_nueva,
                                    estado_edicion_cli["id_viejo"]
                                )
                            )
                            mensaje = "Cliente actualizado correctamente."
                        else:
                            db(
                                """INSERT INTO Clientes
                                   (nombre_apellido, direccion_entrega)
                                   VALUES (?, ?)""",
                                (nom_nuevo, dir_nueva)
                            )
                            mensaje = "Cliente agregado correctamente."

                        limpiar_formulario_cliente()
                        buscador_cli_gestion.value = ""
                        pagina_clientes["valor"] = 0
                        ref_cli()

                        page.snack_bar = ft.SnackBar(
                            ft.Text(mensaje, color="white"),
                            bgcolor=COLORES["secondary"]
                        )
                        page.snack_bar.open = True
                        page.update()

                    boton_guardar_cli.on_click = guardar_c

                    encabezado_clientes = ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Column(
                                            [
                                                ft.Text(
                                                    "Gestión de Clientes",
                                                    size=24,
                                                    weight="bold"
                                                ),
                                                total_clientes_txt
                                            ],
                                            spacing=2,
                                            expand=True
                                        ),
                                        ft.ElevatedButton(
                                            "NUEVO CLIENTE",
                                            icon="person_add",
                                            on_click=limpiar_formulario_cliente,
                                            style=ft.ButtonStyle(
                                                bgcolor=COLORES["primary"],
                                                color="white"
                                            )
                                        )
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                                ),
                                ft.ResponsiveRow(
                                    [
                                        ft.Container(
                                            content=inp_nom_c,
                                            col={"xs":12, "md":5}
                                        ),
                                        ft.Container(
                                            content=inp_dir_c,
                                            col={"xs":12, "md":5}
                                        ),
                                        ft.Container(
                                            content=boton_guardar_cli,
                                            col={"xs":12, "md":2}
                                        ),
                                    ],
                                    spacing=10
                                ),
                                ft.Row(
                                    [
                                        buscador_cli_gestion,
                                        ft.Container(
                                            content=ft.Row(
                                                [pagina_txt, btn_anterior, btn_siguiente],
                                                spacing=2
                                            )
                                        )
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER
                                ),
                            ],
                            spacing=12
                        ),
                        padding=16,
                        border_radius=12,
                        bgcolor=COLORES["surface"]
                    )

                    tabla_contenedor = ft.Container(
                        content=ft.Column(
                            [tabla_cli],
                            scroll="auto",
                            expand=True
                        ),
                        expand=True,
                        padding=10,
                        border_radius=12,
                        bgcolor=COLORES["surface"]
                    )

                    page.views.append(
                        ft.View(
                            "/agregar_cliente",
                            [
                                ft.AppBar(
                                    title=ft.Text(
                                        "Directorio de Clientes",
                                        color="white"
                                    ),
                                    bgcolor=COLORES["secondary"],
                                    color="white",
                                    leading=ft.IconButton(
                                        "arrow_back",
                                        icon_color="white",
                                        on_click=lambda _: page.go("/")
                                    )
                                ),
                                encabezado_clientes,
                                tabla_contenedor
                            ],
                            padding=12
                        )
                    )

                    ref_cli()

                elif page.route == "/reportes":
                    hoy = date.today().strftime("%Y-%m-%d")
                    inp_num = ft.TextField(label="Nro Factura", keyboard_type="number")
                    inp_fec = ft.TextField(label="Fecha (YYYY-MM-DD)", value=hoy)
                    inp_fec_cobranza = ft.TextField(label="Fecha a consultar (YYYY-MM-DD)", value=hoy)
                    inp_inicio = ft.TextField(label="Desde (YYYY-MM-DD)", value=hoy, expand=True)
                    inp_fin = ft.TextField(label="Hasta (YYYY-MM-DD)", value=hoy, expand=True)

                    lista_preventistas_bd = [r[0] for r in db("SELECT DISTINCT preventista FROM Facturas WHERE preventista IS NOT NULL", fetch=True, fetchall=True)]
                    if not lista_preventistas_bd: lista_preventistas_bd = ["ADMIN"]
                    
                    dd_usuario_rep_diario = ft.Dropdown(label="Usuario", options=[ft.dropdown.Option(text=u) for u in lista_preventistas_bd], value=lista_preventistas_bd[0], width=150)
                    dd_usuario_rep_rango = ft.Dropdown(label="Usuario", options=[ft.dropdown.Option(text=u) for u in lista_preventistas_bd], value=lista_preventistas_bd[0], width=150)

                    def pedir_pdf(tipo, id_f=None, f=None, finio=None, ffin=None, usuario=None):
                        fecha_archivo_fmt = formatear_fecha_archivo(f if f else (finio if finio else hoy))
                        
                        if tipo == "preventistas_fecha":
                            nombre_archivo = f"Reporte_total_preventistas_{fecha_archivo_fmt}.pdf"
                        elif tipo == "preventistas":
                            nombre_archivo = f"Reporte_preventistas_{fecha_archivo_fmt}.pdf"
                        elif tipo == "cobranza_dia":
                            nombre_archivo = f"Reporte_cobranza_dia_{fecha_archivo_fmt}.pdf"
                        elif tipo == "factura" and not id_f:
                            nombre_archivo = f"Reporte_factura_{fecha_archivo_fmt}.pdf"
                        elif tipo == "reporte_dia":
                            nombre_archivo = f"Reporte_reporte_dia_{fecha_archivo_fmt}.pdf"
                        elif tipo == "consolidado":
                            nombre_archivo = f"Reporte_consolidado_{fecha_archivo_fmt}.pdf"
                        elif usuario:
                            nombre_archivo = f"Reporte_{usuario}_{fecha_archivo_fmt}.pdf"
                        else:
                            nombre_archivo = f"Reporte_{tipo}_{fecha_archivo_fmt}.pdf"

                        ruta_completa = os.path.join(carpeta_assets, nombre_archivo)
                        
                        exito = False
                        if tipo == "factura":
                            exito = generar_pdf_facturas(ruta_completa, num_factura=id_f, fecha_consulta=f)
                        elif tipo == "reporte_dia":
                            exito = generar_reporte_generico(ruta_completa, "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, SUM(d.unidades), SUM(d.total_linea) FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo JOIN Facturas f ON d.numero_factura = f.numero_factura WHERE f.fecha = ? GROUP BY d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario", (f,), "REPORTE DIARIO DE VENTAS", f"Fecha: {f}")
                        elif tipo == "reporte_dia_usuario":
                            if usuario: exito = generar_reporte_articulos_por_usuario_dia(ruta_completa, f, usuario)
                        elif tipo == "consolidado":
                            exito = generar_reporte_generico(ruta_completa, "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, SUM(d.unidades), SUM(d.total_linea) FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo JOIN Facturas f ON d.numero_factura = f.numero_factura WHERE f.fecha BETWEEN ? AND ? GROUP BY d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario", (finio, ffin), "REPORTE CONSOLIDADO", f"Periodo: {finio} al {ffin}")
                        elif tipo == "consolidado_usuario":
                            if usuario: exito = generar_reporte_articulos_por_usuario_rango(ruta_completa, finio, ffin, usuario)
                        elif tipo == "preventistas_fecha":
                            exito = generar_reporte_total_preventistas_fecha(ruta_completa, f)
                        elif tipo == "preventistas":
                            exito = generar_reporte_preventistas(ruta_completa, finio, ffin)
                        elif tipo == "cobranza_dia":
                            exito = generar_reporte_clientes_dia(ruta_completa, f)
                        
                        if exito:
                            abrir_archivo_local(ruta_completa)
                            page.snack_bar = ft.SnackBar(ft.Text(f"✅ PDF generado y abierto: {nombre_archivo}", color="white"), bgcolor="green")
                        else:
                            page.snack_bar = ft.SnackBar(ft.Text("❌ No se encontraron datos.", color="white"), bgcolor="red")
                        page.snack_bar.open = True; page.update()

                    page.views.append(ft.View("/reportes", [
                        ft.AppBar(title=ft.Text("Centro de Impresión"), bgcolor="#FF8F00", color="white", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/"))),
                        
                        ft.Card(content=ft.Container(padding=20, content=ft.Column([
                            ft.Text("Rendición de Caja por Vendedor", weight="bold", size=17),
                            ft.Text("Reporte total de TODOS los preventistas para una fecha específica. No depende del usuario que inició sesión.", size=12, color="gray"),
                            ft.Row([
                                inp_fec,
                                ft.ElevatedButton("TOTAL DE PREVENTISTAS", icon="people", bgcolor="#1565C0", color="white", on_click=lambda _: pedir_pdf("preventistas_fecha", f=inp_fec.value.strip()))
                            ]),
                            ft.Divider(),
                            ft.Text("Consolidado de preventistas por período", weight="bold"),
                            ft.Row([inp_inicio, inp_fin]),
                            ft.ElevatedButton("Generar Balance Vendedores", icon="date_range", bgcolor="#1565C0", color="white", on_click=lambda _: pedir_pdf("preventistas", finio=inp_inicio.value.strip(), ffin=inp_fin.value.strip()))
                        ]))),
                        
                        ft.Card(content=ft.Container(padding=20, content=ft.Column([
                            ft.Text("Resumen de Cobranzas a Clientes", weight="bold"), 
                            inp_fec_cobranza,
                            ft.ElevatedButton("Listado de Cobranza del Día", icon="request_quote", bgcolor="#388E3C", color="white", on_click=lambda _: pedir_pdf("cobranza_dia", f=inp_fec_cobranza.value))
                        ]))),

                        ft.Card(content=ft.Container(padding=20, content=ft.Column([
                            ft.Text("Imprimir Facturas Físicas", weight="bold"), inp_num, 
                            ft.ElevatedButton("Reimprimir por Número", on_click=lambda _: pedir_pdf("factura", id_f=int(inp_num.value) if inp_num.value else 0)), ft.Divider(), inp_fec, 
                            ft.ElevatedButton("Lote Diario Completo", on_click=lambda _: pedir_pdf("factura", f=inp_fec.value))]))),
                            
                        ft.Card(content=ft.Container(padding=20, content=ft.Column([
                            ft.Text("Balances de Mercadería", weight="bold"), 
                            ft.Row([
                                ft.ElevatedButton("Reporte Diario", icon="today", on_click=lambda _: pedir_pdf("reporte_dia", f=inp_fec.value)),
                                dd_usuario_rep_diario,
                                ft.ElevatedButton("Por Usuario", icon="assignment", bgcolor="#00838F", color="white", on_click=lambda _: pedir_pdf("reporte_dia_usuario", f=inp_fec.value, usuario=dd_usuario_rep_diario.value))
                            ]), 
                            ft.Divider(),
                            ft.Text("Consolidado por Fechas", weight="bold"), ft.Row([inp_inicio, inp_fin]),
                            ft.Row([
                                ft.ElevatedButton("Generar Balance Mercadería", icon="date_range", bgcolor="#00695C", color="white", on_click=lambda _: pedir_pdf("consolidado", finio=inp_inicio.value.strip(), ffin=inp_fin.value.strip())),
                                dd_usuario_rep_rango,
                                ft.ElevatedButton("Por Usuario", icon="assignment", bgcolor="#00838F", color="white", on_click=lambda _: pedir_pdf("reporte_dia_usuario", finio=inp_inicio.value.strip(), ffin=inp_fin.value.strip(), usuario=dd_usuario_rep_rango.value))
                            ])
                        ])))
                    ], padding=20, scroll="auto"))

                elif page.route == "/carga_inteligente":
                    inp_texto_magico = ft.TextField(
                        label="Pegá el código de IA acá...",
                        multiline=True,
                        min_lines=3,
                        max_lines=6,
                        border_color="#00838F"
                    )

                    def procesar_magia(e):
                        texto = inp_texto_magico.value.strip()
                        if not texto: return

                        try:
                            partes = texto.split("|")
                            nombre_cliente = None
                            direccion_cliente = "SIN DIRECCIÓN"
                            items_a_cargar = [] 

                            for p in partes:
                                p = p.strip()
                                if not p or ":" not in p: continue
                                clave, valor = p.split(":", 1)
                                clave = clave.strip().upper(); valor = valor.strip().upper()

                                if clave == "CLIENTE":
                                    nombre_cliente = valor
                                elif clave == "DIRECCION" or clave == "DIRECCIÓN":
                                    direccion_cliente = valor
                                else:
                                    try:
                                        cant_float = float(valor.replace(",", "."))
                                        items_a_cargar.append((clave, cant_float))
                                    except ValueError:
                                        pass

                            if not nombre_cliente:
                                page.snack_bar = ft.SnackBar(ft.Text("❌ Error: Faltó indicar 'CLIENTE: Nombre' en el texto.", color="white"), bgcolor="red")
                                page.snack_bar.open = True; page.update(); return

                            if not items_a_cargar:
                                page.snack_bar = ft.SnackBar(ft.Text("❌ Error: No se detectaron productos válidos.", color="white"), bgcolor="red")
                                page.snack_bar.open = True; page.update(); return

                            res_cli = db("SELECT numero_cliente FROM Clientes WHERE nombre_apellido = ?", (nombre_cliente,), fetch=True)
                            if res_cli:
                                num_cli = res_cli[0]
                                if direccion_cliente != "SIN DIRECCIÓN":
                                    db("UPDATE Clientes SET direccion_entrega = ? WHERE numero_cliente = ?", (direccion_cliente, num_cli))
                            else:
                                db("INSERT INTO Clientes (nombre_apellido, direccion_entrega) VALUES (?, ?)", (nombre_cliente, direccion_cliente))
                                num_cli = db("SELECT MAX(numero_cliente) FROM Clientes", fetch=True)[0]

                            fecha_hoy = date.today().strftime("%Y-%m-%d")

                            ya_facturado = db("SELECT COUNT(*) FROM Facturas WHERE numero_cliente = ? AND fecha = ?", (num_cli, fecha_hoy), fetch=True)[0]
                            if ya_facturado > 0:
                                page.snack_bar = ft.SnackBar(ft.Text(f"❌ ALERTA: {nombre_cliente} ya tiene un pedido cargado hoy.", color="white"), bgcolor="red", duration=6000)
                                page.snack_bar.open = True; page.update(); return

                            total_factura = 0
                            detalles_finales = []
                            for cod, cant in items_a_cargar:
                                res_prod = db("SELECT nombre_articulo, precio_unitario FROM Productos WHERE codigo_articulo = ?", (cod,), fetch=True)
                                if not res_prod:
                                    page.snack_bar = ft.SnackBar(ft.Text(f"❌ Error: El artículo '{cod}' no existe.", color="white"), bgcolor="red")
                                    page.snack_bar.open = True; page.update(); return
                                
                                nom_orig = res_prod[0]
                                precio = res_prod[1]
                                subtotal = precio * cant
                                total_factura += subtotal
                                detalles_finales.append((cod, nom_orig, precio, cant, subtotal))

                            vendedor_actual = page.session.get("usuario")
                            db("INSERT INTO Facturas (fecha, numero_cliente, total_a_pagar, preventista) VALUES (?, ?, ?, ?)", (fecha_hoy, num_cli, total_factura, vendedor_actual))
                            nuevo_num_factura = db("SELECT MAX(numero_factura) FROM Facturas", fetch=True)[0]

                            for cod, nom_orig, pre, can, sub in detalles_finales:
                                db("INSERT INTO Detalle_Factura (numero_factura, codigo_articulo, nombre_personalizado, precio_unitario, unidades, total_linea) VALUES (?, ?, ?, ?, ?, ?)", (nuevo_num_factura, cod, nom_orig, pre, can, sub))

                            inp_texto_magico.value = ""
                            def cerrar_aviso_magico(e):
                                page.dialog.open = False
                                page.update()
                            
                            page.dialog = ft.AlertDialog(
                                title=ft.Text("✅ VENTA CREADA CON ÉXITO", color="green", weight="bold"), 
                                content=ft.Text(f"Se generó la factura #{nuevo_num_factura} para {nombre_cliente}\nDir: {direccion_cliente}\nTotal: $ {formato_ars(total_factura)}"),
                                actions=[ft.TextButton("Volver a Ventas", on_click=lambda _: (cerrar_aviso_magico(None), page.go("/pedidos_dia"))), ft.TextButton("Cargar otra", on_click=cerrar_aviso_magico)]
                            )
                            page.dialog.open = True
                            page.update()

                        except Exception as ex:
                            print(traceback.format_exc())
                            page.snack_bar = ft.SnackBar(ft.Text(f"❌ Error técnico.", color="white"), bgcolor="red")
                            page.snack_bar.open = True; page.update()

                    page.views.append(ft.View("/carga_inteligente", [
                        ft.AppBar(title=ft.Text("Carga Inteligente ⚡"), bgcolor="#00838F", color="white", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/pedidos_dia"))),
                        ft.Container(padding=20, expand=True, content=ft.Column([
                            ft.Text("Pegá acá el código que te pase el asistente:", weight="bold", size=18, color="#00838F"),
                            ft.Text("Ejemplo: CLIENTE: CAROLINA | DIRECCION: B° MARIANO MORENO | ART-001: 2", italic=True, color="gray"),
                            ft.Divider(),
                            inp_texto_magico,
                            ft.Divider(),
                            ft.ElevatedButton(">>> PROCESAR Y GENERAR FACTURA <<<", icon="auto_fix_high", style=ft.ButtonStyle(bgcolor="#00838F", color="white", padding=20), on_click=procesar_magia, width=float("inf"))
                        ], scroll="auto"))
                    ]))

                else:
                    page.views.append(ft.View("/error", [ft.Text("Cargando...", size=20)]))
                    page.go("/")
                    return

                page.update()
                
            except Exception as ex:
                error_pila = traceback.format_exc()
                page.clean() 
                page.add(ft.Text("¡ERROR GRÁFICO!", color="white", bgcolor="red", size=24, weight="bold"), ft.Text(error_pila, color="red"))
                page.update()

        page.on_route_change = cambiar_pantalla
        page.route = "/login"
        cambiar_pantalla(None)

    except Exception as e:
        error_pila = traceback.format_exc()
        page.clean() 
        page.add(ft.Text("¡ERROR DE ARRANQUE!", color="white", bgcolor="red", size=24, weight="bold"), ft.Text(error_pila, color="red"))
        page.update()

if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.FLET_APP)