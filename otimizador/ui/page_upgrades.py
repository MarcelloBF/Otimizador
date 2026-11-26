"""Página Upgrades: gargalo do PC e o próximo upgrade que vale a pena."""
from __future__ import annotations

import customtkinter as ctk

from ..core import upgrades as U
from . import widgets as W
from .pages_info import Page

CAT_ICON = {"gpu": "", "cpu": "", "ram": "", "storage": "", "monitor": "",
            "platform": ""}
CAT_COLOR = {"gpu": W.RED, "cpu": W.ACCENT, "ram": W.PURPLE, "storage": W.GREEN, "monitor": W.YELLOW,
             "platform": W.ORANGE}
COMBO_COLOR = {"Econômica": W.GREEN, "Equilibrada": W.ACCENT, "Máxima": W.PURPLE}


def _bar_color(score: int) -> str:
    return W.GREEN if score >= 70 else W.YELLOW if score >= 50 else W.ORANGE if score >= 30 else W.RED


class UpgradesPage(Page):
    title = "Upgrades"
    subtitle = ("Qual peça trocar primeiro no seu PC, compatível com a sua placa-mãe e em ordem de custo-benefício. "
                "Diferente de otimizar: aqui é o que comprar.")

    def build(self):
        self.content = ctk.CTkFrame(self.body, fg_color="transparent")
        self.content.grid(row=0, column=0, sticky="ew")
        self.content.grid_columnconfigure(0, weight=1)
        self._render()

    def on_show(self):
        self._render()

    def _on_data(self):
        if self.visible:
            self._render()

    # ------------------------------------------------------------ desenho
    def _render(self):
        W.clear(self.content)
        if not self.app.specs:
            ctk.CTkLabel(self.content, text="Aguardando a leitura das especificações…", font=W.font(13),
                         text_color=W.MUTED).grid(row=0, column=0, sticky="w", padx=10, pady=10)
            return
        plan = U.analyze(self.app.specs)
        row = 0
        self._balance_card(plan).grid(row=row, column=0, sticky="ew", padx=6, pady=6)
        row += 1
        if plan.recs:
            self._rec_card(plan.recs[0], best=True).grid(row=row, column=0, sticky="ew", padx=6, pady=6)
            row += 1
        if len(plan.recs) > 1:
            ctk.CTkLabel(self.content, text="Depois, nesta ordem", font=W.font(15, "bold"), text_color=W.TEXT,
                         anchor="w").grid(row=row, column=0, sticky="w", padx=10, pady=(12, 2))
            row += 1
            for r in plan.recs[1:]:
                self._rec_card(r).grid(row=row, column=0, sticky="ew", padx=6, pady=5)
                row += 1
        if plan.combos:
            self._combos(plan).grid(row=row, column=0, sticky="ew", padx=6, pady=6)
            row += 1
        if not plan.recs:
            c = W.Card(self.content)
            c.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
            ctk.CTkLabel(c, text="Nenhum upgrade com ganho claro: o PC está bem montado para o uso atual.",
                         font=W.font(13), text_color=W.TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=18)
            row += 1
        ctk.CTkLabel(self.content, text=(
            "Ganhos estimados a partir de médias de reviews de jogos, não de medições no seu PC; o resultado real muda "
            "com o jogo e as configurações. Antes de comprar, confira a fonte de energia, o tamanho do gabinete e a "
            "lista de compatibilidade da sua placa-mãe."), font=W.font(11), text_color=W.MUTED, justify="left",
            anchor="w", wraplength=900).grid(row=row, column=0, sticky="w", padx=10, pady=(8, 16))

    def _balance_card(self, plan: U.UpgradePlan):
        c = W.Card(self.content, "Equilíbrio do seu PC", icon="")
        c.grid_columnconfigure(0, weight=1)
        weak = {"gpu": "gpu", "cpu": "cpu"}.get(plan.bottleneck)
        tag = {"gpu": ("Gargalo: placa de vídeo", W.ORANGE), "cpu": ("Gargalo: processador", W.ORANGE),
               "equilibrado": ("Equilibrado", W.GREEN), "notebook": ("Notebook", W.GRAY)}[plan.bottleneck]
        head = ctk.CTkFrame(c, fg_color="transparent")
        head.grid(row=1, column=0, sticky="ew", padx=18)
        W.Badge(head, tag[0], tag[1]).pack(side="left")
        ctk.CTkLabel(head, text=f"Considerando {plan.resolution}p · {plan.hz} Hz", font=W.font(11),
                     text_color=W.MUTED).pack(side="left", padx=10)
        ctk.CTkLabel(c, text=plan.verdict, font=W.font(14), text_color=W.TEXT, anchor="w", justify="left",
                     wraplength=880).grid(row=2, column=0, sticky="w", padx=18, pady=(8, 10))
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 16))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="b")
        for i, b in enumerate(plan.balance):
            cell = ctk.CTkFrame(grid, fg_color=W.tint(W.ORANGE, W.CARD, 0.08) if b.key == weak else W.CARD_HOVER,
                                corner_radius=10, border_width=1 if b.key == weak else 0,
                                border_color=W.tint(W.ORANGE, W.CARD, 0.4))
            cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)
            cell.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(cell, text=b.label, font=W.font(12, "bold"), text_color=W.TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=12, pady=(10, 0))
            ctk.CTkLabel(cell, text=f"{b.score}", font=W.font(13, "bold"), text_color=_bar_color(b.score)).grid(
                row=0, column=1, sticky="e", padx=12, pady=(10, 0))
            ctk.CTkLabel(cell, text=b.detail, font=W.font(11), text_color=W.MUTED, anchor="w").grid(
                row=1, column=0, columnspan=2, sticky="w", padx=12)
            bar = ctk.CTkProgressBar(cell, height=7, corner_radius=4, progress_color=_bar_color(b.score),
                                     fg_color=W.BORDER)
            bar.set(b.score / 100)
            bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(6, 12))
        ctk.CTkLabel(c, text="Nota de 0 a 100 em relação a um PC gamer topo de linha atual.", font=W.font(10),
                     text_color=W.MUTED, anchor="w").grid(row=4, column=0, sticky="w", padx=18, pady=(0, 12))
        return c

    def _rec_card(self, r: U.UpgradeRec, best: bool = False):
        color = CAT_COLOR.get(r.category, W.ACCENT)
        c = W.Card(self.content, border_color=W.tint(W.ACCENT, W.CARD, 0.6) if best else W.BORDER,
                   border_width=2 if best else 1)
        c.grid_columnconfigure(0, weight=0)
        c.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(c, text=CAT_ICON.get(r.category, ""), width=44, height=44, corner_radius=12,
                     fg_color=W.tint(color, W.CARD, 0.18), text_color=W.light(color, 0.25),
                     font=ctk.CTkFont(W.ICON_FONT, 19)).grid(row=0, column=0, rowspan=3, sticky="n", padx=(18, 14), pady=18)
        top = ctk.CTkFrame(c, fg_color="transparent")
        top.grid(row=0, column=1, sticky="ew", pady=(16, 0), padx=(0, 18))
        if best:
            W.Badge(top, "MELHOR PRÓXIMO PASSO", W.ACCENT).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(top, text=r.title, font=W.font(15, "bold"), text_color=W.TEXT).pack(side="left")
        ctk.CTkLabel(c, text=r.why, font=W.font(12), text_color=W.MUTED, anchor="w", justify="left",
                     wraplength=760).grid(row=1, column=1, sticky="w", pady=(4, 6), padx=(0, 18))
        body = ctk.CTkFrame(c, fg_color="transparent")
        body.grid(row=2, column=1, sticky="ew", padx=(0, 18), pady=(0, 16))
        for item in r.buy:
            line = ctk.CTkFrame(body, fg_color="transparent")
            line.pack(anchor="w", pady=1)
            ctk.CTkLabel(line, text="", font=ctk.CTkFont(W.ICON_FONT, 11), text_color=W.light(color, 0.25),
                         width=16).pack(side="left")
            ctk.CTkLabel(line, text=item, font=W.font(12, "bold"), text_color=W.TEXT).pack(side="left", padx=(6, 0))
        pills = ctk.CTkFrame(body, fg_color="transparent")
        pills.pack(anchor="w", pady=(8, 0))
        W.Badge(pills, f"Ganho: {r.gain}", W.GREEN).pack(side="left", padx=(0, 6))
        W.Badge(pills, f"Custo: {r.cost}", W.YELLOW).pack(side="left")
        for n in r.notes:
            ctk.CTkLabel(body, text=f"• {n}", font=W.font(11), text_color=W.MUTED, anchor="w", justify="left",
                         wraplength=740).pack(anchor="w", pady=(4, 0))
        return c

    def _combos(self, plan: U.UpgradePlan):
        c = W.Card(self.content, "Combinações sugeridas", icon="")
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 16))
        grid.grid_columnconfigure(tuple(range(len(plan.combos))), weight=1, uniform="cmb")
        for i, cb in enumerate(plan.combos):
            color = COMBO_COLOR.get(cb.name, W.ACCENT)
            box = ctk.CTkFrame(grid, fg_color=W.tint(color, W.CARD, 0.07), corner_radius=12, border_width=1,
                               border_color=W.tint(color, W.CARD, 0.35))
            box.grid(row=0, column=i, sticky="nsew", padx=4)
            ctk.CTkLabel(box, text=cb.name, font=W.font(14, "bold"), text_color=W.light(color, 0.3), anchor="w").pack(
                anchor="w", padx=14, pady=(12, 4))
            for part in cb.parts:
                ctk.CTkLabel(box, text=f"+ {part}", font=W.font(12, "bold"), text_color=W.TEXT, anchor="w",
                             justify="left", wraplength=250).pack(anchor="w", padx=14, pady=1)
            ctk.CTkLabel(box, text=cb.result, font=W.font(11), text_color=W.MUTED, anchor="w", justify="left",
                         wraplength=250).pack(anchor="w", padx=14, pady=(6, 14))
        return c
