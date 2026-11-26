"""Página Modo Jogo."""
from __future__ import annotations

import datetime as dt
from tkinter import messagebox

import customtkinter as ctk

from ..core import gamemode as G
from ..core.utils import APP_NAME, fmt_bytes
from . import widgets as W
from .pages_info import Page


class GamePage(Page):
    title = "Modo Jogo"
    subtitle = ("Antes de jogar: fecha programas que pesam em segundo plano e liga o plano de energia de alto desempenho. "
                "Ao desativar, tudo volta como estava.")

    def build(self):
        self.toggle_btn = W.button(self.header.actions, "Ativar Modo Jogo", self._toggle, "success", width=190)
        self.toggle_btn.pack(side="left")

        self.status_card = W.Card(self.body)
        self.status_card.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.status_card.grid_columnconfigure(0, weight=0)
        self.status_card.grid_columnconfigure(1, weight=1)
        self.dot = ctk.CTkLabel(self.status_card, text="●", font=W.font(30), text_color=W.GRAY)
        self.dot.grid(row=0, column=0, rowspan=2, padx=(18, 10), pady=12)
        self.status_title = ctk.CTkLabel(self.status_card, text="Desligado", font=W.font(17, "bold"), text_color=W.TEXT,
                                         anchor="w")
        self.status_title.grid(row=0, column=1, sticky="sw", pady=(14, 0))
        self.status_text = ctk.CTkLabel(self.status_card, text="", font=W.font(12), text_color=W.MUTED, anchor="w",
                                        justify="left", wraplength=760)
        self.status_text.grid(row=1, column=1, sticky="nw", pady=(0, 14))

        self.list_card = W.Card(self.body, "Programas para fechar")
        self.list_card.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        bar = ctk.CTkFrame(self.list_card, fg_color="transparent", width=1, height=1)
        bar.grid(row=0, column=0, sticky="e", padx=16, pady=(12, 0))
        W.button(bar, "Atualizar lista", self.refresh, "secondary", width=130).pack()
        self.rows = ctk.CTkFrame(self.list_card, fg_color="transparent")
        self.rows.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 6))
        self.rows.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.list_card, text=("Primeiro o app pede para cada programa fechar, como clicar no X. O que continuar "
                                           "aberto depois de alguns segundos é encerrado: salve o que estiver fazendo. "
                                           "Steam, Discord, drivers e antivírus nunca são fechados."),
                     font=W.font(11), text_color=W.MUTED, anchor="w", justify="left", wraplength=760
                     ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 14))

        opt = W.Card(self.body, "Opções")
        opt.grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        prefs = G.load_prefs()
        self.power_var = ctk.BooleanVar(value=prefs.get("power", True))
        self.reopen_var = ctk.BooleanVar(value=prefs.get("reopen", True))
        for r, (var, text, hint) in enumerate([
            (self.power_var, "Usar o plano de energia Alto desempenho",
             "O processador não reduz a velocidade entre um quadro e outro. Em notebook, gasta mais bateria."),
            (self.reopen_var, "Reabrir os programas fechados ao desativar",
             "Abre de novo o que o Modo Jogo fechou, como usuário comum."),
        ], start=1):
            sw = ctk.CTkSwitch(opt, text=text, variable=var, font=W.font(13), text_color=W.TEXT, progress_color=W.ACCENT,
                               command=self._save_prefs)
            sw.grid(row=r * 2 - 1, column=0, sticky="w", padx=16, pady=(6, 0))
            ctk.CTkLabel(opt, text=hint, font=W.font(11), text_color=W.MUTED, anchor="w").grid(
                row=r * 2, column=0, sticky="w", padx=62, pady=(0, 6))
        ctk.CTkLabel(opt, text=("O Windows já silencia notificações e dá prioridade ao jogo em tela cheia quando o "
                                "\"Modo de Jogo\" dele está ligado (página Otimizações)."),
                     font=W.font(11), text_color=W.MUTED, anchor="w", justify="left", wraplength=760
                     ).grid(row=5, column=0, sticky="w", padx=16, pady=(4, 14))

        con = W.Card(self.body, "Registro")
        con.grid(row=3, column=0, sticky="ew", padx=6, pady=6)
        self.console = ctk.CTkTextbox(con, font=ctk.CTkFont("Cascadia Mono", 12), fg_color=W.CONSOLE,
                                      text_color="#c8d0e0", wrap="word", height=110)
        self.console.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.cands: list[G.Candidate] = []
        self.vars: dict[str, ctk.BooleanVar] = {}
        self.busy = False
        self._render_status()

    # ------------------------------------------------------------ ciclo de vida
    def on_show(self):
        self._render_status()
        if not G.is_active():
            self.refresh()

    def log(self, line: str):
        self.console.insert("end", line + "\n")
        self.console.see("end")

    def _save_prefs(self):
        prefs = G.load_prefs()
        sel = prefs.get("selected", {})
        for key, var in self.vars.items():
            sel[key] = bool(var.get())
        prefs.update(selected=sel, power=bool(self.power_var.get()), reopen=bool(self.reopen_var.get()))
        try:
            G.save_prefs(prefs)
        except OSError:
            pass

    def _render_status(self):
        st = G.state()
        if st.get("active"):
            since = st.get("since", "")
            try:
                since = dt.datetime.fromisoformat(since).strftime("%H:%M")
            except ValueError:
                pass
            parts = [f"Ativo desde {since}."]
            n = len(st.get("closed", []))
            if n:
                parts.append(f"{n} programa(s) fechado(s)")
            if st.get("freed"):
                parts.append(f"{fmt_bytes(st['freed'])} de RAM liberada")
            if st.get("previous_plan"):
                parts.append("plano de energia em Alto desempenho")
            if st.get("failed"):
                parts.append("não fechou: " + ", ".join(st["failed"]))
            self.status_title.configure(text="Modo Jogo ativo")
            self.status_text.configure(text=parts[0] + " " + "; ".join(parts[1:]) + (". " if len(parts) > 1 else "")
                                       + "Desative quando terminar de jogar.")
            self.dot.configure(text_color=W.GREEN)
            self.toggle_btn.configure(text="Desativar Modo Jogo", fg_color=W.DANGER, hover_color=W.DANGER_HOVER)
            self.list_card.grid_remove()
        else:
            self.status_title.configure(text="Desligado")
            self.status_text.configure(text="Marque o que fechar e clique em Ativar Modo Jogo antes de abrir o jogo.")
            self.dot.configure(text_color=W.GRAY)
            self.toggle_btn.configure(text="Ativar Modo Jogo", fg_color=W.SUCCESS, hover_color=W.SUCCESS_HOVER)
            self.list_card.grid()
        self.app.set_game_indicator(bool(st.get("active")))

    def refresh(self):
        if self.busy:
            return
        self.app.run_bg(G.scan, self._render_list)

    def _render_list(self, cands: list[G.Candidate]):
        self.cands = cands
        W.clear(self.rows)
        self.vars.clear()
        sel = G.load_prefs().get("selected", {})
        if not cands:
            ctk.CTkLabel(self.rows, text="Nenhum programa pesado da lista está aberto agora.", font=W.font(13),
                         text_color=W.MUTED).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=8)
            return
        for r, c in enumerate(cands):
            var = ctk.BooleanVar(value=sel.get(c.key, c.default))
            self.vars[c.key] = var
            ctk.CTkCheckBox(self.rows, text="", variable=var, width=24, checkbox_width=18, checkbox_height=18,
                            command=self._save_prefs).grid(row=r, column=0, padx=(8, 4), pady=6, sticky="n")
            info = ctk.CTkFrame(self.rows, fg_color="transparent")
            info.grid(row=r, column=1, sticky="ew", pady=4)
            ctk.CTkLabel(info, text=c.name, font=W.font(13, "bold"), text_color=W.TEXT).pack(anchor="w")
            ctk.CTkLabel(info, text=c.reason, font=W.font(11), text_color=W.MUTED).pack(anchor="w")
            color = W.ORANGE if c.ram > 1024**3 else W.YELLOW if c.ram > 300 * 1024**2 else W.MUTED
            ctk.CTkLabel(self.rows, text=fmt_bytes(c.ram), font=W.font(13, "bold"), text_color=color, width=90,
                         anchor="e").grid(row=r, column=2, padx=12)

    # ------------------------------------------------------------ ação
    def _toggle(self):
        if self.busy:
            return
        if G.is_active():
            self._deactivate()
        else:
            self._activate()

    def _activate(self):
        chosen = [c for c in self.cands if c.key in self.vars and self.vars[c.key].get()]
        power = bool(self.power_var.get())
        if not chosen and not power:
            messagebox.showinfo(APP_NAME, "Marque ao menos um programa ou o plano de energia.")
            return
        if chosen and not messagebox.askyesno(
                APP_NAME, "Fechar estes programas?\n\n" + "\n".join(f"• {c.name} ({fmt_bytes(c.ram)})" for c in chosen)
                + "\n\nSalve o que estiver aberto neles antes de continuar."):
            return
        self._save_prefs()
        self.busy = True
        self.toggle_btn.configure(state="disabled")
        self.log("▶ Ativando Modo Jogo…")

        def done(st):
            self.busy = False
            self.toggle_btn.configure(state="normal")
            self.log(f"■ Pronto. RAM liberada: {fmt_bytes(st.get('freed', 0))}")
            self.app.set_status("Modo Jogo ativo.")
            self._render_status()

        def err(e, tb):
            self.busy = False
            self.toggle_btn.configure(state="normal")
            self.log(f"Erro: {e}")
            self._render_status()

        self.app.run_bg(lambda: G.activate(chosen, power, lambda s: self.app.ui(lambda: self.log(s))), done, err,
                        status="Ativando Modo Jogo…")

    def _deactivate(self):
        self.busy = True
        self.toggle_btn.configure(state="disabled")
        self.log("▶ Desativando Modo Jogo…")
        reopen = bool(self.reopen_var.get())

        def done(_st):
            self.busy = False
            self.toggle_btn.configure(state="normal")
            self.log("■ Tudo restaurado.")
            self.app.set_status("Modo Jogo desativado.")
            self._render_status()
            self.refresh()

        def err(e, tb):
            self.busy = False
            self.toggle_btn.configure(state="normal")
            self.log(f"Erro: {e}")

        self.app.run_bg(lambda: G.deactivate(reopen, lambda s: self.app.ui(lambda: self.log(s))), done, err,
                        status="Desativando Modo Jogo…")
