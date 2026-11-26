"""Páginas de ação: Otimizações, Limpeza, Inicialização, Ferramentas e Backup."""
from __future__ import annotations

import os
import threading
from tkinter import messagebox

import customtkinter as ctk

from ..core import cleaner, startup, tools, tweaks
from ..core.utils import APP_NAME, data_dir, fmt_bytes, is_admin
from . import widgets as W
from .pages_info import Page

# =========================================================================== fluxos compartilhados


def apply_tweaks_flow(app, items: list[tweaks.Tweak], restore_point: bool, then=None):
    """Aplica otimizações em segundo plano e mostra o resumo."""

    def work():
        log = []
        if restore_point and is_admin():
            ok = tools.create_restore_point(lambda line: None)
            log.append(("Ponto de restauração", ok, "" if ok else "não foi possível criar (o Windows limita 1 por dia em alguns casos)"))
        backup = tweaks.Backup()
        for t in items:
            try:
                tweaks.apply_tweak(t, backup)
                log.append((t.name, True, ""))
            except PermissionError:
                log.append((t.name, False, "requer administrador"))
            except Exception as e:  # noqa: BLE001
                log.append((t.name, False, str(e)[:120]))
        return log

    def done(log):
        restart = sorted({t.restart for t in items if t.restart})
        ok = sum(1 for _, s, _ in log if s)
        lines = [f"{'✓' if s else '✗'} {n}" + (f" — {e}" if e else "") for n, s, e in log]
        msg = f"{ok} de {len(log)} itens aplicados.\n\n" + "\n".join(lines)
        if "reiniciar" in restart:
            msg += "\n\n↻ Reinicie o computador para que todas as mudanças tenham efeito."
        elif "logoff" in restart:
            msg += "\n\n↻ Algumas mudanças aparecem após sair e entrar novamente na conta."
        messagebox.showinfo(APP_NAME, msg)
        app.reanalyze()
        if then:
            then()

    app.run_bg(work, done, status="Aplicando otimizações…")


def one_click_optimize(app):
    a = app.analysis
    if not a:
        messagebox.showinfo(APP_NAME, "Aguarde a análise do computador terminar.")
        return
    admin = is_admin()
    profile = a.profile
    items = [t for t in tweaks.tweaks_for_profile(profile) if not t.is_applied() and (admin or not t.needs_admin)]
    safe_clean = [t for t in cleaner.targets() if t.default and (admin or not t.admin) and t.id != "recycle"]
    msg = (f"Otimização com 1 clique — perfil “{tweaks.PROFILES[profile]}”\n\n"
           f"{'• Criar ponto de restauração' + chr(10) if admin else ''}"
           f"• Aplicar {len(items)} otimizações seguras:\n" + "\n".join(f"     – {t.name}" for t in items)
           + f"\n• Limpar arquivos temporários e caches ({len(safe_clean)} categorias, a Lixeira não é tocada)\n\n"
           "Tudo pode ser desfeito na página Backup e restauração.\n"
           "Dica: para medir o ganho, rode antes o teste da página Desempenho.\n\nContinuar?")
    if not admin:
        msg += "\n\n(Sem administrador: itens de sistema serão pulados.)"
    if not messagebox.askyesno(APP_NAME, msg):
        return

    def clean_after():
        def work():
            freed = 0
            for t in safe_clean:
                f, _ = cleaner.clean(t)
                freed += f
            return freed

        def done(freed):
            app.junk_bytes = None
            app.reanalyze()
            messagebox.showinfo(APP_NAME, f"Limpeza concluída: {fmt_bytes(freed)} liberados.")

        app.run_bg(work, done, status="Limpando arquivos…")

    if items:
        apply_tweaks_flow(app, items, restore_point=admin, then=clean_after)
    else:
        clean_after()


# =========================================================================== Otimizações


