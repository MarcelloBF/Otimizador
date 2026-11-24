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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
