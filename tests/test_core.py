"""Testes do núcleo (rodar: .venv\\Scripts\\python.exe -m pytest tests  ou  python tests\\test_core.py)."""
import pathlib
import sys
import tempfile
import winreg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from otimizador.core import analyzer, startup  # noqa: E402
from otimizador.core import tweaks as T  # noqa: E402

P = r"Software\OtimizadorTest"


def test_tweak_apply_and_revert_restores_exact_original():
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, P) as k:
        winreg.SetValueEx(k, "dw", 0, winreg.REG_DWORD, 7)
        winreg.SetValueEx(k, "bin", 0, winreg.REG_BINARY, bytes.fromhex("aabbcc"))
    try:
        t = T.Tweak("t", "teste", "Desempenho", "", [
            T.Reg(T.HKCU, P, "dw", 1),
            T.Reg(T.HKCU, P, "sz", "x", winreg.REG_SZ),
            T.Reg(T.HKCU, P, "bin", "9012038010000000", winreg.REG_BINARY),
            T.Reg(T.HKCU, P, "big", 0xFFFFFFFF),
        ])
        b = T.Backup(pathlib.Path(tempfile.mkdtemp()) / "b.json")
        assert not t.is_applied()
        T.apply_tweak(t, b)
        assert t.is_applied()
        T.apply_tweak(t, b)  # reaplicar não pode sobrescrever o backup original
        assert T.revert_tweak(t, b)
        assert T.reg_read(T.HKCU, P, "dw")[0] == 7
        assert T.reg_read(T.HKCU, P, "sz")[0] == T.ABSENT
        assert T.reg_read(T.HKCU, P, "big")[0] == T.ABSENT
        assert T.reg_read(T.HKCU, P, "bin")[0] == "aabbcc"
        assert not T.revert_tweak(t, b)  # sem backup -> False
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, P)


def test_catalog_ids_unique_and_profiles_valid():
    ids = [t.id for t in T.TWEAKS]
    assert len(ids) == len(set(ids))
    for t in T.TWEAKS:
        assert t.category in T.CATEGORIES
        assert t.profiles <= set(T.PROFILES)
        assert t.risk in ("baixo", "médio", "alto")
    # Itens de risco alto nunca entram automaticamente em perfis
    assert all(not t.profiles for t in T.TWEAKS if t.risk == "alto")


def _fake_specs(**over):
    d = {
        "cpu": [{"name": "CPU", "cores": 4, "threads": 8}],
        "gpu": [{"name": "NVIDIA GeForce RTX 3060", "vram": 12 * 1024**3, "driver_date": "2020-01-01", "hz": 60, "res_w": 1920}],
        "mem": [{"capacity": 8 * 1024**3, "configured": 2133, "speed": 3200, "type_name": "DDR4"}],
        "mem_slots": 4,
        "disks": [{"name": "HD", "media": "HDD", "bus": "SATA", "system": True, "health": "Healthy", "number": 0}],
        "volumes": [{"letter": "C", "size": 500 * 1024**3, "free": 20 * 1024**3}],
        "ram_total": 8 * 1024**3, "ram_used_pct": 50, "uptime_s": 3600,
        "power_plan": {"guid": T.BALANCED, "name": "Equilibrado"},
        "win": {"game_dvr": 1, "game_mode": 1, "hags": 0, "mouse_accel": "1", "hibernation": 1},
        "net": [{"name": "Ethernet", "desc": "Realtek Gaming 2.5GbE", "speed": "100 Mbps", "media": "802.3"}],
        "is_laptop": False, "os": {"build": "26100"}, "trim": True, "pagefile": {"total": 1},
    }
    d.update(over)
    return d


def test_analyzer_flags_key_problems():
    a = analyzer.analyze(_fake_specs(), {"startup_enabled": 12, "junk_bytes": 3 * 1024**3})
    ids = {r.id for r in a.recs}
    for expected in ("hdd_system", "single_channel", "xmp", "gpu_driver_old", "power_plan", "game_dvr",
                     "refresh_60", "startup_many", "junk", "link_Ethernet", "vol_full_C", "hibernation"):
        assert expected in ids, expected
    assert a.recs[0].severity == "crítico"
    assert 0 < a.score < 70


def test_analyzer_laptop_profile():
    a = analyzer.analyze(_fake_specs(is_laptop=True))
    assert a.profile == "notebook"
    assert "hibernation" not in {r.id for r in a.recs}


def test_link_speed_parse():
    assert analyzer._link_mbps("100 Mbps") == 100
    assert analyzer._link_mbps("2.5 Gbps") == 2500
    assert analyzer._link_mbps(None) is None


def test_startup_hints():
    mk = lambda n, c: startup.StartupItem(n, c, "", T.HKCU, "Run", True)  # noqa: E731
    assert mk("Steam", r"C:\Steam\steam.exe -silent").hint[0] == "desativar"
    assert mk("Riot Vanguard", r"C:\Program Files\Riot Vanguard\vgtray.exe").hint[0] == "manter"
    assert mk("SecurityHealth", "SecurityHealthSystray.exe").hint[0] == "manter"
    assert mk("Foo", '"C:\\a b\\foo.exe" /x').executable == r"C:\a b\foo.exe"


