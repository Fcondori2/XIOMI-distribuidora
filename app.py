"""Punto de entrada ligero para Android.

Muestra una pantalla inmediatamente y carga el programa principal después.
Si main.py falla durante la importación o el arranque, presenta el error en pantalla
en vez de dejar al usuario indefinidamente en el splash nativo de Flet.
"""
import asyncio
import importlib
import traceback

import flet as ft


def main(page: ft.Page):
    page.title = "XIOMI Distribuidora"
    page.bgcolor = "#FFFFFF"
    page.padding = 24
    page.spacing = 12
    page.add(
        ft.Text("XIOMI Distribuidora", size=24, weight=ft.FontWeight.BOLD),
        ft.Text("Preparando el sistema…", size=16),
        ft.ProgressRing(),
    )
    page.update()

    async def iniciar():
        try:
            # Importar en un hilo evita bloquear la interfaz mientras se carga
            # main.py y permite mostrar cualquier error de importación.
            modulo = await asyncio.to_thread(importlib.import_module, "main")
            funcion_principal = getattr(modulo, "main", None)
            if not callable(funcion_principal):
                raise RuntimeError("No se encontró la función main(page) en main.py")

            page.clean()
            funcion_principal(page)
            page.update()
        except Exception as exc:
            detalle = traceback.format_exc()
            try:
                page.clean()
                page.add(
                    ft.Text("No se pudo iniciar XIOMI Distribuidora", size=21,
                            weight=ft.FontWeight.BOLD, color="#B91C1C"),
                    ft.Text(
                        f"Error: {type(exc).__name__}: {exc}",
                        size=15,
                        selectable=True,
                    ),
                    ft.Text(
                        "Copiá este mensaje para identificar la causa. "
                        "Los datos de la aplicación no se borraron.",
                        size=13,
                    ),
                    ft.Text(detalle[-7000:], size=11, selectable=True),
                )
                page.update()
            except Exception:
                print("[XIOMI-ARRANQUE] " + detalle, flush=True)

    page.run_task(iniciar)


if __name__ == "__main__":
    ft.run(main)
