"""Consultor de upgrades: encontra o gargalo do PC e sugere o próximo upgrade compatível, em ordem de custo-benefício.

Os índices de desempenho são médias aproximadas de reviews de jogos (não medem o PC do usuário):
- CPU: Ryzen 5 7600 = 100 (desempenho em jogos, placa de vídeo sem limitar)
- GPU: RTX 4060 = 100 (rasterização em 1440p)
Custos são relativos ($ a $$$$), porque os preços mudam muito entre lojas e países.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ----------------------------------------------------------------- processadores
# modelo -> (índice de jogos, plataforma, núcleos)
CPUS: dict[str, tuple[int, str, int]] = {
    # AM4
    "1200": (40, "AM4", 4), "1600": (50, "AM4", 6), "1700": (52, "AM4", 8), "2600": (55, "AM4", 6), "2700X": (58, "AM4", 8),
    "3200G": (45, "AM4", 4), "3400G": (50, "AM4", 4), "3600": (70, "AM4", 6), "3600X": (71, "AM4", 6),
    "3700X": (72, "AM4", 8), "3800X": (73, "AM4", 8), "3900X": (74, "AM4", 12), "3950X": (75, "AM4", 16),
    "4500": (66, "AM4", 6), "4600G": (66, "AM4", 6), "5500": (72, "AM4", 6), "5600G": (74, "AM4", 6),
    "5600": (80, "AM4", 6), "5600X": (82, "AM4", 6), "5700G": (78, "AM4", 8), "5700X": (84, "AM4", 8),
    "5800X": (86, "AM4", 8), "5900X": (88, "AM4", 12), "5950X": (89, "AM4", 16),
    "5600X3D": (92, "AM4", 6), "5700X3D": (95, "AM4", 8), "5800X3D": (100, "AM4", 8),
    # AM5
    "7500F": (98, "AM5", 6), "7600": (100, "AM5", 6), "7600X": (103, "AM5", 6), "7700": (106, "AM5", 8),
    "7700X": (107, "AM5", 8), "7900": (106, "AM5", 12), "7900X": (108, "AM5", 12), "7950X": (112, "AM5", 16),
    "7800X3D": (130, "AM5", 8), "7900X3D": (122, "AM5", 12), "7950X3D": (130, "AM5", 16),
    "4650G": (66, "AM4", 6), "5500GT": (72, "AM4", 6), "5600GT": (75, "AM4", 6), "8400F": (95, "AM5", 6),
    "8500G": (78, "AM5", 6), "8600G": (85, "AM5", 6), "8700G": (90, "AM5", 8),
    "9600": (108, "AM5", 6), "9600X": (110, "AM5", 6), "9700X": (112, "AM5", 8), "9900X": (114, "AM5", 12),
    "9950X": (118, "AM5", 16), "9800X3D": (145, "AM5", 8), "9900X3D": (135, "AM5", 12), "9950X3D": (145, "AM5", 16),
    # Intel LGA1151
    "6500": (42, "LGA1151", 4), "6600K": (45, "LGA1151", 4), "6700K": (48, "LGA1151", 4), "7700K": (52, "LGA1151", 4),
    "8100": (44, "LGA1151", 4), "8400": (55, "LGA1151", 6), "8600K": (58, "LGA1151", 6), "8700": (60, "LGA1151", 6),
    "8700K": (62, "LGA1151", 6), "9400F": (56, "LGA1151", 6), "9400": (56, "LGA1151", 6), "9600K": (60, "LGA1151", 6),
    "9700K": (66, "LGA1151", 8), "9900K": (70, "LGA1151", 8),
    # Intel LGA1200
    "10100F": (52, "LGA1200", 4), "10100": (52, "LGA1200", 4), "10400F": (62, "LGA1200", 6), "10400": (62, "LGA1200", 6),
    "10600K": (66, "LGA1200", 6), "10700": (69, "LGA1200", 8), "10700K": (70, "LGA1200", 8), "10850K": (73, "LGA1200", 10),
    "10900K": (74, "LGA1200", 10), "11400F": (70, "LGA1200", 6), "11400": (70, "LGA1200", 6), "11600K": (74, "LGA1200", 6),
    "11700K": (76, "LGA1200", 8), "11900K": (78, "LGA1200", 8),
    # Intel LGA1700
    "12100F": (75, "LGA1700", 4), "12100": (75, "LGA1700", 4), "12400F": (85, "LGA1700", 6), "12400": (85, "LGA1700", 6),
    "12600K": (95, "LGA1700", 10), "12600KF": (95, "LGA1700", 10), "12700K": (100, "LGA1700", 12),
    "12700KF": (100, "LGA1700", 12), "12900K": (105, "LGA1700", 16), "13400F": (90, "LGA1700", 10),
    "13400": (90, "LGA1700", 10), "13600K": (108, "LGA1700", 14), "13600KF": (108, "LGA1700", 14),
    "13700K": (115, "LGA1700", 16), "13700KF": (115, "LGA1700", 16), "13900K": (120, "LGA1700", 24),
    "14400F": (92, "LGA1700", 10), "14400": (92, "LGA1700", 10), "14600K": (110, "LGA1700", 14),
    "14600KF": (110, "LGA1700", 14), "14700K": (118, "LGA1700", 20), "14700KF": (118, "LGA1700", 20),
    "14900K": (122, "LGA1700", 24), "14900KF": (122, "LGA1700", 24),
    # Intel LGA1851 (Core Ultra 200S)
    "225": (95, "LGA1851", 10), "245K": (105, "LGA1851", 14), "265K": (112, "LGA1851", 20), "285K": (118, "LGA1851", 24),
}

# Intel com número igual a um Ryzen (ex.: i5-7600 x Ryzen 5 7600) ficam separados
INTEL_EXTRA: dict[str, tuple[int, str, int]] = {
    "4590": (36, "LGA1150", 4), "4690K": (38, "LGA1150", 4), "4770": (39, "LGA1150", 4), "4790K": (42, "LGA1150", 4),
    "6400": (40, "LGA1151", 4), "7400": (46, "LGA1151", 4), "7500": (48, "LGA1151", 4), "7600": (50, "LGA1151", 4),
    "7700": (50, "LGA1151", 4),
}

# Melhor processador que encaixa na mesma placa-mãe (jogos, trabalho pesado)
SAME_SOCKET_BEST = {
    "AM4": (["Ryzen 7 5800X3D", "Ryzen 7 5700X3D"], "5700X3D", "Ryzen 9 5950X",
            "Placas A320/B350/X370 precisam de BIOS atualizada para Ryzen 5000; confira a lista de CPUs do fabricante."),
    "AM5": (["Ryzen 7 9800X3D", "Ryzen 7 7800X3D"], "9800X3D", "Ryzen 9 9950X",
            "Atualize a BIOS da placa antes de trocar o processador."),
    "LGA1700": (["Core i7-14700K", "Core i5-14600K"], "14600K", "Core i9-14900K",
                "Atualize a BIOS (microcódigo 0x12B ou mais novo) antes: corrige a instabilidade dos Intel de 13ª/14ª geração."),
    "LGA1851": (["Core Ultra 9 285K"], "285K", "Core Ultra 9 285K", "Atualize a BIOS antes de trocar."),
    "LGA1200": (["Core i9-11900K", "Core i7-11700K"], "11700K", "Core i9-10900K",
                "Plataforma encerrada: o ganho é pequeno; considere trocar placa-mãe + processador + memória."),
    "LGA1151v1": (["Core i7-7700K"], "7700K", "Core i7-7700K",
                  "Placas da 6ª/7ª geração não aceitam processadores da 8ª/9ª geração."),
    "LGA1151": (["Core i9-9900K"], "9900K", "Core i9-9900K",
                "Placas 100/200 não aceitam a 8ª/9ª geração. Plataforma antiga: compensa mais trocar placa + processador."),
}
NEW_PLATFORM = ("Ryzen 5 7600 ou Ryzen 7 9800X3D + placa B650 + 32 GB DDR5", 100, 145)


# ----------------------------------------------------------------- placas de vídeo
# nome -> (índice, VRAM GB, fonte recomendada W)
GPUS: dict[str, tuple[int, int, int]] = {
    "GTX 1050 Ti": (30, 4, 300), "GTX 1050": (24, 2, 300), "GTX 1060": (45, 6, 400), "GTX 1650": (37, 4, 300),
    "GTX 1650 Super": (45, 4, 350), "GTX 1660": (55, 6, 450), "GTX 1660 Super": (62, 6, 450), "GTX 1660 Ti": (63, 6, 450),
    "GTX 1070": (57, 8, 500), "GTX 1070 Ti": (64, 8, 500), "GTX 1080": (72, 8, 500), "GTX 1080 Ti": (92, 11, 600),
    "RTX 2060": (70, 6, 500), "RTX 2060 Super": (82, 8, 550), "RTX 2070": (85, 8, 550), "RTX 2070 Super": (95, 8, 650),
    "RTX 2080": (103, 8, 650), "RTX 2080 Super": (108, 8, 650), "RTX 2080 Ti": (125, 11, 650),
    "RTX 3050": (60, 8, 550), "RTX 3060": (85, 12, 550), "RTX 3060 Ti": (108, 8, 600), "RTX 3070": (122, 8, 650),
    "RTX 3070 Ti": (128, 8, 750), "RTX 3080": (150, 10, 750), "RTX 3080 Ti": (165, 12, 750), "RTX 3090": (170, 24, 750),
    "RTX 3090 Ti": (180, 24, 850),
    "RTX 4060": (100, 8, 550), "RTX 4060 Ti": (120, 8, 550), "RTX 4070": (150, 12, 650), "RTX 4070 Super": (170, 12, 650),
    "RTX 4070 Ti": (185, 12, 700), "RTX 4070 Ti Super": (200, 16, 700), "RTX 4080": (225, 16, 750),
    "RTX 4080 Super": (230, 16, 750), "RTX 4090": (290, 24, 850),
    "RTX 5050": (95, 8, 550), "RTX 5060": (120, 8, 550), "RTX 5060 Ti": (140, 16, 600), "RTX 5070": (175, 12, 650),
    "RTX 5070 Ti": (220, 16, 750), "RTX 5080": (250, 16, 850), "RTX 5090": (360, 32, 1000),
    "RX 570": (42, 4, 450), "RX 580": (46, 8, 500), "RX 590": (50, 8, 500), "RX 5500 XT": (50, 8, 450),
    "RX 5600 XT": (70, 6, 550), "RX 5700": (78, 8, 600), "RX 5700 XT": (86, 8, 600), "RX 6400": (35, 4, 300),
    "RX 6500 XT": (45, 4, 400), "RX 6600": (90, 8, 450), "RX 6600 XT": (100, 8, 500), "RX 6650 XT": (105, 8, 500),
    "RX 6700": (115, 10, 550), "RX 6700 XT": (125, 12, 650), "RX 6750 XT": (132, 12, 650), "RX 6800": (155, 16, 650),
    "RX 6800 XT": (175, 16, 750), "RX 6900 XT": (185, 16, 850), "RX 6950 XT": (195, 16, 850),
    "RX 7600": (105, 8, 550), "RX 7600 XT": (110, 16, 600), "RX 7700 XT": (150, 12, 700), "RX 7800 XT": (175, 16, 700),
    "RX 7900 GRE": (185, 16, 700), "RX 7900 XT": (215, 20, 750), "RX 7900 XTX": (245, 24, 800),
    "RX 9060 XT": (135, 16, 600), "RX 9070": (200, 16, 650), "RX 9070 XT": (225, 16, 750),
    "Arc A380": (40, 6, 400), "Arc A580": (85, 8, 550), "Arc A750": (92, 8, 600), "Arc A770": (100, 16, 650),
    "Arc B570": (105, 10, 550), "Arc B580": (115, 12, 600),
    # integradas
    "Radeon 780M": (40, 0, 0), "Radeon 760M": (32, 0, 0), "Radeon 680M": (33, 0, 0), "Radeon Vega 8": (20, 0, 0),
    "Radeon Vega 11": (24, 0, 0), "Radeon Graphics": (8, 0, 0), "Iris Xe": (18, 0, 0), "UHD Graphics": (8, 0, 0),
    "Intel Arc Graphics": (35, 0, 0),
}

# Placas novas à venda para sugerir, com custo relativo
BUYABLE_GPUS = [
    ("Arc B580", "$"), ("RTX 5060", "$"), ("RX 9060 XT", "$$"), ("RTX 5060 Ti", "$$"), ("RTX 5070", "$$$"),
    ("RX 9070", "$$$"), ("RX 9070 XT", "$$$"), ("RTX 5070 Ti", "$$$$"), ("RTX 5080", "$$$$"),
]

# Quanto de placa de vídeo um processador consegue aproveitar, por resolução (multiplica o índice da CPU)
GPU_PER_CPU = {1080: 1.6, 1440: 2.2, 2160: 3.0}


@dataclass
class Part:
    name: str
    index: int | None  # None = modelo não reconhecido
    extra: dict = field(default_factory=dict)


@dataclass
class Balance:
    key: str
    label: str
    score: int  # 0–100 em relação a um PC gamer topo de linha atual
    detail: str


@dataclass
class UpgradeRec:
    id: str
    category: str  # gpu, cpu, ram, storage, monitor, platform
    title: str
    why: str
    buy: list[str]
    gain: str
    cost: str
    notes: list[str] = field(default_factory=list)


@dataclass
class Combo:
    name: str
    parts: list[str]
    result: str


@dataclass
class UpgradePlan:
    cpu: Part
    gpu: Part
    resolution: int
    hz: int
    balance: list[Balance]
    bottleneck: str  # gpu, cpu, ram, storage, equilibrado, notebook
    verdict: str
    recs: list[UpgradeRec]
    combos: list[Combo]
    laptop: bool


# ----------------------------------------------------------------- identificação


def identify_cpu(name: str) -> Part:
    n = (name or "").replace("(R)", "").replace("(TM)", "")
    m = re.search(r"Core\s*\(?\w*\)?\s*Ultra\s*\d\s+(\d{3}[A-Z]*)", n, re.I)
    if not m:
        m = re.search(r"i[3579][- ](\d{4,5}[A-Z]*)", n, re.I)
    if not m:
        m = re.search(r"Ryzen\s+\d\s+(?:PRO\s+)?(\d{4}[A-Z0-9]*)", n, re.I)
    if m:
        model = m.group(1).upper()
        intel = not re.search(r"Ryzen", n, re.I)
        for key in (model, model.rstrip("F"), model.replace("KF", "K")):
            entry = INTEL_EXTRA.get(key) if intel else None
            if entry is None and key in CPUS and CPUS[key][1].startswith("LGA" if intel else "AM"):
                entry = CPUS[key]
            if entry:
                idx, plat, cores = entry
                return Part(name.strip(), idx, {"platform": plat, "model": key, "cores": cores})
        return Part(name.strip(), None, {"model": model})
    return Part(name.strip(), None, {})


def identify_gpu(name: str) -> Part:
    n = (name or "").replace("(TM)", "").replace("(R)", "")
    n = re.sub(r"\s+", " ", n)
    best = None
    for key in GPUS:
        pat = r"\b" + re.escape(key).replace(r"\ ", r"\s*") + r"\b"
        if re.search(pat, n, re.I) and (best is None or len(key) > len(best)):
            best = key
    if best:
        idx, vram, psu = GPUS[best]
        return Part(name.strip(), idx, {"model": best, "vram": vram, "psu": psu})
    return Part(name.strip(), None, {})


def _res_bucket(w: int | None) -> int:
    w = w or 1920
    if w >= 3200:
        return 2160
    if w >= 2400:
        return 1440
    return 1080


def _gain(new: float, old: float) -> int:
    return round((new / old - 1) * 100) if old else 0


# ----------------------------------------------------------------- análise


def analyze(specs: dict) -> UpgradePlan:
    from .sysinfo import main_gpu

    laptop = bool(specs.get("is_laptop"))
    cpu_d = (specs.get("cpu") or [{}])[0]
    cpu = identify_cpu(cpu_d.get("name", ""))
    plat = cpu.extra.get("platform") or (cpu_d.get("socket") or "").upper().replace(" ", "")
    # Mesmo soquete, placas diferentes: 6ª/7ª geração não aceita 8ª/9ª
    sock_key = plat
    if plat == "LGA1151" and str(cpu.extra.get("model", ""))[:1] in ("6", "7"):
        sock_key = "LGA1151v1"
    g = main_gpu(specs) or {}
    gpu = identify_gpu(g.get("name", ""))
    res = _res_bucket(g.get("res_w"))
    hz = int(g.get("hz") or 60)

    mem = specs.get("mem") or []
    ram_bytes = sum(m.get("capacity") or 0 for m in mem) or specs.get("ram_total") or 0
    ram_gb = round(ram_bytes / 1024**3)
    ram_type = next((m.get("type_name") for m in mem if m.get("type_name")), "")
    sticks = len(mem)
    slots = specs.get("mem_slots") or 0
    channels = len({(m.get("bank") or m.get("slot") or str(i)) for i, m in enumerate(mem)})
    single = sticks == 1 or channels == 1
    ram_used = specs.get("ram_used_pct") or 0

    sysd = next((d for d in specs.get("disks", []) if d.get("system")), {})
    sys_media = (sysd.get("media") or "").upper()
    sys_bus = (sysd.get("bus") or "").upper()
    sys_free = next((v.get("free") for v in specs.get("volumes", []) if (v.get("letter") or "").upper() == "C"), None)

    # ---- barras de equilíbrio (100 = PC gamer topo de linha atual)
    bal = []
    bal.append(Balance("cpu", "Processador", min(100, round((cpu.index or 70) / 145 * 100)),
                       f"{cpu.name}" + ("" if cpu.index else " (modelo não reconhecido: estimativa)")))
    bal.append(Balance("gpu", "Placa de vídeo", min(100, round((gpu.index or 30) / 250 * 100)),
                       f"{gpu.name or 'sem placa de vídeo dedicada'}" + (f" · {gpu.extra['vram']} GB" if gpu.extra.get("vram") else "")))
    ram_score = 25 if ram_gb < 12 else 60 if ram_gb < 24 else 85 if ram_gb < 48 else 100
    if single:
        ram_score -= 20
    if ram_type == "DDR5":
        ram_score += 10
    bal.append(Balance("ram", "Memória RAM", max(5, min(100, ram_score)),
                       f"{ram_gb} GB {ram_type} · {sticks} pente(s){' · canal único' if single else ''}"))
    sto_score = 100 if sys_bus == "NVME" else 70 if sys_media == "SSD" else 15
    bal.append(Balance("storage", "Disco do Windows", sto_score,
                       f"{sysd.get('name', '?')} ({'SSD NVMe' if sys_bus == 'NVME' else sys_media or '?'})"))

    recs: list[UpgradeRec] = []
    cap = (cpu.index or 70) * GPU_PER_CPU[res]

    # ---- 1. disco: o maior salto por real gasto
    if sys_media == "HDD":
        recs.append(UpgradeRec(
            "ssd", "storage", "Trocar o disco do Windows por um SSD",
            "O Windows está num HD mecânico: é o maior gargalo possível. Um SSD deixa o boot, a abertura de programas "
            "e o carregamento de jogos de 3 a 10 vezes mais rápidos.",
            ["SSD NVMe de 1 TB (se a placa tiver slot M.2)", "ou SSD SATA de 1 TB"], "Muito alto no uso geral", "$",
            ["Dá para clonar o Windows para o SSD sem reinstalar (Macrium Reflect, Clonezilla)."]))
    elif sys_free is not None and sys_free < 50 * 1024**3:
        recs.append(UpgradeRec(
            "ssd_space", "storage", "SSD maior ou um segundo SSD",
            f"O disco do Windows tem só {round(sys_free / 1024**3)} GB livres. Pouco espaço deixa o SSD mais lento e "
            "atrapalha atualizações.", ["SSD NVMe de 1–2 TB para os jogos"], "Médio", "$"))

    # ---- 2. memória
    if ram_gb < 16 or (ram_gb < 32 and ram_used >= 80) or single:
        target = 32 if ram_gb >= 16 or ram_type == "DDR5" else 16
        free_slots = max(0, slots - sticks)
        if single and ram_gb >= 8 and target <= ram_gb * 2 and free_slots:
            buy = [f"Mais 1 pente igual ao atual ({ram_gb} GB {ram_type}, mesma velocidade)"]
            why = ("A memória está em canal único: o processador recebe dados pela metade da velocidade. "
                   "Um segundo pente igual ativa o dual-channel e dá de 10% a 30% mais FPS em muitos jogos.")
            gain = "Alto em jogos"
        else:
            buy = [f"Kit {target} GB (2 × {target // 2} GB) {ram_type}".strip()]
            why = (f"{ram_gb} GB {'é pouco hoje' if ram_gb < 16 else 'ficam no limite'}: "
                   + (f"o uso chegou a {ram_used:.0f}% durante a análise. " if ram_used else "")
                   + "Quando a RAM acaba, o Windows usa o disco e o jogo engasga.")
            gain = "Alto se a RAM enche; menos travadas" if ram_gb < 16 else "Médio: menos travadas com navegador e Discord abertos"
        notes = []
        if ram_type == "DDR5" and sticks + 2 > 2 and "2 ×" in buy[0] and sticks >= 2:
            notes.append("Com DDR5, prefira trocar por um kit de 2 pentes em vez de usar 4: com 4 pentes a velocidade costuma cair.")
        if not laptop and ram_type:
            notes.append(f"Use {ram_type}: é o único tipo que encaixa na sua placa-mãe.")
        if laptop:
            notes.append("Em notebook, confira se a memória não é soldada na placa e quantos slots existem.")
        recs.append(UpgradeRec("ram", "ram", f"Memória: {buy[0].split(' (')[0]}", why, buy, gain, "$", notes))

    # ---- 3. placa de vídeo x processador
    bottleneck = "equilibrado"
    if laptop:
        bottleneck = "notebook"
    elif gpu.index is None or cap / gpu.index >= 1.3:
        bottleneck = "gpu"  # o processador aguenta uma placa pelo menos 30% mais forte
    elif gpu.index > cap * 1.05:
        bottleneck = "cpu"

    if not laptop:
        cur = gpu.index or 20
        options = []
        for name, cost in BUYABLE_GPUS:
            idx, vram, psu = GPUS[name]
            if idx >= cur * 1.3:
                options.append((name, cost, idx, vram, psu))
        # Placas de 8 GB saem da lista quando há uma de 12 GB+ com desempenho parecido
        options = [o for o in options
                   if not (o[3] <= 8 and any(q[3] >= 12 and q[2] >= o[2] * 0.9 for q in options))]
        fitting = [o for o in options if o[2] <= cap * 1.15]
        if options and bottleneck in ("gpu", "equilibrado"):
            pick = fitting or options[:1]
            econ = pick[0]
            best = max(pick, key=lambda o: o[2])
            mid = next((o for o in pick if o[2] >= econ[2] * 1.25 and o[2] <= best[2]), best)
            chosen = list(dict.fromkeys([econ, mid, best]))
            buy = [f"{o[0]} ({o[3]} GB) · {o[1]} · +{_gain(min(o[2], cap), cur)}% FPS"
                   + (" · limitado pelo processador" if o[2] > cap else "") for o in chosen]
            notes = [f"Fonte recomendada: {max(o[4] for o in chosen)} W ou mais, de boa marca. Confira a sua antes de comprar."]
            if any(o[3] == 8 for o in chosen):
                notes.append("Placas de 8 GB já ficam no limite em jogos novos com texturas altas: prefira 12–16 GB.")
            why = ("A placa de vídeo é o que mais limita o FPS hoje: o processador aguenta uma placa bem mais forte"
                   f" em {res}p." if bottleneck == "gpu" else
                   "PC equilibrado. Se quiser mais FPS, a placa de vídeo é a troca com mais efeito.")
            recs.append(UpgradeRec("gpu", "gpu", "Placa de vídeo mais forte", why, buy,
                                   f"Até +{_gain(min(best[2], cap), cur)}% de FPS",
                                   econ[1] if econ[1] == best[1] else econ[1] + "–" + best[1], notes))

    # ---- 4. processador
    if not laptop and sock_key in SAME_SOCKET_BEST:
        names, key, _work, note = SAME_SOCKET_BEST[sock_key]
        top_idx = CPUS[key][0]
        cur = cpu.index or 0
        if cur and top_idx >= cur * 1.15:
            why = ("O processador já limita a placa de vídeo atual" if bottleneck == "cpu" else
                   f"Em {res}p com monitor de {hz} Hz o processador pesa bastante" if hz >= 165 else
                   "Upgrade que encaixa na mesma placa-mãe, sem trocar memória")
            recs.append(UpgradeRec(
                "cpu", "cpu", f"Processador {names[0]} na mesma placa-mãe",
                why + f": troca só o processador, mantendo placa-mãe ({plat}) e memória.",
                [f"{n}" for n in names], f"Até +{_gain(top_idx, cur)}% de FPS onde o processador limita",
                "$$$" if plat in ("AM5", "LGA1851") else "$$", [note]))
        elif plat in ("LGA1151", "LGA1200", "LGA1150") or (cur and cur < 70):
            recs.append(UpgradeRec(
                "platform", "platform", "Nova plataforma (placa-mãe + processador + memória)",
                "O processador é de uma plataforma antiga e sem upgrades que valham a pena: "
                "o próximo salto real é trocar placa-mãe, processador e memória juntos.",
                [NEW_PLATFORM[0]], f"Até +{_gain(NEW_PLATFORM[1], cur or 60)}% de FPS onde o processador limita", "$$$$",
                ["A placa de vídeo, o SSD, a fonte e o gabinete continuam."]))
    elif not laptop and cpu.index and cpu.index < 70:
        recs.append(UpgradeRec(
            "platform", "platform", "Nova plataforma (placa-mãe + processador + memória)",
            "Processador antigo para jogos atuais.", [NEW_PLATFORM[0]], "Alto", "$$$$"))

    # ---- 5. monitor
    if not laptop and hz <= 75 and (gpu.index or 0) >= 85:
        recs.append(UpgradeRec(
            "monitor", "monitor", "Monitor de 144 Hz ou mais",
            f"A placa de vídeo passa de 60 FPS em muitos jogos, mas o monitor só mostra {hz} quadros por segundo.",
            ["Monitor 1080p ou 1440p de 144–180 Hz"], "Muito mais fluidez visível", "$$"))

    # ---- ordenação por custo-benefício
    order = {"ssd": 0, "ram": 1, "ssd_space": 4, "monitor": 3}
    if bottleneck == "cpu":
        order.update(cpu=2, gpu=5, platform=2)
    else:
        order.update(gpu=2, cpu=5, platform=6)
    recs.sort(key=lambda r: order.get(r.id, 9))

    # ---- veredito
    if laptop:
        verdict = ("Notebook: processador e placa de vídeo não são trocáveis. Os upgrades possíveis são memória e SSD; "
                   "para jogos, o próximo passo real é um notebook ou desktop novo.")
        recs = [r for r in recs if r.category in ("ram", "storage")]
    elif sys_media == "HDD":
        verdict = "O Windows num HD mecânico é o maior gargalo deste PC. Comece pelo SSD: é o upgrade mais barato e o que mais se sente."
    elif bottleneck == "gpu":
        verdict = (f"A placa de vídeo é o gargalo: o {cpu.extra.get('model') or 'processador'} aguenta uma placa "
                   f"cerca de {round(cap / max(gpu.index or 20, 1), 1)}× mais forte em {res}p.")
    elif bottleneck == "cpu":
        verdict = f"O processador é o gargalo: ele não consegue alimentar toda a placa de vídeo em {res}p."
    else:
        verdict = "Processador e placa de vídeo estão equilibrados. Qualquer upgrade grande precisa trocar os dois juntos."

    combos = _combos(recs, cpu, gpu, res, sock_key, laptop)
    return UpgradePlan(cpu, gpu, res, hz, bal, bottleneck, verdict, recs, combos, laptop)


def _best_gpu_for(cpu_index: int, res: int, current: int) -> str | None:
    """Placa mais forte à venda que o processador ainda consegue aproveitar."""
    cap = cpu_index * GPU_PER_CPU[res]
    ok = [n for n, _c in BUYABLE_GPUS if current * 1.3 <= GPUS[n][0] <= cap * 1.05]
    return max(ok, key=lambda n: GPUS[n][0]) if ok else None


def _combos(recs, cpu, gpu, res, plat, laptop) -> list[Combo]:
    by = {r.id: r for r in recs}
    combos = []
    cheap = [r for r in recs if r.cost.startswith("$") and len(r.cost.split("–")[0]) == 1]
    if cheap:
        combos.append(Combo("Econômica", [r.buy[0].split(" · ")[0] for r in cheap],
                            "O que custa pouco e já resolve travadas e lentidão."))
    if "gpu" in by:
        g = by["gpu"].buy[min(1, len(by["gpu"].buy) - 1)].split(" · ")[0]
        parts = [g] + [r.buy[0].split(" · ")[0] for r in cheap if r.id != "gpu"][:1]
        combos.append(Combo("Equilibrada", parts, f"Melhor custo-benefício em jogos para o seu processador ({cpu.extra.get('model', '')})."))
    if not laptop and ("cpu" in by or "platform" in by):
        if "cpu" in by:
            c = by["cpu"].buy[0]
            new_idx = CPUS[SAME_SOCKET_BEST[plat][1]][0]
        else:
            c = by["platform"].buy[0]
            new_idx = NEW_PLATFORM[2]
        g = _best_gpu_for(new_idx, res, gpu.index or 20)
        parts = [c] + ([g] if g else []) + ([by["ram"].buy[0]] if "ram" in by and "platform" not in by else [])
        combos.append(Combo("Máxima", parts, "Processador e placa de vídeo fortes juntos, sem um segurar o outro."))
    return combos
