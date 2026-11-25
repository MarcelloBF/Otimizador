"""Página Desempenho: teste antes/depois das otimizações."""
from __future__ import annotations

import datetime as dt
from tkinter import messagebox

import customtkinter as ctk

from ..core import benchmark as B
from ..core import tweaks
from ..core.utils import APP_NAME
from . import widgets as W
from .pages_info import Page

LABELS = ["Antes de otimizar", "Depois de otimizar", "Outro"]


def _fmt(m: B.Metric, v) -> str:
    if v is None:
        return "—"
    if m.unit == "ms":
        return f"{v:.2f} ms"
    if m.unit == "IOPS":
        return f"{v:,.0f} IOPS".replace(",", ".")
    if m.unit == "GB/s":
        return f"{v:.1f} GB/s"
    return f"{v:,.0f} MB/s".replace(",", ".") if v >= 100 else f"{v:.1f} MB/s"


def _run_name(r: dict) -> str:
    d = r["date"].replace("T", " ")[:16]
    return f"{r['label']} — {d} ({r['score']} pts)"


class BenchPage(Page):
    title = "Desempenho"
    subtitle = ("Meça o PC antes e depois das otimizações para ver o ganho real. "
                "Leva cerca de 20 segundos; feche jogos e programas pesados antes.")

    def build(self):
        self.run_btn = W.button(self.header.actions, "▶  Rodar teste", self._run, "primary", width=150)
        self.run_btn.pack(side="left")
        self.running = False

        how = W.Card(self.body, "Como comparar")
        how.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        steps = ctk.CTkFrame(how, fg_color="transparent")
        steps.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
        for i, txt in enumerate(["Rode o teste marcado como “Antes de otimizar”.",
                                 "Aplique as otimizações e reinicie o computador.",
                                 "Rode de novo como “Depois de otimizar” e veja a diferença abaixo."], 1):
            ctk.CTkLabel(steps, text=f"{i}.  {txt}", font=W.font(12), text_color=W.MUTED, anchor="w").pack(anchor="w")
        row = ctk.CTkFrame(how, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=16, pady=(6, 14))
        ctk.CTkLabel(row, text="Este teste é:", font=W.font(13, "bold"), text_color=W.TEXT).pack(side="left", padx=(0, 8))
        self.label_btn = ctk.CTkSegmentedButton(row, values=LABELS, font=W.font(12), selected_color=W.ACCENT,
                                                selected_hover_color=W.ACCENT_HOVER, unselected_color=W.CARD, fg_color=W.CARD)
        self.label_btn.pack(side="left")
        self.progress_lbl = ctk.CTkLabel(row, text="", font=W.font(12), text_color=W.MUTED)
        self.progress_lbl.pack(side="left", padx=14)
        self.progress = ctk.CTkProgressBar(how, height=6, progress_color=W.ACCENT, fg_color=W.BORDER)
        self.progress.set(0)

        self.result = W.Card(self.body, "Resultado")
        self.result.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        self.history = W.Card(self.body, "Histórico de testes")
        self.history.grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        self.base_id = None

    # ------------------------------------------------------------ execução
    def _run(self):
        if self.running:
            return
        label = self.label_btn.get() or LABELS[0]
        self.running = True
        self.run_btn.configure(state="disabled", text="Testando…")
        self.progress.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.progress.set(0)

        def prog(i, n, name):
            self.app.ui(lambda: (self.progress.set(i / n), self.progress_lbl.configure(text=f"{name}…" if i < n else "")))

        def work():
            res = B.run_all(prog)
            ctx = {"power_plan": (self.app.specs or {}).get("power_plan", {}).get("name"),
                   "tweaks_applied": len(tweaks.applied_with_backup())}
            return B.save_run(label, res, ctx)

        def done(run):
            self._finish()
            if run.get("errors"):
                messagebox.showwarning(APP_NAME, "Alguns testes falharam:\n" + "\n".join(run["errors"]))
            self.base_id = None
            self.render()

        def err(e, tb):
            self._finish()
            self.app._default_error(e, tb)

        self.app.run_bg(work, done, err, status="Rodando teste de desempenho…")

    def _finish(self):
        self.running = False
        self.run_btn.configure(state="normal", text="▶  Rodar teste")
        self.progress.grid_remove()
        self.progress_lbl.configure(text="")

    # ------------------------------------------------------------ exibição
    def on_show(self):
        hist = B.load_history()
        if not self.label_btn.get():
            has_before = any(r["label"] == LABELS[0] for r in hist)
            self.label_btn.set(LABELS[1] if has_before else LABELS[0])
        self.render()

    def render(self):
        hist = B.load_history()
        for w in self.result.winfo_children()[1:]:
            w.destroy()
        for w in self.history.winfo_children()[1:]:
            w.destroy()
        if not hist:
            ctk.CTkLabel(self.result, text="Nenhum teste ainda. Clique em “Rodar teste”.", font=W.font(13), text_color=W.MUTED).grid(
                row=1, column=0, sticky="w", padx=16, pady=(0, 16))
            ctk.CTkLabel(self.history, text="Vazio.", font=W.font(12), text_color=W.MUTED).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))
            return
        latest = hist[-1]
        others = [r for r in hist if r["id"] != latest["id"]]
        base = next((r for r in others if r["id"] == self.base_id), None)
        if base is None and others:
            # Base padrão: o último "Antes de otimizar"; senão o teste anterior
            befores = [r for r in others if r["label"] == LABELS[0]]
            base = befores[-1] if befores else others[-1]
        self._render_result(latest, base, others)
        self._render_history(hist)

    def _render_result(self, latest, base, others):
        top = ctk.CTkFrame(self.result, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=16)
        top.grid_columnconfigure(1, weight=1)
        sc = ctk.CTkFrame(top, fg_color="transparent")
        sc.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(sc, text=str(latest["score"]), font=W.font(40, "bold"), text_color=W.TEXT).pack(anchor="w")
        ctk.CTkLabel(sc, text=f"pontos · {latest['label']} · {latest['date'].replace('T', ' ')[:16]}", font=W.font(12),
                     text_color=W.MUTED).pack(anchor="w")
        if base:
            diff = (latest["score"] - base["score"]) / base["score"] * 100 if base["score"] else 0
            color = W.GREEN if diff >= B.NOISE_PCT else W.RED if diff <= -B.NOISE_PCT else W.MUTED
            ctk.CTkLabel(top, text=f"{diff:+.1f}%", font=W.font(30, "bold"), text_color=color).grid(row=0, column=1, sticky="w", padx=30)
            pick = ctk.CTkFrame(top, fg_color="transparent")
            pick.grid(row=0, column=2, sticky="e")
            ctk.CTkLabel(pick, text="Comparar com:", font=W.font(12), text_color=W.MUTED).pack(anchor="e")
            names = {_run_name(r): r["id"] for r in reversed(others)}
            om = ctk.CTkOptionMenu(pick, values=list(names), width=320, font=W.font(12), fg_color=W.CARD_HOVER,
                                   button_color=W.BORDER, button_hover_color=W.ACCENT,
                                   command=lambda n: self._pick_base(names[n]))
            om.set(_run_name(base))
            om.pack(anchor="e")
        ctk.CTkLabel(self.result, text="1000 pontos = PC de referência intermediário (4 núcleos, SSD SATA, DDR4).",
                     font=W.font(11), text_color=W.MUTED).grid(row=2, column=0, sticky="w", padx=16)

        tbl = ctk.CTkFrame(self.result, fg_color="transparent")
        tbl.grid(row=3, column=0, sticky="ew", padx=16, pady=(10, 4))
        tbl.grid_columnconfigure(0, weight=1)
        heads = ["Teste", "Antes" if base else "", "Agora", "Diferença" if base else ""]
        for c, h in enumerate(heads):
            ctk.CTkLabel(tbl, text=h, font=W.font(11, "bold"), text_color=W.MUTED, anchor="w" if c == 0 else "e",
                         width=10 if c == 0 else 130).grid(row=0, column=c, sticky="ew", pady=(0, 4))
        cmp = B.compare(base, latest) if base else {}
        for i, m in enumerate(B.METRICS, start=1):
            ctk.CTkLabel(tbl, text=m.name + ("  (menor é melhor)" if not m.higher_better else ""), font=W.font(12),
                         text_color=W.TEXT, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            if base:
                ctk.CTkLabel(tbl, text=_fmt(m, base["results"].get(m.key)), font=W.font(12), text_color=W.MUTED,
                             anchor="e", width=130).grid(row=i, column=1, sticky="e")
            ctk.CTkLabel(tbl, text=_fmt(m, latest["results"].get(m.key)), font=W.font(12, "bold"), text_color=W.TEXT,
                         anchor="e", width=130).grid(row=i, column=2, sticky="e")
            if m.key in cmp:
                d = cmp[m.key]
                color = W.GREEN if d >= B.NOISE_PCT else W.RED if d <= -B.NOISE_PCT else W.MUTED
                txt = f"{d:+.1f}%" if abs(d) >= B.NOISE_PCT else f"≈ igual ({d:+.1f}%)"
                ctk.CTkLabel(tbl, text=txt, font=W.font(12, "bold"), text_color=color, anchor="e", width=130).grid(
                    row=i, column=3, sticky="e")
        note = (f"Diferenças menores que {B.NOISE_PCT:.0f}% são variação normal entre execuções. "
                "Otimizações do Windows melhoram principalmente latência, estabilidade e uso de fundo — "
                "não espere que o disco ou a CPU fiquem mais rápidos sozinhos.")
        ctk.CTkLabel(self.result, text=note, font=W.font(11), text_color=W.MUTED, wraplength=900, justify="left",
                     anchor="w").grid(row=4, column=0, sticky="w", padx=16, pady=(6, 16))

    def _pick_base(self, run_id):
        self.base_id = run_id
        self.render()

    def _render_history(self, hist):
        fr = ctk.CTkFrame(self.history, fg_color="transparent")
        fr.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        fr.grid_columnconfigure(0, weight=1)
        for i, r in enumerate(reversed(hist)):
            ctx = r.get("context") or {}
            extra = f" · plano: {ctx.get('power_plan')}" if ctx.get("power_plan") else ""
            extra += f" · {ctx.get('tweaks_applied')} otimizações ativas" if ctx.get("tweaks_applied") is not None else ""
            ctk.CTkLabel(fr, text=f"{r['label']}", font=W.font(13, "bold"), text_color=W.TEXT, anchor="w").grid(
                row=i * 2, column=0, sticky="w", pady=(6, 0))
            ctk.CTkLabel(fr, text=f"{dt.datetime.fromisoformat(r['date']).strftime('%d/%m/%Y %H:%M')}{extra}", font=W.font(11),
                         text_color=W.MUTED, anchor="w").grid(row=i * 2 + 1, column=0, sticky="w")
            ctk.CTkLabel(fr, text=f"{r['score']} pts", font=W.font(14, "bold"), text_color=W.TEXT).grid(row=i * 2, column=1, rowspan=2, padx=16)
            W.button(fr, "Excluir", lambda rid=r["id"]: self._delete(rid), "secondary", width=80).grid(row=i * 2, column=2, rowspan=2)

    def _delete(self, run_id):
        if messagebox.askyesno(APP_NAME, "Excluir este teste do histórico?"):
            B.delete_run(run_id)
            if self.base_id == run_id:
                self.base_id = None
            self.render()
