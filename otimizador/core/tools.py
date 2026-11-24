"""Ferramentas de manutenção do Windows (SFC, DISM, TRIM, rede, ponto de restauração...)."""
from __future__ import annotations

import codecs
import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from .utils import CREATE_NO_WINDOW, data_dir, oem_encoding


@dataclass
class Tool:
    id: str
    name: str
    description: str
    command: list[str] | None = None  # executado capturando a saída
    launch: str | None = None  # apenas abre (programa/URI)
    admin: bool = True
    long: bool = False
    confirm: str | None = None  # mensagem de confirmação


PS = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

RESTORE_POINT_PS = (
    "$ErrorActionPreference='Stop';"
    "try { Enable-ComputerRestore -Drive \"$env:SystemDrive\\\" } catch {};"
    "New-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\SystemRestore' "
    "-Name SystemRestorePointCreationFrequency -Value 0 -PropertyType DWord -Force | Out-Null;"
    "Checkpoint-Computer -Description 'Otimizador - antes das otimizacoes' -RestorePointType MODIFY_SETTINGS;"
    "Write-Output 'Ponto de restauração criado com sucesso.'"
)

TOOLS: list[Tool] = [
    Tool("restore_point", "Criar ponto de restauração",
         "Salva o estado atual do Windows para poder voltar caso algo dê errado. Ativa a Proteção do Sistema no C: se estiver desligada.",
         PS + [RESTORE_POINT_PS]),
    Tool("sfc", "Verificar arquivos do sistema (SFC)",
         "Procura e repara arquivos corrompidos do Windows. Leva de 5 a 20 minutos.",
         ["sfc", "/scannow"], long=True),
    Tool("dism_restore", "Reparar imagem do Windows (DISM)",
         "Repara o repositório de componentes usado pelo SFC, baixando arquivos do Windows Update se preciso. Rode antes do SFC se ele falhar.",
         ["DISM", "/Online", "/Cleanup-Image", "/RestoreHealth"], long=True),
    Tool("dism_cleanup", "Limpar componentes antigos (WinSxS)",
         "Remove versões antigas de componentes substituídas por atualizações. Costuma liberar 1–5 GB.",
         ["DISM", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], long=True),
    Tool("optimize_drives", "Otimizar unidades (TRIM / desfragmentar)",
         "Executa TRIM nos SSDs e desfragmentação nos HDDs — o Windows escolhe o certo para cada disco.",
         ["defrag", "/C", "/O", "/U", "/V"], long=True),
    Tool("chkdsk", "Verificar erros no disco C:",
         "Verificação online do sistema de arquivos (não precisa reiniciar).",
         ["chkdsk", os.environ.get("SystemDrive", "C:"), "/scan"], long=True),
    Tool("flush_dns", "Limpar cache DNS",
         "Resolve sites que não abrem ou abrem a versão errada após mudanças de DNS.",
         ["ipconfig", "/flushdns"], admin=False),
    Tool("net_reset", "Redefinir pilha de rede (Winsock/TCP-IP)",
         "Corrige problemas de conexão causados por configurações corrompidas. Requer reiniciar o PC depois.",
         ["cmd", "/c", "netsh winsock reset && netsh int ip reset"],
         confirm="Isso redefine as configurações de rede (IPs fixos e VPNs podem precisar ser reconfigurados) e exige reiniciar. Continuar?"),
    Tool("battery_report", "Relatório de bateria",
         "Gera um relatório com a capacidade original vs. atual da bateria do notebook.",
         ["powercfg", "/batteryreport", "/output", str(data_dir() / "relatorio-bateria.html")], admin=False),
    Tool("energy_report", "Diagnóstico de energia (60 s)",
         "Analisa por 60 segundos o que impede o PC de economizar energia (drivers, USB, processos).",
         ["powercfg", "/energy", "/output", str(data_dir() / "relatorio-energia.html"), "/duration", "60"], long=True),
    Tool("cleanmgr", "Limpeza de Disco do Windows", "Abre a ferramenta nativa (pode remover Windows.old e arquivos de atualização).",
         launch="cleanmgr.exe", admin=False),
    Tool("mdsched", "Diagnóstico de memória RAM", "Testa a memória RAM no próximo reinício (útil para telas azuis).",
         launch="mdsched.exe", admin=False),
    Tool("rstrui", "Restauração do Sistema", "Abre a Restauração do Sistema para voltar a um ponto anterior.",
         launch="rstrui.exe", admin=False),
    Tool("winupdate", "Windows Update", "Abre o Windows Update para instalar atualizações e drivers opcionais.",
         launch="ms-settings:windowsupdate", admin=False),
    Tool("devmgmt", "Gerenciador de Dispositivos", "Verifique dispositivos com ponto de exclamação (sem driver).",
         launch="devmgmt.msc", admin=False),
    Tool("gaming_settings", "Configurações de jogos do Windows", "Modo de Jogo, Game Bar e capturas.",
         launch="ms-settings:gaming-gamemode", admin=False),
    Tool("graphics_settings", "Preferência de GPU por aplicativo",
         "Force jogos a usarem a placa de vídeo dedicada (útil em notebooks com duas GPUs).",
         launch="ms-settings:display-advancedgraphics", admin=False),
]

TOOLS_BY_ID = {t.id: t for t in TOOLS}


def run_streaming(tool: Tool, on_line: Callable[[str], None], should_stop: Callable[[], bool] = lambda: False) -> int:
    if tool.launch:
        os.startfile(tool.launch)  # noqa: S606
        on_line(f"Aberto: {tool.name}")
        return 0
    proc = subprocess.Popen(tool.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=CREATE_NO_WINDOW, bufsize=0)
    buf = ""
    decoder = None
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        if decoder is None:
            # sfc escreve UTF-16; os demais usam a página de código OEM
            enc = "utf-16-le" if chunk.count(b"\x00") > len(chunk) // 4 else oem_encoding()
            decoder = codecs.getincrementaldecoder(enc)(errors="replace")
        buf += decoder.decode(chunk).replace("\x00", "")
        # Linhas terminam em \n ou \r (progresso do sfc/dism usa \r)
        idx = max(buf.rfind("\n"), buf.rfind("\r"))
        if idx >= 0:
            text, buf = buf[: idx + 1], buf[idx + 1:]
            for line in text.replace("\r", "\n").split("\n"):
                if line.strip():
                    on_line(line.rstrip())
        if should_stop():
            proc.terminate()
            on_line("Interrompido pelo usuário.")
            break
    if buf.strip():
        on_line(buf.strip())
    code = proc.wait()
    if tool.id in ("battery_report", "energy_report") and code in (0, 1):
        path = tool.command[tool.command.index("/output") + 1]
        if os.path.exists(path):
            os.startfile(path)  # noqa: S606
    return code


def create_restore_point(on_line: Callable[[str], None]) -> bool:
    return run_streaming(TOOLS_BY_ID["restore_point"], on_line) == 0
