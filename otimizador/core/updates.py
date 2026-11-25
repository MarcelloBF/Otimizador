"""Atualização de programas via winget e verificação dos drivers de vídeo."""
from __future__ import annotations

import codecs
import datetime as dt
import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from typing import Callable

from .utils import CREATE_NO_WINDOW, data_dir

WINGET_COMMON = ["--accept-source-agreements", "--disable-interactivity"]
STORE_APP_INSTALLER = "ms-windows-store://pdp/?productid=9NBLGGH4NNS1"
WINDOWS_OPTIONAL_UPDATES = "ms-settings:windowsupdate-optionalupdates"

# Atualizam o próprio winget ou o ambiente dele: ficam por último
LAST_IDS = ("Microsoft.AppInstaller", "Microsoft.WindowsTerminal", "Microsoft.PowerShell")

# Códigos de saída do winget (APPINSTALLER_CLI_ERROR_*)
EXIT_MESSAGES = {
    0: "Atualizado",
    0x8A150014: "Programa não encontrado (já foi desinstalado?)",
    0x8A15002B: "Nenhuma atualização aplicável",
    0x8A150101: "O programa está aberto: feche-o e tente de novo",
    0x8A150102: "Outra instalação está em andamento",
    0x8A150103: "Um arquivo do programa está em uso",
    0x8A150105: "Disco cheio",
    0x8A150107: "Sem conexão com a internet",
    0x8A150109: "Reinicie o PC para concluir",
    0x8A15010A: "Reinicie o PC antes de atualizar",
}
OK_CODES = {0, 0x8A150109}


@dataclass
class Package:
    name: str
    id: str
    version: str
    available: str
    source: str = ""
    explicit: bool = False  # winget só atualiza se pedido pelo Id (fora do "upgrade --all")

    @property
    def unknown_version(self) -> bool:
        return self.version.strip().lower() in ("unknown", "desconhecido", "desconhecida")

    @property
    def truncated(self) -> bool:
        return self.id.endswith("…")

    @property
    def selectable(self) -> bool:
        return not self.truncated

    @property
    def suggested(self) -> bool:
        """Marcado por padrão: versão conhecida e incluído no 'upgrade --all' do winget."""
        return self.selectable and not self.unknown_version and not self.explicit


# ----------------------------------------------------------------- winget


def winget_path() -> str | None:
    return shutil.which("winget")


def _cell_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _slice_display(line: str, start: int, end: int | None) -> str:
    """Corta a linha por coluna de tela (ideogramas ocupam 2 colunas no console)."""
    out, col = [], 0
    for ch in line:
        w = _cell_width(ch)
        if col >= start and (end is None or col < end):
            out.append(ch)
        col += w
    return "".join(out).strip()


def _column_starts(header: str) -> list[int]:
    starts, col, prev_space = [], 0, True
    for ch in header:
        if ch != " " and prev_space:
            starts.append(col)
        prev_space = ch == " "
        col += _cell_width(ch)
    return starts


