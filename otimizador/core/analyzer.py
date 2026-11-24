"""Motor de diagnóstico: transforma as specs em recomendações priorizadas."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .sysinfo import gpu_vendor, is_integrated_gpu, main_gpu
from .tweaks import HIGH_PERF, TWEAKS_BY_ID
from .utils import fmt_bytes

SEVERITY_ORDER = {"crítico": 0, "alto": 1, "médio": 2, "baixo": 3, "info": 4, "ok": 5}
SEVERITY_PENALTY = {"crítico": 18, "alto": 10, "médio": 5, "baixo": 2, "info": 0, "ok": 0}

DRIVER_URLS = {
    "nvidia": "https://www.nvidia.com/pt-br/software/nvidia-app/",
    "amd": "https://www.amd.com/pt/support/download/drivers.html",
    "intel": "https://www.intel.com.br/content/www/br/pt/support/detect.html",
}


@dataclass
class Rec:
    id: str
    title: str
    detail: str
    severity: str  # crítico | alto | médio | baixo | info | ok
    area: str  # Hardware | Windows | Jogos | Armazenamento | Manutenção
    tweaks: list[str] = field(default_factory=list)  # ids de otimizações que resolvem
    page: str | None = None  # página do app que resolve (limpeza, inicializacao, ferramentas)
    url: str | None = None
    action_label: str = "Corrigir"


@dataclass
class Analysis:
    recs: list[Rec]
    score: int
    tier: str
    tier_detail: str
    profile: str
    profile_reason: str


def _link_mbps(speed: str | None) -> float | None:
    import re

    m = re.match(r"([\d.,]+)\s*([GMK])bps", speed or "", re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v * {"G": 1000, "M": 1, "K": 0.001}[m.group(2).upper()]


def _ram_gb(data) -> float:
    return (data.get("ram_total") or 0) / 1024**3


def classify(data: dict) -> tuple[str, str]:
    """Classifica o PC em Entrada / Intermediário / Alto desempenho."""
    cpu = (data.get("cpu") or [{}])[0]
    threads = cpu.get("threads") or 0
    ram = _ram_gb(data)
    g = main_gpu(data) or {}
    vram = (g.get("vram") or 0) / 1024**3
    dedicated = bool(g) and not is_integrated_gpu(g)
    sys_disk = next((d for d in data.get("disks", []) if d.get("system")), {})
    ssd = sys_disk.get("media") == "SSD"

    pts = 0
    pts += 2 if threads >= 12 else 1 if threads >= 6 else 0
    pts += 2 if ram >= 15 else 1 if ram >= 7.5 else 0
    pts += (2 if vram >= 7.5 else 1 if vram >= 3.5 else 0) if dedicated else 0
    pts += 1 if ssd else 0
    if pts >= 6:
        return "Alto desempenho", "Hardware forte: o foco é latência, estabilidade e manter o sistema limpo."
    if pts >= 3:
        return "Intermediário", "Bom equilíbrio: otimizações de jogos e segundo plano trazem ganhos perceptíveis."
    return "Entrada", "Hardware modesto: reduzir processos, efeitos visuais e consumo de RAM faz grande diferença."


def analyze(data: dict, extra: dict | None = None) -> Analysis:
    extra = extra or {}
    recs: list[Rec] = []
    add = recs.append
    win = data.get("win") or {}
    laptop = data.get("is_laptop")
    ram = _ram_gb(data)
    cpu = (data.get("cpu") or [{}])[0]

    # ------------------------------------------------ armazenamento
    sys_disk = next((d for d in data.get("disks", []) if d.get("system")), None)
    if sys_disk and sys_disk.get("media") == "HDD":
        add(Rec("hdd_system", "Windows instalado em HD mecânico",
                f"O disco do sistema ({sys_disk['name']}) é um HDD. Trocar por um SSD é, de longe, a melhor melhoria possível: "
                "o Windows inicia 3–5x mais rápido e os programas abrem quase instantaneamente. Um SSD SATA ou NVMe de 500 GB é barato.",
                "crítico", "Hardware", tweaks=["search_index_off"], action_label="Reduzir uso do HD"))
    elif sys_disk and sys_disk.get("media") == "SSD" and sys_disk.get("bus") == "SATA":
        nvme_present = any(d.get("bus") == "NVMe" for d in data.get("disks", []))
        if nvme_present:
            add(Rec("sata_system", "Windows está no SSD SATA, mas você tem um NVMe",
                    "Há um SSD NVMe mais rápido no PC. Instalar o Windows e os jogos principais no NVMe deixa carregamentos mais rápidos.",
                    "baixo", "Hardware"))
    for d in data.get("disks", []):
        h = (d.get("health") or "").lower()
        if h and h not in ("healthy", "saudável"):
            add(Rec(f"disk_health_{d.get('number')}", f"Disco com problema de saúde: {d.get('name')}",
                    f"O Windows reporta o estado '{d.get('health')}'. FAÇA BACKUP dos seus arquivos agora e planeje a troca do disco.",
                    "crítico", "Armazenamento"))
        if d.get("wear") is not None and d["wear"] >= 80:
            add(Rec(f"disk_wear_{d.get('number')}", f"SSD com desgaste alto: {d.get('name')} ({d['wear']}%)",
                    "O SSD está perto do fim da vida útil estimada. Mantenha backup e planeje a substituição.", "alto", "Armazenamento"))
        if d.get("temp") and d["temp"] >= 65:
            add(Rec(f"disk_temp_{d.get('number')}", f"Disco quente: {d.get('name')} ({d['temp']} °C)",
                    "Temperaturas acima de 65 °C causam perda de desempenho (throttling). Melhore o fluxo de ar ou use um dissipador no NVMe.",
                    "médio", "Armazenamento"))
    for v in data.get("volumes", []):
        if not v.get("size"):
            continue
        free_pct = v["free"] / v["size"] * 100
        is_sys = v.get("letter", "").upper() == "C"
        if free_pct < 10 or (is_sys and v["free"] < 15 * 1024**3):
            add(Rec(f"vol_full_{v['letter']}", f"Unidade {v['letter']}: quase cheia ({free_pct:.0f}% livre)",
                    f"Restam {fmt_bytes(v['free'])}. Com pouco espaço o Windows fica lento, atualizações falham e SSDs perdem velocidade. "
                    "Use a Limpeza e remova jogos/programas que não usa.",
                    "alto" if is_sys else "médio", "Armazenamento", page="limpeza", action_label="Abrir limpeza"))
        elif free_pct < 20 and is_sys:
            add(Rec("vol_low_C", f"Unidade C: com pouco espaço ({free_pct:.0f}% livre)",
                    "Mantenha pelo menos 15–20% livre no disco do sistema para o melhor desempenho.",
                    "baixo", "Armazenamento", page="limpeza", action_label="Abrir limpeza"))
    if data.get("trim") is False:
        add(Rec("trim", "TRIM desativado", "Sem TRIM, os SSDs ficam mais lentos com o tempo.", "alto", "Armazenamento", tweaks=["trim_on"]))

    # ------------------------------------------------ memória
    mods = data.get("mem", [])
    if ram and ram < 7.5:
        add(Rec("ram_low", f"Pouca memória RAM ({ram:.0f} GB)",
                "Com menos de 8 GB o Windows usa o disco como memória o tempo todo e tudo fica lento. 16 GB é o recomendado hoje (32 GB para jogos pesados).",
                "crítico", "Hardware"))
    elif ram and ram < 15:
        add(Rec("ram_mid", f"Memória RAM limitada para jogos ({ram:.0f} GB)",
                "8 GB funcionam para uso básico, mas jogos atuais + navegador + Discord passam disso. Considere 16 GB em dual-channel.",
                "médio", "Hardware"))
    slots = data.get("mem_slots") or 0
    if len(mods) == 1 and slots >= 2:
        add(Rec("single_channel", "Memória em single-channel (só 1 pente)",
                "Com um único pente a memória trabalha com metade da largura de banda. Adicionar um segundo pente IGUAL ativa o dual-channel: "
                "ganhos de 10–30% em jogos e muito mais em GPUs integradas.",
                "alto", "Hardware"))
    if mods:
        m = mods[0]
        mtype, conf = m.get("type_name"), m.get("configured") or 0
        if (mtype == "DDR4" and 0 < conf <= 2400) or (mtype == "DDR5" and 0 < conf <= 4800):
            add(Rec("xmp", f"Memória rodando a {conf} MHz (XMP/EXPO provavelmente desligado)",
                    f"Memórias {mtype} quase sempre suportam velocidades maiores pelo perfil XMP (Intel) ou EXPO/DOCP (AMD). "
                    "Ative na BIOS (seção AI Tweaker / Extreme Tweaker / OC) — ganho grátis de 5–15% em jogos.",
                    "alto" if not laptop else "info", "Hardware"))
    if (data.get("ram_used_pct") or 0) >= 85:
        add(Rec("ram_pressure", f"RAM quase esgotada agora ({data['ram_used_pct']:.0f}% em uso)",
                "Feche programas pesados (navegador com muitas abas costuma ser o vilão) e revise os programas de inicialização.",
                "alto", "Windows", page="inicializacao", action_label="Ver inicialização"))
    pf = data.get("pagefile") or {}
    if pf.get("total") == 0:
        add(Rec("no_pagefile", "Arquivo de paginação desativado",
                "Sem arquivo de paginação, jogos e programas podem fechar sozinhos ao faltar memória. Deixe 'Gerenciado pelo sistema'.",
                "alto", "Windows"))

    # ------------------------------------------------ GPU / drivers / tela
    g = main_gpu(data)
    if g:
        vendor = gpu_vendor(g["name"])
        if g.get("driver_date"):
            try:
                age = (dt.date.today() - dt.date.fromisoformat(g["driver_date"])).days
            except ValueError:
                age = 0
            if age > 180:
                add(Rec("gpu_driver_old", f"Driver de vídeo desatualizado ({age // 30} meses)",
                        f"O driver da {g['name']} é de {g['driver_date']}. Drivers novos trazem otimizações específicas para jogos e correções de bugs.",
                        "alto" if age > 365 else "médio", "Hardware", url=DRIVER_URLS.get(vendor), action_label="Baixar driver"))
        if "microsoft basic" in g["name"].lower():
            add(Rec("gpu_basic", "Sem driver de vídeo instalado",
                    "O Windows está usando o 'Adaptador de Vídeo Básico'. Instale o driver do fabricante — a diferença é enorme.",
                    "crítico", "Hardware"))
        if not is_integrated_gpu(g) and (g.get("hz") or 0) and g.get("hz") <= 60:
            add(Rec("refresh_60", "Monitor a 60 Hz na placa de vídeo dedicada",
                    "Se seu monitor suporta 75/144/165 Hz, ative em Configurações > Sistema > Tela > Tela avançada > Taxa de atualização. "
                    "Confira também se o cabo está ligado na placa de vídeo (e não na placa-mãe).",
                    "info", "Hardware", url="ms-settings:display-advanced", action_label="Abrir configurações"))
        hags = win.get("hags")
        if not is_integrated_gpu(g) and hags != 2:
            add(Rec("hags", "Agendamento de GPU por hardware (HAGS) desligado",
                    "Pode reduzir a latência e é necessário para DLSS Frame Generation. Teste nos seus jogos.",
                    "baixo", "Jogos", tweaks=["hags_on"]))
    integrated_only = g is None or is_integrated_gpu(g)
    if g and not integrated_only:
        for ig in data.get("gpu", []):
            if ig is not g and is_integrated_gpu(ig) and ig.get("res_w") and "basic" not in ig["name"].lower():
                add(Rec("monitor_igpu", f"Um monitor está ligado na placa-mãe ({ig['name']})",
                        f"Um monitor ({ig.get('res_w')}x{ig.get('res_h')} @ {ig.get('hz')} Hz) está usando o vídeo integrado. "
                        f"Tudo bem para um monitor secundário, mas jogue sempre no monitor ligado à {g['name']}. "
                        "Se ele for o principal, mude o cabo para a placa de vídeo.",
                        "info", "Hardware"))
                break

    # ------------------------------------------------ energia
    plan = data.get("power_plan") or {}
    pname = (plan.get("name") or "").lower()
    high_like = plan.get("guid") == HIGH_PERF or any(k in pname for k in ("alto", "high", "máximo", "maximo", "ultimate", "desempenho"))
    if not laptop and not high_like:
        add(Rec("power_plan", f"Plano de energia '{plan.get('name')}'",
                "Em desktop, o plano Alto desempenho mantém o processador pronto, reduzindo travadinhas sem impacto relevante na conta de luz.",
                "médio", "Windows", tweaks=["power_high"]))
    elif laptop and not high_like:
        add(Rec("power_plan_laptop", "Notebook: use 'Melhor desempenho' na tomada",
                "Ao jogar com o notebook ligado na tomada, mude o modo de energia para 'Melhor desempenho' (ou Alto desempenho). Na bateria, mantenha Equilibrado.",
                "baixo", "Windows", tweaks=["power_high"], action_label="Ativar Alto desempenho"))
    if not laptop and win.get("hibernation") == 1:
        add(Rec("hibernation", "Hibernação ativa em desktop",
                f"O arquivo de hibernação ocupa cerca de {fmt_bytes((data.get('ram_total') or 0) * 0.4)} no disco do sistema. Em desktops raramente é usado.",
                "baixo", "Armazenamento", tweaks=["hibernation_off"]))

    # ------------------------------------------------ jogos
    if win.get("game_dvr") == 1:
        add(Rec("game_dvr", "Gravação em segundo plano (Game DVR) ligada",
                "Grava sua tela continuamente durante jogos, custando FPS e disco.", "médio", "Jogos", tweaks=["game_dvr_off"]))
    if win.get("game_mode") == 0:
        add(Rec("game_mode", "Modo de Jogo desativado", "O Modo de Jogo evita interrupções do Windows Update durante partidas.",
                "baixo", "Jogos", tweaks=["game_mode"]))
    if str(win.get("mouse_accel")) == "1":
        add(Rec("mouse_accel", "Aceleração do mouse ligada",
                "Para jogos de tiro, a aceleração atrapalha a memória muscular. Desligue para movimento 1:1.", "baixo", "Jogos", tweaks=["mouse_accel_off"]))
    vbs = data.get("vbs") or {}
    if vbs.get("status") == 2 and 2 in (vbs.get("running") or []) and not integrated_only:
        add(Rec("vbs", "Integridade de Memória (VBS/HVCI) ativa",
                "Protege o kernel contra malware, mas pode custar 5–15% de FPS em alguns jogos. Só desative se o PC é focado em jogos "
                "e você não baixa arquivos suspeitos. Escolha consciente — não é uma correção obrigatória.",
                "info", "Jogos", tweaks=["vbs_off"], action_label="Desativar (risco)"))

    # ------------------------------------------------ Windows / manutenção
    if win.get("diagtrack_start") in (2, 3):
        add(Rec("telemetry", "Telemetria do Windows ativa",
                "O serviço DiagTrack coleta e envia dados de uso em segundo plano.", "baixo", "Windows", tweaks=["telemetry_off"]))
    if win.get("visual_fx") in (0, 1) and (ram < 7.5 or integrated_only and (cpu.get("threads") or 0) <= 4):
        add(Rec("visual_fx", "Efeitos visuais completos em PC modesto",
                "Animações e transparências pesam em PCs com pouca RAM/GPU integrada. Desligá-los deixa o Windows bem mais ágil.",
                "médio", "Windows", tweaks=["visual_perf", "transparency_off"]))
    if sys_disk and sys_disk.get("media") == "HDD" and win.get("sysmain_start") in (2, None) and ram < 7.5:
        add(Rec("sysmain_hdd", "SysMain em HD com pouca RAM",
                "Se o disco vive em 100%, desativar o SysMain costuma aliviar.", "baixo", "Windows", tweaks=["sysmain_off"]))
    uptime_days = (data.get("uptime_s") or 0) / 86400
    if uptime_days >= 7:
        add(Rec("uptime", f"PC ligado há {uptime_days:.0f} dias sem reiniciar",
                "A Inicialização Rápida faz o 'Desligar' não limpar a memória de verdade. Reinicie para aplicar atualizações e liberar recursos.",
                "baixo", "Manutenção"))
    n_startup = extra.get("startup_enabled")
    if n_startup is not None and n_startup >= 8:
        add(Rec("startup_many", f"{n_startup} programas abrindo com o Windows",
                "Cada programa na inicialização atrasa o boot e consome RAM o tempo todo. Desative o que não precisa abrir sozinho.",
                "médio" if n_startup < 15 else "alto", "Windows", page="inicializacao", action_label="Gerenciar"))
    junk = extra.get("junk_bytes")
    if junk and junk >= 1024**3:
        add(Rec("junk", f"{fmt_bytes(junk)} de arquivos temporários/lixo",
                "Arquivos temporários, caches e lixeira podem ser removidos com segurança.",
                "médio" if junk < 10 * 1024**3 else "alto", "Manutenção", page="limpeza", action_label="Limpar"))
    build = int((data.get("os") or {}).get("build") or 0)
    if build and build < 22631:
        add(Rec("old_build", f"Windows desatualizado (build {build})",
                "Versões antigas não recebem melhorias de desempenho do agendador e correções de segurança. Atualize pelo Windows Update.",
                "médio", "Manutenção", url="ms-settings:windowsupdate", action_label="Windows Update"))
    for n in data.get("net", []):
        media = (n.get("media") or "").lower()
        desc = (n.get("desc") or "").lower()
        mbps = _link_mbps(n.get("speed"))
        wired = "802.3" in media or "ethernet" in desc or "gbe" in desc
        if wired and mbps and mbps < 1000:
            adapter_gig = any(k in desc for k in ("gbe", "gigabit", "2.5g", "5g", "10g", "1g")) or "gaming" in desc
            add(Rec(f"link_{n.get('name')}", f"Cabo de rede conectado a apenas {n.get('speed')}",
                    f"O adaptador {n.get('desc')} suporta {'1 Gbps ou mais' if adapter_gig else 'velocidades maiores'}, "
                    f"mas a conexão negociou só {n.get('speed')}. Causas comuns: cabo velho/danificado (Cat5 com fios rompidos), "
                    "conector mal encaixado ou porta do roteador limitada. Troque por um cabo Cat5e/Cat6 — "
                    "se sua internet passa de 100 Mega, você está perdendo velocidade.",
                    "médio", "Hardware"))
        if not laptop and ("802.11" in media or "wireless" in media or "wi-fi" in (n.get("desc") or "").lower()):
            add(Rec("wifi_desktop", "Desktop conectado por Wi-Fi",
                    "Para jogos online, cabo de rede elimina picos de ping e perda de pacotes causados por interferência.",
                    "baixo", "Hardware"))
            break
    bios = data.get("bios") or {}
    if bios.get("date"):
        try:
            bios_age = (dt.date.today() - dt.date.fromisoformat(bios["date"])).days
            if bios_age > 3 * 365:
                add(Rec("bios_old", f"BIOS antiga ({bios['date']})",
                        "Atualizações de BIOS trazem correções de estabilidade, compatibilidade de memória e microcódigo do processador. "
                        "Atualize com cuidado seguindo o site do fabricante da placa-mãe.", "info", "Hardware"))
        except ValueError:
            pass

    recs.sort(key=lambda r: SEVERITY_ORDER.get(r.severity, 9))
    # Remove referências a otimizações já aplicadas (resolvidas)
    for r in recs:
        r.tweaks = [t for t in r.tweaks if t in TWEAKS_BY_ID]

    score = max(5, 100 - sum(SEVERITY_PENALTY.get(r.severity, 0) for r in recs))
    tier, tier_detail = classify(data)

    if laptop:
        profile, reason = "notebook", "Notebook detectado: otimizações que melhoram a fluidez sem acabar com a bateria."
    elif integrated_only or tier == "Entrada":
        profile, reason = "maximo", "PC modesto: vale aplicar tudo que reduz processos e efeitos visuais."
    elif tier in ("Alto desempenho", "Intermediário"):
        profile, reason = "gamer", "Desktop com placa de vídeo dedicada: foco em FPS estável e baixa latência."
    else:
        profile, reason = "seguro", "Conjunto seguro de melhorias para qualquer PC."
    return Analysis(recs, score, tier, tier_detail, profile, reason)
