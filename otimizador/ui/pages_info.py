"""Páginas de informação: Painel, Especificações e Diagnóstico."""
from __future__ import annotations

import datetime as dt
from tkinter import filedialog, messagebox

import customtkinter as ctk
import psutil

from ..core import sysinfo, tweaks
from ..core.analyzer import Rec
from ..core.utils import fmt_bytes, fmt_duration, open_url
from . import widgets as W


class Page(ctk.CTkFrame):
    title = ""
    subtitle = ""
    scroll = True

    def __init__(self, master, app):
        super().__init__(master, fg_color=W.BG, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.header = W.PageHeader(self, self.title, self.subtitle)
        self.header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 12))
        if self.scroll:
            self.body = ctk.CTkScrollableFrame(self, fg_color=W.BG, corner_radius=0, scrollbar_button_color=W.BORDER)
        else:
            self.body = ctk.CTkFrame(self, fg_color=W.BG, corner_radius=0)
        self.body.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 12))
        self.body.grid_columnconfigure(0, weight=1)
        self.build()
        app.on_data(self._on_data)

    @property
    def visible(self):
        return self.app.current == self._key()

    def _key(self):
        for k, p in self.app.pages.items():
            if p is self:
                return k
        return None

    def build(self):
        pass

    def on_show(self):
        pass

    def _on_data(self):
        self.refresh()

    def refresh(self):
        pass


# =========================================================================== Painel


