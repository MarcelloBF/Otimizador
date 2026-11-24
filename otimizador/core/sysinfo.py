"""Coleta completa das especificações do PC (hardware + estado do Windows)."""
from __future__ import annotations

import datetime as dt
import platform
import re
import time
import winreg

import psutil

from .utils import is_admin, run_cmd, run_ps_json

_PS_SCRIPT = r"""
$o = [ordered]@{}
$os = Get-CimInstance Win32_OperatingSystem
$o.os = [ordered]@{
  caption = $os.Caption; version = $os.Version; build = $os.BuildNumber; arch = $os.OSArchitecture
  install = $os.InstallDate.ToString('s'); boot = $os.LastBootUpTime.ToString('s')
  display = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion
  ubr = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').UBR
}
$o.cpu = @(Get-CimInstance Win32_Processor | ForEach-Object { [ordered]@{
  name = $_.Name.Trim(); manufacturer = $_.Manufacturer; cores = $_.NumberOfCores; threads = $_.NumberOfLogicalProcessors
  max_mhz = $_.MaxClockSpeed; l2_kb = $_.L2CacheSize; l3_kb = $_.L3CacheSize; socket = $_.SocketDesignation
  virtualization = $_.VirtualizationFirmwareEnabled } })
$vramReg = @{}
Get-ChildItem 'HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}' | ForEach-Object {
  $p = Get-ItemProperty $_.PSPath
  if ($p.DriverDesc -and $p.'HardwareInformation.qwMemorySize') { $vramReg[$p.DriverDesc] = [int64]$p.'HardwareInformation.qwMemorySize' }
}
$o.gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object {
  $v = $vramReg[$_.Name]; if (-not $v) { $v = [int64]$_.AdapterRAM }
  [ordered]@{ name = $_.Name; vram = $v; driver = $_.DriverVersion
    driver_date = if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { $null }
    res_w = $_.CurrentHorizontalResolution; res_h = $_.CurrentVerticalResolution; hz = $_.CurrentRefreshRate
    pnp = $_.PNPDeviceID; status = $_.Status } })
$o.mem = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { [ordered]@{
  capacity = [int64]$_.Capacity; speed = $_.Speed; configured = $_.ConfiguredClockSpeed; manufacturer = "$($_.Manufacturer)".Trim()
  part = "$($_.PartNumber)".Trim(); slot = $_.DeviceLocator; bank = $_.BankLabel; type = $_.SMBIOSMemoryType; form = $_.FormFactor } })
$arr = Get-CimInstance Win32_PhysicalMemoryArray
$o.mem_slots = ($arr | Measure-Object MemoryDevices -Sum).Sum
$o.mem_max = ($arr | Measure-Object MaxCapacityEx -Sum).Sum
$sysDiskNum = (Get-Partition -DriveLetter $env:SystemDrive[0] | Select-Object -First 1).DiskNumber
$o.disks = @(Get-PhysicalDisk | ForEach-Object {
  $rc = $null; try { $rc = $_ | Get-StorageReliabilityCounter } catch {}
  [ordered]@{ name = "$($_.FriendlyName)".Trim(); media = "$($_.MediaType)"; bus = "$($_.BusType)"; size = [int64]$_.Size
    health = "$($_.HealthStatus)"; number = [int]$_.DeviceId; system = ([int]$_.DeviceId -eq $sysDiskNum)
    temp = if ($rc) { $rc.Temperature } else { $null }; wear = if ($rc) { $rc.Wear } else { $null }
    hours = if ($rc) { $rc.PowerOnHours } else { $null } } })
$o.volumes = @(Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' } | ForEach-Object {
  [ordered]@{ letter = "$($_.DriveLetter)"; label = $_.FileSystemLabel; fs = $_.FileSystem; size = [int64]$_.Size; free = [int64]$_.SizeRemaining; health = "$($_.HealthStatus)" } })
$b = Get-CimInstance Win32_BaseBoard; $bios = Get-CimInstance Win32_BIOS; $cs = Get-CimInstance Win32_ComputerSystem
$o.board = [ordered]@{ manufacturer = $b.Manufacturer; product = $b.Product }
$o.bios = [ordered]@{ vendor = $bios.Manufacturer; version = $bios.SMBIOSBIOSVersion; date = if ($bios.ReleaseDate) { $bios.ReleaseDate.ToString('yyyy-MM-dd') } else { $null } }
$o.system = [ordered]@{ manufacturer = $cs.Manufacturer; model = $cs.Model; type = $cs.PCSystemType; ram = [int64]$cs.TotalPhysicalMemory; name = $cs.Name }
$o.battery = @(Get-CimInstance Win32_Battery | ForEach-Object { [ordered]@{ name = $_.Name; charge = $_.EstimatedChargeRemaining; status = $_.BatteryStatus } })
$dg = Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard
$o.vbs = [ordered]@{ status = $dg.VirtualizationBasedSecurityStatus; running = @($dg.SecurityServicesRunning) }
$o.net = @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object {
  [ordered]@{ name = $_.Name; desc = $_.InterfaceDescription; speed = $_.LinkSpeed; media = "$($_.PhysicalMediaType)"; mac = $_.MacAddress } })
$o.monitors = @(Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID | ForEach-Object {
  [ordered]@{ name = (($_.UserFriendlyName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ }) -join '') } })
$o.secure_boot = try { Confirm-SecureBootUEFI } catch { $null }
$o.tpm = try { (Get-Tpm).TpmPresent } catch { $null }
$o | ConvertTo-Json -Depth 5 -Compress
"""

