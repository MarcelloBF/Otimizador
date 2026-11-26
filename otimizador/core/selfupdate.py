"""Verifica novas versões no GitHub e atualiza o próprio .exe."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

from .utils import APP_VERSION, data_dir

REPO = "MarcelloBF/Otimizador"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET_NAME = "Otimizador.exe"
CHECK_INTERVAL_S = 6 * 3600
USER_AGENT = "Otimizador-updater"


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def _state_path() -> Path:
    return data_dir() / "update_check.json"


def _state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(s: dict) -> None:
    _state_path().write_text(json.dumps(s), encoding="utf-8")


def skip_version(version: str) -> None:
    s = _state()
    s["skipped"] = version
    _save_state(s)


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URL fixa do GitHub
        return json.loads(r.read().decode("utf-8"))


def release_info(data: dict) -> dict:
    tag = data.get("tag_name") or ""
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET_NAME), None)
    digest = (asset or {}).get("digest") or ""
    return {
        "version": tag.lstrip("vV"),
        "url": data.get("html_url") or RELEASES_PAGE,
        "notes": data.get("body") or "",
        "asset_url": (asset or {}).get("browser_download_url"),
        "asset_size": (asset or {}).get("size"),
        "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
    }


def check(force: bool = False, timeout: float = 8) -> dict | None:
    """Devolve a versão nova (dict) ou None. Consulta o GitHub no máximo a cada 6 h, salvo force=True."""
    s = _state()
    now = time.time()
    if not force and now - s.get("last_check", 0) < CHECK_INTERVAL_S:
        info = s.get("latest")
    else:
        info = release_info(_get_json(API_LATEST, timeout))
        s.update(last_check=now, latest=info)
        _save_state(s)
    if not info or not is_newer(info.get("version", "")):
        return None
    if not force and s.get("skipped") == info["version"]:
        return None
    return info


def can_self_update(info: dict | None) -> bool:
    return bool(getattr(sys, "frozen", False) and info and info.get("asset_url"))


def download(info: dict, progress: Callable[[int, int], None] = lambda done, total: None) -> Path:
    exe = Path(sys.executable)
    dest = exe.with_name(exe.stem + ".new.exe")
    req = urllib.request.Request(info["asset_url"], headers={"User-Agent": USER_AGENT})
    h = hashlib.sha256()
    total = int(info.get("asset_size") or 0)
    done = 0
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:  # noqa: S310
        total = total or int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done, total)
    try:
        if total and done != total:
            raise RuntimeError("Download incompleto. Tente de novo.")
        if info.get("sha256") and h.hexdigest() != info["sha256"]:
            raise RuntimeError("O arquivo baixado não confere com o publicado no GitHub.")
        with open(dest, "rb") as f:
            if f.read(2) != b"MZ":
                raise RuntimeError("O arquivo baixado não é um executável válido.")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest


def install_and_restart(new_exe: Path) -> None:
    """Troca o .exe em uso pelo novo e abre a nova versão. O chamador deve fechar o app em seguida."""
    cur = Path(sys.executable)
    old = cur.with_name(cur.stem + ".old.exe")
    old.unlink(missing_ok=True)
    os.replace(cur, old)  # o Windows permite renomear um .exe em execução
    try:
        os.replace(new_exe, cur)
    except Exception:
        os.replace(old, cur)
        raise
    subprocess.Popen([str(cur)], close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS


def cleanup_old() -> None:
    if not getattr(sys, "frozen", False):
        return
    cur = Path(sys.executable)
    for p in (cur.with_name(cur.stem + ".old.exe"), cur.with_name(cur.stem + ".new.exe")):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
