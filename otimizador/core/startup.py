"""Programas que iniciam com o Windows (mesmo mecanismo do Gerenciador de Tarefas)."""
from __future__ import annotations

import os
import re
import struct
import time
import winreg
from dataclasses import dataclass

from .utils import is_admin

HKCU = winreg.HKEY_CURRENT_USER
HKLM = winreg.HKEY_LOCAL_MACHINE
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"

# Dicas: (regex no nome/comando, recomendação, motivo)
HINTS = [
    (r"securityhealth|windows defender|msmpeng", "manter", "Proteção do Windows"),
    (r"vanguard|vgtray|easyanticheat|battleye|faceit", "manter", "Anti-cheat (necessário para alguns jogos)"),
    (r"utweb|utorrent|bittorrent|qbittorrent", "desativar", "Torrent: usa rede e disco em segundo plano"),
    (r"ollama|docker|lm studio", "desativar", "Servidor/serviço pesado: abra só quando usar"),
    (r"radmin|hamachi|zerotier|nordvpn|protonvpn|expressvpn", "opcional", "VPN: só se precisa sempre conectado"),
    (r"rtkaud|realtek|nahimic|waves|maxxaudio|dolby", "manter", "Driver de áudio"),
    (r"synaptics|elan|precision touch|touchpad", "manter", "Driver do touchpad"),
    (r"igfx|intel.*graphics|amd.*(radeon|software|noise)|radeonsoftware|nvidia|nvbackend|nvcontainer", "opcional", "Painel/driver de vídeo"),
    (r"onedrive", "desativar", "Sincroniza em segundo plano; abra quando precisar"),
    (r"steam|epicgames|epic games|eadesktop|origin|ubisoft|uplay|battle\.net|riotclient|gog galaxy|rockstar", "desativar", "Launcher de jogos: abra só quando for jogar"),
    (r"discord|spotify|teams|skype|slack|zoom|whatsapp|telegram", "desativar", "Comunicação/mídia: pode abrir manualmente"),
    (r"adobe|acrobat|creative cloud|ccxprocess", "desativar", "Atualizadores da Adobe"),
    (r"update|updater|helper|launcher", "desativar", "Atualizador automático"),
    (r"edge.*autolaunch|msedge", "desativar", "Pré-carregamento do Edge"),
    (r"logi|razer|corsair|icue|steelseries|hyperx|armoury|aura|msi center|dragon center", "opcional", "Software de periféricos (RGB/macros)"),
    (r"antivirus|avast|avg|kaspersky|bitdefender|norton|mcafee|eset", "manter", "Antivírus"),
]


@dataclass
class StartupItem:
    name: str
    command: str
    location: str  # descrição legível
    hive: int
    approved_key: str  # subchave StartupApproved (Run / Run32 / StartupFolder)
    enabled: bool
    file_path: str | None = None

    @property
    def needs_admin(self) -> bool:
        return self.hive == HKLM

    @property
    def hint(self) -> tuple[str, str]:
        text = f"{self.name} {self.command}".lower()
        for pat, rec, why in HINTS:
            if re.search(pat, text):
                return rec, why
        return "avaliar", "Desconhecido: desative se não reconhece ou não precisa"

    @property
    def executable(self) -> str:
        c = self.command.strip()
        if c.startswith('"'):
            return c[1:].split('"', 1)[0]
        m = re.match(r"(.+?\.exe)", c, re.I)
        return m.group(1) if m else c.split(" ")[0]


def _approved_state(hive, sub: str, name: str) -> bool:
    try:
        with winreg.OpenKey(hive, f"{APPROVED}\\{sub}") as k:
            data, _ = winreg.QueryValueEx(k, name)
            return len(data) == 0 or (data[0] & 1) == 0
    except OSError:
        return True


def _enum_values(hive, path):
    out = []
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(k, i)
                    out.append((name, str(val)))
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    return out


def list_items() -> list[StartupItem]:
    items: list[StartupItem] = []
    for name, cmd in _enum_values(HKCU, RUN):
        items.append(StartupItem(name, cmd, "Registro (usuário)", HKCU, "Run", _approved_state(HKCU, "Run", name)))
    for name, cmd in _enum_values(HKLM, RUN):
        items.append(StartupItem(name, cmd, "Registro (todos os usuários)", HKLM, "Run", _approved_state(HKLM, "Run", name)))
    for name, cmd in _enum_values(HKLM, RUN32):
        items.append(StartupItem(name, cmd, "Registro 32-bit (todos)", HKLM, "Run32", _approved_state(HKLM, "Run32", name)))
    folders = [
        (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"), HKCU, "Pasta Inicializar (usuário)"),
        (os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp"), HKLM, "Pasta Inicializar (todos)"),
    ]
    for folder, hive, label in folders:
        try:
            for fn in os.listdir(folder):
                if fn.lower() == "desktop.ini":
                    continue
                full = os.path.join(folder, fn)
                items.append(StartupItem(os.path.splitext(fn)[0], full, label, hive, "StartupFolder",
                                         _approved_state(hive, "StartupFolder", fn), file_path=fn))
        except OSError:
            pass
    items.sort(key=lambda i: (not i.enabled, i.name.lower()))
    return items


def set_enabled(item: StartupItem, enabled: bool) -> None:
    if item.needs_admin and not is_admin():
        raise PermissionError("Requer administrador")
    value_name = item.file_path if item.approved_key == "StartupFolder" else item.name
    if enabled:
        data = bytes([0x02]) + bytes(11)
    else:
        # 0x03 + 3 bytes + FILETIME do momento (formato do Gerenciador de Tarefas)
        ft = int((time.time() + 11644473600) * 10_000_000)
        data = bytes([0x03, 0, 0, 0]) + struct.pack("<Q", ft)
    with winreg.CreateKeyEx(item.hive, f"{APPROVED}\\{item.approved_key}", 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, value_name, 0, winreg.REG_BINARY, data)
    item.enabled = enabled


def count_enabled() -> int:
    return sum(1 for i in list_items() if i.enabled)
