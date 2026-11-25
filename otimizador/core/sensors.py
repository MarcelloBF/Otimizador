"""Sensores em tempo real sem drivers extras.

- Uso da GPU e VRAM: contadores de desempenho do Windows (PDH), os mesmos do Gerenciador de Tarefas.
- Temperatura/ventoinha/energia da GPU: D3DKMT (WDDM 2.4+), também usado pelo Gerenciador de Tarefas.
- Temperatura da CPU: zonas térmicas ACPI (quando a placa-mãe expõe valores reais).
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

pdh = ctypes.WinDLL("pdh")
gdi32 = ctypes.WinDLL("gdi32")
for _fn in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData", "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
    getattr(pdh, _fn).restype = wintypes.DWORD  # códigos PDH são DWORD (evita negativos)
pdh.PdhAddEnglishCounterW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(wintypes.HANDLE)]
pdh.PdhGetFormattedCounterArrayW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                             ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("longValue", ctypes.c_long), ("doubleValue", ctypes.c_double), ("largeValue", ctypes.c_longlong)]

    _fields_ = [("CStatus", wintypes.DWORD), ("u", _U)]


class _PDH_FMT_COUNTERVALUE_ITEM(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PDH_FMT_COUNTERVALUE)]


class PdhQuery:
    """Consulta PDH com contadores curinga (ex.: \\GPU Engine(*)\\Utilization Percentage)."""

    def __init__(self, paths: dict[str, str]):
        self.h = wintypes.HANDLE()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(self.h)) != 0:
            raise OSError("PdhOpenQuery falhou")
        self.counters = {}
        for key, path in paths.items():
            c = wintypes.HANDLE()
            if pdh.PdhAddEnglishCounterW(self.h, path, None, ctypes.byref(c)) == 0:
                self.counters[key] = c
        pdh.PdhCollectQueryData(self.h)

    def collect(self) -> dict[str, dict[str, float]]:
        pdh.PdhCollectQueryData(self.h)
        out = {}
        for key, c in self.counters.items():
            size = wintypes.DWORD(0)
            count = wintypes.DWORD(0)
            rc = pdh.PdhGetFormattedCounterArrayW(c, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count), None)
            if rc != PDH_MORE_DATA or size.value == 0:
                out[key] = {}
                continue
            buf = (ctypes.c_byte * size.value)()
            rc = pdh.PdhGetFormattedCounterArrayW(c, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count),
                                                  ctypes.cast(buf, ctypes.c_void_p))
            items = ctypes.cast(buf, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM))
            vals = {}
            if rc == 0:
                for i in range(count.value):
                    it = items[i]
                    if it.FmtValue.CStatus in (0, 1):  # PDH_CSTATUS_VALID_DATA / NEW_DATA
                        vals[it.szName] = it.FmtValue.u.doubleValue
            out[key] = vals
        return out

    def close(self):
        pdh.PdhCloseQuery(self.h)


# ---------------------------------------------------------------- D3DKMT (temperatura da GPU)


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _ADAPTERINFO(ctypes.Structure):
    _fields_ = [("hAdapter", ctypes.c_uint), ("AdapterLuid", LUID), ("NumOfSources", wintypes.ULONG),
                ("bPrecisePresentRegionsPreferred", wintypes.BOOL)]


class _ENUMADAPTERS2(ctypes.Structure):
    _fields_ = [("NumAdapters", wintypes.ULONG), ("pAdapters", ctypes.POINTER(_ADAPTERINFO))]


class _QUERYADAPTERINFO(ctypes.Structure):
    _fields_ = [("hAdapter", ctypes.c_uint), ("Type", ctypes.c_int), ("pPrivateDriverData", ctypes.c_void_p),
                ("PrivateDriverDataSize", ctypes.c_uint)]


class _ADAPTER_PERFDATA(ctypes.Structure):
    _fields_ = [("PhysicalAdapterIndex", ctypes.c_uint), ("MemoryFrequency", ctypes.c_ulonglong),
                ("MaxMemoryFrequency", ctypes.c_ulonglong), ("MaxMemoryFrequencyOC", ctypes.c_ulonglong),
                ("MemoryBandwidth", ctypes.c_ulonglong), ("PCIEBandwidth", ctypes.c_ulonglong),
                ("FanRPM", ctypes.c_ulong), ("Power", ctypes.c_ulong), ("Temperature", ctypes.c_ulong),
                ("PowerStateOverride", ctypes.c_ubyte)]


class _ADAPTERREGISTRYINFO(ctypes.Structure):
    _fields_ = [("AdapterString", ctypes.c_wchar * 260), ("BiosString", ctypes.c_wchar * 260),
                ("DacType", ctypes.c_wchar * 260), ("ChipType", ctypes.c_wchar * 260)]


KMTQAITYPE_ADAPTERREGISTRYINFO = 8
KMTQAITYPE_ADAPTERPERFDATA = 62


def _query(h, typ, struct):
    q = _QUERYADAPTERINFO(h, typ, ctypes.cast(ctypes.pointer(struct), ctypes.c_void_p), ctypes.sizeof(struct))
    return gdi32.D3DKMTQueryAdapterInfo(ctypes.byref(q)) == 0


def _luid_key(luid: LUID) -> str:
    # Mesmo formato do nome de instância dos contadores PDH: luid_0x00000000_0x0000D2F1
    return f"luid_0x{luid.HighPart & 0xFFFFFFFF:08x}_0x{luid.LowPart:08x}"


class GpuAdapters:
    def __init__(self):
        self.adapters = []  # (handle, luid_key, nome)
        try:
            e = _ENUMADAPTERS2(0, None)
            if gdi32.D3DKMTEnumAdapters2(ctypes.byref(e)) != 0 or e.NumAdapters == 0:
                return
            arr = (_ADAPTERINFO * e.NumAdapters)()
            e.pAdapters = arr
            if gdi32.D3DKMTEnumAdapters2(ctypes.byref(e)) != 0:
                return
            for a in arr[: e.NumAdapters]:
                reg = _ADAPTERREGISTRYINFO()
                name = reg.AdapterString if _query(a.hAdapter, KMTQAITYPE_ADAPTERREGISTRYINFO, reg) else ""
                if not name or "basic render" in name.lower() or "microsoft" in name.lower():
                    continue
                self.adapters.append((a.hAdapter, _luid_key(a.AdapterLuid), name))
        except (OSError, AttributeError):
            pass

    def perf(self) -> dict[str, dict]:
        out = {}
        for h, key, name in self.adapters:
            p = _ADAPTER_PERFDATA()
            if _query(h, KMTQAITYPE_ADAPTERPERFDATA, p):
                out[key] = {"name": name, "temp": p.Temperature / 10 if p.Temperature else None,
                            "fan": p.FanRPM or None, "power_pct": p.Power / 10 if p.Power else None}
            else:
                out[key] = {"name": name, "temp": None, "fan": None, "power_pct": None}
        return out


# ---------------------------------------------------------------- monitor completo


class Sensors:
    """Coleta GPU (uso, VRAM, temperatura) e temperatura da CPU. Chame read() a cada ~1 s."""

    def __init__(self):
        self.q = None
        try:
            self.q = PdhQuery({
                "engine": r"\GPU Engine(*)\Utilization Percentage",
                "vram": r"\GPU Adapter Memory(*)\Dedicated Usage",
                "thermal": r"\Thermal Zone Information(*)\High Precision Temperature",
            })
        except OSError:
            self.q = None
        self.gpus = GpuAdapters()
        self._thermal_hist: list[float] = []

    def read(self) -> dict:
        data = self.q.collect() if self.q else {}
        # Uso por adaptador: soma por tipo de engine (3D, Compute, Copy, VideoDecode...) e pega o maior
        per_adapter: dict[str, dict[str, float]] = {}
        for inst, v in data.get("engine", {}).items():
            # pid_1234_luid_0x..._0x..._phys_0_eng_0_engtype_3D
            try:
                luid = ("luid_" + inst.split("_luid_")[1].split("_phys_")[0]).lower()
                eng = inst.split("_engtype_")[1]
            except IndexError:
                continue
            d = per_adapter.setdefault(luid, {})
            d[eng] = d.get(eng, 0.0) + v
        usage = {k: min(100.0, max(v.values())) for k, v in per_adapter.items() if v}
        vram = {}
        for inst, v in data.get("vram", {}).items():
            key = (inst.split("_phys_")[0] if "_phys_" in inst else inst).lower()
            vram[key] = vram.get(key, 0) + v
        perf = self.gpus.perf()

        gpus = []
        for h, key, name in self.gpus.adapters:
            p = perf.get(key, {})
            gpus.append({"name": name, "usage": usage.get(key, 0.0), "vram_used": vram.get(key),
                         "temp": p.get("temp"), "fan": p.get("fan"), "power_pct": p.get("power_pct")})

        # Zona térmica ACPI em décimos de Kelvin; muitas placas expõem um valor fixo (falso) -> descartado
        cpu_temp = None
        temps = [(v / 10) - 273.15 for v in data.get("thermal", {}).values() if v > 2000]
        temps = [t for t in temps if 15 < t < 115]
        if temps:
            t = max(temps)
            self._thermal_hist = (self._thermal_hist + [t])[-30:]
            varies = len(self._thermal_hist) < 10 or (max(self._thermal_hist) - min(self._thermal_hist)) >= 0.5
            if varies and not (27.5 <= t <= 28.0 and len(set(round(x, 1) for x in self._thermal_hist)) == 1):
                cpu_temp = t
        source = "zona térmica" if cpu_temp is not None else None
        if cpu_temp is None:
            # O vídeo integrado fica no mesmo chip do processador: sua temperatura é a do chip
            for g in gpus:
                if g["temp"] and is_on_cpu_die(g["name"]):
                    cpu_temp, source = g["temp"], "sensor do chip"
                    break
        for g in gpus:
            g["integrated"] = is_on_cpu_die(g["name"])
        return {"gpus": gpus, "cpu_temp": cpu_temp, "cpu_temp_source": source}

    @staticmethod
    def main_gpu(reading: dict) -> dict | None:
        """GPU principal: a dedicada se existir; senão a integrada."""
        gs = reading.get("gpus") or []
        if not gs:
            return None
        return max(gs, key=lambda g: (not g.get("integrated"), g.get("vram_used") or 0, g.get("usage") or 0))


def is_on_cpu_die(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in ("radeon(tm) graphics", "radeon graphics", "radeon(tm) vega", "uhd graphics",
                                "iris", "intel(r) hd graphics", "intel(r) graphics", "arc(tm) graphics"))


if __name__ == "__main__":
    s = Sensors()
    for _ in range(4):
        time.sleep(1)
        print(s.read())
