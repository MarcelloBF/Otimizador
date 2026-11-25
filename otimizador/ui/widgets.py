"""Tema e componentes visuais reutilizáveis."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

# ----------------------------------------------------------------- tema
BG = "#0e1117"
SIDEBAR = "#131722"
CARD = "#1a1f2b"
CARD_HOVER = "#212736"
BORDER = "#2a3142"
TEXT = "#e6e9ef"
MUTED = "#8b93a7"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#3b74e0"
GREEN = "#22c55e"
YELLOW = "#f5b014"
ORANGE = "#f97316"
RED = "#ef4444"
GRAY = "#64748b"

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


# ----------------------------------------------------------------- componentes


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str | None = None, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 12)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", BORDER)
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.body_row = 0
        if title:
            ctk.CTkLabel(self, text=title, font=font(15, "bold"), text_color=TEXT, anchor="w").grid(
                row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
            self.body_row = 1


class Badge(ctk.CTkLabel):
    def __init__(self, master, text: str, color: str, **kw):
        super().__init__(master, text=f" {text} ", fg_color=color, text_color="#0b0d12", corner_radius=6,
                         font=font(11, "bold"), height=20, **kw)


class PageHeader(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=font(24, "bold"), text_color=TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        self.sub = None
        if subtitle:
            self.sub = ctk.CTkLabel(self, text=subtitle, font=font(13), text_color=MUTED, anchor="w", justify="left",
                                    wraplength=620)
            self.sub.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.actions = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.actions.grid(row=0, column=1, rowspan=2, sticky="e")
        self.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, _event=None):
        """Quebra o subtítulo antes dos botões do cabeçalho, em qualquer largura de janela."""
        if self.sub is None:
            return
        scale = self._get_widget_scaling()
        free = (self.winfo_width() - self.actions.winfo_reqwidth()) / scale - 24
        wrap = int(max(320, min(720, free)))
        if wrap != self.sub.cget("wraplength"):
            self.sub.configure(wraplength=wrap)


def button(master, text, command, kind="primary", width=140, **kw):
    styles = {
        "primary": dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white"),
        "secondary": dict(fg_color=CARD_HOVER, hover_color=BORDER, text_color=TEXT, border_width=1, border_color=BORDER),
        "success": dict(fg_color="#16a34a", hover_color="#15803d", text_color="white"),
        "danger": dict(fg_color="#b91c1c", hover_color="#991b1b", text_color="white"),
    }
    return ctk.CTkButton(master, text=text, command=command, width=width, height=36, corner_radius=8,
                         font=font(13, "bold"), **styles[kind], **kw)


class ScoreRing(tk.Canvas):
    """Anel circular com a nota de saúde do PC."""

    def __init__(self, master, size=170, **kw):
        super().__init__(master, width=size, height=size, bg=CARD, highlightthickness=0, **kw)
        self.size = size
        self.set(None)

    def set(self, score: int | None, label: str = "Saúde do PC"):
        self.delete("all")
        s, w = self.size, 14
        pad = w // 2 + 4
        self.create_oval(pad, pad, s - pad, s - pad, outline=BORDER, width=w)
        if score is None:
            self.create_text(s / 2, s / 2, text="…", fill=MUTED, font=(FONT, 28, "bold"))
            return
        color = score_color(score)
        self.create_arc(pad, pad, s - pad, s - pad, start=90, extent=-3.6 * score, style="arc", outline=color, width=w)
        self.create_text(s / 2, s / 2 - 8, text=str(score), fill=TEXT, font=(FONT, 38, "bold"))
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


def _blend(c1: str, c2: str, a: float) -> str:
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (round(r1 * a + r2 * (1 - a)), round(g1 * a + g2 * (1 - a)), round(b1 * a + b2 * (1 - a)))


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