_MEMORY_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 30: "LPDDR4", 35: "LPDDR5"}
_CHASSIS = {1: "Desktop", 2: "Notebook", 3: "Workstation", 4: "Servidor", 5: "Servidor", 8: "Notebook/tablet"}


def _reg_get(hive, path, name, default=None):
    try:
        with winreg.OpenKey(hive, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def active_power_plan() -> dict:
    code, out = run_cmd(["powercfg", "/getactivescheme"])
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*\((.*)\)", out, re.I)
    if not m:
        return {"guid": None, "name": "Desconhecido"}
    return {"guid": m.group(1).lower(), "name": m.group(2).strip()}


def hibernation_enabled() -> bool:
    import os
    drive = os.environ.get("SystemDrive", "C:") + "\\"
    try:
        return "hiberfil.sys" in (f.lower() for f in os.listdir(drive))
    except OSError:
        return False


def windows_state() -> dict:
    """Configurações do Windows relevantes ao desempenho (lidas do registro)."""
    hku = winreg.HKEY_CURRENT_USER
    hklm = winreg.HKEY_LOCAL_MACHINE
    return {
        "game_mode": _reg_get(hku, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1),
        "game_dvr": _reg_get(hku, r"System\GameConfigStore", "GameDVR_Enabled", 1),
        "hags": _reg_get(hklm, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", None),
        "transparency": _reg_get(hku, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 1),
        "visual_fx": _reg_get(hku, r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 0),
        "hibernation": 1 if hibernation_enabled() else 0,
        "fast_startup": _reg_get(hklm, r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled", 0),
        "wsearch_start": _reg_get(hklm, r"SYSTEM\CurrentControlSet\Services\WSearch", "Start", None),
        "sysmain_start": _reg_get(hklm, r"SYSTEM\CurrentControlSet\Services\SysMain", "Start", None),
        "diagtrack_start": _reg_get(hklm, r"SYSTEM\CurrentControlSet\Services\DiagTrack", "Start", None),
        "mouse_accel": _reg_get(hku, r"Control Panel\Mouse", "MouseSpeed", "1"),
    }


def trim_enabled() -> bool | None:
    code, out = run_cmd(["fsutil", "behavior", "query", "DisableDeleteNotify"])
    m = re.search(r"NTFS\s+DisableDeleteNotify\s*=\s*(\d)", out)
    if not m:
        return None
    return m.group(1) == "0"


def pagefile_info() -> dict:
    sw = psutil.swap_memory()
    auto = None
    try:
        from .utils import run_ps
        auto = run_ps("(Get-CimInstance Win32_ComputerSystem).AutomaticManagedPagefile").strip().lower() == "true"
    except Exception:
        pass
    return {"total": sw.total, "used": sw.used, "auto": auto}


def collect() -> dict:
    """Coleta tudo. Pode levar alguns segundos (rode em thread)."""
    t0 = time.time()
    data = run_ps_json(_PS_SCRIPT, timeout=180) or {}
    for key in ("cpu", "gpu", "mem", "disks", "volumes", "battery", "net", "monitors"):
        data[key] = _as_list(data.get(key))

    for m in data["mem"]:
        m["type_name"] = _MEMORY_TYPES.get(m.get("type"), "Desconhecido")
    sysinfo = data.get("system") or {}
    sysinfo["type_name"] = _CHASSIS.get(sysinfo.get("type"), "Desktop")
    data["system"] = sysinfo
    data["is_laptop"] = bool(data["battery"]) or sysinfo.get("type") in (2, 8)

    vm = psutil.virtual_memory()
    data["ram_total"] = vm.total
    data["ram_used_pct"] = vm.percent
    data["uptime_s"] = time.time() - psutil.boot_time()
    data["cpu_freq_now"] = (psutil.cpu_freq().current if psutil.cpu_freq() else None)
    data["power_plan"] = active_power_plan()
    data["win"] = windows_state()
    data["trim"] = trim_enabled()
    data["pagefile"] = pagefile_info()
    data["python_platform"] = platform.platform()
    data["admin"] = is_admin()
    data["collected_at"] = dt.datetime.now().isoformat(timespec="seconds")
    data["collect_seconds"] = round(time.time() - t0, 1)
    return data


def gpu_vendor(name: str) -> str:
    n = (name or "").lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "gtx" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n:
        return "amd"
    if "intel" in n or "arc" in n or "iris" in n or "uhd" in n:
        return "intel"
    return "outro"


def is_integrated_gpu(g: dict) -> bool:
    n = (g.get("name") or "").lower()
    if "microsoft basic" in n or "remote" in n or "virtual" in n:
        return True
    if any(k in n for k in ("uhd graphics", "hd graphics", "iris", "radeon(tm) graphics", "radeon graphics", "vega")):
        return True
    return (g.get("vram") or 0) < 1 * 1024**3


def main_gpu(data: dict) -> dict | None:
    gpus = [g for g in data.get("gpu", []) if "basic" not in (g.get("name") or "").lower()]
    if not gpus:
        return None
    dedicated = [g for g in gpus if not is_integrated_gpu(g)]
    pool = dedicated or gpus
    return max(pool, key=lambda g: g.get("vram") or 0)


def report_text(data: dict) -> str:
    """Relatório em texto simples para exportar."""
    from .utils import fmt_bytes

    lines = ["RELATÓRIO DO SISTEMA — Otimizador", f"Gerado em: {data.get('collected_at')}", ""]
    o = data.get("os") or {}
    lines += ["[Sistema]", f"  {o.get('caption')} {o.get('display') or ''} (build {o.get('build')}.{o.get('ubr')}) {o.get('arch')}",
              f"  Computador: {data['system'].get('manufacturer')} {data['system'].get('model')} — {data['system'].get('type_name')}",
              f"  Placa-mãe: {(data.get('board') or {}).get('manufacturer')} {(data.get('board') or {}).get('product')}",
              f"  BIOS: {(data.get('bios') or {}).get('version')} ({(data.get('bios') or {}).get('date')})", ""]
    for c in data.get("cpu", []):
        lines += ["[Processador]", f"  {c.get('name')} — {c.get('cores')} núcleos / {c.get('threads')} threads, {c.get('max_mhz')} MHz base", ""]
    lines.append("[Placas de vídeo]")
    for g in data.get("gpu", []):
        lines.append(f"  {g.get('name')} — {fmt_bytes(g.get('vram'))} VRAM, driver {g.get('driver')} ({g.get('driver_date')}), {g.get('res_w')}x{g.get('res_h')} @ {g.get('hz')} Hz")
    lines += ["", f"[Memória] {fmt_bytes(data.get('ram_total'))} — {len(data.get('mem', []))} pente(s) de {data.get('mem_slots')} slot(s)"]
    for m in data.get("mem", []):
        lines.append(f"  {m.get('slot')}: {fmt_bytes(m.get('capacity'))} {m.get('type_name')} {m.get('configured')} MHz ({m.get('manufacturer')} {m.get('part')})")
    lines += ["", "[Armazenamento]"]
    for d in data.get("disks", []):
        lines.append(f"  {d.get('name')} — {d.get('media')} {d.get('bus')} {fmt_bytes(d.get('size'))} — {d.get('health')}{' (sistema)' if d.get('system') else ''}")
    for v in data.get("volumes", []):
        lines.append(f"  {v.get('letter')}: {fmt_bytes(v.get('free'))} livres de {fmt_bytes(v.get('size'))}")
    lines += ["", "[Rede]"]
    for n in data.get("net", []):
        lines.append(f"  {n.get('name')}: {n.get('desc')} — {n.get('speed')}")
    lines += ["", f"[Energia] Plano ativo: {data['power_plan'].get('name')}"]
    return "\n".join(lines)
