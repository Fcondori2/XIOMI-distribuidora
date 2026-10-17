import flet as ft
import asyncio
import os
import sqlite3
import traceback
import time
import csv
import json
import urllib.parse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
 
# ==========================================
# 0. RUTAS ABSOLUTAS Y BASE DE DATOS LIMPIA PARA APK
# ==========================================
directorio_actual = os.path.dirname(os.path.abspath(__file__))

# En Android/APK, Flet asigna una carpeta privada de datos por instalación.
# Al desinstalar e instalar la APK, esta carpeta nace 100% vacía (0 facturas).
directorio_datos_usuario = os.environ.get("FLET_APP_STORAGE_DATA") or directorio_actual
carpeta_assets = os.path.join(directorio_datos_usuario, "assets")
carpeta_assets_empacada = os.path.join(directorio_actual, "assets")

for c in (carpeta_assets, carpeta_assets_empacada):
    if not os.path.exists(c):
        try:
            os.makedirs(c)
        except Exception:
            pass

# Archivo semilla que guarda SOLO clientes, productos y vendedores (CERO FACTURAS)
ruta_semilla_catalogo = os.path.join(carpeta_assets_empacada, "catalogo_semilla.json")

# Base de datos exclusiva de la App/APK (separada de sistema_ventas.db para no arrastrar facturas viejas)
ruta_db = os.path.join(directorio_datos_usuario, "xiomi_preventa_local.db")

# Base de datos madre en tu PC (solo se lee en tu compu para extraer clientes y productos limpios)
_candidatas_db_madre = [
    os.path.join(directorio_actual, "sistema_ventas.db"),
    os.path.join(directorio_actual, "sistema_ventas(2).db"),
]
ruta_db_madre = next((p for p in _candidatas_db_madre if os.path.exists(p)), None)

# Registro de diagnóstico persistente: permite identificar fallos de inicio en Android.
ruta_log_inicio = os.path.join(directorio_datos_usuario, "xiomi_inicio_error.txt")

def registrar_inicio(etapa, detalle=None):
    try:
        os.makedirs(directorio_datos_usuario, exist_ok=True)
        with open(ruta_log_inicio, "a", encoding="utf-8") as archivo_log:
            archivo_log.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {etapa}\n")
            if detalle:
                archivo_log.write(str(detalle) + "\n")
    except Exception:
        pass
    try:
        print(f"[XIOMI-INICIO] {etapa}", flush=True)
        if detalle:
            print(str(detalle), flush=True)
    except Exception:
        pass

# Registrar que el módulo llegó a cargarse; se guarda fuera del bundle de solo lectura.
registrar_inicio("MÓDULO main.py cargado; imports completados")

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

def formato_ars(numero): 
    try: 
        return f"{float(numero):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception: 
        return "0,00"

def formato_ars_corto(numero):
    try:
        val = float(numero or 0)
        if val == int(val):
            return f"{int(val):,}".replace(",", ".")
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0"

def formatear_fecha_archivo(fecha_str):
    try: 
        return datetime.strptime(fecha_str, "%Y-%m-%d").strftime("%d-%m-%y")
    except Exception: 
        return datetime.now().strftime("%d-%m-%y")

def fecha_ui(fecha_str):
    try:
        obj = datetime.strptime(fecha_str, "%Y-%m-%d")
        return f"{obj.day}/{obj.month}/{obj.year}"
    except Exception:
        return str(fecha_str)

# ==========================================
# 1. BASE DE DATOS LOCAL Y SEMILLA SIN FACTURAS
# ==========================================
@contextmanager
def conexion_segura():
    conexion = sqlite3.connect(ruta_db, timeout=15, check_same_thread=False)
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
        if query.lstrip().upper().startswith("INSERT"): 
            return cursor.lastrowid
        return None

def crear_factura_con_detalle(fecha, numero_cliente, total, preventista, detalles):
    with conexion_segura() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "INSERT INTO Facturas (fecha, numero_cliente, total_a_pagar, preventista) VALUES (?, ?, ?, ?)", 
            (fecha, numero_cliente, total, preventista)
        )
        numero_factura = cursor.lastrowid
        cursor.executemany(
            "INSERT INTO Detalle_Factura (numero_factura, codigo_articulo, nombre_personalizado, precio_unitario, unidades, total_linea) VALUES (?, ?, ?, ?, ?, ?)", 
            [(numero_factura, cod, nombre, precio, cantidad, subtotal) for cod, nombre, precio, cantidad, subtotal in detalles]
        )
        return numero_factura

def actualizar_factura_con_detalle(numero_factura, fecha, numero_cliente, total, preventista, detalles):
    with conexion_segura() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE Facturas SET numero_cliente=?, total_a_pagar=?, preventista=?, fecha=? WHERE numero_factura=?", 
            (numero_cliente, total, preventista, fecha, numero_factura)
        )
        if cursor.rowcount != 1: 
            raise ValueError(f"No existe la factura #{numero_factura} para actualizar.")
        cursor.execute("DELETE FROM Detalle_Factura WHERE numero_factura = ?", (numero_factura,))
        cursor.executemany(
            "INSERT INTO Detalle_Factura (numero_factura, codigo_articulo, nombre_personalizado, precio_unitario, unidades, total_linea) VALUES (?, ?, ?, ?, ?, ?)", 
            [(numero_factura, cod, nombre, precio, cantidad, subtotal) for cod, nombre, precio, cantidad, subtotal in detalles]
        )

def reiniciar_facturas_a_cero():
    """Borra todas las facturas locales y reinicia el contador para que la próxima sea la #1."""
    with conexion_segura() as conexion:
        cursor = conexion.cursor()
        cursor.execute("DELETE FROM Detalle_Factura")
        cursor.execute("DELETE FROM Facturas")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('Facturas', 'Detalle_Factura')")

def generar_semilla_desde_db_madre():
    """En la PC: extrae Clientes y Productos de sistema_ventas.db (sin facturas) para que viajen en el APK."""
    if not ruta_db_madre or not os.path.exists(ruta_db_madre):
        return
    try:
        conn_m = sqlite3.connect(ruta_db_madre)
        cur_m = conn_m.cursor()
        clientes_m = cur_m.execute("SELECT numero_cliente, nombre_apellido, direccion_entrega FROM Clientes ORDER BY numero_cliente").fetchall()
        productos_m = cur_m.execute("SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos ORDER BY codigo_articulo").fetchall()
        conn_m.close()

        datos_semilla = {
            "clientes": [{"id": c[0], "nombre": c[1], "direccion": c[2] or ""} for c in clientes_m],
            "productos": [{"codigo": p[0], "nombre": p[1], "precio": float(p[2] or 0)} for p in productos_m],
        }
        with open(ruta_semilla_catalogo, "w", encoding="utf-8") as f:
            json.dump(datos_semilla, f, ensure_ascii=False)
    except Exception as e:
        print("Aviso semilla:", e)

def inicializar_base_datos():
    # Si estamos en la PC y existe sistema_ventas.db, actualizamos el catálogo semilla limpio
    generar_semilla_desde_db_madre()

    db('''CREATE TABLE IF NOT EXISTS Clientes (numero_cliente INTEGER PRIMARY KEY AUTOINCREMENT, nombre_apellido TEXT NOT NULL, direccion_entrega TEXT)''')
    db('''CREATE TABLE IF NOT EXISTS Productos (codigo_articulo TEXT PRIMARY KEY, nombre_articulo TEXT NOT NULL, precio_unitario REAL NOT NULL)''')
    db('''CREATE TABLE IF NOT EXISTS Facturas (numero_factura INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, numero_cliente INTEGER, total_a_pagar REAL NOT NULL, preventista TEXT)''')
    db('''CREATE TABLE IF NOT EXISTS Detalle_Factura (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_factura INTEGER, codigo_articulo TEXT, nombre_personalizado TEXT, precio_unitario REAL, unidades REAL, total_linea REAL)''')
    db('''CREATE TABLE IF NOT EXISTS Preventistas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, pin TEXT NOT NULL)''')

    usuarios_permitidos = [("ABR042026", "4444"), ("ABR012026", "1111"), ("ABR022026", "2222"), ("ABR032026", "3333")]
    for nombre, pin in usuarios_permitidos:
        if db("SELECT COUNT(*) FROM Preventistas WHERE nombre=?", (nombre,), fetch=True)[0] == 0:
            db("INSERT INTO Preventistas (nombre, pin) VALUES (?, ?)", (nombre, pin))

    # Si la base del APK recién se instala, cargamos el padrón de Clientes y Productos (PERO 0 FACTURAS)
    cant_cli = db("SELECT COUNT(*) FROM Clientes", fetch=True)[0]
    cant_prod = db("SELECT COUNT(*) FROM Productos", fetch=True)[0]

    if (cant_cli == 0 or cant_prod == 0) and os.path.exists(ruta_semilla_catalogo):
        try:
            with open(ruta_semilla_catalogo, "r", encoding="utf-8") as f:
                semilla = json.load(f)
            with conexion_segura() as conexion:
                cursor = conexion.cursor()
                if cant_cli == 0:
                    for c in semilla.get("clientes", []):
                        cursor.execute(
                            "INSERT OR IGNORE INTO Clientes (numero_cliente, nombre_apellido, direccion_entrega) VALUES (?, ?, ?)",
                            (c["id"], c["nombre"], c["direccion"])
                        )
                if cant_prod == 0:
                    for p in semilla.get("productos", []):
                        cursor.execute(
                            "INSERT OR IGNORE INTO Productos (codigo_articulo, nombre_articulo, precio_unitario) VALUES (?, ?, ?)",
                            (p["codigo"], p["nombre"], p["precio"])
                        )
        except Exception as e:
            print("Error cargando semilla:", e)

    if db("SELECT COUNT(*) FROM Clientes", fetch=True)[0] == 0:
        db("INSERT INTO Clientes (nombre_apellido, direccion_entrega) VALUES ('CONSUMIDOR FINAL', 'PERICO')")

    if db("SELECT COUNT(*) FROM Productos", fetch=True)[0] == 0:
        lista_productos_base = [
            ("ART-001", "SODA MARINARO 1,5 LT X 6", 5500.0), ("ART-002", "SODA SIFON 2LT X 4", 6700.0), 
            ("ART-003", "AGUA MARINARO 500 ML X 12", 7000.0), ("ART-004", "SODA MARINARO 500 ML X 12", 7000.0), 
            ("ART-005", "ICE LIMONADA 500 ML X 12", 8000.0), ("ART-006", "ICE GRANADINA 500 ML X 12", 8000.0), 
            ("ART-007", "ICE COLA 500ML X 12", 8000.0), ("ART-008", "ICE MANZANA 500 ML X12", 8000.0), 
            ("ART-009", "REAKTOR 500 ML X 8", 14700.0), ("ART-010", "AGUA MARINARO 1,5 X 6", 6000.0)
        ]
        for cod, nom, pre in lista_productos_base: 
            db("INSERT INTO Productos (codigo_articulo, nombre_articulo, precio_unitario) VALUES (?, ?, ?)", (cod, nom, pre))

    indices = [
        "CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON Facturas(fecha)", 
        "CREATE INDEX IF NOT EXISTS idx_facturas_cliente_fecha ON Facturas(numero_cliente, fecha)", 
        "CREATE INDEX IF NOT EXISTS idx_facturas_preventista_fecha ON Facturas(preventista, fecha)", 
        "CREATE INDEX IF NOT EXISTS idx_detalle_factura ON Detalle_Factura(numero_factura)", 
        "CREATE INDEX IF NOT EXISTS idx_detalle_producto ON Detalle_Factura(codigo_articulo)", 
        "CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON Clientes(nombre_apellido)"
    ]
    for sql in indices:
        db(sql)

    try: 
        db("PRAGMA journal_mode=WAL")
        db("PRAGMA synchronous=NORMAL")
    except Exception: 
        pass

# ==========================================
# 2. MOTORES DE REPORTES PDF 
# ==========================================
def limpiar_texto(texto): 
    return str(texto).encode('latin-1', 'replace').decode('latin-1')