class TweaksPage(Page):
    title = "Otimizações"
    subtitle = ("Escolha um perfil ou marque individualmente. Cada otimização salva o valor original e pode ser revertida. "
                "Itens marcados como já aplicados aparecem em verde.")

    def build(self):
        self.vars: dict[str, ctk.BooleanVar] = {}
        self.status_lbls = {}
        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 6))
        ctk.CTkLabel(top, text="Perfil:", font=W.font(13, "bold"), text_color=W.TEXT).pack(side="left", padx=(0, 8))
        self.profile_btn = ctk.CTkSegmentedButton(top, values=list(tweaks.PROFILES.values()), command=self._on_profile,
                                                  font=W.font(12), selected_color=W.ACCENT, selected_hover_color=W.ACCENT_HOVER, height=34, corner_radius=9,
                                                  unselected_color=W.CARD_HOVER, fg_color=W.CARD_HOVER)
        self.profile_btn.pack(side="left")
        self.rp_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(top, text="Criar ponto de restauração antes", variable=self.rp_var, font=W.font(12),
                        text_color=W.MUTED, fg_color=W.ACCENT).pack(side="left", padx=16)

        W.button(self.header.actions, "Reverter marcados", self._revert, "secondary", width=160).pack(side="left", padx=6)
        W.button(self.header.actions, "Aplicar marcados", self._apply, "primary", width=160).pack(side="left")

        row = 1
        for cat in tweaks.CATEGORIES:
            items = [t for t in tweaks.TWEAKS if t.category == cat]
            if not items:
                continue
            card = W.Card(self.body, cat)
            card.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
            row += 1
            for i, t in enumerate(items):
                self._tweak_row(card, t).grid(row=i + 1, column=0, sticky="ew", padx=12, pady=(0, 10 if i == len(items) - 1 else 2))
        self._profile_key = "seguro"

    def _tweak_row(self, parent, t: tweaks.Tweak):
        fr = ctk.CTkFrame(parent, fg_color=W.BG, corner_radius=8)
        fr.grid_columnconfigure(1, weight=1)
        var = ctk.BooleanVar(value=False)
        self.vars[t.id] = var
        cb = ctk.CTkCheckBox(fr, text="", variable=var, width=24, fg_color=W.ACCENT)
        cb.grid(row=0, column=0, rowspan=2, padx=(12, 4), pady=10)
        if t.needs_admin and not is_admin():
            cb.configure(state="disabled")
        head = ctk.CTkFrame(fr, fg_color="transparent")
        head.grid(row=0, column=1, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(head, text=t.name, font=W.font(13, "bold"), text_color=W.TEXT).pack(side="left")
        W.Badge(head, f"risco {t.risk}", W.RISK_COLORS[t.risk]).pack(side="left", padx=8)
        if t.needs_admin:
            W.Badge(head, "admin", W.GRAY).pack(side="left")
        if t.restart:
            ctk.CTkLabel(head, text="↻ " + ("reiniciar" if t.restart == "reiniciar" else "sair/entrar"), font=W.font(11),
                         text_color=W.MUTED).pack(side="left", padx=8)
        desc = t.description + (f"\nGanho: {t.impact}" if t.impact else "")
        ctk.CTkLabel(fr, text=desc, font=W.font(12), text_color=W.MUTED, anchor="w", justify="left", wraplength=760).grid(
            row=1, column=1, sticky="w", pady=(0, 10))
        st = ctk.CTkLabel(fr, text="", font=W.font(11, "bold"), width=110)
        st.grid(row=0, column=2, rowspan=2, padx=12)
        self.status_lbls[t.id] = st
        return fr

    def select_profile(self, key: str):
        self._profile_key = key
        self.profile_btn.set(tweaks.PROFILES[key])
        self._apply_profile_selection()

    def _on_profile(self, label):
        self._profile_key = next(k for k, v in tweaks.PROFILES.items() if v == label)
        self._apply_profile_selection()

    def _apply_profile_selection(self):
        admin = is_admin()
        for t in tweaks.TWEAKS:
            self.vars[t.id].set(self._profile_key in t.profiles and (admin or not t.needs_admin))

    def on_show(self):
        if not self.profile_btn.get():
            self.select_profile(self.app.analysis.profile if self.app.analysis else "seguro")
        self._refresh_status()

    def refresh(self):
        if self.visible:
            self._refresh_status()

    def _refresh_status(self):
        def work():
            return {t.id: t.is_applied() for t in tweaks.TWEAKS}

        def done(state):
            for tid, applied in state.items():
                self.status_lbls[tid].configure(text="✓ Aplicado" if applied else "Não aplicado",
                                                text_color=W.GREEN if applied else W.MUTED)

        self.app.run_bg(work, done)

    def _selected(self):
        return [t for t in tweaks.TWEAKS if self.vars[t.id].get()]

    def _apply(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo(APP_NAME, "Nenhuma otimização marcada.")
            return
        risky = [t for t in sel if t.risk == "alto"]
        msg = f"Aplicar {len(sel)} otimização(ões)?"
        if risky:
            msg += "\n\nATENÇÃO — itens de risco alto:\n" + "\n".join(f"• {t.name}: {t.description}" for t in risky)
        if not messagebox.askyesno(APP_NAME, msg, icon="warning" if risky else "question"):
            return
        apply_tweaks_flow(self.app, sel, self.rp_var.get(), then=self._refresh_status)

    def _revert(self):
        sel = self._selected()
        if not sel or not messagebox.askyesno(APP_NAME, f"Reverter {len(sel)} otimização(ões) para o valor original?"):
            return

        def work():
            res = []
            for t in sel:
                try:
                    res.append((t.name, tweaks.revert_tweak(t)))
                except Exception as e:  # noqa: BLE001
                    res.append((t.name, f"erro: {e}"))
            return res

        def done(res):
            lines = [f"{'✓ revertido' if r is True else '— sem backup (não foi aplicado por aqui)' if r is False else r}: {n}" for n, r in res]
            messagebox.showinfo(APP_NAME, "\n".join(lines))
            self._refresh_status()
            self.app.reanalyze()

        self.app.run_bg(work, done, status="Revertendo…")


# =========================================================================== Limpeza


class CleanPage(Page):
    title = "Limpeza"
    subtitle = "Libere espaço removendo arquivos temporários e caches. Arquivos em uso são ignorados automaticamente."

    def build(self):
        W.button(self.header.actions, "Analisar", self._scan, "secondary", width=120).pack(side="left", padx=6)
        self.clean_btn = W.button(self.header.actions, "Limpar selecionados", self._clean, "primary", width=170)
        self.clean_btn.pack(side="left")
        self.total_card = W.Card(self.body)
        self.total_card.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.total_lbl = ctk.CTkLabel(self.total_card, text="Clique em Analisar para calcular o espaço recuperável.",
                                      font=W.font(18, "bold"), text_color=W.TEXT)
        self.total_lbl.grid(row=0, column=0, sticky="w", padx=18, pady=16)
        self.list_card = W.Card(self.body)
        self.list_card.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        self.targets = cleaner.targets()
        self.vars = {}
        self.size_lbls = {}
        for i, t in enumerate(self.targets):
            fr = ctk.CTkFrame(self.list_card, fg_color="transparent")
            fr.grid(row=i, column=0, sticky="ew", padx=14, pady=6)
            fr.grid_columnconfigure(1, weight=1)
            v = ctk.BooleanVar(value=t.default)
            self.vars[t.id] = v
            cb = ctk.CTkCheckBox(fr, text="", variable=v, width=24, fg_color=W.ACCENT, command=self._update_total)
            cb.grid(row=0, column=0, rowspan=2, padx=(0, 8))
            if t.admin and not is_admin():
                cb.configure(state="disabled")
                v.set(False)
            ctk.CTkLabel(fr, text=t.name + ("  (requer admin)" if t.admin and not is_admin() else ""), font=W.font(13, "bold"),
                         text_color=W.TEXT, anchor="w").grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(fr, text=t.description, font=W.font(11), text_color=W.MUTED, anchor="w", justify="left",
                         wraplength=720).grid(row=1, column=1, sticky="w")
            sl = ctk.CTkLabel(fr, text="—", font=W.font(13, "bold"), text_color=W.MUTED, width=120, anchor="e")
            sl.grid(row=0, column=2, rowspan=2)
            self.size_lbls[t.id] = sl
        self.scanned = False

    def on_show(self):
        if not self.scanned:
            self._scan()

    def _scan(self):
        def work():
            return cleaner.scan_all()

        def done(ts):
            self.targets = ts
            self.scanned = True
            for t in ts:
                self.size_lbls[t.id].configure(text=f"{fmt_bytes(t.size)}" + (f"\n{t.files} arquivos" if t.files else ""),
                                               text_color=W.TEXT if t.size > 50 * 1024**2 else W.MUTED)
            self._update_total()

        for lbl in self.size_lbls.values():
            lbl.configure(text="…")
        self.app.run_bg(work, done, status="Calculando espaço…")

    def _update_total(self):
        if not self.scanned:
            return
        total = sum(t.size for t in self.targets if self.vars[t.id].get())
        self.total_lbl.configure(text=f"{fmt_bytes(total)} podem ser liberados")

    def _clean(self):
        sel = [t for t in self.targets if self.vars[t.id].get()]
        if not sel:
            return
        if not messagebox.askyesno(APP_NAME, "Limpar:\n" + "\n".join(f"• {t.name}" for t in sel)
                                   + "\n\nArquivos removidos não vão para a Lixeira. Continuar?"):
            return

        def work():
            freed, skipped = 0, 0
            for t in sel:
                f, s = cleaner.clean(t)
                freed += f
                skipped += s
            return freed, skipped

        def done(res):
            freed, skipped = res
            messagebox.showinfo(APP_NAME, f"Limpeza concluída!\n\n{fmt_bytes(freed)} liberados."
                                + (f"\n{skipped} arquivos em uso foram ignorados." if skipped else ""))
            self.app.junk_bytes = None
            self.app.reanalyze()
            self._scan()

        self.app.run_bg(work, done, status="Limpando…")


# =========================================================================== Inicialização


class StartupPage(Page):
    title = "Inicialização"
    subtitle = ("Programas que abrem junto com o Windows. Desativar não desinstala nada — o programa só deixa de abrir sozinho. "
                "Mesmo mecanismo do Gerenciador de Tarefas.")

    REC_COLORS = {"manter": W.GREEN, "desativar": W.ORANGE, "opcional": W.YELLOW, "avaliar": W.GRAY}
    REC_TEXT = {"manter": "Manter", "desativar": "Pode desativar", "opcional": "Opcional", "avaliar": "Avaliar"}

    def build(self):
        W.button(self.header.actions, "Desativar sugeridos", self._disable_suggested, "primary", width=170).pack(side="left", padx=6)
        W.button(self.header.actions, "Atualizar", self.on_show, "secondary", width=110).pack(side="left")
        self.info = ctk.CTkLabel(self.body, text="", font=W.font(13), text_color=W.MUTED, anchor="w")
        self.info.grid(row=0, column=0, sticky="w", padx=8, pady=(0, 6))
        self.list = W.Card(self.body)
        self.list.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        self.items: list[startup.StartupItem] = []

    def on_show(self):
        self.app.run_bg(startup.list_items, self._render)

    def _render(self, items):
        self.items = items
        W.clear(self.list)
        enabled = sum(1 for i in items if i.enabled)
        self.info.configure(text=f"{enabled} de {len(items)} programas ativos na inicialização.")
        self.app.startup_count = enabled
        for idx, it in enumerate(items):
            fr = ctk.CTkFrame(self.list, fg_color="transparent")
            fr.grid(row=idx, column=0, sticky="ew", padx=14, pady=5)
            fr.grid_columnconfigure(0, weight=1)
            rec, why = it.hint
            head = ctk.CTkFrame(fr, fg_color="transparent")
            head.grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(head, text=it.name, font=W.font(13, "bold"), text_color=W.TEXT if it.enabled else W.MUTED).pack(side="left")
            W.Badge(head, self.REC_TEXT[rec], self.REC_COLORS[rec]).pack(side="left", padx=8)
            ctk.CTkLabel(head, text=why, font=W.font(11), text_color=W.MUTED).pack(side="left")
            ctk.CTkLabel(fr, text=f"{it.location} · {it.executable}", font=W.font(11), text_color=W.MUTED, anchor="w",
                         wraplength=760, justify="left").grid(row=1, column=0, sticky="w")
            sw = ctk.CTkSwitch(fr, text="", width=46, progress_color=W.ACCENT)
            if it.enabled:
                sw.select()
            sw.configure(command=lambda i=it, s=sw: self._toggle(i, s))
            if it.needs_admin and not is_admin():
                sw.configure(state="disabled")
            sw.grid(row=0, column=1, rowspan=2, padx=8)

    def _toggle(self, item, sw):
        want = bool(sw.get())
        try:
            startup.set_enabled(item, want)
            self.app.set_status(f"{item.name}: {'ativado' if want else 'desativado'} na inicialização.")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Não foi possível alterar {item.name}:\n{e}")
            sw.select() if item.enabled else sw.deselect()
        self.app.startup_count = sum(1 for i in self.items if i.enabled)
        self.app.reanalyze()

    def _disable_suggested(self):
        admin = is_admin()
        sel = [i for i in self.items if i.enabled and i.hint[0] == "desativar" and (admin or not i.needs_admin)]
        if not sel:
            messagebox.showinfo(APP_NAME, "Nenhum item sugerido para desativar.")
            return
        if not messagebox.askyesno(APP_NAME, "Desativar na inicialização:\n\n" + "\n".join(f"• {i.name}" for i in sel)
                                   + "\n\nVocê pode reativar a qualquer momento aqui."):
            return
        for i in sel:
            try:
                startup.set_enabled(i, False)
            except Exception:  # noqa: BLE001
                pass
        self._render(self.items)
        self.app.reanalyze()


# =========================================================================== Ferramentas


class ToolsPage(Page):
    title = "Ferramentas"
    subtitle = "Reparos e manutenção do Windows. A saída de cada comando aparece no console abaixo."
    scroll = False

    def build(self):
        self.body.grid_rowconfigure(0, weight=3)
        self.body.grid_rowconfigure(1, weight=2)
        grid = ctk.CTkScrollableFrame(self.body, fg_color=W.BG, height=200)
        grid.grid(row=0, column=0, sticky="nsew")
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="t")
        for i, t in enumerate(tools.TOOLS):
            c = W.Card(grid)
            c.grid(row=i // 3, column=i % 3, sticky="nsew", padx=5, pady=5)
            head = ctk.CTkFrame(c, fg_color="transparent")
            head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
            ctk.CTkLabel(head, text=t.name, font=W.font(13, "bold"), text_color=W.TEXT, anchor="w").pack(side="left")
            ctk.CTkLabel(c, text=t.description, font=W.font(11), text_color=W.MUTED, anchor="w", justify="left",
                         wraplength=280).grid(row=1, column=0, sticky="w", padx=14, pady=4)
            foot = ctk.CTkFrame(c, fg_color="transparent")
            foot.grid(row=2, column=0, sticky="w", padx=14, pady=(2, 12))
            b = W.button(foot, "Abrir" if t.launch else "Executar", lambda tool=t: self._run(tool), "secondary", width=110)
            b.pack(side="left")
            if t.admin:
                W.Badge(foot, "requer admin", W.GRAY).pack(side="left", padx=8)
            if t.long:
                ctk.CTkLabel(foot, text="⏱ demorado", font=W.font(11), text_color=W.MUTED).pack(side="left")
            if t.admin and not is_admin():
                b.configure(state="disabled")
        con = W.Card(self.body)
        con.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        con.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(con, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        ctk.CTkLabel(bar, text="Console", font=W.font(13, "bold"), text_color=W.TEXT).pack(side="left")
        self.stop_btn = W.button(bar, "Parar", self._stop, "danger", width=80)
        self.stop_btn.pack(side="right")
        self.stop_btn.configure(state="disabled")
        self.console = ctk.CTkTextbox(con, font=ctk.CTkFont("Cascadia Mono", 12), fg_color=W.CONSOLE, text_color="#c8d0e0",
                                      wrap="word", height=120)
        self.console.grid(row=1, column=0, sticky="nsew", padx=12, pady=(6, 12))
        self.running = False
        self._stop_flag = threading.Event()

    def log(self, line):
        self.console.insert("end", line + "\n")
        self.console.see("end")

    def _stop(self):
        self._stop_flag.set()

    def _run(self, tool: tools.Tool):
        if tool.launch:
            tools.run_streaming(tool, self.log)
            return
        if self.running:
            messagebox.showinfo(APP_NAME, "Aguarde o comando atual terminar.")
            return
        if tool.confirm and not messagebox.askyesno(APP_NAME, tool.confirm):
            return
        self.running = True
        self._stop_flag.clear()
        self.stop_btn.configure(state="normal")
        self.log(f"\n▶ {tool.name}\n" + "─" * 60)

        def work():
            return tools.run_streaming(tool, lambda line: self.app.ui(lambda: self.log(line)), self._stop_flag.is_set)

        def done(code):
            self.running = False
            self.stop_btn.configure(state="disabled")
            self.log(f"■ Finalizado (código {code})")

        def err(e, tb):
            self.running = False
            self.stop_btn.configure(state="disabled")
            self.log(f"Erro: {e}")

        self.app.run_bg(work, done, err, status=f"Executando: {tool.name}")


# =========================================================================== Backup


class BackupPage(Page):
    title = "Backup e restauração"
    subtitle = ("Todas as alterações feitas por este app ficam registradas com o valor original. "
                "Você pode desfazer uma a uma, tudo de uma vez, ou usar um ponto de restauração do Windows.")

    def build(self):
        W.button(self.header.actions, "Desfazer tudo", self._revert_all, "danger", width=140).pack(side="left", padx=6)
        top = W.Card(self.body, "Pontos de restauração do Windows")
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        fr = ctk.CTkFrame(top, fg_color="transparent")
        fr.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        b1 = W.button(fr, "Criar ponto agora", self._create_rp, "primary", width=170)
        b1.pack(side="left")
        if not is_admin():
            b1.configure(state="disabled")
        W.button(fr, "Abrir Restauração do Sistema", lambda: os.startfile("rstrui.exe"), "secondary", width=230).pack(side="left", padx=8)
        W.button(fr, "Abrir pasta de dados", lambda: os.startfile(str(data_dir())), "secondary", width=180).pack(side="left")
        self.list = W.Card(self.body, "Alterações aplicadas por este app")
        self.list.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

    def on_show(self):
        for w in self.list.winfo_children()[1:]:
            w.destroy()
        items = tweaks.applied_with_backup()
        fr = ctk.CTkFrame(self.list, fg_color="transparent")
        fr.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        fr.grid_columnconfigure(0, weight=1)
        if not items:
            ctk.CTkLabel(fr, text="Nenhuma alteração registrada ainda.", font=W.font(12), text_color=W.MUTED).grid(row=0, column=0, sticky="w")
        for i, t in enumerate(items):
            ctk.CTkLabel(fr, text=f"{t.name}", font=W.font(13, "bold"), text_color=W.TEXT, anchor="w").grid(row=i, column=0, sticky="w", pady=4)
            ctk.CTkLabel(fr, text=t.category, font=W.font(11), text_color=W.MUTED).grid(row=i, column=1, padx=12)
            b = W.button(fr, "Desfazer", lambda tw=t: self._revert([tw]), "secondary", width=100)
            b.grid(row=i, column=2)
            if t.needs_admin and not is_admin():
                b.configure(state="disabled")

    def refresh(self):
        if self.visible:
            self.on_show()

    def _revert(self, items):
        def work():
            out = []
            for t in items:
                try:
                    tweaks.revert_tweak(t)
                    out.append(f"✓ {t.name}")
                except Exception as e:  # noqa: BLE001
                    out.append(f"✗ {t.name}: {e}")
            return out

        def done(out):
            if len(items) > 1:
                messagebox.showinfo(APP_NAME, "\n".join(out) + "\n\nReinicie o PC para garantir que tudo voltou ao normal.")
            self.app.reanalyze()
            self.on_show()

        self.app.run_bg(work, done, status="Desfazendo…")

    def _revert_all(self):
        items = tweaks.applied_with_backup()
        if not items:
            return
        if messagebox.askyesno(APP_NAME, f"Desfazer todas as {len(items)} alterações e voltar aos valores originais?"):
            self._revert(items)

    def _create_rp(self):
        def work():
            lines = []
            ok = tools.create_restore_point(lines.append)
            return ok, "\n".join(lines[-5:])

        def done(res):
            ok, text = res
            (messagebox.showinfo if ok else messagebox.showwarning)(APP_NAME, text or ("Criado." if ok else "Falhou."))

        self.app.run_bg(work, done, status="Criando ponto de restauração…")
