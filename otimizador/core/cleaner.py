"""Limpeza de arquivos temporários, caches e lixeira."""
from __future__ import annotations

import ctypes
import glob
import os
import time
from ctypes import wintypes
from dataclasses import dataclass, field

from .utils import is_admin, run_ps

LOCAL = os.environ.get("LOCALAPPDATA", "")
ROAMING = os.environ.get("APPDATA", "")
WINDIR = os.environ.get("WINDIR", r"C:\Windows")
PROGRAMDATA = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
TEMP = os.environ.get("TEMP", os.path.join(LOCAL, "Temp"))


@dataclass
class CleanTarget:
    id: str
    name: str
    description: str
    patterns: list[str]  # pastas (conteúdo é limpo) ou globs de arquivos
    default: bool = True
    admin: bool = False
    min_age_h: float = 0  # só apaga arquivos mais velhos que isso
    size: int = 0
    files: int = 0
    paths: list[str] = field(default_factory=list)


def _browser_dirs(base: str, subdirs: list[str]) -> list[str]:
    return [os.path.join(base, "*", s) for s in subdirs]


def targets() -> list[CleanTarget]:
    chrome = os.path.join(LOCAL, r"Google\Chrome\User Data")
    edge = os.path.join(LOCAL, r"Microsoft\Edge\User Data")
    brave = os.path.join(LOCAL, r"BraveSoftware\Brave-Browser\User Data")
    opera = os.path.join(ROAMING, r"Opera Software\Opera GX Stable")
    cache_sub = ["Cache", "Code Cache", "GPUCache", r"Service Worker\CacheStorage"]
    return [
        CleanTarget("user_temp", "Arquivos temporários do usuário", "Pasta %TEMP%: sobras de instaladores e programas.",
                    [TEMP], min_age_h=2),
        CleanTarget("win_temp", "Arquivos temporários do Windows", r"C:\Windows\Temp.",
                    [os.path.join(WINDIR, "Temp")], admin=True, min_age_h=2),
        CleanTarget("wu_cache", "Cache do Windows Update", "Instaladores de atualizações já aplicadas. Pode ser grande.",
                    [os.path.join(WINDIR, r"SoftwareDistribution\Download")], admin=True, min_age_h=24),
        CleanTarget("delivery_opt", "Cache de Otimização de Entrega", "Atualizações baixadas para compartilhar com outros PCs.",
                    [os.path.join(WINDIR, r"ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache")],
                    admin=True),
        CleanTarget("crash", "Relatórios de erro e despejos de memória", "Logs de travamentos (WER) e minidumps.",
                    [os.path.join(PROGRAMDATA, r"Microsoft\Windows\WER\ReportArchive"),
                     os.path.join(PROGRAMDATA, r"Microsoft\Windows\WER\ReportQueue"),
                     os.path.join(LOCAL, "CrashDumps"), os.path.join(WINDIR, "Minidump"),
                     os.path.join(WINDIR, "MEMORY.DMP")]),
        CleanTarget("thumbs", "Cache de miniaturas", "Miniaturas de imagens do Explorador (são recriadas automaticamente).",
                    [os.path.join(LOCAL, r"Microsoft\Windows\Explorer\thumbcache_*.db"),
                     os.path.join(LOCAL, r"Microsoft\Windows\Explorer\iconcache_*.db")], default=False),
        CleanTarget("browsers", "Cache dos navegadores", "Chrome, Edge, Brave, Opera GX e Firefox. Não apaga senhas, histórico nem logins.",
                    _browser_dirs(chrome, cache_sub) + _browser_dirs(edge, cache_sub) + _browser_dirs(brave, cache_sub)
                    + [os.path.join(opera, s) for s in cache_sub]
                    + [os.path.join(LOCAL, r"Mozilla\Firefox\Profiles\*\cache2")], default=True),
        CleanTarget("shader", "Cache de shaders (DirectX/GPU)", "Caches de shader do Windows, NVIDIA, AMD e Intel. Limpe só se tiver "
                    "travamentos gráficos após atualizar o driver — os jogos recompilam na próxima vez (pode travar um pouco no início).",
                    [os.path.join(LOCAL, "D3DSCache"), os.path.join(LOCAL, r"NVIDIA\DXCache"), os.path.join(LOCAL, r"NVIDIA\GLCache"),
                     os.path.join(LOCAL, r"AMD\DxCache"), os.path.join(LOCAL, r"AMD\DxcCache"), os.path.join(LOCAL, r"AMD\GLCache"),
                     os.path.join(LOCAL, r"Intel\ShaderCache")], default=False),
        CleanTarget("logs", "Logs antigos do Windows", "Registros de instalação e de componentes (CBS, DISM, etc.) com mais de 7 dias.",
                    [os.path.join(WINDIR, r"Logs\CBS\*.log"), os.path.join(WINDIR, r"Logs\DISM\*.log"),
                     os.path.join(WINDIR, r"Panther\*.log")], admin=True, min_age_h=24 * 7),
        CleanTarget("recycle", "Lixeira", "Esvazia a Lixeira de todas as unidades.", [], default=True),
    ]