def generar_pdf_facturas(ruta_destino, num_factura=None, fecha_consulta=None):
    from fpdf import FPDF 
    
    if num_factura: 
        facturas = db("SELECT numero_factura FROM Facturas WHERE numero_factura = ?", (num_factura,), fetch=True, fetchall=True)
    elif fecha_consulta: 
        facturas = db("SELECT numero_factura FROM Facturas WHERE fecha = ?", (fecha_consulta,), fetch=True, fetchall=True)
    else: 
        return False
        
    if not facturas: 
        return False
    
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(False)
    
    def dibujar_lado(x_base, factura, lineas, tipo_copia):
        w_total = 135
        pdf.set_xy(x_base, 7)
        pdf.set_font("Arial", 'B', 18)
        pdf.cell(w_total, 8, limpiar_texto("XIOMI Distribuidora"), ln=1, align='C')
        
        pdf.set_xy(x_base, 16)
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(w_total, 5, limpiar_texto(f"Factura - {tipo_copia}"), ln=1, align='C')
        
        pdf.set_xy(x_base, 22.5)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(w_total, 5, limpiar_texto(str(factura[2])[:45]), ln=1, align='L')
        
        pdf.set_xy(x_base, 27.5)
        pdf.set_font("Arial", '', 9)
        pdf.cell(w_total, 5, limpiar_texto((str(factura[3]) if factura[3] else "Sin dirección")[:55]), ln=1, align='L')

        try:
            fecha_obj = datetime.strptime(factura[1], "%Y-%m-%d")
            venc_fmt = (fecha_obj + timedelta(days=30)).strftime("%d/%m/%Y")
            fecha_fmt = fecha_obj.strftime("%d/%m/%Y")
        except Exception: 
            fecha_fmt = factura[1]
            venc_fmt = factura[1]

        y_ctrl = 34
        pdf.set_fill_color(210, 210, 210)
        pdf.set_font("Arial", 'B', 9)
        pdf.set_xy(x_base, y_ctrl)
        
        pdf.cell(23, 6, limpiar_texto("N° Cliente"), border=1, align='C', fill=True)
        pdf.cell(23, 6, limpiar_texto("N° Factura"), border=1, align='C', fill=True)
        pdf.cell(17, 6, limpiar_texto("Página"), border=1, align='C', fill=True)
        pdf.cell(36, 6, limpiar_texto("Fecha Factura"), border=1, align='C', fill=True)
        pdf.cell(36, 6, limpiar_texto("Vencimiento"), border=1, align='C', fill=True)
        
        pdf.set_xy(x_base, y_ctrl + 6)
        pdf.set_font("Arial", '', 9)
        pdf.cell(23, 6, limpiar_texto(str(factura[6])), border=1, align='C')
        pdf.cell(23, 6, limpiar_texto(str(factura[0])), border=1, align='C')
        pdf.cell(17, 6, limpiar_texto("1 / 1"), border=1, align='C')
        pdf.cell(36, 6, limpiar_texto(fecha_fmt), border=1, align='C')
        pdf.cell(36, 6, limpiar_texto(venc_fmt), border=1, align='C')
        
        y_items = y_ctrl + 15
        pdf.set_xy(x_base, y_items)
        pdf.set_fill_color(210, 210, 210)
        pdf.set_font("Arial", 'B', 9)
        
        pdf.cell(65, 6.5, limpiar_texto("Artículo"), border=1, align='L', fill=True)
        pdf.cell(18, 6.5, limpiar_texto("Cantidad"), border=1, align='R', fill=True)
        pdf.cell(24, 6.5, limpiar_texto("Precio"), border=1, align='R', fill=True)
        pdf.cell(28, 6.5, limpiar_texto("Importe total"), border=1, align='R', fill=True)
        
        y_fila = y_items + 6.5
        pdf.set_font("Arial", '', 9)
        filas_cargadas = 0
        
        for art, cant, pre, tot in lineas:
            cant_fmt = str(int(cant)) if cant == int(cant) else str(cant).replace('.', ',')
            pdf.set_xy(x_base, y_fila)
            pdf.cell(65, 6.2, limpiar_texto(str(art)[:32]), border='LR', align='L')
            pdf.cell(18, 6.2, limpiar_texto(cant_fmt), border='LR', align='R')
            pdf.cell(24, 6.2, limpiar_texto(formato_ars(pre or 0)), border='LR', align='R')
            pdf.cell(28, 6.2, limpiar_texto(formato_ars(tot or 0)), border='LR', align='R')
            y_fila += 6.2
            filas_cargadas += 1
            
        for _ in range(max(0, 20 - filas_cargadas)):
            pdf.set_xy(x_base, y_fila)
            pdf.cell(65, 6.2, "", border='LR')
            pdf.cell(18, 6.2, "", border='LR')
            pdf.cell(24, 6.2, "", border='LR')
            pdf.cell(28, 6.2, "", border='LR')
            y_fila += 6.2
        
        pdf.set_xy(x_base, y_fila)
        pdf.cell(w_total, 0, "", border='T')
        y_tot = y_fila + 3
        pdf.set_xy(x_base + 50, y_tot)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(57, 7, limpiar_texto("Importe total:"), align='R')
        pdf.cell(28, 7, limpiar_texto(f"$ {formato_ars(factura[4])}"), align='R')
        
        pdf.set_xy(x_base, y_tot + 8)
        pdf.set_font("Arial", '', 10)
        pdf.cell(w_total, 6, limpiar_texto(f"Vendedor asignado: {factura[5] if len(factura) > 5 and factura[5] else 'ADMIN'}"), align='L')

    for (f_id,) in facturas:
        factura = db('''SELECT f.numero_factura, f.fecha, c.nombre_apellido, c.direccion_entrega, f.total_a_pagar, f.preventista, c.numero_cliente FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente WHERE f.numero_factura = ?''', (f_id,), fetch=True)
        if not factura: 
            continue
        lineas = db('''SELECT COALESCE(d.nombre_personalizado, p.nombre_articulo, d.codigo_articulo), d.unidades, d.precio_unitario, d.total_linea FROM Detalle_Factura d LEFT JOIN Productos p ON d.codigo_articulo = p.codigo_articulo WHERE d.numero_factura = ?''', (f_id,), fetch=True, fetchall=True)
        
        pdf.add_page()
        pdf.set_draw_color(180, 180, 180)
        for y_dot in range(6, 204, 4): 
            pdf.line(148.5, y_dot, 148.5, y_dot + 2)
        pdf.set_draw_color(0, 0, 0)
        dibujar_lado(7, factura, lineas, "DUPLICADO")
        dibujar_lado(155, factura, lineas, "ORIGINAL")
    
    pdf.output(ruta_destino)
    return True

