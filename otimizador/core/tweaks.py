"""Catálogo de otimizações reversíveis.

Cada otimização é composta por ações (registro, serviço ou comando). Antes de
aplicar, o valor original é salvo em backup.json para que tudo possa ser
desfeito exatamente como estava.
"""
from __future__ import annotations

import json
import re
import winreg
from dataclasses import dataclass, field
from typing import Callable

from .utils import data_dir, is_admin, run_cmd

HKCU = winreg.HKEY_CURRENT_USER
HKLM = winreg.HKEY_LOCAL_MACHINE
_HIVE_NAMES = {HKCU: "HKCU", HKLM: "HKLM"}
_HIVES = {"HKCU": HKCU, "HKLM": HKLM}

ABSENT = "__ausente__"

# --------------------------------------------------------------------------- backup


class Backup:
    def __init__(self, path=None):
        self.path = path or (data_dir() / "backup.json")
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, tweak_id: str) -> dict | None:
        return self.data.get(tweak_id)

    def put(self, tweak_id: str, entry: dict):
        # Só grava o original na primeira aplicação (não sobrescreve o estado "de fábrica")
        if tweak_id not in self.data:
            self.data[tweak_id] = entry
            self.save()

    def remove(self, tweak_id: str):
        if self.data.pop(tweak_id, None) is not None:
            self.save()


# --------------------------------------------------------------------------- registro


def reg_read(hive, path: str, name: str):
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            val, typ = winreg.QueryValueEx(k, name)
            if isinstance(val, bytes):
                val = val.hex()
            return val, typ
    except OSError:
        return ABSENT, None


def reg_write(hive, path: str, name: str, typ: int, value):
    with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
        if typ == winreg.REG_BINARY and isinstance(value, str):
            value = bytes.fromhex(value)
        winreg.SetValueEx(k, name, 0, typ, value)


def reg_delete(hive, path: str, name: str):
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------- ações


@dataclass
class Reg:
    hive: int
    path: str
    name: str
    value: object
    typ: int = winreg.REG_DWORD

    @property
    def key(self):
        return f"{_HIVE_NAMES[self.hive]}\\{self.path}\\{self.name}"

    @property
    def needs_admin(self):
        return self.hive == HKLM

    def current(self):
        return reg_read(self.hive, self.path, self.name)[0]

    def is_applied(self) -> bool:
        cur = self.current()
        want = self.value.hex() if isinstance(self.value, bytes) else self.value
        if isinstance(want, str) and isinstance(cur, str):
            return cur.lower() == want.lower()
        return cur == want

    def snapshot(self):
        val, typ = reg_read(self.hive, self.path, self.name)
        return {"kind": "reg", "hive": _HIVE_NAMES[self.hive], "path": self.path, "name": self.name, "value": val, "typ": typ}

    def apply(self):
        reg_write(self.hive, self.path, self.name, self.typ, self.value)


def restore_reg(snap: dict):
    hive = _HIVES[snap["hive"]]
    if snap["value"] == ABSENT:
        reg_delete(hive, snap["path"], snap["name"])
    else:
        reg_write(hive, snap["path"], snap["name"], snap["typ"], snap["value"])


def Service(name: str, start: int) -> Reg:
    """Tipo de inicialização de serviço: 2=automático, 3=manual, 4=desativado."""
    return Reg(HKLM, rf"SYSTEM\CurrentControlSet\Services\{name}", "Start", start)


@dataclass
class Cmd:
    """Ação por comando. `check` diz se já está aplicada; `snapshot` guarda o estado anterior."""
    apply_fn: Callable[[], None]
    revert_fn: Callable[[dict], None]
    check_fn: Callable[[], bool]
    snapshot_fn: Callable[[], dict] = lambda: {}
    needs_admin: bool = True
    key: str = "cmd"

    def is_applied(self):
        try:
            return self.check_fn()
        except Exception:
            return False

    def snapshot(self):
        s = {"kind": "cmd", "key": self.key}
        s.update(self.snapshot_fn())
        return s

    def apply(self):
        self.apply_fn()


