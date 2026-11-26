"""Janela principal: barra lateral, navegação, estado compartilhado e tarefas em segundo plano."""
from __future__ import annotations

import json
import queue
import threading
import traceback
from tkinter import messagebox

import customtkinter as ctk

from ..core import analyzer, cleaner, selfupdate, startup, sysinfo
from ..core.utils import APP_NAME, APP_VERSION, data_dir, fmt_bytes, is_admin, open_url, relaunch_as_admin
from . import widgets as W

NAV = [
    ("painel", "\uE80F", "Painel"),
    ("jogo", "\uE7FC", "Modo Jogo"),
    ("specs", "\uE7F8", "Especificações"),
    ("diagnostico", "\uE9D9", "Diagnóstico"),
    ("desempenho", "\uEC4A", "Desempenho"),
    ("upgrades", "\uE74A", "Upgrades"),
    ("otimizacoes", "\uE945", "Otimizações"),
    ("limpeza", "\uE74D", "Limpeza"),
    ("inicializacao", "\uE7E8", "Inicialização"),
    ("atualizacoes", "\uE895", "Atualizações"),
    ("ferramentas", "\uE90F", "Ferramentas"),
    ("backup", "\uE777", "Backup e restauração"),
]
# Título de seção mostrado antes do item
SECTIONS = {"painel": "VISÃO GERAL", "otimizacoes": "OTIMIZAR", "ferramentas": "SISTEMA"}
NAV_ACTIVE_BG = W.tint(W.ACCENT, W.SIDEBAR, 0.14)