def generar_reporte_generico(ruta_destino, query, parametros, titulo, subtitulo):
    from fpdf import FPDF
    productos = db(query, parametros, fetch=True, fetchall=True)
    if not productos: 
        return False
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(190, 10, txt=limpiar_texto(titulo), ln=True, align='C')
    pdf.set_font("Arial", size=11)
    pdf.cell(190, 8, txt=limpiar_texto(subtitulo), ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_fill_color(210, 210, 210)
    pdf.set_font("Arial", 'B', 10)
    for col, w in [("Codigo", 25), ("Descripcion", 65), ("Precio Unit.", 30), ("Total Unid.", 30)]: 
        pdf.cell(w, 10, limpiar_texto(col), border=1, align='C', fill=True)
    pdf.cell(40, 10, limpiar_texto("Total"), border=1, ln=True, align='C', fill=True)
    
    pdf.set_font("Arial", size=10)
    unidades_t, dinero_t = 0, 0
    for cod, nom, pre, uni, tot in productos:
        uni_fmt = str(int(uni)) if uni == int(uni) else str(uni).replace('.', ',')
        pdf.cell(25, 9, limpiar_texto(str(cod)), border='LR', align='C')
        pdf.cell(65, 9, limpiar_texto(str(nom)), border='LR', align='C')
        pdf.cell(30, 9, limpiar_texto(f"$ {formato_ars(pre)}"), border='LR', align='C')
        pdf.cell(30, 9, limpiar_texto(uni_fmt), border='LR', align='C')
        pdf.cell(40, 9, limpiar_texto(f"$ {formato_ars(tot)}"), border='LR', ln=True, align='C')
        unidades_t += uni
        dinero_t += tot
        
    pdf.cell(190, 0, "", border='T', ln=True)
    pdf.ln(5)
    
    uni_t_fmt = str(int(unidades_t)) if unidades_t == int(unidades_t) else str(unidades_t).replace('.', ',')
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(120, 10, limpiar_texto("TOTAL GENERAL:"), border=1, align='R')
    pdf.cell(30, 10, limpiar_texto(uni_t_fmt), border=1, align='C')
    pdf.cell(40, 10, limpiar_texto(f"$ {formato_ars(dinero_t)}"), border=1, ln=True, align='C')
    
    pdf.output(ruta_destino)
    return True

def generar_reporte_preventistas(ruta_destino, f_inicio, f_fin):
    from fpdf import FPDF
    if f_inicio == f_fin: 
        datos = db("SELECT preventista, COUNT(numero_factura), SUM(total_a_pagar) FROM Facturas WHERE fecha = ? GROUP BY preventista", (f_inicio,), fetch=True, fetchall=True)
        periodo = f"Fecha consultada: {f_inicio}"
    else: 
        datos = db("SELECT preventista, COUNT(numero_factura), SUM(total_a_pagar) FROM Facturas WHERE fecha BETWEEN ? AND ? GROUP BY preventista", (f_inicio, f_fin), fetch=True, fetchall=True)
        periodo = f"Periodo: {f_inicio} al {f_fin}"
        
    if not datos: 
        return False
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(190, 10, txt=limpiar_texto("RENDICION DE CAJA POR PREVENTISTA"), ln=True, align='C')
    pdf.set_font("Arial", size=11)
    pdf.cell(190, 8, txt=limpiar_texto(periodo), ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_fill_color(210, 210, 210)
    pdf.set_font("Arial", 'B', 12)
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
        
    pdf.cell(190, 0, "", border='T', ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(70, 10, limpiar_texto("TOTAL DE VENTAS:"), border=1, align='R')
    pdf.cell(50, 10, limpiar_texto(str(total_tickets)), border=1, align='C')
    pdf.cell(70, 10, limpiar_texto(f"$ {formato_ars(total_dinero)}"), border=1, ln=True, align='C')
    
    pdf.output(ruta_destino)
    return True

def generar_reporte_total_preventistas_fecha(ruta_destino, fecha_sel): 
    return generar_reporte_preventistas(ruta_destino, fecha_sel, fecha_sel)

def generar_reporte_articulos_por_usuario_dia(ruta_destino, fecha_sel, usuario_sel):
    query = "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, SUM(d.unidades), SUM(d.total_linea) FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo JOIN Facturas f ON d.numero_factura = f.numero_factura WHERE f.fecha = ? AND f.preventista = ? GROUP BY d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario"
    return generar_reporte_generico(ruta_destino, query, (fecha_sel, usuario_sel), "REPORTE DIARIO POR USUARIO", f"Usuario: {usuario_sel} | Fecha: {fecha_sel}")

def generar_reporte_articulos_por_usuario_rango(ruta_destino, f_inicio, f_fin, usuario_sel):
    query = "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, SUM(d.unidades), SUM(d.total_linea) FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo JOIN Facturas f ON d.numero_factura = f.numero_factura WHERE f.fecha BETWEEN ? AND ? AND f.preventista = ? GROUP BY d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario"
    return generar_reporte_generico(ruta_destino, query, (f_inicio, f_fin, usuario_sel), "BALANCE CONSOLIDADO POR USUARIO", f"Usuario: {usuario_sel} | Periodo: {f_inicio} al {f_fin}")

def generar_reporte_clientes_dia(ruta_destino, f_consulta):
    from fpdf import FPDF
    datos = db("SELECT c.nombre_apellido, c.direccion_entrega, SUM(f.total_a_pagar) FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente WHERE f.fecha = ? GROUP BY c.numero_cliente", (f_consulta,), fetch=True, fetchall=True)
    if not datos: 
        return False
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(190, 10, txt=limpiar_texto("LISTADO DE COBRANZA DIARIA"), ln=True, align='C')
    pdf.set_font("Arial", size=11)
    pdf.cell(190, 8, txt=limpiar_texto(f"Fecha: {f_consulta}"), ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_fill_color(210, 210, 210)
    pdf.set_font("Arial", 'B', 11)
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
    
    pdf.output(ruta_destino)
    return True

# ==========================================
# 3. PALETA DE COLORES (ESTILO APK IMÁGENES)
# ==========================================
COLORES = {
    "header_blue": "#2C4B70",      # Barra superior azul pizarra (Imágenes 1 y 3)
    "fab_blue": "#3B5F8A",         # Botón flotante + azul (Imagen 1)
    "header_green": "#4B6B0A",     # Barra verde oliva Seleccionar cliente (Imagen 2)
    "header_purple": "#5A3D7A",    # Barra violeta Seleccionar artículo (Imagen 4)
    "strip_cyan": "#EBF5FA",       # Franja celeste Artículos facturados (Imagen 3)
    "filter_bar": "#F5F5F5",       # Barra Pulsa para filtrar lista (Imagen 1)
    "divider": "#D6D6D6",          # Líneas divisorias finas
    "text": "#000000",             # Texto negro puro en negrita
    "muted": "#555555",
    "surface": "#FFFFFF",
    "danger": "#DC2626",
    "success": "#059669",
    "info": "#2563EB",
}

def mostrar_snack(page, mensaje, bgcolor="#2C4B70"):
    snack = ft.SnackBar(content=ft.Text(mensaje, color="white", weight="bold"), bgcolor=bgcolor, duration=3500)
    try: 
        page.open(snack)
    except Exception: 
        page.snack_bar = snack
        snack.open = True
        page.update()

def mostrar_dialogo(page, dialogo):
    try: 
        page.open(dialogo)
    except Exception: 
        page.dialog = dialogo
        dialogo.open = True
        page.update()

def cerrar_dialogo(page, dialogo=None):
    dialog = dialogo or getattr(page, "dialog", None)
    if not dialog: 
        return
    try: 
        page.close(dialog)
    except Exception: 
        dialog.open = False
        page.update()

# ==========================================
# 4. INTERFAZ GRÁFICA ESTILO APK (FACTURAS DESDE CERO)
# ==========================================
def main(page: ft.Page):
    registrar_inicio("ENTRADA A main()")
    try:
        page.title = "XIOMI Distribuidora"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = "#FFFFFF"
        page.padding = 0
        page.spacing = 0
        page.window_width = 415
        page.window_height = 680
        try:
            page.window.width = 415
            page.window.height = 680
        except Exception:
            pass

        # Pantalla mínima inmediata: permite distinguir un fallo de UI de uno de base de datos.
        page.add(
            ft.Container(
                expand=True,
                alignment=ft.Alignment(0, 0),
                bgcolor="#FFFFFF",
                content=ft.Column(
                    [
                        ft.ProgressRing(width=38, height=38, stroke_width=4, color="#2C4B70"),
                        ft.Text("XIOMI DISTRIBUIDORA", size=21, weight="bold", color="#2C4B70"),
                        ft.Text("Preparando la aplicación...", size=14, color="#555555"),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=18,
                ),
            )
        )
        page.update()
        registrar_inicio("PANTALLA DE ARRANQUE PREPARADA; la base de datos se inicializará sin bloquear la interfaz")

        carrito = {}
        estado_carrito = {
            "editando": False,
            "id_factura": None,
            "cargado": False,
            "id_cliente": None,
            "fecha": date.today().strftime("%Y-%m-%d"),
            "nota_texto": "",
        }
        estado_historial_cli = {"id_cliente": None}

        def generar_siguiente_codigo():
            try:
                fila = db("SELECT COALESCE(MAX(CAST(SUBSTR(codigo_articulo, 5) AS INTEGER)), 0) FROM Productos WHERE codigo_articulo GLOB 'ART-[0-9]*'", fetch=True)
                max_num = int(fila[0] or 0) if fila else 0
                candidato = max_num + 1
                while db("SELECT 1 FROM Productos WHERE codigo_articulo = ? LIMIT 1", (f"ART-{candidato:03d}",), fetch=True): 
                    candidato += 1
                return f"ART-{candidato:03d}"
            except Exception:
                return f"ART-{int(time.time()) % 10000:04d}"

        overlay_modal = ft.Container(visible=False, expand=True)

        def cerrar_overlay(_=None):
            overlay_modal.visible = False
            overlay_modal.content = None
            page.update()

        def confirmar_reinicio_facturas(_=None):
            cerrar_overlay()

            def ejecutar_reinicio(_):
                reiniciar_facturas_a_cero()
                cerrar_dialogo(page, dlg_reset)
                mostrar_snack(page, "✅ Facturero reiniciado a cero (Próxima factura: #1)", COLORES["success"])
                cambiar_pantalla()

            dlg_reset = ft.AlertDialog(
                title=ft.Text("Reiniciar Facturas a Cero", weight="bold"),
                content=ft.Text("¿Querés borrar todas las facturas de este dispositivo y reiniciar el contador a #1?\n(Los clientes y artículos se mantienen intactos)."),
                actions=[
                    ft.TextButton("CANCELAR", on_click=lambda _: cerrar_dialogo(page, dlg_reset)),
                    ft.Button("SÍ, DEJAR EN CERO", bgcolor=COLORES["danger"], color="white", on_click=ejecutar_reinicio),
                ]
            )
            mostrar_dialogo(page, dlg_reset)

        def abrir_menu_lateral(_=None):
            usuario_actual = page.session.store.get("usuario") or "ADMIN"

            def ir_ruta(ruta):
                cerrar_overlay()
                page.navigate(ruta)

            def cerrar_sesion(_):
                cerrar_overlay()
                page.session.store.clear()
                page.navigate("/login")

            def item_menu(icono, titulo, ruta, activo=False):
                return ft.Container(
                    padding=ft.padding.symmetric(horizontal=18, vertical=13),
                    bgcolor="#EBF5FA" if activo else "transparent",
                    ink=True,
                    on_click=lambda _: ir_ruta(ruta),
                    content=ft.Row([
                        ft.Icon(icono, color=COLORES["header_blue"] if activo else "#333333", size=22),
                        ft.Text(titulo, size=15, weight="bold", color=COLORES["header_blue"] if activo else "#111111")
                    ], spacing=16)
                )

            panel_menu = ft.Container(
                width=285,
                bgcolor="#FFFFFF",
                shadow=ft.BoxShadow(blur_radius=20, color="#66000000"),
                content=ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.only(left=20, right=20, top=28, bottom=18),
                        width=float("inf"),
                        content=ft.Column([
                            ft.Icon("storefront", color="white", size=34),
                            ft.Text("XIOMI Distribuidora", size=18, weight="bold", color="white"),
                            ft.Text(f"Vendedor: {usuario_actual}", size=13, color="#D0E1F9", weight="bold"),
                        ], spacing=4)
                    ),
                    ft.Column([
                        item_menu("receipt_long", "Facturas", "/", page.route in ("/", "/pedidos_dia")),
                        item_menu("people", "Clientes (Padrón y Excel)", "/agregar_cliente", page.route == "/agregar_cliente"),
                        item_menu("history", "Historial del Cliente", "/historial_cliente", page.route == "/historial_cliente"),
                        item_menu("inventory_2", "Artículos (Catálogo y Excel)", "/agregar_producto", page.route == "/agregar_producto"),
                        ft.Divider(height=1, color=COLORES["divider"]),
                        item_menu("picture_as_pdf", "Reportes y Caja (PDF)", "/reportes", page.route == "/reportes"),
                        item_menu("swap_horiz", "Reasignar Tickets", "/reasignar_tickets", page.route == "/reasignar_tickets"),
                        item_menu("auto_awesome", "Carga Inteligente (IA)", "/carga_inteligente", page.route == "/carga_inteligente"),
                        ft.Divider(height=1, color=COLORES["divider"]),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=18, vertical=13),
                            ink=True,
                            on_click=confirmar_reinicio_facturas,
                            content=ft.Row([
                                ft.Icon("restart_alt", color="#D97706", size=22),
                                ft.Text("Reiniciar Facturas a Cero", size=14, weight="bold", color="#D97706")
                            ], spacing=16)
                        ),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=18, vertical=13),
                            ink=True,
                            on_click=cerrar_sesion,
                            content=ft.Row([
                                ft.Icon("logout", color=COLORES["danger"], size=22),
                                ft.Text("Cerrar sesión", size=15, weight="bold", color=COLORES["danger"])
                            ], spacing=16)
                        )
                    ], spacing=0, scroll="auto", expand=True)
                ], spacing=0, expand=True)
            )

            overlay_modal.content = ft.Row([
                panel_menu,
                ft.Container(expand=True, bgcolor="#77000000", on_click=cerrar_overlay)
            ], expand=True, spacing=0)
            overlay_modal.visible = True
            page.update()

        # ==========================================================
        # MODAL IMAGEN 2: "Seleccionar al cliente" (VERDE OLIVA)
        # ==========================================================
        def mostrar_modal_seleccionar_cliente(al_elegir_cliente):
            lista_cli_controls = ft.ListView(expand=True, spacing=0)
            txt_buscar_cli = ft.TextField(
                hint_text="Buscar por nombre, ID o dirección...",
                bgcolor="white",
                height=40,
                text_size=14,
                content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
                border_radius=4,
                visible=False
            )

            def cargar_clientes_modal(filtro=""):
                lista_cli_controls.controls.clear()
                f_str = (filtro or "").strip().upper()
                if f_str:
                    filas = db(
                        "SELECT numero_cliente, nombre_apellido, direccion_entrega FROM Clientes WHERE UPPER(nombre_apellido) LIKE ? OR UPPER(COALESCE(direccion_entrega,'')) LIKE ? OR CAST(numero_cliente AS TEXT) LIKE ? ORDER BY numero_cliente ASC LIMIT 150",
                        (f"%{f_str}%", f"%{f_str}%", f"%{f_str}%"), fetch=True, fetchall=True
                    )
                else:
                    filas = db(
                        "SELECT numero_cliente, nombre_apellido, direccion_entrega FROM Clientes ORDER BY numero_cliente ASC LIMIT 150",
                        fetch=True, fetchall=True
                    )

                if not filas:
                    lista_cli_controls.controls.append(
                        ft.Container(padding=24, content=ft.Text("No se encontraron clientes.", size=14, weight="bold", color=COLORES["muted"]))
                    )
                else:
                    for id_c, nom, direc in filas:
                        dir_mostrar = direc if (direc and str(direc).strip()) else "....."

                        def click_cli(c_id=id_c):
                            def _hacer(_):
                                cerrar_overlay()
                                al_elegir_cliente(c_id)
                            return _hacer

                        lista_cli_controls.controls.append(
                            ft.Container(
                                bgcolor="#FFFFFF",
                                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                                border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                ink=True,
                                on_click=click_cli(id_c),
                                content=ft.Column([
                                    ft.Text(f"{id_c}  {nom}", size=15, weight="bold", color="#000000", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(str(dir_mostrar), size=13, weight="bold", color="#111111", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ], spacing=3)
                            )
                        )
                page.update()

            def toggle_buscador_cli(_):
                txt_buscar_cli.visible = not txt_buscar_cli.visible
                if not txt_buscar_cli.visible:
                    txt_buscar_cli.value = ""
                    cargar_clientes_modal("")
                page.update()

            txt_buscar_cli.on_change = lambda e: cargar_clientes_modal(e.control.value)

            def abrir_nuevo_cliente_rapido(_):
                inp_nom = ft.TextField(label="Nombre y Apellido", autofocus=True)
                inp_dir = ft.TextField(label="Dirección de entrega")

                def guardar_nuevo(_):
                    nom_val = (inp_nom.value or "").strip().upper()
                    dir_val = (inp_dir.value or "").strip().upper()
                    if not nom_val:
                        mostrar_snack(page, "Ingresá el nombre del cliente", COLORES["danger"])
                        return
                    nuevo_id = db("INSERT INTO Clientes (nombre_apellido, direccion_entrega) VALUES (?, ?)", (nom_val, dir_val))
                    cerrar_dialogo(page, dlg_cli)
                    cerrar_overlay()
                    al_elegir_cliente(nuevo_id)

                dlg_cli = ft.AlertDialog(
                    title=ft.Text("Nuevo Cliente", weight="bold"),
                    content=ft.Column([inp_nom, inp_dir], tight=True, spacing=12),
                    actions=[
                        ft.TextButton("CANCELAR", on_click=lambda _: cerrar_dialogo(page, dlg_cli)),
                        ft.Button("GUARDAR", bgcolor=COLORES["header_green"], color="white", on_click=guardar_nuevo),
                    ]
                )
                mostrar_dialogo(page, dlg_cli)

            tarjeta_modal = ft.Container(
                margin=ft.margin.symmetric(horizontal=16, vertical=18),
                bgcolor="#FFFFFF",
                expand=True,
                shadow=ft.BoxShadow(blur_radius=24, color="#77000000"),
                content=ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_green"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Column([
                            ft.Row([
                                ft.IconButton("arrow_back", icon_color="white", on_click=cerrar_overlay),
                                ft.Text("Seleccionar al cliente", size=18, weight="bold", color="white", expand=True),
                                ft.IconButton("search", icon_color="white", on_click=toggle_buscador_cli),
                            ], spacing=4),
                            txt_buscar_cli,
                        ], spacing=4)
                    ),
                    ft.Container(content=lista_cli_controls, expand=True),
                    ft.Container(
                        bgcolor="#FFFFFF",
                        padding=ft.padding.symmetric(vertical=8),
                        alignment=ft.Alignment(0, 0),
                        content=ft.Container(
                            width=50,
                            height=50,
                            border_radius=25,
                            bgcolor=COLORES["header_green"],
                            alignment=ft.Alignment(0, 0),
                            shadow=ft.BoxShadow(blur_radius=8, color="#55000000", offset=ft.Offset(0, 2)),
                            ink=True,
                            on_click=abrir_nuevo_cliente_rapido,
                            content=ft.Icon("add", color="white", size=28)
                        )
                    )
                ], spacing=0, expand=True)
            )

            overlay_modal.content = ft.Container(
                expand=True,
                bgcolor="#77000000",
                content=tarjeta_modal
            )
            overlay_modal.visible = True
            cargar_clientes_modal("")

        # ==========================================================
        # MODAL IMAGEN 4: "Seleccionar el artículo" (VIOLETA) + "Añadir artículo"
        # ==========================================================
        def mostrar_modal_editar_linea_articulo(cod_art, nom_art, pre_art, cant_inicial=1, al_guardar=None):
            inp_nombre = ft.TextField(label="Artículo / Descripción en factura", value=str(nom_art), border="underlined", text_style=ft.TextStyle(weight="bold", size=15))
            inp_cantidad = ft.TextField(label="Cantidad", value=str(cant_inicial), keyboard_type="number", border="underlined", text_style=ft.TextStyle(weight="bold", size=16))
            inp_precio = ft.TextField(label="Precio unitario (ARS)", value=str(pre_art), keyboard_type="number", border="underlined", text_style=ft.TextStyle(weight="bold", size=16))
            txt_subtotal_preview = ft.Text(f"Importe total: {formato_ars_corto(float(cant_inicial) * float(pre_art))} ARS", size=16, weight="bold", color=COLORES["header_blue"])

            def recalcular_preview(_=None):
                try:
                    c_val = float((inp_cantidad.value or "0").replace(",", "."))
                    p_val = float((inp_precio.value or "0").replace(",", "."))
                    txt_subtotal_preview.value = f"Importe total: {formato_ars_corto(c_val * p_val)} ARS"
                except Exception:
                    txt_subtotal_preview.value = "Importe total: 0 ARS"
                page.update()

            inp_cantidad.on_change = recalcular_preview
            inp_precio.on_change = recalcular_preview

            def confirmar_linea(_):
                try:
                    c_val = float((inp_cantidad.value or "0").replace(",", "."))
                    p_val = float((inp_precio.value or "0").replace(",", "."))
                    if c_val <= 0 or p_val < 0:
                        mostrar_snack(page, "Revisá la cantidad y el precio", COLORES["danger"])
                        return
                except ValueError:
                    mostrar_snack(page, "Cantidad o precio inválido", COLORES["danger"])
                    return

                cant_final = int(c_val) if c_val.is_integer() else c_val
                nom_final = (inp_nombre.value or nom_art).strip().upper()
                carrito[cod_art] = {
                    "nombre": nom_final,
                    "precio": p_val,
                    "cantidad": cant_final
                }
                cerrar_overlay()
                if al_guardar:
                    al_guardar()

            def eliminar_linea(_):
                carrito.pop(cod_art, None)
                cerrar_overlay()
                if al_guardar:
                    al_guardar()

            pantalla_anadir = ft.Container(
                bgcolor="#FFFFFF",
                expand=True,
                content=ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("arrow_back", icon_color="white", on_click=cerrar_overlay),
                            ft.Text("Añadir artículo", size=18, weight="bold", color="white", expand=True),
                            ft.TextButton(
                                content=ft.Text("GUARDAR", size=15, weight="bold", color="white"),
                                on_click=confirmar_linea
                            )
                        ])
                    ),
                    ft.Container(
                        padding=20,
                        content=ft.Column([
                            ft.Row([
                                ft.Text(f"Código: {cod_art}", size=13, weight="bold", color=COLORES["muted"], expand=True),
                                ft.TextButton("Cambiar artículo", icon="swap_horiz", on_click=lambda _: mostrar_modal_seleccionar_articulo(al_guardar))
                            ]),
                            inp_nombre,
                            inp_cantidad,
                            inp_precio,
                            ft.Container(height=8),
                            txt_subtotal_preview,
                            ft.Container(height=16),
                            ft.OutlinedButton(
                                "QUITAR ARTÍCULO DE LA FACTURA",
                                icon="delete_outline",
                                style=ft.ButtonStyle(color=COLORES["danger"]),
                                visible=(cod_art in carrito),
                                on_click=eliminar_linea
                            )
                        ], spacing=12)
                    )
                ], spacing=0, expand=True)
            )

            overlay_modal.content = pantalla_anadir
            overlay_modal.visible = True
            page.update()

        def mostrar_modal_seleccionar_articulo(al_actualizar_carrito):
            lista_art_controls = ft.ListView(expand=True, spacing=0)
            txt_buscar_art = ft.TextField(
                hint_text="Buscar artículo por nombre o código...",
                bgcolor="white",
                height=40,
                text_size=14,
                content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
                border_radius=4,
                visible=False
            )

            def cargar_articulos_modal(filtro=""):
                lista_art_controls.controls.clear()
                f_str = (filtro or "").strip().upper()
                if f_str:
                    filas = db(
                        "SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos WHERE UPPER(nombre_articulo) LIKE ? OR UPPER(codigo_articulo) LIKE ? ORDER BY nombre_articulo ASC LIMIT 150",
                        (f"%{f_str}%", f"%{f_str}%"), fetch=True, fetchall=True
                    )
                else:
                    filas = db(
                        "SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos ORDER BY nombre_articulo ASC LIMIT 150",
                        fetch=True, fetchall=True
                    )

                if not filas:
                    lista_art_controls.controls.append(
                        ft.Container(padding=24, content=ft.Text("No se encontraron artículos.", size=14, weight="bold", color=COLORES["muted"]))
                    )
                else:
                    for cod, nom, pre in filas:
                        def click_art(c_a=cod, n_a=nom, p_a=pre):
                            def _sel(_):
                                cant_actual = carrito.get(c_a, {}).get("cantidad", 1)
                                mostrar_modal_editar_linea_articulo(c_a, n_a, p_a, cant_inicial=cant_actual, al_guardar=al_actualizar_carrito)
                            return _sel

                        lista_art_controls.controls.append(
                            ft.Container(
                                bgcolor="#FFFFFF",
                                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                                border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                ink=True,
                                on_click=click_art(cod, nom, pre),
                                content=ft.Column([
                                    ft.Row([
                                        ft.Text(str(nom), size=15, weight="bold", color="#000000", expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ]),
                                    ft.Row([
                                        ft.Text(f"{formato_ars_corto(pre)} ARS", size=15, weight="bold", color="#000000"),
                                    ], alignment=ft.MainAxisAlignment.END)
                                ], spacing=2)
                            )
                        )
                page.update()

            def toggle_buscador_art(_):
                txt_buscar_art.visible = not txt_buscar_art.visible
                if not txt_buscar_art.visible:
                    txt_buscar_art.value = ""
                    cargar_articulos_modal("")
                page.update()

            txt_buscar_art.on_change = lambda e: cargar_articulos_modal(e.control.value)

            def abrir_nuevo_articulo_rapido(_):
                cod_auto = generar_siguiente_codigo()
                inp_cod = ft.TextField(label="Código", value=cod_auto, read_only=True)
                inp_nom = ft.TextField(label="Nombre del artículo", autofocus=True)
                inp_pre = ft.TextField(label="Precio en ARS", keyboard_type="number")

                def guardar_art_nuevo(_):
                    nom_v = (inp_nom.value or "").strip().upper()
                    try:
                        pre_v = float((inp_pre.value or "0").replace(",", "."))
                    except ValueError:
                        mostrar_snack(page, "Precio inválido", COLORES["danger"])
                        return
                    if not nom_v or pre_v < 0:
                        mostrar_snack(page, "Completá descripción y precio", COLORES["danger"])
                        return
                    db("INSERT INTO Productos (codigo_articulo, nombre_articulo, precio_unitario) VALUES (?, ?, ?)", (cod_auto, nom_v, pre_v))
                    cerrar_dialogo(page, dlg_art)
                    mostrar_modal_editar_linea_articulo(cod_auto, nom_v, pre_v, cant_inicial=1, al_guardar=al_actualizar_carrito)

                dlg_art = ft.AlertDialog(
                    title=ft.Text("Nuevo Artículo", weight="bold"),
                    content=ft.Column([inp_cod, inp_nom, inp_pre], tight=True, spacing=12),
                    actions=[
                        ft.TextButton("CANCELAR", on_click=lambda _: cerrar_dialogo(page, dlg_art)),
                        ft.Button("GUARDAR", bgcolor=COLORES["header_purple"], color="white", on_click=guardar_art_nuevo),
                    ]
                )
                mostrar_dialogo(page, dlg_art)

            tarjeta_art = ft.Container(
                margin=ft.margin.symmetric(horizontal=16, vertical=18),
                bgcolor="#FFFFFF",
                expand=True,
                shadow=ft.BoxShadow(blur_radius=24, color="#77000000"),
                content=ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_purple"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Column([
                            ft.Row([
                                ft.IconButton("arrow_back", icon_color="white", on_click=cerrar_overlay),
                                ft.Text("Seleccionar el artículo", size=18, weight="bold", color="white", expand=True),
                                ft.IconButton("search", icon_color="white", on_click=toggle_buscador_art),
                            ], spacing=4),
                            txt_buscar_art,
                        ], spacing=4)
                    ),
                    ft.Container(content=lista_art_controls, expand=True),
                    ft.Container(
                        bgcolor="#FFFFFF",
                        padding=ft.padding.symmetric(vertical=8),
                        alignment=ft.Alignment(0, 0),
                        content=ft.Container(
                            width=50,
                            height=50,
                            border_radius=25,
                            bgcolor=COLORES["header_purple"],
                            alignment=ft.Alignment(0, 0),
                            shadow=ft.BoxShadow(blur_radius=8, color="#55000000", offset=ft.Offset(0, 2)),
                            ink=True,
                            on_click=abrir_nuevo_articulo_rapido,
                            content=ft.Icon("add", color="white", size=28)
                        )
                    )
                ], spacing=0, expand=True)
            )

            overlay_modal.content = ft.Container(
                expand=True,
                bgcolor="#77000000",
                content=tarjeta_art
            )
            overlay_modal.visible = True
            cargar_articulos_modal("")

        # ==========================================================
        # NAVEGACIÓN PRINCIPAL POR RUTAS
        # ==========================================================
        def cambiar_pantalla(e=None):
            registrar_inicio("ROUTE_HANDLER: entrada", f"route={page.route}; views_antes={len(page.views)}")
            # No llamar cerrar_overlay() después de limpiar las vistas: esa función
            # ejecuta page.update() y Flet puede quedar con la lista de vistas vacía.
            page.views.clear()
            registrar_inicio("ROUTE_HANDLER: vistas limpiadas", f"route={page.route}; views={len(page.views)}")
            overlay_modal.visible = False
            overlay_modal.content = None
            usuario_actual = page.session.store.get("usuario")
            
            if not usuario_actual and page.route != "/login":
                page.navigate("/login")
                return

            # ------------------------------------------------------
            # LOGIN
            # ------------------------------------------------------
            if page.route == "/login":
                registrar_inicio("ROUTE_HANDLER: construyendo login")
                inp_user = ft.TextField(label="Usuario (Ej: ABR012026)", width=310, border_color=COLORES["header_blue"])
                inp_pin = ft.TextField(label="PIN (Ej: 1111)", password=True, can_reveal_password=True, width=310, border_color=COLORES["header_blue"])
                
                def ingresar(_):
                    vendedor = db("SELECT nombre FROM Preventistas WHERE nombre=? AND pin=?", (inp_user.value.strip().upper(), inp_pin.value.strip()), fetch=True)
                    if vendedor:
                        page.session.store.set("usuario", vendedor[0])
                        page.navigate("/")
                    else: 
                        mostrar_snack(page, "Usuario o PIN incorrectos", COLORES["danger"])

                page.views.append(ft.View("/login", [
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        padding=24,
                        content=ft.Column([
                            ft.Container(
                                width=80, height=80, border_radius=40, bgcolor=COLORES["header_blue"],
                                alignment=ft.Alignment(0, 0),
                                content=ft.Icon("storefront", size=44, color="white")
                            ),
                            ft.Text("XIOMI Distribuidora", size=26, weight="bold", color=COLORES["header_blue"]),
                            ft.Text("Facturación y Preventa Móvil", size=14, color=COLORES["muted"], weight="bold"),
                            ft.Container(height=12),
                            inp_user,
                            inp_pin,
                            ft.Button(
                                "INGRESAR",
                                icon="login",
                                on_click=ingresar,
                                width=310,
                                style=ft.ButtonStyle(bgcolor=COLORES["header_blue"], color="white", padding=18)
                            )
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=12)
                    )
                ], padding=0, bgcolor="#FFFFFF"))
                registrar_inicio("ROUTE_HANDLER: login agregado", f"views={len(page.views)}")
                page.update()
                registrar_inicio("ROUTE_HANDLER: update login completado", f"route={page.route}; views={len(page.views)}")
                return

            cuerpo_principal = ft.Container(expand=True)

            # ------------------------------------------------------
            # IMAGEN 1: LISTA DE "Facturas" (RUTA "/" o "/pedidos_dia")
            # ------------------------------------------------------
            if page.route in ("/", "/pedidos_dia"):
                lista_facturas_ui = ft.ListView(expand=True, spacing=0)
                inp_filtro_facturas = ft.TextField(
                    hint_text="Escribí cliente, N° de factura, dirección o fecha...",
                    bgcolor="#FFFFFF",
                    height=42,
                    text_size=14,
                    content_padding=ft.padding.symmetric(horizontal=14, vertical=8),
                    visible=False
                )

                def iniciar_nueva_factura_con_cliente(id_cli_elegido):
                    carrito.clear()
                    dir_cli = db("SELECT direccion_entrega FROM Clientes WHERE numero_cliente = ?", (id_cli_elegido,), fetch=True)
                    estado_carrito.update({
                        "editando": False,
                        "id_factura": None,
                        "cargado": True,
                        "id_cliente": int(id_cli_elegido),
                        "fecha": date.today().strftime("%Y-%m-%d"),
                        "nota_texto": (dir_cli[0] if dir_cli and dir_cli[0] else ""),
                    })
                    page.navigate("/carrito")

                def abrir_factura_existente(id_fac):
                    fac = db("SELECT numero_cliente, fecha FROM Facturas WHERE numero_factura = ?", (id_fac,), fetch=True)
                    if not fac:
                        return
                    dir_cli = db("SELECT direccion_entrega FROM Clientes WHERE numero_cliente = ?", (fac[0],), fetch=True)
                    carrito.clear()
                    detalles = db(
                        "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo, d.codigo_articulo), d.precio_unitario, d.unidades FROM Detalle_Factura d LEFT JOIN Productos p ON d.codigo_articulo = p.codigo_articulo WHERE d.numero_factura = ?",
                        (id_fac,), fetch=True, fetchall=True
                    )
                    for cod, nom_p, pre_u, uni in detalles:
                        carrito[cod] = {"nombre": nom_p, "precio": float(pre_u or 0), "cantidad": int(uni) if float(uni).is_integer() else float(uni)}

                    estado_carrito.update({
                        "editando": True,
                        "id_factura": id_fac,
                        "cargado": True,
                        "id_cliente": fac[0],
                        "fecha": fac[1],
                        "nota_texto": (dir_cli[0] if dir_cli and dir_cli[0] else ""),
                    })
                    page.navigate("/carrito")

                def cargar_lista_facturas(filtro=""):
                    lista_facturas_ui.controls.clear()
                    f_txt = (filtro or "").strip().upper()
                    if f_txt:
                        filas = db(
                            '''SELECT f.numero_factura, f.fecha, COALESCE(c.nombre_apellido, 'CONSUMIDOR FINAL'),
                                      COALESCE(c.direccion_entrega, ''), f.total_a_pagar, COALESCE(f.preventista, 'ADMIN')
                               FROM Facturas f LEFT JOIN Clientes c ON f.numero_cliente = c.numero_cliente
                               WHERE UPPER(COALESCE(c.nombre_apellido,'')) LIKE ?
                                  OR UPPER(COALESCE(c.direccion_entrega,'')) LIKE ?
                                  OR CAST(f.numero_factura AS TEXT) LIKE ?
                                  OR f.fecha LIKE ?
                               ORDER BY f.numero_factura DESC LIMIT 120''',
                            (f"%{f_txt}%", f"%{f_txt}%", f"%{f_txt}%", f"%{f_txt}%"), fetch=True, fetchall=True
                        )
                    else:
                        filas = db(
                            '''SELECT f.numero_factura, f.fecha, COALESCE(c.nombre_apellido, 'CONSUMIDOR FINAL'),
                                      COALESCE(c.direccion_entrega, ''), f.total_a_pagar, COALESCE(f.preventista, 'ADMIN')
                               FROM Facturas f LEFT JOIN Clientes c ON f.numero_cliente = c.numero_cliente
                               ORDER BY f.numero_factura DESC LIMIT 120''',
                            fetch=True, fetchall=True
                        )

                    if not filas:
                        lista_facturas_ui.controls.append(
                            ft.Container(
                                padding=40,
                                alignment=ft.Alignment(0, 0),
                                content=ft.Text("Facturero en cero (0 facturas).\nPulsá el botón + abajo para emitir la Factura #1.", size=14, weight="bold", color=COLORES["muted"], text_align="center")
                            )
                        )
                    else:
                        for num_f, fec, nom_cli, dir_cli, total, prev in filas:
                            def click_abrir(id_f=num_f):
                                return lambda _: abrir_factura_existente(id_f)

                            lista_facturas_ui.controls.append(
                                ft.Container(
                                    bgcolor="#FFFFFF",
                                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                                    border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                    ink=True,
                                    on_click=click_abrir(num_f),
                                    content=ft.Row([
                                        ft.Column([
                                            ft.Text(f"{num_f}  {nom_cli}", size=15, weight="bold", color="#000000", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                            ft.Text(dir_cli if dir_cli else "SIN DIRECCIÓN", size=14, weight="bold", color="#000000", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                            ft.Text(fecha_ui(fec), size=14, weight="bold", color="#000000"),
                                        ], spacing=2, expand=True),
                                        ft.Column([
                                            ft.Text(f"{formato_ars_corto(total)} ARS", size=15, weight="bold", color="#000000"),
                                            ft.Container(height=14),
                                            ft.Text("Abrir", size=14, weight="bold", color="#000000"),
                                        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END)
                                    ], vertical_alignment=ft.CrossAxisAlignment.START)
                                )
                            )
                    page.update()

                def toggle_filtro(_):
                    inp_filtro_facturas.visible = not inp_filtro_facturas.visible
                    if not inp_filtro_facturas.visible:
                        inp_filtro_facturas.value = ""
                        cargar_lista_facturas("")
                    page.update()

                inp_filtro_facturas.on_change = lambda e: cargar_lista_facturas(e.control.value)

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("menu", icon_color="white", tooltip="Abrir menú", on_click=abrir_menu_lateral),
                            ft.Text("Facturas", size=19, weight="bold", color="white", expand=True),
                            ft.IconButton("search", icon_color="white", tooltip="Filtrar", on_click=toggle_filtro),
                        ])
                    ),
                    ft.Container(
                        bgcolor=COLORES["filter_bar"],
                        width=float("inf"),
                        padding=ft.padding.symmetric(vertical=9, horizontal=12),
                        border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                        ink=True,
                        on_click=toggle_filtro,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text("Pulsa para filtrar lista", size=15, weight="bold", color="#000000")
                    ),
                    inp_filtro_facturas,
                    ft.Container(content=lista_facturas_ui, expand=True),
                    ft.Container(
                        bgcolor="#FFFFFF",
                        padding=ft.padding.symmetric(vertical=8),
                        alignment=ft.Alignment(0, 0),
                        content=ft.Container(
                            width=54,
                            height=54,
                            border_radius=27,
                            bgcolor=COLORES["fab_blue"],
                            alignment=ft.Alignment(0, 0),
                            shadow=ft.BoxShadow(blur_radius=10, color="#66000000", offset=ft.Offset(0, 3)),
                            ink=True,
                            on_click=lambda _: mostrar_modal_seleccionar_cliente(iniciar_nueva_factura_con_cliente),
                            content=ft.Icon("add", color="white", size=30)
                        )
                    )
                ], spacing=0, expand=True)
                cargar_lista_facturas("")

            # ------------------------------------------------------
            # IMAGEN 3: EDITOR DE FACTURA ("GUARDAR" | "AÑADIR ARTÍCULO")
            # ------------------------------------------------------
            elif page.route == "/carrito":
                if not estado_carrito.get("id_cliente"):
                    primero = db("SELECT numero_cliente, direccion_entrega FROM Clientes ORDER BY numero_cliente LIMIT 1", fetch=True)
                    if primero:
                        estado_carrito["id_cliente"] = primero[0]
                        estado_carrito["nota_texto"] = primero[1] or ""

                txt_cantidad_pagar = ft.Text("Cantidad a pagar  0 ARS", size=16, weight="bold", color="#000000")
                txt_fecha_fac = ft.Text("", size=15, weight="bold", color="#000000")
                txt_venc_fac = ft.Text("", size=15, weight="bold", color="#000000")
                txt_cliente_linea1 = ft.Text("", size=15, weight="bold", color="#000000")
                txt_cliente_linea2 = ft.Text("", size=15, weight="bold", color="#000000")

                inp_direccion_editable = ft.TextField(
                    value=estado_carrito.get("nota_texto", ""),
                    hint_text="Clic para introducir un texto",
                    hint_style=ft.TextStyle(weight="bold", color="#000000"),
                    text_style=ft.TextStyle(weight="bold", size=14, color="#000000"),
                    border="none",
                    content_padding=ft.padding.symmetric(horizontal=10, vertical=6)
                )

                lista_articulos_facturados = ft.Column(spacing=0)

                def refrescar_vista_factura():
                    id_cli = estado_carrito.get("id_cliente")
                    cli_row = db("SELECT nombre_apellido, direccion_entrega FROM Clientes WHERE numero_cliente = ?", (id_cli,), fetch=True)
                    nom_c = cli_row[0] if cli_row else "CONSUMIDOR FINAL"
                    dir_c = (inp_direccion_editable.value or (cli_row[1] if cli_row else "") or "").strip().upper()

                    txt_cliente_linea1.value = f"{nom_c} ({id_cli})"
                    txt_cliente_linea2.value = dir_c if dir_c else "SIN DIRECCIÓN"

                    fec_str = estado_carrito.get("fecha") or date.today().strftime("%Y-%m-%d")
                    try:
                        f_obj = datetime.strptime(fec_str, "%Y-%m-%d")
                        v_obj = f_obj + timedelta(days=30)
                        txt_fecha_fac.value = f_obj.strftime("%d/%m/%Y")
                        txt_venc_fac.value = v_obj.strftime("%d/%m/%Y")
                    except Exception:
                        txt_fecha_fac.value = fec_str
                        txt_venc_fac.value = fec_str

                    suma_total = sum(item["cantidad"] * item["precio"] for item in carrito.values())
                    txt_cantidad_pagar.value = f"Cantidad a pagar  {formato_ars_corto(suma_total)} ARS"

                    lista_articulos_facturados.controls.clear()
                    for cod, item in carrito.items():
                        cant_fmt = str(int(item["cantidad"])) if float(item["cantidad"]).is_integer() else str(item["cantidad"]).replace(".", ",")
                        sub_item = item["cantidad"] * item["precio"]

                        def editar_item(c_i=cod, it=item):
                            return lambda _: mostrar_modal_editar_linea_articulo(c_i, it["nombre"], it["precio"], cant_inicial=it["cantidad"], al_guardar=refrescar_vista_factura)

                        def borrar_item(c_i=cod):
                            def _del(_):
                                carrito.pop(c_i, None)
                                refrescar_vista_factura()
                            return _del

                        lista_articulos_facturados.controls.append(
                            ft.Container(
                                bgcolor="#FFFFFF",
                                padding=ft.padding.symmetric(horizontal=10, vertical=10),
                                border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                ink=True,
                                on_click=editar_item(cod, item),
                                content=ft.Row([
                                    ft.Column([
                                        ft.Text(item["nombre"], size=15, weight="bold", color="#000000"),
                                        ft.Text(f"{cant_fmt} x {formato_ars_corto(item['precio'])} ARS", size=13, weight="bold", color=COLORES["muted"]),
                                    ], spacing=2, expand=True),
                                    ft.Text(f"{formato_ars_corto(sub_item)} ARS", size=15, weight="bold", color="#000000"),
                                    ft.IconButton("close", icon_color=COLORES["danger"], icon_size=20, on_click=borrar_item(cod))
                                ])
                            )
                        )
                    page.update()

                inp_direccion_editable.on_change = lambda e: (
                    estado_carrito.update({"nota_texto": e.control.value}),
                    setattr(txt_cliente_linea2, "value", (e.control.value or "").strip().upper() or "SIN DIRECCIÓN"),
                    page.update()
                )

                def cambiar_fecha_modal(_):
                    inp_f = ft.TextField(label="Fecha (AAAA-MM-DD)", value=estado_carrito.get("fecha", date.today().strftime("%Y-%m-%d")))
                    def guardar_f(_):
                        estado_carrito["fecha"] = inp_f.value.strip() or date.today().strftime("%Y-%m-%d")
                        cerrar_dialogo(page, dlg_f)
                        refrescar_vista_factura()
                    dlg_f = ft.AlertDialog(
                        title=ft.Text("Fecha de factura", weight="bold"),
                        content=inp_f,
                        actions=[
                            ft.TextButton("CANCELAR", on_click=lambda _: cerrar_dialogo(page, dlg_f)),
                            ft.Button("ACEPTAR", bgcolor=COLORES["header_blue"], color="white", on_click=guardar_f)
                        ]
                    )
                    mostrar_dialogo(page, dlg_f)

                def cambiar_cliente_en_factura(_):
                    def _al_elegir(nuevo_id):
                        dir_c = db("SELECT direccion_entrega FROM Clientes WHERE numero_cliente = ?", (nuevo_id,), fetch=True)
                        estado_carrito["id_cliente"] = int(nuevo_id)
                        inp_direccion_editable.value = dir_c[0] if dir_c and dir_c[0] else ""
                        refrescar_vista_factura()
                    mostrar_modal_seleccionar_cliente(_al_elegir)

                def guardar_factura(e):
                    btn_guardar = e.control
                    btn_guardar.disabled = True
                    page.update()

                    id_cli = estado_carrito.get("id_cliente")
                    if not id_cli or not carrito:
                        mostrar_snack(page, "Añadí al menos un artículo antes de guardar", COLORES["danger"])
                        btn_guardar.disabled = False
                        page.update()
                        return

                    fecha_elegida = (estado_carrito.get("fecha") or date.today().strftime("%Y-%m-%d")).strip()

                    if estado_carrito["editando"]:
                        ya_facturado = db(
                            "SELECT COUNT(*) FROM Facturas WHERE numero_cliente = ? AND fecha = ? AND numero_factura != ?",
                            (id_cli, fecha_elegida, estado_carrito["id_factura"]), fetch=True
                        )[0]
                    else:
                        ya_facturado = db(
                            "SELECT COUNT(*) FROM Facturas WHERE numero_cliente = ? AND fecha = ?",
                            (id_cli, fecha_elegida), fetch=True
                        )[0]

                    if ya_facturado > 0:
                        mostrar_snack(page, "❌ ¡CUIDADO! Este cliente ya tiene una factura en esta fecha.", COLORES["danger"])
                        btn_guardar.disabled = False
                        page.update()
                        return

                    nueva_dir = (inp_direccion_editable.value or "").strip().upper()
                    if nueva_dir:
                        db("UPDATE Clientes SET direccion_entrega = ? WHERE numero_cliente = ?", (nueva_dir, id_cli))

                    tot = sum(item["cantidad"] * item["precio"] for item in carrito.values())
                    detalles_venta = [
                        (cod, item["nombre"], item["precio"], item["cantidad"], item["cantidad"] * item["precio"])
                        for cod, item in carrito.items()
                    ]

                    try:
                        if estado_carrito["editando"]:
                            actualizar_factura_con_detalle(estado_carrito["id_factura"], fecha_elegida, id_cli, tot, usuario_actual, detalles_venta)
                        else:
                            crear_factura_con_detalle(fecha_elegida, id_cli, tot, usuario_actual, detalles_venta)

                        carrito.clear()
                        estado_carrito["editando"] = False
                        page.navigate("/")
                    except Exception as ex:
                        mostrar_snack(page, f"Error al guardar: {ex}", COLORES["danger"])
                        btn_guardar.disabled = False
                        page.update()

                def imprimir_factura_actual(_):
                    if not estado_carrito.get("editando") or not estado_carrito.get("id_factura"):
                        mostrar_snack(page, "Primero guardá la factura para generar el PDF", COLORES["info"])
                        return
                    id_f = estado_carrito["id_factura"]
                    ruta = os.path.join(carpeta_assets, f"Reporte_{id_f}.pdf")
                    if generar_pdf_facturas(ruta, num_factura=id_f):
                        abrir_archivo_local(ruta)
                        mostrar_snack(page, f"✅ PDF generado: Factura #{id_f}", COLORES["success"])

                def eliminar_factura_actual(_):
                    if estado_carrito.get("editando") and estado_carrito.get("id_factura"):
                        id_f = estado_carrito["id_factura"]
                        db("DELETE FROM Detalle_Factura WHERE numero_factura=?", (id_f,))
                        db("DELETE FROM Facturas WHERE numero_factura=?", (id_f,))
                    carrito.clear()
                    estado_carrito["editando"] = False
                    page.navigate("/")

                menu_tres_puntos = ft.PopupMenuButton(
                    icon="more_vert",
                    icon_color="white",
                    items=[
                        ft.PopupMenuItem(text="Imprimir / Exportar PDF", icon="print", on_click=imprimir_factura_actual),
                        ft.PopupMenuItem(text="Cambiar cliente", icon="person_search", on_click=cambiar_cliente_en_factura),
                        ft.PopupMenuItem(text="Cambiar fecha", icon="calendar_today", on_click=cambiar_fecha_modal),
                        ft.PopupMenuItem(text="Ver historial de este cliente", icon="history", on_click=lambda _: (estado_historial_cli.update({"id_cliente": estado_carrito.get("id_cliente")}), page.navigate("/historial_cliente"))),
                        ft.PopupMenuItem(text="Eliminar factura", icon="delete", on_click=eliminar_factura_actual),
                    ]
                )

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.symmetric(horizontal=4, vertical=6),
                        content=ft.Row([
                            ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.navigate("/")),
                            ft.Container(expand=True),
                            ft.TextButton(
                                content=ft.Text("GUARDAR", size=14, weight="bold", color="white"),
                                on_click=guardar_factura
                            ),
                            ft.TextButton(
                                content=ft.Text("AÑADIR ARTÍCULO", size=14, weight="bold", color="white"),
                                on_click=lambda _: mostrar_modal_seleccionar_articulo(refrescar_vista_factura)
                            ),
                            menu_tres_puntos,
                        ], spacing=2)
                    ),
                    ft.Column([
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=10, vertical=12),
                            border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                            width=float("inf"),
                            content=txt_cantidad_pagar
                        ),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=10, vertical=10),
                            border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                            ink=True,
                            on_click=cambiar_fecha_modal,
                            content=ft.Column([
                                ft.Row([
                                    ft.Text("Estatus", size=15, weight="bold", color="#000000", width=140),
                                    ft.Text("Abrir", size=15, weight="bold", color="#000000"),
                                ]),
                                ft.Row([
                                    ft.Text("Fecha de factura", size=15, weight="bold", color="#000000", width=140),
                                    txt_fecha_fac,
                                ]),
                                ft.Row([
                                    ft.Text("Vencimiento", size=15, weight="bold", color="#000000", width=140),
                                    txt_venc_fac,
                                ]),
                            ], spacing=4)
                        ),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=10, vertical=10),
                            border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                            width=float("inf"),
                            ink=True,
                            on_click=cambiar_cliente_en_factura,
                            content=ft.Column([
                                txt_cliente_linea1,
                                txt_cliente_linea2,
                            ], spacing=4)
                        ),
                        ft.Container(
                            border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                            width=float("inf"),
                            content=inp_direccion_editable
                        ),
                        ft.Container(
                            bgcolor=COLORES["strip_cyan"],
                            padding=ft.padding.symmetric(horizontal=10, vertical=8),
                            border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                            ink=True,
                            on_click=lambda _: mostrar_modal_seleccionar_articulo(refrescar_vista_factura),
                            content=ft.Row([
                                ft.Row([
                                    ft.Text("Artículos facturados ", size=15, weight="bold", color="#000000"),
                                    ft.Text("(Pulse para añadir)", size=14, weight="bold", color="#000000"),
                                ], spacing=0, expand=True),
                                ft.Icon("add_shopping_cart", size=20, color="#333333")
                            ])
                        ),
                        lista_articulos_facturados,
                    ], spacing=0, scroll="auto", expand=True)
                ], spacing=0, expand=True)

                refrescar_vista_factura()

            # ------------------------------------------------------
            # DIRECTORIO DE CLIENTES + EXCEL + BOTÓN HISTORIAL
            # ------------------------------------------------------
            elif page.route == "/agregar_cliente":
                def exportar_clientes_excel(_):
                    try:
                        fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        nombre_archivo = f"Listado_Clientes_{fecha_str}.csv"
                        ruta_csv = os.path.join(carpeta_assets, nombre_archivo)
                        filas_exportar = db("SELECT numero_cliente, nombre_apellido, direccion_entrega FROM Clientes ORDER BY nombre_apellido", fetch=True, fetchall=True)
                        with open(ruta_csv, mode='w', newline='', encoding='utf-8-sig') as f:
                            writer = csv.writer(f, delimiter=';')
                            writer.writerow(["ID Cliente", "Nombre / Razón Social", "Dirección de Entrega"])
                            for r in (filas_exportar or []):
                                writer.writerow([r[0], r[1] or "", r[2] or ""])
                        abrir_archivo_local(ruta_csv)
                        mostrar_snack(page, "✅ Clientes exportados a Excel", COLORES["success"])
                    except Exception as ex:
                        mostrar_snack(page, f"Error: {ex}", COLORES["danger"])

                inp_nom_c = ft.TextField(label="Nombre / Razón social", expand=True, dense=True)
                inp_dir_c = ft.TextField(label="Dirección de entrega", expand=True, dense=True)
                buscador_cli_g = ft.TextField(hint_text="Buscar cliente...", prefix_icon="search", expand=True, dense=True)
                btn_guardar_c = ft.Button("GUARDAR", bgcolor=COLORES["header_green"], color="white")
                estado_ed_cli = {"editando": False, "id_viejo": None}
                lista_padron_cli = ft.ListView(expand=True, spacing=0)

                def ref_padron_cli(_=None):
                    lista_padron_cli.controls.clear()
                    f_str = (buscador_cli_g.value or "").strip().upper()
                    if f_str:
                        filas = db("SELECT numero_cliente, nombre_apellido, direccion_entrega FROM Clientes WHERE UPPER(nombre_apellido) LIKE ? OR UPPER(COALESCE(direccion_entrega,'')) LIKE ? ORDER BY numero_cliente ASC LIMIT 100", (f"%{f_str}%", f"%{f_str}%"), fetch=True, fetchall=True)
                    else:
                        filas = db("SELECT numero_cliente, nombre_apellido, direccion_entrega FROM Clientes ORDER BY numero_cliente ASC LIMIT 100", fetch=True, fetchall=True)

                    for id_c, n, d in (filas or []):
                        def ver_hist(c_id=id_c):
                            return lambda _: (estado_historial_cli.update({"id_cliente": c_id}), page.navigate("/historial_cliente"))

                        def editar_c(c_id=id_c, nom_v=n, dir_v=d):
                            def _ed(_):
                                estado_ed_cli.update({"editando": True, "id_viejo": c_id})
                                inp_nom_c.value = nom_v or ""
                                inp_dir_c.value = dir_v or ""
                                btn_guardar_c.text = "ACTUALIZAR"
                                page.update()
                            return _ed

                        def borrar_c(c_id=id_c):
                            def _del(_):
                                db("DELETE FROM Clientes WHERE numero_cliente=?", (c_id,))
                                ref_padron_cli()
                            return _del

                        lista_padron_cli.controls.append(
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                                border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                content=ft.Row([
                                    ft.Column([
                                        ft.Text(f"{id_c}  {n}", size=15, weight="bold", color="#000000"),
                                        ft.Text(d if d else "SIN DIRECCIÓN", size=13, weight="bold", color=COLORES["muted"]),
                                    ], spacing=2, expand=True),
                                    ft.IconButton("history", tooltip="Historial del Cliente", icon_color="#5A3D7A", on_click=ver_hist(id_c)),
                                    ft.IconButton("edit", icon_color=COLORES["info"], on_click=editar_c(id_c, n, d)),
                                    ft.IconButton("delete", icon_color=COLORES["danger"], on_click=borrar_c(id_c)),
                                ])
                            )
                        )
                    page.update()

                def guardar_cli_padron(_):
                    nom_v = (inp_nom_c.value or "").strip().upper()
                    dir_v = (inp_dir_c.value or "").strip().upper()
                    if not nom_v:
                        return
                    if estado_ed_cli["editando"]:
                        db("UPDATE Clientes SET nombre_apellido=?, direccion_entrega=? WHERE numero_cliente=?", (nom_v, dir_v, estado_ed_cli["id_viejo"]))
                    else:
                        db("INSERT INTO Clientes (nombre_apellido, direccion_entrega) VALUES (?, ?)", (nom_v, dir_v))
                    estado_ed_cli.update({"editando": False, "id_viejo": None})
                    inp_nom_c.value = ""
                    inp_dir_c.value = ""
                    btn_guardar_c.text = "GUARDAR"
                    ref_padron_cli()

                btn_guardar_c.on_click = guardar_cli_padron
                buscador_cli_g.on_change = ref_padron_cli

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_green"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("menu", icon_color="white", on_click=abrir_menu_lateral),
                            ft.Text("Clientes", size=19, weight="bold", color="white", expand=True),
                            ft.TextButton(content=ft.Text("EXCEL", color="white", weight="bold"), icon="table_chart", on_click=exportar_clientes_excel),
                        ])
                    ),
                    ft.Container(
                        padding=12,
                        bgcolor="#F8FAFC",
                        border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                        content=ft.Column([
                            ft.Row([inp_nom_c, inp_dir_c], spacing=8),
                            ft.Row([buscador_cli_g, btn_guardar_c], spacing=8),
                        ], spacing=8)
                    ),
                    lista_padron_cli
                ], spacing=0, expand=True)
                ref_padron_cli()

            # ------------------------------------------------------
            # HISTORIAL DEL CLIENTE CON VISTA PREVIA DE CADA FACTURA
            # ------------------------------------------------------
            elif page.route == "/historial_cliente":
                opciones_cli = db("SELECT numero_cliente, nombre_apellido, direccion_entrega FROM Clientes ORDER BY numero_cliente LIMIT 100", fetch=True, fetchall=True) or []
                id_inicial = estado_historial_cli.get("id_cliente")
                if not id_inicial and opciones_cli:
                    id_inicial = opciones_cli[0][0]

                dd_cli_hist = ft.Dropdown(
                    label="Cliente",
                    options=[ft.dropdown.Option(key=str(c[0]), text=f"{c[0]} {c[1]}") for c in opciones_cli],
                    value=str(id_inicial) if id_inicial else None,
                    expand=True,
                    dense=True
                )
                txt_resumen_hist = ft.Text("0 facturas | Total: 0 ARS", size=14, weight="bold", color=COLORES["header_blue"])
                lista_hist_facturas = ft.ListView(expand=True, spacing=0)
                contenedor_detalle_factura = ft.Column(spacing=4)

                def ver_detalle_factura_hist(id_fac):
                    contenedor_detalle_factura.controls.clear()
                    fac = db("SELECT f.numero_factura, f.fecha, c.nombre_apellido, c.direccion_entrega, f.total_a_pagar, f.preventista FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente WHERE f.numero_factura = ?", (id_fac,), fetch=True)
                    lineas = db("SELECT COALESCE(d.nombre_personalizado, p.nombre_articulo, d.codigo_articulo), d.unidades, d.precio_unitario, d.total_linea FROM Detalle_Factura d LEFT JOIN Productos p ON d.codigo_articulo = p.codigo_articulo WHERE d.numero_factura = ?", (id_fac,), fetch=True, fetchall=True)
                    if not fac:
                        return

                    def imp_pdf(_):
                        ruta = os.path.join(carpeta_assets, f"Reporte_{id_fac}.pdf")
                        if generar_pdf_facturas(ruta, num_factura=id_fac):
                            abrir_archivo_local(ruta)

                    def abrir_en_editor(_):
                        carrito.clear()
                        detalles = db("SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo, d.codigo_articulo), d.precio_unitario, d.unidades FROM Detalle_Factura d LEFT JOIN Productos p ON d.codigo_articulo = p.codigo_articulo WHERE d.numero_factura = ?", (id_fac,), fetch=True, fetchall=True)
                        for cod, nom_p, pre_u, uni in detalles:
                            carrito[cod] = {"nombre": nom_p, "precio": float(pre_u or 0), "cantidad": int(uni) if float(uni).is_integer() else float(uni)}
                        estado_carrito.update({
                            "editando": True,
                            "id_factura": id_fac,
                            "cargado": True,
                            "id_cliente": int(dd_cli_hist.value),
                            "fecha": fac[1],
                            "nota_texto": fac[3] or ""
                        })
                        page.navigate("/carrito")

                    contenedor_detalle_factura.controls.append(
                        ft.Container(
                            bgcolor=COLORES["strip_cyan"],
                            padding=10,
                            border=ft.border.all(1, COLORES["divider"]),
                            content=ft.Column([
                                ft.Row([
                                    ft.Text(f"Vista Previa Factura #{fac[0]} ({fecha_ui(fac[1])})", size=15, weight="bold", expand=True),
                                    ft.TextButton("ABRIR", on_click=abrir_en_editor),
                                    ft.Button("PDF", icon="print", bgcolor=COLORES["header_blue"], color="white", on_click=imp_pdf),
                                ]),
                                ft.Text(f"Vendedor: {fac[5] or 'ADMIN'} | Total: {formato_ars_corto(fac[4])} ARS", size=13, weight="bold"),
                                ft.Divider(height=1, color=COLORES["divider"]),
                                ft.Column([
                                    ft.Row([
                                        ft.Text(str(art), size=13, weight="bold", expand=True),
                                        ft.Text(f"{int(cant) if float(cant).is_integer() else cant} x {formato_ars_corto(pre)}", size=12, weight="bold"),
                                        ft.Text(f"{formato_ars_corto(tot)} ARS", size=13, weight="bold", width=90, text_align="right"),
                                    ]) for art, cant, pre, tot in lineas
                                ], spacing=4)
                            ], spacing=6)
                        )
                    )
                    page.update()

                def cargar_hist(_=None):
                    lista_hist_facturas.controls.clear()
                    contenedor_detalle_factura.controls.clear()
                    if not dd_cli_hist.value:
                        return
                    c_id = int(dd_cli_hist.value)
                    estado_historial_cli["id_cliente"] = c_id
                    facturas = db(
                        "SELECT f.numero_factura, f.fecha, c.nombre_apellido, c.direccion_entrega, f.total_a_pagar FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente WHERE f.numero_cliente = ? ORDER BY f.numero_factura DESC",
                        (c_id,), fetch=True, fetchall=True
                    )
                    suma = sum(float(r[4] or 0) for r in (facturas or []))
                    txt_resumen_hist.value = f"{len(facturas or [])} facturas | Total histórico: {formato_ars_corto(suma)} ARS"

                    for num_f, fec, nom_c, dir_c, tot in (facturas or []):
                        def sel_f(id_f=num_f):
                            return lambda _: ver_detalle_factura_hist(id_f)

                        lista_hist_facturas.controls.append(
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=10, vertical=8),
                                border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                ink=True,
                                on_click=sel_f(num_f),
                                content=ft.Row([
                                    ft.Column([
                                        ft.Text(f"{num_f}  {nom_c}", size=15, weight="bold"),
                                        ft.Text(dir_c or "SIN DIRECCIÓN", size=13, weight="bold"),
                                        ft.Text(fecha_ui(fec), size=13, weight="bold"),
                                    ], spacing=2, expand=True),
                                    ft.Column([
                                        ft.Text(f"{formato_ars_corto(tot)} ARS", size=15, weight="bold"),
                                        ft.Text("Ver detalle", size=13, weight="bold", color=COLORES["header_blue"]),
                                    ], horizontal_alignment=ft.CrossAxisAlignment.END)
                                ])
                            )
                        )
                    if facturas:
                        ver_detalle_factura_hist(facturas[0][0])
                    page.update()

                dd_cli_hist.on_change = cargar_hist

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("menu", icon_color="white", on_click=abrir_menu_lateral),
                            ft.Text("Historial del Cliente", size=19, weight="bold", color="white", expand=True),
                        ])
                    ),
                    ft.Container(
                        padding=10,
                        bgcolor="#F5F5F5",
                        content=ft.Column([dd_cli_hist, txt_resumen_hist], spacing=6)
                    ),
                    contenedor_detalle_factura,
                    lista_hist_facturas,
                ], spacing=0, expand=True)
                cargar_hist()

            # ------------------------------------------------------
            # CATÁLOGO DE ARTÍCULOS + EXCEL (ESTILO IMAGEN 4)
            # ------------------------------------------------------
            elif page.route == "/agregar_producto":
                def exportar_productos_excel(_):
                    try:
                        fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        nombre_archivo = f"Listado_Productos_{fecha_str}.csv"
                        ruta_csv = os.path.join(carpeta_assets, nombre_archivo)
                        filas_exportar = db("SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos ORDER BY nombre_articulo", fetch=True, fetchall=True)
                        with open(ruta_csv, mode='w', newline='', encoding='utf-8-sig') as f:
                            writer = csv.writer(f, delimiter=';')
                            writer.writerow(["Código", "Descripción", "Precio Unitario"])
                            for r in (filas_exportar or []):
                                writer.writerow([r[0], r[1] or "", formato_ars(r[2])])
                        abrir_archivo_local(ruta_csv)
                        mostrar_snack(page, "✅ Artículos exportados a Excel", COLORES["success"])
                    except Exception as ex:
                        mostrar_snack(page, f"Error: {ex}", COLORES["danger"])

                inp_cod = ft.TextField(label="Código", value=generar_siguiente_codigo(), width=110, dense=True)
                inp_nom = ft.TextField(label="Descripción", expand=True, dense=True)
                inp_pre = ft.TextField(label="Precio ARS", keyboard_type="number", width=120, dense=True)
                buscador_p = ft.TextField(hint_text="Buscar artículo...", prefix_icon="search", expand=True, dense=True)
                btn_guardar_p = ft.Button("GUARDAR", bgcolor=COLORES["header_purple"], color="white")
                estado_ed_p = {"editando": False, "codigo_viejo": None}
                lista_prod_ui = ft.ListView(expand=True, spacing=0)

                def ref_prod(_=None):
                    lista_prod_ui.controls.clear()
                    f_str = (buscador_p.value or "").strip().upper()
                    filas = db(
                        "SELECT codigo_articulo, nombre_articulo, precio_unitario FROM Productos WHERE UPPER(nombre_articulo) LIKE ? OR UPPER(codigo_articulo) LIKE ? ORDER BY nombre_articulo ASC LIMIT 150",
                        (f"%{f_str}%", f"%{f_str}%"), fetch=True, fetchall=True
                    )
                    for c, n, p in (filas or []):
                        def editar_p(cod_p=c, nom_p=n, pre_p=p):
                            def _ed(_):
                                estado_ed_p.update({"editando": True, "codigo_viejo": cod_p})
                                inp_cod.value = cod_p
                                inp_nom.value = nom_p
                                inp_pre.value = str(pre_p)
                                btn_guardar_p.text = "ACTUALIZAR"
                                page.update()
                            return _ed

                        def borrar_p(cod_p=c):
                            def _del(_):
                                db("DELETE FROM Productos WHERE codigo_articulo=?", (cod_p,))
                                ref_prod()
                            return _del

                        lista_prod_ui.controls.append(
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                                border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                content=ft.Row([
                                    ft.Column([
                                        ft.Text(str(n), size=15, weight="bold", color="#000000"),
                                        ft.Text(f"{formato_ars_corto(p)} ARS", size=14, weight="bold", color="#000000"),
                                    ], spacing=2, expand=True),
                                    ft.IconButton("edit", icon_color=COLORES["info"], on_click=editar_p(c, n, p)),
                                    ft.IconButton("delete", icon_color=COLORES["danger"], on_click=borrar_p(c)),
                                ])
                            )
                        )
                    page.update()

                def guardar_prod(_):
                    c_val = (inp_cod.value or "").strip().upper()
                    n_val = (inp_nom.value or "").strip().upper()
                    try:
                        p_val = float((inp_pre.value or "0").replace(",", "."))
                    except ValueError:
                        return
                    if not c_val or not n_val:
                        return
                    if estado_ed_p["editando"]:
                        db("UPDATE Productos SET nombre_articulo=?, precio_unitario=? WHERE codigo_articulo=?", (n_val, p_val, estado_ed_p["codigo_viejo"]))
                    else:
                        db("INSERT OR REPLACE INTO Productos (codigo_articulo, nombre_articulo, precio_unitario) VALUES (?, ?, ?)", (c_val, n_val, p_val))
                    estado_ed_p.update({"editando": False, "codigo_viejo": None})
                    inp_cod.value = generar_siguiente_codigo()
                    inp_nom.value = ""
                    inp_pre.value = ""
                    btn_guardar_p.text = "GUARDAR"
                    ref_prod()

                btn_guardar_p.on_click = guardar_prod
                buscador_p.on_change = ref_prod

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_purple"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("menu", icon_color="white", on_click=abrir_menu_lateral),
                            ft.Text("Artículos", size=19, weight="bold", color="white", expand=True),
                            ft.TextButton(content=ft.Text("EXCEL", color="white", weight="bold"), icon="table_chart", on_click=exportar_productos_excel),
                        ])
                    ),
                    ft.Container(
                        padding=12,
                        bgcolor="#F8FAFC",
                        border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                        content=ft.Column([
                            ft.Row([inp_cod, inp_nom, inp_pre], spacing=8),
                            ft.Row([buscador_p, btn_guardar_p], spacing=8),
                        ], spacing=8)
                    ),
                    lista_prod_ui
                ], spacing=0, expand=True)
                ref_prod()

            # ------------------------------------------------------
            # CENTRO DE REPORTES PDF
            # ------------------------------------------------------
            elif page.route == "/reportes":
                hoy = date.today().strftime("%Y-%m-%d")
                inp_fec = ft.TextField(label="Fecha (AAAA-MM-DD)", value=hoy, dense=True, expand=True)
                inp_ini = ft.TextField(label="Desde", value=hoy, dense=True, expand=True)
                inp_fin = ft.TextField(label="Hasta", value=hoy, dense=True, expand=True)
                inp_num = ft.TextField(label="N° Factura", dense=True, expand=True)
                lista_prev = [r[0] for r in db("SELECT DISTINCT preventista FROM Facturas WHERE preventista IS NOT NULL", fetch=True, fetchall=True)] or ["ADMIN"]
                dd_usu = ft.Dropdown(label="Vendedor", options=[ft.dropdown.Option(text=u) for u in lista_prev], value=lista_prev[0], dense=True, expand=True)

                def pedir_pdf(tipo):
                    f = inp_fec.value.strip() or hoy
                    finio = inp_ini.value.strip() or hoy
                    ffin = inp_fin.value.strip() or hoy
                    usu = dd_usu.value
                    f_fmt = formatear_fecha_archivo(f)
                    ruta_completa = os.path.join(carpeta_assets, f"Reporte_{tipo}_{f_fmt}.pdf")
                    exito = False
                    if tipo == "factura_unica":
                        exito = generar_pdf_facturas(ruta_completa, num_factura=int(inp_num.value) if inp_num.value else 0)
                    elif tipo == "lote_diario":
                        exito = generar_pdf_facturas(ruta_completa, fecha_consulta=f)
                    elif tipo == "cobranza_dia":
                        exito = generar_reporte_clientes_dia(ruta_completa, f)
                    elif tipo == "preventistas_dia":
                        exito = generar_reporte_total_preventistas_fecha(ruta_completa, f)
                    elif tipo == "preventistas_rango":
                        exito = generar_reporte_preventistas(ruta_completa, finio, ffin)
                    elif tipo == "mercaderia_dia":
                        exito = generar_reporte_generico(ruta_completa, "SELECT d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario, SUM(d.unidades), SUM(d.total_linea) FROM Detalle_Factura d JOIN Productos p ON d.codigo_articulo = p.codigo_articulo JOIN Facturas f ON d.numero_factura = f.numero_factura WHERE f.fecha = ? GROUP BY d.codigo_articulo, COALESCE(d.nombre_personalizado, p.nombre_articulo), d.precio_unitario", (f,), "REPORTE DIARIO DE VENTAS", f"Fecha: {f}")
                    elif tipo == "mercaderia_usu":
                        exito = generar_reporte_articulos_por_usuario_dia(ruta_completa, f, usu)

                    if exito:
                        abrir_archivo_local(ruta_completa)
                        mostrar_snack(page, "✅ PDF generado correctamente", COLORES["success"])
                    else:
                        mostrar_snack(page, "No se encontraron datos para esa consulta", COLORES["danger"])

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("menu", icon_color="white", on_click=abrir_menu_lateral),
                            ft.Text("Reportes PDF y Caja", size=19, weight="bold", color="white", expand=True),
                        ])
                    ),
                    ft.Container(
                        padding=16,
                        expand=True,
                        content=ft.Column([
                            ft.Row([inp_fec, dd_usu], spacing=10),
                            ft.Row([inp_ini, inp_fin], spacing=10),
                            ft.Button("LISTADO DE COBRANZA DIARIA (PDF)", icon="request_quote", bgcolor=COLORES["header_green"], color="white", width=float("inf"), on_click=lambda _: pedir_pdf("cobranza_dia")),
                            ft.Button("RENDICIÓN VENDEDORES DEL DÍA (PDF)", icon="people", bgcolor=COLORES["header_blue"], color="white", width=float("inf"), on_click=lambda _: pedir_pdf("preventistas_dia")),
                            ft.Button("RENDICIÓN VENDEDORES POR RANGO (PDF)", icon="date_range", bgcolor=COLORES["header_blue"], color="white", width=float("inf"), on_click=lambda _: pedir_pdf("preventistas_rango")),
                            ft.Button("SALDOS MERCADERÍA DEL DÍA (PDF)", icon="inventory_2", bgcolor=COLORES["header_purple"], color="white", width=float("inf"), on_click=lambda _: pedir_pdf("mercaderia_dia")),
                            ft.Button("MERCADERÍA POR VENDEDOR (PDF)", icon="person", bgcolor=COLORES["header_purple"], color="white", width=float("inf"), on_click=lambda _: pedir_pdf("mercaderia_usu")),
                            ft.Divider(),
                            ft.Row([inp_num, ft.Button("REIMPRIMIR N°", icon="print", bgcolor=COLORES["header_blue"], color="white", on_click=lambda _: pedir_pdf("factura_unica"))]),
                            ft.Button("IMPRIMIR TODAS LAS FACTURAS DEL DÍA", icon="print", bgcolor="#0F172A", color="white", width=float("inf"), on_click=lambda _: pedir_pdf("lote_diario")),
                        ], spacing=10, scroll="auto")
                    )
                ], spacing=0, expand=True)

            # ------------------------------------------------------
            # REASIGNAR TICKETS
            # ------------------------------------------------------
            elif page.route == "/reasignar_tickets":
                lista_reasignar = ft.ListView(expand=True, spacing=0)
                lista_prev = [r[0] for r in db("SELECT DISTINCT nombre FROM Preventistas", fetch=True, fetchall=True)] or ["ADMIN"]

                def cargar_reasignar():
                    lista_reasignar.controls.clear()
                    filas = db("SELECT f.numero_factura, f.fecha, c.nombre_apellido, f.preventista FROM Facturas f JOIN Clientes c ON f.numero_cliente = c.numero_cliente ORDER BY f.numero_factura DESC LIMIT 60", fetch=True, fetchall=True)
                    for num_f, fec, nom_c, prev_act in (filas or []):
                        dd_p = ft.Dropdown(options=[ft.dropdown.Option(text=u) for u in lista_prev], value=prev_act if prev_act in lista_prev else lista_prev[0], width=135, dense=True)
                        def guardar_cam(n_f=num_f, d_p=dd_p):
                            return lambda _: (db("UPDATE Facturas SET preventista = ? WHERE numero_factura = ?", (d_p.value, n_f)), mostrar_snack(page, f"Factura #{n_f} reasignada a {d_p.value}", COLORES["success"]))
                        lista_reasignar.controls.append(
                            ft.Container(
                                padding=10,
                                border=ft.border.only(bottom=ft.BorderSide(1, COLORES["divider"])),
                                content=ft.Row([
                                    ft.Column([
                                        ft.Text(f"#{num_f}  {nom_c}", size=14, weight="bold"),
                                        ft.Text(fecha_ui(fec), size=12, color=COLORES["muted"], weight="bold"),
                                    ], spacing=2, expand=True),
                                    dd_p,
                                    ft.IconButton("save", icon_color=COLORES["success"], on_click=guardar_cam())
                                ])
                            )
                        )
                    page.update()

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("menu", icon_color="white", on_click=abrir_menu_lateral),
                            ft.Text("Reasignar Tickets", size=19, weight="bold", color="white", expand=True),
                        ])
                    ),
                    lista_reasignar
                ], spacing=0, expand=True)
                cargar_reasignar()

            # ------------------------------------------------------
            # CARGA INTELIGENTE IA (CON BLOQUEO ANTI-DUPLICADOS)
            # ------------------------------------------------------
            elif page.route == "/carga_inteligente":
                inp_magico = ft.TextField(label="Formato: CLIENTE: JUAN | DIRECCION: CALLE 1 | ART-001: 2", multiline=True, min_lines=6, expand=True)

                def procesar_ia(e):
                    btn = e.control
                    btn.disabled = True
                    page.update()
                    texto = (inp_magico.value or "").strip()
                    if not texto:
                        btn.disabled = False
                        page.update()
                        return
                    try:
                        partes = texto.split("|")
                        nom_cli = None
                        dir_cli = "SIN DIRECCIÓN"
                        items = []
                        for p in partes:
                            if ":" not in p:
                                continue
                            k, v = p.split(":", 1)
                            k, v = k.strip().upper(), v.strip().upper()
                            if k == "CLIENTE":
                                nom_cli = v
                            elif k in ("DIRECCION", "DIRECCIÓN"):
                                dir_cli = v
                            else:
                                items.append((k, float(v.replace(",", "."))))
                        if not nom_cli or not items:
                            btn.disabled = False
                            page.update()
                            return
                        res_c = db("SELECT numero_cliente FROM Clientes WHERE UPPER(nombre_apellido) = ?", (nom_cli,), fetch=True)
                        num_cli = res_c[0] if res_c else db("INSERT INTO Clientes (nombre_apellido, direccion_entrega) VALUES (?, ?)", (nom_cli, dir_cli))
                        f_hoy = date.today().strftime("%Y-%m-%d")
                        if db("SELECT COUNT(*) FROM Facturas WHERE numero_cliente = ? AND fecha = ?", (num_cli, f_hoy), fetch=True)[0] > 0:
                            mostrar_snack(page, "❌ Este cliente ya tiene factura hoy.", COLORES["danger"])
                            btn.disabled = False
                            page.update()
                            return
                        detalles = []
                        total_f = 0.0
                        for cod, cant in items:
                            pr = db("SELECT nombre_articulo, precio_unitario FROM Productos WHERE codigo_articulo = ?", (cod,), fetch=True)
                            if not pr:
                                mostrar_snack(page, f"No existe artículo {cod}", COLORES["danger"])
                                btn.disabled = False
                                page.update()
                                return
                            detalles.append((cod, pr[0], pr[1], cant, pr[1] * cant))
                            total_f += pr[1] * cant
                        crear_factura_con_detalle(f_hoy, num_cli, total_f, usuario_actual, detalles)
                        inp_magico.value = ""
                        page.navigate("/")
                    except Exception as ex:
                        mostrar_snack(page, f"Error: {ex}", COLORES["danger"])
                        btn.disabled = False
                        page.update()

                cuerpo_principal = ft.Column([
                    ft.Container(
                        bgcolor=COLORES["header_blue"],
                        padding=ft.padding.symmetric(horizontal=6, vertical=6),
                        content=ft.Row([
                            ft.IconButton("menu", icon_color="white", on_click=abrir_menu_lateral),
                            ft.Text("Carga Inteligente (IA)", size=19, weight="bold", color="white", expand=True),
                        ])
                    ),
                    ft.Container(
                        padding=16,
                        expand=True,
                        content=ft.Column([
                            inp_magico,
                            ft.Button("PROCESAR PEDIDO", icon="bolt", bgcolor=COLORES["header_blue"], color="white", width=float("inf"), on_click=procesar_ia)
                        ], spacing=12, expand=True)
                    )
                ], spacing=0, expand=True)

            # Ensamble final
            page.views.append(
                ft.View(
                    page.route,
                    [ft.Stack([cuerpo_principal, overlay_modal], expand=True)],
                    padding=0,
                    spacing=0,
                    bgcolor="#FFFFFF"
                )
            )
            page.update()

        page.on_route_change = cambiar_pantalla
        registrar_inicio("Manejador de rutas registrado; iniciando preparación de la base de datos en segundo plano")

        async def completar_inicio():
            try:
                await asyncio.to_thread(inicializar_base_datos)
                registrar_inicio("Base de datos inicializada correctamente")
                page.clean()
                registrar_inicio("Base de datos lista; navegando con la API compatible de Flet 1.0.4 hacia /login")
                await page.push_route("/login")
                registrar_inicio(f"Solicitud page.push_route('/login') ejecutada; ruta observada inmediatamente: {page.route}")
            except Exception:
                detalle_error_inicio = traceback.format_exc()
                registrar_inicio("ERROR AL PREPARAR LA APLICACIÓN", detalle_error_inicio)
                try:
                    page.clean()
                    page.add(
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text("XIOMI DISTRIBUIDORA", size=20, weight="bold", color="white"),
                                    ft.Text("No se pudo preparar la aplicación", size=17, weight="bold", color="white"),
                                    ft.Text("Sacá una captura de este mensaje para corregir el problema.", size=12, color="#E5E7EB"),
                                    ft.Text(detalle_error_inicio[-3000:], size=11, color="#FCA5A5", selectable=True),
                                ],
                                scroll=ft.ScrollMode.AUTO,
                                spacing=10,
                                expand=True,
                            ),
                            padding=16,
                            expand=True,
                            bgcolor="#111827",
                        )
                    )
                    page.update()
                except Exception:
                    registrar_inicio("No se pudo mostrar el error de inicialización", traceback.format_exc())

        page.run_task(completar_inicio)

    except Exception:
        detalle_error = traceback.format_exc()
        registrar_inicio("ERROR CRÍTICO DURANTE EL INICIO", detalle_error)

        # Conservar la vista raíz de Flet: si se vacía page.views, page.add() falla.
        try:
            page.clean()
        except Exception:
            try:
                page.controls.clear()
            except Exception:
                pass
        try:
            page.add(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("XIOMI DISTRIBUIDORA", size=20, weight="bold", color="white"),
                            ft.Text("Error al iniciar", size=17, weight="bold", color="white"),
                            ft.Text("Sacá una captura de este mensaje para corregir el problema.", size=12, color="#E5E7EB"),
                            ft.Text(detalle_error[-3500:], size=11, color="#FCA5A5", selectable=True),
                        ],
                        scroll=ft.ScrollMode.AUTO,
                        spacing=10,
                        expand=True,
                    ),
                    padding=16,
                    expand=True,
                    bgcolor="#111827",
                )
            )
            page.update()
            registrar_inicio("Pantalla de diagnóstico mostrada")
        except Exception:
            registrar_inicio("No se pudo dibujar la pantalla de diagnóstico; revisar el registro guardado", traceback.format_exc())

if __name__ == "__main__":
    ft.run(main)