class DashboardPage(Page):
    title = "Painel"
    subtitle = "Visão geral da saúde e do uso do seu computador em tempo real."

    def build(self):
        W.button(self.header.actions, "Analisar novamente", self.app.refresh_specs, "secondary", width=160).pack(side="left", padx=6)
        W.button(self.header.actions, "⚡ Otimizar agora", self._one_click, "primary", width=170).pack(side="left")

        b = self.body
        b.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="c")

        # --- Nota + resumo
        score_card = W.Card(b)
        score_card.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.ring = W.ScoreRing(score_card, size=160)
        self.ring.grid(row=0, column=0, pady=(16, 4))
        self.tier_lbl = ctk.CTkLabel(score_card, text="", font=W.font(14, "bold"), text_color=W.TEXT)
        self.tier_lbl.grid(row=1, column=0)
        self.issues_lbl = ctk.CTkLabel(score_card, text="", font=W.font(12), text_color=W.MUTED)
        self.issues_lbl.grid(row=2, column=0, pady=(0, 14))

        self.summary = W.Card(b, "Seu computador")
        self.summary.grid(row=0, column=1, columnspan=3, sticky="nsew", padx=6, pady=6)

        # --- Monitores ao vivo
        self.meters = {}
        for i, (key, label, color) in enumerate([("cpu", "Processador", W.ACCENT), ("ram", "Memória RAM", "#a855f7"),
                                                 ("disk", "Disco (leitura+escrita)", W.GREEN), ("net", "Rede (down+up)", W.YELLOW)]):
            c = W.Card(b)
            c.grid(row=1, column=i, sticky="nsew", padx=6, pady=6)
            ctk.CTkLabel(c, text=label, font=W.font(12), text_color=W.MUTED, anchor="w").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))
            val = ctk.CTkLabel(c, text="—", font=W.font(22, "bold"), text_color=W.TEXT, anchor="w")
            val.grid(row=1, column=0, sticky="w", padx=14)
            sub = ctk.CTkLabel(c, text="", font=W.font(11), text_color=W.MUTED, anchor="w")
            sub.grid(row=2, column=0, sticky="w", padx=14)
            spark = W.Sparkline(c, color=color, height=60)
            spark.grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 12))
            self.meters[key] = (val, sub, spark)

        # --- Problemas + processos
        self.problems = W.Card(b, "Principais pontos de atenção")
        self.problems.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=6, pady=6)
        self.procs = W.Card(b, "Programas usando mais memória")
        self.procs.grid(row=2, column=2, columnspan=2, sticky="nsew", padx=6, pady=6)
        self.proc_frame = ctk.CTkFrame(self.procs, fg_color="transparent")
        self.proc_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.proc_frame.grid_columnconfigure(0, weight=1)

        self._last_disk = psutil.disk_io_counters()
        self._last_net = psutil.net_io_counters()
        psutil.cpu_percent(None)
        self._tick = 0
        self.after(1000, self._live)

    def _one_click(self):
        from .pages_actions import one_click_optimize
        one_click_optimize(self.app)

    def _live(self):
        try:
            cpu = psutil.cpu_percent(None)
            vm = psutil.virtual_memory()
            d = psutil.disk_io_counters()
            n = psutil.net_io_counters()
            dbytes = (d.read_bytes - self._last_disk.read_bytes) + (d.write_bytes - self._last_disk.write_bytes) if d and self._last_disk else 0
            nbytes = (n.bytes_recv - self._last_net.bytes_recv) + (n.bytes_sent - self._last_net.bytes_sent)
            self._last_disk, self._last_net = d, n
            freq = psutil.cpu_freq()
            vals = {
                "cpu": (cpu, f"{cpu:.0f}%", f"{freq.current / 1000:.2f} GHz" if freq else ""),
                "ram": (vm.percent, f"{vm.percent:.0f}%", f"{fmt_bytes(vm.used)} de {fmt_bytes(vm.total)}"),
                "disk": (min(100, dbytes / (200 * 1024**2) * 100), f"{fmt_bytes(dbytes)}/s", "escala: 200 MB/s"),
                "net": (min(100, nbytes / (12.5 * 1024**2) * 100), f"{fmt_bytes(nbytes)}/s", "escala: 100 Mbps"),
            }
            for k, (pct, text, sub) in vals.items():
                val, sublbl, spark = self.meters[k]
                spark.values = spark.values[1:] + [max(0.0, min(100.0, pct))]
                if self.visible:
                    val.configure(text=text)
                    sublbl.configure(text=sub)
                    spark.redraw()
            self._tick += 1
            if self.visible and self._tick % 3 == 1:
                self.app.run_bg(_top_processes, self._show_procs)
        finally:
            self.after(1000, self._live)

    def _show_procs(self, procs):
        W.clear(self.proc_frame)
        total = psutil.virtual_memory().total
        for i, (name, rss, count) in enumerate(procs):
            label = f"{name}" + (f"  ×{count}" if count > 1 else "")
            ctk.CTkLabel(self.proc_frame, text=label, font=W.font(12), text_color=W.TEXT, anchor="w").grid(row=i * 2, column=0, sticky="w")
            ctk.CTkLabel(self.proc_frame, text=fmt_bytes(rss), font=W.font(12, "bold"), text_color=W.MUTED).grid(row=i * 2, column=1, sticky="e")
            bar = ctk.CTkProgressBar(self.proc_frame, height=5, progress_color="#a855f7", fg_color=W.BORDER)
            bar.set(min(1, rss / total * 4))
            bar.grid(row=i * 2 + 1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

    def refresh(self):
        a, s = self.app.analysis, self.app.specs
        if not a or not s:
            return
        self.ring.set(a.score)
        self.tier_lbl.configure(text=f"Categoria: {a.tier}")
        serious = sum(1 for r in a.recs if r.severity in ("crítico", "alto"))
        self.issues_lbl.configure(text=f"{len(a.recs)} sugestões · {serious} importantes")

        for w in self.summary.winfo_children()[1:]:
            w.destroy()
        cpu = (s.get("cpu") or [{}])[0]
        g = sysinfo.main_gpu(s) or {}
        sys_disk = next((d for d in s.get("disks", []) if d.get("system")), {})
        vol_c = next((v for v in s.get("volumes", []) if v.get("letter") == "C"), {})
        o = s.get("os") or {}
        mods = s.get("mem", [])
        mem_txt = fmt_bytes(s.get("ram_total"))
        if mods:
            mem_txt += f" {mods[0].get('type_name')} @ {mods[0].get('configured')} MHz · {len(mods)} pente(s)"
        rows = [
            ("Processador", f"{cpu.get('name')} ({cpu.get('cores')}C/{cpu.get('threads')}T)"),
            ("Placa de vídeo", f"{g.get('name', '—')} · {fmt_bytes(g.get('vram'))}"),
            ("Memória", mem_txt),
            ("Disco do sistema", f"{sys_disk.get('name', '—')} ({sys_disk.get('media', '?')} {sys_disk.get('bus', '')}) · "
                                 f"{fmt_bytes(vol_c.get('free'))} livres"),
            ("Windows", f"{o.get('caption', '')} {o.get('display') or ''} (build {o.get('build')})"),
            ("Ligado há", fmt_duration(s.get("uptime_s") or 0)),
        ]
        W.kv_rows(self.summary, rows, start_row=1)

        for w in self.problems.winfo_children()[1:]:
            w.destroy()
        top = [r for r in a.recs if r.severity != "info"][:5]
        fr = ctk.CTkFrame(self.problems, fg_color="transparent")
        fr.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        fr.grid_columnconfigure(1, weight=1)
        if not top:
            ctk.CTkLabel(fr, text="✓ Nenhum problema importante encontrado!", text_color=W.GREEN, font=W.font(13, "bold")).grid(row=0, column=0, sticky="w")
        for i, r in enumerate(top):
            W.Badge(fr, r.severity.upper(), W.SEVERITY_COLORS[r.severity]).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            ctk.CTkLabel(fr, text=r.title, font=W.font(12), text_color=W.TEXT, anchor="w").grid(row=i, column=1, sticky="w")
        W.button(fr, "Ver diagnóstico completo →", lambda: self.app.show("diagnostico"), "secondary", width=200).grid(
            row=len(top) + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))


