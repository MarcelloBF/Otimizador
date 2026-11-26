"""Tema e componentes visuais reutilizáveis."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

# ----------------------------------------------------------------- tema
BG = "#0b0e15"
SIDEBAR = "#0f131c"
CARD = "#151a26"
CARD_HOVER = "#1d2333"
BORDER = "#242b3d"
TEXT = "#eef1f7"
MUTED = "#8a93a8"
ACCENT = "#6c7bff"
ACCENT_HOVER = "#5a69f0"
GREEN = "#22c55e"
YELLOW = "#f5b014"
ORANGE = "#f97316"
RED = "#ef4444"
GRAY = "#64748b"
PURPLE = "#a855f7"
SUCCESS, SUCCESS_HOVER = "#16a34a", "#15803d"
DANGER, DANGER_HOVER = "#c0262d", "#a11d23"
CONSOLE = "#090b11"

SEVERITY_COLORS = {"crítico": RED, "alto": ORANGE, "médio": YELLOW, "baixo": ACCENT, "info": GRAY, "ok": GREEN}
RISK_COLORS = {"baixo": GREEN, "médio": YELLOW, "alto": RED}

FONT = "Segoe UI"
ICON_FONT = "Segoe Fluent Icons"


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def score_color(score: int) -> str:
    if score >= 85:
        return GREEN
    if score >= 65:
        return YELLOW
    if score >= 45:
        return ORANGE
    return RED


def _blend(c1: str, c2: str, a: float) -> str:
    """Mistura c1 sobre c2 com opacidade a (Tk não tem transparência)."""
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (round(r1 * a + r2 * (1 - a)), round(g1 * a + g2 * (1 - a)), round(b1 * a + b2 * (1 - a)))


def tint(color: str, base: str = CARD, a: float = 0.16) -> str:
    return _blend(color, base, a)


def light(color: str, a: float = 0.35) -> str:
    """Versão mais clara da cor, legível sobre fundo escuro tingido."""
    return _blend("#ffffff", color, a)


def apply_theme() -> None:
    """Aplica as cores do app aos widgets padrão do CustomTkinter (chamar antes de criar a janela)."""
    t = ctk.ThemeManager.theme

    def put(widget, **values):
        for k, v in values.items():
            if k in t.get(widget, {}):
                t[widget][k] = [v, v] if isinstance(v, str) and k != "corner_radius" else v

    put("CTkCheckBox", fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color="#4a5470", checkmark_color="#ffffff",
        corner_radius=5, border_width=2)
    put("CTkSwitch", fg_color="#2c3448", progress_color=ACCENT, button_color="#e8ebf3", button_hover_color="#ffffff")
    put("CTkProgressBar", fg_color=BORDER, progress_color=ACCENT)
    put("CTkSegmentedButton", fg_color=CARD_HOVER, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
        unselected_color=CARD_HOVER, unselected_hover_color=BORDER, text_color=TEXT)
    put("CTkScrollbar", button_color=BORDER, button_hover_color="#38415a")
    put("CTkOptionMenu", fg_color=CARD_HOVER, button_color=BORDER, button_hover_color=ACCENT, text_color=TEXT)
    put("DropdownMenu", fg_color=CARD, hover_color=CARD_HOVER, text_color=TEXT)
    put("CTkTextbox", fg_color=CONSOLE, border_color=BORDER, scrollbar_button_color=BORDER)
    put("CTkButton", fg_color=ACCENT, hover_color=ACCENT_HOVER)


# ----------------------------------------------------------------- componentes


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str | None = None, icon: str | None = None, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", BORDER)
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.body_row = 0
        if title:
            head = ctk.CTkFrame(self, fg_color="transparent")
            head.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
            if icon:
                ctk.CTkLabel(head, text=icon, font=ctk.CTkFont(ICON_FONT, 15), text_color=ACCENT).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(head, text=title, font=font(15, "bold"), text_color=TEXT, anchor="w").pack(side="left")
            self.body_row = 1


class Badge(ctk.CTkLabel):
    """Etiqueta discreta: fundo tingido com a cor e texto na própria cor."""

    def __init__(self, master, text: str, color: str, **kw):
        base = kw.pop("base", CARD)
        super().__init__(master, text=f"  {text}  ", fg_color=tint(color, base, 0.2), text_color=light(color, 0.3),
                         corner_radius=8, font=font(11, "bold"), height=20, **kw)


class PageHeader(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        self.icon_tile = ctk.CTkLabel(self, text="", width=46, height=46, corner_radius=12, fg_color=tint(ACCENT, BG, 0.18),
                                      text_color=light(ACCENT, 0.2), font=ctk.CTkFont(ICON_FONT, 20))
        ctk.CTkLabel(self, text=title, font=font(25, "bold"), text_color=TEXT, anchor="w").grid(row=0, column=1, sticky="sw")
        self.sub = None
        if subtitle:
            self.sub = ctk.CTkLabel(self, text=subtitle, font=font(13), text_color=MUTED, anchor="w", justify="left",
                                    wraplength=620)
            self.sub.grid(row=1, column=1, sticky="nw", pady=(0, 0))
        self.actions = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.actions.grid(row=0, column=2, rowspan=2, sticky="e")
        self.bind("<Configure>", self._rewrap, add="+")

    def set_icon(self, icon: str):
        self.icon_tile.configure(text=icon)
        self.icon_tile.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))

    def _rewrap(self, _event=None):
        """Quebra o subtítulo antes dos botões do cabeçalho, em qualquer largura de janela."""
        if self.sub is None:
            return
        scale = self._get_widget_scaling()
        free = (self.winfo_width() - self.actions.winfo_reqwidth()) / scale - 24 - 60
        wrap = int(max(300, min(720, free)))
        if wrap != self.sub.cget("wraplength"):
            self.sub.configure(wraplength=wrap)


def button(master, text, command, kind="primary", width=140, **kw):
    styles = {
        "primary": dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white"),
        "secondary": dict(fg_color=CARD_HOVER, hover_color=BORDER, text_color=TEXT, border_width=1, border_color=BORDER),
        "success": dict(fg_color=SUCCESS, hover_color=SUCCESS_HOVER, text_color="white"),
        "danger": dict(fg_color=DANGER, hover_color=DANGER_HOVER, text_color="white"),
        "ghost": dict(fg_color="transparent", hover_color=CARD_HOVER, text_color=MUTED),
    }
    kw.setdefault("height", 38)
    return ctk.CTkButton(master, text=text, command=command, width=width, corner_radius=10,
                         font=font(13, "bold"), **styles[kind], **kw)


class ScoreRing(tk.Canvas):
    """Anel circular com a nota de saúde do PC."""

    def __init__(self, master, size=170, **kw):
        super().__init__(master, width=size, height=size, bg=CARD, highlightthickness=0, **kw)
        self.size = size
        self.set(None)

    def set(self, score: int | None, label: str = "Saúde do PC"):
        self.delete("all")
        s, w = self.size, 12
        pad = w // 2 + 6
        color = score_color(score) if score is not None else BORDER
        # halo suave + trilha tingida com a cor da nota
        self.create_oval(pad - 5, pad - 5, s - pad + 5, s - pad + 5, outline=_blend(color, CARD, 0.08), width=2)
        self.create_oval(pad, pad, s - pad, s - pad, outline=_blend(color, CARD, 0.16), width=w)
        if score is None:
            self.create_text(s / 2, s / 2, text="…", fill=MUTED, font=(FONT, 28, "bold"))
            return
        self.create_arc(pad, pad, s - pad, s - pad, start=90, extent=-3.6 * max(score, 1), style="arc", outline=color, width=w)
        # pontas arredondadas do arco
        import math
        r = (s - 2 * pad) / 2
        for ang in (90, 90 - 3.6 * max(score, 1)):
            x = s / 2 + r * math.cos(math.radians(ang))
            y = s / 2 - r * math.sin(math.radians(ang))
            self.create_oval(x - w / 2, y - w / 2, x + w / 2, y + w / 2, fill=color, outline="")
        self.create_text(s / 2, s / 2 - 8, text=str(score), fill=TEXT, font=(FONT, 40, "bold"))
        self.create_text(s / 2, s / 2 + 28, text=label, fill=MUTED, font=(FONT, 10))


class Sparkline(tk.Canvas):
    """Gráfico de linha em tempo real (0–100%)."""

    def __init__(self, master, color=ACCENT, height=70, points=60, **kw):
        super().__init__(master, height=height, bg=CARD, highlightthickness=0, **kw)
        self.color = color
        self.values = [0.0] * points
        self.bind("<Configure>", lambda e: self.redraw())

    def push(self, v: float):
        self.values = self.values[1:] + [max(0.0, min(100.0, v))]
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        for frac in (0.25, 0.5, 0.75):
            y = h - frac * h
            self.create_line(0, y, w, y, fill=BORDER, dash=(2, 4))
        n = len(self.values)
        step = w / (n - 1)
        pts = []
        for i, v in enumerate(self.values):
            pts += [i * step, h - 2 - (v / 100) * (h - 4)]
        poly = [0, h] + pts + [w, h]
        self.create_polygon(poly, fill=_blend(self.color, CARD, 0.22), outline="")
        self.create_line(pts, fill=self.color, width=2, smooth=True)


class UsageBar(ctk.CTkFrame):
    """Barra de uso com rótulo (ex.: disco)."""

    def __init__(self, master, label: str, value: float, right_text: str = "", **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=label, font=font(12), text_color=TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(self, text=right_text, font=font(12), text_color=MUTED, anchor="e").grid(row=0, column=1, sticky="e")
        color = RED if value >= 0.9 else YELLOW if value >= 0.8 else ACCENT
        bar = ctk.CTkProgressBar(self, progress_color=color, fg_color=BORDER, height=8, corner_radius=4)
        bar.set(value)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 0))


def kv_rows(master, rows: list[tuple[str, str]], start_row: int = 0, padx=16):
    """Linhas chave/valor dentro de um Card."""
    frame = ctk.CTkFrame(master, fg_color="transparent")
    frame.grid(row=start_row, column=0, sticky="ew", padx=padx, pady=(0, 14))
    frame.grid_columnconfigure(1, weight=1)
    for i, (k, v) in enumerate(rows):
        ctk.CTkLabel(frame, text=k, font=font(12), text_color=MUTED, anchor="w").grid(row=i, column=0, sticky="nw", pady=2, padx=(0, 16))
        ctk.CTkLabel(frame, text=v if v not in (None, "") else "—", font=font(12, "bold"), text_color=TEXT, anchor="w",
                     justify="left", wraplength=520).grid(row=i, column=1, sticky="w", pady=2)
    return frame


def clear(frame):
    for w in frame.winfo_children():
        w.destroy()
