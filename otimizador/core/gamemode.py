"""Modo Jogo: fecha programas em segundo plano e ativa o plano de energia de desempenho; desfaz ao sair."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field

import psutil

from . import tweaks as T
from .utils import CREATE_NO_WINDOW, data_dir, run_ps

# nome do processo (minúsculo) -> (nome exibido, marcado por padrão, motivo)
CANDIDATES: dict[str, tuple[str, bool, str]] = {
    "ms-teams.exe": ("Microsoft Teams", True, "Usa bastante RAM e CPU em segundo plano"),
    "teams.exe": ("Microsoft Teams (clássico)", True, "Usa bastante RAM e CPU em segundo plano"),
    "onedrive.exe": ("OneDrive", True, "Sincronização usa disco e internet"),
    "googledrivefs.exe": ("Google Drive", True, "Sincronização usa disco e internet"),
    "dropbox.exe": ("Dropbox", True, "Sincronização usa disco e internet"),
    "creative cloud.exe": ("Adobe Creative Cloud", True, "Atualizações e sincronização em segundo plano"),
    "ollama app.exe": ("Ollama", True, "Modelos carregados ocupam memória da placa de vídeo"),
    "ollama.exe": ("Ollama (servidor)", True, "Modelos carregados ocupam memória da placa de vídeo"),
    "phoneexperiencehost.exe": ("Vincular ao Celular", True, "Fica sincronizando com o celular"),
    "widgets.exe": ("Widgets do Windows", True, "Notícias e clima em segundo plano"),
    "spotify.exe": ("Spotify", False, "Feche se não for ouvir música jogando"),
    "chrome.exe": ("Google Chrome", False, "Navegadores costumam ser o que mais usa RAM"),
    "msedge.exe": ("Microsoft Edge", False, "Navegadores costumam ser o que mais usa RAM"),
    "firefox.exe": ("Firefox", False, "Navegadores costumam ser o que mais usa RAM"),
    "opera.exe": ("Opera", False, "Navegadores costumam ser o que mais usa RAM"),
    "opera_gx.exe": ("Opera GX", False, "Navegadores costumam ser o que mais usa RAM"),
    "brave.exe": ("Brave", False, "Navegadores costumam ser o que mais usa RAM"),
    "code.exe": ("Visual Studio Code", False, "Editor com extensões em segundo plano"),
    "docker desktop.exe": ("Docker Desktop", False, "A máquina virtual do Docker reserva muita RAM"),
    "epicgameslauncher.exe": ("Epic Games Launcher", False, "Feche se o jogo não for da Epic"),
    "eadesktop.exe": ("EA app", False, "Feche se o jogo não for da EA"),
    "upc.exe": ("Ubisoft Connect", False, "Feche se o jogo não for da Ubisoft"),
    "battle.net.exe": ("Battle.net", False, "Feche se o jogo não for da Blizzard"),
    "whatsapp.exe": ("WhatsApp", False, "Mensagens e notificações durante o jogo"),
    "whatsapp.root.exe": ("WhatsApp", False, "Mensagens e notificações durante o jogo"),
    "telegram.exe": ("Telegram", False, "Mensagens e notificações durante o jogo"),
}

# Voltam sozinhos (ou são abertos pelo programa principal): não reabrir
NO_REOPEN = {"ollama.exe", "widgets.exe", "phoneexperiencehost.exe"}


@dataclass
class Candidate:
    key: str  # nome do processo em minúsculo
    name: str
    default: bool
    reason: str
    pids: list[int] = field(default_factory=list)
    exe: str | None = None
    ram: int = 0  # memória privada somada de todos os processos


def _state_path():
    return data_dir() / "gamemode.json"


def _prefs_path():
    return data_dir() / "gamemode_prefs.json"


def state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_active() -> bool:
    return bool(state().get("active"))


def load_prefs() -> dict:
    try:
        return json.loads(_prefs_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_prefs(prefs: dict) -> None:
    _prefs_path().write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")


def scan() -> list[Candidate]:
    """Programas da lista que estão abertos agora, do que mais usa RAM para o que menos usa."""
    found: dict[str, Candidate] = {}
    me = os.getpid()
    for p in psutil.process_iter(["name", "pid"]):
        try:
            key = (p.info["name"] or "").lower()
            if key not in CANDIDATES or p.info["pid"] == me:
                continue
            name, default, reason = CANDIDATES[key]
            c = found.setdefault(key, Candidate(key, name, default, reason))
            c.pids.append(p.info["pid"])
            mi = p.memory_info()
            c.ram += getattr(mi, "private", 0) or mi.rss
            if c.exe is None:
                c.exe = p.exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    # O mesmo programa com dois nomes (ex.: WhatsApp) aparece uma vez só
    merged: dict[str, Candidate] = {}
    for c in found.values():
        if c.name in merged:
            m = merged[c.name]
            m.pids += c.pids
            m.ram += c.ram
        else:
            merged[c.name] = c
    return sorted(merged.values(), key=lambda c: c.ram, reverse=True)


# ----------------------------------------------------------------- reabrir sem administrador


def _packaged_app_id(exe: str) -> str | None:
    """Programas da Microsoft Store não abrem pelo .exe: precisa do AppID (shell:AppsFolder)."""
    m = re.search(r"\\WindowsApps\\([^\\]+)\\", exe or "", re.I)
    if not m:
        return None
    parts = m.group(1).split("_")
    if len(parts) < 5:
        return None
    family = f"{parts[0]}_{parts[-1]}"
    out = run_ps(f"(Get-StartApps | Where-Object {{ $_.AppID -like '{family}!*' }} | Select-Object -First 1).AppID",
                 timeout=30).strip()
    return out or None


def launch_target(c: Candidate) -> dict | None:
    if not c.exe or c.key in NO_REOPEN:
        return None
    app_id = _packaged_app_id(c.exe)
    if app_id:
        return {"name": c.name, "shell": f"shell:AppsFolder\\{app_id}"}
    return {"name": c.name, "exe": c.exe}


def reopen(target: dict) -> None:
    # explorer.exe abre o programa como usuário comum, mesmo que o Otimizador esteja como administrador
    if target.get("shell"):
        subprocess.Popen(["explorer.exe", target["shell"]], creationflags=CREATE_NO_WINDOW)
        return
    exe = target.get("exe")
    if exe and os.path.exists(exe):
        subprocess.Popen(["explorer.exe", exe], creationflags=CREATE_NO_WINDOW)


# ----------------------------------------------------------------- fechar


def close(c: Candidate, grace_s: float = 4.0) -> bool:
    """Pede para fechar (como clicar no X); o que continuar aberto é encerrado. True se fechou."""
    procs = []
    for pid in c.pids:
        try:
            procs.append(psutil.Process(pid))
        except psutil.NoSuchProcess:
            pass
    for p in procs:
        subprocess.run(["taskkill", "/PID", str(p.pid)], capture_output=True, creationflags=CREATE_NO_WINDOW)
    _, alive = psutil.wait_procs(procs, timeout=grace_s)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(alive, timeout=3)
    return not alive


# ----------------------------------------------------------------- ativar / desativar


def _high_perf_active() -> bool:
    cur = T._active_scheme()
    return cur in (T.HIGH_PERF, T._ultimate_guid(False))


def activate(selected: list[Candidate], power: bool, log=lambda s: None) -> dict:
    before = psutil.virtual_memory().available
    st = {"active": True, "since": dt.datetime.now().isoformat(timespec="seconds"), "closed": [],
          "previous_plan": None, "failed": []}
    if power:
        try:
            if _high_perf_active():
                log("Plano de energia já está em alto desempenho.")
            else:
                st["previous_plan"] = T._active_scheme()
                if T.HIGH_PERF not in [g for g, _ in T._list_schemes()]:
                    T.run_cmd(["powercfg", "-duplicatescheme", T.HIGH_PERF, T.HIGH_PERF])
                T._set_scheme(T.HIGH_PERF)
                log("Plano de energia: Alto desempenho.")
        except Exception as e:  # noqa: BLE001
            log(f"Não foi possível trocar o plano de energia: {e}")
    # Salva o estado antes de fechar: se o app cair no meio, dá para desfazer depois
    _state_path().write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    for c in selected:
        target = launch_target(c)
        if close(c):
            log(f"Fechado: {c.name}")
            if target:
                st["closed"].append(target)
        else:
            log(f"Não fechou: {c.name}")
            st["failed"].append(c.name)
        _state_path().write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    time.sleep(1.5)
    st["freed"] = max(0, psutil.virtual_memory().available - before)
    _state_path().write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return st


def deactivate(reopen_apps: bool, log=lambda s: None) -> dict:
    st = state()
    if st.get("previous_plan"):
        try:
            T._set_scheme(st["previous_plan"])
            log("Plano de energia restaurado.")
        except Exception as e:  # noqa: BLE001
            log(f"Não foi possível restaurar o plano de energia: {e}")
    if reopen_apps:
        running = {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
        for t in st.get("closed", []):
            exe_name = os.path.basename(t.get("exe") or "").lower()
            if exe_name and exe_name in running:
                continue
            try:
                reopen(t)
                log(f"Reaberto: {t['name']}")
            except Exception as e:  # noqa: BLE001
                log(f"Não foi possível reabrir {t['name']}: {e}")
    _state_path().unlink(missing_ok=True)
    return st