# --------------------------------------------------------------------------- lixeira


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_info() -> tuple[int, int]:
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
        return info.i64Size, info.i64NumItems
    return 0, 0


def empty_recycle_bin() -> None:
    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)


# --------------------------------------------------------------------------- varredura


def _expand(pattern: str) -> list[str]:
    if any(ch in pattern for ch in "*?["):
        return glob.glob(pattern)
    return [pattern] if os.path.exists(pattern) else []


def _walk_files(path: str):
    if os.path.isfile(path):
        yield path
        return
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            yield e.path
                    except OSError:
                        continue
        except OSError:
            continue


def scan(t: CleanTarget) -> CleanTarget:
    t.size, t.files, t.paths = 0, 0, []
    if t.id == "recycle":
        t.size, t.files = recycle_bin_info()
        return t
    if t.admin and not is_admin():
        return t
    cutoff = time.time() - t.min_age_h * 3600
    for pat in t.patterns:
        for root in _expand(pat):
            t.paths.append(root)
            for f in _walk_files(root):
                try:
                    st = os.stat(f)
                    if t.min_age_h and st.st_mtime > cutoff:
                        continue
                    t.size += st.st_size
                    t.files += 1
                except OSError:
                    pass
    return t


def scan_all(progress=None) -> list[CleanTarget]:
    ts = targets()
    for i, t in enumerate(ts):
        if progress:
            progress(i, len(ts), t.name)
        scan(t)
    return ts


def clean(t: CleanTarget) -> tuple[int, int]:
    """Apaga os arquivos do alvo. Retorna (bytes liberados, arquivos ignorados por estarem em uso)."""
    if t.id == "recycle":
        size, _ = recycle_bin_info()
        empty_recycle_bin()
        return size, 0
    if t.admin and not is_admin():
        return 0, 0
    if t.id == "delivery_opt":
        run_ps("Delete-DeliveryOptimizationCache -Force")
    freed, skipped = 0, 0
    cutoff = time.time() - t.min_age_h * 3600
    for pat in t.patterns:
        for root in _expand(pat):
            for f in list(_walk_files(root)):
                try:
                    st = os.stat(f)
                    if t.min_age_h and st.st_mtime > cutoff:
                        continue
                    os.chmod(f, 0o666)
                    os.remove(f)
                    freed += st.st_size
                except OSError:
                    skipped += 1
            # remove pastas vazias que sobraram (mantém a pasta raiz)
            if os.path.isdir(root):
                for dirpath, dirnames, filenames in os.walk(root, topdown=False):
                    if dirpath != root and not os.listdir(dirpath):
                        try:
                            os.rmdir(dirpath)
                        except OSError:
                            pass
    return freed, skipped


def quick_junk_estimate() -> int:
    """Estimativa rápida (só temp do usuário + lixeira) para o diagnóstico."""
    total = 0
    for t in targets():
        if t.id in ("user_temp", "recycle", "crash"):
            total += scan(t).size
    return total