class App(ctk.CTk):
    def __init__(self):
        W.apply_theme()
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(f"{APP_NAME} — Otimizador de PC")
        self.geometry("1280x820")
        self.minsize(1080, 680)
        self.configure(fg_color=W.BG)

        self.specs: dict | None = None
        self.analysis: analyzer.Analysis | None = None
        self.startup_count: int | None = None
        self.junk_bytes: int | None = None
        self.loading = False
        self._q: queue.Queue = queue.Queue()
        self._listeners: list = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color=W.BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)
        self.top = ctk.CTkFrame(self.content, fg_color=W.BG, corner_radius=0, width=1, height=1)
        self.top.grid(row=0, column=0, sticky="ew")
        self._build_admin_banner()

        from .pages_actions import BackupPage, CleanPage, StartupPage, ToolsPage, TweaksPage
        from .page_bench import BenchPage
        from .page_game import GamePage
        from .page_updates import UpdatesPage
        from .page_upgrades import UpgradesPage
        from .pages_info import DashboardPage, DiagnosisPage, SpecsPage

        classes = {"painel": DashboardPage, "jogo": GamePage, "specs": SpecsPage, "diagnostico": DiagnosisPage,
                   "desempenho": BenchPage, "upgrades": UpgradesPage, "otimizacoes": TweaksPage, "limpeza": CleanPage, "inicializacao": StartupPage,
                   "atualizacoes": UpdatesPage,
                   "ferramentas": ToolsPage, "backup": BackupPage}
        self.pages = {}
        for key, cls in classes.items():
            page = cls(self.content, self)
            page.grid(row=1, column=0, sticky="nsew")
            page.grid_remove()
            self.pages[key] = page
            page.header.set_icon(next(icon for k, icon, _ in NAV if k == key))
        self.current = None
        self.show("painel")

        self._load_cached_specs()
        self.after(40, self._poll)
        self.after(150, self.refresh_specs)
        self.after(4000, self.check_update)
        self.after(15000, selfupdate.cleanup_old)

    # ------------------------------------------------------------ layout
    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, fg_color=W.SIDEBAR, corner_radius=0, width=236)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        # borda direita sutil
        ctk.CTkFrame(self, fg_color=W.BORDER, corner_radius=0, width=1).grid(row=0, column=0, sticky="nse")

        logo = ctk.CTkFrame(bar, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 4))
        ctk.CTkLabel(logo, text="\uE945", width=40, height=40, corner_radius=11, fg_color=W.ACCENT, text_color="white",
                     font=ctk.CTkFont(W.ICON_FONT, 19)).pack(side="left")
        txt = ctk.CTkFrame(logo, fg_color="transparent")
        txt.pack(side="left", padx=12)
        ctk.CTkLabel(txt, text=APP_NAME, font=W.font(18, "bold"), text_color=W.TEXT, anchor="w", height=22).pack(anchor="w")
        ctk.CTkLabel(txt, text=f"Otimizador de PC · v{APP_VERSION}", font=W.font(11), text_color=W.MUTED, anchor="w",
                     height=16).pack(anchor="w")

        self.nav_buttons = {}
        row = 1
        for key, icon, label in NAV:
            if key in SECTIONS:
                ctk.CTkLabel(bar, text=SECTIONS[key], font=W.font(10, "bold"), text_color="#5b6479", anchor="w",
                             height=16).grid(row=row, column=0, sticky="ew", padx=28, pady=(10, 2))
                row += 1
            item = ctk.CTkFrame(bar, fg_color="transparent", corner_radius=9, height=34, cursor="hand2")
            item.grid(row=row, column=0, sticky="ew", padx=12, pady=1)
            row += 1
            item.grid_propagate(False)
            item.grid_rowconfigure(0, weight=1)
            item.grid_columnconfigure(2, weight=1)
            mark = ctk.CTkFrame(item, fg_color=W.ACCENT, corner_radius=2, width=3, height=18)
            icon_lbl = ctk.CTkLabel(item, text=icon, font=ctk.CTkFont(W.ICON_FONT, 15), text_color=W.MUTED, width=22)
            icon_lbl.grid(row=0, column=1, padx=(12, 10))
            text_lbl = ctk.CTkLabel(item, text=label, font=W.font(13), text_color=W.MUTED, anchor="w")
            text_lbl.grid(row=0, column=2, sticky="w")
            for w in (item, icon_lbl, text_lbl):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
                w.bind("<Enter>", lambda e, k=key: self._hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._hover(k, False))
            self.nav_buttons[key] = (item, icon_lbl, text_lbl, mark)
            if key == "jogo":
                self.game_dot = ctk.CTkLabel(item, text=" ATIVO ", font=W.font(9, "bold"), text_color=W.light(W.GREEN, 0.3),
                                             fg_color=W.tint(W.GREEN, W.SIDEBAR, 0.2), corner_radius=6, height=18)
        bar.grid_rowconfigure(row, weight=1)

        foot = ctk.CTkFrame(bar, fg_color=W.CARD, corner_radius=12, border_width=1, border_color=W.BORDER)
        foot.grid(row=row + 1, column=0, sticky="ew", padx=12, pady=(6, 12))
        foot.grid_columnconfigure(1, weight=1)
        admin = is_admin()
        ctk.CTkLabel(foot, text="●", font=W.font(11), text_color=W.GREEN if admin else W.YELLOW, width=10,
                     height=18).grid(row=0, column=0, sticky="nw", padx=(12, 6), pady=(8, 0))
        self.status = ctk.CTkLabel(foot, text="Pronto.", font=W.font(11), text_color=W.MUTED, wraplength=170,
                                   justify="left", anchor="w")
        self.status.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(8, 8))
        self.status_idle = "Administrador · pronto." if admin else "Modo limitado · pronto."
        self.status.configure(text=self.status_idle)
        self.status_bar = ctk.CTkProgressBar(foot, mode="indeterminate", height=3, progress_color=W.ACCENT, fg_color=W.BORDER)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        self.status_bar.grid_remove()

    def _alert(self, color: str, icon: str, text: str):
        """Faixa de aviso arredondada no topo do conteúdo."""
        f = ctk.CTkFrame(self.top, fg_color=W.tint(color, W.BG, 0.10), corner_radius=12, border_width=1,
                         border_color=W.tint(color, W.BG, 0.35))
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=icon, font=ctk.CTkFont(W.ICON_FONT, 15), text_color=W.light(color, 0.2), width=20).grid(
            row=0, column=0, padx=(16, 10), pady=10)
        lbl = ctk.CTkLabel(f, text=text, text_color=W.light(color, 0.45), font=W.font(12), anchor="w", justify="left")
        lbl.grid(row=0, column=1, sticky="w")
        return f, lbl

    def _build_admin_banner(self):
        if is_admin():
            self.banner = None
            return
        self.banner, _ = self._alert(W.YELLOW, "\uE7BA", "Sem administrador: otimizações do sistema, serviços e algumas "
                                                          "limpezas ficam bloqueadas.")
        self.banner.pack(fill="x", padx=24, pady=(14, 0))
        W.button(self.banner, "Reabrir como administrador", self._elevate, "secondary", width=200, height=32).grid(
            row=0, column=2, padx=8, pady=8)

    def set_game_indicator(self, active: bool):
        dot = getattr(self, "game_dot", None)
        if dot is None:
            return
        if active:
            dot.grid(row=0, column=3, padx=(4, 10))
        else:
            dot.grid_remove()

    # ------------------------------------------------------------ nova versão
    def check_update(self, force: bool = False):
        def err(e, tb):
            if force:
                messagebox.showerror(APP_NAME, f"Não foi possível verificar atualizações:\n{e}")

        def done(info):
            if info:
                self._show_update_banner(info)
            elif force:
                messagebox.showinfo(APP_NAME, f"Você já está na versão mais nova (v{APP_VERSION}).")

        self.run_bg(lambda: selfupdate.check(force), done, err)

    def _show_update_banner(self, info: dict):
        if getattr(self, "update_banner", None) is not None:
            self.update_banner.destroy()
        b, self.update_label = self._alert(W.ACCENT, "\uE896",
                                           f"Nova versão disponível: v{info['version']} (você tem v{APP_VERSION}).")
        self.update_banner = b
        b.pack(fill="x", padx=24, pady=(14, 0))
        W.button(b, "Novidades", lambda: open_url(info["url"]), "secondary", width=110, height=32).grid(
            row=0, column=2, padx=(0, 6))
        self.update_btn = W.button(b, "Atualizar agora", lambda: self._self_update(info), "primary", width=150, height=32)
        self.update_btn.grid(row=0, column=3, padx=(0, 4), pady=8)
        ctk.CTkButton(b, text="✕", width=32, height=32, corner_radius=8, fg_color="transparent", hover_color=W.CARD_HOVER,
                      text_color=W.MUTED, command=lambda: self._skip_update(info)).grid(row=0, column=4, padx=(0, 8))

    def _skip_update(self, info: dict):
        if messagebox.askyesno(APP_NAME, f"Não avisar mais sobre a versão v{info['version']}?\n\n"
                                         "Você ainda pode baixá-la pelo GitHub quando quiser."):
            selfupdate.skip_version(info["version"])
        self.update_banner.destroy()
        self.update_banner = None

    def _self_update(self, info: dict):
        if not selfupdate.can_self_update(info):
            open_url(info["url"])
            return
        if not messagebox.askyesno(APP_NAME, f"Baixar a v{info['version']} e reiniciar o Otimizador agora?"):
            return
        self.update_btn.configure(state="disabled")

        def progress(done, total):
            pct = f" {done * 100 // total}%" if total else ""
            self.ui(lambda: self.update_label.configure(text=f"Baixando v{info['version']}…{pct} ({fmt_bytes(done)})"))

        def done(path):
            try:
                selfupdate.install_and_restart(path)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Não foi possível instalar a nova versão:\n{e}\n\n"
                                               "Baixe pelo GitHub e substitua o arquivo manualmente.")
                self.update_btn.configure(state="normal")
                return
            self.destroy()

        def err(e, tb):
            self.update_btn.configure(state="normal")
            self.update_label.configure(text=f"Falha no download: {e}")

        self.run_bg(lambda: selfupdate.download(info, progress), done, err, status="Baixando atualização…")

    def _elevate(self):
        if relaunch_as_admin():
            self.destroy()

    def _hover(self, key: str, inside: bool):
        if key == self.current:
            return
        self.nav_buttons[key][0].configure(fg_color=W.CARD_HOVER if inside else "transparent")
        self.nav_buttons[key][2].configure(text_color=W.TEXT if inside else W.MUTED)

    def show(self, key: str):
        if self.current == key:
            return
        prev, self.current_nav = getattr(self, "current_nav", None), key
        for k, (item, icon, text, mark) in self.nav_buttons.items():
            active = k == key
            item.configure(fg_color=NAV_ACTIVE_BG if active else "transparent")
            icon.configure(text_color=W.light(W.ACCENT, 0.15) if active else W.MUTED)
            text.configure(text_color=W.TEXT if active else W.MUTED, font=W.font(13, "bold" if active else "normal"))
            if active:
                mark.grid(row=0, column=0, padx=(4, 0))
            else:
                mark.grid_remove()
        if self.current:
            self.pages[self.current].grid_remove()
        self.current = key
        page = self.pages[key]
        page.grid()
        page.on_show()

    # ------------------------------------------------------------ tarefas
    def run_bg(self, fn, done=None, error=None, status: str | None = None):
        """Executa fn em thread; done(resultado) roda na thread da interface."""
        if status:
            self.set_status(status, busy=True)

        def worker():
            try:
                res = fn()
                self._q.put(lambda: done(res) if done else None)
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc()
                self._q.put(lambda: (error or self._default_error)(e, tb))
            finally:
                if status:
                    self._q.put(lambda: self.set_status("", busy=False))

        threading.Thread(target=worker, daemon=True).start()

    def ui(self, fn):
        """Agenda uma chamada na thread da interface (seguro a partir de threads)."""
        self._q.put(fn)

    def _poll(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        self.after(40, self._poll)

    def _default_error(self, e, tb):
        print(tb)
        messagebox.showerror(APP_NAME, f"Ocorreu um erro:\n\n{e}")

    def set_status(self, text: str, busy: bool = False):
        self.status.configure(text=text or self.status_idle)
        if busy:
            self.status_bar.grid()
            self.status_bar.start()
        else:
            self.status_bar.stop()
            self.status_bar.grid_remove()

    # ------------------------------------------------------------ dados
    def on_data(self, fn):
        """Registra callback chamado quando specs/análise mudam."""
        self._listeners.append(fn)

    def _emit(self):
        for fn in self._listeners:
            try:
                fn()
            except Exception:  # noqa: BLE001
                traceback.print_exc()

    def _cache_path(self):
        return data_dir() / "specs_cache.json"

    def _load_cached_specs(self):
        try:
            self.specs = json.loads(self._cache_path().read_text(encoding="utf-8"))
            self.reanalyze(emit=True)
        except Exception:
            pass

    def refresh_specs(self):
        if self.loading:
            return
        self.loading = True

        def work():
            data = sysinfo.collect()
            sc = startup.count_enabled()
            junk = cleaner.quick_junk_estimate()
            return data, sc, junk

        def done(res):
            self.loading = False
            self.specs, self.startup_count, self.junk_bytes = res
            try:
                self._cache_path().write_text(json.dumps(self.specs, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            self.reanalyze()
            self.set_status("Análise concluída.")

        def err(e, tb):
            self.loading = False
            self._default_error(e, tb)

        self.run_bg(work, done, err, status="Analisando o computador…")

    def reanalyze(self, emit=True):
        if not self.specs:
            return
        # estado do Windows muda após otimizações: relê o que é barato
        try:
            self.specs["win"] = sysinfo.windows_state()
        except Exception:
            pass
        self.analysis = analyzer.analyze(self.specs, {"startup_enabled": self.startup_count, "junk_bytes": self.junk_bytes})
        if emit:
            self._emit()


def run():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Otimizador.App")
    except Exception:
        pass
    app = App()
    app.mainloop()
