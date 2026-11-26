"""Funções utilitárias compartilhadas: PowerShell, admin, caminhos, formatação."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

APP_NAME = "Otimizador"
APP_VERSION = "1.4.0"


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Reabre o programa pedindo elevação (UAC). Retorna True se o pedido foi aceito."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(exe):
            exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def oem_encoding() -> str:
    try:
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except Exception:
        return "cp850"


def run_ps(script: str, timeout: int = 120) -> str:
    """Executa um script PowerShell e devolve stdout (UTF-8)."""
    prefix = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';$ErrorActionPreference='SilentlyContinue';"
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prefix + script],
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    return proc.stdout.decode("utf-8", errors="replace")


def run_ps_json(script: str, timeout: int = 120):
    out = run_ps(script, timeout).strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # Pega somente o trecho JSON caso venha lixo antes
        start = min([i for i in (out.find("{"), out.find("[")) if i >= 0], default=-1)
        if start >= 0:
            try:
                return json.loads(out[start:])
            except json.JSONDecodeError:
                return None
        return None


def run_cmd(args, timeout: int = 120, shell: bool = False) -> tuple[int, str]:
    proc = subprocess.run(
        args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW, shell=shell
    )
    raw = proc.stdout + proc.stderr
    return proc.returncode, decode_console(raw)


def decode_console(raw: bytes) -> str:
    # sfc/dism às vezes escrevem UTF-16 sem BOM -> remove bytes nulos
    if raw.count(b"\x00") > len(raw) // 4:
        try:
            return raw.decode("utf-16-le", errors="replace")
        except Exception:
            raw = raw.replace(b"\x00", b"")
    return raw.decode(oem_encoding(), errors="replace").replace("\x00", "")


def fmt_bytes(n: float | int | None, digits: int = 1) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.{digits if unit not in ('B', 'KB') else 0}f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}min"
    if h:
        return f"{h}h {m}min"
    return f"{m}min"


def open_url(url: str) -> None:
    os.startfile(url)  # noqa: S606 - abre no navegador padrão
