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
    ("painel", "", "Painel"),
    ("specs", "", "Especificações"),
    ("diagnostico", "", "Diagnóstico"),
    ("otimizacoes", "", "Otimizações"),
    ("limpeza", "", "Limpeza"),
    ("inicializacao", "", "Inicialização"),
    ("ferramentas", "", "Ferramentas"),
    ("backup", "", "Backup e restauração"),
]
NAV.insert(3, ("desempenho", "", "Desempenho"))
NAV.insert(7, ("atualizacoes", "", "Atualizações"))
NAV.insert(1, ("jogo", "", "Modo Jogo"))


class App(ctk.CTk):
    def __init__(self):
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
        from .pages_info import DashboardPage, DiagnosisPage, SpecsPage

        classes = {"painel": DashboardPage, "jogo": GamePage, "specs": SpecsPage, "diagnostico": DiagnosisPage,
                   "desempenho": BenchPage, "otimizacoes": TweaksPage, "limpeza": CleanPage, "inicializacao": StartupPage,
                   "atualizacoes": UpdatesPage,
                   "ferramentas": ToolsPage, "backup": BackupPage}
        self.pages = {}
        for key, cls in classes.items():
            page = cls(self.content, self)
            page.grid(row=1, column=0, sticky="nsew")
            page.grid_remove()
            self.pages[key] = page
        self.current = None
        self.show("painel")

        self._load_cached_specs()
        self.after(40, self._poll)
        self.after(150, self.refresh_specs)
        self.after(4000, self.check_update)
        self.after(15000, selfupdate.cleanup_old)

    # ------------------------------------------------------------ layout
    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, fg_color=W.SIDEBAR, corner_radius=0, width=230)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        logo = ctk.CTkFrame(bar, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 20))
        ctk.CTkLabel(logo, text="", font=ctk.CTkFont(W.ICON_FONT, 26), text_color=W.ACCENT).pack(side="left")
        txt = ctk.CTkFrame(logo, fg_color="transparent")
        txt.pack(side="left", padx=10)
        ctk.CTkLabel(txt, text=APP_NAME, font=W.font(19, "bold"), text_color=W.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(txt, text=f"v{APP_VERSION}", font=W.font(11), text_color=W.MUTED, anchor="w").pack(anchor="w")

        self.nav_buttons = {}
        for i, (key, icon, label) in enumerate(NAV, start=1):
            item = ctk.CTkFrame(bar, fg_color="transparent", corner_radius=8, height=42, cursor="hand2")
            item.grid(row=i, column=0, sticky="ew", padx=12, pady=2)
            item.grid_propagate(False)
            item.grid_rowconfigure(0, weight=1)
            icon_lbl = ctk.CTkLabel(item, text=icon, font=ctk.CTkFont(W.ICON_FONT, 16), text_color=W.MUTED, width=24)
            icon_lbl.grid(row=0, column=0, padx=(14, 10))
            text_lbl = ctk.CTkLabel(item, text=label, font=W.font(14), text_color=W.MUTED, anchor="w")
            text_lbl.grid(row=0, column=1, sticky="w")
            for w in (item, icon_lbl, text_lbl):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
                w.bind("<Enter>", lambda e, k=key: self._hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._hover(k, False))
            self.nav_buttons[key] = (item, icon_lbl, text_lbl)
            if key == "jogo":
                self.game_dot = ctk.CTkLabel(item, text="●", font=W.font(12), text_color=W.GREEN, width=16)
        bar.grid_rowconfigure(len(NAV) + 1, weight=1)
        self.status = ctk.CTkLabel(bar, text="", font=W.font(11), text_color=W.MUTED, wraplength=200, justify="left", anchor="w")
        self.status.grid(row=len(NAV) + 2, column=0, sticky="ew", padx=18, pady=(0, 6))
        self.status_bar = ctk.CTkProgressBar(bar, mode="indeterminate", height=4, progress_color=W.ACCENT, fg_color=W.SIDEBAR)
        self.status_bar.grid(row=len(NAV) + 3, column=0, sticky="ew", padx=18, pady=(0, 18))
        self.status_bar.grid_remove()

    def _build_admin_banner(self):
        self.banner = ctk.CTkFrame(self.top, fg_color="#3a2a0a", corner_radius=0, height=44)
        if is_admin():
            return
        self.banner.pack(fill="x")
        self.banner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.banner, text="⚠  Executando sem privilégios de administrador — otimizações do sistema, serviços e "
                                       "algumas limpezas ficarão bloqueadas.", text_color="#fcd34d", font=W.font(12),
                     anchor="w").grid(row=0, column=0, sticky="w", padx=20, pady=8)
        W.button(self.banner, "Reabrir como administrador", self._elevate, "secondary", width=210).grid(row=0, column=1, padx=12, pady=6)

    def set_game_indicator(self, active: bool):
        dot = getattr(self, "game_dot", None)
        if dot is None:
            return
        if active:
            dot.grid(row=0, column=2, padx=(6, 0))
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
        b = self.update_banner = ctk.CTkFrame(self.top, fg_color="#0c2a4d", corner_radius=0)
        b.pack(fill="x")
        b.grid_columnconfigure(0, weight=1)
        self.update_label = ctk.CTkLabel(b, text=f"Nova versão disponível: v{info['version']} (você tem v{APP_VERSION}).",
                                         text_color="#bfdbfe", font=W.font(12, "bold"), anchor="w")
        self.update_label.grid(row=0, column=0, sticky="w", padx=20, pady=8)
        W.button(b, "Novidades", lambda: open_url(info["url"]), "secondary", width=110).grid(row=0, column=1, padx=(0, 6))
        self.update_btn = W.button(b, "Atualizar agora", lambda: self._self_update(info), "primary", width=150)
        self.update_btn.grid(row=0, column=2, padx=(0, 6), pady=6)
        ctk.CTkButton(b, text="✕", width=32, height=32, corner_radius=8, fg_color="transparent", hover_color=W.CARD_HOVER,
                      text_color="#bfdbfe", command=lambda: self._skip_update(info)).grid(row=0, column=3, padx=(0, 10))

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

    def show(self, key: str):
        if self.current == key:
            return
        prev, self.current_nav = getattr(self, "current_nav", None), key
        for k, (item, icon, text) in self.nav_buttons.items():
            active = k == key
            item.configure(fg_color=W.CARD if active else "transparent")
            icon.configure(text_color=W.ACCENT if active else W.MUTED)
            text.configure(text_color=W.TEXT if active else W.MUTED)
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
        self.status.configure(text=text)
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
