"""Ponto de entrada do Otimizador.

Uso:
    python main.py              (pede elevação de administrador; se negada, abre em modo limitado)
    python main.py --no-elevate (abre sem pedir administrador)
"""
import sys

from otimizador.core.utils import is_admin, relaunch_as_admin


def main():
    if "--no-elevate" not in sys.argv and not is_admin():
        if relaunch_as_admin():
            return
    from otimizador.ui.app import run

    run()


if __name__ == "__main__":
    main()