def _top_processes(n=7):
    agg: dict[str, list] = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            name = p.info["name"] or "?"
            mi = p.info["memory_info"]
            if not mi:
                continue
            a = agg.setdefault(name, [0, 0])
            a[0] += mi.rss
            a[1] += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    agg.pop("System Idle Process", None)
    agg.pop("Memory Compression", None)
    items = sorted(((k, v[0], v[1]) for k, v in agg.items()), key=lambda x: -x[1])
    return items[:n]


# =========================================================================== Especificações


class SpecsPage(Page):
    title = "Especificações"
    subtitle = "Tudo sobre o hardware e o software do seu PC."

    def build(self):
        W.button(self.header.actions, "Copiar", self._copy, "secondary", width=100).pack(side="left", padx=6)
        W.button(self.header.actions, "Exportar relatório", self._export, "primary", width=160).pack(side="left")
        self.body.grid_columnconfigure((0, 1), weight=1, uniform="s")
        self.placeholder = ctk.CTkLabel(self.body, text="Coletando informações do sistema…", text_color=W.MUTED, font=W.font(14))
        self.placeholder.grid(row=0, column=0, columnspan=2, pady=60)

    def _copy(self):
        if self.app.specs:
            self.clipboard_clear()
            self.clipboard_append(sysinfo.report_text(self.app.specs))
            self.app.set_status("Especificações copiadas para a área de transferência.")

    def _export(self):
        if not self.app.specs:
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=f"specs-{dt.date.today()}.txt",
                                            filetypes=[("Texto", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(sysinfo.report_text(self.app.specs))
            self.app.set_status(f"Relatório salvo em {path}")

    def refresh(self):
        s = self.app.specs
        if not s:
            return
        W.clear(self.body)
        cards = []
        o = s.get("os") or {}
        sysi = s.get("system") or {}
        cards.append(("Sistema operacional", [
            ("Windows", f"{o.get('caption')}"), ("Versão", f"{o.get('display') or ''} — build {o.get('build')}.{o.get('ubr')}"),
            ("Arquitetura", o.get("arch")), ("Instalado em", (o.get("install") or "")[:10]),
            ("Último boot", (o.get("boot") or "").replace("T", " ")), ("Ligado há", fmt_duration(s.get("uptime_s") or 0)),
            ("Nome do PC", sysi.get("name")), ("Tipo", sysi.get("type_name")),
        ]))
        for c in s.get("cpu", []):
            cards.append(("Processador", [
                ("Modelo", c.get("name")), ("Núcleos / Threads", f"{c.get('cores')} / {c.get('threads')}"),
                ("Clock base", f"{(c.get('max_mhz') or 0) / 1000:.2f} GHz"),
                ("Clock atual", f"{(s.get('cpu_freq_now') or 0) / 1000:.2f} GHz"),
                ("Cache L2 / L3", f"{fmt_bytes((c.get('l2_kb') or 0) * 1024)} / {fmt_bytes((c.get('l3_kb') or 0) * 1024)}"),
                ("Soquete", c.get("socket")), ("Virtualização", "Ativada" if c.get("virtualization") else "Desativada/indisponível"),
            ]))
        gpu_rows = []
        for g in s.get("gpu", []):
            kind = "Integrada" if sysinfo.is_integrated_gpu(g) else "Dedicada"
            gpu_rows += [(g.get("name"), f"{kind} · {fmt_bytes(g.get('vram'))} VRAM"),
                         ("   Driver", f"{g.get('driver')} ({g.get('driver_date')})"),
                         ("   Tela", f"{g.get('res_w')}x{g.get('res_h')} @ {g.get('hz')} Hz" if g.get("res_w") else "sem monitor ativo")]
        cards.append(("Placas de vídeo", gpu_rows))
        mods = s.get("mem", [])
        mem_rows = [("Total", fmt_bytes(s.get("ram_total"))), ("Em uso agora", f"{s.get('ram_used_pct', 0):.0f}%"),
                    ("Slots", f"{len(mods)} de {s.get('mem_slots') or '?'} ocupados"),
                    ("Canal", "Dual/Multi-channel" if len(mods) >= 2 else "Single-channel")]
        for m in mods:
            mem_rows.append((m.get("bank") or m.get("slot") or "Pente", f"{fmt_bytes(m.get('capacity'))} {m.get('type_name')} {m.get('configured')} MHz "
                                                       f"(nominal {m.get('speed')}) · {m.get('manufacturer')} {m.get('part')}"))
        pf = s.get("pagefile") or {}
        mem_rows.append(("Arquivo de paginação", f"{fmt_bytes(pf.get('total'))} ({'automático' if pf.get('auto') else 'manual'})"))
        cards.append(("Memória RAM", mem_rows))
        board = s.get("board") or {}
        bios = s.get("bios") or {}
        vbs = s.get("vbs") or {}
        cards.append(("Placa-mãe e segurança", [
            ("Fabricante", board.get("manufacturer")), ("Modelo", board.get("product")),
            ("BIOS", f"{bios.get('vendor')} {bios.get('version')} ({bios.get('date')})"),
            ("Secure Boot", {True: "Ativado", False: "Desativado"}.get(s.get("secure_boot"), "—")),
            ("TPM", {True: "Presente", False: "Ausente"}.get(s.get("tpm"), "—")),
            ("Integridade de memória (VBS)", "Ativa" if vbs.get("status") == 2 and 2 in (vbs.get("running") or []) else "Inativa"),
        ]))
        cards.append(("Rede e monitores", [(n.get("name"), f"{n.get('desc')} — {n.get('speed')}") for n in s.get("net", [])]
                      + [("Monitor", m.get("name")) for m in s.get("monitors", []) if m.get("name")]))
        win = s.get("win") or {}
        bat = s.get("battery") or []
        energy = [("Plano de energia", (s.get("power_plan") or {}).get("name")),
                  ("Hibernação", "Ativa" if win.get("hibernation") else "Desativada"),
                  ("Inicialização rápida", "Ativa" if win.get("fast_startup") else "Desativada"),
                  ("TRIM (SSD)", {True: "Ativo", False: "DESATIVADO", None: "—"}[s.get("trim")]),
                  ("Modo de Jogo", "Ativo" if win.get("game_mode") else "Desativado"),
                  ("HAGS", "Ativo" if win.get("hags") == 2 else "Desativado/padrão")]
        for b in bat:
            energy.append(("Bateria", f"{b.get('name')} — {b.get('charge')}%"))
        cards.append(("Energia e Windows", energy))

        for i, (title, rows) in enumerate(cards):
            c = W.Card(self.body, title)
            c.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            W.kv_rows(c, rows, start_row=1)

        # Armazenamento ocupa a largura toda
        st = W.Card(self.body, "Armazenamento")
        st.grid(row=len(cards) // 2 + 1, column=0, columnspan=2, sticky="nsew", padx=6, pady=6)
        fr = ctk.CTkFrame(st, fg_color="transparent")
        fr.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        fr.grid_columnconfigure(0, weight=1)
        for i, d in enumerate(s.get("disks", [])):
            extra = []
            if d.get("temp"):
                extra.append(f"{d['temp']} °C")
            if d.get("wear") is not None:
                extra.append(f"desgaste {d['wear']}%")
            if d.get("hours"):
                extra.append(f"{d['hours']} h ligado")
            health_ok = (d.get("health") or "").lower() == "healthy"
            line = ctk.CTkFrame(fr, fg_color="transparent")
            line.grid(row=i, column=0, sticky="ew", pady=3)
            W.Badge(line, d.get("media") or "?", W.ACCENT if d.get("media") == "SSD" else W.GRAY).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(line, text=f"{d.get('name')} · {d.get('bus')} · {fmt_bytes(d.get('size'))}"
                                    + (" · DISCO DO SISTEMA" if d.get("system") else "") + (" · " + ", ".join(extra) if extra else ""),
                         font=W.font(12), text_color=W.TEXT).pack(side="left")
            W.Badge(line, "Saudável" if health_ok else d.get("health") or "?", W.GREEN if health_ok else W.RED).pack(side="right")
        vf = ctk.CTkFrame(st, fg_color="transparent")
        vf.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 16))
        vf.grid_columnconfigure((0, 1), weight=1, uniform="v")
        for i, v in enumerate(s.get("volumes", [])):
            used = 1 - (v["free"] / v["size"]) if v.get("size") else 0
            W.UsageBar(vf, f"{v['letter']}:  {v.get('label') or ''}", used,
                       f"{fmt_bytes(v['free'])} livres de {fmt_bytes(v['size'])}").grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(self.body, text=f"Coletado em {s.get('collected_at', '').replace('T', ' ')} "
                                     f"({s.get('collect_seconds')} s){'' if s.get('admin') else ' · rode como administrador para ver temperatura e desgaste dos discos'}",
                     font=W.font(11), text_color=W.MUTED).grid(row=len(cards) // 2 + 2, column=0, columnspan=2, pady=8)


# =========================================================================== Diagnóstico


class DiagnosisPage(Page):
    title = "Diagnóstico"
    subtitle = "Análise do seu PC com recomendações priorizadas — do que mais impacta para o que menos impacta."

    def build(self):
        W.button(self.header.actions, "Analisar novamente", self.app.refresh_specs, "secondary", width=160).pack(side="left")
        self.top = W.Card(self.body)
        self.top.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.list = ctk.CTkFrame(self.body, fg_color="transparent")
        self.list.grid(row=1, column=0, sticky="ew")
        self.list.grid_columnconfigure(0, weight=1)

    def refresh(self):
        a = self.app.analysis
        if not a:
            return
        W.clear(self.top)
        self.top.grid_columnconfigure(0, weight=0)
        self.top.grid_columnconfigure(1, weight=1)
        ring = W.ScoreRing(self.top, size=130)
        ring.set(a.score, "Nota")
        ring.grid(row=0, column=0, rowspan=4, padx=16, pady=14)
        ctk.CTkLabel(self.top, text=f"Categoria do PC: {a.tier}", font=W.font(17, "bold"), text_color=W.TEXT, anchor="w").grid(
            row=0, column=1, sticky="sw", pady=(18, 0))
        ctk.CTkLabel(self.top, text=a.tier_detail, font=W.font(12), text_color=W.MUTED, anchor="w", wraplength=700, justify="left").grid(
            row=1, column=1, sticky="w")
        prof = tweaks.PROFILES[a.profile]
        ctk.CTkLabel(self.top, text=f"Melhor opção para você: perfil “{prof}”", font=W.font(14, "bold"), text_color=W.ACCENT,
                     anchor="w").grid(row=2, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(self.top, text=a.profile_reason, font=W.font(12), text_color=W.MUTED, anchor="w", wraplength=700, justify="left").grid(
            row=3, column=1, sticky="nw", pady=(0, 14))
        W.button(self.top, "Ver perfil recomendado →", self._go_profile, "primary", width=210).grid(row=0, column=2, rowspan=4, padx=18)

        W.clear(self.list)
        if not a.recs:
            ctk.CTkLabel(self.list, text="✓ Seu PC está em ótima forma! Nenhum problema encontrado.", font=W.font(15, "bold"),
                         text_color=W.GREEN).grid(row=0, column=0, pady=40)
        for i, r in enumerate(a.recs):
            self._rec_card(r).grid(row=i, column=0, sticky="ew", padx=6, pady=5)

    def _go_profile(self):
        self.app.pages["otimizacoes"].select_profile(self.app.analysis.profile)
        self.app.show("otimizacoes")

    def _rec_card(self, r: Rec):
        color = W.SEVERITY_COLORS[r.severity]
        c = W.Card(self.list)
        c.grid_columnconfigure(0, weight=0)
        c.grid_columnconfigure(1, weight=1)
        strip = ctk.CTkFrame(c, fg_color=color, width=5, height=10, corner_radius=3)
        strip.grid(row=0, column=0, rowspan=3, sticky="ns", padx=(8, 0), pady=10)
        head = ctk.CTkFrame(c, fg_color="transparent")
        head.grid(row=0, column=1, sticky="ew", padx=14, pady=(12, 2))
        W.Badge(head, r.severity.upper(), color).pack(side="left")
        ctk.CTkLabel(head, text=r.area, font=W.font(11), text_color=W.MUTED).pack(side="left", padx=8)
        ctk.CTkLabel(c, text=r.title, font=W.font(14, "bold"), text_color=W.TEXT, anchor="w", justify="left", wraplength=780).grid(
            row=1, column=1, sticky="w", padx=14)
        ctk.CTkLabel(c, text=r.detail, font=W.font(12), text_color=W.MUTED, anchor="w", justify="left", wraplength=780).grid(
            row=2, column=1, sticky="w", padx=14, pady=(2, 12))
        action = None
        if r.tweaks:
            pending = [tweaks.TWEAKS_BY_ID[t] for t in r.tweaks if not tweaks.TWEAKS_BY_ID[t].is_applied()]
            if pending:
                action = lambda: self._fix(r, pending)  # noqa: E731
        elif r.page:
            action = lambda: self.app.show(r.page)  # noqa: E731
        elif r.url:
            action = lambda: open_url(r.url)  # noqa: E731
        if action:
            kind = "danger" if any(tweaks.TWEAKS_BY_ID[t].risk == "alto" for t in r.tweaks) else "secondary"
            W.button(c, r.action_label, action, kind, width=150).grid(row=0, column=2, rowspan=3, padx=16)
        return c

    def _fix(self, r: Rec, pending):
        from .pages_actions import apply_tweaks_flow
        risky = [t for t in pending if t.risk != "baixo"]
        msg = "Aplicar:\n\n" + "\n".join(f"• {t.name}" for t in pending)
        if risky:
            msg += "\n\nATENÇÃO:\n" + "\n".join(f"• {t.description}" for t in risky)
        if not messagebox.askyesno("Corrigir", msg + "\n\nTudo é salvo em backup e pode ser desfeito. Continuar?"):
            return
        apply_tweaks_flow(self.app, pending, restore_point=False)
