"""Entrada Android de XIOMI Distribuidora: iniciar directamente y reportar errores visibles."""
import traceback
import flet as ft


def main(page: ft.Page):
    page.title = "XIOMI Distribuidora"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#FFFFFF"
    page.padding = 12
    page.spacing = 0

    def mostrar_error(exc):
        detalle = traceback.format_exc()
        page.clean()
        page.bgcolor = "#FFFFFF"
        page.add(
            ft.Container(
                expand=True,
                padding=16,
                content=ft.Column(
                    [
                        ft.Icon("error_outline", size=42, color="#B91C1C"),
                        ft.Text("XIOMI NO PUDO INICIAR", size=21, weight=ft.FontWeight.BOLD, color="#B91C1C"),
                        ft.Text(f"{type(exc).__name__}: {exc}", size=15, color="#111827", selectable=True),
                        ft.Text(detalle[-5000:], size=11, color="#374151", selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    expand=True,
                ),
            )
        )
        page.update()

    # Confirmar visualmente que el punto de entrada Python sí se ejecutó.
    page.add(
        ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                [
                    ft.ProgressRing(width=38, height=38, stroke_width=4, color="#2C4B70"),
                    ft.Text("XIOMI DISTRIBUIDORA", size=22, weight=ft.FontWeight.BOLD, color="#2C4B70"),
                    ft.Text("Iniciando el sistema...", size=14, color="#374151"),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=16,
            ),
        )
    )
    page.update()

    try:
        from main import main as iniciar_sistema
        page.clean()
        iniciar_sistema(page)
        page.update()
    except Exception as exc:
        mostrar_error(exc)


ft.run(main)