def test_benchmark_score_and_compare():
    from otimizador.core import benchmark as B

    ref = {m.key: m.reference for m in B.METRICS}
    assert B.score(ref) == 1000
    faster = dict(ref, latency=ref["latency"] / 2, cpu_single=ref["cpu_single"] * 2)
    assert B.score(faster) > 1000
    cmp = B.compare({"results": ref}, {"results": faster})
    assert round(cmp["latency"]) == 50  # menor é melhor -> +50%
    assert round(cmp["cpu_single"]) == 100
    assert round(cmp["mem_bw"]) == 0


def test_latency_and_memory_benchmarks_run():
    from otimizador.core import benchmark as B

    lat = B.bench_latency(samples=50)
    assert 0 <= lat["latency"] < 50
    assert B.bench_memory(size_mb=16, rounds=2) > 0.1


def test_sensors_read_does_not_crash():
    from otimizador.core.sensors import Sensors

    r = Sensors().read()
    assert "gpus" in r and "cpu_temp" in r


WINGET_EN = """Name                 Id                     Version    Available Source
-------------------------------------------------------------------------
App Installer        Microsoft.AppInstaller 1.29.379.0 1.29.380  winget
Some Tool            Vendor.Tool            Unknown    2.0       winget
2 upgrades available.

The following packages have an upgrade available, but require explicit targeting for upgrade:
Name    Id              Version  Available Source
-------------------------------------------------
Discord Discord.Discord 1.0.9269 1.0.9270  winget
"""

WINGET_PT = """Nome              ID              Versão  Disponível Origem
-----------------------------------------------------------
微信 WeChat       Tencent.WeChat  3.9.0   3.9.1      winget
Programa Ágil      Foo.Bar         1.0     1.1        winget
2 atualizações disponíveis.
"""


def test_winget_parser():
    from otimizador.core import updates as U

    pk = U.parse_upgrade_table(WINGET_EN)
    assert [p.id for p in pk] == ["Microsoft.AppInstaller", "Vendor.Tool", "Discord.Discord"]
    assert pk[0].version == "1.29.379.0" and pk[0].available == "1.29.380" and pk[0].suggested
    assert pk[1].unknown_version and not pk[1].suggested
    assert pk[2].explicit and not pk[2].suggested
    assert U.order_for_install(pk)[-1].id == "Microsoft.AppInstaller"
    pt = U.parse_upgrade_table(WINGET_PT)
    assert [(p.name, p.id, p.available) for p in pt] == [("微信 WeChat", "Tencent.WeChat", "3.9.1"),
                                                          ("Programa Ágil", "Foo.Bar", "1.1")]
    assert U.parse_upgrade_table("No installed package found matching input criteria.") == []


def test_winget_exit_codes_and_drivers():
    import datetime as dt

    from otimizador.core import updates as U

    assert U.is_success(0) and U.exit_message(0) == "Atualizado"
    assert U.exit_message(-1978334975) == U.EXIT_MESSAGES[0x8A150101]  # valor com sinal
    assert "0x8A150999" in U.exit_message(0x8A150999)
    specs = {"gpu": [{"name": "NVIDIA GeForce RTX 3060", "driver": "31.0", "driver_date": "2025-01-01"},
                     {"name": "Microsoft Basic Display Adapter"}]}
    d = U.gpu_drivers(specs, today=dt.date(2026, 6, 1))
    assert d[0]["vendor"] == "nvidia" and d[0]["status"] == "old" and "nvidia" in d[0]["url"]
    assert d[1]["status"] == "missing"


def test_selfupdate_versions_and_release_info():
    from otimizador.core import selfupdate as S

    assert S.is_newer("v1.10.0", "1.9.9") and not S.is_newer("1.2.0", "1.2.0") and not S.is_newer("1.1", "1.2.0")
    info = S.release_info({"tag_name": "v2.0.0", "html_url": "u", "assets": [
        {"name": "outro.zip", "browser_download_url": "x"},
        {"name": "Otimizador.exe", "browser_download_url": "d", "size": 10, "digest": "sha256:ABC"}]})
    assert info == {"version": "2.0.0", "url": "u", "notes": "", "asset_url": "d", "asset_size": 10, "sha256": "abc"}
    assert not S.can_self_update(info)  # rodando pelo Python, não pelo .exe


def test_gamemode_close_and_state(monkeypatch=None):
    import subprocess as sp

    from otimizador.core import gamemode as G

    tmp = pathlib.Path(tempfile.mkdtemp())
    old_dd, old_set, old_active = G.data_dir, G.T._set_scheme, G.T._active_scheme
    calls = []
    G.data_dir = lambda: tmp
    G.T._set_scheme = calls.append
    G.T._active_scheme = lambda: G.T.BALANCED
    proc = sp.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        c = G.Candidate("python.exe", "Teste", True, "", pids=[proc.pid], exe=sys.executable)
        assert G._packaged_app_id(sys.executable) is None
        st = G.activate([c], power=True)
        assert proc.poll() is not None, "processo deveria ter sido fechado"
        assert G.is_active() and st["previous_plan"] == G.T.BALANCED and calls[-1] == G.T.HIGH_PERF
        assert st["closed"] == [{"name": "Teste", "exe": sys.executable}]
        G.deactivate(reopen_apps=False)
        assert calls[-1] == G.T.BALANCED and not G.is_active()
    finally:
        proc.kill()
        G.data_dir, G.T._set_scheme, G.T._active_scheme = old_dd, old_set, old_active


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
