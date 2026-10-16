"""Punto de entrada Android de XIOMI Distribuidora."""
import traceback
import flet as ft


def main(page: ft.Page):
    page.title = "XIOMI Distribuidora - Diagnóstico"
    page.bgcolor = "#FFFFFF"
    page.padding = 20
    page.theme_mode = ft.ThemeMode.LIGHT

    estado = ft.Text(
        "Si ves esta pantalla, Flet está dibujando la interfaz correctamente.",
        size=16,
        color="#1F2937",
        selectable=True,
        text_align=ft.TextAlign.CENTER,
    )

    def iniciar_sistema(_):
        boton.disabled = True
        estado.value = "Cargando el sistema de gestión..."
        page.update()
        try:
            from main import main as iniciar_aplicacion
            page.clean()
            iniciar_aplicacion(page)
            page.update()
        except Exception as exc:
            error = traceback.format_exc()
            page.clean()
            page.bgcolor = "#FFFFFF"
            page.add(
                ft.Column(
                    [
                        ft.Text("XIOMI: ERROR AL INICIAR", size=22, weight=ft.FontWeight.BOLD, color="#B91C1C"),
                        ft.Text(f"{type(exc).__name__}: {exc}", size=15, color="#111827", selectable=True),
                        ft.Text(error[-8000:], size=11, color="#374151", selectable=True),
                        ft.ElevatedButton("Volver a probar", on_click=reiniciar_pantalla),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                    spacing=12,
                )
            )
            page.update()

    def reiniciar_pantalla(_):
        page.clean()
        main(page)

    boton = ft.ElevatedButton(
        "ABRIR SISTEMA XIOMI",
        on_click=iniciar_sistema,
        bgcolor="#2C4B70",
        color="#FFFFFF",
        width=300,
        height=52,
    )

    page.add(
        ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                [
                    ft.Icon("storefront", size=58, color="#2C4B70"),
                    ft.Text("XIOMI DISTRIBUIDORA", size=24, weight=ft.FontWeight.BOLD, color="#2C4B70"),
                    ft.Text("Diagnóstico de inicio", size=18, weight=ft.FontWeight.BOLD, color="#111827"),
                    estado,
                    boton,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=18,
                scroll=ft.ScrollMode.AUTO,
            ),
        )
    )
    page.update()


# Importante: Flet debe ejecutar el punto de entrada también cuando empaqueta
# el módulo para Android; no depender de __name__ == "__main__".
ft.run(main)