# --------------------------------------------------------------------------- plano de energia

HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
ULTIMATE_BASE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
_GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def _active_scheme() -> str | None:
    _, out = run_cmd(["powercfg", "/getactivescheme"])
    m = re.search(_GUID, out, re.I)
    return m.group(0).lower() if m else None


def _list_schemes() -> list[tuple[str, str]]:
    _, out = run_cmd(["powercfg", "/list"])
    return [(m.group(1).lower(), m.group(2)) for m in re.finditer(rf"({_GUID})\s*\(([^)]*)\)", out, re.I)]


def _meta_path():
    return data_dir() / "meta.json"


def _meta() -> dict:
    try:
        return json.loads(_meta_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ultimate_guid(create: bool) -> str | None:
    state = _meta()
    guids = [g for g, _ in _list_schemes()]
    saved = state.get("ultimate_guid")
    if saved and saved in guids:
        return saved
    if ULTIMATE_BASE in guids:
        return ULTIMATE_BASE
    for g, name in _list_schemes():
        if "máximo" in name.lower() or "ultimate" in name.lower() or "maximo" in name.lower():
            return g
    if not create:
        return None
    _, out = run_cmd(["powercfg", "-duplicatescheme", ULTIMATE_BASE])
    m = re.search(_GUID, out, re.I)
    if not m:
        raise RuntimeError("Este Windows não oferece o plano Desempenho Máximo.\n" + out)
    state["ultimate_guid"] = m.group(0).lower()
    _meta_path().write_text(json.dumps(state), encoding="utf-8")
    return state["ultimate_guid"]


def _set_scheme(guid: str):
    code, out = run_cmd(["powercfg", "/setactive", guid])
    if code != 0:
        raise RuntimeError(out.strip() or "Falha ao ativar o plano de energia")


def _plan_cmd(target: str) -> Cmd:
    def target_guid(create):
        return _ultimate_guid(create) if target == "ultimate" else HIGH_PERF

    def apply():
        g = target_guid(True)
        if target == "high" and HIGH_PERF not in [x for x, _ in _list_schemes()]:
            # Em alguns notebooks o plano fica oculto: recria a partir do modelo
            run_cmd(["powercfg", "-duplicatescheme", HIGH_PERF, HIGH_PERF])
        _set_scheme(g)

    def revert(snap):
        _set_scheme(snap.get("previous") or BALANCED)

    def check():
        return _active_scheme() == target_guid(False)

    return Cmd(apply, revert, check, lambda: {"previous": _active_scheme()}, needs_admin=False, key=f"power:{target}")


def _powercfg_hibernate() -> Cmd:
    def check():
        from .sysinfo import hibernation_enabled
        return not hibernation_enabled()

    def apply():
        code, out = run_cmd(["powercfg", "/hibernate", "off"])
        if code != 0:
            raise RuntimeError(out)

    def revert(snap):
        if snap.get("was_enabled"):
            run_cmd(["powercfg", "/hibernate", "on"])

    return Cmd(apply, revert, check, lambda: {"was_enabled": not check()}, key="hibernate")


def _trim_cmd() -> Cmd:
    def check():
        _, out = run_cmd(["fsutil", "behavior", "query", "DisableDeleteNotify"])
        m = re.search(r"NTFS\s+DisableDeleteNotify\s*=\s*(\d)", out)
        return bool(m and m.group(1) == "0")

    def apply():
        run_cmd(["fsutil", "behavior", "set", "DisableDeleteNotify", "0"])

    def revert(snap):
        if snap.get("was_disabled"):
            run_cmd(["fsutil", "behavior", "set", "DisableDeleteNotify", "1"])

    return Cmd(apply, revert, check, lambda: {"was_disabled": not check()}, key="trim")


# --------------------------------------------------------------------------- catálogo

CATEGORIES = ["Desempenho", "Jogos", "Privacidade e segundo plano", "Rede", "Visual", "Avançado (com riscos)"]

PROFILES = {
    "seguro": "Recomendado (seguro)",
    "gamer": "Gamer / Desempenho",
    "notebook": "Notebook / Bateria",
    "maximo": "Máximo",
}


@dataclass
class Tweak:
    id: str
    name: str
    category: str
    description: str
    actions: list
    risk: str = "baixo"  # baixo | médio | alto
    profiles: set = field(default_factory=set)
    restart: str = ""  # "", "logoff", "reiniciar"
    impact: str = ""  # frase curta sobre o ganho real

    @property
    def needs_admin(self) -> bool:
        return any(a.needs_admin for a in self.actions)

    def is_applied(self) -> bool:
        try:
            return all(a.is_applied() for a in self.actions)
        except Exception:
            return False


def _content_delivery(names: list[str]) -> list[Reg]:
    p = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
    return [Reg(HKCU, p, n, 0) for n in names]


SEG = "seguro"
GAM = "gamer"
NOT = "notebook"
MAX = "maximo"

TWEAKS: list[Tweak] = [
    # ---------------- Desempenho
    Tweak("power_high", "Plano de energia: Alto desempenho", "Desempenho",
          "Mantém o processador em frequências altas e reduz a latência para acordar núcleos. "
          "Em desktop o custo de energia é pequeno; em notebook gasta mais bateria.",
          [_plan_cmd("high")], "baixo", {GAM}, impact="Mais FPS mínimo e resposta mais rápida, principalmente em notebooks na tomada"),
    Tweak("power_ultimate", "Plano de energia: Desempenho Máximo (Ultimate)", "Desempenho",
          "Plano oculto do Windows que desativa todas as economias de energia (estados ociosos agressivos, desligamento de disco/USB). "
          "Indicado apenas para desktops.",
          [_plan_cmd("ultimate")], "médio", {MAX}, impact="Elimina micro-atrasos de economia de energia; maior consumo"),
    Tweak("background_apps", "Bloquear apps da Store em segundo plano", "Desempenho",
          "Impede que aplicativos da Microsoft Store fiquem rodando escondidos consumindo RAM, CPU e rede.",
          [Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled", 1),
           Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Search", "BackgroundAppGlobalToggle", 0)],
          "baixo", {SEG, GAM, NOT, MAX}, impact="Menos processos e menos consumo de bateria"),
    Tweak("startup_delay", "Remover atraso de inicialização dos programas", "Desempenho",
          "O Windows espera alguns segundos antes de abrir os programas de inicialização. Isso remove a espera.",
          [Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "StartupDelayInMSec", 0)],
          "baixo", {SEG, GAM, MAX}, impact="Área de trabalho utilizável mais cedo após o login"),
    Tweak("menu_delay", "Menus mais rápidos", "Desempenho",
          "Reduz o atraso dos menus do Windows de 400 ms para 50 ms.",
          [Reg(HKCU, r"Control Panel\Desktop", "MenuShowDelay", "50", winreg.REG_SZ)],
          "baixo", {SEG, GAM, NOT, MAX}, restart="logoff", impact="Interface mais ágil"),
    Tweak("hibernation_off", "Desativar hibernação (libera espaço)", "Desempenho",
          "Apaga o arquivo hiberfil.sys (normalmente 40% da RAM, vários GB) e desativa a hibernação. "
          "Também desativa a Inicialização Rápida. Não recomendado em notebooks.",
          [_powercfg_hibernate()], "baixo", {MAX}, impact="Libera vários GB no disco do sistema"),
    Tweak("trim_on", "Garantir TRIM ativo nos SSDs", "Desempenho",
          "O TRIM mantém a velocidade de escrita do SSD ao longo do tempo. Normalmente já vem ativo.",
          [_trim_cmd()], "baixo", {SEG, GAM, NOT, MAX}, impact="Mantém o SSD rápido e saudável"),
    Tweak("search_index_off", "Desativar indexação da Pesquisa (Windows Search)", "Desempenho",
          "A indexação lê o disco constantemente. Em HDD ou PCs fracos isso pesa bastante; a busca do menu Iniciar fica mais lenta para arquivos.",
          [Service("WSearch", 4)], "médio", set(), restart="reiniciar", impact="Menos uso de disco em HDDs"),
    Tweak("sysmain_off", "Desativar SysMain (Superfetch)", "Desempenho",
          "Só ajuda em PCs com HDD e pouca RAM que sofrem com disco a 100%. Em SSD com RAM suficiente o SysMain é benéfico — mantenha ligado.",
          [Service("SysMain", 4)], "médio", set(), restart="reiniciar", impact="Pode resolver 'disco 100%' em HDDs lentos"),

    # ---------------- Jogos
    Tweak("game_mode", "Ativar Modo de Jogo", "Jogos",
          "Prioriza o jogo em execução e evita que o Windows Update instale drivers ou reinicie durante a partida.",
          [Reg(HKCU, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1)],
          "baixo", {SEG, GAM, NOT, MAX}, impact="FPS mais estável (0–2% médio, menos quedas)"),
    Tweak("game_dvr_off", "Desativar gravação em segundo plano (Game DVR)", "Jogos",
          "A captura contínua da Xbox Game Bar grava os últimos minutos do jogo o tempo todo, gastando GPU e disco.",
          [Reg(HKCU, r"System\GameConfigStore", "GameDVR_Enabled", 0),
           Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0),
           Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "HistoricalCaptureEnabled", 0)],
          "baixo", {SEG, GAM, NOT, MAX}, impact="Ganho mensurável de FPS e menos stutter"),
    Tweak("hags_on", "Agendamento de GPU acelerado por hardware (HAGS)", "Jogos",
          "Deixa a própria GPU gerenciar sua memória de vídeo, reduzindo latência. Necessário para DLSS Frame Generation. "
          "O ganho varia por jogo — teste. Requer GPU moderna (GTX 1000+/RX 5000+) e reinício.",
          [Reg(HKLM, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2)],
          "baixo", {GAM, MAX}, restart="reiniciar", impact="Menor latência; obrigatório para Frame Generation"),
    Tweak("windowed_opt", "Otimizações para jogos em janela", "Jogos",
          "Faz jogos DirectX 10/11 em janela/sem bordas usarem o modelo de apresentação moderno (flip), reduzindo latência e liberando VRR.",
          [Reg(HKCU, r"Software\Microsoft\DirectX\UserGpuPreferences", "DirectXUserGlobalSettings",
               "SwapEffectUpgradeEnable=1;", winreg.REG_SZ)],
          "baixo", {GAM, MAX}, impact="Menos input lag em modo janela sem bordas"),
    Tweak("game_priority", "Prioridade de CPU/GPU para jogos (MMCSS)", "Jogos",
          "Ajusta o agendador multimídia para dar prioridade alta a jogos e reservar menos CPU para tarefas de fundo.",
          [Reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "GPU Priority", 8),
           Reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Priority", 6),
           Reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Scheduling Category", "High", winreg.REG_SZ),
           Reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "SFIO Priority", "High", winreg.REG_SZ),
           Reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 10)],
          "baixo", {GAM, MAX}, impact="Efeito pequeno; ajuda em PCs com muita coisa aberta"),
    Tweak("mouse_accel_off", "Desativar aceleração do mouse", "Jogos",
          "Remove o 'Aprimorar precisão do ponteiro' para que o movimento do mouse seja 1:1 — essencial para mira consistente.",
          [Reg(HKCU, r"Control Panel\Mouse", "MouseSpeed", "0", winreg.REG_SZ),
           Reg(HKCU, r"Control Panel\Mouse", "MouseThreshold1", "0", winreg.REG_SZ),
           Reg(HKCU, r"Control Panel\Mouse", "MouseThreshold2", "0", winreg.REG_SZ)],
          "baixo", {GAM, MAX}, restart="logoff", impact="Mira consistente (memória muscular)"),

    # ---------------- Privacidade e segundo plano
    Tweak("telemetry_off", "Reduzir telemetria do Windows", "Privacidade e segundo plano",
          "Define a coleta de dados de diagnóstico no mínimo e desativa o serviço DiagTrack (Experiências do Usuário Conectado e Telemetria).",
          [Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 0),
           Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "DoNotShowFeedbackNotifications", 1),
           Service("DiagTrack", 4), Service("dmwappushservice", 4)],
          "baixo", {SEG, GAM, NOT, MAX}, restart="reiniciar", impact="Menos processos, uso de disco e rede em segundo plano"),
    Tweak("ads_off", "Remover anúncios e sugestões do Windows", "Privacidade e segundo plano",
          "Desativa ID de publicidade, apps instalados automaticamente, dicas, sugestões no Iniciar e anúncios no Explorador.",
          [Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0),
           Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Privacy", "TailoredExperiencesWithDiagnosticDataEnabled", 0),
           Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ShowSyncProviderNotifications", 0),
           Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "Start_IrisRecommendations", 0),
           *_content_delivery(["SilentInstalledAppsEnabled", "SystemPaneSuggestionsEnabled", "SoftLandingEnabled",
                               "SubscribedContent-338388Enabled", "SubscribedContent-338389Enabled",
                               "SubscribedContent-353694Enabled", "SubscribedContent-353696Enabled",
                               "SubscribedContent-310093Enabled", "PreInstalledAppsEnabled", "OemPreInstalledAppsEnabled"])],
          "baixo", {SEG, GAM, NOT, MAX}, impact="Menos instalações automáticas e processos de fundo"),
    Tweak("bing_off", "Remover pesquisa Bing do menu Iniciar", "Privacidade e segundo plano",
          "A busca do Iniciar deixa de enviar o que você digita para a internet, ficando mais rápida e só local.",
          [Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Search", "BingSearchEnabled", 0),
           Reg(HKCU, r"Software\Policies\Microsoft\Windows\Explorer", "DisableSearchBoxSuggestions", 1)],
          "baixo", {SEG, GAM, NOT, MAX}, restart="logoff", impact="Pesquisa do Iniciar mais rápida"),
    Tweak("activity_off", "Desativar histórico de atividades", "Privacidade e segundo plano",
          "Impede que o Windows registre e envie os aplicativos e arquivos que você usa.",
          [Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\System", "EnableActivityFeed", 0),
           Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\System", "PublishUserActivities", 0),
           Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\System", "UploadUserActivities", 0)],
          "baixo", {SEG, GAM, NOT, MAX}),
    Tweak("widgets_off", "Desativar Widgets (Notícias e interesses)", "Privacidade e segundo plano",
          "O painel de Widgets mantém processos do Edge WebView rodando o tempo todo (100–300 MB de RAM).",
          [Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Dsh", "AllowNewsAndInterests", 0)],
          "baixo", {GAM, NOT, MAX}, restart="logoff", impact="Libera RAM e CPU de fundo"),
    Tweak("copilot_recall_off", "Desativar Copilot e Recall (IA do Windows)", "Privacidade e segundo plano",
          "Desativa o Copilot integrado e o Recall, que tira capturas de tela periódicas para indexar sua atividade.",
          [Reg(HKCU, r"Software\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1),
           Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1),
           Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", 1)],
          "baixo", {GAM, MAX}, restart="reiniciar"),
    Tweak("storage_sense", "Ativar Sensor de Armazenamento", "Privacidade e segundo plano",
          "O próprio Windows passa a limpar arquivos temporários e a lixeira antiga automaticamente.",
          [Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy", "01", 1)],
          "baixo", {SEG, NOT, MAX}, impact="Mantém o disco limpo sozinho"),

    # ---------------- Rede
    Tweak("delivery_opt_off", "Desativar compartilhamento P2P de atualizações", "Rede",
          "Por padrão o Windows usa sua internet para enviar atualizações a outros PCs. Isso desliga o envio (baixa só da Microsoft).",
          [Reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", 0)],
          "baixo", {SEG, GAM, NOT, MAX}, impact="Libera upload e reduz ping durante atualizações"),
    Tweak("net_throttle_off", "Desativar limitação de rede multimídia", "Rede",
          "O Windows limita o processamento de pacotes de rede enquanto toca mídia. Remover pode reduzir picos de ping em jogos.",
          [Reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "NetworkThrottlingIndex", 0xFFFFFFFF)],
          "baixo", {GAM, MAX}, restart="reiniciar", impact="Efeito pequeno; ajuda com música/stream + jogo"),

    # ---------------- Visual
    Tweak("visual_perf", "Efeitos visuais para melhor desempenho", "Visual",
          "Desliga animações, sombras e fades do Windows, mantendo fontes suavizadas e miniaturas. Grande diferença em PCs fracos.",
          [Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 3),
           Reg(HKCU, r"Control Panel\Desktop", "UserPreferencesMask", "9012038010000000", winreg.REG_BINARY),
           Reg(HKCU, r"Control Panel\Desktop\WindowMetrics", "MinAnimate", "0", winreg.REG_SZ),
           Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarAnimations", 0),
           Reg(HKCU, r"Software\Microsoft\Windows\DWM", "EnableAeroPeek", 0)],
          "baixo", {MAX}, restart="logoff", impact="Janelas abrem instantaneamente; menos uso da GPU integrada"),
    Tweak("transparency_off", "Desativar transparência", "Visual",
          "Remove o efeito de vidro/acrílico da barra de tarefas e menus.",
          [Reg(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 0)],
          "baixo", {NOT, MAX}, impact="Menos uso da GPU; economiza bateria"),

    # ---------------- Avançado (riscos)
    Tweak("vbs_off", "Desativar Integridade de Memória / VBS", "Avançado (com riscos)",
          "A Segurança Baseada em Virtualização pode custar 5–15% de FPS em alguns jogos. PORÉM ela protege contra rootkits e "
          "malware de kernel. Só desative se o PC é usado principalmente para jogos e você entende o risco.",
          [Reg(HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity", "Enabled", 0),
           Reg(HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceGuard", "EnableVirtualizationBasedSecurity", 0)],
          "alto", set(), restart="reiniciar", impact="Até 5–15% de FPS em alguns jogos, com perda de segurança"),
]

TWEAKS_BY_ID = {t.id: t for t in TWEAKS}


def tweaks_for_profile(profile: str) -> list[Tweak]:
    return [t for t in TWEAKS if profile in t.profiles]


# --------------------------------------------------------------------------- aplicar / reverter


def apply_tweak(t: Tweak, backup: Backup | None = None) -> None:
    backup = backup or Backup()
    if t.needs_admin and not is_admin():
        raise PermissionError("Requer administrador")
    if t.id not in backup.data:
        backup.put(t.id, {"actions": [a.snapshot() for a in t.actions]})
    for a in t.actions:
        a.apply()


def revert_tweak(t: Tweak, backup: Backup | None = None) -> bool:
    """Desfaz usando o backup. Retorna False se não havia backup."""
    backup = backup or Backup()
    if t.needs_admin and not is_admin():
        raise PermissionError("Requer administrador")
    entry = backup.get(t.id)
    if not entry:
        return False
    for action, snap in zip(t.actions, entry["actions"]):
        if snap.get("kind") == "reg":
            restore_reg(snap)
        else:
            action.revert_fn(snap)
    backup.remove(t.id)
    return True


def applied_with_backup() -> list[Tweak]:
    b = Backup()
    return [TWEAKS_BY_ID[k] for k in b.data if k in TWEAKS_BY_ID]
