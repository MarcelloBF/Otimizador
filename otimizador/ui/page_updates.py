"""Página Atualizações: programas via winget e drivers de vídeo."""
from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from ..core import updates as U
from ..core.utils import APP_NAME, is_admin, open_url
from . import widgets as W
from .pages_info import Page

DRIVER_STATUS = {
    "ok": ("Em dia", W.GREEN),
    "aging": ("Mais de 6 meses", W.YELLOW),
    "old": ("Desatualizado", W.ORANGE),
    "missing": ("Sem driver", W.RED),
}


class UpdatesPage(Page):
    title = "Atualizações"
    subtitle = ("Programas desatualizados encontrados pelo winget, o gerenciador de pacotes oficial do Windows, "
                "e a situação dos drivers de vídeo.")

    def build(self):
        self.update_btn = W.button(self.header.actions, "Atualizar selecionados", self._update_selected, "primary", width=190)
        self.update_btn.pack(side="left", padx=6)
        self.scan_btn = W.button(self.header.actions, "Verificar de novo", self.scan, "secondary", width=150)
        self.scan_btn.pack(side="left")
        W.button(self.header.actions, "Versão do Otimizador", lambda: self.app.check_update(force=True), "secondary",
                 width=170).pack(side="left", padx=(6, 0))

        # ---- programas
        self.prog = W.Card(self.body, "Programas")
        self.prog.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        bar = ctk.CTkFrame(self.prog, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 4))
        bar.grid_columnconfigure(0, weight=1)
        self.info = ctk.CTkLabel(bar, text="Procurando atualizações…", font=W.font(13), text_color=W.MUTED, anchor="w",
                                 justify="left", wraplength=640)
        self.info.grid(row=0, column=0, sticky="w")
        self.all_var = ctk.BooleanVar(value=True)
        self.all_chk = ctk.CTkCheckBox(bar, text="Marcar todos", variable=self.all_var, command=self._toggle_all,
                                       font=W.font(12), text_color=W.MUTED, checkbox_width=18, checkbox_height=18)
        self.all_chk.grid(row=0, column=1, sticky="e")
        self.rows = ctk.CTkFrame(self.prog, fg_color="transparent")
        self.rows.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))
        self.rows.grid_columnconfigure(1, weight=1)
        self.ignored_frame = ctk.CTkFrame(self.prog, fg_color="transparent", width=1, height=1)
        self.ignored_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))

        # ---- drivers
        self.drv = W.Card(self.body, "Drivers de vídeo")
        self.drv.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        self.drv_rows = ctk.CTkFrame(self.drv, fg_color="transparent")
        self.drv_rows.grid(row=1, column=0, sticky="ew", padx=16)
        self.drv_rows.grid_columnconfigure(0, weight=1)
        foot = ctk.CTkFrame(self.drv, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=16, pady=(6, 14))
        ctk.CTkLabel(foot, text=("O winget não atualiza drivers de vídeo: use o programa do fabricante. Outros drivers "
                                 "(chipset, rede, áudio) chegam pelas atualizações opcionais do Windows Update."),
                     font=W.font(11), text_color=W.MUTED, anchor="w", justify="left", wraplength=600).pack(side="left")
        W.button(foot, "Drivers opcionais", lambda: open_url(U.WINDOWS_OPTIONAL_UPDATES), "secondary",
                 width=150).pack(side="right")

        # ---- console
        con = W.Card(self.body, "Saída")
        con.grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        cbar = ctk.CTkFrame(con, fg_color="transparent", width=1, height=1)
        cbar.grid(row=0, column=0, sticky="e", padx=16, pady=(12, 0))
        self.stop_btn = W.button(cbar, "Parar", self._stop, "danger", width=80)
        self.stop_btn.pack(side="right")
        self.stop_btn.configure(state="disabled")
        self.console = ctk.CTkTextbox(con, font=ctk.CTkFont("Cascadia Mono", 12), fg_color=W.CONSOLE,
                                      text_color="#c8d0e0", wrap="word", height=170)
        self.console.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.pkgs: list[U.Package] = []
        self.vars: dict[str, ctk.BooleanVar] = {}
        self.status_labels: dict[str, ctk.CTkLabel] = {}
        self.ignored = U.load_ignored()
        self.loaded = False
        self.scanning = False
        self.running = False
        self._stop_flag = threading.Event()
        self._render_drivers()

    # ------------------------------------------------------------ ciclo de vida
    def on_show(self):
        if not self.loaded:
            self.scan()

    def _on_data(self):
        self._render_drivers()

    def log(self, line: str):
        self.console.insert("end", line + "\n")
        self.console.see("end")

    # ------------------------------------------------------------ programas
    def scan(self):
        if self.scanning or self.running:
            return
        if not U.winget_path():
            self.loaded = True
            self._no_winget()
            return
        self.scanning = True
        self.scan_btn.configure(state="disabled")
        self.update_btn.configure(state="disabled")
        self.info.configure(text="Procurando atualizações… (pode levar alguns segundos)")

        def done(pkgs):
            self.scanning = False
            self.loaded = True
            self.scan_btn.configure(state="normal")
            self.pkgs = U.order_for_install(pkgs)
            self._render_packages()

        def err(e, tb):
            self.scanning = False
            self.scan_btn.configure(state="normal")
            self.info.configure(text=f"Não foi possível consultar o winget: {e}")

        self.app.run_bg(U.list_upgrades, done, err, status="Procurando atualizações de programas…")

    def _no_winget(self):
        W.clear(self.rows)
        self.info.configure(text="O winget (Instalador de Aplicativo) não está instalado neste Windows.")
        W.button(self.rows, "Instalar pela Microsoft Store", lambda: open_url(U.STORE_APP_INSTALLER), "primary",
                 width=230).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.update_btn.configure(state="disabled")
        self.all_chk.grid_remove()

    def _render_packages(self):
        W.clear(self.rows)
        W.clear(self.ignored_frame)
        self.vars.clear()
        self.status_labels.clear()
        visible = [p for p in self.pkgs if p.id not in self.ignored]
        hidden = [p for p in self.pkgs if p.id in self.ignored]
        if not visible:
            self.info.configure(text="Tudo em dia: nenhum programa com atualização pendente.")
        else:
            extra = "" if is_admin() else " Sem administrador, o Windows pode pedir confirmação para alguns programas."
            self.info.configure(text=f"{len(visible)} programa(s) com atualização. Feche os programas marcados antes de "
                                     f"atualizar.{extra}")
        self.all_chk.grid() if visible else self.all_chk.grid_remove()

        for r, p in enumerate(visible):
            var = ctk.BooleanVar(value=p.suggested)
            self.vars[p.id] = var
            chk = ctk.CTkCheckBox(self.rows, text="", variable=var, width=24, checkbox_width=18, checkbox_height=18,
                                  command=self._sync)
            chk.grid(row=r, column=0, padx=(8, 4), pady=6, sticky="n")
            if not p.selectable:
                chk.configure(state="disabled")
            info = ctk.CTkFrame(self.rows, fg_color="transparent")
            info.grid(row=r, column=1, sticky="ew", pady=4)
            head = ctk.CTkFrame(info, fg_color="transparent")
            head.pack(anchor="w")
            ctk.CTkLabel(head, text=p.name, font=W.font(13, "bold"), text_color=W.TEXT).pack(side="left")
            if p.explicit:
                W.Badge(head, "atualização manual", W.GRAY).pack(side="left", padx=8)
            if p.unknown_version:
                W.Badge(head, "versão desconhecida", W.YELLOW).pack(side="left", padx=8)
            ctk.CTkLabel(info, text=f"{p.version}  →  {p.available}    ·    {p.id}", font=W.font(11),
                         text_color=W.MUTED, anchor="w").pack(anchor="w")
            st = ctk.CTkLabel(self.rows, text="", font=W.font(12), text_color=W.MUTED, width=150, anchor="e")
            st.grid(row=r, column=2, padx=8)
            self.status_labels[p.id] = st
            ctk.CTkButton(self.rows, text="Ignorar", width=70, height=26, corner_radius=6, font=W.font(11),
                          fg_color="transparent", hover_color=W.CARD_HOVER, text_color=W.MUTED,
                          command=lambda i=p.id: self._ignore(i, True)).grid(row=r, column=3, padx=(0, 8))

        if hidden:
            ctk.CTkLabel(self.ignored_frame, text=f"Ignorados ({len(hidden)}):", font=W.font(11), text_color=W.MUTED
                         ).pack(side="left")
            for p in hidden:
                ctk.CTkButton(self.ignored_frame, text=f"{p.name}  ✕", width=10, height=24, corner_radius=6,
                              font=W.font(11), fg_color=W.CARD_HOVER, hover_color=W.BORDER, text_color=W.MUTED,
                              command=lambda i=p.id: self._ignore(i, False)).pack(side="left", padx=4)
        self._sync()

    def _ignore(self, pkg_id: str, on: bool):
        if self.running:
            return
        (self.ignored.add if on else self.ignored.discard)(pkg_id)
        U.save_ignored(self.ignored)
        self._render_packages()

    def _selected(self) -> list[U.Package]:
        return [p for p in self.pkgs if p.id in self.vars and self.vars[p.id].get() and p.selectable]

    def _sync(self):
        n = len(self._selected())
        self.update_btn.configure(text=f"Atualizar selecionados ({n})" if n else "Atualizar selecionados",
                                  state="normal" if n and not self.running else "disabled")
        selectable = [p for p in self.pkgs if p.id in self.vars and p.selectable]
        self.all_var.set(bool(selectable) and n == len(selectable))

    def _toggle_all(self):
        on = self.all_var.get()
        for p in self.pkgs:
            if p.id in self.vars and p.selectable:
                self.vars[p.id].set(on)
        self._sync()

    def _stop(self):
        self._stop_flag.set()
        self.log("Parando depois do programa atual…")

    def _set_row(self, pkg_id: str, text: str, color: str):
        lbl = self.status_labels.get(pkg_id)
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text=text, text_color=color)

    def _update_selected(self):
        sel = U.order_for_install(self._selected())
        if not sel or self.running:
            return
        names = "\n".join(f"• {p.name} ({p.version} → {p.available})" for p in sel)
        if not messagebox.askyesno(APP_NAME, f"Atualizar {len(sel)} programa(s)?\n\n{names}\n\n"
                                             "Salve o que estiver aberto: os instaladores podem fechar esses programas."):
            return
        self.running = True
        self._stop_flag.clear()
        self.stop_btn.configure(state="normal")
        self.scan_btn.configure(state="disabled")
        self._sync()
        for p in sel:
            self._set_row(p.id, "Na fila", W.MUTED)

        def work():
            results = {}
            for i, p in enumerate(sel, 1):
                if self._stop_flag.is_set():
                    break
                self.app.ui(lambda p=p: self._set_row(p.id, "Atualizando…", W.ACCENT))
                self.app.ui(lambda p=p, i=i: (self.log(f"\n▶ [{i}/{len(sel)}] {p.name}"),
                                              self.app.set_status(f"Atualizando {p.name} ({i}/{len(sel)})…", busy=True)))
                try:
                    code = U.upgrade(p, lambda line: self.app.ui(lambda: self.log(line)), self._stop_flag.is_set)
                except Exception as e:  # noqa: BLE001
                    code = -1
                    self.app.ui(lambda e=e: self.log(f"Erro: {e}"))
                results[p.id] = code
                ok = U.is_success(code)
                msg = U.exit_message(code) if code != -1 else "Erro"
                self.app.ui(lambda p=p, ok=ok, msg=msg: (self._set_row(p.id, ("✓ " if ok else "✗ ") + msg,
                                                                       W.GREEN if ok else W.RED),
                                                         self.log(("■ " if ok else "✗ ") + msg)))
            return results

        def done(results):
            self.running = False
            self.stop_btn.configure(state="disabled")
            self.scan_btn.configure(state="normal")
            ok = sum(1 for c in results.values() if U.is_success(c))
            fail = len(results) - ok
            skipped = len(sel) - len(results)
            parts = [f"{ok} atualizado(s)"]
            if fail:
                parts.append(f"{fail} com erro")
            if skipped:
                parts.append(f"{skipped} não executado(s)")
            summary = ", ".join(parts) + "."
            self.log("\n" + summary)
            self.app.set_status(summary)
            # Remove da lista o que foi atualizado; os demais continuam para nova tentativa
            done_ids = {i for i, c in results.items() if U.is_success(c)}
            self.pkgs = [p for p in self.pkgs if p.id not in done_ids]
            for p in self.pkgs:
                if p.id in self.vars:
                    self.vars[p.id].set(False)
            self._sync()
            if fail:
                messagebox.showwarning(APP_NAME, summary + "\n\nVeja o motivo de cada erro na lista e na saída abaixo.")

        def err(e, tb):
            self.running = False
            self.stop_btn.configure(state="disabled")
            self.scan_btn.configure(state="normal")
            self._sync()
            self.log(f"Erro: {e}")

        self.app.run_bg(work, done, err)

    # ------------------------------------------------------------ drivers
    def _render_drivers(self):
        W.clear(self.drv_rows)
        drivers = U.gpu_drivers(self.app.specs)
        if not drivers:
            ctk.CTkLabel(self.drv_rows, text="Aguardando a leitura das especificações…", font=W.font(12),
                         text_color=W.MUTED).grid(row=0, column=0, sticky="w", pady=4)
            return
        for r, d in enumerate(drivers):
            info = ctk.CTkFrame(self.drv_rows, fg_color="transparent")
            info.grid(row=r, column=0, sticky="ew", pady=5)
            head = ctk.CTkFrame(info, fg_color="transparent")
            head.pack(anchor="w")
            ctk.CTkLabel(head, text=d["name"], font=W.font(13, "bold"), text_color=W.TEXT).pack(side="left")
            label, color = DRIVER_STATUS[d["status"]]
            W.Badge(head, label, color).pack(side="left", padx=8)
            age = d["age_days"]
            when = ""
            if d["date"]:
                when = f" · de {d['date']}"
                if age is not None:
                    when += f" ({age} dias)" if age < 60 else f" ({age // 30} meses)"
            ctk.CTkLabel(info, text=f"Driver {d['driver'] or '?'}{when} · atualize pelo {d['tool']}", font=W.font(11),
                         text_color=W.MUTED, anchor="w").pack(anchor="w")
            W.button(self.drv_rows, "Baixar driver", lambda u=d["url"]: open_url(u),
                     "primary" if d["status"] in ("old", "missing") else "secondary", width=130
                     ).grid(row=r, column=1, padx=(8, 0))
