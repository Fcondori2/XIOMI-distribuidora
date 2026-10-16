"""Punto de entrada Android de XIOMI Distribuidora.

Mantiene un único flujo de inicio: delega directamente en main.py, que ya
muestra la pantalla de preparación, inicializa la base de datos en segundo
plano y registra errores de inicio. Evita tareas anidadas y limpiezas de
pantalla desde un segundo cargador, que podían dejar una vista gris vacía.
"""
import traceback

import flet as ft


def main(page: ft.Page):
    try:
        # Importar y ejecutar en el mismo flujo de Flet evita una segunda
        # tarea de arranque compitiendo con la navegación de main.py.
        from main import main as iniciar_aplicacion

        iniciar_aplicacion(page)
    except Exception as exc:
        detalle = traceback.format_exc()
        try:
            page.clean()
            page.bgcolor = "#111827"
            page.padding = 16
            page.add(
                ft.Column(
                    [
                        ft.Text(
                            "XIOMI DISTRIBUIDORA",
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color="#FFFFFF",
                        ),
                        ft.Text(
                            "No se pudo iniciar la aplicación",
                            size=17,
                            weight=ft.FontWeight.BOLD,
                            color="#FCA5A5",
                        ),
                        ft.Text(
                            f"{type(exc).__name__}: {exc}",
                            size=14,
                            color="#FFFFFF",
                            selectable=True,
                        ),
                        ft.Text(
                            detalle[-7000:],
                            size=11,
                            color="#E5E7EB",
                            selectable=True,
                        ),
                    ],
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                )
            )
            page.update()
        except Exception:
            print("[XIOMI-ARRANQUE] " + detalle, flush=True)


if __name__ == "__main__":
    ft.run(main)