def parse_upgrade_table(text: str) -> list[Package]:
    """Lê a(s) tabela(s) de `winget upgrade`. Funciona em qualquer idioma: usa a posição das colunas."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    # Remove restos de animação de progresso antes do cabeçalho
    lines = [ln.split("\r")[-1] for ln in lines]
    pkgs: list[Package] = []
    seen: set[str] = set()
    explicit = False
    i = 0
    while i < len(lines):
        if re.fullmatch(r"-{20,}", lines[i].strip()) and i > 0:
            starts = _column_starts(lines[i - 1])
            if len(starts) < 4:
                i += 1
                continue
            bounds = list(zip(starts, starts[1:] + [None]))
            i += 1
            while i < len(lines) and lines[i].strip():
                row = lines[i]
                cols = [_slice_display(row, a, b) for a, b in bounds]
                # Linha de resumo ("9 upgrades available.") não preenche as colunas do meio
                if len(cols) >= 4 and cols[1] and cols[2] and cols[3] and " " not in cols[1]:
                    p = Package(cols[0], cols[1], cols[2], cols[3], cols[4] if len(cols) > 4 else "", explicit)
                    if p.id not in seen:
                        seen.add(p.id)
                        pkgs.append(p)
                i += 1
            # Tabelas seguintes são as que "exigem seleção explícita"
            explicit = True
            continue
        i += 1
    return pkgs


def list_upgrades(timeout: int = 180) -> list[Package]:
    exe = winget_path()
    if not exe:
        raise FileNotFoundError("winget")
    proc = subprocess.run([exe, "upgrade", "--include-unknown", *WINGET_COMMON], capture_output=True,
                          timeout=timeout, creationflags=CREATE_NO_WINDOW)
    text = proc.stdout.decode("utf-8", errors="replace")
    return parse_upgrade_table(text)


def order_for_install(pkgs: list[Package]) -> list[Package]:
    return sorted(pkgs, key=lambda p: p.id in LAST_IDS)


def exit_message(code: int) -> str:
    code &= 0xFFFFFFFF
    msg = EXIT_MESSAGES.get(code)
    if msg:
        return msg
    return f"Falhou (código 0x{code:08X})"


def is_success(code: int) -> bool:
    return (code & 0xFFFFFFFF) in OK_CODES


_PROGRESS = re.compile(r"[█▒▓░]|^\s*[-\\|/]\s*$")


def upgrade(pkg: Package, on_line: Callable[[str], None], should_stop: Callable[[], bool] = lambda: False) -> int:
    exe = winget_path()
    if not exe:
        raise FileNotFoundError("winget")
    cmd = [exe, "upgrade", "--id", pkg.id, "--exact", "--silent", "--accept-package-agreements", *WINGET_COMMON]
    if pkg.unknown_version:
        cmd.append("--include-unknown")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW,
                            bufsize=0)
    assert proc.stdout is not None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        buf += decoder.decode(chunk)
        idx = max(buf.rfind("\n"), buf.rfind("\r"))
        if idx >= 0:
            text, buf = buf[: idx + 1], buf[idx + 1:]
            for line in text.replace("\r", "\n").split("\n"):
                if line.strip() and not _PROGRESS.search(line):
                    on_line(line.rstrip())
        if should_stop():
            proc.terminate()
            on_line("Interrompido pelo usuário.")
            break
    if buf.strip() and not _PROGRESS.search(buf):
        on_line(buf.strip())
    return proc.wait()


# ----------------------------------------------------------------- ignorados


def _ignore_path():
    return data_dir() / "updates_ignore.json"


def load_ignored() -> set[str]:
    try:
        return set(json.loads(_ignore_path().read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_ignored(ids: set[str]) -> None:
    _ignore_path().write_text(json.dumps(sorted(ids), ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------- drivers de vídeo

DRIVER_PAGES = {
    "nvidia": ("NVIDIA App", "https://www.nvidia.com/pt-br/software/nvidia-app/"),
    "amd": ("AMD Software: Adrenalin Edition", "https://www.amd.com/pt/support/download/drivers.html"),
    "intel": ("Intel Driver & Support Assistant", "https://www.intel.com.br/content/www/br/pt/support/detect.html"),
}


def gpu_drivers(specs: dict | None, today: dt.date | None = None) -> list[dict]:
    """Uma entrada por placa de vídeo: driver instalado, idade e onde baixar o novo."""
    from .sysinfo import gpu_vendor

    today = today or dt.date.today()
    out = []
    for g in (specs or {}).get("gpu", []) or []:
        name = g.get("name") or "?"
        if "basic" in name.lower() or "remote" in name.lower():
            vendor = "outro"
        else:
            vendor = gpu_vendor(name)
        age = None
        if g.get("driver_date"):
            try:
                age = (today - dt.date.fromisoformat(g["driver_date"])).days
            except ValueError:
                age = None
        status = "ok"
        if "basic" in name.lower():
            status = "missing"
        elif age is not None and age > 365:
            status = "old"
        elif age is not None and age > 180:
            status = "aging"
        tool, url = DRIVER_PAGES.get(vendor, ("Windows Update", WINDOWS_OPTIONAL_UPDATES))
        out.append({"name": name, "vendor": vendor, "driver": g.get("driver"), "date": g.get("driver_date"),
                    "age_days": age, "status": status, "tool": tool, "url": url})
    return out
